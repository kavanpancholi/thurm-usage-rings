#!/usr/bin/env python3
import base64
import datetime as dt
import json
import math
import os
import select
import sys
import termios
import textwrap
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usage import demo, fetch_claude, fetch_codex, png  # noqa: E402

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


def left(w, now):
    if w["resets"] and w["resets"] <= now:
        return 100.0
    return 100.0 - w["used"]


def color(pct):
    return GREEN if pct > 50 else AMBER if pct > 20 else RED


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
            for i, part in enumerate(textwrap.wrap(report.get("problem") or "", col_w - 2)[:RING_ROWS]):
                out.append("\x1b[%d;%dH\x1b[2m%s\x1b[0m" % (3 + i, x, part))
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
