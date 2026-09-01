import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS cvs (
    cv_id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    status TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    error_message TEXT,
    photo_path TEXT
);

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    cv_id TEXT NOT NULL,
    section TEXT NOT NULL,
    fields TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    confidence_band TEXT NOT NULL,
    validation_flags TEXT NOT NULL,
    status TEXT NOT NULL,
    edit_history TEXT NOT NULL,
    FOREIGN KEY (cv_id) REFERENCES cvs (cv_id)
);

CREATE TABLE IF NOT EXISTS staff_profiles (
    profile_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    job_title TEXT,
    mdx_email TEXT,
    desk_phone TEXT,
    links TEXT NOT NULL DEFAULT '{}',
    memberships TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cv_id TEXT NOT NULL,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);

-- HR-taught heading -> section rules. A CV's exact wording for something
-- with no MDX equivalent ("Professional Development", "Volunteer Work")
-- cannot be fully enumerated in advance; this is how HR adds one themselves,
-- from the review screen, in seconds -- no code change, no restart, and it
-- applies to every CV uploaded from that point on, not just the one in
-- front of them.
CREATE TABLE IF NOT EXISTS custom_heading_mappings (
    mapping_id TEXT PRIMARY KEY,
    heading_text TEXT NOT NULL,
    section_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Operator-configurable settings, e.g. the auto-approval confidence
-- threshold. Key/value so a new setting never needs a schema migration.
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cvs)")}
        if "photo_path" not in existing_cols:
            conn.execute("ALTER TABLE cvs ADD COLUMN photo_path TEXT")


def log_event(cv_id: str, action: str, detail: str = "", at: str = "") -> None:
    from datetime import datetime, timezone

    ts = at or datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (cv_id, at, action, detail) VALUES (?, ?, ?, ?)",
            (cv_id, ts, action, detail),
        )


