"""
TokenToken - Claude / Codex token usage monitor (always-on-top, resizable widget).

    pythonw tokenmon.pyw

Drag anywhere to move, drag the ◢ corner to resize, right-click for options.
Click + (bottom right) to add a to-do; click ☐ to complete, ✕ to remove, double-click to edit.
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
    "geometry": "340x460+60+60",
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
    "show_todos": True,        # to-do / goal list under the usage panel
    "show_remaining": True,    # show limits as % remaining (100 - used) instead of % used
    "show_local": True,        # this PC's own Claude Code / Codex logs
    "remote_agents": [],       # [{"name": "vm", "url": "http://192.168.0.63:8787", "token": "..."}]
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


def todos_path():
    return os.path.join(os.path.dirname(config_path()), "todos.json")


def load_todos():
    try:
        with open(todos_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and str(d.get("text", "")).strip()]
    except Exception:
        return []


def save_todos(items):
    try:
        tmp = todos_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, todos_path())
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


def bar_color(used_pct):
    """Color by how much of the limit is used (green -> amber -> red)."""
    return OK if used_pct < 60 else WARN if used_pct < 85 else BAD


class App:
    def __init__(self):
        self.cfg = load_config()
        self.monitor = UsageMonitor()
        self.snap = None
        self._pending = None
        self._wake = threading.Event()
        self._compact = None
        self._layout_key = None
        self.todos = load_todos()
        self._edit_idx = None
        self._todo_w = None

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
        self.f_strike = tkfont.Font(family=fam, size=9, overstrike=1)
        self.f_base = None

        self.vars = {k: tk.BooleanVar(value=bool(self.cfg[k]))
                     for k in ("topmost", "frameless", "show_claude", "show_codex", "claude_api",
                               "show_todos", "show_remaining", "show_local")}
        self.v_alpha = tk.DoubleVar(value=self.cfg["alpha"])
        self.v_refresh = tk.IntVar(value=self.cfg["refresh_sec"])
        self.v_theme = tk.StringVar(value=self.cfg.get("theme", "dark"))
        self.v_autostart = tk.BooleanVar(value=autostart_enabled())

        self._build_shell()
        self._apply_window_flags(initial=True)
        self._build_menu()

        self.root.bind("<Configure>", self._on_configure)
        self.root.bind_all("<Button-3>", self._popup)
        self.root.bind_all("<MouseWheel>", self._todo_wheel)
        self.root.bind_all("<Button-4>", self._todo_wheel)
        self.root.bind_all("<Button-5>", self._todo_wheel)
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

        # footer row: status text on the left, "+" (add to-do) on the right
        self.foot = tk.Frame(self.outer, bg=t["bg"])
        self.footer = tk.Label(self.foot, text="불러오는 중…", font=self.f_small,
                               bg=t["bg"], fg=t["dim"], anchor="w")
        self.footer.pack(side="left", fill="x", expand=True)
        self.btn_add = tk.Label(self.foot, text="＋", font=self.f_title, bg=t["bg"], fg=t["dim"],
                                cursor="hand2")
        self.btn_add.pack(side="right")
        self.btn_add.bind("<Button-1>", lambda e: self.todo_add_start())
        self.btn_add.bind("<Enter>", lambda e: self.btn_add.configure(fg=ACCENT["claude"]))
        self.btn_add.bind("<Leave>", lambda e: self.btn_add.configure(fg=self.t["dim"]))

        self.todo = tk.Frame(self.outer, bg=t["bg"])
        self._build_todo()
        self._pack_lower()

        self.grip = tk.Label(self.outer, text="◢", font=self.f_small, bg=t["bg"],
                             fg=t["dim"], cursor="size_nw_se" if IS_WIN else "bottom_right_corner")
        self.grip.bind("<ButtonPress-1>", self._grip_start)
        self.grip.bind("<B1-Motion>", self._grip_move)
        self.grip.bind("<ButtonRelease-1>", lambda e: self._save_geometry())
        self._nodrag = {self.btn_close, self.btn_refresh, self.btn_pin, self.grip,
                        self.btn_add, self.todo_entry, self.todo_cv}
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
        m.add_command(label="원격 PC(VM) 연결…", command=self.remote_dialog)
        m.add_checkbutton(label="이 PC 기록 표시", variable=self.vars["show_local"], command=self._on_opts)
        m.add_checkbutton(label="Claude 표시", variable=self.vars["show_claude"], command=self._on_opts)
        m.add_checkbutton(label="Codex 표시", variable=self.vars["show_codex"], command=self._on_opts)
        m.add_checkbutton(label="Claude 구독 한도(%) 조회", variable=self.vars["claude_api"], command=self._on_opts)
        m.add_checkbutton(label="남은 한도(%)로 표시", variable=self.vars["show_remaining"], command=self._on_opts)
        ref = tk.Menu(m, tearoff=0)
        for s in (10, 30, 60, 120, 300):
            ref.add_radiobutton(label="%d초" % s, value=s, variable=self.v_refresh, command=self._on_opts)
        m.add_cascade(label="새로고침 주기", menu=ref)
        m.add_separator()
        m.add_checkbutton(label="할 일 목록 표시", variable=self.vars["show_todos"], command=self._on_todo_visible)
        m.add_command(label="할 일 추가", command=self.todo_add_start)
        m.add_command(label="완료한 할 일 지우기", command=self.todo_clear_done)
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
        for k in ("show_claude", "show_codex", "claude_api", "show_remaining", "show_local"):
            self.cfg[k] = self.vars[k].get()
        self.cfg["refresh_sec"] = int(self.v_refresh.get())
        save_config(self.cfg)
        self._layout_key = None
        self.refresh_now()

    def _on_theme(self):
        self.cfg["theme"] = self.v_theme.get()
        save_config(self.cfg)
        for w in (self.outer, self.header, self.body, self.footer, self.grip, self.lbl_title,
                  self.btn_close, self.btn_refresh, self.btn_pin, self.foot, self.btn_add,
                  self.todo, self.todo_head, self.lbl_todo, self.todo_entry_row, self.todo_cv,
                  self.todo_list):
            w.configure(bg=self.t["bg"])
        self.todo_sep.configure(bg=self.t["line"])
        self.lbl_todo.configure(fg=self.t["fg"])
        self.todo_entry.configure(bg=self.t["panel"], fg=self.t["fg"], insertbackground=self.t["fg"],
                                  highlightbackground=self.t["line"])
        self.root.configure(bg=self.t["line"])
        self.lbl_title.configure(fg=self.t["fg"])
        for w in (self.footer, self.grip, self.btn_close, self.btn_refresh, self.btn_add):
            w.configure(fg=self.t["dim"])
        self._update_pin()
        self._render_todos()
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

    # ------------------------------------------------------------ remote agent dialog
    def remote_dialog(self):
        """Connect to a TokenToken agent on another machine (tokentoken_agent.py)."""
        t = self.t
        agents = self.cfg.get("remote_agents") or []
        cur = agents[0] if agents else {}
        d = tk.Toplevel(self.root)
        d.title("원격 PC 연결")
        d.configure(bg=t["bg"])
        d.attributes("-topmost", True)
        d.resizable(False, False)
        d.transient(self.root)
        tk.Label(d, text="VM / 다른 PC에서 tokentoken_agent.py 를 실행하면 나오는\n주소와 토큰을 입력하세요.",
                 font=self.f_small, bg=t["bg"], fg=t["dim"], justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 6))
        fields = {}
        for i, (k, label, val) in enumerate((
                ("url", "주소", cur.get("url") or "http://192.168.0.63:8787"),
                ("token", "토큰", cur.get("token") or ""),
                ("name", "이름", cur.get("name") or "vm"))):
            tk.Label(d, text=label, font=self.f_main, bg=t["bg"], fg=t["fg"]).grid(
                row=i + 1, column=0, sticky="w", padx=(12, 6), pady=3)
            e = tk.Entry(d, font=self.f_main, width=34, bg=t["panel"], fg=t["fg"], insertbackground=t["fg"],
                         relief="flat", highlightthickness=1, highlightbackground=t["line"],
                         highlightcolor=ACCENT["claude"])
            e.insert(0, val)
            e.grid(row=i + 1, column=1, sticky="ew", padx=(0, 12), pady=3, ipady=2)
            fields[k] = e
        status = tk.Label(d, text="", font=self.f_small, bg=t["bg"], fg=t["dim"], anchor="w", justify="left",
                          wraplength=320)
        status.grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 0))
        if len(agents) > 1:
            status.configure(text="원격 %d개 중 첫 번째만 여기서 편집합니다 (나머지는 config.json)." % len(agents))

        def values():
            return {k: fields[k].get().strip() for k in fields}

        def test():
            import usage_core
            v = values()
            if not v["url"]:
                return
            status.configure(text="연결 중…", fg=t["dim"])
            d.update_idletasks()
            src = usage_core.RemoteSource(v)
            accs, codex = src.fetch(time.time())
            if src.err:
                status.configure(text="실패: " + src.err, fg=BAD)
            else:
                names = [a.get("account") for a in accs] + (["Codex"] if codex else [])
                status.configure(text="성공: " + (", ".join(names) or "데이터 없음 (아직 사용 기록이 없을 수 있음)"),
                                 fg=OK)

        def save():
            v = values()
            rest = agents[1:]
            self.cfg["remote_agents"] = ([v] if v["url"] else []) + rest
            save_config(self.cfg)
            d.destroy()
            self._layout_key = None
            self.refresh_now()

        def remove():
            fields["url"].delete(0, "end")
            save()

        bar = tk.Frame(d, bg=t["bg"])
        bar.grid(row=5, column=0, columnspan=2, sticky="e", padx=12, pady=10)
        for text, cmd in (("연결 테스트", test), ("연결 해제", remove), ("취소", d.destroy), ("저장", save)):
            tk.Button(bar, text=text, command=cmd, font=self.f_small, relief="flat", bg=t["panel"], fg=t["fg"],
                      activebackground=t["track"], activeforeground=t["fg"], padx=8).pack(side="left", padx=(6, 0))
        d.bind("<Return>", lambda e: save())
        d.bind("<Escape>", lambda e: d.destroy())
        d.update_idletasks()
        x = self.root.winfo_rootx() + 20
        y = self.root.winfo_rooty() + 40
        d.geometry("+%d+%d" % (x, y))
        try:
            d.focus_force()
            fields["token" if cur.get("url") else "url"].focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ data
    def _worker(self):
        while True:
            try:
                snap = self.monitor.snapshot(
                    use_claude_api=self.cfg.get("claude_api", True),
                    api_interval=int(self.cfg.get("claude_api_interval", 90)),
                    claude_block_limit=int(self.cfg.get("claude_block_limit", 0) or 0),
                    claude_dirs=self.cfg.get("claude_dirs") or [],
                    show_idle_claude=bool(self.cfg.get("show_idle_claude")),
                    remote_agents=self.cfg.get("remote_agents") or [],
                    include_local=self.cfg.get("show_local", True) is not False)
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
            s = self.snap.get("codex")
            if s is not None:
                s["_short"] = "X"
                out.append(("codex", "Codex", s))
            for c in self.snap.get("codex_remote") or []:
                c["_short"] = "X" + c.get("remote", "")[:3]
                out.append(("codex", "Codex · " + c.get("remote", "?"), c))
        return out

    def _rows_needed(self, compact):
        rows = 1.3  # header
        for _, _, s in self._sections():
            n = max(1, len(s.get("limits") or []))
            rows += (n + 0.4) if compact else (n + 2.6)
        if not compact and self.vars["show_todos"].get():
            rows += 3  # to-do header + at least one visible item
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
            self.f_strike.configure(size=size)
            self._todo_w = None
            for c in self.body.winfo_children():
                for cv in getattr(c, "_bars", []):
                    cv.configure(height=self._bar_h())
        if compact != self._compact:
            self._compact = compact
            self._layout_key = None
            self._pack_lower()
            self.render()
        if w != self._todo_w and not compact:
            self._todo_w = w
            self._render_todos()
        self.grip.lift()

    def _bar_h(self):
        return max(4, int(self.f_main.metrics("linespace") * 0.45))

    # ------------------------------------------------------------ to-do list
    def _pack_lower(self):
        """(Re)pack footer + to-do panel in order; both are hidden in compact mode."""
        self.foot.pack_forget()
        self.todo.pack_forget()
        show = bool(self.vars["show_todos"].get())
        self.body.pack_configure(expand=not show)
        if self._compact:
            return
        self.foot.pack(fill="x", padx=8, pady=(2, 2))
        if show:
            self.todo.pack(fill="both", expand=True, padx=8, pady=(0, 14))

    def _build_todo(self):
        t = self.t
        self.todo_head = tk.Frame(self.todo, bg=t["bg"])
        self.todo_head.pack(fill="x")
        self.todo_sep = tk.Frame(self.todo_head, bg=t["line"], height=1)
        self.todo_sep.pack(fill="x", pady=(2, 4))
        self.lbl_todo = tk.Label(self.todo_head, text="할 일", font=self.f_bold, bg=t["bg"], fg=t["fg"],
                                 anchor="w")
        self.lbl_todo.pack(side="left")

        self.todo_entry_row = tk.Frame(self.todo, bg=t["bg"])  # packed only while adding / editing
        self.todo_entry = tk.Entry(self.todo_entry_row, font=self.f_main, bg=t["panel"], fg=t["fg"],
                                   insertbackground=t["fg"], relief="flat", highlightthickness=1,
                                   highlightbackground=t["line"], highlightcolor=ACCENT["claude"])
        self.todo_entry.pack(fill="x", expand=True, ipady=3)
        self.todo_entry.bind("<Return>", lambda e: self._todo_commit())
        self.todo_entry.bind("<KP_Enter>", lambda e: self._todo_commit())
        self.todo_entry.bind("<Escape>", lambda e: self._todo_cancel())

        self.todo_cv = tk.Canvas(self.todo, bg=t["bg"], highlightthickness=0, bd=0, yscrollincrement=12)
        self.todo_cv.pack(fill="both", expand=True, pady=(4, 0))
        self.todo_list = tk.Frame(self.todo_cv, bg=t["bg"])
        self._todo_win = self.todo_cv.create_window(0, 0, window=self.todo_list, anchor="nw")
        self.todo_list.bind("<Configure>", lambda e: self._todo_sync_scroll())
        self.todo_cv.bind("<Configure>", lambda e: (
            self.todo_cv.itemconfigure(self._todo_win, width=e.width), self._todo_sync_scroll()))

    def _todo_sync_scroll(self):
        cv = self.todo_cv
        cv.configure(scrollregion=(0, 0, cv.winfo_width(), max(cv.winfo_height(),
                                                               self.todo_list.winfo_reqheight())))

    def _todo_wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is None or not str(w).startswith(str(self.todo_cv)):
            return
        if self.todo_list.winfo_reqheight() <= self.todo_cv.winfo_height():
            return
        up = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
        self.todo_cv.yview_scroll(-3 if up else 3, "units")

    def _render_todos(self):
        t = self.t
        for c in self.todo_list.winfo_children():
            c.destroy()
        done = sum(1 for d in self.todos if d.get("done"))
        self.lbl_todo.configure(text=("할 일  %d/%d" % (done, len(self.todos))) if self.todos else "할 일")
        if not self.todos and not self.todo_entry_row.winfo_ismapped():
            tk.Label(self.todo_list, text="＋ 를 눌러 목표를 추가하세요", font=self.f_small,
                     bg=t["bg"], fg=t["dim"], anchor="w").pack(fill="x", pady=2)
        wrap = max(60, self.root.winfo_width() - 16 - 2 * self.f_main.measure("☐✕") - 30)
        for i, d in enumerate(self.todos):
            is_done = bool(d.get("done"))
            row = tk.Frame(self.todo_list, bg=t["panel"])
            row.pack(fill="x", pady=(0, 3))
            chk = tk.Label(row, text="☑" if is_done else "☐", font=self.f_main, bg=t["panel"],
                           fg=OK if is_done else t["dim"], cursor="hand2")
            chk.pack(side="left", anchor="n", padx=(6, 4), pady=3)
            chk.bind("<Button-1>", lambda e, i=i: self._todo_toggle(i))
            x = tk.Label(row, text="✕", font=self.f_small, bg=t["panel"], fg=t["dim"], cursor="hand2")
            x.pack(side="right", anchor="n", padx=(4, 6), pady=4)
            x.bind("<Button-1>", lambda e, i=i: self._todo_delete(i))
            x.bind("<Enter>", lambda e, x=x: x.configure(fg=BAD))
            x.bind("<Leave>", lambda e, x=x: x.configure(fg=self.t["dim"]))
            txt = tk.Label(row, text=d["text"], font=self.f_strike if is_done else self.f_main,
                           bg=t["panel"], fg=t["dim"] if is_done else t["fg"], anchor="w",
                           justify="left", wraplength=wrap)
            txt.pack(side="left", fill="x", expand=True, pady=3)
            txt.bind("<Double-Button-1>", lambda e, i=i: self.todo_add_start(i))
        self.todo_cv.yview_moveto(min(1.0, self.todo_cv.yview()[0]))

    def _todo_save(self):
        save_todos(self.todos)
        self._render_todos()

    def _todo_toggle(self, i):
        if 0 <= i < len(self.todos):
            self.todos[i]["done"] = not self.todos[i].get("done")
            self.todos[i]["done_at"] = time.time() if self.todos[i]["done"] else None
            self._todo_save()

    def _todo_delete(self, i):
        if 0 <= i < len(self.todos):
            del self.todos[i]
            if self._edit_idx is not None:
                self._todo_cancel()
            self._todo_save()

    def todo_clear_done(self):
        self.todos = [d for d in self.todos if not d.get("done")]
        self._todo_save()

    def todo_add_start(self, idx=None):
        """Open the input row. idx=None adds a new item, otherwise edits that item."""
        if not self.vars["show_todos"].get():
            self.vars["show_todos"].set(True)
            self._on_todo_visible()
        if idx is None and self.todo_entry_row.winfo_ismapped() and self._edit_idx is None \
                and not self.todo_entry.get().strip():
            self._todo_cancel()  # "+" again on an empty input closes it
            return
        self._edit_idx = idx
        self.todo_entry.delete(0, "end")
        if idx is not None and 0 <= idx < len(self.todos):
            self.todo_entry.insert(0, self.todos[idx]["text"])
            self.todo_entry.select_range(0, "end")
        if not self.todo_entry_row.winfo_ismapped():
            self.todo_entry_row.pack(fill="x", pady=(2, 0), before=self.todo_cv)
        self._render_todos()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.todo_entry.focus_set()

    def _todo_commit(self):
        text = self.todo_entry.get().strip()
        editing = self._edit_idx is not None
        if text:
            if editing and 0 <= self._edit_idx < len(self.todos):
                self.todos[self._edit_idx]["text"] = text
            elif not editing:
                self.todos.append({"text": text, "done": False, "created": time.time()})
        if editing or not text:
            self._todo_cancel()
        else:
            self.todo_entry.delete(0, "end")  # stay open for quick multi-add
        self._todo_save()
        if text and not editing:
            self.root.update_idletasks()
            self.todo_cv.yview_moveto(1.0)

    def _todo_cancel(self):
        self._edit_idx = None
        self.todo_entry.delete(0, "end")
        self.todo_entry_row.pack_forget()
        self._render_todos()

    def _on_todo_visible(self):
        self.cfg["show_todos"] = self.vars["show_todos"].get()
        save_config(self.cfg)
        self._compact = None   # force re-layout
        self._layout_key = None
        self._rescale()

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
            used = float(lim["used_percent"])
            # remaining mode: bar/number show what's left (100 - used); color still follows usage
            pct = max(0.0, 100.0 - used) if self.vars["show_remaining"].get() else used
            cv.bind("<Configure>", lambda e, c=cv, p=pct, u=used: self._draw_bar(c, p, u))
            sec._bars.append(cv)
            tk.Label(sec, text="%d%%" % round(pct), font=self.f_bold, bg=t["bg"], fg=bar_color(used),
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
            tk.Label(sec, text=msg, font=self.f_small, bg=t["bg"], fg=BAD if s.get("remote") else t["dim"],
                     anchor="w", justify="left", wraplength=max(80, self.root.winfo_width() - 24)).grid(
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

    def _draw_bar(self, cv, pct, used):
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 4:
            return
        cv.create_rectangle(0, 0, w, h, fill=self.t["track"], width=0)
        fw = int(w * max(0.0, min(100.0, pct)) / 100.0)
        if fw > 0:
            cv.create_rectangle(0, 0, fw, h, fill=bar_color(used), width=0)

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
