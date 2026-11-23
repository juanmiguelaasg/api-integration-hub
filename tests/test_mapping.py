import pytest

from integrationhub.mapping import MappingError, apply_rule, get_path, map_record, matches

RECORD = {
    "id": 7,
    "first_name": "Anna",
    "last_name": "Kovács",
    "email": "  Anna.Kovacs@Example.com ",
    "company": {"name": "Danube Logistics Kft.", "country": "hu"},
    "tags": [{"name": "vip"}],
    "priority": "high",
    "created": "2026-11-20T10:15:00Z",
}


def test_get_path_handles_nesting_lists_and_missing_keys():
    assert get_path(RECORD, "company.name") == "Danube Logistics Kft."
    assert get_path(RECORD, "tags.0.name") == "vip"
    assert get_path(RECORD, "company.city", "n/a") == "n/a"
    assert get_path(RECORD, "tags.5.name") is None


def test_template_and_plain_path():
    assert apply_rule("{first_name} {last_name}", RECORD) == "Anna Kovács"
    assert apply_rule("company.country", RECORD) == "hu"


def test_transform_chain_and_single_transform():
    assert apply_rule({"from": "email", "transform": ["strip", "lower"]}, RECORD) == "anna.kovacs@example.com"
    assert apply_rule({"from": "company.country", "transform": "upper"}, RECORD) == "HU"
    assert apply_rule({"from": "id", "transform": "str"}, RECORD) == "7"
    assert apply_rule({"from": "created", "transform": "date"}, RECORD) == "2026-11-20"


def test_value_map_default_and_const():
    rule = {"from": "priority", "map": {"critical": 5, "high": 3}, "default": 1}
    assert apply_rule(rule, RECORD) == 3
    assert apply_rule(rule, {**RECORD, "priority": "low"}) == 1
    assert apply_rule({"from": "missing", "default": "x"}, RECORD) == "x"
    assert apply_rule({"const": "CRM"}, RECORD) == "CRM"


def test_map_record_builds_nested_target_fields():
    payload = map_record({"name": "{first_name} {last_name}", "address.country": "company.country"}, RECORD)
    assert payload == {"name": "Anna Kovács", "address": {"country": "hu"}}


def test_bad_rules_raise_mapping_error():
    with pytest.raises(MappingError):
        apply_rule({"from": "email", "transform": "shout"}, RECORD)
    with pytest.raises(MappingError):
        apply_rule({"from": "first_name", "transform": "int"}, RECORD)
    with pytest.raises(MappingError):
        apply_rule({"nothing": True}, RECORD)


def test_filter_supports_single_values_and_lists():
    assert matches(RECORD, {"priority": ["critical", "high"], "company.country": "hu"})
    assert not matches(RECORD, {"priority": "critical"})
    assert matches(RECORD, {})
