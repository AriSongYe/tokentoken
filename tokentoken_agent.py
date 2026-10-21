"""
TokenToken agent - shares this machine's Claude Code / Codex usage over HTTP so a
TokenToken widget on another PC can show it (e.g. Claude Code inside a VM, widget on
the Windows host). Standard library only.

    python3 tokentoken_agent.py                      # run (port 8787, prints the token)
    python3 tokentoken_agent.py --install-service    # run in background via systemd --user
    python3 tokentoken_agent.py --uninstall-service
    python3 tokentoken_agent.py --show-token

The Claude limit % is read with this machine's own Claude Code login, which Claude
Code keeps refreshing while you use it here, so the numbers stay current.

Endpoints:  GET /health (no auth)   GET /snapshot (Authorization: Bearer <token>)
"""
import argparse
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from usage_core import UsageMonitor  # noqa: E402

PROTOCOL = 1
SERVICE = "tokentoken-agent"


def conf_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    if os.name == "nt":
        base = os.environ.get("APPDATA") or base
    d = os.path.join(base, "TokenToken")
    os.makedirs(d, exist_ok=True)
    return d


def token_file():
    return os.path.join(conf_dir(), "agent_token")


def load_or_create_token():
    p = token_file()
    try:
        with open(p, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(18)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    return tok


def guess_ip():
    """Best-guess LAN address (no packets are sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "<이 PC의 IP>"


class Agent:
    def __init__(self, name, api_interval, ttl=10):
        self.name = name
        self.api_interval = api_interval
        self.ttl = ttl
        self.monitor = UsageMonitor()
        self.lock = threading.Lock()
        self.cache, self.cache_at = None, 0.0

    def snapshot(self):
        with self.lock:
            now = time.time()
            if self.cache is None or now - self.cache_at > self.ttl:
                snap = self.monitor.snapshot(use_claude_api=True, api_interval=self.api_interval)
                snap.pop("codex_remote", None)
                snap.update({"agent": self.name, "protocol": PROTOCOL})
                self.cache, self.cache_at = snap, now
            return self.cache


def make_handler(agent, token, verbose):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TokenTokenAgent/%d" % PROTOCOL

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            given = ""
            h = self.headers.get("Authorization") or ""
            if h.lower().startswith("bearer "):
                given = h[7:].strip()
            if not given:
                given = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
            return bool(given) and hmac.compare_digest(given.encode(), token.encode())

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path in ("/", "/health"):
                return self._send(200, {"ok": True, "agent": agent.name, "protocol": PROTOCOL})
            if path == "/snapshot":
                if not self._authorized():
                    return self._send(401, {"error": "unauthorized"})
                try:
                    return self._send(200, agent.snapshot())
                except Exception as e:  # never kill the server over one bad read
                    return self._send(500, {"error": repr(e)})
            self._send(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            if verbose:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return Handler


# ------------------------------------------------------------------ systemd --user
def unit_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "systemd", "user", SERVICE + ".service")


def install_service(args):
    exec_line = '%s %s --host %s --port %d --name "%s" --api-interval %d' % (
        sys.executable, os.path.abspath(__file__), args.host, args.port, args.name, args.api_interval)
    unit = """[Unit]
Description=TokenToken agent (shares Claude Code / Codex usage)
After=network-online.target

[Service]
ExecStart=%s
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
""" % exec_line
    os.makedirs(os.path.dirname(unit_path()), exist_ok=True)
    with open(unit_path(), "w", encoding="utf-8") as f:
        f.write(unit)
    load_or_create_token()
    for cmd in (["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", SERVICE],
                ["systemctl", "--user", "restart", SERVICE]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("실패: %s\n%s" % (" ".join(cmd), (r.stderr or r.stdout).strip()))
            return 1
    print("서비스 등록 완료: %s" % unit_path())
    print("로그아웃 상태에서도 계속 돌게 하려면 한 번만:  sudo loginctl enable-linger %s" % os.environ.get("USER", "$USER"))
    print_connect_info(args)
    return 0


def uninstall_service():
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], capture_output=True)
    try:
        os.remove(unit_path())
    except OSError:
        pass
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("서비스를 해제했습니다.")
    return 0


def print_connect_info(args):
    print("")
    print("  Windows 위젯에서:  우클릭 → 원격 PC 연결…")
    print("    주소  http://%s:%d" % (guess_ip(), args.port))
    print("    토큰  %s" % load_or_create_token())
    print("    이름  %s" % args.name)
    print("")


def main():
    ap = argparse.ArgumentParser(description="TokenToken agent")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--name", default=socket.gethostname().split(".")[0][:12] or "remote",
                    help="label shown in the widget (default: hostname)")
    ap.add_argument("--api-interval", type=int, default=90, help="seconds between Claude limit API calls")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--show-token", action="store_true")
    ap.add_argument("--install-service", action="store_true")
    ap.add_argument("--uninstall-service", action="store_true")
    args = ap.parse_args()

    if args.show_token:
        print(load_or_create_token())
        return 0
    if args.install_service:
        return install_service(args)
    if args.uninstall_service:
        return uninstall_service()

    token = load_or_create_token()
    agent = Agent(args.name, args.api_interval)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(agent, token, args.verbose))
    srv.daemon_threads = True
    print("TokenToken agent '%s' 실행 중 - %s:%d" % (args.name, args.host, args.port), flush=True)
    print_connect_info(args)
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
