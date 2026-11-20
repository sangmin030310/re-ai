"""Handle document commands before sending ordinary chat to the AI provider."""
import re
from pathlib import PurePath

from pydantic import ValidationError

from .agents.contract import AgentAction, AgentReply
from .document_archive import list_documents, remove_document
from .matching import IntakeRequest, persist_request
from .request_chat import DEFERRABLE_FIELDS, missing_fields


ARCHIVE = re.compile(r"문서(?:보관)?함|보관함|문서목록")
DOCUMENT = re.compile(r"문서|파일|요청서|의뢰서|보고서|자료|첨부")
FILE_EXTENSION = re.compile(r"\.(?:docx?|pdf|xlsx?|hwpx?|csv|txt|png|jpe?g)(?![a-z0-9])", re.I)
DELETE = re.compile(r"(?:삭제|제거)(?:해(?:줘|주세요|줄래|$)|해주세요|하세요|부탁|$)|(?:지워|없애|빼)(?:줘|주세요|줄래|$)")
SAVE = re.compile(r"(?:저장|보관)(?:해(?:줘|주세요|줄래|$)|해주세요|하세요|부탁|$)|(?:넣어|담아)(?:줘|주세요|줄래|$)")
OPEN = re.compile(r"열어|보여|목록|어디|뭐(?:가)?있|확인(?:해줘|하고싶)|들어가")
NOT_A_COMMAND = re.compile(r"하지마|지우지마|넣지마|빼지마|없애지마|방법|어떻게|예를들어")


def document_intent(prompt: str) -> str | None:
    compact = re.sub(r"\s+", "", prompt).rstrip(".!?。")
    archive = ARCHIVE.search(compact)
    document = archive or DOCUMENT.search(compact) or FILE_EXTENSION.search(compact)
    if not document or NOT_A_COMMAND.search(compact):
        return None
    if DELETE.search(compact):
        return "delete"
    if SAVE.search(compact):
        return "save"
    if archive and OPEN.search(compact):
        return "open"
    return None


def document_reply(message: str, *, actions=(), needs_information=False) -> AgentReply:
    return AgentReply(
        agent="document_archive",
        status="needs_information" if needs_information else "review_ready",
        message=message,
        actions=list(actions),
    )


def save_from_chat(db, project, workspace, profile, request_draft):
    draft = {**profile, **(request_draft or {})}
    missing = [label for key, label, _ in missing_fields(draft) if key not in DEFERRABLE_FIELDS]
    if missing:
        return document_reply(f"요청서를 저장하려면 {', '.join(missing)}을(를) 먼저 입력해 주세요.",
                              needs_information=True), {"changed": False}
    for key in DEFERRABLE_FIELDS:
        if not draft.get(key):
            draft[key] = "확인 필요"
    try:
        request = IntakeRequest.model_validate(draft)
    except ValidationError:
        return document_reply("요청서에 입력한 재질, 물량과 지역 등 항목을 확인해 주세요.",
                              needs_information=True), {"changed": False}
    persist_request(db, project["id"], request, workspace)
    return (
        document_reply("요청서를 Word 파일로 문서 보관함에 저장했어요.", actions=[
            AgentAction(id="open-document-archive", label="문서 보관함 열기", value="문서 보관함을 열어줘"),
        ]),
        {"changed": True, "saved_request": request.model_dump()},
    )


def delete_from_chat(db, workspace, prompt, selected_id):
    if selected_id:
        return remove_document(db, selected_id, workspace), []

    documents = list_documents(db, workspace)
    normalized = prompt.casefold()
    named = [doc for doc in documents if doc["name"].casefold() in normalized]
    if len(named) == 1:
        return remove_document(db, named[0]["id"], workspace), []
    if named:
        return None, named
    if FILE_EXTENSION.search(prompt):
        return None, []
    mentioned = [doc for doc in documents if PurePath(doc["name"]).stem.casefold() in normalized]
    return None, mentioned or documents
