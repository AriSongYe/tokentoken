"""
TokenToken - usage collection core.

Reads local session logs written by
  * Claude Code  (~/.claude/projects/**/*.jsonl, or $CLAUDE_CONFIG_DIR)
  * Codex CLI    (~/.codex/sessions/**/*.jsonl,  or $CODEX_HOME)
and (optionally) the Claude subscription limit endpoint used by Claude Code's
own /usage screen, authenticated with the local Claude Code login.

Standard library only. Shared by the desktop widget and the MCP server.
"""
import glob
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

LOOKBACK_DAYS = 8
BLOCK_SECONDS = 5 * 3600


# ----------------------------------------------------------------- helpers
def _home():
    return os.path.expanduser("~")


def parse_ts(value):
    """ISO-8601 string / epoch number -> epoch seconds (float) or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000.0 if value > 1e12 else 1.0)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        # Python 3.10 fromisoformat accepts at most 6 fractional digits
        if "." in s:
            head, rest = s.split(".", 1)
            frac = ""
            i = 0
            while i < len(rest) and rest[i].isdigit():
                frac += rest[i]
                i += 1
            s = head + "." + (frac[:6] or "0") + rest[i:]
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.timestamp()
    except Exception:
        return None


def local_midnight(now=None):
    now = now or time.time()
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def fmt_tokens(n):
    n = float(n or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            v = n / div
            return ("%.1f" % v).rstrip("0").rstrip(".") + unit
    return str(int(n))


def fmt_duration(sec):
    if sec is None:
        return "-"
    sec = int(max(0, sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "%d일 %d시간" % (d, h)
    if h:
        return "%d시간 %d분" % (h, m)
    return "%d분" % m


def fmt_ago(ts, now=None):
    if not ts:
        return "기록 없음"
    diff = (now or time.time()) - ts
    if diff < 60:
        return "방금"
    return fmt_duration(diff) + " 전"


class _Tail:
    """Incremental JSONL reader: only parses bytes appended since last call."""

    def __init__(self):
        self.files = {}

    def read(self, path):
        try:
            size = os.path.getsize(path)
        except OSError:
            return None, []
        ent = self.files.get(path)
        reset = ent is None or size < ent["offset"]
        if reset:
            ent = {"offset": 0, "state": {}}
            self.files[path] = ent
        if size == ent["offset"]:
            return ent, []
        try:
            with open(path, "rb") as f:
                f.seek(ent["offset"])
                data = f.read(size - ent["offset"])
        except OSError:
            return ent, []
        nl = data.rfind(b"\n")
        if nl < 0:
            return ent, []
        chunk = data[: nl + 1]
        ent["offset"] += len(chunk)
        out = []
        for line in chunk.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line.decode("utf-8", "replace")))
            except Exception:
                pass
        return ent, out


def _recent_files(patterns, since):
    seen = set()
    out = []
    for pat in patterns:
        for p in glob.glob(pat, recursive=True):
            if p in seen:
                continue
            seen.add(p)
            try:
                if os.path.getmtime(p) >= since:
                    out.append(p)
            except OSError:
                pass
    return out


def _empty_claude_tot():
    return {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "total": 0}


def _empty_codex_tot():
    return {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "total": 0}


# ----------------------------------------------------------------- Claude
def _looks_like_claude_dir(d):
    return os.path.isdir(os.path.join(d, "projects")) or \
        os.path.isfile(os.path.join(d, ".credentials.json"))


def claude_roots(extra=None):
    """All Claude Code config dirs: $CLAUDE_CONFIG_DIR, ~/.claude, ~/.claude-*, ..."""
    cands = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        cands += [p.strip() for p in env.split(os.pathsep if os.pathsep in env else ",") if p.strip()]
    cands += list(extra or [])
    home = _home()
    cands += [os.path.join(home, ".claude"), os.path.join(home, ".config", "claude")]
    cands += sorted(glob.glob(os.path.join(home, ".claude-*")) + glob.glob(os.path.join(home, ".claude_*")))
    roots = []
    for c in cands:
        c = os.path.abspath(os.path.expanduser(c))
        if os.path.isdir(c) and c not in roots and _looks_like_claude_dir(c):
            roots.append(c)
    return roots


def claude_account_name(root):
    base = os.path.basename(root.rstrip("\\/"))
    if base.lower() in (".claude", "claude"):
        return "기본"
    for pre in (".claude-", ".claude_", "claude-", "claude_"):
        if base.lower().startswith(pre):
            return base[len(pre):]
    return base


def _limits_cache_path():
    base = os.environ.get("APPDATA") or os.path.join(_home(), ".config")
    d = os.path.join(base, "TokenToken")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, "claude_limits_cache.json")


_cache_lock = threading.Lock()


def _load_limits_cache(root):
    with _cache_lock:
        try:
            with open(_limits_cache_path(), "r", encoding="utf-8") as f:
                return json.load(f).get(root)
        except Exception:
            return None


def _save_limits_cache(root, value):
    with _cache_lock:
        path = _limits_cache_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data[root] = value
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass


class ClaudeCollector:
    """One Claude Code config dir == one account."""
    API_URL = "https://api.anthropic.com/api/oauth/usage"

    def __init__(self, root):
        self.root = root
        self.name = claude_account_name(root)
        self.tail = _Tail()
        self.seen = set()
        self.entries = []  # (ts, model, inp, out, cw, cr)
        self._api_cache = _load_limits_cache(root)  # last good answer survives restarts
        self._api_time = 0.0
        self._api_err = None

    def _scan(self, now):
        since = now - LOOKBACK_DAYS * 86400
        pats = [os.path.join(self.root, "projects", "**", "*.jsonl")]
        for path in _recent_files(pats, since):
            _, objs = self.tail.read(path)
            for o in objs:
                if not isinstance(o, dict):
                    continue
                msg = o.get("message")
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if not isinstance(u, dict):
                    continue
                key = "%s:%s" % (msg.get("id"), o.get("requestId"))
                if msg.get("id") and key in self.seen:
                    continue
                self.seen.add(key)
                ts = parse_ts(o.get("timestamp"))
                if ts is None:
                    continue
                e = (ts, msg.get("model") or "unknown",
                     int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                     int(u.get("cache_creation_input_tokens") or 0),
                     int(u.get("cache_read_input_tokens") or 0))
                if e[2] + e[3] + e[4] + e[5] == 0:
                    continue  # synthetic / error messages carry an all-zero usage block
                self.entries.append(e)
        cutoff = now - LOOKBACK_DAYS * 86400
        self.entries = [e for e in self.entries if e[0] >= cutoff]
        self.entries.sort(key=lambda e: e[0])

    @staticmethod
    def _sum(entries):
        t = _empty_claude_tot()
        for _, _, i, o, cw, cr in entries:
            t["input"] += i
            t["output"] += o
            t["cache_write"] += cw
            t["cache_read"] += cr
        t["total"] = t["input"] + t["output"] + t["cache_write"] + t["cache_read"]
        return t

    def _current_block(self, now):
        """ccusage-style 5h billing block that contains `now`, if any."""
        start = last = None
        block = []
        for e in self.entries:
            ts = e[0]
            if start is None or ts >= start + BLOCK_SECONDS or ts - last >= BLOCK_SECONDS:
                start = ts - (ts % 3600)  # floor to the hour
                block = []
            block.append(e)
            last = ts
        if start is None or now >= start + BLOCK_SECONDS or now - last >= BLOCK_SECONDS:
            return None
        return {"start": start, "end": start + BLOCK_SECONDS, "tokens": self._sum(block)}

    # -- subscription limits (same data as Claude Code's /usage) --
    def _credentials(self):
        p = os.path.join(self.root, ".credentials.json")
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    oauth = (json.load(f) or {}).get("claudeAiOauth") or {}
                if oauth.get("accessToken"):
                    return oauth
            except Exception:
                pass
        return None

    def has_valid_login(self, now):
        cred = self._credentials()
        if not cred:
            return False
        exp = parse_ts(cred.get("expiresAt"))
        return not exp or exp > now

    def _fetch_limits(self, now, min_interval):
        if now - self._api_time < min_interval:
            return
        self._api_time = now
        cred = self._credentials()
        if not cred:
            self._api_err = "로그인 정보 없음 (.credentials.json)"
            return
        exp = parse_ts(cred.get("expiresAt"))
        if exp and exp < now:
            self._api_err = "로그인 토큰 만료 - Claude Code를 사용하면 자동 갱신"
            return
        req = urllib.request.Request(self.API_URL, headers={
            "Authorization": "Bearer " + cred["accessToken"],
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
            "User-Agent": "tokentoken-monitor/1.2",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            self._api_cache = {"data": data, "plan": cred.get("subscriptionType"), "at": now}
            self._api_err = None
            _save_limits_cache(self.root, self._api_cache)
        except urllib.error.HTTPError as e:
            self._api_err = "한도 API HTTP %s" % e.code
        except Exception as e:  # offline, proxy, ...
            self._api_err = "한도 API 오류: %s" % type(e).__name__

    def _limits(self, now):
        if not self._api_cache:
            return []
        data = self._api_cache.get("data") or {}
        names = [("five_hour", "5시간"), ("seven_day", "주간"),
                 ("seven_day_opus", "주간 Opus"), ("seven_day_sonnet", "주간 Sonnet")]
        out = []
        for key, label in names:
            v = data.get(key)
            if isinstance(v, dict) and v.get("utilization") is not None:
                used = float(v["utilization"])
                resets = parse_ts(v.get("resets_at"))
                if resets and now >= resets:
                    used, resets = 0.0, None  # window rolled over since we last asked
                out.append({"key": key, "name": label, "used_percent": used, "resets_at": resets})
        return out

    def collect(self, now=None, use_api=True, api_interval=90, block_limit=0):
        now = now or time.time()
        self._scan(now)
        if use_api:
            self._fetch_limits(now, api_interval)
        midnight = local_midnight(now)
        today = [e for e in self.entries if e[0] >= midnight]
        week = [e for e in self.entries if e[0] >= now - 7 * 86400]
        models = {}
        for e in today:
            models[e[1]] = models.get(e[1], 0) + e[2] + e[3] + e[4] + e[5]
        block = self._current_block(now)
        limits = self._limits(now) if use_api else []
        source = "api" if limits else "none"
        note = None
        if limits and self._api_cache and now - self._api_cache.get("at", now) > max(300, 3 * api_interval):
            note = "%s 기준 값" % fmt_ago(self._api_cache.get("at"), now)
            if self._api_err:
                note += " · " + self._api_err
        if not limits and block_limit and block_limit > 0:
            used = block["tokens"]["total"] if block else 0
            limits = [{"key": "five_hour", "name": "5시간(추정)",
                       "used_percent": min(999.0, 100.0 * used / block_limit),
                       "resets_at": block["end"] if block else None}]
            source = "local"
        return {
            "available": True,
            "account": self.name,
            "root": self.root,
            "plan": (self._api_cache or {}).get("plan"),
            "limits": limits,
            "limits_source": source,
            "limits_note": note,
            "limits_error": None if limits else self._api_err,
            "block": block,
            "today": self._sum(today),
            "week": self._sum(week),
            "models_today": models,
            "last_activity": self.entries[-1][0] if self.entries else None,
            "logged_in": self.has_valid_login(now),
        }


# ----------------------------------------------------------------- Codex
def codex_home():
    return os.path.abspath(os.environ.get("CODEX_HOME") or os.path.join(_home(), ".codex"))


def _norm_window(w, ts):
    """Normalise one Codex rate-limit window -> (used%, window_min, resets_at)."""
    if not isinstance(w, dict):
        return None
    used = w.get("used_percent")
    if used is None:
        return None
    resets = w.get("resets_at")
    resets = parse_ts(resets) if resets is not None else None
    if resets is None:
        rin = w.get("resets_in_seconds", w.get("reset_after_seconds"))
        if rin is not None and ts:
            resets = ts + float(rin)
    return float(used), w.get("window_minutes"), resets


class CodexCollector:
    def __init__(self):
        self.tail = _Tail()
        self.entries = []  # (ts, model, input, cached, output, reasoning, total)
        self.rate = None  # (ts, primary, secondary)

    def _scan(self, now):
        since = now - LOOKBACK_DAYS * 86400
        home = codex_home()
        pats = [os.path.join(home, "sessions", "**", "*.jsonl"),
                os.path.join(home, "archived_sessions", "**", "*.jsonl")]
        for path in _recent_files(pats, since):
            ent, objs = self.tail.read(path)
            if ent is None:
                continue
            st = ent["state"]
            for o in objs:
                if not isinstance(o, dict):
                    continue
                p = o.get("payload")
                if not isinstance(p, dict):
                    continue
                ptype = p.get("type")
                if o.get("type") == "turn_context" or ("model" in p and ptype is None):
                    if p.get("model"):
                        st["model"] = p["model"]
                    continue
                if ptype != "token_count":
                    continue
                ts = parse_ts(o.get("timestamp"))
                info = p.get("info")
                if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                    tot = info["total_token_usage"]
                    prev = st.get("prev") or {}
                    def d(k):
                        return max(0, int(tot.get(k) or 0) - int(prev.get(k) or 0))
                    delta_total = d("total_tokens")
                    if delta_total > 0 and ts:
                        self.entries.append((ts, st.get("model") or "unknown",
                                             d("input_tokens"), d("cached_input_tokens"),
                                             d("output_tokens"), d("reasoning_output_tokens"),
                                             delta_total))
                    if int(tot.get("total_tokens") or 0) >= int(prev.get("total_tokens") or 0):
                        st["prev"] = tot
                rl = p.get("rate_limits")
                if isinstance(rl, dict) and ts:
                    prim = rl.get("primary")
                    sec = rl.get("secondary")
                    if prim is None and "primary_used_percent" in rl:  # legacy flat format
                        prim = {"used_percent": rl.get("primary_used_percent"),
                                "window_minutes": rl.get("primary_window_minutes"),
                                "resets_in_seconds": rl.get("primary_reset_after_seconds")}
                        sec = {"used_percent": rl.get("secondary_used_percent"),
                               "window_minutes": rl.get("secondary_window_minutes"),
                               "resets_in_seconds": rl.get("secondary_reset_after_seconds")}
                    prim = _norm_window(prim, ts)
                    sec = _norm_window(sec, ts)
                    if (prim or sec) and (self.rate is None or ts >= self.rate[0]):
                        self.rate = (ts, prim, sec)
        cutoff = now - LOOKBACK_DAYS * 86400
        self.entries = [e for e in self.entries if e[0] >= cutoff]
        self.entries.sort(key=lambda e: e[0])

    @staticmethod
    def _sum(entries):
        t = _empty_codex_tot()
        for _, _, i, c, o, r, tot in entries:
            t["input"] += max(0, i - c)
            t["cached"] += c
            t["output"] += o
            t["reasoning"] += r
            t["total"] += tot
        return t

    @staticmethod
    def _label(win_min, fallback):
        if not win_min:
            return fallback
        win_min = int(win_min)
        if win_min >= 7 * 1440 - 60:
            return "주간"
        if win_min % 60 == 0 and win_min < 1440:
            return "%d시간" % (win_min // 60)
        if win_min % 1440 == 0:
            return "%d일" % (win_min // 1440)
        return "%d분" % win_min

    def collect(self, now=None):
        now = now or time.time()
        self._scan(now)
        limits = []
        if self.rate:
            ts, prim, sec = self.rate
            for w, key, fb in ((prim, "primary", "5시간"), (sec, "secondary", "주간")):
                if not w:
                    continue
                used, win, resets = w
                if resets and now >= resets:
                    used, resets = 0.0, None  # window already rolled over
                limits.append({"key": key, "name": self._label(win, fb),
                               "used_percent": used, "resets_at": resets,
                               "window_minutes": win})
        midnight = local_midnight(now)
        today = [e for e in self.entries if e[0] >= midnight]
        week = [e for e in self.entries if e[0] >= now - 7 * 86400]
        models = {}
        for e in today:
            models[e[1]] = models.get(e[1], 0) + e[6]
        return {
            "available": os.path.isdir(codex_home()),
            "limits": limits,
            "limits_updated_at": self.rate[0] if self.rate else None,
            "limits_error": None if limits else "Codex 기록에 한도 정보 없음 (Codex를 한 번 사용하면 표시)",
            "today": self._sum(today),
            "week": self._sum(week),
            "models_today": models,
            "last_activity": self.entries[-1][0] if self.entries else None,
        }


# ----------------------------------------------------------------- facade
class UsageMonitor:
    def __init__(self):
        self.claude = {}  # root -> ClaudeCollector
        self.codex = CodexCollector()
        self.lock = threading.Lock()

    def snapshot(self, use_claude_api=True, api_interval=90, claude_block_limit=0,
                 claude_dirs=None, show_idle_claude=False):
        with self.lock:
            now = time.time()
            snap = {"generated_at": now, "claude_accounts": []}
            try:
                for root in claude_roots(claude_dirs):
                    if root not in self.claude:
                        self.claude[root] = ClaudeCollector(root)
                    acc = self.claude[root].collect(now, use_claude_api, api_interval, claude_block_limit)
                    # skip stale/unused dirs (no tokens this week and no live login)
                    if show_idle_claude or acc["week"]["total"] > 0 or acc["logged_in"]:
                        snap["claude_accounts"].append(acc)
            except Exception as e:
                snap["claude_accounts"].append({"available": False, "account": "?", "error": repr(e)})
            snap["claude_accounts"].sort(key=lambda a: -(a.get("last_activity") or 0))
            try:
                snap["codex"] = self.codex.collect(now)
            except Exception as e:
                snap["codex"] = {"available": False, "error": repr(e)}
            return snap


def format_summary(snap, provider="all"):
    """Human readable (Korean) summary, used by the MCP server."""
    now = snap.get("generated_at") or time.time()
    blocks = []
    if provider in ("all", "claude"):
        accs = snap.get("claude_accounts") or []
        if not accs:
            blocks.append(("claude", "Claude", {"available": False}))
        for a in accs:
            blocks.append(("claude", "Claude [%s]" % a.get("account", "?"), a))
    if provider in ("all", "codex"):
        blocks.append(("codex", "Codex", snap.get("codex") or {}))
    lines = []
    for key, title, s in blocks:
        head = "■ " + title
        if s.get("plan"):
            head += " (%s)" % s["plan"]
        lines.append(head)
        if s.get("error"):
            lines.append("  오류: " + s["error"])
            continue
        if not s.get("available"):
            lines.append("  사용 기록을 찾지 못했습니다.")
            continue
        for lim in s.get("limits") or []:
            r = lim.get("resets_at")
            lines.append("  %s 한도: %.0f%% 사용%s" % (
                lim["name"], lim["used_percent"],
                (" · %s 후 리셋" % fmt_duration(r - now)) if r else ""))
        if s.get("limits_note"):
            lines.append("    (" + s["limits_note"] + ")")
        if not s.get("limits") and s.get("limits_error"):
            lines.append("  한도: " + s["limits_error"])
        if s.get("block"):
            b = s["block"]
            lines.append("  현재 5시간 블록: %s 토큰 (%s 후 종료)" % (
                fmt_tokens(b["tokens"]["total"]), fmt_duration(b["end"] - now)))
        t, w = s.get("today") or {}, s.get("week") or {}
        lines.append("  오늘: %s 토큰 · 최근 7일: %s 토큰" % (
            fmt_tokens(t.get("total")), fmt_tokens(w.get("total"))))
        if key == "claude":
            lines.append("    (오늘 입력 %s / 출력 %s / 캐시쓰기 %s / 캐시읽기 %s)" % (
                fmt_tokens(t.get("input")), fmt_tokens(t.get("output")),
                fmt_tokens(t.get("cache_write")), fmt_tokens(t.get("cache_read"))))
        else:
            lines.append("    (오늘 입력 %s / 캐시 %s / 출력 %s / 추론 %s)" % (
                fmt_tokens(t.get("input")), fmt_tokens(t.get("cached")),
                fmt_tokens(t.get("output")), fmt_tokens(t.get("reasoning"))))
        if s.get("models_today"):
            ms = sorted(s["models_today"].items(), key=lambda kv: -kv[1])
            lines.append("    모델별 오늘: " + ", ".join("%s %s" % (m, fmt_tokens(v)) for m, v in ms))
        lines.append("  마지막 사용: " + fmt_ago(s.get("last_activity"), now))
        if s.get("root"):
            lines.append("  기록 폴더: " + s["root"])
    return "\n".join(lines)


if __name__ == "__main__":
    m = UsageMonitor()
    print(format_summary(m.snapshot()))
