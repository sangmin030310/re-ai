"""Storage shared by the document archive and the project conversation."""
import re
from urllib.parse import quote

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse

from .db import data_dir, new_id, utc_now
from .request_document import WORD_MIME, render_request_document


def list_documents(db, workspace, project_id=None):
    sql = """
        SELECT d.id, d.project_id, d.name, d.mime, d.size, d.created_at, p.title AS project_title,
               CASE WHEN d.generated_content IS NULL THEN 'upload' ELSE 'request' END AS source
        FROM documents d JOIN projects p ON p.id=d.project_id WHERE p.organization_id=?
    """
    if project_id is not None:
        return db.execute(sql + " AND d.project_id=? ORDER BY d.created_at DESC, d.rowid DESC",
                          (workspace, project_id)).fetchall()
    return db.execute(sql + " ORDER BY d.created_at DESC, d.rowid DESC", (workspace,)).fetchall()


def archive_request(db, project, request, *, title, company, unchanged, now):
    project_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", project["title"]).strip(" .") or "요청서"
    filename = f"{project_name} - {title}.docx"
    existing = db.execute(
        "SELECT name FROM documents WHERE project_id=? AND generated_content IS NOT NULL",
        (project["id"],),
    ).fetchone()
    if unchanged and existing and existing["name"] == filename:
        return
    content = render_request_document(request, title=title, company=company)
    db.execute("""
        INSERT INTO documents(id, project_id, name, mime, size, stored_name, created_at, generated_content)
        VALUES (?, ?, ?, ?, ?, '', ?, ?)
        ON CONFLICT(project_id) WHERE generated_content IS NOT NULL DO UPDATE SET
            name=excluded.name, size=excluded.size, created_at=excluded.created_at,
            generated_content=excluded.generated_content
    """, (new_id(), project["id"], filename, WORD_MIME, len(content), now, content))


def word_download(content: bytes, filename: str) -> Response:
    return Response(content, media_type=WORD_MIME,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})


def download_document(db, document_id, workspace):
    row = db.execute("""
        SELECT d.name, d.stored_name, d.generated_content FROM documents d
        JOIN projects p ON p.id=d.project_id WHERE d.id=? AND p.organization_id=?
    """, (document_id, workspace)).fetchone()
    if not row:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    if row["generated_content"] is not None:
        return word_download(row["generated_content"], row["name"])
    path = data_dir() / "uploads" / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "보관된 파일이 없습니다.")
    return FileResponse(path, filename=row["name"], media_type="application/octet-stream")


def remove_document(db, document_id, workspace):
    return db.execute("""
        DELETE FROM documents WHERE id=? AND project_id IN (
            SELECT id FROM projects WHERE organization_id=?
        ) RETURNING stored_name, name
    """, (document_id, workspace)).fetchone()


def remove_upload(stored_name: str):
    if stored_name:
        (data_dir() / "uploads" / stored_name).unlink(missing_ok=True)
