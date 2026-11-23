"""Demo data: a closed sprint and an active one, so the board, burndown and velocity have content."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .scrum import Scrum

SPRINT_1 = [  # (title, points, assignee, done_on_day)
    ("Document CRM and ERP API contracts", 2, "Zénó", 1),
    ("Connector with API key / Bearer / Basic auth", 3, "Zénó", 3),
    ("Health gate before every sync", 3, "Zénó", 5),
    ("Field mapping with transforms", 5, "Zénó", 8),
    ("Retry on 5xx and connection errors", 2, "Zénó", None),
]
SPRINT_2 = [  # (title, points, assignee, status, done_on_day)
    ("Sync CRM customers to ERP partners", 5, "Zénó", "done", 1),
    ("Skip unchanged records (payload hash)", 3, "Zénó", "done", 3),
    ("Scrum board in the desktop app", 5, "Zénó", "review", None),
    ("Excel export: run log and burndown", 3, "Zénó", "in_progress", None),
    ("Helpdesk tickets to backlog", 3, "", "todo", None),
    ("Scheduled syncs in the background", 2, "", "todo", None),
]
BACKLOG = [
    ("Import systems from API Health-Checker", 2),
    ("OAuth2 client-credentials auth", 5),
    ("Webhook trigger instead of polling", 8),
]


def _at(day: date) -> float:
    return datetime.combine(day, datetime.min.time()).replace(hour=15).timestamp()


def seed_demo(scrum: Scrum, today: date | None = None) -> bool:
    """Create demo sprints and stories. Does nothing (returns False) if sprints already exist."""
    if scrum.sprints():
        return False
    today = today or date.today()
    s2_start = today - timedelta(days=4)
    s1_start = s2_start - timedelta(days=14)

    s1 = scrum.create_sprint("Sprint 1 – Connectors", s1_start, s1_start + timedelta(days=13),
                             goal="Talk to CRM, ERP and Helpdesk safely")
    scrum.start_sprint(s1)
    for title, points, who, done_day in SPRINT_1:
        sid = scrum.add_story(title, points, sprint_id=s1, assignee=who)
        if done_day is not None:
            scrum.move_story(sid, "done")
            _set_done(scrum, sid, _at(s1_start + timedelta(days=done_day)))
    scrum.close_sprint(s1)

    s2 = scrum.create_sprint("Sprint 2 – CRM ↔ ERP sync", s2_start, s2_start + timedelta(days=13),
                             goal="Customers flow from CRM to ERP without duplicates; work is reported in Excel")
    scrum.start_sprint(s2)
    for title, points, who, status, done_day in SPRINT_2:
        sid = scrum.add_story(title, points, sprint_id=s2, assignee=who)
        scrum.move_story(sid, status)
        if done_day is not None:
            _set_done(scrum, sid, _at(s2_start + timedelta(days=done_day)))
    for title, points in BACKLOG:
        scrum.add_story(title, points)
    return True


def _set_done(scrum: Scrum, story_id: int, ts: float) -> None:
    with scrum.store.connect() as db:
        db.execute("UPDATE stories SET done_at = ? WHERE id = ?", (ts, story_id))
