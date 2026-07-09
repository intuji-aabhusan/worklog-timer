# Worklog Timer

A lightweight daemon that prompts you every N minutes to describe what you've been working on. Entries are saved to daily JSONL files for later use in timesheet filling.

## Features

- 🕐 **Wall-clock check-ins** — popups land on a fixed grid (default: 8:45, 9:30, 10:15, …), configurable interval and anchor time; survives restarts and suspend/resume without drifting
- 🎨 **Dark-themed popup** — Catppuccin Mocha–styled Tkinter dialog that stays on top and grabs focus
- 🔔 **Desktop notifications** — `notify-send` + a soft synthesised chime (no harsh system sounds)
- ⏱️ **Auto-skip** — popup auto-dismisses after 2 minutes; typing resets the countdown
- 📝 **JSONL storage** — one file per day in `~/.timelogs/`
- 🖥️ **CLI** — `worklog start/stop/status/show/log/open` commands
- 📲 **Click-to-open** — click the notification to open the popup immediately
- ⚙️ **systemd service** — starts with the graphical session
- 🛡️ **Crash-isolated popup** — the dialog runs in its own subprocess with a fresh
  `DISPLAY`/`XAUTHORITY`, re-discovered before every prompt (survives Wayland
  auth-file rotation and login races)

## Quick Start

```bash
# Install
./install.sh

# Start with default 45-minute interval
worklog start

# Start with custom interval
worklog start --interval 30

# Start with a custom anchor time (popups at 9:00, 9:45, 10:30, …)
worklog start --anchor 09:00

# Check status
worklog status

# View today's entries
worklog show

# View entries for a specific date
worklog show --date 2026-07-01

# Manually log something
worklog log "Fixed authentication bug in the MCP integration"

# Open the popup right now (without waiting for the timer)
worklog open

# Stop the timer
worklog stop
```

## How It Works

1. Prompts fire on a wall-clock grid: `anchor + k × interval` (default anchor 08:45,
   interval 45m → 8:45, 9:30, 10:15, 11:00, …). The daemon sleeps until the next slot,
   comparing against the clock so restarts and suspend/resume don't shift the schedule.
   A slot landing within 5 minutes of the previous prompt (e.g. right after
   `worklog open`) is skipped to avoid back-to-back popups.
2. At each slot, the daemon sends a desktop notification and plays a gentle chime
3. It re-discovers the graphical environment (`DISPLAY`, `XAUTHORITY`, …) at that moment —
   not at startup — so popups keep working across session restarts
4. A dark-themed popup appears (in its own subprocess) asking "What did you do?"
5. You type a brief description and press **Enter** (or click "✓ Log It")
6. The entry is saved to `~/.timelogs/YYYY-MM-DD.jsonl`
7. If you don't respond within 2 minutes, it auto-skips and records a "skipped" entry —
   but typing resets the countdown, so it never closes mid-sentence
8. You can click the notification or run `worklog open` to open the popup at any time

## Storage Format

Entries are stored as JSON Lines in `~/.timelogs/YYYY-MM-DD.jsonl`:

```json
{"timestamp": "2026-07-02T09:30:00+05:45", "interval_start": "2026-07-02T08:45:00+05:45", "interval_end": "2026-07-02T09:30:00+05:45", "description": "Worked on auth token management for IntujiOS", "status": "logged", "interval_minutes": 45}
```

## Keyboard Shortcuts (Popup)

| Key | Action |
|---|---|
| `Enter` | Submit entry |
| `Shift+Enter` | New line |
| `Ctrl+Enter` | Submit entry |
| `Escape` | Skip |
| Close window | Skip |

## Notification Sound

The alert is a soft three-note bell arpeggio (C5–E5–G5) synthesised once with the
Python stdlib and cached at `~/.timelogs/.chime-v1.wav`, played via `pw-play`,
`paplay`, or `aplay` — whichever is available. To preview it:

```bash
pw-play ~/.timelogs/.chime-v1.wav
```

Want a different sound? Delete the cached file and tweak the note/envelope
parameters in `worklog_timer/notifier.py` (`_synthesize_chime`).

## systemd Service

The service is bound to `graphical-session.target`, so it starts once the desktop
is up and stops with it.

```bash
# Start via systemd
systemctl --user start worklog-timer

# Check status
systemctl --user status worklog-timer

# Stop
systemctl --user stop worklog-timer

# View logs
journalctl --user -u worklog-timer
```

## Troubleshooting

**Popup never appears / entries are all "skipped"**
Check the logs for display errors:

```bash
journalctl --user -u worklog-timer | grep -i -E 'popup|display'
```

The daemon re-discovers `DISPLAY`/`XAUTHORITY` before every popup, so a login
race can no longer break it permanently. If popups still fail, test one directly:

```bash
python3 test_popup.py
```

**No sound**
Verify a player exists (`pw-play`, `paplay`, or `aplay`) and that
`~/.timelogs/.chime-v1.wav` exists (it is regenerated automatically if deleted).

## Dependencies

- Python 3.10+ (stdlib only — no pip installs needed)
- `tkinter` (usually bundled with Python)
- `notify-send` (for desktop notifications)
- `pw-play`, `paplay`, or `aplay` (for the notification chime)

## Project Structure

```
worklog-timer/
├── worklog_timer/
│   ├── __init__.py       # Package version
│   ├── daemon.py         # Main daemon loop + daemonization
│   ├── display.py        # Runtime discovery of DISPLAY/XAUTHORITY/etc.
│   ├── popup.py          # Dark-themed Tkinter popup (runs as a subprocess)
│   ├── storage.py        # JSONL read/write to ~/.timelogs/
│   └── notifier.py       # Desktop notifications + synthesised chime
├── worklog               # CLI entry point
├── worklog-timer.service # systemd user service
├── install.sh            # Installer script
├── test_popup.py         # Manual popup smoke test
└── README.md
```
