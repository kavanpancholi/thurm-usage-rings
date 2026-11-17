#!/usr/bin/env python3
"""What is left of an AI tool's usage limits, for the usage-rings plugin.

    usage.py claude | codex | demo     prints {"windows": [{"label", "left", "resets_at"}]} or {"problem"}
    usage.py ring VALUE RRGGBB         prints a ring filled to VALUE (0 to 1), as a base64 PNG
"""
import base64
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib


def parse_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def window(minutes, used, resets):
    return {"minutes": minutes, "used": max(0.0, min(100.0, float(used))), "resets": resets}


class NoCredentials(Exception):
    pass


def claude_credentials():
    keychain = "keychain: not tried"
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, timeout=10,
        )
        raw = out.stdout.strip() if out.returncode == 0 else b""
        keychain = "keychain: security exited %d" % out.returncode
    except subprocess.TimeoutExpired:
        raw, keychain = b"", "keychain: security timed out"
    except OSError:
        raw, keychain = b"", "keychain: security not found"
    if not raw:
        home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        try:
            with open(os.path.join(home, ".credentials.json"), "rb") as f:
                raw = f.read().strip()
        except OSError:
            raise NoCredentials(keychain + ", no .credentials.json")
    if not raw.startswith(b"{"):
        try:
            raw = bytes.fromhex(raw.decode())
        except ValueError:
            raise NoCredentials("sign-in is not JSON")
    try:
        oauth = json.loads(raw)["claudeAiOauth"]
    except (ValueError, KeyError, TypeError):
        raise NoCredentials("sign-in has no claudeAiOauth")
    token = oauth.get("accessToken")
    if not token:
        raise NoCredentials("sign-in has no access token")
    expires = oauth.get("expiresAt")
    return token, (expires / 1000 if isinstance(expires, (int, float)) else None)


def fetch_claude():
    try:
        token, expires = claude_credentials()
    except NoCredentials as e:
        return {"problem": str(e)}
    if expires and expires <= time.time():
        return {"problem": "sign-in expired; renews when Claude Code runs"}
    request = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": "thurm-usage-rings",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        return {"problem": {401: "sign-in refused", 403: "sign-in refused",
                            429: "rate limited, trying later"}.get(e.code, "Anthropic answered %d" % e.code)}
    except (urllib.error.URLError, OSError, ValueError):
        return {"problem": "couldn't reach Anthropic"}
    windows = []
    for key, minutes in (("five_hour", 300), ("seven_day", 10080)):
        w = body.get(key) or {}
        if isinstance(w.get("utilization"), (int, float)):
            windows.append(window(minutes, w["utilization"], parse_time(w.get("resets_at"))))
    return {"windows": windows} if windows else {"problem": "answer not understood"}


def codex_logs():
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    sessions = os.path.join(home, "sessions")

    def children(path):
        try:
            return sorted((os.path.join(path, n) for n in os.listdir(path)), reverse=True)
        except OSError:
            return []

    days = [d for y in children(sessions) for m in children(y) for d in children(m)][:7]
    files = [f for d in days for f in children(d)
             if os.path.basename(f).startswith("rollout-") and f.endswith(".jsonl")]
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files[:5]


def tail(path, size=512 * 1024):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        return f.read()


def codex_snapshot(data):
    for line in reversed(data.split(b"\n")):
        if b'"rate_limits"' not in line or len(line) > 64 * 1024:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        payload = event.get("payload") or {}
        limits = payload.get("rate_limits")
        if payload.get("type") != "token_count" or not isinstance(limits, dict):
            continue
        if limits.get("limit_id") not in (None, "codex"):
            continue
        at = parse_time(event.get("timestamp"))
        windows = []
        for key in ("primary", "secondary"):
            w = limits.get(key) or {}
            minutes = w.get("window_minutes")
            if not isinstance(w.get("used_percent"), (int, float)) or not minutes:
                continue
            resets = parse_time(w.get("resets_at"))
            if resets is None and at and isinstance(w.get("resets_in_seconds"), (int, float)):
                resets = at + dt.timedelta(seconds=w["resets_in_seconds"])
            windows.append(window(int(minutes), w["used_percent"], resets))
        if windows:
            return sorted(windows, key=lambda w: w["minutes"])
    return None


def fetch_codex():
    for path in codex_logs():
        try:
            windows = codex_snapshot(tail(path))
        except OSError:
            continue
        if windows:
            return {"windows": windows}
    return {"problem": "no Codex session log with limits"}


def demo():
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "Claude": {"windows": [window(300, 38, now + dt.timedelta(hours=2, minutes=10)),
                               window(10080, 71, now + dt.timedelta(days=3))]},
        "Codex": {"windows": [window(300, 12, now + dt.timedelta(hours=4)),
                              window(10080, 86, now + dt.timedelta(days=1, hours=5))]},
    }


def png(width, height, rgba):
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind, data):
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))



def ring_png(value, color, size=96):
    fg = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    track = (90, 90, 96)
    rgba = bytearray(size * size * 4)
    c, r, w = (size - 1) / 2, size / 2 - size * 0.06, size * 0.09
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            cover = min(d - (r - w) + 0.5, r - d + 0.5, 1.0)
            if cover <= 0:
                continue
            angle = (math.atan2(x - c, -(y - c)) / (2 * math.pi)) % 1.0
            rgb = fg if angle <= value else track
            i = (y * size + x) * 4
            rgba[i:i + 4] = bytes((*rgb, int(255 * cover)))
    return png(size, size, bytes(rgba))


def label(minutes):
    if minutes == 300:
        return "5-hour limit"
    if minutes == 10080:
        return "Weekly limit"
    if minutes % 1440 == 0:
        return "%d-day limit" % (minutes // 1440)
    return "%d-hour limit" % (minutes // 60) if minutes % 60 == 0 else "%d-minute limit" % minutes


def report(result):
    if "windows" not in result:
        return result
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for w in result["windows"]:
        reset = w["resets"]
        left = 100.0 if reset and reset <= now else 100.0 - w["used"]
        out.append({
            "label": label(w["minutes"]),
            "left": round(left),
            "resets_at": reset.isoformat() if reset and reset > now else None,
        })
    return {"windows": out}


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "ring":
        sys.stdout.write(base64.b64encode(ring_png(float(sys.argv[2]), sys.argv[3])).decode())
        return
    fetch = {"claude": fetch_claude, "codex": fetch_codex, "demo": lambda: demo()["Claude"]}.get(what)
    if fetch is None:
        sys.exit("usage: usage.py claude|codex|demo|ring VALUE RRGGBB")
    print(json.dumps(report(fetch())))


if __name__ == "__main__":
    main()
