from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .schemas import DialogueTurn, RfidUser, UserMode


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def norm_text(value: str | None, *, limit: int = 500) -> str | None:
    text = (value or "").strip()
    return text[:limit] if text else None


@dataclass(frozen=True)
class EnrollmentRecord:
    enroll_id: str
    user: RfidUser
    status: str
    expires_at: datetime
    created_at: datetime
    completed_at: datetime | None = None
    uid: str | None = None


class ContextDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    profile_summary TEXT,
                    admin_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rfid_cards (
                    uid TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    registered_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual'
                );

                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT REFERENCES user_sessions(session_id) ON DELETE SET NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_summaries (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS enrollment_requests (
                    enroll_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    uid TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    actor TEXT,
                    device_id TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    uid TEXT,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def migrate_rfid_json(self, path: str | Path | None) -> None:
        if not path:
            return
        source = Path(path)
        if not source.exists():
            return
        with self._connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM rfid_cards").fetchone()[0] > 0:
                return
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            uid = norm_text(item.get("uid"), limit=64)
            name = norm_text(item.get("name"), limit=80) or uid
            mode_raw = norm_text(item.get("mode"), limit=20) or UserMode.study.value
            if not uid or not name:
                continue
            try:
                mode = UserMode(mode_raw)
            except ValueError:
                mode = UserMode.study
            self.create_user_with_card(uid=uid, name=name, mode=mode, source="json_migration")

    def create_user(
        self,
        *,
        name: str,
        mode: UserMode,
        profile_summary: str | None = None,
        admin_notes: str | None = None,
    ) -> RfidUser:
        stamp = utc_now().isoformat()
        user_id = f"user_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, name, mode, profile_summary, admin_notes, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    norm_text(name, limit=80) or user_id,
                    mode.value,
                    norm_text(profile_summary),
                    norm_text(admin_notes),
                    stamp,
                    stamp,
                ),
            )
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("created user was not readable")
        return user

    def create_user_with_card(
        self,
        *,
        uid: str,
        name: str,
        mode: UserMode,
        profile_summary: str | None = None,
        admin_notes: str | None = None,
        source: str = "manual",
    ) -> RfidUser:
        user = self.create_user(name=name, mode=mode, profile_summary=profile_summary, admin_notes=admin_notes)
        return self.bind_card(uid=uid, user_id=user.user_id, source=source)

    def bind_card(self, *, uid: str, user_id: str, source: str) -> RfidUser:
        stamp = utc_now().isoformat()
        normalized_uid = uid.strip().upper().replace(" ", "").replace(":", "").replace("-", "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rfid_cards(uid, user_id, registered_at, source)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET user_id=excluded.user_id, registered_at=excluded.registered_at, source=excluded.source
                """,
                (normalized_uid, user_id, stamp, norm_text(source, limit=40) or "manual"),
            )
        user = self.get_card_user(normalized_uid)
        if user is None:
            raise RuntimeError("bound card was not readable")
        self.audit("rfid_card_bound", user_id=user.user_id, uid=normalized_uid, detail=source)
        return user

    def get_user(self, user_id: str) -> RfidUser | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return self._user_from_row(row) if row else None

    def list_users(self) -> list[RfidUser]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [self._user_from_row(row) for row in rows]

    def get_card_user(self, uid: str) -> RfidUser | None:
        normalized_uid = uid.strip().upper().replace(" ", "").replace(":", "").replace("-", "")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.*, c.uid, c.registered_at
                FROM rfid_cards c
                JOIN users u ON u.user_id = c.user_id
                WHERE c.uid = ?
                """,
                (normalized_uid,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def start_enrollment(
        self,
        *,
        device_id: str,
        user_id: str | None,
        name: str | None,
        mode: UserMode,
        profile_summary: str | None,
        admin_notes: str | None,
        ttl_seconds: int,
    ) -> EnrollmentRecord:
        user = self.get_user(user_id) if user_id else None
        if user is None:
            user = self.create_user(
                name=name or "new-user",
                mode=mode,
                profile_summary=profile_summary,
                admin_notes=admin_notes,
            )
        now = utc_now()
        expires_at = now + timedelta(seconds=max(10, min(300, ttl_seconds)))
        enroll_id = f"enroll_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "UPDATE enrollment_requests SET status = 'expired' WHERE device_id = ? AND status = 'pending'",
                (device_id,),
            )
            conn.execute(
                """
                INSERT INTO enrollment_requests(enroll_id, device_id, user_id, status, created_at, expires_at)
                VALUES(?, ?, ?, 'pending', ?, ?)
                """,
                (enroll_id, device_id, user.user_id, now.isoformat(), expires_at.isoformat()),
            )
        self.audit("rfid_enroll_started", actor="control", device_id=device_id, user_id=user.user_id)
        record = self.get_enrollment(enroll_id)
        if record is None:
            raise RuntimeError("created enrollment was not readable")
        return record

    def pending_enrollment_for_device(self, device_id: str) -> EnrollmentRecord | None:
        self.expire_enrollments()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM enrollment_requests
                WHERE device_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return self._enrollment_from_row(row) if row else None

    def get_enrollment(self, enroll_id: str) -> EnrollmentRecord | None:
        self.expire_enrollments()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM enrollment_requests WHERE enroll_id = ?", (enroll_id,)).fetchone()
        return self._enrollment_from_row(row) if row else None

    def complete_enrollment(self, enroll_id: str, uid: str) -> EnrollmentRecord:
        record = self.get_enrollment(enroll_id)
        if record is None:
            raise ValueError("unknown enrollment")
        if record.status != "pending":
            return record
        user = self.bind_card(uid=uid, user_id=record.user.user_id, source="online_enroll")
        completed_at = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE enrollment_requests SET status = 'completed', uid = ?, completed_at = ? WHERE enroll_id = ?",
                (user.uid, completed_at, enroll_id),
            )
        self.audit("rfid_enroll_completed", actor="device", device_id=None, user_id=user.user_id, uid=user.uid)
        completed = self.get_enrollment(enroll_id)
        if completed is None:
            raise RuntimeError("completed enrollment was not readable")
        return completed

    def cancel_enrollment(self, enroll_id: str) -> EnrollmentRecord | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE enrollment_requests SET status = 'cancelled' WHERE enroll_id = ? AND status = 'pending'",
                (enroll_id,),
            )
        self.audit("rfid_enroll_cancelled", actor="control", detail=enroll_id)
        return self.get_enrollment(enroll_id)

    def expire_enrollments(self) -> None:
        stamp = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE enrollment_requests SET status = 'expired' WHERE status = 'pending' AND expires_at < ?",
                (stamp,),
            )

    def create_session(self, *, user_id: str, device_id: str, source: str, ttl_seconds: int = 14400) -> str:
        now = utc_now()
        session_id = f"sess_{uuid4().hex[:12]}"
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_sessions SET ended_at = ? WHERE device_id = ? AND ended_at IS NULL",
                (now.isoformat(), device_id),
            )
            conn.execute(
                """
                INSERT INTO user_sessions(session_id, user_id, device_id, source, started_at, last_seen_at, expires_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, device_id, source, now.isoformat(), now.isoformat(), expires_at.isoformat()),
            )
        self.audit("context_selected", actor=source, device_id=device_id, user_id=user_id, session_id=session_id)
        return session_id

    def touch_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE user_sessions SET last_seen_at = ? WHERE session_id = ?", (utc_now().isoformat(), session_id))

    def add_memory_event(self, *, user_id: str, session_id: str | None, role: str, text: str, source: str | None) -> None:
        message = text.strip()
        if not message:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_events(event_id, user_id, session_id, role, text, source, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (f"mem_{uuid4().hex[:12]}", user_id, session_id, role, message, source, utc_now().isoformat()),
            )
        if session_id:
            self.touch_session(session_id)

    def recent_dialogue(self, *, user_id: str, session_id: str | None, limit: int = 12) -> list[DialogueTurn]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    """
                    SELECT role, text, source, created_at FROM memory_events
                    WHERE user_id = ? AND session_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT role, text, source, created_at FROM memory_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
        turns = [
            DialogueTurn(role=row["role"], text=row["text"], source=row["source"], time=parse_dt(row["created_at"]) or utc_now())
            for row in reversed(rows)
        ]
        return turns

    def audit(
        self,
        event_type: str,
        *,
        actor: str | None = None,
        device_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        uid: str | None = None,
        detail: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(audit_id, event_type, actor, device_id, user_id, session_id, uid, detail, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"audit_{uuid4().hex[:12]}",
                    event_type,
                    actor,
                    device_id,
                    user_id,
                    session_id,
                    uid,
                    detail,
                    utc_now().isoformat(),
                ),
            )

    def _user_from_row(self, row: sqlite3.Row) -> RfidUser:
        created_at = parse_dt(row["created_at"]) or utc_now()
        updated_at = parse_dt(row["updated_at"]) or created_at
        return RfidUser(
            user_id=row["user_id"],
            uid=row["uid"] if "uid" in row.keys() else None,
            name=row["name"],
            mode=UserMode(row["mode"]),
            profile_summary=row["profile_summary"],
            admin_notes=row["admin_notes"],
            registered_at=parse_dt(row["registered_at"]) if "registered_at" in row.keys() else created_at,
            updated_at=updated_at,
        )

    def _enrollment_from_row(self, row: sqlite3.Row) -> EnrollmentRecord:
        user = self.get_user(row["user_id"])
        if user is None:
            raise RuntimeError(f"enrollment user missing: {row['user_id']}")
        return EnrollmentRecord(
            enroll_id=row["enroll_id"],
            user=user,
            status=row["status"],
            expires_at=parse_dt(row["expires_at"]) or utc_now(),
            created_at=parse_dt(row["created_at"]) or utc_now(),
            completed_at=parse_dt(row["completed_at"]),
            uid=row["uid"],
        )
