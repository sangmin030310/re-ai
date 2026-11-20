"""End-to-end tests for deals, transport quotes, demand posts and trust badges (account mode)."""
import hashlib
import json
import secrets
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents import matching_agents
from app.db import connect
from app.main import app

ORIGIN = {"Origin": "https://testserver"}
REQUEST = {
    "material": "PP", "monthly_ton": 2, "region": "전북 전주시 덕진구",
    "contamination": "오염 없음", "packaging": "톤백", "notes": "",
    "legal_status": "확인 전", "waste_code": "", "frequency": "매월 정기",
    "address": "전주시 덕진구 산업로 1", "price_preference": "매각 희망", "attachment_ids": [],
}


def make_account(role, name, username, profile=None):
    account_id = f"company-{uuid4()}"
    token = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute(
            """INSERT INTO company_accounts(id, username, company_name, role, salt, password_hash, recycler_profile)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (account_id, username, name, role, b"0" * 16, b"0" * 32, json.dumps(profile, ensure_ascii=False) if profile else None),
        )
        db.execute(
            "INSERT INTO company_sessions(token_hash, account_id, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode()).digest(), account_id, 4102444800),
        )
    return account_id, {"Cookie": f"reai_company_session={token}", **ORIGIN}


@pytest.fixture
def market(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_ENV", "online-demo")
    monkeypatch.setenv("REAI_ACCOUNT_LOGIN", "1")
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_OPERATOR_USERNAMES", "operator")
    matching_agents.reset_agent()
    with TestClient(app) as client:
        supplier_id, supplier = make_account("supplier", "한빛부품", "hanbit")
        recycler_id, recycler = make_account("recycler", "전주순환", "jeonju", {
            "city": "전주", "regions": ["전주", "완주"], "materials": ["PP", "PE"], "max_ton": 5, "transport": "업체 수거",
        })
        far_id, far = make_account("recycler", "익산리사이클", "iksan", {
            "city": "익산", "regions": ["전주", "익산"], "materials": ["PP"], "max_ton": 5, "transport": "배출업체 직접 운반",
        })
        carrier_id, carrier = make_account("carrier", "빠른운송", "fast", {
            "city": "전주", "regions": ["전주", "익산"], "materials": ["PP"], "max_ton": 10,
        })
        carrier2_id, carrier2 = make_account("carrier", "든든물류", "dd", {
            "city": "완주", "regions": ["전주", "완주", "익산"], "materials": ["PP", "PE"], "max_ton": 10,
        })
        _, operator = make_account("supplier", "운영팀", "operator")
        yield client, {
            "supplier": (supplier_id, supplier), "recycler": (recycler_id, recycler), "far": (far_id, far),
            "carrier": (carrier_id, carrier), "carrier2": (carrier2_id, carrier2), "operator": (None, operator),
        }


def saved_project(client, supplier):
    project = client.post("/api/projects", json={"title": "PP"}, headers=supplier).json()["id"]
    upload = client.post(f"/api/projects/{project}/documents", headers=supplier,
                         files={"file": ("사진.png", b"\x89PNG demo", "image/png")})
    assert upload.status_code == 201
    request = {**REQUEST, "attachment_ids": [upload.json()["id"]]}
    assert client.put(f"/api/matching/requests/{project}", json=request, headers=supplier).status_code == 200
    return project, request


def test_trust_badge_requires_operator_and_resets_on_edit(market):
    client, who = market
    recycler_id, recycler = who["recycler"]
    _, operator = who["operator"]
    assert client.get("/api/session", headers=operator).json()["operator"] is True
    assert client.get("/api/session", headers=recycler).json()["operator"] is False
    details = {"permit_type": "폐기물 중간재활용업", "permit_number": "전북-2025-01", "permit_valid_until": "2099-12-31",
               "business_number": "123-45-67890", "address": "전주", "price_model": "매입"}
    assert client.put("/api/accounts/trust", json=details, headers=recycler).status_code == 200
    path = f"/api/operator/companies/{recycler_id}/verification"
    assert client.put(path, json={"verified": True}, headers=recycler).status_code == 403
    assert client.put(path, json={"verified": True, "note": "허가증 사본 확인"}, headers=operator).json()["permit_verified"]
    assert client.get("/api/accounts/trust", headers=recycler).json()["trust"]["permit_verified"]
    changed = client.put("/api/accounts/trust", json={**details, "permit_number": "전북-2025-02"}, headers=recycler)
    assert changed.json()["trust"]["permit_verified"] is False
    unchanged = client.put("/api/accounts/trust", json={**details, "permit_number": "전북-2025-02", "address": "완주"},
                           headers=recycler)
    assert unchanged.json()["trust"]["permit_verified"] is False


def test_batch_inquiry_quotes_comparison_and_attachments(market):
    client, who = market
    supplier_id, supplier = who["supplier"]
    recycler_id, recycler = who["recycler"]
    far_id, far = who["far"]
    project, request = saved_project(client, supplier)
    companies = client.get(f"/api/matching/requests/{project}/companies", headers=supplier).json()
    registered = {company["id"]: company for company in companies if company["registered"]}
    assert set(registered) == {recycler_id, far_id}, "'전북 전주시 덕진구' must match companies serving 전주"
    assert registered[recycler_id]["distance_km"] < registered[far_id]["distance_km"]
    assert registered[recycler_id]["agent"]["score"] is not None
    assert "permit_verified" in registered[recycler_id]["trust"]
    review = client.get(f"/api/matching/requests/{project}/review", headers=supplier).json()
    assert review["legal_status"] is None and review["unverified"]

    batch = client.post("/api/matching/inquiries/batch", headers=supplier, json={
        "project_id": project, "recipient_ids": [recycler_id, far_id, "demo-b"], "content": "견적 부탁드립니다.",
        "request": request,
    }).json()
    assert {item["recipient_id"] for item in batch["created"]} == {recycler_id, far_id}
    assert batch["skipped"][0]["recipient_id"] == "demo-b"
    again = client.post("/api/matching/inquiries/batch", headers=supplier, json={
        "project_id": project, "recipient_ids": [recycler_id], "content": "다시", "request": request,
    }).json()
    assert again["created"] == [] and again["skipped"][0]["reason"] == "이미 문의한 업체입니다."

    inquiry = next(item["id"] for item in batch["created"] if item["recipient_id"] == recycler_id)
    thread = client.get(f"/api/matching/inquiries/{inquiry}", headers=recycler).json()
    attachment = thread["attachments"][0]
    assert client.get(f"/api/matching/inquiries/{inquiry}/files/{attachment['id']}", headers=recycler).content == b"\x89PNG demo"
    assert client.get(f"/api/matching/inquiries/{inquiry}/files/{attachment['id']}", headers=far).status_code == 404

    quote = {"status": "accepted", "reason": "샘플 확인 후 반입 가능", "price_type": "매입", "unit_price": 120000,
             "available_from": "2026-12-01"}
    assert client.put(f"/api/matching/inquiries/{inquiry}/review", json=quote, headers=recycler).json()["quote"]["unit_price"] == 120000
    far_inquiry = next(item["id"] for item in batch["created"] if item["recipient_id"] == far_id)
    client.put(f"/api/matching/inquiries/{far_inquiry}/review", json={"status": "declined", "reason": "물량 부족"}, headers=far)
    responses = client.get(f"/api/matching/requests/{project}/responses", headers=supplier).json()
    by_company = {item["company_id"]: item for item in responses}
    assert by_company[recycler_id]["quote"]["price_type"] == "매입"
    assert by_company[far_id]["review"]["status"] == "declined"
    assert client.post("/api/deals", json={"inquiry_id": far_inquiry}, headers=supplier).status_code == 409


def test_full_deal_flow_with_transport_quotes(market):
    client, who = market
    supplier_id, supplier = who["supplier"]
    recycler_id, recycler = who["recycler"]
    carrier_id, carrier = who["carrier"]
    carrier2_id, carrier2 = who["carrier2"]
    _, far = who["far"]
    project, request = saved_project(client, supplier)
    inquiry = client.post("/api/matching/inquiries/batch", headers=supplier, json={
        "project_id": project, "recipient_ids": [recycler_id], "content": "문의", "request": request,
    }).json()["created"][0]["id"]
    client.put(f"/api/matching/inquiries/{inquiry}/review", headers=recycler,
               json={"status": "accepted", "reason": "가능", "price_type": "매입", "unit_price": 100000})

    deal = client.post("/api/deals", json={"inquiry_id": inquiry}, headers=recycler)
    assert deal.status_code == 201
    deal = deal.json()
    deal_id = deal["id"]
    assert deal["status"] == "negotiating"
    assert deal["suggested_terms"]["price_type"] == "매입" and deal["suggested_terms"]["unit_price"] == 100000
    assert deal["shipment"]["pickup_address"] == REQUEST["address"]
    assert client.post("/api/deals", json={"inquiry_id": inquiry}, headers=supplier).json()["id"] == deal_id
    assert client.get(f"/api/deals/{deal_id}", headers=far).status_code == 404
    assert client.get(f"/api/matching/inquiries/{inquiry}", headers=supplier).json()["deal_id"] == deal_id

    path = f"/api/deals/{deal_id}"
    terms = {"price_type": "매입", "unit_price": 110000, "quantity_ton": 2, "frequency": "매월 정기",
             "start_date": "2026-12-01", "transport_by": "supplier"}
    assert client.put(f"{path}/terms", json={**terms, "unit_price": None}, headers=supplier).status_code == 422
    proposed = client.put(f"{path}/terms", json=terms, headers=supplier).json()
    assert proposed["next_action"]["mine"] is False
    assert client.get(path, headers=recycler).json()["next_action"]["mine"] is True
    assert client.post(f"{path}/terms/accept", headers=supplier).status_code == 409
    agreed = client.post(f"{path}/terms/accept", headers=recycler).json()
    assert agreed["status"] == "agreed"
    assert any(item["key"] == "transport_permit" for item in agreed["checklist"])

    assert client.get(f"{path}/carriers", headers=recycler).status_code == 403
    carriers = client.get(f"{path}/carriers", headers=supplier).json()
    assert {item["id"] for item in carriers} == {carrier_id, carrier2_id}
    pending = client.post(f"{path}/transport-requests", headers=supplier,
                          json={"carrier_ids": [carrier_id, carrier2_id], "note": "다음 주 상차"}).json()
    assert pending["status"] == "transport_pending"

    carrier_view = client.get(path, headers=carrier).json()
    assert carrier_view["my_role"] == "carrier_candidate"
    assert "unit_price" not in carrier_view["terms"] and "notes" not in carrier_view["request"]
    assert carrier_view["next_action"]["mine"] is True
    assert len(carrier_view["transport_requests"]) == 1
    assert client.post(f"{path}/messages", headers=carrier,
                       json={"content": "질문", "client_id": str(uuid4())}).status_code == 403
    assert any(item["id"] == deal_id for item in client.get("/api/deals", headers=carrier).json())

    assert client.put(f"{path}/transport-requests/mine", headers=carrier, json={"action": "quote"}).status_code == 422
    client.put(f"{path}/transport-requests/mine", headers=carrier,
               json={"action": "quote", "price": 180000, "available_date": "2026-12-02", "vehicle": "5톤 카고"})
    client.put(f"{path}/transport-requests/mine", headers=carrier2,
               json={"action": "quote", "price": 150000, "available_date": "2026-12-03", "vehicle": "5톤 윙바디"})
    quotes = client.get(path, headers=supplier).json()["transport_requests"]
    assert len(quotes) == 2
    cheaper = next(item for item in quotes if item["carrier_id"] == carrier2_id)
    assert client.post(f"{path}/transport-requests/{cheaper['id']}/select", headers=recycler).status_code == 403
    scheduled = client.post(f"{path}/transport-requests/{cheaper['id']}/select", headers=supplier).json()
    assert scheduled["status"] == "scheduled" and scheduled["parties"]["carrier"]["id"] == carrier2_id
    assert scheduled["shipment"]["vehicle"] == "5톤 윙바디"
    assert client.get(path, headers=carrier).status_code == 404 or \
        client.get(path, headers=carrier).json()["my_role"] == "carrier_candidate"
    assert all(item["id"] != deal_id for item in client.get("/api/deals", headers=carrier).json())

    assert client.put(f"{path}/shipment", headers=carrier2, json={"driver_contact": "010-0000-0000"}).status_code == 200
    assert client.put(f"{path}/shipment", headers=carrier2, json={"unknown": "x"}).status_code == 422
    for headers in (supplier, recycler, carrier2):
        assert client.post(f"{path}/messages", headers=headers,
                           json={"content": "상차 10시 확인", "client_id": str(uuid4())}).status_code == 201
    assert len(client.get(path, headers=supplier).json()["messages"]) == 3

    assert client.post(f"{path}/progress", headers=supplier, json={"step": "picked_up"}).status_code == 403
    assert client.post(f"{path}/progress", headers=carrier2, json={"step": "picked_up", "actual_ton": 2}).json()["status"] == "picked_up"
    assert client.post(f"{path}/progress", headers=recycler, json={"step": "delivered"}).status_code == 422
    delivered = client.post(f"{path}/progress", headers=recycler, json={"step": "delivered", "actual_ton": 1.96}).json()
    assert delivered["shipment"]["delivered_ton"] == 1.96
    blocked = client.post(f"{path}/progress", headers=supplier, json={"step": "completed"})
    assert blocked.status_code == 409 and "남은 서류" in blocked.json()["detail"]

    upload = client.post(f"{path}/files", headers=recycler, data={"key": "weighing"},
                         files={"file": ("계량증명서.pdf", b"%PDF demo", "application/pdf")})
    assert upload.status_code == 201
    file_id = next(item for item in upload.json()["checklist"] if item["key"] == "weighing")["files"][0]["id"]
    assert client.get(f"{path}/files/{file_id}", headers=supplier).content == b"%PDF demo"
    assert client.get(f"{path}/files/{file_id}", headers=far).status_code == 404
    for item in client.get(path, headers=supplier).json()["checklist"]:
        if item["state"] == "pending":
            assert client.put(f"{path}/checklist/{item['key']}", headers=supplier,
                              json={"state": "done", "note": "올바로 등록"}).status_code == 200
    completed = client.post(f"{path}/progress", headers=supplier, json={"step": "completed"}).json()
    assert completed["status"] == "completed"
    kinds = [event["kind"] for event in completed["events"]]
    assert kinds[:4] == ["created", "terms_proposed", "terms_agreed", "transport_requested"] and kinds[-1] == "completed"
    assert client.get("/api/accounts/trust", headers=recycler).json()["trust"]["stats"]["completed_deals"] == 1


def test_self_transport_and_cancel(market):
    client, who = market
    supplier_id, supplier = who["supplier"]
    recycler_id, recycler = who["recycler"]
    project, request = saved_project(client, supplier)
    inquiry = client.post("/api/matching/inquiries/batch", headers=supplier, json={
        "project_id": project, "recipient_ids": [recycler_id], "content": "문의", "request": request,
    }).json()["created"][0]["id"]
    deal_id = client.post("/api/deals", json={"inquiry_id": inquiry}, headers=supplier).json()["id"]
    path = f"/api/deals/{deal_id}"
    client.put(f"{path}/terms", headers=recycler, json={
        "price_type": "처리비", "unit_price": 50000, "quantity_ton": 2, "transport_by": "recycler_self"})
    agreed = client.post(f"{path}/terms/accept", headers=supplier).json()
    assert agreed["needs_carrier"] is False and all(step["status"] != "transport_pending" for step in agreed["flow"])
    assert client.get(f"{path}/carriers", headers=recycler).status_code == 409
    assert client.post(f"{path}/progress", headers=recycler, json={"step": "scheduled"}).status_code == 409
    client.put(f"{path}/shipment", headers=recycler, json={"pickup_window": "12/3 오전"})
    assert client.post(f"{path}/progress", headers=supplier, json={"step": "scheduled"}).status_code == 403
    assert client.post(f"{path}/progress", headers=recycler, json={"step": "scheduled"}).json()["status"] == "scheduled"
    assert client.post(f"{path}/cancel", headers=supplier, json={"reason": "생산 중단"}).json()["status"] == "cancelled"
    assert client.put(f"{path}/terms", headers=supplier, json={
        "price_type": "무상", "quantity_ton": 1, "transport_by": "supplier"}).status_code == 409


def test_demand_posts(market):
    client, who = market
    supplier_id, supplier = who["supplier"]
    recycler_id, recycler = who["recycler"]
    _, far = who["far"]
    post = {"material": "PP", "monthly_ton": 3, "regions": ["전주", "완주"], "price_type": "매입", "unit_price": 90000,
            "conditions": "단일 재질, 이물질 없음", "until": "2099-01-01"}
    assert client.post("/api/matching/demands", json=post, headers=supplier).status_code == 403
    demand = client.post("/api/matching/demands", json=post, headers=recycler).json()
    client.post("/api/matching/demands", json={**post, "material": "PE"}, headers=recycler)
    client.post("/api/matching/demands", json={**post, "until": "2000-01-01"}, headers=recycler)
    project, _ = saved_project(client, supplier)
    found = client.get(f"/api/matching/demands?project_id={project}", headers=supplier).json()
    assert [item["id"] for item in found] == [demand["id"]]
    assert found[0]["distance_km"] is not None
    reply = client.post(f"/api/matching/demands/{demand['id']}/reply", headers=supplier,
                        json={"project_id": project, "content": "월 2톤 공급 가능합니다."})
    inquiry = reply.json()["id"]
    assert client.get(f"/api/matching/inquiries/{inquiry}", headers=recycler).json()["can_start_deal"] is True
    mine = client.get("/api/matching/demands?mine=true", headers=recycler).json()
    assert next(item for item in mine if item["id"] == demand["id"])["response_count"] == 1
    assert client.get(f"/api/matching/demands?project_id={project}", headers=supplier).json()[0]["my_inquiry_id"] == inquiry
    assert client.put(f"/api/matching/demands/{demand['id']}", json=post, headers=far).status_code == 404
    assert client.delete(f"/api/matching/demands/{demand['id']}", headers=recycler).json()["status"] == "closed"
    assert client.get(f"/api/matching/demands?project_id={project}", headers=supplier).json() == []


def test_agent_failure_falls_back(market, monkeypatch):
    client, who = market
    _, supplier = who["supplier"]

    class Broken:
        def assess_request(self, request, context):
            raise RuntimeError("timeout")

        def assess_companies(self, request, companies, context):
            raise RuntimeError("timeout")

        def deal_documents(self, request, terms, context):
            raise RuntimeError("timeout")

    monkeypatch.setattr(matching_agents, "_agent", Broken())
    project, _ = saved_project(client, supplier)
    review = client.get(f"/api/matching/requests/{project}/review", headers=supplier).json()
    assert review["warnings"][0].startswith("연결된 에이전트가 응답하지 않아")
    companies = client.get(f"/api/matching/requests/{project}/companies", headers=supplier).json()
    assert companies and all(company["agent"]["warnings"][0].startswith("연결된 에이전트") for company in companies)


def test_deal_in_demo_workspaces_without_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("REAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REAI_SEED_SAMPLE", "0")
    monkeypatch.setenv("REAI_DEMO_MULTI_TENANT", "1")
    supplier, recycler = {"X-Reai-Demo-Org": "demo-a"}, {"X-Reai-Demo-Org": "demo-b"}
    old_request = {key: REQUEST[key] for key in ("material", "monthly_ton", "contamination", "packaging", "notes")}
    old_request["region"] = "전주"
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "PP"}, headers=supplier).json()["id"]
        assert client.put(f"/api/matching/requests/{project}", json=old_request, headers=supplier).status_code == 200
        inquiry = client.post("/api/matching/inquiries/batch", headers=supplier, json={
            "project_id": project, "recipient_ids": ["demo-b", "demo-c"], "content": "문의", "request": old_request,
        }).json()["created"]
        assert len(inquiry) == 2
        deal = client.post("/api/deals", json={"inquiry_id": inquiry[0]["id"]}, headers=recycler).json()
        assert deal["parties"]["supplier"]["name"] == "한빛부품" and deal["parties"]["recycler"]["trust"]["permit_registered"] is False
        client.put(f"/api/deals/{deal['id']}/terms", headers=supplier, json={
            "price_type": "무상", "quantity_ton": 2, "transport_by": "recycler"})
        agreed = client.post(f"/api/deals/{deal['id']}/terms/accept", headers=recycler).json()
        assert agreed["status"] == "agreed"
        assert client.get(f"/api/deals/{deal['id']}/carriers", headers=recycler).json() == []
        assert [item["id"] for item in client.get("/api/deals", headers=supplier).json()] == [deal["id"]]
