# Worklog Timer

A lightweight daemon that prompts you every N minutes to describe what you've been working on. Entries are saved to daily JSONL files for later use in timesheet filling.

## Features

- 🕐 **Periodic check-ins** — configurable interval (default: 45 minutes)
- 🎨 **Dark-themed popup** — Catppuccin Mocha–styled Tkinter dialog
- 🔔 **Desktop notifications** — `notify-send` + sound alert
- ⏱️ **Auto-skip** — popup auto-dismisses after 2 minutes if no response
- 📝 **JSONL storage** — one file per day in `~/.timelogs/`
- 🖥️ **CLI** — `worklog start/stop/status/show/log` commands
- ⚙️ **systemd service** — auto-starts on login

## Quick Start

```bash
# Install
./install.sh

# Start with default 45-minute interval
worklog start

# Start with custom interval
worklog start --interval 30

# Check status
worklog status

# View today's entries
worklog show

# View entries for a specific date
worklog show --date 2026-07-01

# Manually log something
worklog log "Fixed authentication bug in the MCP integration"

# Stop the timer
worklog stop
```

## How It Works

1. Every N minutes, the daemon sends a desktop notification and plays a sound
2. A dark-themed popup appears asking "What did you do?"
3. You type a brief description and click "✓ Log It" (or press Ctrl+Enter)
4. The entry is saved to `~/.timelogs/YYYY-MM-DD.jsonl`
5. If you don't respond within 2 minutes, it auto-skips and records a "skipped" entry

## Storage Format

Entries are stored as JSON Lines in `~/.timelogs/YYYY-MM-DD.jsonl`:

```json
{"timestamp": "2026-07-02T09:30:00+05:45", "interval_start": "2026-07-02T08:45:00+05:45", "interval_end": "2026-07-02T09:30:00+05:45", "description": "Worked on auth token management for IntujiOS", "status": "logged", "interval_minutes": 45}
```

## Keyboard Shortcuts (Popup)

| Key | Action |
|---|---|
| `Ctrl+Enter` | Submit entry |
| `Escape` | Skip |
| Close window | Skip |

## systemd Service

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

## Dependencies

- Python 3.10+ (stdlib only — no pip installs needed)
- `tkinter` (usually bundled with Python)
- `notify-send` (for desktop notifications)
- `paplay` or `aplay` (for notification sound)

## Project Structure

```
worklog-timer/
├── worklog_timer/
│   ├── __init__.py       # Package version
│   ├── daemon.py         # Main daemon loop + daemonization
│   ├── popup.py          # Dark-themed Tkinter popup
│   ├── storage.py        # JSONL read/write to ~/.timelogs/
│   └── notifier.py       # Desktop notifications + sound
├── worklog               # CLI entry point
├── worklog-timer.service # systemd user service
├── install.sh            # Installer script
└── README.md
```
