"""Request forms and inquiry threads for the local matching demo."""
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .accounts import Material, get_account, registered_companies
from .agents import matching_agents
from .db import connect, data_dir, new_id, utc_now
from .document_archive import archive_request, word_download
from .request_document import render_request_document
from .regions import distance_km, normalized_region, same_region
from .request_chat import CITIES, merge_request_profile
from .trust import company_trust
from .workspaces import accounts_enabled, current_workspace, invite_codes, online_enabled

router = APIRouter(prefix="/api/matching", tags=["matching"])
Workspace = Annotated[str, Depends(current_workspace)]
SUPPLIER = "demo-a"
SUPPLIER_NAME = "한빛부품"
TITLE = "폐기물 인수 검토 요청서"
FILENAME = f"{TITLE}.docx"

COMPANIES = {
    "demo-b": {
        "id": "demo-b", "name": "전주순환소재", "city": "전주",
        "materials": ("PP", "PE"), "regions": ("전주", "완주", "익산"),
        "max_ton": 5, "transport": "업체 수거", "route": "선별 후 재생원료화",
        "intro": "분리 배출된 플라스틱을 수거해 선별한 뒤 재생원료로 가공합니다.",
        "check": "성상 분석표와 포장 사진 확인",
    },
    "demo-c": {
        "id": "demo-c", "name": "익산리플라", "city": "익산",
        "materials": ("PP", "PET"), "regions": ("익산", "전주", "군산"),
        "max_ton": 4, "transport": "배출업체 직접 운반", "route": "사업장 반입 후 파쇄",
        "intro": "담당자와 반입 일정을 조율한 뒤 사업장에 직접 가져오는 방식입니다.",
        "check": "재질 분리 상태와 샘플 확인",
    },
    "demo-d": {
        "id": "demo-d", "name": "새봄자원", "city": "완주",
        "materials": ("PP", "철/금속"), "regions": ("완주", "전주", "김제"),
        "max_ton": 10, "transport": "업체 수거", "route": "집하 후 재질별 선별",
        "intro": "사업장에서 수거한 폐기물을 집하한 뒤 재질에 따라 선별합니다.",
        "check": "현장 보관 상태와 수거 일정 확인",
    },
    "demo-e": {
        "id": "demo-e", "name": "서울순환소재", "city": "서울",
        "materials": ("PP", "PE"), "regions": ("서울", "전주", "익산", "완주"),
        "max_ton": 6, "transport": "업체 수거", "route": "재질 선별 후 재생원료화",
        "intro": "시연용 광역 수거 업체입니다. 전주 배출 현장의 물량도 상담 후 수거할 수 있습니다.",
        "check": "장거리 운반 견적과 수거 일정 확인",
    },
    "demo-f": {
        "id": "demo-f", "name": "군산리턴폴리머", "city": "군산",
        "materials": ("PP", "PE", "혼합 플라스틱"), "regions": ("전주", "군산", "익산", "김제"),
        "max_ton": 7, "transport": "업체 수거", "route": "재질 선별·세척",
        "intro": "플라스틱 스크랩을 수거한 뒤 재질을 선별하고 세척합니다.",
        "check": "필름 혼입 여부와 상차 공간 확인",
    },
    "demo-g": {
        "id": "demo-g", "name": "김제리폼소재", "city": "김제",
        "materials": ("PP", "PET"), "regions": ("전주", "김제", "군산", "부안"),
        "min_ton": 1, "max_ton": 3, "transport": "배출업체 직접 운반", "route": "샘플 검토 후 시험 가공",
        "intro": "단일 재질의 생산 스크랩을 샘플로 확인한 뒤 소량 반입 일정을 잡습니다.",
        "check": "샘플 승인과 반입 가능 시간 확인",
    },
    "demo-h": {
        "id": "demo-h", "name": "대전달빛중합", "city": "대전",
        "materials": ("PP", "PE"), "regions": ("전주", "대전", "세종", "청주"),
        "max_ton": 12, "transport": "배출업체 직접 운반", "route": "분쇄·펠릿 생산",
        "intro": "PP와 PE를 재질별로 반입받아 분쇄 후 재생 펠릿으로 가공합니다.",
        "check": "재질별 포장 표기와 하차 장비 확인",
    },
    "demo-i": {
        "id": "demo-i", "name": "전주새결금속", "city": "전주",
        "materials": ("철/금속",), "regions": ("전주", "완주", "익산"),
        "max_ton": 15, "transport": "업체 수거", "route": "금속 선별·압축",
        "intro": "철 스크랩을 계량하고 이물질을 선별한 뒤 압축합니다.",
        "check": "절삭유 잔류 여부와 금속 종류 확인",
    },
    "demo-j": {
        "id": "demo-j", "name": "익산다시종이", "city": "익산",
        "materials": ("폐지",), "regions": ("전주", "익산", "김제"),
        "max_ton": 8, "transport": "업체 수거", "route": "폐지 선별·압축",
        "intro": "포장지와 골판지를 등급별로 분류한 뒤 압축합니다.",
        "check": "수분과 코팅·테이프 혼입 확인",
    },
}
PARTICIPANTS = {"local": "배출업체 작업공간", SUPPLIER: SUPPLIER_NAME, **{key: value["name"] for key, value in COMPANIES.items()}}


