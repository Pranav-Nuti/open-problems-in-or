"""SQLite helpers for users, uploads, and extract jobs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional

from . import config


USER_STATUSES = frozenset({"pending", "approved", "rejected"})
DEFAULT_USER_STATUS = "approved"


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, typedef: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'uploader',
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS uploads (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              filename TEXT NOT NULL,
              stored_name TEXT NOT NULL UNIQUE,
              content_type TEXT NOT NULL,
              size_bytes INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'received',
              uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_uploads_user_id ON uploads(user_id);

            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
              kind TEXT NOT NULL DEFAULT 'extract',
              status TEXT NOT NULL DEFAULT 'queued',
              error_message TEXT,
              result_upload_id INTEGER REFERENCES uploads(id) ON DELETE SET NULL,
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              started_at TEXT,
              finished_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_upload_id ON jobs(upload_id);

            CREATE TABLE IF NOT EXISTS job_artifacts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
              artifact_kind TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);
            """
        )
        _ensure_column(conn, "uploads", "parent_upload_id", "INTEGER REFERENCES uploads(id)")
        _ensure_column(conn, "uploads", "kind", "TEXT NOT NULL DEFAULT 'source'")
        _ensure_column(conn, "jobs", "stages_json", "TEXT")
        _ensure_column(conn, "uploads", "archived_at", "TEXT")
        # Account approval (Phase A): existing rows become approved so logins keep working.
        _ensure_column(conn, "users", "email", "TEXT")
        _ensure_column(conn, "users", "status", "TEXT NOT NULL DEFAULT 'approved'")
        _ensure_column(conn, "users", "approved_at", "TEXT")
        _ensure_column(conn, "users", "approved_by", "INTEGER")
        conn.execute(
            """
            UPDATE users
            SET status = 'approved',
                approved_at = COALESCE(approved_at, created_at)
            WHERE status IS NULL OR TRIM(status) = '' OR status NOT IN ('pending', 'approved', 'rejected')
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
            ON users(email)
            WHERE email IS NOT NULL AND TRIM(email) != ''
            """
        )


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    cleaned = (email or "").strip()
    if not cleaned:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
            (cleaned,),
        ).fetchone()
    return dict(row) if row else None


def create_user(
    *,
    username: str,
    password_hash: str,
    role: str = "admin",
    email: Optional[str] = None,
    status: str = DEFAULT_USER_STATUS,
    approved_by: Optional[int] = None,
) -> Dict[str, Any]:
    status_key = (status or DEFAULT_USER_STATUS).strip().lower()
    if status_key not in USER_STATUSES:
        raise ValueError(f"Invalid user status: {status}")
    email_value = (email or "").strip() or None
    approved_at = None
    if status_key == "approved":
        # Use DB clock via SQL below.
        approved_at = True
    with db() as conn:
        if approved_at:
            cur = conn.execute(
                """
                INSERT INTO users (
                  username, password_hash, role, email, status, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?)
                """,
                (username, password_hash, role, email_value, status_key, approved_by),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO users (
                  username, password_hash, role, email, status, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (username, password_hash, role, email_value, status_key, approved_by),
            )
        user_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row)


