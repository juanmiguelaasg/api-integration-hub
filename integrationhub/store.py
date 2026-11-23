"""SQLite persistence: sync runs, sync state, health checks, sprints and stories.

Every call opens its own short-lived connection, so the store can be used
from the UI thread and from background sync threads at the same time.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    integration TEXT NOT NULL,
    started_at  REAL NOT NULL,
    duration_ms REAL,
    status      TEXT NOT NULL,          -- success | partial | failed | blocked
    trigger     TEXT NOT NULL DEFAULT 'manual',
    fetched     INTEGER DEFAULT 0,
    created     INTEGER DEFAULT 0,
    updated     INTEGER DEFAULT 0,
    unchanged   INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    message     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_by_integration ON runs(integration, started_at);

CREATE TABLE IF NOT EXISTS run_items (
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    action     TEXT NOT NULL,           -- created | updated | unchanged | failed
    target_id  TEXT,
    message    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_state (
    integration TEXT NOT NULL,
    source_key  TEXT NOT NULL,
    target_id   TEXT,
    payload_sha TEXT NOT NULL,
    synced_at   REAL NOT NULL,
    PRIMARY KEY (integration, source_key)
);

CREATE TABLE IF NOT EXISTS health_checks (
    system     TEXT NOT NULL,
    checked_at REAL NOT NULL,
    healthy    INTEGER NOT NULL,
    status     INTEGER,
    latency_ms REAL,
    message    TEXT
);
CREATE INDEX IF NOT EXISTS health_by_system ON health_checks(system, checked_at);

CREATE TABLE IF NOT EXISTS sprints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    goal       TEXT DEFAULT '',
    start_date TEXT NOT NULL,           -- YYYY-MM-DD
    end_date   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'planned'   -- planned | active | closed
);

CREATE TABLE IF NOT EXISTS stories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    points       INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'todo',   -- todo | in_progress | review | done
    sprint_id    INTEGER REFERENCES sprints(id), -- NULL = product backlog
    assignee     TEXT DEFAULT '',
    source       TEXT DEFAULT 'manual',          -- 'manual' or the integration that created it
    external_key TEXT,
    created_at   REAL NOT NULL,
    done_at      REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS stories_external ON stories(source, external_key)
    WHERE external_key IS NOT NULL;
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ runs
    def add_run(self, integration: str, started_at: float, duration_ms: float, status: str, trigger: str,
                counts: dict, message: str, items: list[tuple]) -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO runs(integration, started_at, duration_ms, status, trigger, fetched, created, updated,"
                " unchanged, failed, message) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (integration, started_at, duration_ms, status, trigger, counts.get("fetched", 0),
                 counts.get("created", 0), counts.get("updated", 0), counts.get("unchanged", 0),
                 counts.get("failed", 0), message))
            run_id = cur.lastrowid
            db.executemany("INSERT INTO run_items(run_id, source_key, action, target_id, message) VALUES (?,?,?,?,?)",
                           [(run_id, *item) for item in items])
            return run_id

    def runs(self, integration: str | None = None, limit: int = 200, since: float | None = None) -> list[dict]:
        sql, args = "SELECT * FROM runs WHERE 1=1", []
        if integration:
            sql += " AND integration = ?"
            args.append(integration)
        if since:
            sql += " AND started_at >= ?"
            args.append(since)
        sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def run_items(self, run_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM run_items WHERE run_id = ? ORDER BY rowid", (run_id,))]

    def last_run(self, integration: str) -> dict | None:
        rows = self.runs(integration, limit=1)
        return rows[0] if rows else None

    def run_totals(self) -> dict[str, dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT integration, COUNT(*) AS runs, SUM(created) AS created, SUM(updated) AS updated,"
                " SUM(unchanged) AS unchanged, SUM(failed) AS failed,"
                " SUM(status = 'success') AS ok_runs FROM runs GROUP BY integration")
            return {r["integration"]: dict(r) for r in rows}

    # ------------------------------------------------------------------ sync state
    def get_state(self, integration: str, source_key: str) -> dict | None:
        with self.connect() as db:
            r = db.execute("SELECT * FROM sync_state WHERE integration = ? AND source_key = ?",
                           (integration, source_key)).fetchone()
            return dict(r) if r else None

    def set_state(self, integration: str, source_key: str, target_id: str | None, payload_sha: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO sync_state(integration, source_key, target_id, payload_sha, synced_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT(integration, source_key) DO UPDATE SET"
                " target_id = excluded.target_id, payload_sha = excluded.payload_sha, synced_at = excluded.synced_at",
                (integration, source_key, target_id, payload_sha, time.time()))

    def reset_state(self, integration: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sync_state WHERE integration = ?", (integration,))

    # ------------------------------------------------------------------ health
    def add_health(self, system: str, checked_at: float, healthy: bool, status: int | None,
                   latency_ms: float | None, message: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO health_checks VALUES (?,?,?,?,?,?)",
                       (system, checked_at, int(healthy), status, latency_ms, message))

    def latest_health(self) -> dict[str, dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT h.* FROM health_checks h JOIN (SELECT system, MAX(checked_at) AS t FROM health_checks"
                " GROUP BY system) m ON h.system = m.system AND h.checked_at = m.t")
            return {r["system"]: dict(r) for r in rows}
