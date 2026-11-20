"""Developer workspace separation checks.

WARNING: X-Reai-Demo-Org is NOT authenticated. These tests verify only query scoping.
"""
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_dev_workspaces_separate_all_entities(monkeypatch, tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REAI_SEED_SAMPLE', '0')
    monkeypatch.setenv('REAI_DEMO_MULTI_TENANT', '1')
    a = {'X-Reai-Demo-Org': 'demo-a'}
    b = {'X-Reai-Demo-Org': 'demo-b'}
    with TestClient(app) as client:
        assert client.get('/api/health').json()['demo_workspaces'] is True
        p = client.post('/api/projects', json={'title': 'A사 비공개 검토'}, headers=a).json()
        pid = p['id']
        assert p['organization_id'] == 'demo-a'
        assert client.get('/api/projects', headers=b).json() == []
        assert client.get(f'/api/projects/{pid}', headers=b).status_code == 404
        assert client.patch(f'/api/projects/{pid}',json={'title':'침해'},headers=b).status_code == 404
        assert client.delete(f'/api/projects/{pid}', headers=b).status_code == 404
        assert client.get(f'/api/projects/{pid}/analysis',headers=b).status_code == 404
        assert client.get(f'/api/projects/{pid}/messages',headers=b).status_code == 404
        assert client.post(f'/api/projects/{pid}/messages',json={'content':'안녕하세요'},headers=b).status_code == 404
        assert client.post(f'/api/projects/{pid}/select-route',json={'route_id':'direct'},headers=b).status_code == 404
        assert client.get(f'/api/projects/{pid}/export',headers=b).status_code == 404
        f = client.post(f'/api/projects/{pid}/documents', files={'file':('plan.pdf',b'%PDF-safe','application/pdf')},headers=a)
        assert f.status_code == 201
        did = f.json()['id']
        assert client.get('/api/documents',headers=b).json() == []
        assert client.get('/api/documents',params={'project_id':pid},headers=b).status_code == 404
        assert client.get(f'/api/documents/{did}/download',headers=b).status_code == 404
        assert client.delete(f'/api/documents/{did}',headers=b).status_code == 404
        assert client.get(f'/api/documents/{did}/download',headers=a).content == b'%PDF-safe'
        assert client.get(f'/api/projects/{pid}',headers=a).status_code == 200
        assert client.get('/api/projects',headers=a).json()[0]['title'] == 'A사 비공개 검토'


def test_migrate_previous_sqlite_without_data_loss(monkeypatch,tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('REAI_SEED_SAMPLE','0')
    monkeypatch.delenv('REAI_DEMO_MULTI_TENANT',raising=False)
    db=sqlite3.connect(tmp_path/'reai.sqlite3')
    db.execute('CREATE TABLE projects (id TEXT PRIMARY KEY,title TEXT NOT NULL,profile TEXT NOT NULL DEFAULT "{}",selected_route TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
    db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',('legacy','이전 기록','{}',None,'2026-01-01','2026-01-01'))
    db.commit(); db.close()
    with TestClient(app) as client:
        p=client.get('/api/projects').json()[0]
        assert p['id']=='legacy' and p['organization_id']=='local'


def test_public_startup_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setenv('REAI_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('REAI_ENV','production')
    with pytest.raises(RuntimeError, match='local-development only'):
        with TestClient(app):
            pass
