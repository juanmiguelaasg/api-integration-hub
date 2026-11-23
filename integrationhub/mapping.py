"""Field mapping: turn a source record into the payload the target system expects.

A mapping is a dict of target_field -> rule. A rule can be:

* ``"company.name"``           – dotted path into the source record
* ``"{first_name} {last_name}"`` – template; every {path} is looked up
* ``{"from": "email", "transform": "lower"}``  – path plus transforms (a name or a list)
* ``{"from": "priority", "map": {"high": 3}, "default": 1}`` – value lookup table
* ``{"const": "crm"}``         – fixed value
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_TEMPLATE = re.compile(r"\{([^{}]+)\}")
_MISSING = object()


class MappingError(ValueError):
    pass


def get_path(record: Any, path: str, default: Any = None) -> Any:
    """Look up 'a.b.0.c' in nested dicts/lists. Returns default when any step is missing."""
    if path in ("", "."):
        return record
    cur = record
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def _to_date(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError as exc:
        raise MappingError(f"not a date: {value!r}") from exc


TRANSFORMS = {
    "lower": lambda v: str(v).lower(),
    "upper": lambda v: str(v).upper(),
    "strip": lambda v: str(v).strip(),
    "title": lambda v: str(v).title(),
    "str": str,
    "int": lambda v: int(float(v)),
    "float": float,
    "bool": lambda v: v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "y"},
    "date": _to_date,
}


def render_template(template: str, record: Any) -> str:
    def repl(m: re.Match) -> str:
        value = get_path(record, m.group(1).strip(), "")
        return "" if value is None else str(value)
    return _TEMPLATE.sub(repl, template).strip()


def apply_rule(rule: Any, record: Any) -> Any:
    if isinstance(rule, str):
        return render_template(rule, record) if "{" in rule else get_path(record, rule)
    if isinstance(rule, dict):
        if "const" in rule:
            return rule["const"]
        if "template" in rule:
            value = render_template(rule["template"], record)
        elif "from" in rule:
            value = get_path(record, rule["from"], _MISSING)
        else:
            raise MappingError(f"rule needs 'from', 'template' or 'const': {rule!r}")
        if value is _MISSING or value is None or value == "":
            return rule.get("default")
        if "map" in rule:
            value = rule["map"].get(value, rule["map"].get(str(value), rule.get("default", value)))
        transforms = rule.get("transform") or []
        for name in [transforms] if isinstance(transforms, str) else transforms:
            if name not in TRANSFORMS:
                raise MappingError(f"unknown transform {name!r} (use one of {', '.join(TRANSFORMS)})")
            try:
                value = TRANSFORMS[name](value)
            except (TypeError, ValueError) as exc:
                raise MappingError(f"transform {name!r} failed on {value!r}") from exc
        return value
    if isinstance(rule, (int, float, bool)) or rule is None:
        return rule
    raise MappingError(f"unsupported mapping rule: {rule!r}")


def map_record(mapping: dict, record: Any) -> dict:
    """Build the target payload. Nested target fields can be written as 'address.city'."""
    out: dict = {}
    for target_field, rule in mapping.items():
        value = apply_rule(rule, record)
        node = out
        *parents, leaf = str(target_field).split(".")
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = value
    return out


def matches(record: Any, conditions: dict) -> bool:
    """Source filter: every field must equal the value (or be one of a list of values)."""
    for path, expected in (conditions or {}).items():
        actual = get_path(record, path)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
