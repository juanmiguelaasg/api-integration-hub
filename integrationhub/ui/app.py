"""Main window: sidebar navigation, background jobs, auto-sync scheduler and toasts."""
from __future__ import annotations

import queue
import socket
import threading
import tkinter as tk
import traceback
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from .. import __version__
from ..config import load_config
from ..engine import Engine
from . import theme as t
from . import widgets as w
from .pages.dashboard import DashboardPage
from .pages.integrations import IntegrationsPage
from .pages.reports import ReportsPage
from .pages.scrum import ScrumPage
from .pages.systems import SystemsPage

NAV = [
    ("dashboard", "Dashboard", DashboardPage),
    ("systems", "Systems", SystemsPage),
    ("integrations", "Integrations", IntegrationsPage),
    ("scrum", "Scrum board", ScrumPage),
    ("reports", "Excel export", ReportsPage),
]


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class App(ctk.CTk):
    def __init__(self, config_path: str | Path, demo: bool = False) -> None:
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=t.BG)
        self.title("API Integration Hub")
        w.SCALE = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self._fit_to_screen(1380, 880)
        self.minsize(1180, 720)
        w.FONTS = t.init_fonts(self)
        w.configure_ttk(self)

        self.config_path = Path(config_path).resolve()
        self.engine = Engine(load_config(self.config_path))
        self.export_dir: Path | None = None
        self.auto_sync = False
        self._jobs: queue.Queue = queue.Queue()
        self._busy = 0
        self._toasts: list[ctk.CTkFrame] = []
        self.demo_server = None
        if demo:
            self._start_demo()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        content = ctk.CTkFrame(self, fg_color=t.BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for key, _label, cls in NAV:
            page = cls(content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.current = None
        self.show("dashboard")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_jobs)
        self.after(600, self.check_systems)
        self.after(self.engine.config.settings.scheduler_tick_seconds * 1000, self._scheduler_tick)

    # ------------------------------------------------------------------ layout
    def _fit_to_screen(self, width: int, height: int) -> None:
        s = w.SCALE
        sw, sh = self.winfo_screenwidth() / s, self.winfo_screenheight() / s
        width, height = int(min(width, sw * 0.94)), int(min(height, sh * 0.88))
        x, y = int((sw - width) / 2 * s), int(max(0, (sh - height) / 2 - 20) * s)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=t.SURFACE, corner_radius=0, width=w.px(236))
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 26))
        s = w.px(38)
        logo = tk.Canvas(brand, width=s, height=s, bg=t.SURFACE, highlightthickness=0)
        logo.pack(side="left")
        w.round_rect(logo, 0, 0, s, s, w.px(10), fill=t.mix(t.CYAN, t.SURFACE, 0.8), outline="")
        r = s * 0.1
        for cx, cy in ((.27, .3), (.73, .3), (.5, .74)):         # three connected nodes
            logo.create_line(cx * s, cy * s, .5 * s, .45 * s, fill=t.CYAN, width=max(2, w.px(2)))
        for cx, cy in ((.27, .3), (.73, .3), (.5, .74)):
            logo.create_oval(cx * s - r, cy * s - r, cx * s + r, cy * s + r, fill=t.CYAN, outline="")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=12)
        ctk.CTkLabel(names, text="Integration Hub", font=w.FONTS.brand, text_color=t.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(names, text=f"v{__version__}  /  REST · Scrum · Excel", font=w.FONTS.small, text_color=t.DIM,
                     anchor="w").pack(anchor="w")

        nav = ctk.CTkFrame(bar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(nav, text="NAVIGATION", font=w.FONTS.caption, text_color=t.DIM, anchor="w").pack(
            fill="x", padx=10, pady=(0, 6))
        self.nav_buttons = {}
        for key, label, _cls in NAV:
            btn = ctk.CTkButton(nav, text=label, anchor="w", height=40, corner_radius=10, font=w.FONTS.body,
                                fg_color="transparent", hover_color=t.CARD_HOVER, text_color=t.MUTED,
                                command=lambda k=key: self.show(k))
            btn.pack(fill="x", pady=2)
            self.nav_buttons[key] = btn

        foot = ctk.CTkFrame(bar, fg_color=t.CARD, corner_radius=12)
        foot.grid(row=3, column=0, sticky="ew", padx=14, pady=16)
        self.auto_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(foot, text="Auto-sync on schedule", variable=self.auto_var, command=self._toggle_auto,
                      font=w.FONTS.small, text_color=t.TEXT, progress_color=t.GREEN).pack(anchor="w", padx=12,
                                                                                         pady=(12, 4))
        self.status = ctk.CTkLabel(foot, text="Idle", font=w.FONTS.small, text_color=t.DIM, anchor="w",
                                   justify="left", wraplength=190)
        self.status.pack(fill="x", padx=12, pady=(0, 4))
        if self.demo_server:
            ctk.CTkLabel(foot, text="Demo systems on :8100", font=w.FONTS.caption, text_color=t.AMBER,
                         anchor="w").pack(fill="x", padx=12)
        ctk.CTkLabel(foot, text=self.config_path.name, font=w.FONTS.mono_small, text_color=t.DIM, anchor="w").pack(
            fill="x", padx=12, pady=(0, 12))

    def show(self, key: str) -> None:
        for k, btn in self.nav_buttons.items():
            active = k == key
            btn.configure(fg_color=t.CARD_HOVER if active else "transparent", text_color=t.TEXT if active else t.MUTED)
        self.current = key
        self.pages[key].tkraise()
        self.pages[key].refresh()

    def refresh(self) -> None:
        if self.current:
            self.pages[self.current].refresh()

    # ------------------------------------------------------------------ background jobs
    def background(self, work: Callable, done: Callable | None = None, label: str = "Working…") -> None:
        """Run ``work`` in a thread; ``done(result)`` is called on the UI thread afterwards."""
        self._busy += 1
        self.status.configure(text=label, text_color=t.CYAN)

        def runner() -> None:
            try:
                self._jobs.put((done, work(), None))
            except Exception as exc:  # noqa: BLE001 – surface any failure as a toast
                traceback.print_exc()
                self._jobs.put((None, None, exc))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_jobs(self) -> None:
        try:
            while True:
                done, result, error = self._jobs.get_nowait()
                self._busy = max(0, self._busy - 1)
                if error is not None:
                    self.toast(f"Error: {error}", t.ROSE)
                elif done:
                    done(result)
                if not self._busy:
                    self.status.configure(text="Idle" if not self.auto_sync else "Auto-sync on – waiting",
                                          text_color=t.DIM)
                self.refresh()
        except queue.Empty:
            pass
        self.after(120, self._drain_jobs)

    def check_systems(self) -> None:
        def done(results) -> None:
            down = [h.system for h in results if not h.healthy]
            if down:
                self.toast(f"Unhealthy: {', '.join(down)}", t.ROSE)
        self.background(self.engine.check_all, done, "Checking systems…")

    def run_integration(self, name: str, trigger: str = "manual") -> None:
        def done(result) -> None:
            color = {"success": t.GREEN, "partial": t.AMBER, "failed": t.ROSE, "blocked": t.AMBER}[result.status]
            self.toast(f"{name}: {result.summary()}", color)
        self.background(lambda: self.engine.run(name, trigger=trigger), done, f"Syncing {name}…")

    def run_all(self) -> None:
        for integ in self.engine.config.integrations:
            if integ.enabled:
                self.run_integration(integ.name)

    def reload_config(self) -> None:
        self.engine.config = load_config(self.config_path)
        self.refresh()

    # ------------------------------------------------------------------ scheduler
    def _toggle_auto(self) -> None:
        self.auto_sync = self.auto_var.get()
        self.status.configure(text="Auto-sync on – waiting" if self.auto_sync else "Idle", text_color=t.DIM)
        if self.auto_sync:
            self._scheduler_tick(reschedule=False)
        self.refresh()

    def _scheduler_tick(self, reschedule: bool = True) -> None:
        if self.auto_sync:
            for integ in self.engine.due():
                self.run_integration(integ.name, trigger="schedule")
        if reschedule:
            self.after(self.engine.config.settings.scheduler_tick_seconds * 1000, self._scheduler_tick)

    # ------------------------------------------------------------------ toasts
    def toast(self, text: str, color: str = t.CYAN, ms: int = 4500) -> None:
        frame = ctk.CTkFrame(self, fg_color=t.CARD, corner_radius=12, border_width=1, border_color=color)
        ctk.CTkLabel(frame, text=text, font=w.FONTS.small, text_color=t.TEXT, wraplength=380,
                     justify="left").pack(padx=14, pady=10)
        self._toasts.append(frame)
        self._place_toasts()
        self.after(ms, lambda: self._drop_toast(frame))

    def _place_toasts(self) -> None:
        y = -18
        for frame in reversed(self._toasts):
            frame.place(relx=1.0, rely=1.0, x=-18, y=y, anchor="se")
            frame.update_idletasks()
            y -= frame.winfo_height() + 8

    def _drop_toast(self, frame) -> None:
        if frame in self._toasts:
            self._toasts.remove(frame)
            frame.destroy()
            self._place_toasts()

    # ------------------------------------------------------------------ demo
    def _start_demo(self) -> None:
        from ..demo import seed_demo
        if not port_in_use(8100):
            import sys
            sys.path.insert(0, str(self.config_path.parent))
            from mock_systems import make_server
            self.demo_server = make_server(8100)
            threading.Thread(target=self.demo_server.serve_forever, daemon=True).start()
        else:
            self.demo_server = True   # already running elsewhere (e.g. start_demo_api.bat)
        seed_demo(self.engine.scrum)

    def _on_close(self) -> None:
        if self.demo_server not in (None, True):
            self.demo_server.shutdown()
        self.destroy()


def run_app(config_path: str | Path, demo: bool = False) -> int:
    App(config_path, demo=demo).mainloop()
    return 0
