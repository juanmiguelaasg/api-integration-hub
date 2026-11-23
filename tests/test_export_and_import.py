from openpyxl import load_workbook

from integrationhub.config import load_config, save_imported_systems, systems_from_healthchecker
from integrationhub.demo import seed_demo
from integrationhub.export import SHEETS, export_workbook

HEALTHCHECKER_YAML = """
endpoints:
  - name: Health
    url: http://127.0.0.1:8000/health
  - name: List users
    url: http://127.0.0.1:8000/api/users
    headers:
      Authorization: Bearer ${API_TOKEN:-demo-token}
  - name: Payments
    url: https://payments.example.com/v1/status
"""


def test_excel_report_has_every_sheet_with_data(engine, tmp_path):
    seed_demo(engine.scrum)
    engine.run("CRM customers → ERP partners")
    engine.run("Helpdesk tickets → Scrum backlog")
    path = export_workbook(engine, tmp_path / "report.xlsx", check_health=True)

    wb = load_workbook(path)
    assert wb.sheetnames == SHEETS
    assert wb["Summary"]["A1"].value.startswith("API Integration Hub")
    assert wb["Systems"].max_row == 4                      # header + CRM, ERP, Helpdesk
    assert wb["Systems"]["E2"].value == "healthy"
    run_log = wb["Run log"]
    assert run_log.max_row == 3
    assert {run_log.cell(r, 5).value for r in (2, 3)} == {"success"}
    backlog = wb["Sprint backlog"]
    titles = [backlog.cell(r, 2).value for r in range(2, backlog.max_row + 1)]
    assert any(t.startswith("Ticket #501") for t in titles)
    assert wb["Burndown"]._charts and wb["Summary"]._charts
    assert len(wb["Integrations"].tables) == 1


def test_excel_report_can_be_limited_to_some_sheets(engine, tmp_path):
    path = export_workbook(engine, tmp_path / "small.xlsx", sheets=["Run log", "Burndown"])
    assert load_workbook(path).sheetnames == ["Run log", "Burndown"]


def test_import_from_api_health_checker(tmp_path, engine):
    src = tmp_path / "endpoints.yaml"
    src.write_text(HEALTHCHECKER_YAML, encoding="utf-8")
    systems = {s.name: s for s in systems_from_healthchecker(src)}
    assert set(systems) == {"127.0.0.1:8000", "payments.example.com"}
    local = systems["127.0.0.1:8000"]
    assert local.health == "/health"
    assert local.auth == {"type": "bearer", "token": "demo-token"}
    assert systems["payments.example.com"].health is None

    save_imported_systems(engine.config.settings, list(systems.values()))
    reloaded = load_config(engine.config.path)
    assert reloaded.systems["127.0.0.1:8000"].origin == "health-checker"
    assert "CRM" in reloaded.systems
