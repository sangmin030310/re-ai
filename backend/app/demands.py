"""Demand posts: a recycler announces the material it wants, suppliers respond.

This is the reverse of supply listings (배출업체 '남은 물량 공개'). A supplier answers
with a saved request from one of its projects, which opens a normal inquiry thread
(sender = supplier, recipient = recycler), so review, quotes and deals work the same way.
"""
import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .accounts import Material
from .db import connect, new_id, utc_now
from .regions import distance_km, same_region
from .trust import company_trust
from .workspaces import current_workspace

router = APIRouter(prefix="/api/matching/demands", tags=["demands"])
Workspace = Annotated[str, Depends(current_workspace)]
Region = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


def init_demands():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS demand_posts (
                id TEXT PRIMARY KEY,
                recycler_id TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


class DemandPost(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    material: Material
    monthly_ton: float = Field(gt=0, le=100000, allow_inf_nan=False)
    regions: list[Region] = Field(min_length=1, max_length=12)
    price_type: Literal["매입", "처리비", "무상", "협의"] = "협의"
    unit_price: int | None = Field(default=None, ge=0, le=100_000_000)
    conditions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    until: date | None = None


class DemandReply(BaseModel):
    project_id: str
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def require_role(db, workspace, role):
    from .deals import role_of

    if role_of(db, workspace) != role:
        names = {"recycler": "가공업체", "supplier": "배출업체"}
        raise HTTPException(403, f"{names[role]} 계정에서 이용할 수 있습니다.")


def demand_json(db, row, workspace, origin: str | None = None) -> dict:
    from .matching import company_name

    from .deals import company_city

    details = json.loads(row["details"])
    city = company_city(db, row["recycler_id"])
    responded = db.execute(
        "SELECT id FROM inquiries WHERE demand_id=? AND sender_id=? LIMIT 1", (row["id"], workspace),
    ).fetchone()
    responses = db.execute("SELECT COUNT(*) FROM inquiries WHERE demand_id=?", (row["id"],)).fetchone()[0] \
        if row["recycler_id"] == workspace else None
    return {
        "id": row["id"], "recycler_id": row["recycler_id"], "recycler_name": company_name(row["recycler_id"], db),
        "city": city, "status": row["status"], **details,
        "expired": bool(details.get("until") and details["until"] < date.today().isoformat()),
        "distance_km": distance_km(origin, city) if origin else None,
        "trust": company_trust(db, row["recycler_id"]),
        "my_inquiry_id": responded["id"] if responded else None,
        "response_count": responses,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


@router.get("")
def list_demands(workspace: Workspace, mine: bool = False, project_id: str | None = None,
                 material: str | None = None, region: str | None = None):
    from .matching import IntakeRequest

    with connect() as db:
        if mine:
            require_role(db, workspace, "recycler")
            rows = db.execute(
                "SELECT * FROM demand_posts WHERE recycler_id=? ORDER BY status, updated_at DESC", (workspace,),
            ).fetchall()
            return [demand_json(db, row, workspace) for row in rows]
        require_role(db, workspace, "supplier")
        origin = region
        if project_id:
            saved = db.execute(
                """SELECT r.details FROM intake_requests r JOIN projects p ON p.id=r.project_id
                   WHERE r.project_id=? AND p.organization_id=?""", (project_id, workspace),
            ).fetchone()
            if saved:
                request = IntakeRequest.model_validate_json(saved["details"])
                material, origin = material or request.material, origin or request.region
        rows = db.execute("SELECT * FROM demand_posts WHERE status='open' ORDER BY updated_at DESC").fetchall()
        results = []
        for row in rows:
            details = json.loads(row["details"])
            if details.get("until") and details["until"] < date.today().isoformat():
                continue
            if material and details["material"] != material:
                continue
            if origin and not any(same_region(origin, area) for area in details["regions"]):
                continue
            results.append(demand_json(db, row, workspace, origin))
        results.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 0))
        return results


@router.post("", status_code=201)
def create_demand(data: DemandPost, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_role(db, workspace, "recycler")
        demand_id, now = new_id(), utc_now()
        db.execute(
            "INSERT INTO demand_posts(id, recycler_id, details, status, created_at, updated_at) VALUES (?, ?, ?, 'open', ?, ?)",
            (demand_id, workspace, data.model_dump_json(), now, now),
        )
        row = db.execute("SELECT * FROM demand_posts WHERE id=?", (demand_id,)).fetchone()
        return demand_json(db, row, workspace)


def own_demand(db, demand_id, workspace):
    row = db.execute("SELECT * FROM demand_posts WHERE id=? AND recycler_id=?", (demand_id, workspace)).fetchone()
    if row is None:
        raise HTTPException(404, "수요 공고를 찾을 수 없습니다.")
    return row


@router.put("/{demand_id}")
def update_demand(demand_id: str, data: DemandPost, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        own_demand(db, demand_id, workspace)
        db.execute("UPDATE demand_posts SET details=?, status='open', updated_at=? WHERE id=?",
                   (data.model_dump_json(), utc_now(), demand_id))
        return demand_json(db, own_demand(db, demand_id, workspace), workspace)


@router.delete("/{demand_id}")
def close_demand(demand_id: str, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        own_demand(db, demand_id, workspace)
        db.execute("UPDATE demand_posts SET status='closed', updated_at=? WHERE id=?", (utc_now(), demand_id))
        return demand_json(db, own_demand(db, demand_id, workspace), workspace)


@router.post("/{demand_id}/reply")
def reply_to_demand(demand_id: str, data: DemandReply, workspace: Workspace):
    """Supplier answers a demand post with its saved request."""
    from .matching import IntakeRequest

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_role(db, workspace, "supplier")
        demand = db.execute("SELECT * FROM demand_posts WHERE id=? AND status='open'", (demand_id,)).fetchone()
        if demand is None:
            raise HTTPException(404, "마감되었거나 없는 수요 공고입니다.")
        saved = db.execute(
            """SELECT r.details FROM intake_requests r JOIN projects p ON p.id=r.project_id
               WHERE r.project_id=? AND p.organization_id=?""", (data.project_id, workspace),
        ).fetchone()
        if saved is None:
            raise HTTPException(409, "답할 프로젝트의 요청서를 먼저 저장해 주세요.")
        request = IntakeRequest.model_validate_json(saved["details"])
        details = json.loads(demand["details"])
        if request.material != details["material"]:
            raise HTTPException(422, f"이 공고는 {details['material']}을(를) 찾고 있습니다. 요청서의 재질을 확인해 주세요.")
        existing = db.execute(
            "SELECT id FROM inquiries WHERE project_id=? AND recipient_id=?", (data.project_id, demand["recycler_id"]),
        ).fetchone()
        if existing:
            db.execute("UPDATE inquiries SET demand_id=COALESCE(demand_id, ?) WHERE id=?", (demand_id, existing["id"]))
            return {"id": existing["id"]}
        inquiry_id, now = new_id(), utc_now()
        db.execute(
            """INSERT INTO inquiries(id, project_id, sender_id, recipient_id, request_snapshot, created_at, demand_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (inquiry_id, data.project_id, workspace, demand["recycler_id"], request.model_dump_json(), now, demand_id),
        )
        db.execute(
            "INSERT INTO inquiry_messages(inquiry_id, author_id, content, created_at) VALUES (?, ?, ?, ?)",
            (inquiry_id, workspace, data.content, now),
        )
        return {"id": inquiry_id}
