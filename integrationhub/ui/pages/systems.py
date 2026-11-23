from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk

from ...config import save_imported_systems, systems_from_healthchecker
from .. import theme as t
from .. import widgets as w
from .base import Page

AUTH_LABEL = {"none": "None", "api_key": "API key", "bearer": "Bearer token", "basic": "Basic auth"}


class SystemsPage(Page):
    title = "Systems"
    subtitle = "Every system the hub talks to, with its auth method and last health check."

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        w.ghost_button(self.actions, "Import from Health-Checker…", self._import, width=210).pack(side="left", padx=6)
        w.accent_button(self.actions, "Check all", app.check_systems, width=110).pack(side="left")

        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        panel = w.Panel(self.body, "Connected systems", "Defined in hub.yaml or imported from API Health-Checker")
        panel.grid(row=0, column=0, sticky="nsew")
        self.table = w.DataTable(panel.body, [
            ("name", "System", 130), ("url", "Base URL", 260), ("auth", "Auth", 100), ("health", "Health path", 110),
            ("status", "Status", 100), ("latency", "Latency", 80), ("checked", "Checked", 90),
            ("origin", "Defined in", 110)], height=10, on_select=self._show_detail)
        self.table.pack(fill="both", expand=True)

        self.detail = w.Panel(self.body, "Details", "Select a system")
        self.detail.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.detail_text = ctk.CTkLabel(self.detail.body, text="", font=w.FONTS.body, text_color=t.MUTED,
                                        anchor="w", justify="left")
        self.detail_text.pack(fill="x")

    def refresh(self) -> None:
        health = self.engine.store.latest_health()
        rows, ids, tags = [], [], []
        for name, s in self.engine.config.systems.items():
            h = health.get(name)
            status = "–" if not h else ("Healthy" if h["healthy"] else "Unhealthy")
            rows.append((name, s.base_url, AUTH_LABEL.get(s.auth_type, s.auth_type), s.health or "–", status,
                         t.fmt_ms(h["latency_ms"]) if h else "–", t.fmt_ago(h["checked_at"]) if h else "never",
                         s.origin))
            ids.append(name)
            tags.append(None if not h else ("green" if h["healthy"] else "rose"))
        self.table.set_rows(rows, ids=ids, tags=tags)
        self._show_detail(self.table.selected())

    def _show_detail(self, name: str | None) -> None:
        s = self.engine.config.systems.get(name or "")
        if not s:
            self.detail.subtitle_label.configure(text="Select a system")
            self.detail_text.configure(text="")
            return
        self.detail.title_label.configure(text=s.name)
        self.detail.subtitle_label.configure(text=s.description or "No description")
        used = [i.name for i in self.engine.config.integrations if s.name in (i.source.system, i.target.system)]
        h = self.engine.store.latest_health().get(s.name)
        lines = [
            f"Base URL:      {s.base_url}",
            f"Auth:          {AUTH_LABEL.get(s.auth_type, s.auth_type)}"
            + (f" (header {s.auth.get('header', 'X-API-Key')})" if s.auth_type == "api_key" else ""),
            f"Health check:  {s.health or 'none – the health gate always passes'}",
            f"Last result:   {h['message'] + ' · ' + t.fmt_time(h['checked_at'], True) if h else 'not checked yet'}",
            f"Used by:       {', '.join(used) if used else 'no integration yet'}",
        ]
        self.detail_text.configure(text="\n".join(lines), font=w.FONTS.mono)

    def _import(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the API Health-Checker endpoints.yaml",
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if not path:
            return
        try:
            systems = systems_from_healthchecker(path)
        except Exception as exc:   # noqa: BLE001 – any parse error is shown to the user
            self.app.toast(f"Import failed: {exc}", t.ROSE)
            return
        if not systems:
            self.app.toast("No endpoints with a URL found in that file.", t.AMBER)
            return
        save_imported_systems(self.engine.config.settings, systems)
        self.app.reload_config()
        self.app.toast(f"Imported {len(systems)} system(s): {', '.join(s.name for s in systems)}", t.GREEN)
