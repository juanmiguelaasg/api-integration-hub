"""Command line: run syncs, check systems, manage sprints and export to Excel without the GUI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config, save_imported_systems, systems_from_healthchecker
from .engine import Engine
from .scrum import STATUS_LABELS, ScrumError

DEFAULT_CONFIG = "hub.yaml"


def _engine(args) -> Engine:
    return Engine(load_config(args.config))


def cmd_check(args) -> int:
    engine = _engine(args)
    bad = 0
    for h in engine.check_all():
        bad += not h.healthy
        latency = f"{h.latency_ms:.0f} ms" if h.latency_ms is not None else "–"
        print(f"{'OK  ' if h.healthy else 'DOWN'}  {h.system:<14} {latency:>8}  {h.message}")
    return 1 if bad else 0


def cmd_run(args) -> int:
    engine = _engine(args)
    targets = engine.config.integrations if args.all or not args.name else [engine.config.integration(args.name)]
    worst = 0
    for integ in targets:
        result = engine.run(integ, dry_run=args.dry_run, trigger="cli")
        print(f"[{integ.name}] {result.summary()}  ({result.duration_ms:.0f} ms)")
        if args.dry_run:
            for item in result.preview[: args.preview]:
                print("   ", item["key"], json.dumps(item["payload"], ensure_ascii=False))
        for key, action, _tid, msg in result.items:
            if action == "failed":
                print(f"    ! {key}: {msg}")
        worst = max(worst, {"success": 0, "partial": 1, "blocked": 2, "failed": 2}[result.status])
    return worst


def cmd_export(args) -> int:
    from .export import export_workbook
    path = export_workbook(_engine(args), args.output, check_health=args.check)
    print(f"Excel report written to {path}")
    return 0


def cmd_sprint(args) -> int:
    engine = _engine(args)
    scrum = engine.scrum
    if args.action == "new":
        sid = scrum.create_sprint(args.name, args.start, args.end, args.goal or "")
        print(f"Created sprint #{sid}")
    elif args.action == "start":
        scrum.start_sprint(args.id)
        print(f"Sprint #{args.id} is active")
    elif args.action == "close":
        moved = scrum.close_sprint(args.id)
        print(f"Sprint #{args.id} closed, {moved} unfinished stories moved back to the backlog")
    else:
        sprint = scrum.current_sprint()
        if not sprint:
            print("No sprints yet. Try:  python -m integrationhub demo-seed")
            return 0
        p = scrum.progress(sprint["id"])
        print(f"{sprint['name']}  [{sprint['status']}]  {sprint['start_date']} → {sprint['end_date']}")
        print(f"Goal: {sprint['goal'] or '–'}")
        print(f"Done: {p['done_points']}/{p['points']} points ({p['percent']:.0f}%)\n")
        for status, stories in scrum.board(sprint["id"]).items():
            print(f"{STATUS_LABELS[status]} ({sum(s['points'] for s in stories)} pts)")
            for s in stories:
                print(f"   #{s['id']:<4} {s['points']:>2} pts  {s['title']}")
        backlog = scrum.stories(backlog=True)
        print(f"\nProduct backlog: {len(backlog)} stories, {sum(s['points'] for s in backlog)} pts")
    return 0


def cmd_story(args) -> int:
    scrum = _engine(args).scrum
    if args.action == "add":
        sid = scrum.add_story(args.title, args.points, sprint_id=args.sprint, assignee=args.assignee or "")
        print(f"Created story #{sid}")
    else:
        scrum.move_story(args.id, args.status)
        print(f"Story #{args.id} → {STATUS_LABELS[args.status]}")
    return 0


def cmd_import(args) -> int:
    cfg = load_config(args.config)
    systems = systems_from_healthchecker(args.endpoints)
    path = save_imported_systems(cfg.settings, systems)
    for s in systems:
        print(f"Imported {s.name:<20} {s.base_url}  health={s.health or '–'}  auth={s.auth_type}")
    print(f"Saved to {path}")
    return 0


def cmd_seed(args) -> int:
    from .demo import seed_demo
    created = seed_demo(_engine(args).scrum)
    print("Demo sprints and stories created." if created else "Sprints already exist – nothing changed.")
    return 0


def cmd_demo_api(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mock_systems import make_server
    server = make_server(args.port)
    print(f"Demo systems on http://127.0.0.1:{args.port}  (crm, erp, helpdesk) – Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_gui(args) -> int:
    from .ui.app import run_app
    return run_app(args.config, demo=args.demo)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="integrationhub", description="API Integration Hub")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="path to hub.yaml (default: %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gui", help="open the desktop app")
    g.add_argument("--demo", action="store_true", help="start the demo systems and seed demo sprints")
    g.set_defaults(func=cmd_gui)

    sub.add_parser("check", help="health-check every connected system").set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="run one integration (or --all)")
    r.add_argument("name", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--dry-run", action="store_true", help="map records and show payloads, send nothing")
    r.add_argument("--preview", type=int, default=5, help="payloads to print in a dry run")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("export", help="write the Excel report")
    e.add_argument("-o", "--output")
    e.add_argument("--check", action="store_true", help="health-check systems first")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("sprint", help="show or manage sprints")
    s.add_argument("action", nargs="?", default="status", choices=["status", "new", "start", "close"])
    s.add_argument("--name")
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--goal")
    s.add_argument("--id", type=int)
    s.set_defaults(func=cmd_sprint)

    st = sub.add_parser("story", help="add a story or move it on the board")
    st.add_argument("action", choices=["add", "move"])
    st.add_argument("--title")
    st.add_argument("--points", type=int, default=1)
    st.add_argument("--sprint", type=int)
    st.add_argument("--assignee")
    st.add_argument("--id", type=int)
    st.add_argument("--status", choices=list(STATUS_LABELS))
    st.set_defaults(func=cmd_story)

    i = sub.add_parser("import-healthchecker", help="import systems from an API Health-Checker endpoints.yaml")
    i.add_argument("endpoints")
    i.set_defaults(func=cmd_import)

    sub.add_parser("demo-seed", help="create demo sprints and stories").set_defaults(func=cmd_seed)

    d = sub.add_parser("demo-api", help="run the demo CRM / ERP / Helpdesk APIs")
    d.add_argument("--port", type=int, default=8100)
    d.set_defaults(func=cmd_demo_api)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # integration names contain "→"; never crash on a cp1252 pipe
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ScrumError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
