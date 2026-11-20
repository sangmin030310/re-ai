"""pytest -q — tests local demo API, including persistence and document storage."""
from fastapi.testclient import TestClient
from app.main import app


def test_sample_and_health(monkeypatch, tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR', str(tmp_path))
    with TestClient(app) as c:
        assert c.get('/api/health').json()['mode'] == 'mock'
        projects = c.get('/api/projects').json()
        assert len(projects) == 1
        assert projects[0]['title'] == '폐플라스틱 재활용 검토'
        state = c.get(f"/api/projects/{projects[0]['id']}/analysis").json()
        assert state['missing_fields'] == ['contamination']
        assert state['routes'] == []


def test_conversation_route_document_and_export(monkeypatch, tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REAI_SEED_SAMPLE', '0')
    with TestClient(app) as c:
        project_response = c.post('/api/projects', json={'title': '검토 1'})
        assert project_response.status_code == 201
        pid = project_response.json()['id']
        r1 = c.post(f'/api/projects/{pid}/messages', json={'content': 'PP 폐플라스틱 월 3톤 발생'})
        assert r1.status_code == 200
        assert r1.json()['analysis']['missing_fields'] == ['contamination']
        r2 = c.post(f'/api/projects/{pid}/messages', json={'content': '오염 없음'})
        assert r2.status_code == 200
        assert len(r2.json()['analysis']['routes']) == 3
        assert len(c.get(f'/api/projects/{pid}/messages').json()) == 4
        chosen = c.post(f'/api/projects/{pid}/select-route', json={'route_id': 'pretreat'})
        assert chosen.status_code == 200
        assert chosen.json()['analysis']['selected_route'] == 'pretreat'

        file = c.post(f'/api/projects/{pid}/documents', files={'file': ('성상_분석표.pdf', b'%PDF-test', 'application/pdf')})
        assert file.status_code == 201
        doc_id = file.json()['id']
        listed = c.get('/api/documents', params={'project_id': pid}).json()
        assert len(listed) == 1 and listed[0]['name'] == '성상_분석표.pdf'
        response = c.get(f'/api/documents/{doc_id}/download')
        assert response.status_code == 200 and response.content == b'%PDF-test'
        exported = c.get(f'/api/projects/{pid}/export').json()
        assert len(exported['messages']) == 4
        assert len(exported['documents']) == 1
        assert c.delete(f'/api/documents/{doc_id}').status_code == 200
        assert c.get('/api/documents', params={'project_id': pid}).json() == []
        assert c.patch(f'/api/projects/{pid}', json={'title': '검토 2'}).json()['title'] == '검토 2'
        assert c.delete(f'/api/projects/{pid}').status_code == 200
        assert c.get(f'/api/projects/{pid}').status_code == 404


def test_invalid_route_and_invalid_document(monkeypatch, tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REAI_SEED_SAMPLE', '0')
    with TestClient(app) as c:
        pid = c.post('/api/projects', json={'title': '안전 확인'}).json()['id']
        assert c.post(f'/api/projects/{pid}/select-route', json={'route_id': 'direct'}).status_code == 400
        assert c.post(f'/api/projects/{pid}/documents',files={'file':('bad.exe',b'exe','application/octet-stream')}).status_code == 400
        assert c.post(f'/api/projects/{pid}/messages',json={'content':'   '}).status_code == 422


def test_demo_greeting_responds_naturally(monkeypatch, tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REAI_SEED_SAMPLE', '0')
    with TestClient(app) as c:
        pid = c.post('/api/projects', json={'title': '인사 테스트'}).json()['id']
        resp = c.post(f'/api/projects/{pid}/messages', json={'content': '안녕?'})
        assert resp.status_code == 200
        assert '안녕하세요' in resp.json()['agent_reply']['message']
        assert resp.json()['analysis']['missing_fields'] == ['material','monthly_ton','contamination']


def test_optional_chat_adapter_preserves_history_without_network(monkeypatch):
    from types import SimpleNamespace
    from app.agents.openai_gateway import OpenAIChatGateway

    calls = []
    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text='안녕하세요! 무엇을 도와드릴까요?')
    gateway = OpenAIChatGateway.__new__(OpenAIChatGateway)
    gateway.client = SimpleNamespace(responses=FakeResponses())
    gateway.model = 'gpt-6-luna'
    answer = gateway.reply(
        message='안녕',
        profile={'material': 'PP'},
        history=[{'role': 'user', 'content': '처음 질문'}, {'role': 'assistant', 'content': '처음 답변'}],
    )
    assert answer.agent == 'openai_chat'
    assert '안녕하세요' in answer.message
    assert len(calls[0]['input']) == 3
    assert calls[0]['store'] is False


def test_openai_request_draft_uses_structured_reply(monkeypatch, tmp_path):
    from importlib import import_module
    from types import SimpleNamespace

    from app.agents.openai_gateway import OpenAIChatGateway
    from app.request_chat import IntakeTurn

    main = import_module("app.main")
    monkeypatch.setenv("REAI_ENV", "development")
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "0")
    monkeypatch.setenv("REAI_SEED_SAMPLE", "0")
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_CHAT_PROVIDER", "openai")

    calls = []
    answers = iter([
        IntakeTurn.model_validate({"reply": "전주 공장으로 적었어요. 오염 상태를 확인해 볼까요?", "updates": {"region": "전주", "material": "PP", "monthly_ton": 3}}),
        IntakeTurn.model_validate({"reply": "오염은 확인 필요, 포장은 톤백으로 적었어요.", "updates": {"contamination": "확인 필요", "packaging": "톤백"}}),
    ])

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=next(answers))

    gateway = OpenAIChatGateway.__new__(OpenAIChatGateway)
    gateway.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    gateway.model = "gpt-6-luna"
    monkeypatch.setattr(main, "configured_mode", "openai")
    monkeypatch.setattr(main, "agent_gateway", gateway)

    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"title": "GPT로 요청서 작성"}).json()["id"]
        messages = f"/api/projects/{pid}/messages"
        for message in ("전주에서 PP가 월 3톤 나와요. 오염은 어떻게 확인해요?", "그건 나중에 볼게요. 톤백에 넣어뒀어요."):
            result = client.post(messages, json={"content": message, "intake": True})
            assert result.status_code == 200
            assert result.json()["agent_reply"]["agent"] == "openai_request_draft"
        profile = result.json()["project"]["profile"]
        assert profile == {"region": "전주", "material": "PP", "monthly_ton": 3, "contamination": "확인 필요", "packaging": "톤백"}
        assert calls[1]["text_format"] is IntakeTurn
        assert calls[1]["store"] is False
        assert calls[1]["reasoning"] == {"effort": "none"}
        assert len(calls[1]["input"]) == 3
        form = f"/api/matching/requests/{pid}"
        assert client.put(form, json=profile).status_code == 200
        assert any(company["id"] == "demo-b" for company in client.get(f"{form}/companies").json())
