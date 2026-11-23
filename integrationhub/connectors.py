"""HTTP connector for one connected system: auth, retries and health checks."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings, System


class ConnectorError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class HealthResult:
    system: str
    healthy: bool
    status: int | None
    latency_ms: float | None
    message: str
    checked_at: float


class Connector:
    def __init__(self, system: System, settings: Settings, session: requests.Session | None = None) -> None:
        self.system = system
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "api-integration-hub"})
        self.session.headers.update(system.headers)
        self._apply_auth()

    def _apply_auth(self) -> None:
        a = self.system.auth
        kind = a.get("type", "none")
        if kind == "bearer":
            self.session.headers["Authorization"] = f"Bearer {a.get('token', '')}"
        elif kind == "api_key":
            self.session.headers[a.get("header", "X-API-Key")] = str(a.get("value", ""))
        elif kind == "basic":
            self.session.auth = (str(a.get("username", "")), str(a.get("password", "")))

    def url(self, path: str) -> str:
        return self.system.base_url + ("" if not path else path if path.startswith("/") else "/" + path)

    def request(self, method: str, path: str, json: Any = None) -> Any:
        """Send a request, retrying on connection errors and 5xx. Returns parsed JSON (or None)."""
        last: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                r = self.session.request(method, self.url(path), json=json, timeout=self.settings.timeout_seconds)
            except requests.RequestException as exc:
                last = ConnectorError(f"{self.system.name}: {exc.__class__.__name__}")
            else:
                if r.status_code < 400:
                    if not r.content:
                        return None
                    try:
                        return r.json()
                    except ValueError as exc:
                        raise ConnectorError(f"{self.system.name}: response is not JSON", r.status_code) from exc
                last = ConnectorError(f"{self.system.name}: HTTP {r.status_code} on {method} {path}", r.status_code)
                if r.status_code < 500:
                    raise last           # client errors will not fix themselves
            if attempt < self.settings.retries:
                time.sleep(self.settings.retry_delay_seconds)
        assert last is not None
        raise last

    def health(self) -> HealthResult:
        now = time.time()
        if not self.system.health:
            return HealthResult(self.system.name, True, None, None, "no health endpoint configured", now)
        start = time.perf_counter()
        try:
            r = self.session.get(self.url(self.system.health), timeout=self.settings.timeout_seconds)
        except requests.RequestException as exc:
            return HealthResult(self.system.name, False, None, None, f"unreachable ({exc.__class__.__name__})", now)
        ms = (time.perf_counter() - start) * 1000
        ok = 200 <= r.status_code < 300
        return HealthResult(self.system.name, ok, r.status_code, ms, "ok" if ok else f"HTTP {r.status_code}", now)
