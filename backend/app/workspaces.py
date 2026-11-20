"""Role selection for the local multi-company demo."""
import os
import re

from fastapi import HTTPException, Request

from .accounts import account_payload, get_account, session_workspace
from .db import connect

PC_INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PC_INVITE_PATTERN = re.compile(rf"[{PC_INVITE_ALPHABET}]{{12}}")

DEMO_WORKSPACES = [
    {"id": "local", "label": "내 작업공간"},
    {"id": "demo-a", "label": "배출업체 · 한빛부품"},
    {"id": "demo-b", "label": "가공업체 · 전주순환소재"},
    {"id": "demo-c", "label": "가공업체 · 익산리플라"},
    {"id": "demo-d", "label": "가공업체 · 새봄자원"},
    {"id": "demo-e", "label": "가공업체 · 서울순환소재"},
    {"id": "demo-f", "label": "가공업체 · 군산리턴폴리머"},
    {"id": "demo-g", "label": "가공업체 · 김제리폼소재"},
    {"id": "demo-h", "label": "가공업체 · 대전달빛중합"},
    {"id": "demo-i", "label": "가공업체 · 전주새결금속"},
    {"id": "demo-j", "label": "가공업체 · 익산다시종이"},
]
INVITE_ENVS = {
    "demo-a": "REAI_SUPPLIER_INVITE",
    "demo-b": "REAI_JEONJU_INVITE",
    "demo-c": "REAI_IKSAN_INVITE",
    "demo-d": "REAI_WANJU_INVITE",
    "demo-e": "REAI_RECYCLER_INVITE",
    "demo-f": "REAI_GUNSAN_INVITE",
    "demo-g": "REAI_GIMJE_INVITE",
    "demo-h": "REAI_DAEJEON_INVITE",
    "demo-i": "REAI_METAL_INVITE",
    "demo-j": "REAI_PAPER_INVITE",
}
DEMO_ORGS = {workspace["id"] for workspace in DEMO_WORKSPACES}


def demo_enabled() -> bool:
    return os.getenv("REAI_DEMO_MULTI_TENANT", "0") == "1"


def current_workspace(request: Request) -> str:
    if online_enabled():
        return online_workspace(request)
    if not demo_enabled():
        return "local"
    workspace = request.headers.get("X-Reai-Demo-Org", "local").strip()
    if workspace not in DEMO_ORGS:
        raise HTTPException(400, "개발용 워크스페이스 값이 잘못되었습니다.")
    return workspace


def online_enabled() -> bool:
    return os.getenv("REAI_ENV", "development").strip().lower() == "online-demo"


def accounts_enabled() -> bool:
    return online_enabled() and os.getenv("REAI_ACCOUNT_LOGIN") == "1"


def invite_codes() -> dict[str, str]:
    return {key: os.getenv(env, "").strip() for key, env in INVITE_ENVS.items()}


def normalize_pc_invite(code: str) -> str | None:
    if not code.isascii() or len(code) > 32:
        return None
    compact = code.replace("-", "").replace(" ", "").upper()
    return compact if PC_INVITE_PATTERN.fullmatch(compact) else None


def invite_value(code: str) -> str:
    if os.getenv("REAI_PC_SHARE") == "1":
        return normalize_pc_invite(code) or code
    return code


def validate_invites() -> None:
    configured = invite_codes()
    codes = [code for code in configured.values() if code]
    if not configured["demo-a"] or not configured["demo-e"]:
        raise RuntimeError("배출업체와 서울 가공업체의 초대 코드를 설정하세요.")
    for code in codes:
        if os.getenv("REAI_PC_SHARE") == "1" and normalize_pc_invite(code):
            continue
        if not 24 <= len(code) <= 256 or not code.isascii() or not all(c.isalnum() or c in "-_" for c in code):
            raise RuntimeError("초대 코드 형식이 올바르지 않습니다. 서버의 초대 코드 파일을 확인하세요.")
    if len({invite_value(code) for code in codes}) != len(codes):
        raise RuntimeError("배출업체와 가공업체는 서로 다른 초대 코드를 사용해야 합니다.")


def online_workspace(request: Request) -> str:
    from secrets import compare_digest

    if accounts_enabled():
        workspace = session_workspace(request)
        if workspace is not None:
            return workspace
        raise HTTPException(401, "Re AI 계정으로 로그인해 주세요.")

    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and 0 < len(token) <= 256:
        provided = invite_value(token).encode()
        for workspace, code in invite_codes().items():
            if code and compare_digest(invite_value(code).encode(), provided):
                return workspace
    raise HTTPException(401, "기업 초대 코드를 확인해 주세요.")


def workspace_session(workspace: str) -> dict:
    if workspace.startswith("company-"):
        with connect() as db:
            account = get_account(workspace, db)
        if not account:
            raise HTTPException(401, "Re AI 계정으로 다시 로그인해 주세요.")
        return account_payload(account)
    label = next(item["label"] for item in DEMO_WORKSPACES if item["id"] == workspace)
    return {"id": workspace, "label": label, "role": "supplier" if workspace in {"local", "demo-a"} else "recycler"}
