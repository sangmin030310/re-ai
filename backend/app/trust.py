"""Company trust data: permits, operator verification and activity stats.

Permit details are entered by each company. Only an operator account
(``REAI_OPERATOR_USERNAMES``) can mark them as checked. Editing permit fields
removes the previous check so a badge always refers to the current values.
"""
import json
import os
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .accounts import get_account
from .db import connect, utc_now
from .workspaces import accounts_enabled, current_workspace

router = APIRouter(tags=["trust"])
Workspace = Annotated[str, Depends(current_workspace)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
PERMIT_TYPES = (
    "폐기물 중간재활용업", "폐기물 최종재활용업", "폐기물 종합재활용업",
    "폐기물 수집·운반업", "폐기물 중간처분업", "순환자원 인정", "기타",
)


def init_trust():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS company_trust (
                account_id TEXT PRIMARY KEY REFERENCES company_accounts(id) ON DELETE CASCADE,
                details TEXT NOT NULL DEFAULT '{}',
                verified_at TEXT,
                verified_by TEXT,
                verify_note TEXT
            )
        """)


class TrustDetails(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    business_number: Text = ""
    address: Text = ""
    permit_type: Literal[PERMIT_TYPES] | Literal[""] = ""
    permit_number: Text = ""
    permit_valid_until: date | None = None
    price_model: Literal["매입", "처리비", "협의", ""] = ""


class Verification(BaseModel):
    verified: bool
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


def operator_usernames() -> set[str]:
    return {name.strip().lower() for name in os.getenv("REAI_OPERATOR_USERNAMES", "").split(",") if name.strip()}


def is_operator(workspace: str, db) -> bool:
    if not accounts_enabled() or not workspace.startswith("company-"):
        return False
    row = db.execute("SELECT username FROM company_accounts WHERE id=?", (workspace,)).fetchone()
    return bool(row and row["username"].lower() in operator_usernames())


def require_operator(db, workspace):
    if not is_operator(workspace, db):
        raise HTTPException(403, "운영자 계정만 허가 정보를 확인할 수 있습니다.")


def trust_table_ready(db) -> bool:
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_trust'").fetchone())


def company_stats(db, company_id: str) -> dict:
    completed = db.execute(
        """SELECT COUNT(*) FROM deals WHERE status='completed'
           AND (supplier_id=? OR recycler_id=? OR carrier_id=?)""",
        (company_id, company_id, company_id),
    ).fetchone()[0]
    received, replied = db.execute(
        """SELECT COUNT(*), COALESCE(SUM(EXISTS(
               SELECT 1 FROM inquiry_messages m WHERE m.inquiry_id=i.id AND m.author_id=i.recipient_id
           )), 0)
           FROM inquiries i WHERE i.recipient_id=?
             AND (SELECT author_id FROM inquiry_messages WHERE inquiry_id=i.id ORDER BY sequence LIMIT 1) != i.recipient_id""",
        (company_id,),
    ).fetchone()
    return {
        "completed_deals": completed,
        "inquiries_received": received,
        "reply_rate": round(replied / received * 100) if received else None,
    }


def company_trust(db, company_id: str) -> dict:
    """Trust summary shown on company cards. Demo companies have no permit data."""
    details, verified_at, note = {}, None, None
    if company_id.startswith("company-") and trust_table_ready(db):
        row = db.execute("SELECT * FROM company_trust WHERE account_id=?", (company_id,)).fetchone()
        if row:
            details, verified_at, note = json.loads(row["details"]), row["verified_at"], row["verify_note"]
    valid_until = details.get("permit_valid_until")
    expired = bool(valid_until and valid_until < date.today().isoformat())
    registered = bool(details.get("permit_type") and details.get("permit_number"))
    return {
        "permit_type": details.get("permit_type") or None,
        "permit_number": details.get("permit_number") or None,
        "permit_valid_until": valid_until,
        "price_model": details.get("price_model") or None,
        "permit_registered": registered,
        "permit_verified": bool(registered and verified_at and not expired),
        "permit_expired": expired,
        "verified_at": verified_at,
        "verify_note": note,
        "stats": company_stats(db, company_id),
    }


def require_account(db, workspace):
    if not accounts_enabled():
        raise HTTPException(404, "기업 계정 기능이 꺼져 있습니다.")
    account = get_account(workspace, db)
    if account is None:
        raise HTTPException(401, "Re AI 계정으로 로그인해 주세요.")
    return account


@router.get("/api/accounts/trust")
def get_my_trust(workspace: Workspace):
    with connect() as db:
        require_account(db, workspace)
        row = db.execute("SELECT details FROM company_trust WHERE account_id=?", (workspace,)).fetchone()
        return {
            "details": TrustDetails.model_validate_json(row["details"]) if row else TrustDetails(),
            "trust": company_trust(db, workspace),
            "permit_types": PERMIT_TYPES,
            "operator": is_operator(workspace, db),
        }


@router.put("/api/accounts/trust")
def save_my_trust(data: TrustDetails, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_account(db, workspace)
        row = db.execute("SELECT details, verified_at FROM company_trust WHERE account_id=?", (workspace,)).fetchone()
        permit_keys = ("business_number", "permit_type", "permit_number", "permit_valid_until")
        previous = TrustDetails.model_validate_json(row["details"]) if row else TrustDetails()
        keep_check = row and row["verified_at"] and all(getattr(previous, key) == getattr(data, key) for key in permit_keys)
        db.execute(
            """INSERT INTO company_trust(account_id, details, verified_at, verified_by, verify_note)
               VALUES (?, ?, NULL, NULL, NULL)
               ON CONFLICT(account_id) DO UPDATE SET details=excluded.details,
                 verified_at=CASE WHEN ? THEN company_trust.verified_at END,
                 verified_by=CASE WHEN ? THEN company_trust.verified_by END,
                 verify_note=CASE WHEN ? THEN company_trust.verify_note END""",
            (workspace, data.model_dump_json(), bool(keep_check), bool(keep_check), bool(keep_check)),
        )
        return {"details": data, "trust": company_trust(db, workspace)}


@router.get("/api/operator/companies")
def operator_companies(workspace: Workspace):
    with connect() as db:
        require_operator(db, workspace)
        rows = db.execute(
            """SELECT a.id, a.company_name, a.role, t.details FROM company_accounts a
               LEFT JOIN company_trust t ON t.account_id=a.id ORDER BY a.rowid DESC"""
        ).fetchall()
        return [{
            "id": row["id"], "name": row["company_name"], "role": row["role"],
            "details": json.loads(row["details"]) if row["details"] else {},
            "trust": company_trust(db, row["id"]),
        } for row in rows]


@router.put("/api/operator/companies/{company_id}/verification")
def verify_company(company_id: str, data: Verification, workspace: Workspace):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_operator(db, workspace)
        row = db.execute("SELECT details FROM company_trust WHERE account_id=?", (company_id,)).fetchone()
        details = json.loads(row["details"]) if row else {}
        if data.verified and not (details.get("permit_type") and details.get("permit_number")):
            raise HTTPException(409, "업체가 허가 종류와 허가번호를 먼저 등록해야 합니다.")
        db.execute(
            "UPDATE company_trust SET verified_at=?, verified_by=?, verify_note=? WHERE account_id=?",
            (utc_now() if data.verified else None, workspace if data.verified else None, data.note or None, company_id),
        )
        return company_trust(db, company_id)