def create_cv(cv_id: str, original_filename: str, stored_path: str, status: str, uploaded_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cvs (cv_id, original_filename, stored_path, status, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (cv_id, original_filename, stored_path, status, uploaded_at),
        )


def update_cv_status(cv_id: str, status: str, error_message: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE cvs SET status = ?, error_message = ? WHERE cv_id = ?",
            (status, error_message, cv_id),
        )


def set_cv_photo(cv_id: str, photo_path: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE cvs SET photo_path = ? WHERE cv_id = ?",
            (photo_path, cv_id),
        )


def get_cv(cv_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cvs WHERE cv_id = ?", (cv_id,)).fetchone()
        return dict(row) if row else None


def list_cvs() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cvs ORDER BY uploaded_at DESC").fetchall()
        return [dict(r) for r in rows]


def save_items(cv_id: str, items: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE cv_id = ?", (cv_id,))
        for it in items:
            conn.execute(
                """INSERT INTO items
                   (item_id, cv_id, section, fields, source, confidence,
                    confidence_band, validation_flags, status, edit_history)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    it["item_id"], cv_id, it["section"],
                    json.dumps(it["fields"]), json.dumps(it["source"]),
                    it["confidence"], it["confidence_band"],
                    json.dumps(it["validation_flags"]), it["status"],
                    json.dumps(it["edit_history"]),
                ),
            )


def get_items(cv_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM items WHERE cv_id = ?", (cv_id,)).fetchall()
        return [_row_to_item(r) for r in rows]


def get_item(item_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None


def update_item(item_id: str, **kwargs: Any) -> None:
    fields_to_set = []
    values = []
    for key in ("section", "fields", "confidence", "confidence_band", "validation_flags", "status", "edit_history"):
        if key in kwargs:
            fields_to_set.append(f"{key} = ?")
            val = kwargs[key]
            if key in ("fields", "validation_flags", "edit_history"):
                val = json.dumps(val)
            values.append(val)
    if not fields_to_set:
        return
    values.append(item_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE items SET {', '.join(fields_to_set)} WHERE item_id = ?", values)


def upsert_profile(profile: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO staff_profiles
               (profile_id, full_name, job_title, mdx_email, desk_phone, links, memberships, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_id) DO UPDATE SET
                 full_name=excluded.full_name, job_title=excluded.job_title,
                 mdx_email=excluded.mdx_email, desk_phone=excluded.desk_phone,
                 links=excluded.links, memberships=excluded.memberships,
                 updated_at=excluded.updated_at""",
            (
                profile["profile_id"], profile["full_name"], profile.get("job_title"),
                profile.get("mdx_email"), profile.get("desk_phone"),
                json.dumps(profile.get("links", {})),
                json.dumps(profile.get("memberships", [])),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_profile(profile_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM staff_profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        return _row_to_profile(row) if row else None


def list_profiles() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM staff_profiles ORDER BY full_name").fetchall()
        return [_row_to_profile(r) for r in rows]


def delete_profile(profile_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM staff_profiles WHERE profile_id = ?", (profile_id,))


def _row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["links"] = json.loads(d.get("links") or "{}")
    d["memberships"] = json.loads(d.get("memberships") or "[]")
    return d


def bulk_update_status(item_ids: list[str], status: str) -> int:
    """Set the same status on many items in one transaction. Returns the
    number of rows changed."""
    if not item_ids:
        return 0
    placeholders = ",".join("?" for _ in item_ids)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE items SET status = ? WHERE item_id IN ({placeholders})",
            [status, *item_ids],
        )
        return cur.rowcount


def delete_item(item_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE item_id = ?", (item_id,))


def insert_item(item: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO items
               (item_id, cv_id, section, fields, source, confidence,
                confidence_band, validation_flags, status, edit_history)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["item_id"], item["cv_id"], item["section"],
                json.dumps(item["fields"]), json.dumps(item["source"]),
                item["confidence"], item["confidence_band"],
                json.dumps(item["validation_flags"]), item["status"],
                json.dumps(item["edit_history"]),
            ),
        )


def add_heading_mapping(heading_text: str, section_key: str) -> dict[str, Any]:
    import uuid
    from datetime import datetime, timezone

    mapping = {
        "mapping_id": str(uuid.uuid4()),
        "heading_text": heading_text.strip(),
        "section_key": section_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO custom_heading_mappings (mapping_id, heading_text, section_key, created_at) "
            "VALUES (?, ?, ?, ?)",
            (mapping["mapping_id"], mapping["heading_text"], mapping["section_key"], mapping["created_at"]),
        )
    return mapping


def list_heading_mappings() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM custom_heading_mappings ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_heading_mapping(mapping_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM custom_heading_mappings WHERE mapping_id = ?", (mapping_id,))


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
    except sqlite3.OperationalError:
        # app_settings doesn't exist yet (e.g. a test harness that talks to
        # validation.py directly without calling storage.init_db() first).
        # Falling back to the caller's default here, rather than raising,
        # is what keeps this change invisible to every existing test and
        # every CV processed before a setting is ever written.
        return default


def set_setting(key: str, value: str) -> None:
    from datetime import datetime, timezone
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )


def get_audit_log(cv_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, cv_id, at, action, detail FROM audit_log "
            "WHERE cv_id = ? ORDER BY at ASC",
            (cv_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_unmapped_items_with_cv() -> list[dict]:
    """Raw rows for the cross-CV dashboard. Returns fields as a JSON
    string -- decoding is insights.py's job, not storage's, matching how
    _row_to_item() is the only place that decodes elsewhere."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT cv_id, fields FROM items WHERE section = 'unmapped'"
        ).fetchall()
        return [dict(r) for r in rows]


def list_resolved_formerly_unmapped_items() -> list[dict]:
    """Items that started in the unmapped safety net -- unmapped.py stamps
    a "context" key (the source heading text) into every item it creates,
    and nothing else in the codebase writes that key -- and have SINCE
    been moved to a real section, whether by a manual move or an accepted
    AI suggestion (both go through the same PATCH endpoint and leave
    `fields` otherwise untouched). Raw material for build spec §14: an
    actual correction HR already made, not a guess about one. The `LIKE`
    clause is a cheap pre-filter only; the real check (a genuine JSON
    "context" key, not a coincidental substring) happens in Python once
    fields is decoded, same division of labour as
    list_unmapped_items_with_cv() above."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT cv_id, section, fields FROM items "
            "WHERE section != 'unmapped' AND fields LIKE '%\"context\"%'"
        ).fetchall()
        return [dict(r) for r in rows]


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["fields"] = json.loads(d["fields"])
    d["source"] = json.loads(d["source"])
    d["validation_flags"] = json.loads(d["validation_flags"])
    d["edit_history"] = json.loads(d["edit_history"])
    return d
