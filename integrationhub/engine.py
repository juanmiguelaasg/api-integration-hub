"""Sync engine: health gate -> fetch -> filter -> map -> create / update / skip -> log.

Each source record is identified by the integration's ``key``. A hash of the
mapped payload is stored per key, so a rerun only sends what actually changed
and never creates duplicates in the target system.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import HubConfig, Integration
from .connectors import Connector, ConnectorError, HealthResult
from .mapping import MappingError, get_path, map_record, matches
from .scrum import Scrum
from .store import Store


@dataclass
class RunResult:
    integration: str
    status: str                       # success | partial | failed | blocked
    started_at: float
    duration_ms: float = 0.0
    counts: dict = field(default_factory=lambda: dict(fetched=0, created=0, updated=0, unchanged=0, failed=0))
    message: str = ""
    items: list[tuple] = field(default_factory=list)   # (source_key, action, target_id, message)
    preview: list[dict] = field(default_factory=list)  # dry run: mapped payloads
    run_id: int | None = None

    def summary(self) -> str:
        c = self.counts
        if self.status == "blocked":
            return f"blocked – {self.message}"
        return (f"{self.status}: {c['fetched']} fetched, {c['created']} created, {c['updated']} updated, "
                f"{c['unchanged']} unchanged, {c['failed']} failed")


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class Engine:
    def __init__(self, config: HubConfig, store: Store | None = None) -> None:
        self.config = config
        self.store = store or Store(config.settings.database)
        self.scrum = Scrum(self.store)
        self._locks: dict[str, threading.Lock] = {}

    def connector(self, system: str) -> Connector:
        return Connector(self.config.systems[system], self.config.settings)

    # ------------------------------------------------------------------ health
    def check_health(self, system: str) -> HealthResult:
        result = self.connector(system).health()
        self.store.add_health(result.system, result.checked_at, result.healthy, result.status,
                              result.latency_ms, result.message)
        return result

    def check_all(self) -> list[HealthResult]:
        return [self.check_health(name) for name in self.config.systems]

    # ------------------------------------------------------------------ sync
    def run(self, integration: Integration | str, dry_run: bool = False, trigger: str = "manual",
            progress: Callable[[str], None] | None = None) -> RunResult:
        integ = self.config.integration(integration) if isinstance(integration, str) else integration
        lock = self._locks.setdefault(integ.name, threading.Lock())
        if not lock.acquire(blocking=False):
            return RunResult(integ.name, "blocked", time.time(), message="a run is already in progress")
        try:
            result = self._run(integ, dry_run, progress or (lambda _m: None))
        finally:
            lock.release()
        if not dry_run:
            result.run_id = self.store.add_run(integ.name, result.started_at, result.duration_ms, result.status,
                                               trigger, result.counts, result.message, result.items)
        return result

    def _run(self, integ: Integration, dry_run: bool, progress: Callable[[str], None]) -> RunResult:
        result = RunResult(integ.name, "success", time.time())
        t0 = time.perf_counter()

        # 1) Health gate – do not push data into (or read from) a system that is down.
        for system in {integ.source.system, integ.target.system} - {None}:
            progress(f"Checking {system} health…")
            health = self.check_health(system)
            if not health.healthy:
                result.status = "blocked"
                result.message = f"{system} is unhealthy ({health.message}); nothing was sent"
                result.duration_ms = (time.perf_counter() - t0) * 1000
                return result

        # 2) Fetch and filter source records.
        progress(f"Fetching {integ.source_label}…")
        try:
            data = self.connector(integ.source.system).request(integ.source.method, integ.source.path)
        except ConnectorError as exc:
            result.status, result.message = "failed", f"source: {exc}"
            result.duration_ms = (time.perf_counter() - t0) * 1000
            return result
        records = get_path(data, integ.source.items) if integ.source.items else data
        if not isinstance(records, list):
            result.status = "failed"
            result.message = f"source did not return a list at '{integ.source.items or '.'}'"
            result.duration_ms = (time.perf_counter() - t0) * 1000
            return result
        records = [r for r in records if matches(r, integ.source.filter)]
        result.counts["fetched"] = len(records)

        # 3) Map and deliver every record.
        target = None if integ.target.scrum else self.connector(integ.target.system)
        for i, record in enumerate(records, 1):
            key = get_path(record, integ.key)
            if key is None:
                result.counts["failed"] += 1
                result.items.append(("?", "failed", None, f"record has no '{integ.key}'"))
                continue
            key = str(key)
            progress(f"Syncing {i}/{len(records)} (key {key})…")
            try:
                payload = map_record(integ.mapping, record)
            except MappingError as exc:
                result.counts["failed"] += 1
                result.items.append((key, "failed", None, f"mapping: {exc}"))
                continue
            if dry_run:
                result.preview.append({"key": key, "payload": payload})
                continue
            try:
                action, target_id = self._deliver(integ, target, key, payload)
            except (ConnectorError, ValueError) as exc:
                result.counts["failed"] += 1
                result.items.append((key, "failed", None, str(exc)))
                continue
            result.counts[action] += 1
            result.items.append((key, action, target_id, ""))

        c = result.counts
        if c["failed"]:
            result.status = "failed" if c["failed"] == len(records) else "partial"
        result.message = "dry run – nothing was sent" if dry_run else ""
        result.duration_ms = (time.perf_counter() - t0) * 1000
        return result

    def _deliver(self, integ: Integration, target: Connector | None, key: str, payload: dict):
        digest = payload_hash(payload)
        state = self.store.get_state(integ.name, key)
        if state and state["payload_sha"] == digest:
            return "unchanged", state["target_id"]

        if integ.target.scrum == "backlog":
            if state:   # the story already exists – Scrum owns it now, do not overwrite the team's edits
                self.store.set_state(integ.name, key, state["target_id"], digest)
                return "unchanged", state["target_id"]
            story_id = self.scrum.add_story(
                title=str(payload.get("title") or f"{integ.name} #{key}"),
                points=int(payload.get("points") or payload.get("story_points") or 1),
                description=str(payload.get("description") or ""),
                assignee=str(payload.get("assignee") or ""),
                source=integ.name, external_key=key)
            action = "created" if story_id else "unchanged"
            self.store.set_state(integ.name, key, None if story_id is None else str(story_id), digest)
            return action, None if story_id is None else str(story_id)

        assert target is not None
        ep = integ.target
        if state and state["target_id"] and ep.update_path:
            path = ep.update_path.replace("{target_id}", str(state["target_id"])).replace("{key}", key)
            target.request(ep.update_method or "PUT", path, json=payload)
            self.store.set_state(integ.name, key, state["target_id"], digest)
            return "updated", state["target_id"]
        response = target.request(ep.method if ep.method != "GET" else "POST", ep.path, json=payload)
        target_id = get_path(response, ep.id_field) if isinstance(response, (dict, list)) else None
        self.store.set_state(integ.name, key, None if target_id is None else str(target_id), digest)
        return ("updated" if state else "created"), None if target_id is None else str(target_id)

    # ------------------------------------------------------------------ scheduling
    def due(self, now: float | None = None) -> list[Integration]:
        """Enabled integrations whose schedule has elapsed since their last run."""
        now = now or time.time()
        out = []
        for integ in self.config.integrations:
            if not integ.enabled or not integ.schedule_minutes:
                continue
            last = self.store.last_run(integ.name)
            if last is None or now - last["started_at"] >= integ.schedule_minutes * 60:
                out.append(integ)
        return out
