#!/usr/bin/env python3
import base64
import datetime as dt
import json
import math
import os
import select
import subprocess
import sys
import termios
import time
import tty
import urllib.error
import urllib.request
import zlib

CLAUDE_EVERY = 300
CODEX_EVERY = 60
RING_PX = 120
RING_COLS = 12
RING_ROWS = 6
GREEN = (52, 199, 89)
AMBER = (255, 159, 10)
RED = (255, 69, 58)
TRACK = (90, 90, 96)


def settings():
    try:
        return json.loads(os.environ.get("USAGE_RINGS_SETTINGS") or "{}")
    except ValueError:
        return {}


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


def claude_credentials():
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, timeout=10,
        )
        raw = out.stdout.strip() if out.returncode == 0 else b""
    except (OSError, subprocess.TimeoutExpired):
        raw = b""
    if not raw:
        home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        try:
            with open(os.path.join(home, ".credentials.json"), "rb") as f:
                raw = f.read().strip()
        except OSError:
            return None
    if not raw.startswith(b"{"):
        try:
            raw = bytes.fromhex(raw.decode())
        except ValueError:
            return None
    try:
        oauth = json.loads(raw)["claudeAiOauth"]
    except (ValueError, KeyError, TypeError):
        return None
    token = oauth.get("accessToken")
    if not token:
        return None
    expires = oauth.get("expiresAt")
    return token, (expires / 1000 if isinstance(expires, (int, float)) else None)


def fetch_claude():
    creds = claude_credentials()
    if creds is None:
        return {"problem": "not signed in to Claude Code"}
    token, expires = creds
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


def left(w, now):
    if w["resets"] and w["resets"] <= now:
        return 100.0
    return 100.0 - w["used"]


def color(pct):
    return GREEN if pct > 50 else AMBER if pct > 20 else RED


def png(width, height, rgba):
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind, data):
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ring_image(fractions, size=RING_PX):
    rgba = bytearray(size * size * 4)
    c = (size - 1) / 2
    bands = []
    outer = size / 2 - 2
    thickness = size * 0.12
    for i, (frac, col) in enumerate(fractions):
        r1 = outer - i * (thickness + size * 0.05)
        bands.append((r1 - thickness, r1, frac, col))
    for y in range(size):
        for x in range(size):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            angle = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
            for r0, r1, frac, col in bands:
                cover = min(d - r0 + 0.5, r1 - d + 0.5, 1.0)
                if cover <= 0:
                    continue
                rgb = col if angle <= frac else TRACK
                i = (y * size + x) * 4
                rgba[i:i + 4] = bytes((*rgb, int(255 * cover)))
                break
    return png(size, size, bytes(rgba))


def kitty_image(data, cols, rows):
    payload = base64.standard_b64encode(data).decode()
    out, first = [], True
    while payload:
        part, payload = payload[:4096], payload[4096:]
        head = "a=T,f=100,q=2,c=%d,r=%d,C=1," % (cols, rows) if first else ""
        out.append("\x1b_G%sm=%d;%s\x1b\\" % (head, 1 if payload else 0, part))
        first = False
    return "".join(out)


def until(resets, now):
    if not resets:
        return ""
    secs = int((resets - now).total_seconds())
    if secs <= 0:
        return "reset"
    if secs < 3600:
        return "%dm" % (secs // 60)
    if secs < 86400:
        return "%dh %dm" % (secs // 3600, secs % 3600 // 60)
    return resets.astimezone().strftime("%a %H:%M")


def label(minutes):
    if minutes == 10080:
        return "wk"
    if minutes % 1440 == 0:
        return "%dd" % (minutes // 1440)
    if minutes % 60 == 0:
        return "%dh" % (minutes // 60)
    return "%dm" % minutes


def draw(reports, updated):
    now = dt.datetime.now(dt.timezone.utc)
    rows, cols = os.get_terminal_size(sys.stdout.fileno())[::-1]
    out = ["\x1b_Ga=d,d=A,q=2\x1b\\\x1b[2J"]
    col_w = max(RING_COLS + 2, cols // max(1, len(reports)))
    for n, (name, report) in enumerate(reports.items()):
        x = n * col_w + 2
        out.append("\x1b[1;%dH\x1b[1m%s\x1b[0m" % (x, name))
        windows = report.get("windows") or []
        if windows:
            shown = [(left(w, now) / 100, color(left(w, now))) for w in windows[:2]]
            out.append("\x1b[2;%dH" % x + kitty_image(ring_image(shown), RING_COLS, RING_ROWS))
            for i, w in enumerate(windows[:2]):
                pct = left(w, now)
                line = "%s %3d%% left %s" % (label(w["minutes"]), round(pct), until(w["resets"], now))
                out.append("\x1b[%d;%dH%s" % (RING_ROWS + 3 + i, x, line[:col_w - 1]))
        else:
            out.append("\x1b[3;%dH\x1b[2m%s\x1b[0m" % (x, (report.get("problem") or "")[:col_w - 1]))
    footer = "r refresh  q close  %s" % updated.strftime("%H:%M")
    out.append("\x1b[%d;2H\x1b[2m%s\x1b[0m" % (rows, footer[:cols - 2]))
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def main():
    opts = settings()
    providers = []
    if opts.get("claude", True):
        providers.append(("Claude", fetch_claude, CLAUDE_EVERY))
    if opts.get("codex", True):
        providers.append(("Codex", fetch_codex, CODEX_EVERY))
    reports, fetched = {}, {}

    def refresh(force):
        if "--demo" in sys.argv:
            reports.update(demo())
            return
        now = time.monotonic()
        for name, fetch, every in providers:
            if force or now - fetched.get(name, -every) >= every:
                reports[name] = fetch()
                fetched[name] = now

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        refresh(True)
        draw(reports, dt.datetime.now())
        while True:
            ready, _, _ = select.select([fd], [], [], 30)
            key = os.read(fd, 16) if ready else b""
            if key[:1] in (b"q", b"\x1b", b"\x03"):
                break
            refresh(key[:1] == b"r")
            draw(reports, dt.datetime.now())
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b_Ga=d,d=A,q=2\x1b\\\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


if __name__ == "__main__":
    main()
