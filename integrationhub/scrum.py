"""Scrum: product backlog, sprints, a four-column board, burndown and velocity."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .store import Store

STATUSES = ["todo", "in_progress", "review", "done"]
STATUS_LABELS = {"todo": "To do", "in_progress": "In progress", "review": "Review", "done": "Done"}


class ScrumError(ValueError):
    pass


@dataclass
class BurndownPoint:
    day: date
    remaining: float | None   # None for days that have not happened yet
    ideal: float


def _d(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


class Scrum:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------------ sprints
    def create_sprint(self, name: str, start: str | date, end: str | date, goal: str = "") -> int:
        start, end = _d(start), _d(end)
        if end < start:
            raise ScrumError("sprint end date is before its start date")
        with self.store.connect() as db:
            return db.execute("INSERT INTO sprints(name, goal, start_date, end_date) VALUES (?,?,?,?)",
                              (name.strip(), goal.strip(), start.isoformat(), end.isoformat())).lastrowid

    def sprints(self) -> list[dict]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sprints ORDER BY start_date, id")]

    def sprint(self, sprint_id: int) -> dict:
        with self.store.connect() as db:
            r = db.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
        if not r:
            raise ScrumError(f"no sprint with id {sprint_id}")
        return dict(r)

    def active_sprint(self) -> dict | None:
        with self.store.connect() as db:
            r = db.execute("SELECT * FROM sprints WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def current_sprint(self) -> dict | None:
        """The active sprint, else the next planned one, else the most recent closed one."""
        if (s := self.active_sprint()):
            return s
        all_ = self.sprints()
        planned = [s for s in all_ if s["status"] == "planned"]
        return planned[0] if planned else (all_[-1] if all_ else None)

    def start_sprint(self, sprint_id: int) -> None:
        if (active := self.active_sprint()) and active["id"] != sprint_id:
            raise ScrumError(f"close '{active['name']}' before starting another sprint")
        if self.sprint(sprint_id)["status"] == "closed":
            raise ScrumError("a closed sprint cannot be restarted")
        with self.store.connect() as db:
            db.execute("UPDATE sprints SET status = 'active' WHERE id = ?", (sprint_id,))

    def close_sprint(self, sprint_id: int) -> int:
        """Close the sprint; unfinished stories go back to the backlog. Returns how many moved."""
        self.sprint(sprint_id)
        with self.store.connect() as db:
            moved = db.execute("UPDATE stories SET sprint_id = NULL WHERE sprint_id = ? AND status != 'done'",
                               (sprint_id,)).rowcount
            db.execute("UPDATE sprints SET status = 'closed' WHERE id = ?", (sprint_id,))
            return moved

    # ------------------------------------------------------------------ stories
    def add_story(self, title: str, points: int = 1, description: str = "", sprint_id: int | None = None,
                  assignee: str = "", source: str = "manual", external_key: str | None = None) -> int | None:
        """Create a story. Returns None if a story with this source/external_key already exists."""
        title = (title or "").strip()
        if not title:
            raise ScrumError("a story needs a title")
        points = int(points)
        if points < 0:
            raise ScrumError("story points cannot be negative")
        with self.store.connect() as db:
            if external_key is not None:
                exists = db.execute("SELECT id FROM stories WHERE source = ? AND external_key = ?",
                                    (source, str(external_key))).fetchone()
                if exists:
                    return None
            return db.execute(
                "INSERT INTO stories(title, description, points, sprint_id, assignee, source, external_key,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (title, description, points, sprint_id, assignee, source,
                 None if external_key is None else str(external_key), time.time())).lastrowid

    def stories(self, sprint_id: int | None = None, backlog: bool = False) -> list[dict]:
        sql = "SELECT * FROM stories"
        args: tuple = ()
        if backlog:
            sql += " WHERE sprint_id IS NULL"
        elif sprint_id is not None:
            sql += " WHERE sprint_id = ?"
            args = (sprint_id,)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY id", args)]

    def story(self, story_id: int) -> dict:
        with self.store.connect() as db:
            r = db.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        if not r:
            raise ScrumError(f"no story with id {story_id}")
        return dict(r)

    def move_story(self, story_id: int, status: str) -> None:
        if status not in STATUSES:
            raise ScrumError(f"status must be one of {STATUSES}")
        self.story(story_id)
        done_at = time.time() if status == "done" else None
        with self.store.connect() as db:
            db.execute("UPDATE stories SET status = ?, done_at = ? WHERE id = ?", (status, done_at, story_id))

    def step_story(self, story_id: int, direction: int) -> str:
        """Move a story one column left (-1) or right (+1) on the board."""
        current = self.story(story_id)["status"]
        idx = max(0, min(len(STATUSES) - 1, STATUSES.index(current) + direction))
        self.move_story(story_id, STATUSES[idx])
        return STATUSES[idx]

    def plan_story(self, story_id: int, sprint_id: int | None) -> None:
        """Pull a story into a sprint (or push it back to the backlog with None)."""
        self.story(story_id)
        if sprint_id is not None:
            self.sprint(sprint_id)
        with self.store.connect() as db:
            db.execute("UPDATE stories SET sprint_id = ? WHERE id = ?", (sprint_id, story_id))

    def update_story(self, story_id: int, **fields) -> None:
        allowed = {"title", "description", "points", "assignee"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        self.story(story_id)
        with self.store.connect() as db:
            db.execute(f"UPDATE stories SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                       (*fields.values(), story_id))

    def delete_story(self, story_id: int) -> None:
        with self.store.connect() as db:
            db.execute("DELETE FROM stories WHERE id = ?", (story_id,))

    # ------------------------------------------------------------------ metrics
    def board(self, sprint_id: int) -> dict[str, list[dict]]:
        columns: dict[str, list[dict]] = {s: [] for s in STATUSES}
        for story in self.stories(sprint_id):
            columns[story["status"]].append(story)
        return columns

    def progress(self, sprint_id: int) -> dict:
        stories = self.stories(sprint_id)
        total = sum(s["points"] for s in stories)
        done = sum(s["points"] for s in stories if s["status"] == "done")
        return {"stories": len(stories), "done_stories": sum(s["status"] == "done" for s in stories),
                "points": total, "done_points": done, "percent": (done / total * 100) if total else 0.0}

    def burndown(self, sprint_id: int, today: date | None = None) -> list[BurndownPoint]:
        sprint = self.sprint(sprint_id)
        start, end = _d(sprint["start_date"]), _d(sprint["end_date"])
        today = today or date.today()
        stories = self.stories(sprint_id)
        total = sum(s["points"] for s in stories)
        days = (end - start).days
        points: list[BurndownPoint] = []
        for i in range(days + 1):
            day = start + timedelta(days=i)
            ideal = total - total * (i / days) if days else 0.0
            if day > today and sprint["status"] != "closed":
                points.append(BurndownPoint(day, None, round(ideal, 2)))
                continue
            end_of_day = datetime.combine(day, datetime.max.time()).timestamp()
            burned = sum(s["points"] for s in stories
                         if s["status"] == "done" and s["done_at"] and s["done_at"] <= end_of_day)
            points.append(BurndownPoint(day, float(total - burned), round(ideal, 2)))
        return points

    def velocity(self) -> list[dict]:
        """Completed points per closed (or active) sprint."""
        out = []
        for sprint in self.sprints():
            if sprint["status"] == "planned":
                continue
            p = self.progress(sprint["id"])
            out.append({"sprint": sprint["name"], "status": sprint["status"],
                        "committed": p["points"], "completed": p["done_points"]})
        return out
