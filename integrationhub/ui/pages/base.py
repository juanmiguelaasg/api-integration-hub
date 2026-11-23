from __future__ import annotations

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w


class Page(ctk.CTkFrame):
    """A page with a title row (plus action buttons) and a body. ``refresh`` re-reads data from the engine."""

    title = ""
    subtitle = ""

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color=t.BG, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=self.title, font=w.FONTS.h1, text_color=t.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w")
        self.subtitle_label = ctk.CTkLabel(header, text=self.subtitle, font=w.FONTS.body, text_color=t.MUTED,
                                           anchor="w")
        self.subtitle_label.grid(row=1, column=0, sticky="w")
        self.actions = ctk.CTkFrame(header, fg_color="transparent", width=1, height=1)
        self.actions.grid(row=0, column=1, rowspan=2, sticky="e")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 22))

    @property
    def engine(self):
        return self.app.engine

    def refresh(self) -> None:
        """Re-read state and redraw. Called when the page is shown and after background jobs finish."""
