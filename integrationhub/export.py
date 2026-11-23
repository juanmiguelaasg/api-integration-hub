"""Excel report: summary, systems, integrations, run log, sprint backlog and burndown chart."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .engine import Engine
from .scrum import STATUS_LABELS

NAVY = "1C3F6E"
SHEETS = ["Summary", "Systems", "Integrations", "Run log", "Sprint backlog", "Burndown"]
STATUS_FILL = {
    "success": "D1FAE5", "partial": "FEF3C7", "failed": "FFE4E6", "blocked": "E5E7EB",
    "done": "D1FAE5", "in_progress": "DBEAFE", "review": "EDE9FE", "todo": "F3F4F6",
}


def _ts(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value) if value else None


def _table(ws, name: str, headers: list[str], rows: list[list], widths: list[int] | None = None,
           status_col: str | None = None) -> None:
    """Write a header + rows as a real Excel table (filter buttons, banded rows, frozen header)."""
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    last = get_column_letter(len(headers))
    if rows:
        table = Table(displayName=name, ref=f"A1:{last}{len(rows) + 1}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(table)
    for i, header in enumerate(headers, 1):
        width = (widths[i - 1] if widths and i <= len(widths) else None) or max(
            [len(str(header))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None][:200]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, width))
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
    if status_col and rows:
        col = headers.index(status_col) + 1
        letter = get_column_letter(col)
        for status, color in STATUS_FILL.items():
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{len(rows) + 1}",
                FormulaRule(formula=[f'${letter}2="{status}"'], fill=PatternFill("solid", fgColor=color)))


def export_workbook(engine: Engine, path: str | Path | None = None, sheets: list[str] | None = None,
                    check_health: bool = False) -> Path:
    """Write the report and return its path. ``sheets`` limits which sheets are included."""
    sheets = [s for s in SHEETS if not sheets or s in sheets]
    cfg, store, scrum = engine.config, engine.store, engine.scrum
    if path is None:
        cfg.settings.export_dir.mkdir(parents=True, exist_ok=True)
        path = cfg.settings.export_dir / f"integration-hub-report-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if check_health:
        engine.check_all()
    health = store.latest_health()
    totals = store.run_totals()
    runs = store.runs(limit=5000)
    sprint = scrum.current_sprint()

    wb = Workbook()
    wb.remove(wb.active)

    if "Summary" in sheets:
        ws = wb.create_sheet("Summary")
        ws["A1"] = "API Integration Hub – report"
        ws["A1"].font = Font(bold=True, size=16, color=NAVY)
        ws["A2"] = f"Generated {time.strftime('%Y-%m-%d %H:%M')}  ·  config: {cfg.path.name}"
        ws["A2"].font = Font(italic=True, color="666666")
        healthy = sum(1 for s in cfg.systems if health.get(s, {}).get("healthy"))
        day_runs = [r for r in runs if r["started_at"] >= time.time() - 86400]
        ok = sum(r["status"] == "success" for r in day_runs)
        rows = [
            ("Connected systems", len(cfg.systems)),
            ("Healthy at last check", f"{healthy} / {len(cfg.systems)}"),
            ("Integrations", len(cfg.integrations)),
            ("Sync runs (last 24 h)", len(day_runs)),
            ("Successful runs (last 24 h)", f"{ok / len(day_runs) * 100:.0f}%" if day_runs else "–"),
            ("Records created (all time)", sum(t["created"] or 0 for t in totals.values())),
            ("Records updated (all time)", sum(t["updated"] or 0 for t in totals.values())),
        ]
        if sprint:
            p = scrum.progress(sprint["id"])
            rows += [
                ("Current sprint", f"{sprint['name']} ({sprint['status']})"),
                ("Sprint goal", sprint["goal"] or "–"),
                ("Sprint dates", f"{sprint['start_date']} → {sprint['end_date']}"),
                ("Story points done", f"{p['done_points']} / {p['points']} ({p['percent']:.0f}%)"),
            ]
        for i, (label, value) in enumerate(rows, start=4):
            ws.cell(i, 1, label).font = Font(bold=True)
            ws.cell(i, 2, value).alignment = Alignment(horizontal="left")
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 50

        velocity = scrum.velocity()
        if velocity:
            start = len(rows) + 6
            ws.cell(start, 1, "Velocity").font = Font(bold=True, size=12, color=NAVY)
            ws.cell(start + 1, 1, "Sprint").font = Font(bold=True)
            ws.cell(start + 1, 2, "Committed").font = Font(bold=True)
            ws.cell(start + 1, 3, "Completed").font = Font(bold=True)
            for j, v in enumerate(velocity, start=start + 2):
                ws.cell(j, 1, v["sprint"])
                ws.cell(j, 2, v["committed"])
                ws.cell(j, 3, v["completed"])
            chart = BarChart()
            chart.title = "Velocity (story points)"
            chart.height, chart.width = 7, 14
            data = Reference(ws, min_col=2, max_col=3, min_row=start + 1, max_row=start + 1 + len(velocity))
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=start + 2, max_row=start + 1 + len(velocity)))
            ws.add_chart(chart, "E4")

    if "Systems" in sheets:
        ws = wb.create_sheet("Systems")
        rows = []
        for s in cfg.systems.values():
            h = health.get(s.name, {})
            state = "–" if not h else ("healthy" if h["healthy"] else "unhealthy")
            rows.append([s.name, s.base_url, s.auth_type, s.health or "–", state,
                         round(h["latency_ms"]) if h.get("latency_ms") is not None else None,
                         _ts(h.get("checked_at")), s.origin])
        _table(ws, "Systems", ["System", "Base URL", "Auth", "Health path", "Health", "Latency (ms)",
                               "Checked at", "Defined in"], rows, [16, 40, 10, 14, 11, 13, 18, 16])

    if "Integrations" in sheets:
        ws = wb.create_sheet("Integrations")
        rows = []
        for i in cfg.integrations:
            last = store.last_run(i.name)
            t = totals.get(i.name, {})
            rows.append([i.name, i.source_label, i.target_label, i.schedule_minutes or "manual",
                         "yes" if i.enabled else "no", _ts(last and last["started_at"]),
                         last["status"] if last else "never", t.get("runs", 0), t.get("created") or 0,
                         t.get("updated") or 0, t.get("failed") or 0])
        _table(ws, "Integrations", ["Integration", "Source", "Target", "Every (min)", "Enabled", "Last run",
                                    "Last status", "Runs", "Created", "Updated", "Failed"], rows,
               [32, 26, 26, 12, 10, 18, 12, 8, 10, 10, 9], status_col="Last status")

    if "Run log" in sheets:
        ws = wb.create_sheet("Run log")
        rows = [[r["id"], _ts(r["started_at"]), r["integration"], r["trigger"], r["status"], r["fetched"],
                 r["created"], r["updated"], r["unchanged"], r["failed"], round(r["duration_ms"] or 0),
                 r["message"]] for r in runs]
        _table(ws, "RunLog", ["Run", "Started", "Integration", "Trigger", "Status", "Fetched", "Created",
                              "Updated", "Unchanged", "Failed", "Duration (ms)", "Message"], rows,
               [7, 18, 32, 10, 10, 9, 9, 9, 11, 8, 14, 50], status_col="Status")

    if "Sprint backlog" in sheets:
        ws = wb.create_sheet("Sprint backlog")
        names = {s["id"]: s["name"] for s in scrum.sprints()}
        rows = [[s["id"], s["title"], STATUS_LABELS[s["status"]] if s["sprint_id"] else "Backlog",
                 s["points"], names.get(s["sprint_id"], "Product backlog"), s["assignee"] or "", s["source"],
                 _ts(s["created_at"]), _ts(s["done_at"])] for s in scrum.stories()]
        _table(ws, "Backlog", ["ID", "Story", "Status", "Points", "Sprint", "Assignee", "Source", "Created",
                               "Done"], rows, [6, 50, 12, 8, 24, 14, 30, 18, 18])
        label_to_key = {v: k for k, v in STATUS_LABELS.items()}
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
            key = label_to_key.get(row[0].value)
            if key in STATUS_FILL:
                row[0].fill = PatternFill("solid", fgColor=STATUS_FILL[key])

    if "Burndown" in sheets:
        ws = wb.create_sheet("Burndown")
        if sprint:
            points = scrum.burndown(sprint["id"])
            ws["A1"] = f"{sprint['name']} – burndown"
            ws["A1"].font = Font(bold=True, size=14, color=NAVY)
            ws.append([])
            ws.append(["Day", "Remaining", "Ideal"])
            for c in ws[3]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=NAVY)
            for p in points:
                ws.append([p.day.isoformat(), p.remaining, p.ideal])
            ws.column_dimensions["A"].width = 14
            chart = LineChart()
            chart.title = "Sprint burndown (story points)"
            chart.y_axis.title = "Points remaining"
            chart.height, chart.width = 9, 18
            data = Reference(ws, min_col=2, max_col=3, min_row=3, max_row=3 + len(points))
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=4, max_row=3 + len(points)))
            ws.add_chart(chart, "E3")
        else:
            ws["A1"] = "No sprint yet – create one on the Scrum page."

    wb.properties.creator = "API Integration Hub"
    wb.save(path)
    return path
