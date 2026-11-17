# thurm-usage-rings

A [Thurm](https://github.com/nklmilojevic/thurm) plugin that shows what is left of your Claude and Codex usage limits as rings, in a small floating card.

Each tool gets one ring pair: the outer ring is the 5-hour window, the inner ring the weekly one. A ring shows how much is **left**: green above 50%, amber above 20%, red below. Under the rings are the percentage left and when each window resets.

## Install

```sh
thurm plugin install https://github.com/kavanpancholi/thurm-usage-rings
```

Then press `Cmd+Shift+U`, or run `Usage Rings` from the command palette. The same key closes the card, and so do `q` and `Esc` inside it. `r` refreshes.

```sh
thurm action run usage.rings
```

## Where the numbers come from

- **Claude**: Claude Code's sign-in, the same way Thurm's sidebar reads it. The token comes from the `Claude Code-credentials` keychain item (or `~/.claude/.credentials.json`) and goes only to `https://api.anthropic.com/api/oauth/usage`. Checked every 5 minutes while the card is open.
- **Codex**: the latest `rate_limits` in Codex's session logs (`~/.codex/sessions`). No network. Checked every minute while the card is open.

Nothing runs while the card is closed.

## Settings

In `~/.config/thurm/config.toml`:

```toml
[plugins.settings]
usage-rings = { key = "cmd+shift+u", claude = true, codex = true }
```

- `key`: the key that opens and closes the card; `false` binds none.
- `claude`, `codex`: turn a tool off.
- `python`: the Python 3 to run the card with (default `/usr/bin/python3`).
- `demo`: show sample numbers.

## Requirements

macOS, Thurm with plugins, and Python 3 (the system one is enough; no packages).
