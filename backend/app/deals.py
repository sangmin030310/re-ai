"""Deals: one shared record per supplier–recycler match, with transport and paperwork.

Flow
    negotiating -> agreed -> (transport_pending) -> scheduled -> picked_up -> delivered -> completed
    any open state -> cancelled

* 거래 조건(terms)은 배출업체나 가공업체 중 한쪽이 제안하고 다른 쪽이 수락하면 합의됩니다.
* 운송 담당(transport_by)이 운송업체가 필요한 방식이면 담당 업체가 여러 운송업체에 견적을 요청하고 하나를 선택합니다.
* 운송업체는 선택된 뒤에 거래 대화와 운송 건 정보에 참여합니다. 단가 등 매매 조건은 보지 않습니다.
* 서류 체크리스트는 매칭 에이전트(deal_documents)가 정하고, 모든 항목이 완료 또는 해당 없음이어야 거래를 완료할 수 있습니다.
"""
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .accounts import get_account, registered_companies
from .agents import matching_agents
from .db import connect, data_dir, new_id, utc_now
from .regions import distance_km, normalized_region, same_region
from .trust import company_trust
from .workspaces import accounts_enabled, current_workspace

router = APIRouter(prefix="/api/deals", tags=["deals"])
Workspace = Annotated[str, Depends(current_workspace)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

STATUS_LABELS = {
    "negotiating": "조건 협의",
    "agreed": "조건 합의",
    "transport_pending": "운송 견적 요청",
    "scheduled": "운송 일정 확정",
    "picked_up": "상차 완료",
    "delivered": "반입·계량 완료",
    "completed": "거래 완료",
    "cancelled": "취소",
}
FLOW = ["negotiating", "agreed", "transport_pending", "scheduled", "picked_up", "delivered", "completed"]
TRANSPORT_LABELS = {
    "supplier": "배출업체가 운송업체 섭외",
    "recycler": "가공업체가 운송업체 섭외",
    "supplier_self": "배출업체 자체 운반",
    "recycler_self": "가공업체 직접 수거",
}
PRICE_LABELS = {"매입": "가공업체가 배출업체에 지급", "처리비": "배출업체가 가공업체에 지급", "무상": "대금 없음"}
UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt", ".csv", ".hwp", ".hwpx"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def init_deals():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_inquiry_id TEXT NOT NULL UNIQUE,
                supplier_id TEXT NOT NULL,
                recycler_id TEXT NOT NULL,
                carrier_id TEXT,
                status TEXT NOT NULL,
                request_snapshot TEXT NOT NULL,
                terms TEXT,
                terms_by TEXT,
                terms_agreed_at TEXT,
                shipment TEXT NOT NULL DEFAULT '{}',
                checklist TEXT NOT NULL DEFAULT '[]',
                cancel_reason TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS deals_supplier ON deals(supplier_id, updated_at);
            CREATE INDEX IF NOT EXISTS deals_recycler ON deals(recycler_id, updated_at);
            CREATE INDEX IF NOT EXISTS deals_carrier ON deals(carrier_id, updated_at);
            CREATE TABLE IF NOT EXISTS deal_events (
                sequence INTEGER PRIMARY KEY,
                deal_id TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                actor_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deal_messages (
                sequence INTEGER PRIMARY KEY,
                deal_id TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                author_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                client_id TEXT,
                UNIQUE(deal_id, author_id, client_id)
            );
            CREATE TABLE IF NOT EXISTS deal_transport_requests (
                id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                carrier_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('requested', 'quoted', 'declined', 'selected', 'not_selected')),
                note TEXT NOT NULL DEFAULT '',
                quote TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(deal_id, carrier_id)
            );
            CREATE TABLE IF NOT EXISTS deal_files (
                id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                checklist_key TEXT NOT NULL,
                uploader_id TEXT NOT NULL,
                name TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL,
                stored_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)


# ---------------------------------------------------------------- models

class DealCreate(BaseModel):
    inquiry_id: str


class DealTerms(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    price_type: Literal["매입", "처리비", "무상"]
    unit_price: int | None = Field(default=None, ge=0, le=100_000_000)
    quantity_ton: float = Field(gt=0, le=100000, allow_inf_nan=False)
    frequency: Literal["매월 정기", "주기 협의", "1회성"] = "매월 정기"
    start_date: date | None = None
    transport_by: Literal["supplier", "recycler", "supplier_self", "recycler_self"]
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""

    @model_validator(mode="after")
    def price_required(self):
        if self.price_type != "무상" and self.unit_price is None:
            raise ValueError("톤당 단가를 입력해 주세요.")
        if self.price_type == "무상":
            self.unit_price = None
        return self


class Shipment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pickup_address: Text | None = None
    pickup_window: Text | None = None
    pickup_equipment: Text | None = None
    packaging: Text | None = None
    planned_ton: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    dropoff_address: Text | None = None
    dropoff_window: Text | None = None
    unloading: Text | None = None
    vehicle: Text | None = None
    driver_contact: Text | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


SHIPMENT_LABELS = {
    "pickup_address": "상차 주소", "pickup_window": "상차 가능 시간", "pickup_equipment": "상차 장비",
    "packaging": "포장 상태", "planned_ton": "운송 예정 물량", "dropoff_address": "하차 주소",
    "dropoff_window": "반입 가능 시간", "unloading": "하차 조건", "vehicle": "배차 차량",
    "driver_contact": "기사 연락처", "notes": "운송 메모",
}


class TransportRequest(BaseModel):
    carrier_ids: list[str] = Field(min_length=1, max_length=10)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class TransportResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    action: Literal["quote", "decline"]
    price: int | None = Field(default=None, ge=0, le=1_000_000_000)
    available_date: date | None = None
    vehicle: Text = ""
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""

    @model_validator(mode="after")
    def quote_fields(self):
        if self.action == "quote" and (self.price is None or self.available_date is None):
            raise ValueError("운송비와 가능한 날짜를 입력해 주세요.")
        return self


class Progress(BaseModel):
    step: Literal["scheduled", "picked_up", "delivered", "completed"]
    actual_ton: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class Cancel(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ChecklistUpdate(BaseModel):
    state: Literal["pending", "done", "not_applicable"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class DealMessage(BaseModel):
    content: Message
    client_id: UUID


# ---------------------------------------------------------------- helpers

def role_of(db, workspace: str) -> str | None:
    from .matching import COMPANIES, SUPPLIER

    account = get_account(workspace, db)
    if account:
        return account["role"]
    if workspace in {"local", SUPPLIER}:
        return "supplier"
    if workspace in COMPANIES:
        return "recycler"
    return None


def name_of(db, workspace: str | None) -> str | None:
    from .matching import company_name

    return company_name(workspace, db) if workspace else None


def company_city(db, company_id: str) -> str | None:
    from .matching import COMPANIES

    if company_id in COMPANIES:
        return COMPANIES[company_id]["city"]
    row = db.execute("SELECT recycler_profile FROM company_accounts WHERE id=?", (company_id,)).fetchone() \
        if accounts_enabled() else None
    return json.loads(row["recycler_profile"]).get("city") if row and row["recycler_profile"] else None


def load_deal(db, deal_id: str):
    row = db.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "거래 건을 찾을 수 없습니다.")
    return row


def deal_role(db, deal, workspace) -> str | None:
    if workspace == deal["supplier_id"]:
        return "supplier"
    if workspace == deal["recycler_id"]:
        return "recycler"
    if deal["carrier_id"] and workspace == deal["carrier_id"]:
        return "carrier"
    asked = db.execute(
        "SELECT 1 FROM deal_transport_requests WHERE deal_id=? AND carrier_id=?", (deal["id"], workspace),
    ).fetchone()
    return "carrier_candidate" if asked else None


def require_role(db, deal, workspace, *allowed):
    role = deal_role(db, deal, workspace)
    if role is None:
        raise HTTPException(404, "거래 건을 찾을 수 없습니다.")
    if allowed and role not in allowed:
        raise HTTPException(403, "이 단계는 다른 참여 업체가 진행합니다.")
    return role


def terms_of(deal) -> dict | None:
    return json.loads(deal["terms"]) if deal["terms"] else None


def transport_owner(terms: dict | None) -> str | None:
    if not terms:
        return None
    return "recycler" if terms["transport_by"].startswith("recycler") else "supplier"


def needs_carrier(terms: dict | None) -> bool:
    return bool(terms and terms["transport_by"] in ("supplier", "recycler"))


def log(db, deal_id, actor, kind, detail):
    now = utc_now()
    db.execute(
        "INSERT INTO deal_events(deal_id, actor_id, kind, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (deal_id, actor, kind, detail, now),
    )
    db.execute("UPDATE deals SET updated_at=? WHERE id=?", (now, deal_id))


def require_status(deal, *statuses):
    if deal["status"] not in statuses:
        raise HTTPException(409, f"현재 단계({STATUS_LABELS[deal['status']]})에서는 할 수 없는 작업입니다.")


def merge_checklist(existing: list[dict], requirements: list[dict]) -> list[dict]:
    previous = {item["key"]: item for item in existing}
    merged = []
    for requirement in requirements:
        state = previous.get(requirement["key"], {})
        merged.append({**requirement, "state": state.get("state", "pending"), "state_note": state.get("state_note", ""),
                       "updated_by": state.get("updated_by"), "updated_at": state.get("updated_at")})
    return merged


def agent_context(deal) -> dict:
    return {"deal_id": deal["id"], "supplier_id": deal["supplier_id"], "recycler_id": deal["recycler_id"]}


def carrier_candidates(db, deal) -> list[dict]:
    if not accounts_enabled():
        return []
    request = json.loads(deal["request_snapshot"])
    terms = terms_of(deal) or {}
    amount = terms.get("quantity_ton") or request["monthly_ton"]
    destination = company_city(db, deal["recycler_id"])
    results = []
    for company in registered_companies(db, "carrier"):
        covers_origin = any(same_region(request["region"], area) for area in company["regions"])
        covers_destination = destination and any(same_region(destination, area) for area in company["regions"])
        if request["material"] in company["materials"] and amount <= company["max_ton"] and covers_origin and covers_destination:
            results.append({
                "id": company["id"], "name": company["name"], "city": company["city"],
                "regions": company["regions"], "max_ton": company["max_ton"],
                "distance_km": distance_km(request["region"], destination),
                "trust": company_trust(db, company["id"]),
            })
    return results


def next_action(db, deal, role: str | None, viewer: str) -> dict:
    """What the viewer should do next, and whether it is their turn."""
    status, terms = deal["status"], terms_of(deal)
    owner = transport_owner(terms)

    def action(label, mine):
        return {"label": label, "mine": mine}

    if status == "negotiating":
        if not terms:
            return action("거래 조건(단가·물량·운송 담당)을 제안하세요.", role in ("supplier", "recycler"))
        if deal["terms_by"] == viewer:
            return action("상대 업체가 조건을 확인하고 있습니다.", False)
        return action("상대 업체가 제안한 조건을 확인하고 수락하거나 수정하세요.", role in ("supplier", "recycler"))
    if status == "agreed":
        if needs_carrier(terms):
            return action("운송업체에 견적을 요청하세요.", role == owner)
        return action("운송 일정을 확정하세요.", role == owner)
    if status == "transport_pending":
        if role == "carrier_candidate":
            row = db.execute(
                "SELECT status FROM deal_transport_requests WHERE deal_id=? AND carrier_id=?", (deal["id"], viewer),
            ).fetchone()
            return action("운송 견적을 보내주세요.", bool(row and row["status"] == "requested"))
        quoted = db.execute(
            "SELECT COUNT(*) FROM deal_transport_requests WHERE deal_id=? AND status='quoted'", (deal["id"],),
        ).fetchone()[0]
        if quoted:
            return action(f"받은 운송 견적 {quoted}건을 비교하고 선택하세요.", role == owner)
        return action("운송업체의 견적을 기다리고 있습니다.", False)
    if status == "scheduled":
        mover = "carrier" if deal["carrier_id"] else owner
        return action("상차를 마치면 상차 완료를 기록하세요.", role == mover)
    if status == "picked_up":
        return action("반입·계량 결과(실제 물량)를 기록하세요.", role == "recycler")
    if status == "delivered":
        checklist = json.loads(deal["checklist"])
        missing = [item for item in checklist if item["state"] == "pending"]
        if missing:
            mine = any(item["owner"] in (role, "any") for item in missing)
            return action(f"남은 서류 {len(missing)}건을 올리거나 해당 없음으로 표시하세요.", mine and role != "carrier")
        return action("서류가 모두 준비됐습니다. 거래를 완료하세요.", role in ("supplier", "recycler"))
    if status == "completed":
        return action("거래가 완료됐습니다.", False)
    return action("취소된 거래입니다.", False)


def deal_summary(db, deal, workspace) -> dict:
    role = deal_role(db, deal, workspace)
    request = json.loads(deal["request_snapshot"])
    terms = terms_of(deal)
    return {
        "id": deal["id"], "status": deal["status"], "status_label": STATUS_LABELS[deal["status"]],
        "my_role": role,
        "supplier_name": name_of(db, deal["supplier_id"]),
        "recycler_name": name_of(db, deal["recycler_id"]),
        "carrier_name": name_of(db, deal["carrier_id"]),
        "material": request["material"],
        "quantity_ton": (terms or {}).get("quantity_ton") or request["monthly_ton"],
        "route": f"{request['region']} → {company_city(db, deal['recycler_id']) or '가공업체'}",
        "next_action": next_action(db, deal, role, workspace),
        "updated_at": deal["updated_at"],
    }


def deal_json(db, deal, workspace) -> dict:
    role = deal_role(db, deal, workspace)
    carrier_view = role in ("carrier", "carrier_candidate")
    request = json.loads(deal["request_snapshot"])
    terms = terms_of(deal)
    if carrier_view and terms:
        terms = {key: terms[key] for key in ("quantity_ton", "frequency", "start_date", "transport_by")}
    if carrier_view:
        request = {key: request.get(key) for key in ("material", "monthly_ton", "region", "packaging", "contamination", "address")}
    transport = db.execute(
        "SELECT * FROM deal_transport_requests WHERE deal_id=? ORDER BY created_at, carrier_id", (deal["id"],),
    ).fetchall()
    if carrier_view:
        transport = [row for row in transport if row["carrier_id"] == workspace]
    files = db.execute(
        "SELECT id, checklist_key, uploader_id, name, size, created_at FROM deal_files WHERE deal_id=? ORDER BY created_at",
        (deal["id"],),
    ).fetchall()
    checklist = json.loads(deal["checklist"])
    for item in checklist:
        item["files"] = [dict(file) | {"uploader_name": name_of(db, file["uploader_id"])}
                         for file in files if file["checklist_key"] == item["key"]]
    events = db.execute(
        "SELECT sequence, actor_id, kind, detail, created_at FROM deal_events WHERE deal_id=? ORDER BY sequence",
        (deal["id"],),
    ).fetchall()
    can_chat = role in ("supplier", "recycler", "carrier")
    messages = db.execute(
        "SELECT sequence, author_id, content, created_at FROM deal_messages WHERE deal_id=? ORDER BY sequence",
        (deal["id"],),
    ).fetchall() if can_chat else []
    source = db.execute(
        "SELECT review_status, review_reason, review_quote FROM inquiries WHERE id=?", (deal["source_inquiry_id"],),
    ).fetchone()
    destination_city = company_city(db, deal["recycler_id"])
    parties = {
        key: {"id": deal[f"{key}_id"], "name": name_of(db, deal[f"{key}_id"]),
              "trust": company_trust(db, deal[f"{key}_id"])} if deal[f"{key}_id"] else None
        for key in ("supplier", "recycler", "carrier")
    }
    return {
        "id": deal["id"], "project_id": deal["project_id"] if role == "supplier" else None,
        "source_inquiry_id": deal["source_inquiry_id"] if not carrier_view else None,
        "status": deal["status"], "status_label": STATUS_LABELS[deal["status"]],
        "flow": [{"status": key, "label": STATUS_LABELS[key]} for key in FLOW
                 if key != "transport_pending" or needs_carrier(terms_of(deal)) or terms_of(deal) is None],
        "my_role": role, "parties": parties,
        "request": request, "request_files": request_files(db, deal), "destination_city": destination_city,
        "distance_km": distance_km(request.get("region"), destination_city),
        "terms": terms, "terms_by": deal["terms_by"], "terms_agreed_at": deal["terms_agreed_at"],
        "terms_proposed_by_me": deal["terms_by"] == workspace,
        "suggested_terms": suggested_terms(source, request) if not carrier_view and not deal["terms"] else None,
        "transport_owner": transport_owner(terms_of(deal)),
        "needs_carrier": needs_carrier(terms_of(deal)),
        "shipment": json.loads(deal["shipment"]),
        "transport_requests": [{
            "id": row["id"], "carrier_id": row["carrier_id"], "carrier_name": name_of(db, row["carrier_id"]),
            "status": row["status"], "note": row["note"], "quote": json.loads(row["quote"]) if row["quote"] else None,
            "trust": company_trust(db, row["carrier_id"]), "updated_at": row["updated_at"],
        } for row in transport],
        "checklist": checklist,
        "events": [dict(event) | {"actor_name": name_of(db, event["actor_id"])} for event in events]
        if not carrier_view or role == "carrier" else [],
        "messages": [dict(message) | {"author_name": name_of(db, message["author_id"])} for message in messages],
        "can_chat": can_chat,
        "next_action": next_action(db, deal, role, workspace),
        "cancel_reason": deal["cancel_reason"],
        "created_at": deal["created_at"], "updated_at": deal["updated_at"],
        "labels": {"transport": TRANSPORT_LABELS, "price": PRICE_LABELS},
    }


def suggested_terms(source, request) -> dict | None:
    """Prefill the terms form from the recycler's quote on the original inquiry."""
    quote = json.loads(source["review_quote"]) if source and source["review_quote"] else {}
    preference = request.get("price_preference")
    price_type = quote.get("price_type") or {"매각 희망": "매입", "처리비 지급 가능": "처리비"}.get(preference)
    if price_type == "협의":
        price_type = None
    return {
        "price_type": price_type, "unit_price": quote.get("unit_price"),
        "quantity_ton": request.get("monthly_ton"),
        "frequency": request.get("frequency") or "매월 정기",
        "start_date": quote.get("available_from"),
        "transport_by": None,
    }


def fetch(db, deal_id, workspace):
    return deal_json(db, load_deal(db, deal_id), workspace)


# ---------------------------------------------------------------- endpoints

@router.get("")
def list_deals(workspace: Workspace):
    with connect() as db:
        rows = db.execute(
            """SELECT DISTINCT d.* FROM deals d
               LEFT JOIN deal_transport_requests t ON t.deal_id=d.id AND t.carrier_id=?
               WHERE d.supplier_id=? OR d.recycler_id=? OR d.carrier_id=?
                  OR (t.status IN ('requested', 'quoted') AND d.status='transport_pending')
               ORDER BY d.updated_at DESC""",
            (workspace, workspace, workspace, workspace),
        ).fetchall()
        return [deal_summary(db, row, workspace) for row in rows]


@router.post("", status_code=201)
def create_deal(data: DealCreate, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inquiry = db.execute(
            "SELECT * FROM inquiries WHERE id=? AND (sender_id=? OR recipient_id=?)",
            (data.inquiry_id, workspace, workspace),
        ).fetchone()
        if inquiry is None:
            raise HTTPException(404, "문의를 찾을 수 없습니다.")
        existing = db.execute("SELECT id FROM deals WHERE source_inquiry_id=?", (data.inquiry_id,)).fetchone()
        if existing:
            return fetch(db, existing["id"], workspace)
        if inquiry["destination_inquiry_id"] or role_of(db, inquiry["recipient_id"]) != "recycler":
            raise HTTPException(422, "배출업체와 가공업체 사이의 문의에서만 거래 건을 만들 수 있습니다.")
        if role_of(db, inquiry["sender_id"]) != "supplier":
            raise HTTPException(422, "배출업체의 요청서가 연결된 문의가 필요합니다.")
        if inquiry["review_status"] == "declined":
            raise HTTPException(409, "가공업체가 '반입 어려움'으로 검토한 문의입니다. 검토 결과를 바꾼 뒤 거래를 시작하세요.")
        deal_id, now = new_id(), utc_now()
        request = json.loads(inquiry["request_snapshot"])
        requirements = matching_agents.deal_documents(request, {}, {"inquiry_id": inquiry["id"]})
        db.execute(
            """INSERT INTO deals(id, project_id, source_inquiry_id, supplier_id, recycler_id, status, request_snapshot,
                                 shipment, checklist, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'negotiating', ?, ?, ?, ?, ?, ?)""",
            (deal_id, inquiry["project_id"], inquiry["id"], inquiry["sender_id"], inquiry["recipient_id"],
             inquiry["request_snapshot"],
             json.dumps({"pickup_address": request.get("address") or None, "packaging": request.get("packaging")},
                        ensure_ascii=False),
             json.dumps(merge_checklist([], requirements), ensure_ascii=False), workspace, now, now),
        )
        log(db, deal_id, workspace, "created", "거래 건을 만들었습니다.")
        return fetch(db, deal_id, workspace)


@router.get("/{deal_id}")
def get_deal(deal_id: str, workspace: Workspace):
    with connect() as db:
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace)
        return deal_json(db, deal, workspace)


@router.put("/{deal_id}/terms")
def propose_terms(deal_id: str, data: DealTerms, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler")
        require_status(deal, "negotiating", "agreed")
        db.execute(
            "UPDATE deals SET terms=?, terms_by=?, terms_agreed_at=NULL, status='negotiating' WHERE id=?",
            (data.model_dump_json(), workspace, deal_id),
        )
        price = "대금 없음" if data.price_type == "무상" else f"{data.price_type} 톤당 {data.unit_price:,}원"
        log(db, deal_id, workspace, "terms_proposed",
            f"조건 제안: {price}, {data.quantity_ton:g}톤, {data.frequency}, {TRANSPORT_LABELS[data.transport_by]}")
        return fetch(db, deal_id, workspace)


@router.post("/{deal_id}/terms/accept")
def accept_terms(deal_id: str, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler")
        require_status(deal, "negotiating")
        if not deal["terms"]:
            raise HTTPException(409, "먼저 거래 조건을 제안해 주세요.")
        if deal["terms_by"] == workspace:
            raise HTTPException(409, "제안한 업체가 아닌 상대 업체가 수락해야 합니다.")
        terms = terms_of(deal)
        requirements = matching_agents.deal_documents(json.loads(deal["request_snapshot"]), terms, agent_context(deal))
        checklist = merge_checklist(json.loads(deal["checklist"]), requirements)
        db.execute(
            "UPDATE deals SET status='agreed', terms_agreed_at=?, checklist=? WHERE id=?",
            (utc_now(), json.dumps(checklist, ensure_ascii=False), deal_id),
        )
        log(db, deal_id, workspace, "terms_agreed", "거래 조건에 합의했습니다.")
        return fetch(db, deal_id, workspace)


@router.get("/{deal_id}/carriers")
def list_carriers(deal_id: str, workspace: Workspace):
    with connect() as db:
        deal = load_deal(db, deal_id)
        role = require_role(db, deal, workspace, "supplier", "recycler")
        terms = terms_of(deal)
        if not needs_carrier(terms):
            raise HTTPException(409, "운송업체 섭외가 필요한 운송 방식이 아닙니다.")
        if transport_owner(terms) != role:
            raise HTTPException(403, "운송 담당 업체가 운송업체를 찾습니다.")
        asked = {row["carrier_id"] for row in db.execute(
            "SELECT carrier_id FROM deal_transport_requests WHERE deal_id=?", (deal_id,))}
        return [company | {"requested": company["id"] in asked} for company in carrier_candidates(db, deal)]


@router.post("/{deal_id}/transport-requests")
def request_transport(deal_id: str, data: TransportRequest, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        role = require_role(db, deal, workspace, "supplier", "recycler")
        require_status(deal, "agreed", "transport_pending")
        terms = terms_of(deal)
        if not needs_carrier(terms) or transport_owner(terms) != role:
            raise HTTPException(403, "운송 담당 업체만 운송 견적을 요청할 수 있습니다.")
        allowed = {company["id"] for company in carrier_candidates(db, deal)}
        invalid = [carrier for carrier in data.carrier_ids if carrier not in allowed]
        if invalid:
            raise HTTPException(422, "출발지·도착지와 재질·물량 조건에 맞는 운송업체만 선택할 수 있습니다.")
        now = utc_now()
        added = 0
        for carrier in dict.fromkeys(data.carrier_ids):
            added += db.execute(
                """INSERT INTO deal_transport_requests(id, deal_id, carrier_id, status, note, created_at, updated_at)
                   VALUES (?, ?, ?, 'requested', ?, ?, ?) ON CONFLICT(deal_id, carrier_id) DO NOTHING""",
                (new_id(), deal_id, carrier, data.note, now, now),
            ).rowcount
        db.execute("UPDATE deals SET status='transport_pending' WHERE id=?", (deal_id,))
        if added:
            log(db, deal_id, workspace, "transport_requested", f"운송업체 {added}곳에 견적을 요청했습니다.")
        return fetch(db, deal_id, workspace)


@router.put("/{deal_id}/transport-requests/mine")
def respond_transport(deal_id: str, data: TransportResponse, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "carrier_candidate")
        require_status(deal, "transport_pending")
        row = db.execute(
            "SELECT * FROM deal_transport_requests WHERE deal_id=? AND carrier_id=?", (deal_id, workspace),
        ).fetchone()
        if row["status"] not in ("requested", "quoted"):
            raise HTTPException(409, "이미 마감된 견적 요청입니다.")
        quote = data.model_dump(mode="json", exclude={"action"}) if data.action == "quote" else None
        db.execute(
            "UPDATE deal_transport_requests SET status=?, quote=?, updated_at=? WHERE id=?",
            ("quoted" if quote else "declined", json.dumps(quote, ensure_ascii=False) if quote else None, utc_now(), row["id"]),
        )
        detail = f"운송 견적 {data.price:,}원 ({data.available_date} 가능)" if quote else "운송 요청을 거절했습니다."
        log(db, deal_id, workspace, "transport_quoted" if quote else "transport_declined", detail)
        return fetch(db, deal_id, workspace)


@router.post("/{deal_id}/transport-requests/{request_id}/select")
def select_transport(deal_id: str, request_id: str, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        role = require_role(db, deal, workspace, "supplier", "recycler")
        require_status(deal, "transport_pending")
        if transport_owner(terms_of(deal)) != role:
            raise HTTPException(403, "운송 담당 업체만 운송업체를 선택할 수 있습니다.")
        row = db.execute(
            "SELECT * FROM deal_transport_requests WHERE id=? AND deal_id=?", (request_id, deal_id),
        ).fetchone()
        if row is None or row["status"] != "quoted":
            raise HTTPException(409, "견적을 보낸 운송업체만 선택할 수 있습니다.")
        quote = json.loads(row["quote"])
        now = utc_now()
        db.execute("UPDATE deal_transport_requests SET status='not_selected', updated_at=? WHERE deal_id=? AND id!=? "
                   "AND status IN ('requested', 'quoted')", (now, deal_id, request_id))
        db.execute("UPDATE deal_transport_requests SET status='selected', updated_at=? WHERE id=?", (now, request_id))
        shipment = json.loads(deal["shipment"])
        if quote.get("vehicle") and not shipment.get("vehicle"):
            shipment["vehicle"] = quote["vehicle"]
        db.execute(
            "UPDATE deals SET carrier_id=?, status='scheduled', shipment=? WHERE id=?",
            (row["carrier_id"], json.dumps(shipment, ensure_ascii=False), deal_id),
        )
        log(db, deal_id, workspace, "transport_selected",
            f"{name_of(db, row['carrier_id'])}을(를) 운송업체로 선택했습니다 ({quote['price']:,}원, {quote['available_date']}).")
        return fetch(db, deal_id, workspace)


@router.put("/{deal_id}/shipment")
def update_shipment(deal_id: str, data: Shipment, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        require_status(deal, "negotiating", "agreed", "transport_pending", "scheduled", "picked_up")
        shipment = json.loads(deal["shipment"])
        changes = {key: value for key, value in data.model_dump(exclude_unset=True).items() if shipment.get(key) != value}
        if not changes:
            return deal_json(db, deal, workspace)
        shipment.update(changes)
        db.execute("UPDATE deals SET shipment=? WHERE id=?", (json.dumps(shipment, ensure_ascii=False), deal_id))
        log(db, deal_id, workspace, "shipment_updated",
            "운송 정보 수정: " + ", ".join(SHIPMENT_LABELS[key] for key in changes))
        return fetch(db, deal_id, workspace)


@router.post("/{deal_id}/progress")
def record_progress(deal_id: str, data: Progress, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        role = require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        terms = terms_of(deal)
        owner = transport_owner(terms)
        shipment = json.loads(deal["shipment"])
        if data.step == "scheduled":
            require_status(deal, "agreed")
            if needs_carrier(terms) or role != owner:
                raise HTTPException(403, "자체 운반을 맡은 업체가 운송 일정을 확정합니다.")
            if not shipment.get("pickup_window"):
                raise HTTPException(409, "운송 건에 상차 가능 시간을 먼저 입력해 주세요.")
            detail = f"운송 일정을 확정했습니다 ({shipment['pickup_window']})."
        elif data.step == "picked_up":
            require_status(deal, "scheduled")
            mover = "carrier" if deal["carrier_id"] else owner
            if role != mover:
                raise HTTPException(403, "운송을 맡은 업체가 상차 완료를 기록합니다.")
            if data.actual_ton:
                shipment["picked_up_ton"] = data.actual_ton
            detail = "상차를 완료했습니다." + (f" ({data.actual_ton:g}톤)" if data.actual_ton else "")
        elif data.step == "delivered":
            require_status(deal, "picked_up")
            if role != "recycler":
                raise HTTPException(403, "가공업체가 반입·계량 결과를 기록합니다.")
            if not data.actual_ton:
                raise HTTPException(422, "계량한 실제 물량(톤)을 입력해 주세요.")
            shipment["delivered_ton"] = data.actual_ton
            detail = f"반입·계량을 완료했습니다 ({data.actual_ton:g}톤)."
        else:
            require_status(deal, "delivered")
            if role not in ("supplier", "recycler"):
                raise HTTPException(403, "배출업체나 가공업체가 거래를 완료합니다.")
            missing = [item["label"] for item in json.loads(deal["checklist"]) if item["state"] == "pending"]
            if missing:
                raise HTTPException(409, "남은 서류가 있습니다: " + ", ".join(missing))
            detail = "거래를 완료했습니다."
        if data.note:
            detail += f" 메모: {data.note}"
        db.execute("UPDATE deals SET status=?, shipment=? WHERE id=?",
                   (data.step, json.dumps(shipment, ensure_ascii=False), deal_id))
        log(db, deal_id, workspace, data.step, detail)
        return fetch(db, deal_id, workspace)


@router.post("/{deal_id}/cancel")
def cancel_deal(deal_id: str, data: Cancel, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler")
        require_status(deal, "negotiating", "agreed", "transport_pending", "scheduled")
        db.execute("UPDATE deals SET status='cancelled', cancel_reason=? WHERE id=?", (data.reason, deal_id))
        db.execute("UPDATE deal_transport_requests SET status='not_selected' WHERE deal_id=? "
                   "AND status IN ('requested', 'quoted')", (deal_id,))
        log(db, deal_id, workspace, "cancelled", f"거래를 취소했습니다. 사유: {data.reason}")
        return fetch(db, deal_id, workspace)


@router.put("/{deal_id}/checklist/{key}")
def update_checklist(deal_id: str, key: str, data: ChecklistUpdate, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        checklist = json.loads(deal["checklist"])
        item = next((item for item in checklist if item["key"] == key), None)
        if item is None:
            raise HTTPException(404, "체크리스트 항목을 찾을 수 없습니다.")
        item.update(state=data.state, state_note=data.note, updated_by=workspace, updated_at=utc_now())
        db.execute("UPDATE deals SET checklist=? WHERE id=?", (json.dumps(checklist, ensure_ascii=False), deal_id))
        label = {"done": "완료", "not_applicable": "해당 없음", "pending": "준비 중"}[data.state]
        log(db, deal_id, workspace, "checklist", f"{item['label']}: {label}" + (f" ({data.note})" if data.note else ""))
        return fetch(db, deal_id, workspace)


@router.post("/{deal_id}/files", status_code=201)
async def upload_file(deal_id: str, workspace: Workspace, key: str = Form(...), file: UploadFile = File(...)):
    with connect() as db:
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        if not any(item["key"] == key for item in json.loads(deal["checklist"])):
            raise HTTPException(404, "체크리스트 항목을 찾을 수 없습니다.")
    original = Path((file.filename or "").replace("\\", "/")).name
    ext = Path(original).suffix.lower()
    if not original or ext not in UPLOAD_EXTENSIONS:
        raise HTTPException(400, "허용된 파일 형식만 올릴 수 있습니다: PDF, 이미지, DOCX, XLSX, TXT, CSV, HWP, HWPX")
    folder = data_dir() / "deal-files"
    folder.mkdir(parents=True, exist_ok=True)
    file_id = new_id()
    path = folder / f"{file_id}{ext}"
    size = 0
    try:
        with path.open("wb") as target:
            while part := await file.read(1024 * 1024):
                size += len(part)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "15MB 이하의 파일만 올릴 수 있습니다.")
                target.write(part)
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            deal = load_deal(db, deal_id)
            checklist = json.loads(deal["checklist"])
            item = next(item for item in checklist if item["key"] == key)
            db.execute(
                """INSERT INTO deal_files(id, deal_id, checklist_key, uploader_id, name, mime, size, stored_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_id, deal_id, key, workspace, original, file.content_type or "application/octet-stream", size,
                 path.name, utc_now()),
            )
            if item["state"] == "pending":
                item.update(state="done", updated_by=workspace, updated_at=utc_now())
                db.execute("UPDATE deals SET checklist=? WHERE id=?", (json.dumps(checklist, ensure_ascii=False), deal_id))
            log(db, deal_id, workspace, "file", f"{item['label']} 파일을 올렸습니다: {original}")
            return fetch(db, deal_id, workspace)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/{deal_id}/files/{file_id}")
def download_file(deal_id: str, file_id: str, workspace: Workspace):
    with connect() as db:
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        row = db.execute("SELECT * FROM deal_files WHERE id=? AND deal_id=?", (file_id, deal_id)).fetchone()
    if row is None or not (data_dir() / "deal-files" / row["stored_name"]).is_file():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    return FileResponse(data_dir() / "deal-files" / row["stored_name"], filename=row["name"],
                        media_type="application/octet-stream")


@router.post("/{deal_id}/messages", status_code=201)
def post_message(deal_id: str, data: DealMessage, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier")
        db.execute(
            """INSERT INTO deal_messages(deal_id, author_id, content, created_at, client_id) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(deal_id, author_id, client_id) DO NOTHING""",
            (deal_id, workspace, data.content, utc_now(), str(data.client_id)),
        )
        db.execute("UPDATE deals SET updated_at=? WHERE id=?", (utc_now(), deal_id))
    return {"ok": True}


@router.get("/{deal_id}/request-files/{document_id}")
def download_request_file(deal_id: str, document_id: str, workspace: Workspace):
    """Photos or analysis sheets attached to the request this deal is based on."""
    with connect() as db:
        deal = load_deal(db, deal_id)
        require_role(db, deal, workspace, "supplier", "recycler", "carrier", "carrier_candidate")
        ids = json.loads(deal["request_snapshot"]).get("attachment_ids", [])
        row = db.execute("SELECT * FROM documents WHERE id=? AND project_id=?", (document_id, deal["project_id"])).fetchone() \
            if document_id in ids else None
    if row is None or not (data_dir() / "uploads" / row["stored_name"]).is_file():
        raise HTTPException(404, "첨부 파일을 찾을 수 없습니다.")
    return FileResponse(data_dir() / "uploads" / row["stored_name"], filename=row["name"],
                        media_type="application/octet-stream")


def request_files(db, deal) -> list[dict]:
    ids = json.loads(deal["request_snapshot"]).get("attachment_ids", [])
    if not ids:
        return []
    rows = db.execute(
        f"SELECT id, name, size FROM documents WHERE project_id=? AND id IN ({','.join('?' * len(ids))})",
        (deal["project_id"], *ids),
    ).fetchall()
    return [dict(row) for row in rows]


def deal_for_inquiry(db, inquiry_id: str) -> str | None:
    row = db.execute("SELECT id FROM deals WHERE source_inquiry_id=?", (inquiry_id,)).fetchone()
    return row["id"] if row else None


__all__ = ["router", "init_deals", "deal_for_inquiry", "role_of", "normalized_region"]
