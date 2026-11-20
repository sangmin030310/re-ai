import io
import json
from types import SimpleNamespace


def test_ollama_gateway_request_and_history(monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL','http://127.0.0.1:11434')
    monkeypatch.setenv('OLLAMA_MODEL','qwen3.5:9b')
    from app.agents import ollama_gateway
    seen = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return json.dumps({'message':{'content':'안녕하세요! 무엇을 도와드릴까요?'}}).encode()
    def fake_urlopen(request, timeout):
        seen['url'] = request.full_url
        seen['payload'] = json.loads(request.data)
        seen['timeout'] = timeout
        return FakeResponse()
    monkeypatch.setattr(ollama_gateway, 'urlopen', fake_urlopen)
    gateway=ollama_gateway.OllamaChatGateway()
    response=gateway.reply(message='안녕', profile={'material':'PP'}, history=[{'role':'user','content':'전 대화'}])
    assert seen['url'] == 'http://127.0.0.1:11434/api/chat'
    assert seen['payload']['model'] == 'qwen3.5:9b'
    assert seen['payload']['stream'] is False
    assert [m['role'] for m in seen['payload']['messages']] == ['system','user','user']
    assert '안녕하세요' in response.message
    assert response.agent=='ollama_chat'
    assert response.data['verified'] is False


def test_ollama_url_disallows_remote_provider(monkeypatch):
    import pytest
    from app.agents.ollama_gateway import OllamaChatGateway
    monkeypatch.setenv('OLLAMA_BASE_URL','https://somewhere.example')
    with pytest.raises(ValueError):
        OllamaChatGateway()
