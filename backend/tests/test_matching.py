from io import BytesIO
from uuid import uuid4

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


def test_request_matching_and_two_company_inbox(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_SEED_SAMPLE", "0")
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "1")
    sender = {"X-Reai-Demo-Org": "demo-a"}
    receiver = {"X-Reai-Demo-Org": "demo-b"}
    other = {"X-Reai-Demo-Org": "demo-c"}
    request = {
        "material": "PP", "monthly_ton": 3, "region": "전주",
        "contamination": "오염 없음", "packaging": "톤백", "notes": "수거 일정 확인",
    }
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "PP 시연"}, headers=sender).json()["id"]
        form = f"/api/matching/requests/{project}"
        collection = "/api/matching/inquiries"
        assert client.get(f"{form}/companies", headers=sender).status_code == 409
        assert client.put(form, json=request, headers=sender).status_code == 200
        options = client.get(f"{form}/companies", headers=sender).json()
        assert {company["id"] for company in options} == {"demo-b", "demo-c", "demo-d", "demo-e", "demo-f", "demo-g", "demo-h"}
        assert all(company["inquiry_available"] for company in options)
        assert client.get(form, headers=receiver).status_code == 403
        selection = {"company_id": "demo-b", "request": request}
        assert client.put(f"{form}/selection", json=selection, headers=receiver).status_code == 403
        assert client.put(f"{form}/selection", json={**selection, "company_id": "local"}, headers=sender).status_code == 422
        assert client.put(f"{form}/selection", json=selection, headers=sender).json()["selected_company_id"] == "demo-b"
        assert client.get(form, headers=sender).json()["selected_company_id"] == "demo-b"
        assert client.get(collection, headers=receiver).json() == []
        body = {
            "project_id": project, "recipient_id": "demo-b", "content": "자료 확인 부탁드립니다.", "request": request,
        }
        assert client.post(collection, json={**body, "recipient_id": "local"}, headers=sender).status_code == 422
        assert client.post(collection, json={**body, "recipient_id": "demo-c"}, headers=sender).status_code == 409
        assert client.get(collection, headers=receiver).json() == []
        sent = client.post(collection, json=body, headers=sender)
        assert sent.status_code == 200
        assert client.post(collection, json=body, headers=sender).json() == sent.json()
        path = f"{collection}/{sent.json()['id']}"
        assert client.get(collection, headers=other).json() == []
        assert client.get(path, headers=other).status_code == 404
        assert client.get(f"{path}/attachment", headers=other).status_code == 404
        assert client.put(form, json={**request, "monthly_ton": 8}, headers=sender).status_code == 200
        options = client.get(f"{form}/companies", headers=sender).json()
        assert {company["id"] for company in options} == {"demo-d", "demo-h"}
        assert client.get(form, headers=sender).json()["selected_company_id"] is None
        assert client.put(f"{form}/selection", json=selection, headers=sender).status_code == 409
        assert client.post(collection, json={**body, "recipient_id": "demo-c"}, headers=sender).status_code == 409
        attachment = client.get(f"{path}/attachment", headers=receiver)
        assert attachment.status_code == 200
        assert Document(BytesIO(attachment.content)).tables[0].cell(1, 1).text == "3톤"
        reply = {"content": "성상 분석표를 보내주세요.", "client_id": str(uuid4())}
        assert client.post(f"{path}/messages", json=reply, headers=other).status_code == 404
        for _ in range(2):
            assert client.post(f"{path}/messages", json=reply, headers=receiver).status_code == 201
        assert [m["content"] for m in client.get(path, headers=sender).json()["messages"]] == [body["content"], reply["content"]]


