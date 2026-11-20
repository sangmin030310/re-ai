"""Re AI MVP API: local demo only; add authentication/authorization before deployment."""
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8-sig")

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .accounts import init_accounts, router as accounts_router
from .account_recovery import init_recovery, router as recovery_router
from .agents.contract import AgentAction, AgentReply
from .agents.mock_gateway import MockAgentGateway, analysis_from_profile, merge_profile
from .chatgpt_connection import ChatGPTError, local_plan_request, require_local, router as chatgpt_router
from .db import (connect, data_dir, document_json, ensure_sample, init_db,
                 message_json, new_id, project_json, utc_now)
from . import document_archive
from .document_chat import delete_from_chat, document_intent, document_reply, save_from_chat
from .request_chat import interpret_request_message, merge_shipping_details, request_reply
from .matching import init_matching, router as matching_router
from .role_chat import role_chat, workspace_help
from .deals import init_deals, router as deals_router
from .demands import init_demands, router as demands_router
from .trust import init_trust, is_operator, router as trust_router
from .workspaces import DEMO_WORKSPACES, accounts_enabled, current_workspace, demo_enabled, online_enabled, validate_invites, workspace_session

logger = logging.getLogger(__name__)
GREETING = re.compile(r"안녕(?:하세요|하십니까|하세용|해요)?|하이|hello|hi", re.IGNORECASE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # IMPORTANT: The v4 workspace selector is a local simulator, not authentication.
    # Fail closed rather than exposing other companies' data publicly.
    if online_enabled():
        if not accounts_enabled():
            validate_invites()
    elif os.getenv("REAI_ENV", "development").lower() != "development":
        raise RuntimeError("Re AI v4 is local-development only. Implement verified login, tenant authorization, managed DB and object storage before public deployment.")
    init_db()
    init_matching()
    init_deals()
    init_demands()
    if accounts_enabled():
        init_accounts()
        init_recovery()
        init_trust()
    if not online_enabled() and os.getenv("REAI_SEED_SAMPLE", "1") == "1":
        ensure_sample()
    yield


app = FastAPI(title="Re AI MVP", description="산업폐기물 자원순환 UI 연동용 데모 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Reai-Demo-Org"],
)
app.include_router(demands_router)
app.include_router(matching_router)
app.include_router(deals_router)
app.include_router(trust_router)
app.include_router(chatgpt_router)
app.include_router(accounts_router)
app.include_router(recovery_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path in {"/api/accounts/register", "/api/accounts/login"}:
        return JSONResponse({"detail": "아이디·비밀번호와 입력 항목을 확인해 주세요."}, status_code=422)
    return await request_validation_exception_handler(request, error)


def agent_mode() -> str:
    """Use the configured provider when set, with a demo fallback for unknown values."""
    requested = os.getenv("REAI_CHAT_PROVIDER", "").strip().lower()
    if requested:
        return "openai" if requested == "openai" else "mock"
    return "openai" if os.getenv("OPENAI_API_KEY", "").strip() else "mock"


def make_gateway(mode: str):
    if mode == "chatgpt":
        from .agents.chatgpt_gateway import ChatGPTPlanGateway
        return ChatGPTPlanGateway()
    if mode == "openai":
        from .agents.openai_gateway import OpenAIChatGateway
        return OpenAIChatGateway()
    return MockAgentGateway()


configured_mode = agent_mode()
agent_gateway = make_gateway(configured_mode)


class ProjectCreate(BaseModel):
    title: str = Field(default="새 폐기물 검토", min_length=1, max_length=100)


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class SendMessage(BaseModel):
    intake: bool = False
    content: str = Field(min_length=1, max_length=10000)
    request_draft: dict | None = None
    document_selection: str | None = Field(default=None, max_length=64)


class RouteSelection(BaseModel):
    route_id: str


def require_project(db, project_id: str, workspace: str):
    row = db.execute("SELECT * FROM projects WHERE id=? AND organization_id=?", (project_id, workspace)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다.")
    return row


@app.get("/api/health")
def health(request: Request):
    mode = "chatgpt" if local_plan_request(request) else agent_mode()
    return {"ok": True, "mode": mode, "online_demo": online_enabled(), "account_login": accounts_enabled(), "pc_share": online_enabled() and os.getenv("REAI_PC_SHARE") == "1", "demo_workspaces": demo_enabled() and not online_enabled(), "workspaces": DEMO_WORKSPACES if demo_enabled() and not online_enabled() else [], "notice": "로컬 설정 상태입니다. AI 모델 응답 가능 여부는 채팅으로 확인하세요. 법규 검증은 지원하지 않습니다."}


@app.get("/api/session")
def session(workspace: str = Depends(current_workspace)):
    return workspace_session(workspace)


@app.get("/api/projects")
def list_projects(workspace: str = Depends(current_workspace)):
    with connect() as db:
        rows = db.execute("SELECT * FROM projects WHERE organization_id=? ORDER BY updated_at DESC",(workspace,)).fetchall()
    return [project_json(r) for r in rows]


@app.post("/api/projects", status_code=201)
def create_project(data: ProjectCreate, workspace: str = Depends(current_workspace)):
    project_id, now = new_id(), utc_now()
    with connect() as db:
        db.execute("INSERT INTO projects(id,title,profile,created_at,updated_at,organization_id) VALUES (?,?,?,?,?,?)", (project_id,data.title.strip(),"{}",now,now,workspace))
        row = require_project(db, project_id, workspace)
        return project_json(row)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        row = require_project(db, project_id, workspace)
        return project_json(row)


@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, data: ProjectUpdate, workspace: str = Depends(current_workspace)):
    with connect() as db:
        require_project(db, project_id, workspace)
        db.execute("UPDATE projects SET title=?,updated_at=? WHERE id=? AND organization_id=?", (data.title.strip(),utc_now(),project_id,workspace))
        return project_json(require_project(db, project_id, workspace))


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        require_project(db, project_id, workspace)
        files = db.execute("SELECT stored_name FROM documents WHERE project_id=? AND stored_name<>''",(project_id,)).fetchall()
        db.execute("DELETE FROM projects WHERE id=? AND organization_id=?",(project_id,workspace))
    for f in files:
        document_archive.remove_upload(f["stored_name"])
    return {"ok": True}


@app.get("/api/projects/{project_id}/messages")
def get_messages(project_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        require_project(db, project_id, workspace)
        rows = db.execute("SELECT * FROM messages WHERE project_id=? ORDER BY rowid ASC",(project_id,)).fetchall()
    return [message_json(r) for r in rows]


@app.get("/api/projects/{project_id}/analysis")
def get_analysis(project_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        row = require_project(db, project_id, workspace)
        return analysis_from_profile(json.loads(row["profile"]), row["selected_route"])


@app.post("/api/projects/{project_id}/messages")
def send_message(project_id: str, data: SendMessage, request: Request, workspace: str = Depends(current_workspace)):
    prompt = data.content.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="내용을 입력하세요.")
    role = workspace_session(workspace)["role"]
    supplier = role == "supplier"
    intent = document_intent(prompt)
    if intent:
        return handle_document_chat(project_id, workspace, prompt, data, intent, supplier)
    preparing_request = data.intake and supplier
    mode = agent_mode()
    if local_plan_request(request) and online_enabled():
        require_local(request)
        mode = "chatgpt"
    greeting = GREETING.fullmatch(prompt.rstrip("!?.,~^ ㅎㅎㅋㅋ😊"))
    draft_turn = None
    draft_provider_failed = False
    # Read existing conversation before any outbound provider call.
    # Only text, not uploaded files, is passed to the optional AI provider.
    with connect() as db:
        row = require_project(db, project_id, workspace)
        original_profile = json.loads(row["profile"])
        history = []
        if not greeting:
            recent = db.execute("SELECT role, content FROM messages WHERE project_id=? ORDER BY rowid DESC LIMIT 16", (project_id,)).fetchall()
            history = [dict(r) for r in reversed(recent)]

    if preparing_request and mode in {"openai", "chatgpt"} and not greeting:
        try:
            gateway = agent_gateway if mode == configured_mode else make_gateway(mode)
            draft_turn = gateway.draft_reply(message=prompt, profile=original_profile, history=history)
        except Exception as exc:
            if mode == "chatgpt":
                detail = str(exc) if isinstance(exc, ChatGPTError) else "ChatGPT 요청서 답변을 처리하지 못했습니다. 다시 시도해 주세요."
                raise HTTPException(502, detail) from None
            logger.warning("%s request drafting fell back to guided mode (%s)", mode, type(exc).__name__)
            draft_provider_failed = True

    if not supplier:
        result, profile = role_chat(workspace, role, prompt, original_profile, greeting)
    elif greeting:
        profile = original_profile
        text = "안녕하세요! 작성하던 요청서를 이어가 볼까요?" if preparing_request else "안녕하세요! 어떤 폐기물이나 요청서에 대해 이야기해 볼까요?"
        result = AgentReply(agent="reai_greeting", status="review_ready", message=text)
    elif draft_turn is not None:
        profile = {**original_profile, **draft_turn.updates.model_dump(exclude_none=True)}
    elif preparing_request:
        profile, request_guidance, request_actions = interpret_request_message(original_profile, prompt)
    else:
        profile = merge_profile(original_profile, prompt)
        merge_shipping_details(profile, prompt)

    try:
        if not supplier:
            if result is None:
                if mode in {"openai", "chatgpt"}:
                    gateway = agent_gateway if mode == configured_mode else make_gateway(mode)
                    result = gateway.reply(message=prompt, profile={}, history=history, role=role)
                else:
                    result = workspace_help(role, accounts_enabled())
        elif not greeting and not preparing_request and mode in {"openai", "chatgpt"}:
            gateway = agent_gateway if mode == configured_mode else make_gateway(mode)
            result = gateway.reply(message=prompt, profile=profile, history=history)
        elif not greeting and not preparing_request:
            result = agent_gateway.reply(message=prompt, profile=profile)
    except Exception as exc:
        # Never return provider internals or credentials to the browser.
        if mode == "chatgpt":
            detail = str(exc) if isinstance(exc, ChatGPTError) else "ChatGPT 답변을 처리하지 못했습니다. 다시 시도해 주세요."
            raise HTTPException(502, detail) from None
        detail = "AI 응답을 받지 못했습니다. API 키·잔액·모델 접근 권한과 백엔드 로그를 확인해주세요."
        raise HTTPException(status_code=502, detail=detail) from exc

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = json.loads(require_project(db, project_id, workspace)["profile"])
        changes = {key: value for key, value in profile.items() if original_profile.get(key) != value}
        profile = {**latest, **changes}
        if greeting or not supplier:
            result.data = analysis_from_profile(profile)
        elif preparing_request:
            if draft_turn is not None:
                result = request_reply(profile, draft_turn.reply, [], continue_intake=False)
                result.agent = f"{mode}_request_draft"
            else:
                result = request_reply(profile, request_guidance, request_actions, continue_intake=bool(changes) and not request_actions)
                if draft_provider_failed:
                    result.message = "OpenAI API 응답을 받지 못했어요. 지금은 기본 요청서 안내로 이어갈게요.\n\n" + result.message
        return store_chat_reply(db, project_id, workspace, prompt, result, profile)


def store_chat_reply(db, project_id, workspace, prompt, result, profile):
    now = utc_now()
    user_id, reply_id = new_id(), new_id()
    db.executemany(
        "INSERT INTO messages(id,project_id,role,content,actions,created_at) VALUES (?,?,?,?,?,?)",
        [(user_id, project_id, "user", prompt, "[]", now),
         (reply_id, project_id, "assistant", result.message,
          json.dumps([action.model_dump() for action in result.actions], ensure_ascii=False), now)],
    )
    db.execute("UPDATE projects SET profile=?,updated_at=? WHERE id=?",
               (json.dumps(profile, ensure_ascii=False), now, project_id))
    messages = db.execute("SELECT * FROM messages WHERE id IN (?,?) ORDER BY rowid", (user_id, reply_id)).fetchall()
    project = require_project(db, project_id, workspace)
    return {"messages": [message_json(row) for row in messages], "project": project_json(project),
            "analysis": analysis_from_profile(profile, project["selected_route"]), "agent_reply": result.model_dump()}


def handle_document_chat(project_id, workspace, prompt, data, intent, supplier):
    removed = None
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        project = require_project(db, project_id, workspace)
        profile = json.loads(project["profile"])
        command = {"changed": False}
        if intent == "open":
            result = document_reply("문서 보관함을 열었어요.")
            command["open_archive"] = True
        elif intent == "save" and supplier:
            result, command = save_from_chat(db, project, workspace, profile, data.request_draft)
            if command.get("saved_request"):
                profile.update(command["saved_request"])
        elif intent == "save":
            result = document_reply("요청서는 배출업체 작업공간에서 작성하고 보관할 수 있어요.")
        else:
            removed, candidates = delete_from_chat(db, workspace, prompt, data.document_selection)
            if removed:
                result = document_reply(f"문서 보관함에서 {removed['name']} 파일을 삭제했어요.")
                command["changed"] = True
            elif candidates:
                actions = [
                    AgentAction(id=f"archive-choice-{row['id']}",
                                label=f"{row['name']} · {row['project_title']}", value=row["id"])
                    for row in candidates[:8]
                ]
                message = "삭제할 문서를 선택해 주세요."
                if len(candidates) > len(actions):
                    message += "여기에 없으면 파일 이름을 확장자까지 입력해 주세요."
                result = document_reply(message, actions=actions, needs_information=True)
            else:
                result = document_reply("문서 보관함에서 해당 파일을 찾을 수 없어요.", needs_information=True)
        result.data = analysis_from_profile(profile)
        response = store_chat_reply(db, project_id, workspace, prompt, result, profile)
    if removed:
        document_archive.remove_upload(removed["stored_name"])
    return {**response, "document_command": command}


@app.post("/api/projects/{project_id}/select-route")
def select_route(project_id: str, data: RouteSelection, workspace: str = Depends(current_workspace)):
    with connect() as db:
        row = require_project(db, project_id, workspace)
        state = analysis_from_profile(json.loads(row["profile"]))
        permitted = {r["id"] for r in state["routes"]}
        if data.route_id not in permitted:
            raise HTTPException(status_code=400, detail="먼저 필수 정보를 입력하고 후보 경로를 확인해주세요.")
        db.execute("UPDATE projects SET selected_route=?,updated_at=? WHERE id=? AND organization_id=?",(data.route_id,utc_now(),project_id,workspace))
        updated = require_project(db, project_id, workspace)
    return {"project": project_json(updated), "analysis": analysis_from_profile(json.loads(updated["profile"]), updated["selected_route"]), "notice":"후보 경로를 임시 선택했습니다. 실제 실행 전 법규와 업체 조건 검증이 필요합니다."}


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt", ".csv", ".hwp", ".hwpx"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@app.get("/api/documents")
def get_documents(project_id: str | None = None, workspace: str = Depends(current_workspace)):
    with connect() as db:
        if project_id is not None:
            require_project(db, project_id, workspace)
        rows = document_archive.list_documents(db, workspace, project_id)
    return [document_json(r) for r in rows]


@app.post("/api/projects/{project_id}/documents", status_code=201)
async def upload_document(project_id: str, file: UploadFile = File(...), workspace: str = Depends(current_workspace)):
    with connect() as db:
        require_project(db, project_id, workspace)
    original = Path((file.filename or "").replace("\\", "/")).name
    ext = Path(original).suffix.lower()
    if not original or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400,detail="허용된 파일 형식만 업로드할 수 있습니다: PDF, 이미지, DOCX, XLSX, TXT, CSV, HWP, HWPX")
    folder = data_dir() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    doc_id = new_id()
    stored_name = doc_id + ext
    path = folder / stored_name
    size = 0
    try:
        with path.open("wb") as dst:
            while part := await file.read(1024 * 1024):
                size += len(part)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="15MB 이하의 파일만 업로드할 수 있습니다.")
                dst.write(part)
        with connect() as db:
            require_project(db, project_id, workspace)
            db.execute("INSERT INTO documents(id,project_id,name,mime,size,stored_name,created_at) VALUES (?,?,?,?,?,?,?)",(doc_id,project_id,original,file.content_type or "application/octet-stream",size,stored_name,utc_now()))
            row = db.execute("""SELECT d.*, p.title AS project_title FROM documents d
                                JOIN projects p ON p.id=d.project_id WHERE d.id=?""", (doc_id,)).fetchone()
            db.execute("UPDATE projects SET updated_at=? WHERE id=?",(utc_now(),project_id))
            return document_json(row)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        return document_archive.download_document(db, document_id, workspace)


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        row = document_archive.remove_document(db, document_id, workspace)
        if not row:
            raise HTTPException(status_code=404,detail="문서를 찾을 수 없습니다.")
    document_archive.remove_upload(row["stored_name"])
    return {"ok": True}


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str, workspace: str = Depends(current_workspace)):
    with connect() as db:
        row = require_project(db, project_id, workspace)
        messages = db.execute("SELECT * FROM messages WHERE project_id=? ORDER BY rowid",(project_id,)).fetchall()
        docs = reversed(document_archive.list_documents(db, workspace, project_id))
    return {"project":project_json(row), "analysis":analysis_from_profile(json.loads(row["profile"]),row["selected_route"]), "messages":[message_json(m) for m in messages],"documents":[document_json(d) for d in docs], "notice":"수집된 정보 및 검토 경로는 전문가 검증을 대체하지 않습니다."}



# In the hosted build, the API and browser app share a single origin.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="web")
