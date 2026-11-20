"""Verified company email, username reminders and single-use password resets."""
import logging
import os
import re
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .accounts import (
    COOKIE, TOKEN_FORMAT, auth_attempt, hash_password, is_local_account_request, require_account_origin,
    session_workspace, token_hash,
)
from .db import connect

router = APIRouter(prefix="/api/accounts/recovery", tags=["accounts"])
logger = logging.getLogger(__name__)
EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
LINK_SECONDS = 30 * 60
SIGNUP_CODE_SECONDS = 10 * 60
SIGNUP_CODE_MAX_ERRORS = 5


def init_recovery():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS company_recovery_emails (
            account_id TEXT PRIMARY KEY REFERENCES company_accounts(id) ON DELETE CASCADE,
            email TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS company_pending_recovery_emails (
            account_id TEXT PRIMARY KEY REFERENCES company_accounts(id) ON DELETE CASCADE,
            email TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS company_recovery_tokens (
            token_hash BLOB PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES company_accounts(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            purpose TEXT NOT NULL CHECK(purpose IN ('verify', 'reset')),
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recovery_tokens_account
            ON company_recovery_tokens(account_id);
        CREATE TABLE IF NOT EXISTS company_signup_email_codes (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            code_hash BLOB NOT NULL,
            expires_at INTEGER NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0
        );
        """)


class EmailRequest(BaseModel):
    email: str = Field(max_length=254)


class EmailSetup(EmailRequest):
    password: str = Field(min_length=8, max_length=128)


class RecoveryRequest(EmailRequest):
    purpose: Literal["username", "reset"]


class LinkToken(BaseModel):
    token: str = Field(pattern=TOKEN_FORMAT.pattern + "$", min_length=43, max_length=43)


class PasswordReset(LinkToken):
    password: str = Field(min_length=8, max_length=128)


def clean_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(422, "이메일 주소를 확인해 주세요.")
    return email


@dataclass(frozen=True)
class RecoveryMailer:
    host: str
    port: int
    security: str
    sender: str
    username: str
    password: str
    base_url: str

    def send(self, recipient: str, subject: str, body: str):
        mail = EmailMessage()
        mail["From"] = self.sender
        mail["To"] = recipient
        mail["Subject"] = subject
        mail.set_content(body)
        context = ssl.create_default_context()
        connection = (smtplib.SMTP_SSL(self.host, self.port, timeout=10, context=context)
                      if self.security == "ssl" else smtplib.SMTP(self.host, self.port, timeout=10))
        with connection as smtp:
            if self.security == "starttls":
                smtp.starttls(context=context)
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(mail)

    def link(self, purpose: str, token: str) -> str:
        return self.base_url + "#" + urlencode({"recovery": purpose, "token": token})


def recovery_base_url(request: Request | None) -> str:
    configured = os.getenv("REAI_RECOVERY_BASE_URL", "").strip()
    active_tunnel = os.getenv("REAI_PC_SHARE_URL", "").strip() if os.getenv("REAI_PC_SHARE") == "1" else ""
    parsed = urlsplit(configured)
    loopback = {"localhost", "127.0.0.1"}
    if active_tunnel and (not configured or parsed.hostname in loopback
                          or (parsed.hostname or "").endswith(".trycloudflare.com")):
        parsed = urlsplit(active_tunnel)
    local = request is not None and is_local_account_request(request)
    if not parsed.netloc and not configured and local:
        parsed = urlsplit(f"http://{request.headers['host']}")
    # A public recovery link must come from server configuration, never an incoming Host header.
    if parsed.hostname in loopback and request is not None and not local:
        raise HTTPException(503, "팀 공유 실행으로 서버를 시작하거나 서버의 복구 링크 주소를 설정해 주세요.")
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(char.isspace() for char in parsed.netloc)
            or not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in loopback))):
        raise HTTPException(503, "서버에 복구 메일 링크 주소를 설정해 주세요.")
    return parsed.geturl().rstrip("/") + "/"


def mailer(request: Request | None = None, *, needs_link: bool = True) -> RecoveryMailer:
    host = os.getenv("REAI_SMTP_HOST", "").strip()
    sender = os.getenv("REAI_SMTP_FROM", "").strip()
    security = os.getenv("REAI_SMTP_SECURITY", "starttls").strip().lower()
    username = os.getenv("REAI_SMTP_USERNAME", "").strip()
    password = os.getenv("REAI_SMTP_PASSWORD", "")
    try:
        port = int(os.getenv("REAI_SMTP_PORT", "465" if security == "ssl" else "587"))
        base_url = recovery_base_url(request) if needs_link else ""
    except ValueError:
        raise HTTPException(503, "서버의 이메일 발송 포트와 복구 링크 주소를 확인해 주세요.") from None
    if (not host or not EMAIL.fullmatch(sender.lower())
            or security not in {"ssl", "starttls"} or not 0 < port < 65536
            or bool(username) != bool(password)):
        raise HTTPException(503, "복구 메일을 사용하려면 서버의 이메일 발송 설정이 필요합니다.")
    return RecoveryMailer(host, port, security, sender, username, password, base_url)


def create_link(db, purpose: str, account_id: str, email: str) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM company_recovery_tokens WHERE expires_at<=?", (now,))
    db.execute(
        """INSERT INTO company_recovery_tokens(token_hash, account_id, email, purpose, expires_at)
           VALUES (?, ?, ?, ?, ?)""",
        (token_hash(token), account_id, email, purpose, now + LINK_SECONDS),
    )
    return token


def find_link(db, token: str, purpose: str):
    digest = token_hash(token)
    row = db.execute(
        "SELECT * FROM company_recovery_tokens WHERE token_hash=? AND purpose=? AND expires_at>?",
        (digest, purpose, int(time.time())),
    ).fetchone()
    if row is None:
        raise HTTPException(400, "링크가 만료되었거나 이미 사용되었습니다. 새 링크를 요청해 주세요.")
    return row


def send_recovery(mailing: RecoveryMailer, email: str, purpose: str):
    try:
        with connect() as db:
            if purpose == "reset":
                db.execute("BEGIN IMMEDIATE")
            account = db.execute(
                """SELECT a.id, a.username FROM company_recovery_emails e
                   JOIN company_accounts a ON a.id=e.account_id WHERE e.email=?""",
                (email,),
            ).fetchone()
            if account is None:
                return
            if purpose == "reset":
                token = create_link(db, "reset", account["id"], email)
        if purpose == "username":
            mailing.send(email, "[Re AI] 기업 계정 아이디 안내", f"로그인 아이디는 {account['username']}입니다.")
        else:
            mailing.send(email, "[Re AI] 비밀번호 재설정",
                         f"30분 이내에 아래 링크를 열어 새 비밀번호를 설정해 주세요.\n\n{mailing.link('reset', token)}")
    except Exception:
        logger.error("계정 복구 메일을 발송하지 못했습니다.")


@router.get("/email")
def current_recovery_email(request: Request, response: Response):
    account_id = session_workspace(request)
    if account_id is None:
        raise HTTPException(401, "기업 계정으로 로그인해 주세요.")
    response.headers["Cache-Control"] = "no-store"
    with connect() as db:
        row = db.execute("SELECT email FROM company_recovery_emails WHERE account_id=?", (account_id,)).fetchone()
        pending = db.execute(
            "SELECT email FROM company_pending_recovery_emails WHERE account_id=?", (account_id,),
        ).fetchone()
    try:
        mailer(request)
        can_send = True
    except HTTPException:
        can_send = False
    return {"email": row["email"] if row else None, "pending_email": pending["email"] if pending else None,
            "mail_available": can_send}


def send_account_email(mailing: RecoveryMailer, email: str, subject: str, body: str):
    try:
        mailing.send(email, subject, body)
    except (smtplib.SMTPException, OSError, ValueError) as failure:
        logger.warning("Account verification email failed: %s (SMTP code: %s)",
                       type(failure).__name__, getattr(failure, "smtp_code", "-"))
        if isinstance(failure, smtplib.SMTPAuthenticationError):
            message = "메일 서버 로그인에 실패했습니다. 발신 계정의 SMTP 사용 설정과 앱 비밀번호를 확인해 주세요."
        elif isinstance(failure, smtplib.SMTPSenderRefused):
            message = "메일 서버가 발신 주소를 거부했습니다. 서버에 설정한 발신 주소를 확인해 주세요."
        else:
            message = "인증 메일을 보내지 못했습니다. 서버 터미널에서 메일 오류를 확인한 뒤 다시 시도해 주세요."
        raise HTTPException(503, message) from None


def send_verification_email(mailing: RecoveryMailer, email: str, token: str):
    try:
        send_account_email(mailing, email, "[Re AI] 복구 이메일 인증",
                           f"본인이 요청한 경우 30분 이내에 링크를 열고 인증을 완료해 주세요.\n\n{mailing.link('verify', token)}")
    except HTTPException:
        with connect() as db:
            db.execute("DELETE FROM company_recovery_tokens WHERE token_hash=?", (token_hash(token),))
        raise


def consume_signup_email_code(db, email: str, challenge: str, code: str) -> bool:
    now = int(time.time())
    match = db.execute(
        """DELETE FROM company_signup_email_codes
           WHERE id=? AND email=? AND code_hash=? AND expires_at>? AND failed_attempts<?
           RETURNING id""",
        (challenge, email, token_hash(f"{challenge}:{code}"), now, SIGNUP_CODE_MAX_ERRORS),
    ).fetchone()
    if match is None:
        db.execute(
            """UPDATE company_signup_email_codes SET failed_attempts=failed_attempts+1
               WHERE id=? AND email=? AND expires_at>? AND failed_attempts<?""",
            (challenge, email, now, SIGNUP_CODE_MAX_ERRORS),
        )
    return match is not None


@router.post("/signup-code")
def request_signup_email_code(data: EmailRequest, request: Request):
    require_account_origin(request)
    email = clean_email(data.email)
    mailing = mailer(needs_link=False)
    auth_attempt(f"signup-email:{email}")
    auth_attempt(f"signup-client:{request.client.host if request.client else 'unknown'}")
    challenge = secrets.token_hex(16)
    code = f"{secrets.randbelow(1000000):06d}"
    now = int(time.time())
    with connect() as db:
        db.execute("DELETE FROM company_signup_email_codes WHERE expires_at<=?", (now,))
        db.execute(
            """INSERT INTO company_signup_email_codes(id, email, code_hash, expires_at)
               VALUES (?, ?, ?, ?)""",
            (challenge, email, token_hash(f"{challenge}:{code}"), now + SIGNUP_CODE_SECONDS),
        )
    try:
        send_account_email(mailing, email, "[Re AI] 회원가입 이메일 인증번호",
                           f"Re AI 회원가입 화면에 아래 번호를 입력해 주세요. 10분 동안 유효합니다.\n\n{code}")
    except HTTPException:
        with connect() as db:
            db.execute("DELETE FROM company_signup_email_codes WHERE id=?", (challenge,))
        raise
    return {"challenge_id": challenge}


@router.post("/email/resend")
def resend_signup_email(request: Request):
    require_account_origin(request)
    account_id = session_workspace(request)
    if account_id is None:
        raise HTTPException(401, "기업 계정으로 로그인해 주세요.")
    auth_attempt(f"set-email:{account_id}")
    mailing = mailer(request)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        pending = db.execute(
            "SELECT email FROM company_pending_recovery_emails WHERE account_id=?", (account_id,),
        ).fetchone()
        if not pending:
            raise HTTPException(409, "인증을 기다리는 이메일 주소가 없습니다.")
        email = pending["email"]
        auth_attempt(f"verify-email:{email}")
        token = create_link(db, "verify", account_id, email)
    send_verification_email(mailing, email, token)
    return {"ok": True}


@router.post("/email")
def setup_email(data: EmailSetup, request: Request):
    require_account_origin(request)
    account_id = session_workspace(request)
    if account_id is None:
        raise HTTPException(401, "기업 계정으로 로그인해 주세요.")
    email = clean_email(data.email)
    auth_attempt(f"set-email:{account_id}")
    with connect() as db:
        row = db.execute("SELECT salt, password_hash FROM company_accounts WHERE id=?", (account_id,)).fetchone()
        if not row or not secrets.compare_digest(hash_password(data.password, row["salt"]), row["password_hash"]):
            raise HTTPException(401, "현재 비밀번호를 확인해 주세요.")
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT password_hash FROM company_accounts WHERE id=?", (account_id,)).fetchone()
        if not current or not secrets.compare_digest(current["password_hash"], row["password_hash"]):
            raise HTTPException(401, "다시 로그인해 주세요.")
        db.execute(
            "DELETE FROM company_recovery_tokens WHERE account_id=? AND purpose='verify' AND email<>?",
            (account_id, email),
        )
        db.execute(
            """INSERT INTO company_pending_recovery_emails(account_id, email) VALUES (?, ?)
               ON CONFLICT(account_id) DO UPDATE SET email=excluded.email""", (account_id, email),
        )
    try:
        mailing = mailer(request)
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT 1 FROM company_pending_recovery_emails WHERE account_id=? AND email=?",
                (account_id, email),
            ).fetchone()
            if pending is None:
                raise HTTPException(409, "복구 이메일이 변경되었습니다. 현재 주소를 다시 확인해 주세요.")
            auth_attempt(f"verify-email:{email}")
            token = create_link(db, "verify", account_id, email)
        send_verification_email(mailing, email, token)
    except HTTPException as failure:
        if failure.status_code == 409:
            raise
        return {"ok": True, "mail_sent": False, "message": failure.detail}
    return {"ok": True, "mail_sent": True}


@router.post("/verify")
def verify_email(data: LinkToken, request: Request):
    require_account_origin(request)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = find_link(db, data.token, "verify")
        pending = db.execute(
            "SELECT 1 FROM company_pending_recovery_emails WHERE account_id=? AND email=?",
            (row["account_id"], row["email"]),
        ).fetchone()
        if pending is None:
            raise HTTPException(400, "복구 이메일이 변경되었습니다. 새 인증 링크를 요청해 주세요.")
        existing = db.execute("SELECT account_id FROM company_recovery_emails WHERE email=?", (row["email"],)).fetchone()
        if existing and existing["account_id"] != row["account_id"]:
            raise HTTPException(409, "다른 기업 계정에 이미 등록된 이메일입니다.")
        db.execute(
            """INSERT INTO company_recovery_emails(account_id, email) VALUES (?, ?)
               ON CONFLICT(account_id) DO UPDATE SET email=excluded.email""",
            (row["account_id"], row["email"]),
        )
        db.execute("DELETE FROM company_recovery_tokens WHERE account_id=?", (row["account_id"],))
        db.execute("DELETE FROM company_pending_recovery_emails WHERE account_id=?", (row["account_id"],))
    return {"ok": True}


@router.post("/request", status_code=202)
def request_recovery(data: RecoveryRequest, request: Request, background: BackgroundTasks):
    require_account_origin(request)
    email = clean_email(data.email)
    mailing = mailer(request)
    auth_attempt(f"recovery-client:{request.client.host if request.client else 'unknown'}")
    auth_attempt(f"recovery-email:{email}")
    background.add_task(send_recovery, mailing, email, data.purpose)
    return {"ok": True}


@router.post("/reset")
def reset_password(data: PasswordReset, request: Request, response: Response):
    secure = require_account_origin(request)
    with connect() as db:
        find_link(db, data.token, "reset")
        salt = secrets.token_bytes(16)
        digest = hash_password(data.password, salt)
        db.execute("BEGIN IMMEDIATE")
        row = find_link(db, data.token, "reset")
        db.execute("UPDATE company_accounts SET salt=?, password_hash=? WHERE id=?",
                   (salt, digest, row["account_id"]))
        cookie = request.cookies.get(COOKIE, "")
        active = TOKEN_FORMAT.fullmatch(cookie) and db.execute(
            "SELECT 1 FROM company_sessions WHERE token_hash=? AND account_id=?",
            (token_hash(cookie), row["account_id"]),
        ).fetchone()
        db.execute("DELETE FROM company_sessions WHERE account_id=?", (row["account_id"],))
        db.execute("DELETE FROM company_recovery_tokens WHERE account_id=?", (row["account_id"],))
        db.execute("DELETE FROM company_pending_recovery_emails WHERE account_id=?", (row["account_id"],))
    if active:
        response.delete_cookie(COOKIE, httponly=True, samesite="strict", secure=secure)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}
