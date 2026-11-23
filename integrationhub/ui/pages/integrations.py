from __future__ import annotations

import json

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page


def describe_rule(rule) -> str:
    if isinstance(rule, str):
        return f"template  {rule}" if "{" in rule else f"field     {rule}"
    if isinstance(rule, dict):
        if "const" in rule:
            return f"constant  {rule['const']!r}"
        parts = [f"field     {rule.get('from') or rule.get('template')}"]
        if rule.get("map"):
            parts.append("map " + ", ".join(f"{k}→{v}" for k, v in rule["map"].items()))
        if rule.get("transform"):
            tr = rule["transform"]
            parts.append("→ " + (" → ".join(tr) if isinstance(tr, list) else tr))
        if "default" in rule:
            parts.append(f"default {rule['default']!r}")
        return "  ".join(parts)
    return repr(rule)


class IntegrationsPage(Page):
    title = "Integrations"
    subtitle = "Source → mapping → target. Only new or changed records are sent; a dry run sends nothing."

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        self.current: str | None = None
        self.last_preview: dict[str, list] = {}

        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=1)
        top = w.Panel(self.body, "Integrations", "Select one to see its mapping and last run")
        top.grid(row=0, column=0, sticky="ew")
        self.table = w.DataTable(top.body, [
            ("name", "Integration", 240), ("flow", "Source → target", 300), ("every", "Schedule", 90),
            ("last", "Last run", 90), ("status", "Status", 90), ("totals", "Created / updated", 120)],
            height=3, on_select=self._select)
        self.table.pack(fill="x")

        lower = ctk.CTkFrame(self.body, fg_color="transparent")
        lower.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        lower.grid_columnconfigure((0, 1), weight=1, uniform="lower")
        lower.grid_rowconfigure(0, weight=1)

        self.detail = w.Panel(lower, "Mapping", "")
        self.detail.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.run_btn = w.accent_button(self.detail.actions, "Run now", self._run, width=96)
        self.run_btn.pack(side="right")
        w.ghost_button(self.detail.actions, "Dry run", self._dry_run, width=86).pack(side="right", padx=6)
        # bottom-up packing keeps the flow description and reset button visible on small windows
        w.ghost_button(self.detail.body, "Reset sync state", self._reset, width=140).pack(
            side="bottom", anchor="w", pady=(8, 0))
        self.flow_label = ctk.CTkLabel(self.detail.body, text="", font=w.FONTS.small, text_color=t.MUTED,
                                       anchor="w", justify="left", wraplength=360)
        self.flow_label.pack(side="bottom", fill="x", pady=(10, 0))
        w.auto_wrap(self.flow_label, self.detail.body, margin=0)
        self.mapping_table = w.DataTable(self.detail.body, [("field", "Target field", 120), ("rule", "Rule", 300)],
                                         height=5)
        self.mapping_table.pack(fill="both", expand=True)

        self.items_panel = w.Panel(lower, "Last run", "")
        self.items_panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.items_table = w.DataTable(self.items_panel.body, [
            ("key", "Source key", 80), ("action", "Action", 80), ("target", "Target ID", 80),
            ("detail", "Detail", 340)], height=12)
        self.items_table.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        cfg, store = self.engine.config, self.engine.store
        totals = store.run_totals()
        rows, ids, tags = [], [], []
        for integ in cfg.integrations:
            last = store.last_run(integ.name)
            tot = totals.get(integ.name, {})
            label, _ = t.RUN_STATUS[last["status"] if last else "never"]
            rows.append((integ.name, f"{integ.source_label}  →  {integ.target_label}",
                         f"{integ.schedule_minutes:g} min" if integ.schedule_minutes else "manual",
                         t.fmt_ago(last["started_at"]) if last else "never", label,
                         f"{tot.get('created') or 0} / {tot.get('updated') or 0}"))
            ids.append(integ.name)
            tags.append({"success": "green", "partial": "amber", "failed": "rose", "blocked": "dim"}.get(
                last["status"]) if last else "dim")
        self.table.set_rows(rows, ids=ids, tags=tags)
        if self.current is None and ids:
            self.current = ids[0]
            self.table.select(ids[0])
        self._render_detail()

    def _select(self, name: str | None) -> None:
        if name:
            self.current = name
            self._render_detail()

    def _render_detail(self) -> None:
        try:
            integ = self.engine.config.integration(self.current or "")
        except KeyError:
            return
        self.detail.title_label.configure(text=integ.name)
        self.detail.subtitle_label.configure(text=f"{len(integ.mapping)} mapped fields · key '{integ.key}'")
        self.detail.subtitle_label.grid(row=1, column=0, sticky="w")
        self.mapping_table.set_rows([(k, describe_rule(v)) for k, v in integ.mapping.items()])
        f = integ.source.filter
        flow = ([integ.description, ""] if integ.description else []) + [
                f"Source: {integ.source.method} {integ.source_label}"
                + (f"  (items at '{integ.source.items}')" if integ.source.items else ""),
                f"Filter: {', '.join(f'{k} = {v}' for k, v in f.items()) if f else 'none'}",
                f"Key: {integ.key}   ·   Target: {integ.target_label}"]
        if integ.target.update_path:
            flow.append(f"Changes: {integ.target.update_method or 'PUT'} {integ.target.update_path}")
        self.flow_label.configure(text="\n".join(flow))

        if integ.name in self.last_preview:
            self.items_panel.title_label.configure(text="Dry run preview")
            self.items_panel.subtitle_label.configure(text="Mapped payloads – nothing was sent")
            self.items_panel.subtitle_label.grid(row=1, column=0, sticky="w")
            self.items_table.set_rows([(p["key"], "preview", "–", json.dumps(p["payload"], ensure_ascii=False))
                                       for p in self.last_preview[integ.name]], tags=None)
            return
        last = self.engine.store.last_run(integ.name)
        self.items_panel.title_label.configure(text="Last run")
        self.items_panel.subtitle_label.grid(row=1, column=0, sticky="w")
        if not last:
            self.items_panel.subtitle_label.configure(text="Never run")
            self.items_table.set_rows([])
            return
        self.items_panel.subtitle_label.configure(
            text=f"{t.fmt_time(last['started_at'], True)} · {last['status']} · {t.fmt_ms(last['duration_ms'])}"
                 + (f" · {last['message']}" if last["message"] else ""))
        items = self.engine.store.run_items(last["id"])
        tag_for = {"created": "green", "updated": "blue", "unchanged": "muted", "failed": "rose"}
        self.items_table.set_rows([(i["source_key"], i["action"], i["target_id"] or "–", i["message"])
                                   for i in items], tags=[tag_for.get(i["action"]) for i in items])

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if self.current:
            self.last_preview.pop(self.current, None)
            self.app.run_integration(self.current)

    def _dry_run(self) -> None:
        name = self.current
        if not name:
            return

        def done(result) -> None:
            self.last_preview[name] = result.preview
            self.app.toast(f"Dry run: {len(result.preview)} payload(s) mapped, nothing sent"
                           if result.status != "blocked" else f"Dry run blocked – {result.message}",
                           t.CYAN if result.status != "blocked" else t.AMBER)
            self._render_detail()

        self.app.background(lambda: self.engine.run(name, dry_run=True), done, f"Dry run: {name}…")

    def _reset(self) -> None:
        if self.current:
            self.engine.store.reset_state(self.current)
            self.app.toast("Sync state cleared – the next run treats every record as new "
                           "(the target upserts, so no duplicates).", t.AMBER)
