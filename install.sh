#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Worklog Timer Installer ==="
echo ""

# 1. Create timelogs directory
mkdir -p ~/.timelogs
echo "✓ Created ~/.timelogs/"

# 2. Make CLI executable
chmod +x "$SCRIPT_DIR/worklog"
echo "✓ Made worklog CLI executable"

# 3. Symlink to ~/.local/bin
mkdir -p ~/.local/bin
ln -sf "$SCRIPT_DIR/worklog" ~/.local/bin/worklog
echo "✓ Symlinked worklog → ~/.local/bin/worklog"

# 4. Install systemd service
mkdir -p ~/.config/systemd/user
sed "s|@WORKLOG_PATH@|${SCRIPT_DIR}|g" \
    "$SCRIPT_DIR/worklog-timer.service" > ~/.config/systemd/user/worklog-timer.service
systemctl --user daemon-reload
echo "✓ Installed systemd service"

# 5. Enable service (but don't start yet)
systemctl --user enable worklog-timer.service
echo "✓ Enabled worklog-timer.service (will auto-start on login)"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Quick start:"
echo "  worklog start              # Start with default 45m interval"
echo "  worklog start --interval 30 # Start with 30m interval"
echo "  worklog status             # Check if running"
echo "  worklog show               # View today's entries"
echo "  worklog stop               # Stop the timer"
echo ""
echo "Or use systemd:"
echo "  systemctl --user start worklog-timer   # Start via systemd"
echo "  systemctl --user status worklog-timer  # Check status"
echo "  systemctl --user stop worklog-timer    # Stop"