def set_user_status(
    *,
    user_id: int,
    status: str,
    approved_by: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    status_key = (status or "").strip().lower()
    if status_key not in USER_STATUSES:
        raise ValueError(f"Invalid user status: {status}")
    with db() as conn:
        if status_key == "approved":
            conn.execute(
                """
                UPDATE users
                SET status = ?,
                    approved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    approved_by = ?
                WHERE id = ?
                """,
                (status_key, approved_by, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET status = ?,
                    approved_at = NULL,
                    approved_by = NULL
                WHERE id = ?
                """,
                (status_key, user_id),
            )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users_by_status(status: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    status_key = (status or "").strip().lower()
    if status_key not in USER_STATUSES:
        raise ValueError(f"Invalid user status: {status}")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM users
            WHERE status = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (status_key, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def count_users() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"])


def insert_upload(
    *,
    user_id: int,
    filename: str,
    stored_name: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    status: str = "received",
    parent_upload_id: Optional[int] = None,
    kind: str = "source",
) -> Dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO uploads (
              user_id, filename, stored_name, content_type, size_bytes, sha256,
              status, parent_upload_id, kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                filename,
                stored_name,
                content_type,
                size_bytes,
                sha256,
                status,
                parent_upload_id,
                kind,
            ),
        )
        upload_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    return dict(row)


def list_uploads_for_user(user_id: int, *, limit: int = 50) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, size_bytes, status, uploaded_at, sha256,
                   parent_upload_id, kind
            FROM uploads
            WHERE user_id = ? AND archived_at IS NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def archive_uploads_for_user(user_id: int, *, scope: str) -> Dict[str, int]:
    """Hide the caller's listed uploads without deleting anything on disk.

    scope "sources" archives source uploads (skipping any with a queued or
    running job); scope "results" archives job-output uploads (extraction,
    literature review, solver attempt PDFs). Returns counts.
    """
    if scope not in {"sources", "results"}:
        raise ValueError(f"Unknown archive scope: {scope}")
    with db() as conn:
        # UPDATE first, then count what stayed behind: both statements share
        # the UPDATE's implicit transaction, so the reported counts cannot be
        # skewed by a job finishing or queueing between two autocommit reads.
        if scope == "sources":
            cur = conn.execute(
                """
                UPDATE uploads
                SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE user_id = ? AND archived_at IS NULL
                  AND (kind = 'source' OR kind IS NULL)
                  AND NOT EXISTS (
                    SELECT 1 FROM jobs j
                    WHERE j.upload_id = uploads.id AND j.status IN ('queued', 'running')
                  )
                """,
                (user_id,),
            )
            skipped = conn.execute(
                """
                SELECT COUNT(*) AS n FROM uploads u
                WHERE u.user_id = ? AND u.archived_at IS NULL
                  AND (u.kind = 'source' OR u.kind IS NULL)
                  AND EXISTS (
                    SELECT 1 FROM jobs j
                    WHERE j.upload_id = u.id AND j.status IN ('queued', 'running')
                  )
                """,
                (user_id,),
            ).fetchone()
            return {"archived": int(cur.rowcount), "skipped_active": int(skipped["n"])}
        # Results: keep outputs that belong to a still-active job, so one
        # run's artifacts are never split between hidden and visible.
        cur = conn.execute(
            """
            UPDATE uploads
            SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE user_id = ? AND archived_at IS NULL
              AND kind IS NOT NULL AND kind != 'source'
              AND NOT EXISTS (
                SELECT 1 FROM job_artifacts ja
                JOIN jobs j ON j.id = ja.job_id
                WHERE ja.upload_id = uploads.id AND j.status IN ('queued', 'running')
              )
            """,
            (user_id,),
        )
        skipped = conn.execute(
            """
            SELECT COUNT(*) AS n FROM uploads u
            WHERE u.user_id = ? AND u.archived_at IS NULL
              AND u.kind IS NOT NULL AND u.kind != 'source'
              AND EXISTS (
                SELECT 1 FROM job_artifacts ja
                JOIN jobs j ON j.id = ja.job_id
                WHERE ja.upload_id = u.id AND j.status IN ('queued', 'running')
              )
            """,
            (user_id,),
        ).fetchone()
        return {"archived": int(cur.rowcount), "skipped_active": int(skipped["n"])}


def unarchive_upload(upload_id: int) -> None:
    """Make an upload visible again (e.g. when a new job is queued on it)."""
    with db() as conn:
        conn.execute(
            "UPDATE uploads SET archived_at = NULL WHERE id = ?",
            (upload_id,),
        )


def get_upload_by_id(upload_id: int) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    return dict(row) if row else None


def storage_path(stored_name: str) -> Path:
    return config.UPLOAD_DIR / stored_name


def job_public(row: Dict[str, Any], *, artifacts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    out = {
        "id": row["id"],
        "upload_id": row["upload_id"],
        "kind": row["kind"],
        "status": row["status"],
        "error_message": row.get("error_message"),
        "result_upload_id": row.get("result_upload_id"),
        "created_at": row["created_at"],
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }
    if artifacts is not None:
        out["artifacts"] = artifacts
    stages_raw = row.get("stages_json")
    if stages_raw:
        try:
            out["stages"] = json.loads(stages_raw)
        except Exception:
            out["stages"] = None
    return out


def list_job_artifacts(job_id: int) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT ja.id, ja.job_id, ja.upload_id, ja.artifact_kind, ja.created_at,
                   u.filename, u.kind AS upload_kind, u.status AS upload_status
            FROM job_artifacts ja
            JOIN uploads u ON u.id = ja.upload_id
            WHERE ja.job_id = ?
            ORDER BY ja.id ASC
            """,
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_job_artifact(*, job_id: int, upload_id: int, artifact_kind: str) -> Dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO job_artifacts (job_id, upload_id, artifact_kind)
            VALUES (?, ?, ?)
            """,
            (job_id, upload_id, artifact_kind),
        )
        art_id = int(cur.lastrowid)
        # Keep result_upload_id as the latest artifact for backwards compatibility.
        conn.execute(
            "UPDATE jobs SET result_upload_id = ? WHERE id = ?",
            (upload_id, job_id),
        )
        row = conn.execute(
            """
            SELECT ja.id, ja.job_id, ja.upload_id, ja.artifact_kind, ja.created_at,
                   u.filename, u.kind AS upload_kind, u.status AS upload_status
            FROM job_artifacts ja
            JOIN uploads u ON u.id = ja.upload_id
            WHERE ja.id = ?
            """,
            (art_id,),
        ).fetchone()
    return dict(row)


def create_job(*, upload_id: int, kind: str = "extract") -> Dict[str, Any]:
    with db() as conn:
        existing = conn.execute(
            """
            SELECT * FROM jobs
            WHERE upload_id = ? AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (upload_id,),
        ).fetchone()
        if existing:
            return dict(existing)
        cur = conn.execute(
            "INSERT INTO jobs (upload_id, kind, status) VALUES (?, ?, 'queued')",
            (upload_id, kind),
        )
        job_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row)


def get_job_by_id(job_id: int) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def job_public_full(job_id: int) -> Optional[Dict[str, Any]]:
    job = get_job_by_id(job_id)
    if not job:
        return None
    return job_public(job, artifacts=list_job_artifacts(job_id))


def list_jobs_for_upload(upload_id: int, *, limit: int = 20) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE upload_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (upload_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def claim_next_job(*, kind: str = "extract") -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued' AND kind = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        if not row:
            return None
        job_id = int(row["id"])
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                error_message = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (job_id,),
        )
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not claimed or claimed["status"] != "running":
            return None
        return dict(claimed)


def mark_job_done(*, job_id: int, result_upload_id: Optional[int] = None) -> Dict[str, Any]:
    with db() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'done',
                result_upload_id = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                error_message = NULL
            WHERE id = ?
            """,
            (result_upload_id, job_id),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row)


def mark_job_failed(*, job_id: int, error_message: str) -> Dict[str, Any]:
    with db() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error_message = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (error_message[:2000], job_id),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row)


def list_active_jobs(*, statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    wanted = statuses or ["queued", "running"]
    placeholders = ",".join("?" for _ in wanted)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE status IN ({placeholders})
            ORDER BY id ASC
            """,
            tuple(wanted),
        ).fetchall()
    return [dict(row) for row in rows]


def update_job_stages(*, job_id: int, stages: Dict[str, Any]) -> Dict[str, Any]:
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET stages_json = ? WHERE id = ?",
            (json.dumps(stages), job_id),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row)
