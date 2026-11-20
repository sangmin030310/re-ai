from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


REQUEST = {"material": "PP", "monthly_ton": 2, "region": "전주",
           "contamination": "오염 없음", "packaging": "톤백"}


def test_request_save_adds_one_downloadable_word_document(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_SEED_SAMPLE", "0")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "전주 PP"}).json()["id"]
        path = f"/api/matching/requests/{project}"
        assert client.put(path, json=REQUEST).status_code == 200
        first, = client.get("/api/documents").json()
        assert (first["source"], first["project_title"]) == ("request", "전주 PP")

        assert client.put(path, json=REQUEST).status_code == 200
        assert client.get("/api/documents").json() == [first]
        assert client.put(path, json={**REQUEST, "monthly_ton": 5}).status_code == 200
        updated, = client.get("/api/documents").json()
        assert updated["id"] == first["id"]
        downloaded = client.get(f"/api/documents/{first['id']}/download")
        assert downloaded.status_code == 200
        assert Document(BytesIO(downloaded.content)).tables[0].cell(1, 1).text == "5톤"

        assert client.delete(f"/api/projects/{project}").status_code == 200
        assert client.get("/api/documents").json() == []


def test_document_commands_keep_workspace_boundaries_and_request_data(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_SEED_SAMPLE", "0")
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "1")
    with TestClient(app) as client:
        supplier = {"X-Reai-Demo-Org": "demo-a"}
        other = {"X-Reai-Demo-Org": "local"}
        project = client.post("/api/projects", headers=supplier, json={"title": "요청서 A"}).json()["id"]
        chat = f"/api/projects/{project}/messages"
        save = {"content": "이 요청서를 문서함에 넣어줘", "request_draft": REQUEST}
        missing = client.post(chat, headers=supplier, json={"content": save["content"]}).json()
        assert missing["document_command"] == {"changed": False}

        saved = client.post(chat, headers=supplier, json=save).json()
        assert saved["document_command"]["saved_request"]["material"] == "PP"
        doc, = client.get("/api/documents", headers=supplier).json()
        assert client.get("/api/documents", headers=other).json() == []
        assert client.get(f"/api/documents/{doc['id']}/download", headers=other).status_code == 404
        assert client.post(chat, headers=other, json=save).status_code == 404

        opened = client.post(chat, headers=supplier, json={"content": "문서 보관함 보여줘"}).json()
        assert opened["document_command"]["open_archive"]
        delete = "이 문서를 보관함에서 삭제해줘"
        choice = client.post(chat, headers=supplier, json={"content": delete}).json()
        action, = choice["messages"][-1]["actions"]
        assert action["value"] == doc["id"]
        assert not choice["document_command"]["changed"]
        deleted = client.post(chat, headers=supplier, json={"content": delete, "document_selection": action["value"]}).json()
        assert deleted["document_command"]["changed"]
        assert client.get("/api/documents", headers=supplier).json() == []
        assert client.get(f"/api/matching/requests/{project}", headers=supplier).json()["request"]["material"] == "PP"

        # The previously saved request can be archived again after the copy is removed.
        saved_again = client.post(chat, headers=supplier, json={"content": save["content"]}).json()
        assert saved_again["document_command"]["changed"]