def init_matching():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS intake_requests (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                details TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS selected_companies (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                company_id TEXT NOT NULL,
                selected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inquiries (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                request_snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, recipient_id)
            );
            CREATE TABLE IF NOT EXISTS inquiry_messages (
                sequence INTEGER PRIMARY KEY,
                inquiry_id TEXT NOT NULL REFERENCES inquiries(id) ON DELETE CASCADE,
                author_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                client_id TEXT,
                UNIQUE(inquiry_id, author_id, client_id)
            );
            CREATE INDEX IF NOT EXISTS inquiry_messages_thread
                ON inquiry_messages(inquiry_id, sequence);
            CREATE TABLE IF NOT EXISTS supply_listings (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                details TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(inquiries)")}
        if "transport_to" not in columns:
            db.execute("ALTER TABLE inquiries ADD COLUMN transport_to TEXT")
            db.execute("ALTER TABLE inquiries ADD COLUMN destination_inquiry_id TEXT")
        if "review_status" not in columns:
            db.execute("""
                ALTER TABLE inquiries ADD COLUMN review_status TEXT
                CHECK(review_status IN ('accepted', 'needs_info', 'declined'))
            """)
            db.execute("ALTER TABLE inquiries ADD COLUMN review_reason TEXT")
            db.execute("ALTER TABLE inquiries ADD COLUMN reviewed_at TEXT")
        if "review_quote" not in columns:
            db.execute("ALTER TABLE inquiries ADD COLUMN review_quote TEXT")
        if "demand_id" not in columns:
            db.execute("ALTER TABLE inquiries ADD COLUMN demand_id TEXT")


class IntakeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    material: Literal["PP", "PE", "PET", "철/금속", "혼합 플라스틱", "플라스틱(미상)", "폐지", "슬러지", "기타"]
    monthly_ton: float = Field(gt=0, le=100000, allow_inf_nan=False)
    region: str = Field(min_length=1, max_length=50)
    contamination: str = Field(min_length=1, max_length=100)
    packaging: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=500)
    # 신뢰·매칭 정보. 모두 선택 항목이며 기존 요청서와 호환되도록 기본값을 둡니다.
    legal_status: Literal["확인 전", "폐기물", "순환자원 인정", "부산물"] = "확인 전"
    waste_code: str = Field(default="", max_length=30)
    frequency: Literal["매월 정기", "주기 협의", "1회성"] = "매월 정기"
    address: str = Field(default="", max_length=120)
    price_preference: Literal["협의", "매각 희망", "처리비 지급 가능"] = "협의"
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)


REQUEST_LABELS = {
    "legal_status": "법적 지위(배출업체 입력)", "waste_code": "폐기물 분류번호", "frequency": "발생 주기",
    "address": "상차 주소", "price_preference": "거래 희망",
}


MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CompanySelection(BaseModel):
    company_id: str
    request: IntakeRequest


class InquiryCreate(BaseModel):
    project_id: str
    recipient_id: str
    content: MessageText
    request: IntakeRequest
    destination_inquiry_id: str | None = None


class ReplyCreate(BaseModel):
    content: MessageText
    client_id: UUID


