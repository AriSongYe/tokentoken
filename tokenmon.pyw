"""
TokenToken - Claude / Codex token usage monitor (always-on-top, resizable widget).

    pythonw tokenmon.pyw

Drag anywhere to move, drag the ◢ corner to resize, right-click for options.
"""
import json
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from usage_core import UsageMonitor, fmt_ago, fmt_duration, fmt_tokens  # noqa: E402

APP = "TokenToken"
IS_WIN = os.name == "nt"

DEFAULTS = {
    "geometry": "340x300+60+60",
    "topmost": True,
    "frameless": True,
    "alpha": 0.95,
    "refresh_sec": 30,
    "show_claude": True,
    "show_codex": True,
    "claude_api": True,
    "claude_api_interval": 90,
    "claude_block_limit": 0,   # optional: tokens per 5h block for a local % estimate
    "claude_dirs": [],         # optional: extra Claude Code config dirs (auto: ~/.claude, ~/.claude-*)
    "show_idle_claude": False, # also show config dirs with no recent use and no live login
    "theme": "dark",
}

THEMES = {
    "dark": {"bg": "#16171b", "panel": "#1f2026", "fg": "#e8e8ea", "dim": "#8b8d96",
             "track": "#2e3038", "line": "#2a2b31"},
    "light": {"bg": "#f6f6f4", "panel": "#ffffff", "fg": "#1d1d1f", "dim": "#6e6e73",
              "track": "#e4e4e0", "line": "#e2e2de"},
}
ACCENT = {"claude": "#d97757", "codex": "#10a37f"}
OK, WARN, BAD = "#3fb27f", "#e0a43a", "#e5534b"


def config_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, APP)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "config.json")


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def gui_python():
    exe = sys.executable
    if IS_WIN and os.path.basename(exe).lower() == "python.exe":
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(cand):
            return cand
    return exe


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    """Command line used for Windows auto-start."""
    launcher = os.path.join(os.path.dirname(HERE), "TokenToken.exe")  # installed layout
    if os.path.isfile(launcher):
        return '"%s"' % launcher
    return '"%s" "%s"' % (gui_python(), os.path.abspath(__file__))


def autostart_enabled():
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass
    # clean up the startup-folder script used by older versions
    appdata = os.environ.get("APPDATA")
    if appdata:
        old = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "TokenToken.vbs")
        if os.path.isfile(old):
            os.remove(old)


