"""Palette, fonts and formatters – same visual language as API Health-Checker and System Process Monitor."""
from __future__ import annotations

import time
import tkinter.font as tkfont
from types import SimpleNamespace

import customtkinter as ctk

BG = "#0b0e14"
SURFACE = "#11151e"
CARD = "#161b26"
CARD_HOVER = "#1e2433"
ROW_ALT = "#1a2030"
BORDER = "#242b3b"
GRID = "#222939"
TRACK = "#232a3a"

TEXT = "#e7eaf1"
MUTED = "#8b93a7"
DIM = "#5d6578"

CYAN = "#22d3ee"
VIOLET = "#a78bfa"
GREEN = "#34d399"
AMBER = "#fbbf24"
ROSE = "#fb7185"
BLUE = "#60a5fa"
PINK = "#f472b6"
TEAL = "#2dd4bf"

RUN_STATUS = {
    "success": ("Success", GREEN),
    "partial": ("Partial", AMBER),
    "failed": ("Failed", ROSE),
    "blocked": ("Blocked", DIM),
    "never": ("Never run", DIM),
}
ACTION_COLOR = {"created": GREEN, "updated": BLUE, "unchanged": MUTED, "failed": ROSE}
COLUMN_COLOR = {"backlog": DIM, "todo": MUTED, "in_progress": BLUE, "review": VIOLET, "done": GREEN}
SPRINT_COLOR = {"planned": AMBER, "active": GREEN, "closed": DIM}

FONT = "Segoe UI"
MONO = "Consolas"


def mix(color_a: str, color_b: str, t: float) -> str:
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def init_fonts(root) -> SimpleNamespace:
    global FONT, MONO
    families = set(tkfont.families(root))
    for c in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica"):
        if c in families:
            FONT = c
            break
    for c in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"):
        if c in families:
            MONO = c
            break
    display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else FONT
    return SimpleNamespace(
        h1=ctk.CTkFont(display, 24, "bold"),
        h2=ctk.CTkFont(display, 15, "bold"),
        brand=ctk.CTkFont(display, 16, "bold"),
        metric=ctk.CTkFont(display, 28, "bold"),
        body=ctk.CTkFont(FONT, 13),
        body_bold=ctk.CTkFont(FONT, 13, "bold"),
        small=ctk.CTkFont(FONT, 12),
        caption=ctk.CTkFont(FONT, 11, "bold"),
        mono=ctk.CTkFont(MONO, 12),
        mono_small=ctk.CTkFont(MONO, 11),
    )


def fmt_ms(v: float | None) -> str:
    return "–" if v is None else f"{v:,.0f} ms".replace(",", " ")


def fmt_time(ts: float | None, with_date: bool = False) -> str:
    if not ts:
        return "–"
    return time.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M:%S", time.localtime(ts))


def fmt_ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = max(0, int(time.time() - ts))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"
