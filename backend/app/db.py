"""Small SQLite persistence layer for local MVP. Not a multi-user production store."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_dir() -> Path:
    root = Path(__file__).resolve().parents[2] / "data"
    if os.getenv("REAI_ENV", "").strip().lower() == "online-demo":
        root /= "online-demo"
    path = Path(os.getenv("REAI_DATA_DIR") or root)
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    db = sqlite3.connect(data_dir() / "reai.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, title TEXT NOT NULL,
          organization_id TEXT NOT NULL DEFAULT 'local',
          profile TEXT NOT NULL DEFAULT '{}', selected_route TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL, actions TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
          stored_name TEXT NOT NULL, created_at TEXT NOT NULL, generated_content BLOB
        );
        """)
        db.execute("BEGIN IMMEDIATE")
        # Preserve v1-v3 conversation history and documents in the local workspace.
        # For a real company launch, these old records must be reviewed, not migrated
        # as if they were authenticated company data.
        columns = {r["name"] for r in db.execute("PRAGMA table_info(projects)").fetchall()}
        if "organization_id" not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'local'")
        db.execute("CREATE INDEX IF NOT EXISTS idx_projects_organization ON projects(organization_id,updated_at)")
        if "generated_content" not in {row["name"] for row in db.execute("PRAGMA table_info(documents)")}:
            db.execute("ALTER TABLE documents ADD COLUMN generated_content BLOB")
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_request ON documents(project_id)
            WHERE generated_content IS NOT NULL
        """)


def new_id() -> str:
    return str(uuid4())


def project_json(row) -> dict:
    return {"id": row["id"], "title": row["title"], "organization_id": row["organization_id"], "profile": json.loads(row["profile"]), "selected_route": row["selected_route"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def message_json(row) -> dict:
    return {"id": row["id"], "project_id": row["project_id"], "role": row["role"], "content": row["content"], "actions": json.loads(row["actions"]), "created_at": row["created_at"]}


def document_json(row) -> dict:
    keys = row.keys()
    return {"id": row["id"], "project_id": row["project_id"], "name": row["name"], "mime": row["mime"], "size": row["size"],
            "created_at": row["created_at"], "source": row["source"] if "source" in keys else "upload",
            "project_title": row["project_title"] if "project_title" in keys else None}


def ensure_sample():
    from .agents.mock_gateway import merge_profile
    with connect() as db:
        if db.execute("SELECT COUNT(*) FROM projects WHERE organization_id='local'").fetchone()[0]:
            return
        pid = new_id()
        now = utc_now()
        prompt = "자동차 부품 공장에서 PP 폐플라스틱이 매월 3톤 발생합니다. 재활용할 수 있을까요?"
        profile = merge_profile({}, prompt)
        db.execute("INSERT INTO projects(id,title,profile,created_at,updated_at) VALUES (?,?,?,?,?)", (pid,"폐플라스틱 재활용 검토",json.dumps(profile,ensure_ascii=False),now,now))
        for role, content, actions in [
            ("user",prompt,[]),
            ("assistant","네, 폐플라스틱의 **활용 가능 경로를 검토**해보겠습니다. 먼저 오염 여부를 확인해야 합니다. 유분이나 이물질이 묻어 있나요?",[{"id":"clean","label":"오염 없음","value":"오염 없음"},{"id":"dirty","label":"오염 있음","value":"유분 등 오염 있음"}]),
        ]:
            db.execute("INSERT INTO messages(id,project_id,role,content,actions,created_at) VALUES (?,?,?,?,?,?)",(new_id(),pid,role,content,json.dumps(actions,ensure_ascii=False),now))
