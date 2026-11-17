# thurm-usage-rings

A [Thurm](https://github.com/nklmilojevic/thurm) plugin that shows how much of your AI tools' usage limits you have used as rings in a corner of the window.

![The dock in the bottom right corner of a Thurm window, with the Claude Code popover: 5-hour and weekly limits, percent used, and when each resets](media/popover.png)

Each tool gets a ring with its icon. The ring fills with the highest share used of its limits, rounded down like Claude Code's `/usage`: white below 50%, orange from 50%, red from 80%. Hover a ring for each limit, with a bar and when it resets; click the ring to refresh, or right click the dock for its settings. A "!" means the tool could not be read, and its popover says why.

The plugin draws everything itself (the rings are images it renders); Thurm only gives it a place in the window ([plugin views](https://docs.thurm.rs/plugins/#views-in-the-window)). On a Thurm without plugin views, `Cmd+Shift+U` opens the limits in a floating card instead.

## Install

```sh
thurm plugin install https://github.com/kavanpancholi/thurm-usage-rings
```

## Settings

Click the sliders icon at the start of the dock to show or hide a tool, add one with its own command, remove one, or move the dock to another corner. Those choices go to `prefs.json` in the plugin's folder and win over the config file.

Or set them in `~/.config/thurm/config.toml`:

```toml
[plugins.settings.usage-rings]
slot = "window.bottom_trailing"   # or window.bottom_leading, window.top_trailing
tools = ["claude", "codex"]       # which built-in tools to show, in this order
every = 300                       # seconds between refreshes (at least 60)
menu = true                       # false hides the sliders icon
```

`thurm reload` applies a change at once.

## Built-in tools

- **claude**: Claude Code's sign-in, read the way Thurm's sidebar reads it (the `Claude Code-credentials` keychain item for your macOS user, or `~/.claude/.credentials.json`). The token goes only to `https://api.anthropic.com/api/oauth/usage`.
- **codex**: the latest `rate_limits` in Codex's session logs (`~/.codex/sessions`). No network.

## Any other tool

Add a `custom` entry with a command that prints the limits as JSON, and it gets a ring after the built-in ones:

```toml
[[plugins.settings.usage-rings.custom]]
name = "Grok"
icon = "~/icons/grok.png"           # a PNG; or symbol = "bolt" for an SF Symbol
command = ["~/bin/grok-usage"]
```

The command prints:

```json
{"windows": [{"label": "Weekly limit", "left": 66, "resets_at": "2026-11-21T09:00:00Z"}]}
```

`left` is the percentage left (0 to 100), and `resets_at` an ISO 8601 time or null. To show a problem instead, print `{"problem": "Sign in to Grok first"}`. The command runs through your login shell, on every refresh.

## Requirements

macOS, Thurm with plugins, and Python 3 (the system one is enough; no packages).