def already_running():
    """Single instance guard (Windows named mutex)."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        already_running._h = k32.CreateMutexW(None, False, "Local\\TokenTokenMonitorMutex")
        return k32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def bar_color(pct):
    return OK if pct < 60 else WARN if pct < 85 else BAD


class App:
    def __init__(self):
        self.cfg = load_config()
        self.monitor = UsageMonitor()
        self.snap = None
        self._pending = None
        self._wake = threading.Event()
        self._compact = None
        self._layout_key = None

        if IS_WIN:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.title(APP)
        ico = os.path.join(HERE, "tokentoken.ico")
        if IS_WIN and os.path.isfile(ico):
            try:
                self.root.iconbitmap(default=ico)
            except tk.TclError:
                pass
        self.root.minsize(160, 70)
        self.root.geometry(self.cfg["geometry"])
        self.dpi = self.root.winfo_fpixels("1i")
        fam = "Malgun Gothic" if IS_WIN else "DejaVu Sans"
        self.f_title = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_main = tkfont.Font(family=fam, size=9)
        self.f_bold = tkfont.Font(family=fam, size=9, weight="bold")
        self.f_small = tkfont.Font(family=fam, size=8)
        self.f_base = None

        self.vars = {k: tk.BooleanVar(value=bool(self.cfg[k]))
                     for k in ("topmost", "frameless", "show_claude", "show_codex", "claude_api")}
        self.v_alpha = tk.DoubleVar(value=self.cfg["alpha"])
        self.v_refresh = tk.IntVar(value=self.cfg["refresh_sec"])
        self.v_theme = tk.StringVar(value=self.cfg.get("theme", "dark"))
        self.v_autostart = tk.BooleanVar(value=autostart_enabled())

        self._build_shell()
        self._apply_window_flags(initial=True)
        self._build_menu()

        self.root.bind("<Configure>", self._on_configure)
        self.root.bind_all("<Button-3>", self._popup)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(300, self._poll)
        self.root.after(20000, self._tick)

    # ------------------------------------------------------------ window
    @property
    def t(self):
        return THEMES.get(self.v_theme.get(), THEMES["dark"])

    def _apply_window_flags(self, initial=False):
        r = self.root
        frameless = self.vars["frameless"].get()
        if not initial:
            geo = r.geometry()
            r.withdraw()
        r.overrideredirect(frameless)
        if not initial:
            r.geometry(geo)
            r.deiconify()
        r.attributes("-topmost", self.vars["topmost"].get())
        try:
            r.attributes("-alpha", float(self.v_alpha.get()))
        except tk.TclError:
            pass
        self.grip.place_forget()
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

    def _build_shell(self):
        t = self.t
        r = self.root
        r.configure(bg=t["line"])
        self.outer = tk.Frame(r, bg=t["bg"])
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)

        self.header = tk.Frame(self.outer, bg=t["bg"])
        self.header.pack(fill="x", padx=8, pady=(5, 2))
        self.lbl_title = tk.Label(self.header, text="TOKENTOKEN", font=self.f_title,
                                  bg=t["bg"], fg=t["fg"])
        self.lbl_title.pack(side="left")
        self.btn_close = self._btn("✕", self.quit)
        self.btn_close.pack(side="right", padx=(6, 0))
        self.btn_refresh = self._btn("⟳", self.refresh_now)
        self.btn_refresh.pack(side="right", padx=(6, 0))
        self.btn_pin = self._btn("", self.toggle_topmost)
        self.btn_pin.pack(side="right")
        self._update_pin()

        self.body = tk.Frame(self.outer, bg=t["bg"])
        self.body.pack(fill="both", expand=True, padx=8)

        self.footer = tk.Label(self.outer, text="불러오는 중…", font=self.f_small,
                               bg=t["bg"], fg=t["dim"], anchor="w")
        self.footer.pack(fill="x", padx=8, pady=(0, 4))

        self.grip = tk.Label(self.outer, text="◢", font=self.f_small, bg=t["bg"],
                             fg=t["dim"], cursor="size_nw_se" if IS_WIN else "bottom_right_corner")
        self.grip.bind("<ButtonPress-1>", self._grip_start)
        self.grip.bind("<B1-Motion>", self._grip_move)
        self.grip.bind("<ButtonRelease-1>", lambda e: self._save_geometry())
        self._nodrag = {self.btn_close, self.btn_refresh, self.btn_pin, self.grip}
        self._bind_drag(self.outer)

    def _btn(self, text, cmd):
        t = self.t
        b = tk.Label(self.header, text=text, font=self.f_bold, bg=t["bg"], fg=t["dim"], cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=self.t["fg"]))
        b.bind("<Leave>", lambda e: (b.configure(fg=self.t["dim"]), self._update_pin()))
        return b

    def _update_pin(self):
        on = self.vars["topmost"].get()
        self.btn_pin.configure(text="● 고정" if on else "○ 고정",
                               fg=ACCENT["claude"] if on else self.t["dim"])

    def _bind_drag(self, w):
        if w in self._nodrag:
            return
        w.bind("<ButtonPress-1>", self._drag_start, add="+")
        w.bind("<B1-Motion>", self._drag_move, add="+")
        w.bind("<ButtonRelease-1>", lambda e: self._save_geometry(), add="+")
        for c in w.winfo_children():
            self._bind_drag(c)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if getattr(self, "_drag", None):
            self.root.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def _grip_start(self, e):
        self._gs = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _grip_move(self, e):
        x0, y0, w0, h0 = self._gs
        w = max(160, w0 + e.x_root - x0)
        h = max(70, h0 + e.y_root - y0)
        self.root.geometry("%dx%d" % (w, h))

    def _save_geometry(self):
        self._drag = None
        self.cfg["geometry"] = self.root.geometry()
        save_config(self.cfg)

    # ------------------------------------------------------------ menu
    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="지금 새로고침", command=self.refresh_now)
        m.add_separator()
        m.add_checkbutton(label="항상 위에 고정", variable=self.vars["topmost"], command=self.toggle_topmost_var)
        m.add_checkbutton(label="테두리 없는 위젯 모드", variable=self.vars["frameless"], command=self._on_flags)
        alpha = tk.Menu(m, tearoff=0)
        for a in (1.0, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
            alpha.add_radiobutton(label="%d%%" % (a * 100), value=a, variable=self.v_alpha, command=self._on_flags)
        m.add_cascade(label="투명도", menu=alpha)
        theme = tk.Menu(m, tearoff=0)
        theme.add_radiobutton(label="다크", value="dark", variable=self.v_theme, command=self._on_theme)
        theme.add_radiobutton(label="라이트", value="light", variable=self.v_theme, command=self._on_theme)
        m.add_cascade(label="테마", menu=theme)
        m.add_separator()
        m.add_checkbutton(label="Claude 표시", variable=self.vars["show_claude"], command=self._on_opts)
        m.add_checkbutton(label="Codex 표시", variable=self.vars["show_codex"], command=self._on_opts)
        m.add_checkbutton(label="Claude 구독 한도(%) 조회", variable=self.vars["claude_api"], command=self._on_opts)
        ref = tk.Menu(m, tearoff=0)
        for s in (10, 30, 60, 120, 300):
            ref.add_radiobutton(label="%d초" % s, value=s, variable=self.v_refresh, command=self._on_opts)
        m.add_cascade(label="새로고침 주기", menu=ref)
        m.add_separator()
        m.add_command(label="MCP 서버 등록 (Claude / Codex)", command=self.install_mcp)
        if IS_WIN:
            m.add_checkbutton(label="Windows 시작 시 실행", variable=self.v_autostart, command=self._on_autostart)
        m.add_command(label="설정 파일 위치 열기", command=self._open_config_dir)
        m.add_separator()
        m.add_command(label="종료", command=self.quit)
        self.menu = m

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def toggle_topmost(self):
        self.vars["topmost"].set(not self.vars["topmost"].get())
        self.toggle_topmost_var()

    def toggle_topmost_var(self):
        self._on_flags()
        self._update_pin()

    def _on_flags(self):
        self.cfg["topmost"] = self.vars["topmost"].get()
        self.cfg["frameless"] = self.vars["frameless"].get()
        self.cfg["alpha"] = float(self.v_alpha.get())
        self.cfg["geometry"] = self.root.geometry()
        save_config(self.cfg)
        self._apply_window_flags()

    def _on_opts(self):
        for k in ("show_claude", "show_codex", "claude_api"):
            self.cfg[k] = self.vars[k].get()
        self.cfg["refresh_sec"] = int(self.v_refresh.get())
        save_config(self.cfg)
        self._layout_key = None
        self.refresh_now()

    def _on_theme(self):
        self.cfg["theme"] = self.v_theme.get()
        save_config(self.cfg)
        for w in (self.outer, self.header, self.body, self.footer, self.grip, self.lbl_title,
                  self.btn_close, self.btn_refresh, self.btn_pin):
            w.configure(bg=self.t["bg"])
        self.root.configure(bg=self.t["line"])
        self.lbl_title.configure(fg=self.t["fg"])
        for w in (self.footer, self.grip, self.btn_close, self.btn_refresh):
            w.configure(fg=self.t["dim"])
        self._update_pin()
        self._layout_key = None
        self.render()

    def _on_autostart(self):
        try:
            set_autostart(self.v_autostart.get())
        except Exception as e:
            messagebox.showerror(APP, "자동 실행 설정 실패: %r" % e)
        self.v_autostart.set(autostart_enabled())

    def _open_config_dir(self):
        d = os.path.dirname(config_path())
        if IS_WIN:
            os.startfile(d)
        else:
            messagebox.showinfo(APP, d)

    def install_mcp(self):
        try:
            import install_mcp
            lines = install_mcp.main()
            messagebox.showinfo(APP, "MCP 서버 등록 결과\n\n" + "\n".join("• " + l for l in lines) +
                                "\n\nClaude Code / Codex 를 새로 열면 'get_token_usage' 도구를 쓸 수 있습니다.")
        except Exception as e:
            messagebox.showerror(APP, "등록 실패: %r" % e)

    # ------------------------------------------------------------ data
    def _worker(self):
        while True:
            try:
                snap = self.monitor.snapshot(
                    use_claude_api=self.cfg.get("claude_api", True),
                    api_interval=int(self.cfg.get("claude_api_interval", 90)),
                    claude_block_limit=int(self.cfg.get("claude_block_limit", 0) or 0),
                    claude_dirs=self.cfg.get("claude_dirs") or [],
                    show_idle_claude=bool(self.cfg.get("show_idle_claude")))
            except Exception as e:
                snap = {"generated_at": time.time(), "error": repr(e)}
            self._pending = snap
            self._wake.wait(max(5, int(self.cfg.get("refresh_sec", 30))))
            self._wake.clear()

    def refresh_now(self):
        self.footer.configure(text="새로고침 중…")
        self._wake.set()

    def _poll(self):
        if self._pending is not None:
            self.snap, self._pending = self._pending, None
            self.render()
        self.root.after(300, self._poll)

    def _tick(self):
        if self.vars["topmost"].get():
            try:
                self.root.attributes("-topmost", True)
                self.root.lift()
            except tk.TclError:
                pass
        if self.snap:
            self.render()
        self.root.after(20000, self._tick)

    # ------------------------------------------------------------ layout / scaling
    def _sections(self):
        out = []
        if not self.snap:
            return out
        if self.vars["show_claude"].get():
            accs = self.snap.get("claude_accounts") or []
            if not accs:
                out.append(("claude", "Claude", {"available": False}))
            for a in accs:
                label = "Claude" if len(accs) == 1 and a.get("account") == "기본" else "Claude · " + a.get("account", "?")
                a["_short"] = "C" if len(accs) == 1 else a.get("account", "C")[:4]
                out.append(("claude", label, a))
        if self.vars["show_codex"].get():
            s = self.snap.get("codex") or {}
            s["_short"] = "X"
            out.append(("codex", "Codex", s))
        return out

    def _rows_needed(self, compact):
        rows = 1.3  # header
        for _, _, s in self._sections():
            n = max(1, len(s.get("limits") or []))
            rows += (n + 0.4) if compact else (n + 2.6)
        return rows + (0 if compact else 1)

    def _on_configure(self, e):
        if e.widget is self.root:
            self._rescale()

    def _rescale(self):
        w = max(1, self.root.winfo_width())
        h = max(1, self.root.winfo_height())
        px_per_pt = self.dpi / 72.0
        full = h / (self._rows_needed(False) * 1.85 * px_per_pt)
        compact = full < 7.5
        fit = h / (self._rows_needed(compact) * 1.85 * px_per_pt)
        base = max(6.0, min(26.0, w / (30.0 * px_per_pt) * 1.05, fit))
        size = int(round(base))
        if size != self.f_base:
            self.f_base = size
            self.f_main.configure(size=size)
            self.f_bold.configure(size=size)
            self.f_title.configure(size=size + 1)
            self.f_small.configure(size=max(6, size - 1))
            for c in self.body.winfo_children():
                for cv in getattr(c, "_bars", []):
                    cv.configure(height=self._bar_h())
        if compact != self._compact:
            self._compact = compact
            self._layout_key = None
            if compact:
                self.footer.pack_forget()
            else:
                self.footer.pack(fill="x", padx=8, pady=(0, 4))
            self.render()
        self.grip.lift()

    def _bar_h(self):
        return max(4, int(self.f_main.metrics("linespace") * 0.45))

    # ------------------------------------------------------------ render
    def render(self):
        if self._compact is None:
            self._rescale()
        t = self.t
        now = time.time()
        for c in self.body.winfo_children():
            c.destroy()
        if self.snap is None:
            return
        if self.snap.get("error"):
            tk.Label(self.body, text=self.snap["error"], font=self.f_small, bg=t["bg"], fg=BAD,
                     wraplength=self.root.winfo_width() - 20, justify="left").pack(anchor="w")
        secs = self._sections()
        for i, (key, name, s) in enumerate(secs):
            self._render_section(key, name, s, now, first=(i == 0))
        if not secs:
            tk.Label(self.body, text="표시할 항목이 없습니다 (우클릭 → 표시)", font=self.f_small,
                     bg=t["bg"], fg=t["dim"]).pack(anchor="w")
        self.footer.configure(text="업데이트 %s · 우클릭 = 설정" %
                              time.strftime("%H:%M:%S", time.localtime(self.snap["generated_at"])))
        for c in self.body.winfo_children():
            self._bind_drag(c)
        self.grip.lift()
        self._rescale()

    def _render_section(self, key, name, s, now, first):
        t = self.t
        compact = self._compact
        sec = tk.Frame(self.body, bg=t["bg"])
        sec.pack(fill="x", pady=(0 if first else (2 if compact else 6), 0))
        sec._bars = []
        sec.columnconfigure(1, weight=1)
        row = 0
        if not compact:
            top = tk.Frame(sec, bg=t["bg"])
            top.grid(row=row, column=0, columnspan=4, sticky="ew")
            tk.Label(top, text="●", font=self.f_main, bg=t["bg"], fg=ACCENT[key]).pack(side="left")
            title = name + (" · " + s["plan"].capitalize() if s.get("plan") else "")
            tk.Label(top, text=title, font=self.f_bold, bg=t["bg"], fg=t["fg"]).pack(side="left", padx=(3, 0))
            tk.Label(top, text=fmt_ago(s.get("last_activity"), now), font=self.f_small,
                     bg=t["bg"], fg=t["dim"]).pack(side="right")
            row += 1

        limits = s.get("limits") or []
        for lim in limits:
            label = lim["name"]
            if compact:
                label = s.get("_short", "") + " " + label
            tk.Label(sec, text=label, font=self.f_small, bg=t["bg"],
                     fg=ACCENT[key] if compact else t["dim"], anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 6))
            cv = tk.Canvas(sec, height=self._bar_h(), bg=t["bg"], highlightthickness=0, bd=0)
            cv.grid(row=row, column=1, sticky="ew")
            pct = float(lim["used_percent"])
            cv.bind("<Configure>", lambda e, c=cv, p=pct: self._draw_bar(c, p))
            sec._bars.append(cv)
            tk.Label(sec, text="%d%%" % round(pct), font=self.f_bold, bg=t["bg"], fg=bar_color(pct),
                     width=4, anchor="e").grid(row=row, column=2, sticky="e")
            r = lim.get("resets_at")
            tk.Label(sec, text=(fmt_duration(r - now) if r else "-"), font=self.f_small, bg=t["bg"],
                     fg=t["dim"], anchor="e").grid(row=row, column=3, sticky="e", padx=(6, 0))
            row += 1

        if limits and s.get("limits_note") and not compact:
            tk.Label(sec, text=s["limits_note"], font=self.f_small, bg=t["bg"], fg=t["dim"], anchor="w",
                     justify="left", wraplength=max(80, self.root.winfo_width() - 24)).grid(
                row=row, column=0, columnspan=4, sticky="w")
            row += 1
        if s.get("error") or not s.get("available", True):
            msg = s.get("error") or ("Claude Code 기록 폴더 없음" if key == "claude" else "~/.codex 폴더 없음")
            tk.Label(sec, text=msg, font=self.f_small, bg=t["bg"], fg=t["dim"], anchor="w").grid(
                row=row, column=0, columnspan=4, sticky="w")
            return
        if not limits:
            err = s.get("limits_error") or "한도 정보 없음"
            if compact:
                err = s.get("_short", "") + " 오늘 " + fmt_tokens((s.get("today") or {}).get("total"))
            tk.Label(sec, text=err, font=self.f_small, bg=t["bg"], fg=t["dim"], anchor="w", justify="left",
                     wraplength=max(80, self.root.winfo_width() - 24)).grid(
                row=row, column=0, columnspan=4, sticky="w")
            row += 1
        if compact:
            return
        today = s.get("today") or {}
        week = s.get("week") or {}
        parts = ["오늘 " + fmt_tokens(today.get("total")), "7일 " + fmt_tokens(week.get("total"))]
        if key == "claude" and s.get("block"):
            parts.insert(1, "블록 " + fmt_tokens(s["block"]["tokens"]["total"]))
        if key == "claude":
            sub = "입력 %s · 출력 %s · 캐시 %s" % (
                fmt_tokens(today.get("input")), fmt_tokens(today.get("output")),
                fmt_tokens(today.get("cache_read", 0) + today.get("cache_write", 0)))
        else:
            sub = "입력 %s · 캐시 %s · 출력 %s" % (
                fmt_tokens(today.get("input")), fmt_tokens(today.get("cached")),
                fmt_tokens(today.get("output")))
        tk.Label(sec, text="  ·  ".join(parts), font=self.f_main, bg=t["bg"], fg=t["fg"], anchor="w").grid(
            row=row, column=0, columnspan=4, sticky="w")
        tk.Label(sec, text=sub, font=self.f_small, bg=t["bg"], fg=t["dim"], anchor="w").grid(
            row=row + 1, column=0, columnspan=4, sticky="w")

    def _draw_bar(self, cv, pct):
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 4:
            return
        cv.create_rectangle(0, 0, w, h, fill=self.t["track"], width=0)
        fw = int(w * max(0.0, min(100.0, pct)) / 100.0)
        if fw > 0:
            cv.create_rectangle(0, 0, fw, h, fill=bar_color(pct), width=0)

    # ------------------------------------------------------------ run
    def quit(self):
        self.cfg["geometry"] = self.root.geometry()
        save_config(self.cfg)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        sys.exit(0)
    App().run()
