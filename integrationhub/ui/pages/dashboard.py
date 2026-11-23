from __future__ import annotations

import time

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page


class DashboardPage(Page):
    title = "Dashboard"
    subtitle = "Connected systems, sync activity and the current sprint at a glance."

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        w.ghost_button(self.actions, "Check systems", app.check_systems, width=130).pack(side="left", padx=6)
        w.accent_button(self.actions, "Run all integrations", app.run_all, width=170).pack(side="left")

        self.body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="cards")
        self.body.grid_rowconfigure(1, weight=1)
        self.cards = {
            "systems": w.StatCard(self.body, "Systems healthy", t.GREEN),
            "integrations": w.StatCard(self.body, "Integrations", t.CYAN),
            "runs": w.StatCard(self.body, "Sync runs · 24 h", t.BLUE),
            "sprint": w.StatCard(self.body, "Sprint progress", t.VIOLET),
        }
        for i, card in enumerate(self.cards.values()):
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 3 else 7), pady=(0, 14))

        lower = ctk.CTkFrame(self.body, fg_color="transparent")
        lower.grid(row=1, column=0, columnspan=4, sticky="nsew")
        lower.grid_columnconfigure(0, weight=2)
        lower.grid_columnconfigure(1, weight=3)
        lower.grid_rowconfigure(0, weight=1)

        self.systems_panel = w.Panel(lower, "Systems", "Health gate status before each sync")
        self.systems_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.system_rows = ctk.CTkFrame(self.systems_panel.body, fg_color="transparent")
        self.system_rows.pack(fill="both", expand=True)

        runs = w.Panel(lower, "Recent sync runs", "Newest first")
        runs.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.runs_table = w.DataTable(runs.body, [
            ("time", "Time", 70), ("integration", "Integration", 230), ("status", "Status", 80),
            ("result", "Created / updated / unchanged / failed", 230)], height=12)
        self.runs_table.pack(fill="both", expand=True)

    def refresh(self) -> None:
        eng = self.engine
        cfg = eng.config
        health = eng.store.latest_health()
        healthy = sum(1 for s in cfg.systems if health.get(s, {}).get("healthy"))
        checked = sum(1 for s in cfg.systems if s in health)
        color = t.GREEN if checked and healthy == len(cfg.systems) else (t.AMBER if checked else t.TEXT)
        self.cards["systems"].set(f"{healthy}/{len(cfg.systems)}" if checked else "–",
                                  "all reachable" if checked and healthy == len(cfg.systems)
                                  else ("not checked yet" if not checked else "some systems are down"), color)

        scheduled = sum(1 for i in cfg.integrations if i.enabled and i.schedule_minutes)
        self.cards["integrations"].set(str(len(cfg.integrations)),
                                       f"{scheduled} scheduled · auto-sync {'on' if self.app.auto_sync else 'off'}")

        day = eng.store.runs(since=time.time() - 86400, limit=10000)
        ok = sum(r["status"] == "success" for r in day)
        self.cards["runs"].set(str(len(day)), f"{ok / len(day) * 100:.0f}% successful" if day else "no runs yet",
                               t.GREEN if day and ok == len(day) else None)

        sprint = eng.scrum.current_sprint()
        if sprint:
            p = eng.scrum.progress(sprint["id"])
            self.cards["sprint"].set(f"{p['percent']:.0f}%", f"{p['done_points']}/{p['points']} pts · {sprint['name']}")
        else:
            self.cards["sprint"].set("–", "no sprint yet")

        for child in self.system_rows.winfo_children():
            child.destroy()
        for name, system in cfg.systems.items():
            h = health.get(name)
            row = ctk.CTkFrame(self.system_rows, fg_color=t.SURFACE, corner_radius=10)
            row.pack(fill="x", pady=4)
            dot = t.DIM if not h else (t.GREEN if h["healthy"] else t.ROSE)
            ctk.CTkLabel(row, text="●", text_color=dot, font=w.FONTS.body).pack(side="left", padx=(12, 6), pady=8)
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(box, text=name, font=w.FONTS.body_bold, text_color=t.TEXT, anchor="w").pack(anchor="w")
            ctk.CTkLabel(box, text=system.base_url, font=w.FONTS.mono_small, text_color=t.DIM, anchor="w").pack(
                anchor="w")
            label = "not checked" if not h else (t.fmt_ms(h["latency_ms"]) if h["healthy"] else h["message"])
            ctk.CTkLabel(row, text=label, font=w.FONTS.small, text_color=t.MUTED).pack(side="right", padx=12)

        rows, tags = [], []
        for r in eng.store.runs(limit=60):
            label, _color = t.RUN_STATUS.get(r["status"], (r["status"], t.MUTED))
            result = (r["message"] if r["status"] == "blocked"
                      else f"{r['created']} / {r['updated']} / {r['unchanged']} / {r['failed']}")
            rows.append((t.fmt_time(r["started_at"]), r["integration"], label, result))
            tags.append({"success": "green", "partial": "amber", "failed": "rose", "blocked": "dim"}.get(r["status"]))
        self.runs_table.set_rows(rows, tags=tags)
