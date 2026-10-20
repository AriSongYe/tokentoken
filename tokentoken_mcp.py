"""
TokenToken MCP server (stdio, JSON-RPC 2.0, no external dependencies).

Register it in Claude Code / Codex / Claude Desktop with install_mcp.py.
Tools:
  get_token_usage(provider="all"|"claude"|"codex", format="text"|"json")
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usage_core import UsageMonitor, format_summary  # noqa: E402

SERVER_INFO = {"name": "tokentoken", "version": "1.2.0"}
DEFAULT_PROTOCOL = "2025-06-18"

TOOLS = [{
    "name": "get_token_usage",
    "title": "Claude / Codex 토큰 사용량",
    "description": ("로컬 Claude Code 와 Codex CLI 기록에서 토큰 사용량(오늘, 최근 7일, 현재 5시간 블록)과 "
                    "구독 한도 사용률(5시간/주간 %, 리셋까지 남은 시간)을 조회합니다."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "enum": ["all", "claude", "codex"],
                         "description": "조회 대상 (기본 all)"},
            "format": {"type": "string", "enum": ["text", "json"],
                       "description": "text: 요약문, json: 원본 수치 (기본 text)"},
        },
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}]

_monitor = UsageMonitor()


def _extra_claude_dirs():
    """Extra Claude config dirs listed in the widget's config (claude_dirs)."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    try:
        with open(os.path.join(base, "TokenToken", "config.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("claude_dirs") or []
    except Exception:
        return []


def _out(msg):
    sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _result(mid, result):
    _out({"jsonrpc": "2.0", "id": mid, "result": result})


def _error(mid, code, message):
    _out({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


def _call_tool(name, args):
    if name != "get_token_usage":
        raise KeyError(name)
    provider = (args or {}).get("provider") or "all"
    fmt = (args or {}).get("format") or "text"
    snap = _monitor.snapshot(claude_dirs=_extra_claude_dirs())
    if provider == "claude":
        snap.pop("codex", None)
    elif provider == "codex":
        snap.pop("claude_accounts", None)
    text = json.dumps(snap, ensure_ascii=False, indent=1) if fmt == "json" else format_summary(snap, provider)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method is None:
        return  # a response to us; ignore
    if method == "initialize":
        _result(mid, {
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "토큰/한도 사용량이 궁금하면 get_token_usage 를 호출하세요.",
        })
    elif method == "ping":
        _result(mid, {})
    elif method == "tools/list":
        _result(mid, {"tools": TOOLS})
    elif method == "tools/call":
        try:
            _result(mid, _call_tool(params.get("name"), params.get("arguments")))
        except KeyError:
            _error(mid, -32602, "Unknown tool: %s" % params.get("name"))
        except Exception as e:
            _result(mid, {"content": [{"type": "text", "text": "오류: %r" % e}], "isError": True})
    elif method in ("resources/list", "prompts/list"):
        _result(mid, {method.split("/")[0]: []})
    elif method.startswith("notifications/"):
        return
    elif mid is not None:
        _error(mid, -32601, "Method not found: %s" % method)


def main():
    for raw in sys.stdin.buffer:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            _error(None, -32700, "Parse error")
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            if isinstance(m, dict):
                handle(m)


if __name__ == "__main__":
    main()