def test_online_invites_ignore_demo_header_and_allow_seoul_match(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_ENV", "online-demo")
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "1")
    supplier_code, recycler_code = ("a" * 32), ("b" * 32)
    monkeypatch.setenv("REAI_SUPPLIER_INVITE", supplier_code)
    monkeypatch.setenv("REAI_RECYCLER_INVITE", recycler_code)
    supplier = {"Authorization": f"Bearer {supplier_code}", "X-Reai-Demo-Org": "demo-e"}
    recycler = {"Authorization": f"Bearer {recycler_code}", "X-Reai-Demo-Org": "demo-a"}
    with TestClient(app) as client:
        assert client.get("/api/health").json()["online_demo"]
        assert client.get("/api/projects", headers={"X-Reai-Demo-Org": "demo-a"}).status_code == 401
        assert client.get("/api/session", headers=supplier).json()["id"] == "demo-a"
        assert client.get("/api/session", headers=recycler).json()["id"] == "demo-e"
        project = client.post("/api/projects", json={"title": "PP 요청서"}, headers=supplier).json()["id"]
        assert client.get(f"/api/projects/{project}", headers=recycler).status_code == 404
        message_url = f"/api/projects/{project}/messages"
        message = {"content": "PP 폐플라스틱이 월 3톤 발생해. 요청서 작성 도와줘.", "intake": True}
        chat = client.post(message_url, json=message, headers=supplier).json()
        assert "배출 지역" in chat["messages"][-1]["content"]
        chat = client.post(message_url, json={"content": "전주야", "intake": True}, headers=supplier).json()
        assert chat["project"]["profile"]["region"] == "전주"
        assert "오염 상태" in chat["messages"][-1]["content"]
        chat = client.post(message_url, json={"content": "이건 잘 모르겠어요", "intake": True}, headers=supplier).json()
        assert "기름, 물기" in chat["messages"][-1]["content"]
        assert not chat["project"]["profile"].get("contamination")
        chat = client.post(message_url, json={"content": "오염 없는 건지 모르겠어요", "intake": True}, headers=supplier).json()
        assert not chat["project"]["profile"].get("contamination")
        chat = client.post(message_url, json={"content": "나중에 확인할게요", "intake": True}, headers=supplier).json()
        assert chat["project"]["profile"]["contamination"] == "확인 필요"
        assert "포장 상태" in chat["messages"][-1]["content"]
        chat = client.post(message_url, json={"content": "포장 상태가 뭐예요?", "intake": True}, headers=supplier).json()
        assert "어디에 담겨 있거나" in chat["messages"][-1]["content"]
        assert not chat["project"]["profile"].get("packaging")
        chat = client.post(message_url, json={"content": "오염 없어요", "intake": True}, headers=supplier).json()
        assert chat["project"]["profile"]["contamination"] == "오염 없음(사용자 진술)"
        chat = client.post(message_url, json={"content": "톤백에 담아요", "intake": True}, headers=supplier).json()
        profile = chat["project"]["profile"]
        assert profile["region"] == "전주"
        assert profile["packaging"] == "톤백 포장"
        assert "추천 업체 보기" in chat["messages"][-1]["content"]
        correction = client.post(message_url, json={"content": "월 4,500kg으로 수정해 주세요", "intake": True}, headers=supplier).json()
        profile = correction["project"]["profile"]
        assert profile["monthly_ton"] == 4.5
        assert profile["material"] == "PP"
        assert profile["contamination"] == "오염 없음(사용자 진술)"
        form = f"/api/matching/requests/{project}"
        saved = client.put(form, json=profile, headers=supplier).json()
        companies = client.get(f"{form}/companies", headers=supplier).json()
        assert {company["id"] for company in companies} == {"demo-b", "demo-d", "demo-e", "demo-f", "demo-h"}
        assert [(c["id"], c["city"]) for c in companies if c["inquiry_available"]] == [("demo-e", "서울")]
        assert client.put(f"{form}/selection", json={"company_id": "demo-f", "request": saved}, headers=supplier).status_code == 422
        assert client.put(f"{form}/selection", json={"company_id": "demo-e", "request": saved}, headers=supplier).status_code == 200
        collection = "/api/matching/inquiries"
        sent = client.post(collection, json={"project_id": project, "recipient_id": "demo-e", "content": "수거 문의", "request": saved}, headers=supplier)
        assert sent.status_code == 200
        inquiry_id = sent.json()["id"]
        assert client.get(collection, headers=recycler).json()[0]["id"] == inquiry_id
        reply = {"content": "전주 방문 수거 가능 일정을 확인하겠습니다.", "client_id": str(uuid4())}
        assert client.post(f"{collection}/{inquiry_id}/messages", json=reply, headers=recycler).status_code == 201
        assert client.get(f"{collection}/{inquiry_id}", headers=supplier).json()["messages"][-1]["content"] == reply["content"]


def test_default_workspace_can_write_request(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_ENV", "development")
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "0")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "내 요청서"}).json()["id"]
        messages = f"/api/projects/{project}/messages"
        help_reply = client.post(messages, json={"content": "재질 확인 필요로 두면 안 돼?", "intake": True}).json()
        assert "원자재 명세서" in help_reply["messages"][-1]["content"]
        assert not help_reply["project"]["profile"].get("material")
        mixed = client.post(messages, json={
            "content": "전주에서 PP가 월 3톤인데 오염은 잘 모르겠어요.", "intake": True,
        }).json()
        assert mixed["project"]["profile"]["monthly_ton"] == 3
        assert not mixed["project"]["profile"].get("contamination")
        assert mixed["messages"][-1]["actions"][0]["label"] == "나중에 확인하기"
        request = {"material": "PP", "monthly_ton": 3, "region": "전주", "contamination": "오염 없음", "packaging": "톤백"}
        assert client.put(f"/api/matching/requests/{project}", json=request).status_code == 200
        form = f"/api/matching/requests/{project}"
        for material, companies in [("철/금속", {"demo-d", "demo-i"}), ("폐지", {"demo-j"}), ("기타", set())]:
            assert client.put(form, json={**request, "material": material}).status_code == 200
            options = client.get(f"{form}/companies").json()
            assert {company["id"] for company in options} == companies
