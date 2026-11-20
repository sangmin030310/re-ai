"""Local Re AI company accounts and browser sessions."""
import hashlib
import json
import re
import secrets
import time
from threading import BoundedSemaphore, Lock
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .db import connect, new_id

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
COOKIE = "reai_company_session"
SESSION_SECONDS = 7 * 86400
LOOPBACK_HOST = re.compile(r"(?:127\.0\.0\.1|localhost)(?::[0-9]+)?")
TOKEN_FORMAT = re.compile(r"[a-zA-Z0-9_-]{43}")
attempts: dict[str, tuple[float, int]] = {}
attempt_lock = Lock()
password_workers = BoundedSemaphore(4)

Material = Literal["PP", "PE", "PET", "철/금속", "혼합 플라스틱", "플라스틱(미상)", "폐지", "슬러지", "기타"]
Region = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Role = Literal["supplier", "recycler", "carrier"]
ROLE_LABELS = {"supplier": "배출업체", "recycler": "가공업체", "carrier": "운송업체"}
ACCOUNT_COLUMNS = """
    id TEXT PRIMARY KEY,
    username TEXT COLLATE NOCASE NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('supplier', 'recycler', 'carrier')),
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    recycler_profile TEXT
"""


def init_accounts():
    with connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT sql FROM sqlite_master WHERE name='company_accounts' AND type='table'").fetchone()
        if current is None:
            db.execute(f"CREATE TABLE company_accounts ({ACCOUNT_COLUMNS})")
        elif "'carrier'" not in current["sql"]:
            db.execute(f"CREATE TABLE company_accounts_new ({ACCOUNT_COLUMNS})")
            db.execute("INSERT INTO company_accounts_new SELECT * FROM company_accounts")
            db.execute("DROP TABLE company_accounts")
            db.execute("ALTER TABLE company_accounts_new RENAME TO company_accounts")
        db.execute("""
            CREATE TABLE IF NOT EXISTS company_sessions (
                token_hash BLOB PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES company_accounts(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            )
        """)
        if db.execute("PRAGMA foreign_key_check(company_sessions)").fetchone():
            raise RuntimeError("기업 계정 세션을 확인할 수 없습니다.")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class CompanyProfile(BaseModel):
    city: Region
    regions: list[Region] = Field(min_length=1, max_length=12)
    materials: list[Material] = Field(min_length=1, max_length=9)
    max_ton: float = Field(ge=0.001, le=100000, allow_inf_nan=False)


class RecyclerProfile(CompanyProfile):
    transport: Literal["업체 수거", "배출업체 직접 운반"]
    min_ton: float | None = Field(default=None, ge=0.001, le=100000, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.min_ton is not None and self.min_ton > self.max_ton:
            raise ValueError("월 최소 반입량은 최대 수용량 이하여야 합니다.")
        return self


class Registration(Credentials):
    model_config = ConfigDict(extra="forbid")
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    role: Role
    recovery_email: str = Field(min_length=1, max_length=254)
    signup_email_challenge: str = Field(pattern=r"^[a-f0-9]{32}$")
    signup_email_code: str = Field(pattern=r"^[0-9]{6}$")
    recycler_profile: RecyclerProfile | None = None
    carrier_profile: CompanyProfile | None = None


def get_account(workspace: str, db):
    if workspace.startswith("company-"):
        return db.execute(
            "SELECT id, username, company_name, role FROM company_accounts WHERE id=?", (workspace,)
        ).fetchone()
    return None


def registered_companies(db, role: Role):
    rows = db.execute(
        "SELECT id, company_name, recycler_profile FROM company_accounts WHERE role=? ORDER BY rowid", (role,)
    )
    for row in rows:
        yield {**json.loads(row["recycler_profile"]), "id": row["id"], "name": row["company_name"]}


def is_local_account_request(request: Request) -> bool:
    return bool(LOOPBACK_HOST.fullmatch(request.headers.get("host", ""))) and not request.headers.get("cf-ray")


def require_account_origin(request: Request) -> bool:
    from .workspaces import accounts_enabled

    if not accounts_enabled():
        raise HTTPException(404, "기업 계정 기능이 꺼져 있습니다.")
    host = request.headers.get("host", "")
    local = is_local_account_request(request)
    scheme = "http" if local else "https"
    if not host or request.headers.get("origin") != f"{scheme}://{host}":
        raise HTTPException(403, "Re AI 화면에서 다시 시도해 주세요.")
    return not local


def hash_password(password: str, salt: bytes) -> bytes:
    if not password_workers.acquire(blocking=False):
        raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3, maxmem=64 * 1024 * 1024)
    finally:
        password_workers.release()


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def session_workspace(request: Request) -> str | None:
    token = request.cookies.get(COOKIE, "")
    if not TOKEN_FORMAT.fullmatch(token):
        return None
    with connect() as db:
        row = db.execute(
            "SELECT account_id FROM company_sessions WHERE token_hash=? AND expires_at>?",
            (token_hash(token), int(time.time())),
        ).fetchone()
    if row is None:
        return None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_account_origin(request)
    return row["account_id"]


