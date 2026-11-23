"""Reusable widgets: cards, pills, buttons, a dark Treeview table and the burndown chart."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import customtkinter as ctk

from . import theme as t

FONTS: SimpleNamespace = SimpleNamespace()
SCALE = 1.0


def px(value: float) -> int:
    return int(round(value * SCALE))


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class Panel(ctk.CTkFrame):
    """Rounded card with a title row and a body frame."""

    def __init__(self, master, title: str = "", subtitle: str = "", **kw) -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        head.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(head, text=title, font=FONTS.h2, text_color=t.TEXT, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ctk.CTkLabel(head, text=subtitle, font=FONTS.small, text_color=t.MUTED, anchor="w")
        if subtitle:
            self.subtitle_label.grid(row=1, column=0, sticky="w")
        self.actions = ctk.CTkFrame(head, fg_color="transparent", width=1, height=1)
        self.actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))


class StatCard(ctk.CTkFrame):
    def __init__(self, master, label: str, color: str = t.CYAN) -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
        bar = ctk.CTkFrame(self, fg_color=color, width=4, height=1, corner_radius=2)
        bar.pack(side="left", fill="y", padx=(12, 0), pady=14)
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(side="left", fill="both", expand=True, padx=14, pady=12)
        ctk.CTkLabel(box, text=label.upper(), font=FONTS.caption, text_color=t.DIM, anchor="w").pack(anchor="w")
        self.value = ctk.CTkLabel(box, text="–", font=FONTS.metric, text_color=t.TEXT, anchor="w")
        self.value.pack(anchor="w")
        self.sub = ctk.CTkLabel(box, text="", font=FONTS.small, text_color=t.MUTED, anchor="w")
        self.sub.pack(anchor="w")

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.configure(text=value, text_color=color or t.TEXT)
        self.sub.configure(text=sub)


def auto_wrap(label: ctk.CTkLabel, container, margin: int = 24) -> None:
    """Keep a label's wraplength equal to its container's current width (CTk scales wraplength itself)."""
    def update(event) -> None:
        scale = label._get_widget_scaling()
        label.configure(wraplength=max(60, (event.width - margin * scale) / scale))
    container.bind("<Configure>", update, add="+")


def pill(master, text: str, color: str, bg: str = t.CARD) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=f"  {text}  ", font=FONTS.caption, text_color=color,
                        fg_color=t.mix(color, bg, 0.82), corner_radius=8, height=22)


def set_pill(label: ctk.CTkLabel, text: str, color: str, bg: str = t.CARD) -> None:
    label.configure(text=f"  {text}  ", text_color=color, fg_color=t.mix(color, bg, 0.82))


def accent_button(master, text: str, command, color: str = t.CYAN, width: int = 120, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=9,
                         font=FONTS.body_bold, fg_color=color, hover_color=t.mix(color, "#ffffff", 0.2),
                         text_color="#0b0e14", **kw)


def ghost_button(master, text: str, command, width: int = 120, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=9,
                         font=FONTS.body, fg_color="transparent", hover_color=t.CARD_HOVER, border_width=1,
                         border_color=t.BORDER, text_color=t.TEXT, **kw)


def configure_ttk(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    rh = px(30)
    style.configure("Hub.Treeview", background=t.CARD, fieldbackground=t.CARD, foreground=t.TEXT,
                    bordercolor=t.CARD, borderwidth=0, rowheight=rh, font=(t.FONT, 10))
    style.configure("Hub.Treeview.Heading", background=t.SURFACE, foreground=t.MUTED, relief="flat",
                    borderwidth=0, font=(t.FONT, 9, "bold"), padding=(8, 6))
    style.map("Hub.Treeview", background=[("selected", t.mix(t.CYAN, t.CARD, 0.78))],
              foreground=[("selected", t.TEXT)])
    style.map("Hub.Treeview.Heading", background=[("active", t.CARD_HOVER)])
    style.layout("Hub.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Hub.Vertical.TScrollbar", background=t.TRACK, troughcolor=t.CARD, bordercolor=t.CARD,
                    arrowcolor=t.DIM, lightcolor=t.TRACK, darkcolor=t.TRACK, gripcount=0, arrowsize=px(11))
    style.map("Hub.Vertical.TScrollbar", background=[("active", t.BORDER), ("!active", t.TRACK)],
              lightcolor=[("active", t.BORDER)], darkcolor=[("active", t.BORDER)])


class DataTable(ctk.CTkFrame):
    """ttk.Treeview with dark styling, zebra rows and per-row colour tags."""

    def __init__(self, master, columns: list[tuple[str, str, int]], height: int = 8, on_select=None) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height, style="Hub.Treeview",
                                 selectmode="browse")
        for key, label, width in columns:
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(key, width=px(width), minwidth=px(40), anchor="w", stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style="Hub.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("alt", background=t.ROW_ALT)
        for name, color in (("green", t.GREEN), ("amber", t.AMBER), ("rose", t.ROSE), ("blue", t.BLUE),
                            ("muted", t.MUTED), ("dim", t.DIM)):
            self.tree.tag_configure(name, foreground=color)
        self._on_select = on_select
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select(self.selected()))

    def set_rows(self, rows: list[tuple], ids: list[str] | None = None, tags: list[str | None] | None = None,
                 keep_selection: bool = True) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            iid = ids[i] if ids else str(i)
            row_tags = ["alt"] if i % 2 else []
            if tags and tags[i]:
                row_tags.append(tags[i])
            self.tree.insert("", "end", iid=iid, values=row, tags=row_tags)
        if keep_selection and selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def select(self, iid: str) -> None:
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)


class BurndownChart(tk.Canvas):
    """Ideal line (dashed) vs. remaining story points per sprint day."""

    def __init__(self, master, height: int = 180) -> None:
        super().__init__(master, height=px(height), bg=t.CARD, highlightthickness=0)
        self.points: list = []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_points(self, points) -> None:
        self.points = list(points)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or not self.points:
            self.create_text(w / 2, h / 2, text="No sprint data", fill=t.DIM, font=(t.FONT, 10))
            return
        left, right, top, bottom = px(34), px(10), px(10), px(24)
        top_val = max([p.ideal for p in self.points] + [p.remaining or 0 for p in self.points] + [1])
        n = len(self.points)

        def xy(i, v):
            x = left + (w - left - right) * (i / max(1, n - 1))
            y = top + (h - top - bottom) * (1 - v / top_val)
            return x, y

        for frac in (0, 0.5, 1):
            y = top + (h - top - bottom) * (1 - frac)
            self.create_line(left, y, w - right, y, fill=t.GRID)
            self.create_text(left - px(6), y, text=f"{top_val * frac:.0f}", fill=t.DIM, anchor="e",
                             font=(t.FONT, 8))
        for i in (0, n // 2, n - 1):
            x, _ = xy(i, 0)
            self.create_text(x, h - px(10), text=self.points[i].day.strftime("%b %d"), fill=t.DIM,
                             font=(t.FONT, 8))
        ideal = [c for i, p in enumerate(self.points) for c in xy(i, p.ideal)]
        self.create_line(*ideal, fill=t.MUTED, dash=(4, 3), width=1)
        real = [(i, p.remaining) for i, p in enumerate(self.points) if p.remaining is not None]
        if len(real) >= 2:
            coords = [c for i, v in real for c in xy(i, v)]
            self.create_line(*coords, fill=t.CYAN, width=max(2, px(2)), joinstyle="round", capstyle="round")
        for i, v in real[-1:]:
            x, y = xy(i, v)
            r = px(4)
            self.create_oval(x - r, y - r, x + r, y + r, fill=t.CYAN, outline=t.CARD, width=2)
        self.create_text(w - right, top, text="— remaining   ┄ ideal", fill=t.DIM, anchor="ne", font=(t.FONT, 8))


class FormDialog(ctk.CTkToplevel):
    """Small modal form. ``fields`` is a list of (key, label, default). Result is a dict or None."""

    def __init__(self, master, title: str, fields: list[tuple[str, str, str]], multiline: set[str] = frozenset()):
        super().__init__(master, fg_color=t.SURFACE)
        self.title(title)
        self.resizable(False, False)
        self.result: dict | None = None
        self.entries: dict[str, ctk.CTkEntry | ctk.CTkTextbox] = {}
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=22, pady=18)
        ctk.CTkLabel(box, text=title, font=FONTS.h2, text_color=t.TEXT).pack(anchor="w", pady=(0, 10))
        for key, label, default in fields:
            ctk.CTkLabel(box, text=label, font=FONTS.small, text_color=t.MUTED).pack(anchor="w")
            if key in multiline:
                e = ctk.CTkTextbox(box, width=px(380), height=px(70), fg_color=t.CARD, border_color=t.BORDER,
                                   border_width=1, font=FONTS.body)
                e.insert("1.0", default)
            else:
                e = ctk.CTkEntry(box, width=px(380), fg_color=t.CARD, border_color=t.BORDER, font=FONTS.body)
                e.insert(0, default)
            e.pack(anchor="w", pady=(2, 10))
            self.entries[key] = e
        self.error = ctk.CTkLabel(box, text="", font=FONTS.small, text_color=t.ROSE)
        self.error.pack(anchor="w")
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", pady=(6, 0))
        accent_button(btns, "Save", self._ok, width=100).pack(side="right")
        ghost_button(btns, "Cancel", self.destroy, width=100).pack(side="right", padx=8)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(master.winfo_toplevel())
        self.after(50, self._focus)

    def _focus(self) -> None:
        try:
            self.grab_set()
            next(iter(self.entries.values())).focus_set()
        except (tk.TclError, StopIteration):
            pass

    def values(self) -> dict:
        out = {}
        for key, e in self.entries.items():
            out[key] = (e.get("1.0", "end") if isinstance(e, ctk.CTkTextbox) else e.get()).strip()
        return out

    def _ok(self) -> None:
        self.result = self.values()
        self.destroy()

    def show(self) -> dict | None:
        self.wait_window()
        return self.result
