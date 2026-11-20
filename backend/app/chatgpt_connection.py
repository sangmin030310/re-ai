"""Official ChatGPT plan authorization for the local Re AI demo."""
import base64
import ctypes
import hashlib
import json
import os
import re
import time
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request as HttpRequest, build_opener
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
OAUTH = f"{ISSUER}/api/accounts/oauth"
DYNAMIC_CLIENT = "dynamic_agent_client"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"
CALLBACK_URI = f"{ORIGIN}/auth/callback"

router = APIRouter(include_in_schema=False)
lock = RLock()
attempts: dict[str, "Attempt"] = {}
_local_browser_key = token_urlsafe(32)


class Attempt(NamedTuple):
    nonce: str
    verifier: str
    client_id: str | None
    expires_at: float


class ChatGPTError(RuntimeError):
    pass


class RemoteError(ChatGPTError):
    def __init__(self, status: int, code: str = ""):
        self.status = status
        self.code = code
        if status == 429:
            message = "ChatGPT 사용 한도에 도달했습니다. ChatGPT의 사용량 설정을 확인해 주세요."
        elif status in (401, 403):
            message = "이 ChatGPT 계정에서 연결 권한을 확인하지 못했습니다. 연결 상태와 구독 사용 권한을 확인해 주세요."
        else:
            message = "ChatGPT 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요."
        super().__init__(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = build_opener(NoRedirect())


def local_plan_request(request: Request) -> bool:
    return (
        os.getenv("REAI_CHATGPT_LOCAL") == "1"
        and request.client is not None
        and request.client.host == "127.0.0.1"
        and request.headers.get("host") == HOST
        and not any(header in request.headers for header in ("forwarded", "cf-connecting-ip", "cf-ray", "via"))
        and not any(header.startswith("x-forwarded-") for header in request.headers)
    )


def local_plan_session(request: Request) -> bool:
    key = request.cookies.get("reai_local_plan", "")
    return compare_digest(key.encode(), _local_browser_key.encode())


def require_local(request: Request) -> None:
    if not local_plan_request(request):
        raise HTTPException(404)
    if request.method == "POST" and (request.headers.get("origin") != ORIGIN or not local_plan_session(request)):
        raise HTTPException(403, "Re AI의 로컬 화면에서 다시 시도해 주세요.")


def exchange(url: str, *, form: dict | None = None, payload: dict | None = None, token: str | None = None):
    headers = {"Accept": "text/event-stream" if payload else "application/json"}
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return opener.open(HttpRequest(url, data=data, headers=headers), timeout=35)
    except HTTPError as exc:
        with exc:
            try:
                body = json.load(exc)
                error = body.get("error")
                code = error.get("code", "") if isinstance(error, dict) else error or ""
            except (ValueError, AttributeError):
                code = ""
        raise RemoteError(exc.code, code) from None
    except (URLError, TimeoutError):
        raise ChatGPTError("OpenAI에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None


def windows_protect(data: bytes, *, encrypt: bool) -> bytes:
    """Use the current Windows user's DPAPI keys for credential storage."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    original = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(original, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt = ctypes.windll.crypt32
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("Windows credential protection failed.")
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free(ctypes.cast(output.data, ctypes.c_void_p))


def storage_path() -> Path:
    directory = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".config") / "ReAI" / "ChatGPT"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / "connection"


def load_state() -> dict:
    path = storage_path()
    if not path.exists():
        state = {"host_id": uuid4().urn, "active": None, "accounts": {}}
        save_state(state)
        return state
    raw = path.read_bytes()
    return json.loads(windows_protect(raw, encrypt=False) if os.name == "nt" else raw)


def save_state(state: dict) -> None:
    path = storage_path()
    raw = json.dumps(state, ensure_ascii=False).encode()
    if os.name == "nt":
        raw = windows_protect(raw, encrypt=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        tmp = Path(temporary.name)
        temporary.write(raw)
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def verify_identity(id_token: str, client_id: str, nonce: str) -> dict:
    import jwt

    jwks = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", timeout=10)
    key = jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token, key.key, algorithms=["RS256"], audience=client_id, issuer=ISSUER,
        options={"require": ["exp", "sub", "nonce"]},
    )
    if not compare_digest(str(claims["nonce"]), nonce):
        raise ChatGPTError("ChatGPT 로그인 확인에 실패했습니다. 다시 로그인해 주세요.")
    return claims


def token_fields(body: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or previous.get("refresh_token"),
        "id_token": body.get("id_token") or previous.get("id_token"),
        "scopes": body["scope"].split() if "scope" in body else previous.get("scopes", []),
        "expires_at": time.time() + int(body["expires_in"]),
    }


def usable_account(state: dict) -> dict:
    active = state["active"]
    account = state["accounts"].get(active, {})
    if not account.get("access_token") or PLAN_SCOPE not in account.get("scopes", []):
        raise ChatGPTError("Re AI에서 ChatGPT로 로그인하고 구독 사용을 허용해 주세요.")
    if account["expires_at"] > time.time() + 45:
        return account
    if not account.get("refresh_token"):
        raise ChatGPTError("ChatGPT 연결이 만료됐습니다. 다시 로그인해 주세요.")
    try:
        with exchange(f"{OAUTH}/token", form={
            "grant_type": "refresh_token", "client_id": active,
            "refresh_token": account["refresh_token"], "resource": RESOURCE,
        }) as response:
            account.update(token_fields(json.load(response), account))
    except RemoteError as error:
        if error.code in {"invalid_grant", "invalid_refresh_token", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused", "token_expired"}:
            account = {key: account[key] for key in ("subject", "email", "model", "had_grant")}
            state["accounts"][active] = account
            save_state(state)
            raise ChatGPTError("ChatGPT 연결이 만료됐습니다. 다시 로그인해 주세요.") from None
        raise
    save_state(state)
    if PLAN_SCOPE not in account.get("scopes", []):
        raise ChatGPTError("ChatGPT 구독 사용 권한이 없습니다. 다시 연결해 주세요.")
    return account


def available_models(account: dict) -> list[dict]:
    with exchange(f"{RESOURCE}/models", token=account["access_token"]) as response:
        models = json.load(response).get("models", [])
    return [
        {"slug": item["slug"], "name": item.get("display_name") or item["slug"]}
        for item in models if item.get("visibility") == "list" and item.get("slug")
    ]


class ConnectionChoice(BaseModel):
    client_id: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)


@router.get("/api/chatgpt")
def connection_status(request: Request):
    require_local(request)
    with lock:
        state = load_state()
        active = state["active"]
        account = state["accounts"].get(active, {})
        response = JSONResponse({
            "active": active,
            "enabled": bool(account.get("access_token") and PLAN_SCOPE in account.get("scopes", [])),
            "email": account.get("email"),
            "model": account.get("model"),
            "accounts": [{"id": key, "email": value["email"]} for key, value in state["accounts"].items()],
        }, headers={"Cache-Control": "no-store"})
        response.set_cookie("reai_local_plan", _local_browser_key, httponly=True, samesite="strict")
        return response


@router.post("/api/chatgpt/connect")
def connect_account(request: Request, choice: ConnectionChoice):
    require_local(request)
    with lock:
        state = load_state()
        account = state["accounts"].get(choice.client_id, {})
        if choice.client_id and not account:
            raise HTTPException(404, "저장된 ChatGPT 계정을 찾을 수 없습니다.")
        now = time.monotonic()
        for pending in list(attempts):
            if attempts[pending].expires_at < now:
                del attempts[pending]
        if len(attempts) >= 8:
            attempts.pop(next(iter(attempts)))
        attempt = Attempt(token_urlsafe(24), token_urlsafe(48), choice.client_id, now + 600)
        state_code = token_urlsafe(24)
        attempts[state_code] = attempt
        challenge = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).decode().rstrip("=")
        params = {
            "client_id": choice.client_id or DYNAMIC_CLIENT, "ext_agent_host_id": state["host_id"],
            "response_type": "code", "redirect_uri": CALLBACK_URI, "scope": SCOPES,
            "resource": RESOURCE, "state": state_code, "nonce": attempt.nonce,
            "code_challenge_method": "S256", "code_challenge": challenge,
        }
        if not choice.client_id:
            params["agent_name_hint"] = "Re AI"
        else:
            if PLAN_SCOPE not in account.get("scopes", []):
                params["prompt"] = "consent"
        return JSONResponse({"url": f"{ISSUER}/api/accounts/authorize?{urlencode(params)}"}, headers={"Cache-Control": "no-store"})


@router.get("/auth/callback")
def authorize_callback(request: Request):
    require_local(request)
    query = request.query_params
    with lock:
        attempt = attempts.pop(query.get("state", ""), None)
    outcome = "error"
    if attempt and attempt.expires_at > time.monotonic():
        if query.get("error") == "access_denied":
            outcome = "denied"
        elif query.get("code") and not query.get("error"):
            client_id = query.get("client_id") or attempt.client_id
            if client_id and re.fullmatch(r"oaiapp_[A-Za-z0-9_-]{1,112}", client_id) and (not attempt.client_id or client_id == attempt.client_id):
                try:
                    with exchange(f"{OAUTH}/token", form={
                        "grant_type": "authorization_code", "client_id": client_id,
                        "code": query["code"], "code_verifier": attempt.verifier,
                        "redirect_uri": CALLBACK_URI, "resource": RESOURCE,
                    }) as response:
                        body = json.load(response)
                    identity = verify_identity(body["id_token"], client_id, attempt.nonce)
                    with lock:
                        state = load_state()
                        previous = state["accounts"].get(client_id, {})
                        if previous and previous["subject"] != identity["sub"]:
                            raise ChatGPTError("다른 ChatGPT 계정이 선택됐습니다.")
                        account = {
                            "subject": identity["sub"], "email": identity.get("email") or "ChatGPT 계정",
                            "model": previous.get("model"), **token_fields(body),
                        }
                        enabled = PLAN_SCOPE in account["scopes"]
                        first_grant = enabled and not previous.get("had_grant")
                        account["had_grant"] = bool(enabled or previous.get("had_grant"))
                        state["accounts"][client_id] = account
                        state["active"] = client_id
                        save_state(state)
                    outcome = ("welcome" if first_grant else "connected") if enabled else "permission"
                except Exception:
                    outcome = "error"
    return RedirectResponse(f"/?chatgpt={outcome}", status_code=303, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    })


@router.get("/api/chatgpt/models")
def models(request: Request):
    require_local(request)
    try:
        with lock:
            return available_models(usable_account(load_state()))
    except ChatGPTError as error:
        raise HTTPException(502, str(error)) from None


@router.post("/api/chatgpt/model")
def select_model(request: Request, choice: ConnectionChoice):
    require_local(request)
    try:
        with lock:
            state = load_state()
            account = usable_account(state)
            if choice.model not in {model["slug"] for model in available_models(account)}:
                raise HTTPException(422, "사용 가능한 모델을 선택해 주세요.")
            account["model"] = choice.model
            save_state(state)
    except ChatGPTError as error:
        raise HTTPException(502, str(error)) from None
    return {"ok": True}


@router.post("/api/chatgpt/disconnect")
def disconnect(request: Request):
    require_local(request)
    remote = True
    with lock:
        state = load_state()
        account = state["accounts"].get(state["active"], {})
        if account.get("refresh_token"):
            for retry in range(2):
                try:
                    with exchange(f"{OAUTH}/revoke", form={
                        "token": account["refresh_token"], "token_type_hint": "refresh_token", "client_id": state["active"],
                    }):
                        remote = True
                    break
                except ChatGPTError as error:
                    remote = False
                    if isinstance(error, RemoteError) and error.status < 500:
                        break
                    if retry == 0:
                        time.sleep(0.25)
        for name in ("access_token", "refresh_token", "id_token", "scopes", "expires_at"):
            account.pop(name, None)
        state["active"] = None
        save_state(state)
    return {"revoked": remote}
