"""
Register the TokenToken MCP server with Claude Code, Codex CLI and Claude Desktop.

    python install_mcp.py            # register everywhere it can
    python install_mcp.py --remove   # unregister
"""
import json
import os
import re
import shutil
import subprocess
import sys

NAME = "tokentoken"
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "tokentoken_mcp.py")


def console_python():
    exe = sys.executable or "python"
    base = os.path.basename(exe).lower()
    if base == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, repr(e)


def _backup(path):
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak_tokentoken")


def _merge_json_servers(path, remove=False):
    data = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    servers = data.setdefault("mcpServers", {})
    if remove:
        servers.pop(NAME, None)
    else:
        servers[NAME] = {"type": "stdio", "command": console_python(), "args": ["-I", SERVER], "env": {}}
    _backup(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def claude_code(remove=False):
    exe = shutil.which("claude")
    if exe:
        _run([exe, "mcp", "remove", "--scope", "user", NAME])
        if remove:
            return "Claude Code: 등록 해제 완료"
        code, out = _run([exe, "mcp", "add", "--scope", "user", NAME, "--", console_python(), "-I", SERVER])
        if code == 0:
            return "Claude Code: 등록 완료 (claude mcp add --scope user)"
        msg = "Claude Code CLI 등록 실패: %s" % out[-200:]
    else:
        msg = "Claude Code CLI(claude)가 PATH에 없음"
    path = os.path.join(os.path.expanduser("~"), ".claude.json")
    if os.path.isfile(path):
        try:
            _merge_json_servers(path, remove)
            return "Claude Code: ~/.claude.json 에 직접 %s (%s)" % ("해제" if remove else "등록", msg)
        except Exception as e:
            return "Claude Code: 실패 - %s / %r" % (msg, e)
    return "Claude Code: 건너뜀 - " + msg


def codex(remove=False):
    exe = shutil.which("codex")
    if exe:
        _run([exe, "mcp", "remove", NAME])
        if remove:
            return "Codex: 등록 해제 완료"
        code, out = _run([exe, "mcp", "add", NAME, "--", console_python(), "-I", SERVER])
        if code == 0:
            return "Codex: 등록 완료 (codex mcp add)"
    home = os.path.abspath(os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex"))
    path = os.path.join(home, "config.toml")
    text = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    pattern = re.compile(r"(?ms)^\[mcp_servers\.%s\]\s*\n.*?(?=^\[|\Z)" % NAME)
    if remove:
        if pattern.search(text):
            _backup(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(pattern.sub("", text))
        return "Codex: config.toml 에서 해제"
    if pattern.search(text):
        return "Codex: 이미 등록되어 있음 (%s)" % path
    if not os.path.isdir(home):
        return "Codex: 설치 기록(~/.codex) 없음 - 건너뜀"
    _backup(path)
    block = ("\n[mcp_servers.%s]\ncommand = '%s'\nargs = ['-I', '%s']\n"
             % (NAME, console_python(), SERVER))
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return "Codex: %s 에 등록 완료" % path


def claude_desktop(remove=False):
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return "Claude Desktop: 건너뜀 (Windows 아님)"
    d = os.path.join(appdata, "Claude")
    if not os.path.isdir(d):
        return "Claude Desktop: 설치 폴더 없음 - 건너뜀"
    try:
        _merge_json_servers(os.path.join(d, "claude_desktop_config.json"), remove)
        return "Claude Desktop: %s 완료 (앱 재시작 필요)" % ("해제" if remove else "등록")
    except Exception as e:
        return "Claude Desktop: 실패 %r" % e


def main(remove=False):
    return [claude_code(remove), codex(remove), claude_desktop(remove)]


if __name__ == "__main__":
    for line in main("--remove" in sys.argv):
        print("-", line)
    if os.name == "nt" and "--no-pause" not in sys.argv:
        input("\nEnter 키를 누르면 닫힙니다...")
