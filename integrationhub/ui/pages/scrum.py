from __future__ import annotations

from datetime import date, timedelta

import customtkinter as ctk

from ...scrum import STATUS_LABELS, STATUSES, ScrumError
from .. import theme as t
from .. import widgets as w
from .base import Page

COLUMNS = [("backlog", "Product backlog")] + [(s, STATUS_LABELS[s]) for s in STATUSES]


class ScrumPage(Page):
    title = "Scrum board"
    subtitle = "Plan the integration work: backlog, sprints, board and burndown."

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        self.sprint_id: int | None = None
        w.ghost_button(self.actions, "New sprint", self._new_sprint, width=110).pack(side="left", padx=6)
        w.accent_button(self.actions, "New story", self._new_story, width=110).pack(side="left")

        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=1)

        # --- sprint header: selector, status, goal, progress, burndown
        head = ctk.CTkFrame(self.body, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        head.grid_columnconfigure(0, weight=3)
        head.grid_columnconfigure(1, weight=2)
        info = ctk.CTkFrame(head, fg_color="transparent")
        info.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x")
        self.sprint_menu = ctk.CTkOptionMenu(row, values=["–"], command=self._pick_sprint, width=w.px(260),
                                             fg_color=t.SURFACE, button_color=t.SURFACE,
                                             button_hover_color=t.CARD_HOVER, font=w.FONTS.body_bold,
                                             dropdown_font=w.FONTS.body)
        self.sprint_menu.pack(side="left")
        self.status_pill = w.pill(row, "–", t.DIM)
        self.status_pill.pack(side="left", padx=10)
        self.start_btn = w.ghost_button(row, "Start sprint", self._start, width=110)
        self.close_btn = w.ghost_button(row, "Close sprint", self._close, width=110)
        self.dates = ctk.CTkLabel(info, text="", font=w.FONTS.small, text_color=t.MUTED, anchor="w")
        self.dates.pack(fill="x", pady=(8, 0))
        self.goal = ctk.CTkLabel(info, text="", font=w.FONTS.body, text_color=t.TEXT, anchor="w", justify="left",
                                 wraplength=420)
        self.goal.pack(fill="x", pady=(2, 8))
        w.auto_wrap(self.goal, info, margin=0)
        self.progress = ctk.CTkProgressBar(info, height=10, progress_color=t.VIOLET, fg_color=t.TRACK)
        self.progress.pack(fill="x")
        self.progress_label = ctk.CTkLabel(info, text="", font=w.FONTS.small, text_color=t.MUTED, anchor="w")
        self.progress_label.pack(fill="x", pady=(4, 0))
        self.chart = w.BurndownChart(head, height=150)
        self.chart.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=14)

        # --- board
        board = ctk.CTkFrame(self.body, fg_color="transparent")
        board.grid(row=1, column=0, sticky="nsew")
        self.columns: dict[str, ctk.CTkScrollableFrame] = {}
        self.column_titles: dict[str, ctk.CTkLabel] = {}
        for i, (key, label) in enumerate(COLUMNS):
            board.grid_columnconfigure(i, weight=1, uniform="col")
            col = ctk.CTkFrame(board, fg_color=t.SURFACE, corner_radius=12)
            col.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == len(COLUMNS) - 1 else 5))
            board.grid_rowconfigure(0, weight=1)
            title = ctk.CTkLabel(col, text=label.upper(), font=w.FONTS.caption, text_color=t.COLUMN_COLOR[key],
                                 anchor="w")
            title.pack(fill="x", padx=12, pady=(10, 4))
            self.column_titles[key] = title
            scroll = ctk.CTkScrollableFrame(col, fg_color="transparent", scrollbar_button_color=t.TRACK)
            scroll.pack(fill="both", expand=True, padx=4, pady=(0, 6))
            self.columns[key] = scroll

    # ------------------------------------------------------------------ rendering
    def refresh(self) -> None:
        scrum = self.engine.scrum
        sprints = scrum.sprints()
        if self.sprint_id not in {s["id"] for s in sprints}:
            cur = scrum.current_sprint()
            self.sprint_id = cur["id"] if cur else None
        labels = [f"#{s['id']} {s['name']}" for s in sprints] or ["No sprints yet"]
        self.sprint_menu.configure(values=labels)
        sprint = next((s for s in sprints if s["id"] == self.sprint_id), None)
        self.sprint_menu.set(f"#{sprint['id']} {sprint['name']}" if sprint else labels[0])

        self.start_btn.pack_forget()
        self.close_btn.pack_forget()
        if sprint:
            w.set_pill(self.status_pill, sprint["status"].capitalize(), t.SPRINT_COLOR[sprint["status"]])
            if sprint["status"] == "planned":
                self.start_btn.pack(side="left")
            elif sprint["status"] == "active":
                self.close_btn.pack(side="left")
            days_left = (date.fromisoformat(sprint["end_date"]) - date.today()).days
            extra = f" · {days_left} day(s) left" if sprint["status"] == "active" and days_left >= 0 else ""
            self.dates.configure(text=f"{sprint['start_date']} → {sprint['end_date']}{extra}")
            self.goal.configure(text=f"Goal: {sprint['goal']}" if sprint["goal"] else "No sprint goal")
            p = scrum.progress(sprint["id"])
            self.progress.set(p["percent"] / 100)
            self.progress_label.configure(
                text=f"{p['done_points']} of {p['points']} story points done ({p['percent']:.0f}%) · "
                     f"{p['done_stories']}/{p['stories']} stories")
            self.chart.set_points(scrum.burndown(sprint["id"]))
        else:
            w.set_pill(self.status_pill, "–", t.DIM)
            self.dates.configure(text="Create a sprint to start planning.")
            self.goal.configure(text="")
            self.progress.set(0)
            self.progress_label.configure(text="")
            self.chart.set_points([])

        cards = {"backlog": scrum.stories(backlog=True)}
        board = scrum.board(sprint["id"]) if sprint else {s: [] for s in STATUSES}
        cards.update(board)
        for key, label in COLUMNS:
            for child in self.columns[key].winfo_children():
                child.destroy()
            stories = cards[key]
            self.column_titles[key].configure(
                text=f"{label.upper()}  ·  {len(stories)}  ·  {sum(s['points'] for s in stories)} pts")
            for story in stories:
                self._card(self.columns[key], key, story, sprint)

    def _card(self, parent, column: str, story: dict, sprint: dict | None) -> None:
        card = ctk.CTkFrame(parent, fg_color=t.CARD, corner_radius=10, border_width=1, border_color=t.BORDER)
        card.pack(fill="x", pady=4, padx=2)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))
        w.pill(top, f"{story['points']} pts", t.COLUMN_COLOR[column]).pack(side="left")
        ctk.CTkLabel(top, text=f"#{story['id']}", font=w.FONTS.caption, text_color=t.DIM).pack(side="right")
        title = ctk.CTkLabel(card, text=story["title"], font=w.FONTS.small, text_color=t.TEXT, anchor="w",
                             justify="left", wraplength=120)
        title.pack(fill="x", padx=10)
        w.auto_wrap(title, card)
        meta = []
        if story["assignee"]:
            meta.append(f"@{story['assignee']}")
        if story["source"] != "manual":
            meta.append("from " + story["source"].split("→")[0].strip())
        if meta:
            ctk.CTkLabel(card, text=" · ".join(meta), font=w.FONTS.mono_small, text_color=t.DIM, anchor="w").pack(
                fill="x", padx=10)
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=6, pady=(4, 8))

        def small(text, cmd, side="left"):
            ctk.CTkButton(btns, text=text, command=cmd, width=w.px(30), height=w.px(24), corner_radius=6,
                          font=w.FONTS.small, fg_color=t.SURFACE, hover_color=t.CARD_HOVER,
                          text_color=t.MUTED).pack(side=side, padx=2)

        sid = story["id"]
        if column == "backlog":
            if sprint and sprint["status"] != "closed":
                small("Add to sprint ▶", lambda: self._plan(sid, sprint["id"]))
        else:
            if column == "todo":
                small("◀ Backlog", lambda: self._plan(sid, None))
            else:
                small("◀", lambda: self._step(sid, -1))
            if column != "done":
                small("▶", lambda: self._step(sid, +1), side="right")
        small("✎", lambda: self._edit(story), side="right")

    # ------------------------------------------------------------------ actions
    def _guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except ScrumError as exc:
            self.app.toast(str(exc), t.AMBER)
        self.app.refresh()

    def _step(self, story_id: int, direction: int) -> None:
        self._guard(self.engine.scrum.step_story, story_id, direction)

    def _plan(self, story_id: int, sprint_id: int | None) -> None:
        self._guard(self.engine.scrum.plan_story, story_id, sprint_id)

    def _pick_sprint(self, label: str) -> None:
        if label.startswith("#"):
            self.sprint_id = int(label[1:].split()[0])
            self.refresh()

    def _start(self) -> None:
        if self.sprint_id:
            self._guard(self.engine.scrum.start_sprint, self.sprint_id)

    def _close(self) -> None:
        if not self.sprint_id:
            return
        try:
            moved = self.engine.scrum.close_sprint(self.sprint_id)
        except ScrumError as exc:
            self.app.toast(str(exc), t.AMBER)
            return
        self.app.toast(f"Sprint closed – {moved} unfinished stor{'y' if moved == 1 else 'ies'} back in the backlog.",
                       t.GREEN)
        self.app.refresh()

    def _new_sprint(self) -> None:
        start = date.today()
        n = len(self.engine.scrum.sprints()) + 1
        values = w.FormDialog(self, "New sprint", [
            ("name", "Name", f"Sprint {n}"), ("start", "Start (YYYY-MM-DD)", start.isoformat()),
            ("end", "End (YYYY-MM-DD)", (start + timedelta(days=13)).isoformat()), ("goal", "Sprint goal", "")],
        ).show()
        if not values:
            return
        try:
            self.sprint_id = self.engine.scrum.create_sprint(values["name"] or f"Sprint {n}", values["start"],
                                                              values["end"], values["goal"])
        except (ScrumError, ValueError) as exc:
            self.app.toast(f"Could not create sprint: {exc}", t.ROSE)
            return
        self.app.toast("Sprint created – pull stories in from the backlog, then start it.", t.GREEN)
        self.app.refresh()

    def _story_form(self, title: str, story: dict | None = None) -> dict | None:
        story = story or {}
        values = w.FormDialog(self, title, [
            ("title", "Title", story.get("title", "")), ("points", "Story points", str(story.get("points", 3))),
            ("assignee", "Assignee", story.get("assignee", "")),
            ("description", "Description", story.get("description", ""))], multiline={"description"}).show()
        if not values:
            return None
        try:
            values["points"] = int(values["points"] or 1)
        except ValueError:
            self.app.toast("Story points must be a whole number.", t.ROSE)
            return None
        return values

    def _new_story(self) -> None:
        values = self._story_form("New story")
        if values:
            sprint = self.engine.scrum.sprint(self.sprint_id) if self.sprint_id else None
            in_sprint = sprint and sprint["status"] != "closed"
            self._guard(lambda: self.engine.scrum.add_story(
                values["title"], values["points"], values["description"],
                sprint_id=self.sprint_id if in_sprint else None, assignee=values["assignee"]))

    def _edit(self, story: dict) -> None:
        values = self._story_form(f"Edit story #{story['id']}", story)
        if values:
            self._guard(lambda: self.engine.scrum.update_story(story["id"], **values))