class InquiryReview(BaseModel):
    status: Literal["accepted", "needs_info", "declined"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    # 가공업체의 견적. 배출업체의 '답변 비교'와 거래 조건 초안에 사용합니다.
    price_type: Literal["매입", "처리비", "무상", "협의"] | None = None
    unit_price: int | None = Field(default=None, ge=0, le=100_000_000)
    available_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    def quote(self) -> dict | None:
        if self.price_type is None and self.unit_price is None and self.available_from is None:
            return None
        return {"price_type": self.price_type, "unit_price": self.unit_price, "available_from": self.available_from}


class BatchInquiry(BaseModel):
    project_id: str
    recipient_ids: list[str] = Field(min_length=1, max_length=10)
    content: MessageText
    request: IntakeRequest


class SupplyPublication(BaseModel):
    available_ton: float = Field(gt=0, le=100000, allow_inf_nan=False)


class SupplySearch(BaseModel):
    material: Material | None = None
    monthly_ton: float | None = Field(gt=0, le=100000, allow_inf_nan=False, default=None)
    region: str | None = Field(min_length=1, max_length=50, default=None)
    message: str = Field(max_length=1000, default="")


class SupplyContact(BaseModel):
    content: MessageText


def require_supplier(workspace):
    if workspace in {"local", SUPPLIER}:
        return
    with connect() as db:
        account = get_account(workspace, db)
    if not account or account["role"] != "supplier":
        raise HTTPException(403, "배출업체 작업공간에서 요청서를 작성할 수 있습니다.")


def require_participant(workspace):
    if workspace not in PARTICIPANTS and not workspace.startswith("company-"):
        raise HTTPException(403, "기업 데모 작업공간을 선택하세요.")


def require_owned_project(db, project_id, workspace):
    project = db.execute(
        "SELECT id, title FROM projects WHERE id=? AND organization_id=?", (project_id, workspace)
    ).fetchone()
    if project is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    return project


def require_market_role(db, workspace, role):
    account = get_account(workspace, db) if accounts_enabled() else None
    if account is None or account["role"] != role:
        raise HTTPException(403, "기업 계정의 역할을 확인해 주세요.")


def company_match(company, request: IntakeRequest) -> dict[str, list[str]]:
    matched = []
    unmet = []
    if request.material in company["materials"]:
        matched.append(f"{request.material} 취급")
    else:
        unmet.append(f"{request.material} 미취급")

    if handling_region(company, request.region):
        matched.append(f"{request.region} 배출 건 검토 가능")
    else:
        unmet.append(f"{request.region}은 수거·반입 대상 지역에 포함되지 않습니다.")

    requested = str(request.monthly_ton).removesuffix(".0")
    minimum = company.get("min_ton")
    maximum = company["max_ton"]
    if minimum is not None and request.monthly_ton < minimum:
        unmet.append(f"월 최소 반입량 {str(minimum).removesuffix('.0')}톤에 못 미칩니다 (요청 {requested}톤).")
    elif request.monthly_ton > maximum:
        unmet.append(f"월 최대 수용량 {str(maximum).removesuffix('.0')}톤을 초과합니다 (요청 {requested}톤).")
    else:
        matched.append(f"월 {requested}톤 수용 범위")
    return {"matched": matched, "unmet": unmet}


def candidate_companies(request: IntakeRequest, db, *, include_excluded: bool = False, context: dict | None = None,
                        with_agent: bool = False):
    enabled = invite_codes() if online_enabled() else None
    registered = accounts_enabled()
    companies = [
        {**company, "registered": False, "role": "recycler",
         "inquiry_available": not registered and (enabled is None or bool(enabled.get(company["id"])))}
        for company in COMPANIES.values()
    ]
    if registered:
        companies.extend({
            **company, "registered": True, "role": "recycler", "inquiry_available": True, "route": "가공 상담",
            "intro": "업체가 등록한 취급 조건입니다.",
            "check": "폐기물 성상, 수거 일정 및 반입 조건 확인",
        } for company in registered_companies(db, "recycler"))
    results = []
    for company in companies:
        match = company_match(company, request)
        eligible = not match["unmet"]
        if eligible or include_excluded:
            results.append({
                **company, "match": match,
                "inquiry_available": eligible and company["inquiry_available"],
                "distance_km": distance_km(request.region, company["city"]),
                "trust": company_trust(db, company["id"]),
            })
    if with_agent:
        assessments = matching_agents.assess_companies(request.model_dump(), results, context or {})
        for company in results:
            company["agent"] = assessments.get(company["id"])
    return results


def handling_region(company, region: str) -> bool:
    return any(same_region(region, area) for area in company["regions"])


def transport_destination(db, inquiry_id, project_id, workspace):
    if not accounts_enabled():
        raise HTTPException(404, "운송업체 계정 기능이 꺼져 있습니다.")
    row = db.execute(
        """SELECT i.*, a.company_name, a.recycler_profile
           FROM inquiries i JOIN company_accounts a ON a.id=i.recipient_id AND a.role='recycler'
           WHERE i.id=? AND i.project_id=? AND i.sender_id=?""",
        (inquiry_id, project_id, workspace),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "보낸 가공 문의를 찾을 수 없습니다.")
    return row


def transport_candidates(db, request: IntakeRequest, destination):
    city = json.loads(destination["recycler_profile"])["city"]
    return [{
        **company, "registered": True, "role": "carrier", "inquiry_available": True,
        "route": "폐기물 운송", "transport": "업체 수거",
        "intro": "업체가 등록한 운송 가능 조건입니다.",
        "check": "상차·하차 위치와 차량 일정 확인",
    } for company in registered_companies(db, "carrier")
        if request.material in company["materials"]
        and request.monthly_ton <= company["max_ton"]
        and handling_region(company, request.region) and handling_region(company, city)]


@router.get("/requests/{project_id}/transport")
def recommend_transport(project_id: str, destination_inquiry_id: str, workspace: Workspace):
    require_supplier(workspace)
    with connect() as db:
        require_owned_project(db, project_id, workspace)
        destination = transport_destination(db, destination_inquiry_id, project_id, workspace)
        request = IntakeRequest.model_validate_json(destination["request_snapshot"])
        city = json.loads(destination["recycler_profile"])["city"]
        return {"companies": transport_candidates(db, request, destination), "request": request,
                "destination": f"{city} · {destination['company_name']}"}


@router.get("/requests/{project_id}")
def get_request(project_id: str, workspace: Workspace):
    require_supplier(workspace)
    with connect() as db:
        require_owned_project(db, project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
        contacts = db.execute(
            "SELECT id, recipient_id FROM inquiries WHERE project_id=? AND sender_id=?", (project_id, workspace)
        ).fetchall()
        selection = db.execute(
            "SELECT company_id FROM selected_companies WHERE project_id=?", (project_id,)
        ).fetchone()
        listing = db.execute("SELECT details FROM supply_listings WHERE project_id=?", (project_id,)).fetchone()
    return {
        "request": json.loads(row["details"]) if row else None,
        "selected_company_id": selection["company_id"] if selection else None,
        "inquiries": {contact["recipient_id"]: contact["id"] for contact in contacts},
        "listing": json.loads(listing["details"]) if listing else None,
    }


@router.put("/requests/{project_id}")
def save_request(project_id: str, request: IntakeRequest, workspace: Workspace):
    require_supplier(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        persist_request(db, project_id, request, workspace)
    return request


def persist_request(db, project_id, request: IntakeRequest, workspace):
    project = require_owned_project(db, project_id, workspace)
    if request.attachment_ids:
        placeholders = ",".join("?" for _ in request.attachment_ids)
        found = {row["id"] for row in db.execute(
            f"SELECT id FROM documents WHERE project_id=? AND generated_content IS NULL AND id IN ({placeholders})",
            (project_id, *request.attachment_ids),
        )}
        if found != set(request.attachment_ids):
            raise HTTPException(422, "이 프로젝트에 업로드한 파일만 요청서에 첨부할 수 있습니다.")
    previous = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
    previous_request = IntakeRequest.model_validate_json(previous["details"]) if previous else None
    if previous_request is not None and previous_request != request:
        db.execute("DELETE FROM selected_companies WHERE project_id=?", (project_id,))
        if previous_request.model_dump(exclude={"notes"}) != request.model_dump(exclude={"notes"}):
            db.execute("DELETE FROM supply_listings WHERE project_id=?", (project_id,))
    now = utc_now()
    document = request.model_dump_json()
    db.execute(
        """INSERT INTO intake_requests(project_id, details, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(project_id) DO UPDATE SET details=excluded.details, updated_at=excluded.updated_at""",
        (project_id, document, now),
    )
    db.execute("UPDATE projects SET profile=json_patch(profile, ?), updated_at=? WHERE id=?", (document, now, project_id))
    archive_request(db, project, request, title=TITLE, company=company_name(workspace, db),
                    unchanged=previous_request == request, now=now)


@router.get("/requests/{project_id}/companies")
def recommend(project_id: str, workspace: Workspace, include_excluded: bool = False):
    require_supplier(workspace)
    with connect() as db:
        require_owned_project(db, project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(409, "요청서를 먼저 저장하세요.")
        return candidate_companies(
            IntakeRequest.model_validate_json(row["details"]), db, include_excluded=include_excluded,
            context=project_context(db, project_id), with_agent=True,
        )


def project_context(db, project_id: str) -> dict:
    row = db.execute("SELECT selected_route FROM projects WHERE id=?", (project_id,)).fetchone()
    return {"project_id": project_id, "selected_route": row["selected_route"] if row else None}


@router.get("/requests/{project_id}/review")
def review_request(project_id: str, workspace: Workspace):
    """Agent review card for the saved request (legal status, evidence, unknowns)."""
    require_supplier(workspace)
    with connect() as db:
        require_owned_project(db, project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(409, "요청서를 먼저 저장하세요.")
        context = project_context(db, project_id)
    return matching_agents.assess_request(json.loads(row["details"]), context)


@router.get("/requests/{project_id}/responses")
def compare_responses(project_id: str, workspace: Workspace):
    """Replies from every recycler contacted for this request, for side-by-side comparison."""
    require_supplier(workspace)
    with connect() as db:
        require_owned_project(db, project_id, workspace)
        rows = db.execute(
            """SELECT i.*, (SELECT MAX(created_at) FROM inquiry_messages m
                             WHERE m.inquiry_id=i.id AND m.author_id=i.recipient_id) AS replied_at,
                      d.id AS deal_id, d.status AS deal_status
               FROM inquiries i LEFT JOIN deals d ON d.source_inquiry_id=i.id
               WHERE i.project_id=? AND i.sender_id=? AND i.destination_inquiry_id IS NULL
               ORDER BY i.created_at""",
            (project_id, workspace),
        ).fetchall()
        results = []
        for row in rows:
            snapshot = IntakeRequest.model_validate_json(row["request_snapshot"])
            company = COMPANIES.get(row["recipient_id"])
            city = company["city"] if company else None
            if city is None and accounts_enabled():
                profile = db.execute("SELECT recycler_profile FROM company_accounts WHERE id=?", (row["recipient_id"],)).fetchone()
                city = json.loads(profile["recycler_profile"])["city"] if profile and profile["recycler_profile"] else None
            results.append({
                "inquiry_id": row["id"], "company_id": row["recipient_id"],
                "company_name": company_name(row["recipient_id"], db), "city": city,
                "distance_km": distance_km(snapshot.region, city),
                "trust": company_trust(db, row["recipient_id"]),
                "review": {"status": row["review_status"], "reason": row["review_reason"], "updated_at": row["reviewed_at"]}
                if row["review_status"] else None,
                "quote": json.loads(row["review_quote"]) if row["review_quote"] else None,
                "replied_at": row["replied_at"], "sent_at": row["created_at"],
                "deal_id": row["deal_id"], "deal_status": row["deal_status"],
            })
    return results


@router.put("/requests/{project_id}/selection")
def select_company(project_id: str, selection: CompanySelection, workspace: Workspace):
    require_supplier(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_owned_project(db, project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
        if row is None or IntakeRequest.model_validate_json(row["details"]) != selection.request:
            raise HTTPException(409, "현재 저장된 요청서를 다시 확인한 뒤 업체를 선택하세요.")
        if selection.company_id not in {company["id"] for company in candidate_companies(selection.request, db) if company["inquiry_available"]}:
            raise HTTPException(422, "요청서 조건에 맞고 문의할 수 있는 업체를 선택하세요.")
        db.execute(
            """INSERT INTO selected_companies(project_id, company_id, selected_at) VALUES (?, ?, ?)
               ON CONFLICT(project_id) DO UPDATE SET company_id=excluded.company_id,
               selected_at=excluded.selected_at""",
            (project_id, selection.company_id, utc_now()),
        )
    return {"selected_company_id": selection.company_id}


def company_name(workspace, db):
    account = get_account(workspace, db)
    return account["company_name"] if account else PARTICIPANTS[workspace]


@router.put("/requests/{project_id}/listing")
def publish_supply(project_id: str, data: SupplyPublication, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_market_role(db, workspace, "supplier")
        require_owned_project(db, project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(409, "배출 정보를 먼저 저장해 주세요.")
        supply = IntakeRequest.model_validate_json(row["details"])
        if data.available_ton > supply.monthly_ton:
            raise HTTPException(422, "공개할 물량은 요청서의 월간 발생량 이하여야 합니다.")
        listed = supply.model_copy(update={"monthly_ton": data.available_ton, "notes": "", "address": ""})
        db.execute(
            """INSERT INTO supply_listings(project_id, details, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(project_id) DO UPDATE SET details=excluded.details, updated_at=excluded.updated_at""",
            (project_id, listed.model_dump_json(), utc_now()),
        )
    return listed


@router.delete("/requests/{project_id}/listing")
def unpublish_supply(project_id: str, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_market_role(db, workspace, "supplier")
        require_owned_project(db, project_id, workspace)
        db.execute("DELETE FROM supply_listings WHERE project_id=?", (project_id,))
    return {"ok": True}


@router.post("/supplies/search")
def search_supplies(data: SupplySearch, workspace: Workspace):
    criteria = data.model_dump(exclude={"message"}, exclude_none=True)
    if data.message:
        parsed = merge_request_profile(criteria, data.message)
        criteria.update({key: parsed[key] for key in ("material", "monthly_ton", "region") if key in parsed})
        city = re.search(rf"(?<![가-힣])({CITIES})(?:시|군)?\s*(?:쪽|근처|인근|지역|에서|만|으로|위주)", data.message)
        if city:
            criteria["region"] = city[1]
        elif "전국" in data.message or "지역 상관없" in data.message:
            criteria.pop("region", None)
    with connect() as db:
        require_market_role(db, workspace, "recycler")
        rows = db.execute(
            """SELECT s.*, a.company_name, p.organization_id, i.id AS inquiry_id
               FROM supply_listings s JOIN projects p ON p.id=s.project_id
               JOIN company_accounts a ON a.id=p.organization_id AND a.role='supplier'
               LEFT JOIN inquiries i ON i.project_id=s.project_id AND i.recipient_id=?
               ORDER BY s.updated_at DESC, s.project_id""",
            (workspace,),
        )
        results = []
        for row in rows:
            supply = IntakeRequest.model_validate_json(row["details"])
            if criteria.get("material") and supply.material != criteria["material"]:
                continue
            if criteria.get("region") and not same_region(supply.region, criteria["region"]):
                continue
            results.append({
                "id": row["project_id"], "name": row["company_name"], "inquiry_id": row["inquiry_id"],
                **supply.model_dump(exclude={"notes", "address", "attachment_ids"}),
                "attachment_count": len(supply.attachment_ids),
                "trust": company_trust(db, row["organization_id"]),
            })
    amount = criteria.get("monthly_ton")
    if amount:
        results.sort(key=lambda item: (
            item["monthly_ton"] < amount, abs(item["monthly_ton"] - amount),
        ))
    return {"criteria": criteria, "results": results}


@router.post("/supplies/{project_id}/contact")
def contact_supply(project_id: str, data: SupplyContact, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_market_role(db, workspace, "recycler")
        row = db.execute(
            """SELECT s.details, p.organization_id FROM supply_listings s JOIN projects p ON p.id=s.project_id
               WHERE s.project_id=?""", (project_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "현재 공개 중인 배출 물량이 없습니다.")
        existing = db.execute("SELECT id FROM inquiries WHERE project_id=? AND recipient_id=?", (project_id, workspace)).fetchone()
        if existing:
            return {"id": existing["id"]}
        inquiry_id, now = new_id(), utc_now()
        db.execute(
            """INSERT INTO inquiries(id, project_id, sender_id, recipient_id, request_snapshot, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (inquiry_id, project_id, row["organization_id"], workspace, row["details"], now),
        )
        db.execute(
            "INSERT INTO inquiry_messages(inquiry_id, author_id, content, created_at) VALUES (?, ?, ?, ?)",
            (inquiry_id, workspace, data.content, now),
        )
    return {"id": inquiry_id}


def thread_json(row, db):
    thread = dict(row)
    thread["sender_name"] = company_name(row["sender_id"], db)
    thread["recipient_name"] = company_name(row["recipient_id"], db)
    recipient = get_account(row["recipient_id"], db)
    thread["recipient_role"] = recipient["role"] if recipient else "recycler"
    thread["can_plan_transport"] = bool(accounts_enabled() and recipient and recipient["role"] == "recycler")
    status = thread.pop("review_status")
    reason = thread.pop("review_reason")
    reviewed_at = thread.pop("reviewed_at")
    quote = thread.pop("review_quote", None)
    thread["review"] = {
        "status": status, "reason": reason, "updated_at": reviewed_at,
        "quote": json.loads(quote) if quote else None,
    } if status else None
    deal = db.execute("SELECT id, status FROM deals WHERE source_inquiry_id=?", (row["id"],)).fetchone()
    thread["deal_id"] = deal["id"] if deal else None
    thread["deal_status"] = deal["status"] if deal else None
    thread["can_start_deal"] = bool(
        deal is None and not row["destination_inquiry_id"] and thread["recipient_role"] == "recycler"
        and status != "declined"
    )
    thread["recipient_trust"] = company_trust(db, row["recipient_id"])
    return thread


def require_thread(db, inquiry_id, workspace):
    row = db.execute(
        "SELECT * FROM inquiries WHERE id=? AND (sender_id=? OR recipient_id=?)",
        (inquiry_id, workspace, workspace),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")
    return row


@router.get("/inquiries")
def list_inquiries(workspace: Workspace):
    require_participant(workspace)
    with connect() as db:
        rows = db.execute(
            """SELECT i.id, i.project_id, i.sender_id, i.recipient_id, i.created_at, i.transport_to,
                      i.destination_inquiry_id, i.demand_id,
                      i.review_status, i.review_reason, i.reviewed_at, i.review_quote,
                      (SELECT author_id FROM inquiry_messages WHERE inquiry_id=i.id ORDER BY sequence LIMIT 1) AS initiated_by,
                      json_extract(i.request_snapshot, '$.material') AS material,
                      m.content AS last_message, m.created_at AS last_at
               FROM inquiries i
               JOIN inquiry_messages m ON m.sequence = (
                   SELECT sequence FROM inquiry_messages WHERE inquiry_id=i.id ORDER BY sequence DESC LIMIT 1
               )
               WHERE i.sender_id=? OR i.recipient_id=?
               ORDER BY m.sequence DESC""",
            (workspace, workspace),
        ).fetchall()
        return [thread_json(row, db) for row in rows]


@router.post("/inquiries")
def send_inquiry(data: InquiryCreate, workspace: Workspace):
    require_supplier(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_owned_project(db, data.project_id, workspace)
        existing = db.execute(
            "SELECT id, destination_inquiry_id FROM inquiries WHERE project_id=? AND recipient_id=? AND sender_id=?",
            (data.project_id, data.recipient_id, workspace),
        ).fetchone()
        if existing:
            if existing["destination_inquiry_id"] != data.destination_inquiry_id:
                raise HTTPException(409, "이 프로젝트에서 같은 운송업체에 다른 목적지로 문의한 기록이 있습니다. 새 프로젝트에서 문의해 주세요.")
            return {"id": existing["id"]}
        transport_to = None
        if data.destination_inquiry_id:
            destination = transport_destination(db, data.destination_inquiry_id, data.project_id, workspace)
            snapshot = IntakeRequest.model_validate_json(destination["request_snapshot"])
            if snapshot != data.request:
                raise HTTPException(409, "가공업체에 보낸 요청서를 다시 확인해 주세요.")
            if data.recipient_id not in {company["id"] for company in transport_candidates(db, snapshot, destination)}:
                raise HTTPException(422, "출발지와 목적지의 운송 조건에 맞는 업체를 선택하세요.")
            city = json.loads(destination["recycler_profile"])["city"]
            transport_to = f"{city} · {destination['company_name']}"
        else:
            row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (data.project_id,)).fetchone()
            if row is None or IntakeRequest.model_validate_json(row["details"]) != data.request:
                raise HTTPException(409, "저장된 요청서가 변경되었습니다. 새로고침 후 다시 확인하세요.")
            if data.recipient_id not in {company["id"] for company in candidate_companies(data.request, db) if company["inquiry_available"]}:
                raise HTTPException(422, "현재 요청서 조건에 맞고 문의할 수 있는 업체를 선택하세요.")
            selected = db.execute(
                "SELECT company_id FROM selected_companies WHERE project_id=?", (data.project_id,)
            ).fetchone()
            if selected is None or selected["company_id"] != data.recipient_id:
                raise HTTPException(409, "업체 상세 화면에서 이 업체를 선택한 후 요청서를 보내세요.")
        inquiry_id, now = new_id(), utc_now()
        db.execute(
            """INSERT INTO inquiries(id, project_id, sender_id, recipient_id, request_snapshot, created_at,
                                    transport_to, destination_inquiry_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (inquiry_id, data.project_id, workspace, data.recipient_id, data.request.model_dump_json(), now,
             transport_to, data.destination_inquiry_id),
        )
        db.execute(
            "INSERT INTO inquiry_messages(inquiry_id, author_id, content, created_at) VALUES (?, ?, ?, ?)",
            (inquiry_id, workspace, data.content, now),
        )
    return {"id": inquiry_id}


@router.post("/inquiries/batch")
def send_batch(data: BatchInquiry, workspace: Workspace):
    """Send the same request to several recyclers at once (견적 일괄 요청)."""
    require_supplier(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_owned_project(db, data.project_id, workspace)
        row = db.execute("SELECT details FROM intake_requests WHERE project_id=?", (data.project_id,)).fetchone()
        if row is None or IntakeRequest.model_validate_json(row["details"]) != data.request:
            raise HTTPException(409, "저장된 요청서가 변경되었습니다. 새로고침 후 다시 확인하세요.")
        eligible = {company["id"]: company for company in candidate_companies(data.request, db) if company["inquiry_available"]}
        created, skipped = [], []
        for recipient in dict.fromkeys(data.recipient_ids):
            existing = db.execute(
                "SELECT id FROM inquiries WHERE project_id=? AND recipient_id=?", (data.project_id, recipient),
            ).fetchone()
            if existing:
                skipped.append({"recipient_id": recipient, "id": existing["id"], "reason": "이미 문의한 업체입니다."})
                continue
            if recipient not in eligible:
                skipped.append({"recipient_id": recipient, "id": None, "reason": "요청서 조건에 맞지 않거나 문의할 수 없는 업체입니다."})
                continue
            inquiry_id, now = new_id(), utc_now()
            db.execute(
                """INSERT INTO inquiries(id, project_id, sender_id, recipient_id, request_snapshot, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (inquiry_id, data.project_id, workspace, recipient, data.request.model_dump_json(), now),
            )
            db.execute(
                "INSERT INTO inquiry_messages(inquiry_id, author_id, content, created_at) VALUES (?, ?, ?, ?)",
                (inquiry_id, workspace, data.content, now),
            )
            created.append({"recipient_id": recipient, "id": inquiry_id, "name": eligible[recipient]["name"]})
    return {"created": created, "skipped": skipped}


def request_attachments(project_id: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    with connect() as db:
        rows = db.execute(
            f"SELECT id, name, size FROM documents WHERE project_id=? AND id IN ({','.join('?' * len(ids))})",
            (project_id, *ids),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/inquiries/{inquiry_id}/files/{document_id}")
def download_inquiry_file(inquiry_id: str, document_id: str, workspace: Workspace):
    """Photos and analysis sheets the supplier attached to the request."""
    require_participant(workspace)
    with connect() as db:
        row = require_thread(db, inquiry_id, workspace)
        snapshot = json.loads(row["request_snapshot"])
        document = db.execute(
            "SELECT * FROM documents WHERE id=? AND project_id=?", (document_id, row["project_id"]),
        ).fetchone() if document_id in snapshot.get("attachment_ids", []) else None
    if document is None or not (data_dir() / "uploads" / document["stored_name"]).is_file():
        raise HTTPException(404, "첨부 파일을 찾을 수 없습니다.")
    return FileResponse(data_dir() / "uploads" / document["stored_name"], filename=document["name"],
                        media_type="application/octet-stream")


@router.get("/inquiries/{inquiry_id}")
def get_inquiry(inquiry_id: str, workspace: Workspace):
    require_participant(workspace)
    with connect() as db:
        thread = thread_json(require_thread(db, inquiry_id, workspace), db)
        messages = db.execute(
            "SELECT sequence, author_id, content, created_at FROM inquiry_messages WHERE inquiry_id=? ORDER BY sequence",
            (inquiry_id,),
        ).fetchall()
    thread["request"] = json.loads(thread.pop("request_snapshot"))
    thread["attachments"] = request_attachments(thread["project_id"], thread["request"].get("attachment_ids", []))
    thread["messages"] = [dict(message) for message in messages]
    thread["initiated_by"] = messages[0]["author_id"] if messages else thread["sender_id"]
    return thread


@router.post("/inquiries/{inquiry_id}/messages", status_code=201)
def reply(inquiry_id: str, data: ReplyCreate, workspace: Workspace):
    require_participant(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_thread(db, inquiry_id, workspace)
        db.execute(
            """INSERT INTO inquiry_messages(inquiry_id, author_id, content, created_at, client_id)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(inquiry_id, author_id, client_id) DO NOTHING""",
            (inquiry_id, workspace, data.content, utc_now(), str(data.client_id)),
        )
    return {"ok": True}


@router.put("/inquiries/{inquiry_id}/review")
def save_inquiry_review(inquiry_id: str, data: InquiryReview, workspace: Workspace):
    require_participant(workspace)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inquiry = require_thread(db, inquiry_id, workspace)
        account = get_account(workspace, db)
        recycler = account["role"] == "recycler" if account else workspace in COMPANIES
        if inquiry["recipient_id"] != workspace or not recycler or inquiry["destination_inquiry_id"]:
            raise HTTPException(403, "이 문의의 가공업체만 검토 결과를 남길 수 있습니다.")
        quote = json.dumps(data.quote(), ensure_ascii=False) if data.quote() else None
        result = {"status": data.status, "reason": data.reason, "quote": data.quote()}
        if (inquiry["review_status"], inquiry["review_reason"], inquiry["review_quote"]) == (data.status, data.reason, quote):
            return {**result, "updated_at": inquiry["reviewed_at"]}
        reviewed_at = utc_now()
        db.execute(
            "UPDATE inquiries SET review_status=?, review_reason=?, reviewed_at=?, review_quote=? WHERE id=?",
            (data.status, data.reason, reviewed_at, quote, inquiry_id),
        )
    return {**result, "updated_at": reviewed_at}


def word_document(data: IntakeRequest, sender: str):
    return word_download(render_request_document(data, title=TITLE, company=sender), FILENAME)


@router.get("/requests/{project_id}/download")
def download_request(project_id: str, workspace: Workspace):
    result = get_request(project_id, workspace)
    if result["request"] is None:
        raise HTTPException(404, "저장한 요청서가 없습니다.")
    with connect() as db:
        sender = company_name(workspace, db)
    return word_document(IntakeRequest.model_validate(result["request"]), sender)


@router.get("/inquiries/{inquiry_id}/attachment")
def download_attachment(inquiry_id: str, workspace: Workspace):
    require_participant(workspace)
    with connect() as db:
        row = require_thread(db, inquiry_id, workspace)
        sender = company_name(row["sender_id"], db)
    return word_document(IntakeRequest.model_validate_json(row["request_snapshot"]), sender)
