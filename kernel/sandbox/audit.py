"""SQLite-backed audit log for sandbox dispatches.

Every action that passes through the sandbox is appended here (success,
denied, or error). Used for:
- User-visible "what did my agents do today" view (Settings)
- Security forensics ("why was my GPS data sent?")
- Quota analytics (per-skill usage over time)

Schema is append-only; no row updates. Old rows trimmed by retention policy
(default 30 days) on boot.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30


@dataclass(frozen=True)
class AuditRecord:
    """One row in the audit log."""

    timestamp: float
    backend: str
    agent: str
    action: str
    caller: str = "user"
    status: str = "ok"                 # ok | denied | error
    denied_reason: str | None = None   # permission | rate_limit | safety
    duration_ms: int = 0
    request_id: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sandbox_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    backend         TEXT    NOT NULL,
    agent           TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    caller          TEXT    NOT NULL DEFAULT 'user',
    status          TEXT    NOT NULL DEFAULT 'ok',
    denied_reason   TEXT,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    request_id      TEXT    NOT NULL DEFAULT '',
    error           TEXT,
    extra           TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_agent_ts
    ON sandbox_audit(agent, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_status_ts
    ON sandbox_audit(status, timestamp DESC);
"""


class AuditLog:
    """Thread-safe sync writer/reader for the audit log.

    Uses sqlite3 directly (not aiosqlite) because writes are fire-and-forget
    short transactions. Reads can be called from async endpoints — SQLite
    is fast enough for a few-hundred-row queries.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._db_path = Path(db_path)
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._ensure_schema()
        self._prune_old()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _prune_old(self) -> None:
        cutoff = time.time() - self._retention_days * 86400
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM sandbox_audit WHERE timestamp < ?", (cutoff,),
            )

    def write(self, record: AuditRecord | dict[str, Any]) -> None:
        """Append a record. Swallows errors — audit must never fail a dispatch."""
        if isinstance(record, AuditRecord):
            data = record.to_dict()
        else:
            data = dict(record)

        # Stable fields (drop anything extra into 'extra' JSON)
        known = {
            "timestamp", "backend", "agent", "action", "caller",
            "status", "denied_reason", "duration_ms", "request_id", "error",
        }
        row = {k: data.get(k) for k in known}
        extra = {k: v for k, v in data.items() if k not in known}

        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sandbox_audit
                        (timestamp, backend, agent, action, caller,
                         status, denied_reason, duration_ms, request_id, error, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("timestamp") or time.time(),
                        row.get("backend") or "",
                        row.get("agent") or "",
                        row.get("action") or "",
                        row.get("caller") or "user",
                        row.get("status") or "ok",
                        row.get("denied_reason"),
                        int(row.get("duration_ms") or 0),
                        row.get("request_id") or "",
                        row.get("error"),
                        json.dumps(extra, default=str) if extra else None,
                    ),
                )
        except Exception:
            logger.exception("Failed to write audit row")

    def query(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read recent audit records with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT * FROM sandbox_audit {where} "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(int(limit))

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [dict(r) for r in rows]

    def stats_by_agent(self, *, since: float | None = None) -> list[dict[str, Any]]:
        """Aggregate usage per agent for Settings/analytics view."""
        clause = "WHERE timestamp >= ?" if since is not None else ""
        params: tuple[Any, ...] = (since,) if since is not None else ()
        query = f"""
            SELECT
                agent,
                COUNT(*)                                              AS total,
                SUM(CASE WHEN status = 'ok'     THEN 1 ELSE 0 END)    AS ok_count,
                SUM(CASE WHEN status = 'denied' THEN 1 ELSE 0 END)    AS denied_count,
                SUM(CASE WHEN status = 'error'  THEN 1 ELSE 0 END)    AS error_count,
                AVG(duration_ms)                                      AS avg_ms
            FROM sandbox_audit
            {clause}
            GROUP BY agent
            ORDER BY total DESC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
