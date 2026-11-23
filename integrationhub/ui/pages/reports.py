from __future__ import annotations

import os
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ...export import SHEETS, export_workbook
from .. import theme as t
from .. import widgets as w
from .base import Page

SHEET_HELP = {
    "Summary": "Key figures, current sprint and a velocity chart",
    "Systems": "Every connected system with its last health check",
    "Integrations": "Source, target, schedule and totals per integration",
    "Run log": "Every sync run with created / updated / unchanged / failed counts",
    "Sprint backlog": "All stories with status, points, sprint and source",
    "Burndown": "Remaining vs. ideal story points of the current sprint, with chart",
}


class ReportsPage(Page):
    title = "Excel export"
    subtitle = "One formatted workbook for the team or the stakeholders: sync results and sprint status."

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        self.last_path: Path | None = None
        self.body.grid_columnconfigure(0, weight=2)
        self.body.grid_columnconfigure(1, weight=3)
        self.body.grid_rowconfigure(0, weight=1)

        left = w.Panel(self.body, "New report", "Choose the sheets to include")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.sheet_vars: dict[str, ctk.BooleanVar] = {}
        for name in SHEETS:
            var = ctk.BooleanVar(value=True)
            row = ctk.CTkFrame(left.body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkCheckBox(row, text=name, variable=var, font=w.FONTS.body_bold, text_color=t.TEXT,
                            fg_color=t.CYAN, hover_color=t.mix(t.CYAN, "#ffffff", .2), checkmark_color=t.BG,
                            border_color=t.BORDER).pack(anchor="w")
            ctk.CTkLabel(row, text=SHEET_HELP[name], font=w.FONTS.small, text_color=t.DIM, anchor="w").pack(
                anchor="w", padx=(30, 0))
            self.sheet_vars[name] = var
        self.health_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(left.body, text="Health-check every system first", variable=self.health_var,
                      font=w.FONTS.body, text_color=t.TEXT, progress_color=t.GREEN).pack(anchor="w", pady=(14, 6))
        folder = ctk.CTkFrame(left.body, fg_color="transparent")
        folder.pack(fill="x", pady=(6, 0))
        self.folder_label = ctk.CTkLabel(folder, text="", font=w.FONTS.mono_small, text_color=t.MUTED, anchor="w")
        self.folder_label.pack(side="left", fill="x", expand=True)
        w.ghost_button(folder, "Change…", self._choose_folder, width=90).pack(side="right")
        w.accent_button(left.body, "Export to Excel", self._export, color=t.GREEN, width=200).pack(
            anchor="w", pady=(16, 0))
        self.result = ctk.CTkLabel(left.body, text="", font=w.FONTS.small, text_color=t.MUTED, anchor="w",
                                   justify="left", wraplength=320)
        self.result.pack(fill="x", pady=(10, 0))
        btns = ctk.CTkFrame(left.body, fg_color="transparent")
        btns.pack(fill="x", pady=(6, 0))
        self.open_btn = w.ghost_button(btns, "Open file", self._open_file, width=100)
        self.folder_btn = w.ghost_button(btns, "Open folder", self._open_folder, width=110)

        right = w.Panel(self.body, "Previous reports", "Double-click to open")
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.table = w.DataTable(right.body, [("name", "File", 300), ("size", "Size", 70),
                                              ("time", "Created", 130)], height=14)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda _e: self._open_selected())

    @property
    def export_dir(self) -> Path:
        return self.app.export_dir or self.engine.config.settings.export_dir

    def refresh(self) -> None:
        self.folder_label.configure(text=str(self.export_dir))
        files = sorted(self.export_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if self.export_dir.exists() else []
        self.table.set_rows([(f.name, f"{f.stat().st_size / 1024:.0f} KB", t.fmt_time(f.stat().st_mtime, True))
                             for f in files], ids=[str(f) for f in files])

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Folder for Excel reports", initialdir=str(self.export_dir))
        if folder:
            self.app.export_dir = Path(folder)
            self.refresh()

    def _export(self) -> None:
        sheets = [n for n, v in self.sheet_vars.items() if v.get()]
        if not sheets:
            self.app.toast("Select at least one sheet.", t.AMBER)
            return
        path = self.export_dir / f"integration-hub-report-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
        check = self.health_var.get()

        def done(result: Path) -> None:
            self.last_path = result
            self.result.configure(text=f"Saved {result.name}\n({len(sheets)} sheet(s))", text_color=t.GREEN)
            self.open_btn.pack(side="left")
            self.folder_btn.pack(side="left", padx=6)
            self.app.toast(f"Excel report saved: {result.name}", t.GREEN)
            self.refresh()

        self.app.background(lambda: export_workbook(self.engine, path, sheets, check_health=check), done,
                            "Writing Excel report…")

    def _open_file(self) -> None:
        if self.last_path and self.last_path.exists():
            os.startfile(self.last_path)  # noqa: S606 – Windows desktop app

    def _open_folder(self) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.export_dir)  # noqa: S606

    def _open_selected(self) -> None:
        sel = self.table.selected()
        if sel and Path(sel).exists():
            os.startfile(sel)  # noqa: S606
