"""End-to-end sync tests against the demo CRM / ERP / Helpdesk APIs."""
import requests

from integrationhub.config import Settings, System
from integrationhub.connectors import Connector, ConnectorError

CRM_TO_ERP = "CRM customers → ERP partners"
TICKETS = "Helpdesk tickets → Scrum backlog"


def erp_partners(engine):
    return engine.connector("ERP").request("GET", "/api/partners")


def test_first_run_creates_only_active_customers(engine):
    result = engine.run(CRM_TO_ERP)
    assert result.status == "success"
    assert result.counts["fetched"] == 6          # 8 customers, 2 are leads
    assert result.counts["created"] == 6
    partners = erp_partners(engine)
    assert len(partners) == 6
    first = next(p for p in partners if p["external_id"] == "1001")
    assert first["country_code"] == first["country_code"].upper()
    assert first["email"] == first["email"].lower()
    assert first["source_system"] == "CRM"


def test_rerun_sends_nothing_and_creates_no_duplicates(engine):
    engine.run(CRM_TO_ERP)
    again = engine.run(CRM_TO_ERP)
    assert again.counts["unchanged"] == 6
    assert again.counts["created"] == again.counts["updated"] == 0
    assert len(erp_partners(engine)) == 6


def test_changed_and_new_records_are_updated_and_created(engine, demo):
    engine.run(CRM_TO_ERP)
    changed = demo("touch")
    demo("new-customer")
    result = engine.run(CRM_TO_ERP)
    assert result.counts == {"fetched": 7, "created": 1, "updated": 1, "unchanged": 5, "failed": 0}
    partner = next(p for p in erp_partners(engine) if p["external_id"] == str(changed["id"]))
    assert partner["company"].endswith("(updated)")


def test_health_gate_blocks_sync_when_target_is_down(engine, demo):
    demo("outage", system="erp", down="1")
    result = engine.run(CRM_TO_ERP)
    assert result.status == "blocked"
    assert "ERP" in result.message
    assert engine.store.last_run(CRM_TO_ERP)["status"] == "blocked"
    demo("outage", system="erp", down="0")
    assert engine.run(CRM_TO_ERP).counts["created"] == 6


def test_dry_run_maps_but_sends_and_logs_nothing(engine):
    result = engine.run(CRM_TO_ERP, dry_run=True)
    assert len(result.preview) == 6
    assert result.preview[0]["payload"]["source_system"] == "CRM"
    assert erp_partners(engine) == []
    assert engine.store.last_run(CRM_TO_ERP) is None


def test_tickets_become_backlog_stories_once(engine):
    result = engine.run(TICKETS)
    assert result.counts["created"] == 3            # open + critical/high only
    stories = engine.scrum.stories(backlog=True)
    assert {s["points"] for s in stories} == {5, 3}
    assert all(s["source"] == TICKETS for s in stories)
    assert engine.run(TICKETS).counts["unchanged"] == 3
    assert len(engine.scrum.stories()) == 3


def test_health_check_results_are_stored(engine):
    results = engine.check_all()
    assert all(r.healthy for r in results)
    assert set(engine.store.latest_health()) == {"CRM", "ERP", "Helpdesk"}


def test_connector_applies_each_auth_type(mock_url):
    settings = Settings(database=None, export_dir=None, retries=0)
    wrong = System("ERP", f"{mock_url}/erp", auth={"type": "bearer", "token": "nope"})
    try:
        Connector(wrong, settings).request("GET", "/api/partners")
        raise AssertionError("expected 401")
    except ConnectorError as exc:
        assert exc.status == 401
    for system in (
        System("CRM", f"{mock_url}/crm", auth={"type": "api_key", "header": "X-API-Key", "value": "demo-crm-key"}),
        System("Helpdesk", f"{mock_url}/helpdesk", auth={"type": "basic", "username": "hub", "password": "demo"}),
    ):
        path = "/api/customers" if system.name == "CRM" else "/api/tickets"
        assert Connector(system, settings).request("GET", path)


def test_connector_retries_5xx_then_reports_failure(mock_url):
    requests.post(f"{mock_url}/__demo/outage", params={"system": "crm", "down": "1"}, timeout=5)
    settings = Settings(database=None, export_dir=None, retries=2, retry_delay_seconds=0)
    crm = System("CRM", f"{mock_url}/crm", auth={"type": "api_key", "value": "demo-crm-key"})
    try:
        Connector(crm, settings).request("GET", "/api/customers")
        raise AssertionError("expected failure")
    except ConnectorError as exc:
        assert exc.status == 503


def test_due_respects_schedule(engine):
    assert {i.name for i in engine.due()} == {CRM_TO_ERP, TICKETS}
    engine.run(CRM_TO_ERP)
    assert {i.name for i in engine.due()} == {TICKETS}