def auth_attempt(username: str):
    now = time.monotonic()
    with attempt_lock:
        for key, (end, _) in list(attempts.items()):
            if end <= now:
                del attempts[key]
        end, count = attempts.get(username, (now + 300, 0))
        if count >= 10 or (username not in attempts and len(attempts) >= 1024):
            raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
        attempts[username] = (end, count + 1)


def login_response(response: Response, request: Request, db, account, secure: bool):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM company_sessions WHERE expires_at<=?", (now,))
    previous = request.cookies.get(COOKIE, "")
    if TOKEN_FORMAT.fullmatch(previous):
        db.execute("DELETE FROM company_sessions WHERE token_hash=?", (token_hash(previous),))
    db.execute(
        "INSERT INTO company_sessions(token_hash, account_id, expires_at) VALUES (?, ?, ?)",
        (token_hash(token), account["id"], now + SESSION_SECONDS),
    )
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=secure)
    response.headers["Cache-Control"] = "no-store"
    return account_payload(account)


def account_payload(account):
    from .trust import operator_usernames

    role_label = ROLE_LABELS[account["role"]]
    username = account["username"] if "username" in account.keys() else ""
    return {"id": account["id"], "label": f"{role_label} · {account['company_name']}", "role": account["role"],
            "company_name": account["company_name"], "operator": bool(username and username.lower() in operator_usernames())}


@router.post("/register", status_code=201)
def register(data: Registration, request: Request, response: Response):
    from .account_recovery import clean_email, consume_signup_email_code

    secure = require_account_origin(request)
    if ((data.role == "recycler") != (data.recycler_profile is not None)
            or (data.role == "carrier") != (data.carrier_profile is not None)):
        raise HTTPException(422, "업체 유형에 맞는 취급 또는 운송 조건을 입력해 주세요.")
    profile = data.recycler_profile or data.carrier_profile
    email = clean_email(data.recovery_email)
    username = data.username.lower()
    auth_attempt(f"register:{username}")
    account = {"id": f"company-{new_id()}", "username": data.username.lower(), "company_name": data.company_name, "role": data.role}
    salt = secrets.token_bytes(16)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if consume_signup_email_code(db, email, data.signup_email_challenge, data.signup_email_code):
            if db.execute("SELECT 1 FROM company_recovery_emails WHERE email=?", (email,)).fetchone():
                raise HTTPException(409, "이미 인증된 이메일입니다. 로그인하거나 아이디 찾기를 이용해 주세요.")
            row = db.execute(
                """INSERT INTO company_accounts(id, username, company_name, role, salt, password_hash, recycler_profile)
                   VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(username) DO NOTHING RETURNING id""",
                (account["id"], username, account["company_name"], account["role"], salt,
                 hash_password(data.password, salt), profile.model_dump_json() if profile else None),
            ).fetchone()
            if row is None:
                raise HTTPException(409, "이미 사용 중인 아이디입니다.")
            db.execute("INSERT INTO company_recovery_emails(account_id, email) VALUES (?, ?)", (account["id"], email))
            db.execute("DELETE FROM company_signup_email_codes WHERE email=?", (email,))
            return login_response(response, request, db, account, secure)
    raise HTTPException(400, "인증번호가 틀렸거나 만료되었습니다. 메일을 확인하거나 새 번호를 요청해 주세요.")


@router.post("/login")
def login(data: Credentials, request: Request, response: Response):
    secure = require_account_origin(request)
    username = data.username.lower()
    auth_attempt(username)
    with connect() as db:
        account = db.execute("SELECT * FROM company_accounts WHERE username=?", (username,)).fetchone()
        digest = hash_password(data.password, account["salt"] if account else bytes(16))
        if account is None or not secrets.compare_digest(account["password_hash"], digest):
            raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT password_hash FROM company_accounts WHERE id=?", (account["id"],)).fetchone()
        if current is None or not secrets.compare_digest(current["password_hash"], digest):
            raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")
        with attempt_lock:
            attempts.pop(username, None)
        return login_response(response, request, db, account, secure)


@router.post("/logout")
def logout(request: Request, response: Response):
    secure = require_account_origin(request)
    token = request.cookies.get(COOKIE, "")
    if TOKEN_FORMAT.fullmatch(token):
        with connect() as db:
            db.execute("DELETE FROM company_sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie(COOKIE, httponly=True, samesite="strict", secure=secure)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}
