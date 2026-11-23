"""Load hub.yaml: settings, connected systems and integrations.

Values may reference environment variables with ${VAR} or ${VAR:-default},
so tokens and URLs never have to be committed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
AUTH_TYPES = {"none", "api_key", "bearer", "basic"}


class ConfigError(ValueError):
    """Raised when hub.yaml is missing something or contradicts itself."""


def expand_env(value: Any) -> Any:
    """Recursively replace ${VAR} / ${VAR:-default} in strings."""
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


@dataclass
class Settings:
    database: Path
    export_dir: Path
    timeout_seconds: float = 10
    retries: int = 2
    retry_delay_seconds: float = 0.5
    scheduler_tick_seconds: int = 30


@dataclass
class System:
    name: str
    base_url: str
    health: str | None = "/health"
    auth: dict = field(default_factory=lambda: {"type": "none"})
    headers: dict = field(default_factory=dict)
    description: str = ""
    origin: str = "hub.yaml"        # or "health-checker" when imported

    @property
    def auth_type(self) -> str:
        return self.auth.get("type", "none")


@dataclass
class Endpoint:
    system: str | None = None       # None when the target is the Scrum backlog
    path: str = ""
    method: str = "GET"
    items: str = ""                 # dotted path to the list inside the response ("" = response is the list)
    filter: dict = field(default_factory=dict)
    update_method: str | None = None
    update_path: str | None = None  # may contain {target_id}
    id_field: str = "id"            # where the target returns the created record's id
    scrum: str | None = None        # "backlog" -> create Scrum stories instead of calling an API


@dataclass
class Integration:
    name: str
    source: Endpoint
    target: Endpoint
    key: str = "id"
    mapping: dict = field(default_factory=dict)
    schedule_minutes: float | None = None
    enabled: bool = True
    description: str = ""

    @property
    def target_label(self) -> str:
        return "Scrum backlog" if self.target.scrum else f"{self.target.system} {self.target.path}"

    @property
    def source_label(self) -> str:
        return f"{self.source.system} {self.source.path}"


@dataclass
class HubConfig:
    path: Path
    settings: Settings
    systems: dict[str, System]
    integrations: list[Integration]

    def integration(self, name: str) -> Integration:
        for i in self.integrations:
            if i.name == name:
                return i
        raise KeyError(f"no integration named {name!r}")


# ---------------------------------------------------------------------------
def _endpoint(raw: dict, where: str) -> Endpoint:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping")
    ep = Endpoint(
        system=raw.get("system"),
        path=raw.get("path", ""),
        method=str(raw.get("method", "GET")).upper(),
        items=raw.get("items", "") or "",
        filter=raw.get("filter") or {},
        update_method=(str(raw["update_method"]).upper() if raw.get("update_method") else None),
        update_path=raw.get("update_path"),
        id_field=raw.get("id_field", "id"),
        scrum=raw.get("scrum"),
    )
    if ep.scrum is None and not ep.system:
        raise ConfigError(f"{where}: needs either 'system' or 'scrum: backlog'")
    if ep.scrum not in (None, "backlog"):
        raise ConfigError(f"{where}: only 'scrum: backlog' is supported")
    return ep


def _system(raw: dict, origin: str = "hub.yaml") -> System:
    if not raw.get("name") or not raw.get("base_url"):
        raise ConfigError("every system needs 'name' and 'base_url'")
    auth = raw.get("auth") or {"type": "none"}
    if auth.get("type", "none") not in AUTH_TYPES:
        raise ConfigError(f"system {raw['name']}: auth type must be one of {sorted(AUTH_TYPES)}")
    return System(
        name=raw["name"],
        base_url=str(raw["base_url"]).rstrip("/"),
        health=raw.get("health", "/health"),
        auth=auth,
        headers=raw.get("headers") or {},
        description=raw.get("description", ""),
        origin=origin,
    )


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into os.environ (real environment variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: str | Path) -> HubConfig:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    load_dotenv(path.parent / ".env")
    raw = expand_env(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    root = path.parent
    s = raw.get("settings") or {}
    settings = Settings(
        database=root / s.get("database", "data/hub.db"),
        export_dir=root / s.get("export_dir", "exports"),
        timeout_seconds=float(s.get("timeout_seconds", 10)),
        retries=int(s.get("retries", 2)),
        retry_delay_seconds=float(s.get("retry_delay_seconds", 0.5)),
        scheduler_tick_seconds=int(s.get("scheduler_tick_seconds", 30)),
    )

    systems: dict[str, System] = {}
    for item in raw.get("systems") or []:
        sys_ = _system(item)
        systems[sys_.name] = sys_
    # Systems imported from the API Health-Checker live next to the database.
    for sys_ in load_imported_systems(imported_systems_file(settings)):
        systems.setdefault(sys_.name, sys_)

    integrations: list[Integration] = []
    for item in raw.get("integrations") or []:
        name = item.get("name")
        if not name:
            raise ConfigError("every integration needs a 'name'")
        integ = Integration(
            name=name,
            source=_endpoint(item.get("source"), f"{name}.source"),
            target=_endpoint(item.get("target"), f"{name}.target"),
            key=item.get("key", "id"),
            mapping=item.get("mapping") or {},
            schedule_minutes=item.get("schedule_minutes"),
            enabled=bool(item.get("enabled", True)),
            description=item.get("description", ""),
        )
        for ep, label in ((integ.source, "source"), (integ.target, "target")):
            if ep.system and ep.system not in systems:
                raise ConfigError(f"{name}.{label}: unknown system {ep.system!r}")
        if integ.source.scrum:
            raise ConfigError(f"{name}: the Scrum backlog can only be a target")
        if not integ.mapping:
            raise ConfigError(f"{name}: 'mapping' must not be empty")
        integrations.append(integ)

    return HubConfig(path=path, settings=settings, systems=systems, integrations=integrations)


# --------------------------------------------------------------------------- health-checker import
def imported_systems_file(settings: Settings) -> Path:
    return settings.database.parent / "imported_systems.yaml"


def load_imported_systems(path: Path) -> list[System]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [_system(item, origin="health-checker") for item in data]


def systems_from_healthchecker(endpoints_yaml: str | Path) -> list[System]:
    """Turn an API Health-Checker endpoints.yaml into connectable systems.

    Endpoints are grouped by host; an endpoint whose path ends in /health
    becomes that system's health check, and Authorization headers are kept.
    """
    raw = expand_env(yaml.safe_load(Path(endpoints_yaml).read_text(encoding="utf-8")) or {})
    grouped: dict[str, System] = {}
    for ep in raw.get("endpoints") or []:
        url = ep.get("url")
        if not url:
            continue
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        sys_ = grouped.get(base)
        if sys_ is None:
            sys_ = System(name=parts.hostname or base, base_url=base, health=None, origin="health-checker",
                          description=f"Imported from {Path(endpoints_yaml).name}")
            grouped[base] = sys_
        if parts.path.rstrip("/").endswith("/health") and sys_.health is None:
            sys_.health = parts.path
        auth = (ep.get("headers") or {}).get("Authorization", "")
        if auth.lower().startswith("bearer ") and sys_.auth_type == "none":
            sys_.auth = {"type": "bearer", "token": auth[7:].strip()}
    names = {}
    for sys_ in grouped.values():               # make host:port names unique and readable
        port = urlsplit(sys_.base_url).port
        label = sys_.name if not port else f"{sys_.name}:{port}"
        names[label] = sys_
        sys_.name = label
    return list(names.values())


def save_imported_systems(settings: Settings, systems: list[System]) -> Path:
    path = imported_systems_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {s.name: s for s in load_imported_systems(path)}
    for s in systems:
        existing[s.name] = s
    data = [{"name": s.name, "base_url": s.base_url, "health": s.health, "auth": s.auth,
             "description": s.description} for s in existing.values()]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
