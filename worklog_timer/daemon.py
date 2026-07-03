"""Main daemon loop for worklog-timer."""

import logging
import os
import signal
import sys
import time

from worklog_timer import notifier, popup, storage

logger = logging.getLogger(__name__)

running = True


def _handle_signal(signum, frame):
    """Handle SIGTERM/SIGINT by setting the running flag to False."""
    global running
    running = False
    _cleanup()


def _cleanup():
    """Remove the PID file if it exists."""
    pid_file = storage.get_pid_file()
    if pid_file.exists():
        pid_file.unlink()


def _run_loop(interval_minutes: int) -> None:
    """Main loop: sleep, notify, show popup, save entry."""
    global running

    while running:
        interval_start = storage.now_npt()

        # Sleep in 1-second chunks so we can respond to signals
        for _ in range(interval_minutes * 60):
            if not running:
                return
            time.sleep(1)

        interval_end = storage.now_npt()

        # Send notification + sound
        notifier.notify_check_in(interval_minutes)

        # Show popup
        description, status = popup.show_popup(
            interval_start, interval_end, timeout_seconds=120
        )

        # Save entry
        entry = storage.append_entry(
            interval_start=interval_start,
            interval_end=interval_end,
            description=description,
            status=status,
            interval_minutes=interval_minutes,
        )

        logger.info(
            f'[{status}] {interval_start.strftime("%H:%M")}–'
            f'{interval_end.strftime("%H:%M")}: {description or "(skipped)"}'
        )


def run_daemon(interval_minutes: int = 45, foreground: bool = False) -> None:
    """Main entry point for the daemon process.

    Args:
        interval_minutes: Minutes between check-in prompts.
        foreground: If True, run in foreground (for systemd). Otherwise daemonize.
    """
    if not foreground:
        # --- Double-fork daemonization ---
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            logger.error(f'First fork failed: {e}')
            sys.exit(1)

        os.setsid()
        os.umask(0o022)

        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            logger.error(f'Second fork failed: {e}')
            sys.exit(1)

        # Redirect stdin to /dev/null
        devnull = open(os.devnull, 'r')
        os.dup2(devnull.fileno(), sys.stdin.fileno())

        # Redirect stdout/stderr to log file (append mode)
        log_dir = storage.get_timelogs_dir()
        log_file = log_dir / '.worklog-timer.log'
        log_fd = open(log_file, 'a')
        os.dup2(log_fd.fileno(), sys.stdout.fileno())
        os.dup2(log_fd.fileno(), sys.stderr.fileno())

        # Ensure DISPLAY is set for Tkinter
        if 'DISPLAY' not in os.environ:
            os.environ['DISPLAY'] = ':0'

        # Ensure XAUTHORITY is set
        if 'XAUTHORITY' not in os.environ:
            xauth = os.path.expanduser('~/.Xauthority')
            if os.path.exists(xauth):
                os.environ['XAUTHORITY'] = xauth

    # Configure logging
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(message)s',
        level=logging.INFO,
    )

    # Write PID file
    pid_file = storage.get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    # Set up signal handlers
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Save config
    storage.save_config(interval_minutes)

    logger.info(
        f'Daemon started (PID {os.getpid()}, interval={interval_minutes}m, '
        f'foreground={foreground})'
    )

    try:
        _run_loop(interval_minutes)
    finally:
        _cleanup()
        logger.info('Daemon stopped')


def stop_daemon() -> bool:
    """Stop the running daemon.

    Returns:
        True if the daemon was stopped, False if it was not running.
    """
    pid_file = storage.get_pid_file()

    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Already dead
        pid_file.unlink(missing_ok=True)
        return False
    except PermissionError:
        logger.error(f'Permission denied sending SIGTERM to PID {pid}')
        return False

    # Wait up to 5 seconds for the process to exit
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process has exited
            pid_file.unlink(missing_ok=True)
            return True
        time.sleep(0.1)

    # Process still alive after 5 seconds
    logger.warning(f'Daemon (PID {pid}) did not exit within 5 seconds')
    return False


def is_running() -> tuple[bool, int | None]:
    """Check if the daemon is currently running.

    Returns:
        A tuple of (is_running, pid). pid is None if not running.
    """
    pid_file = storage.get_pid_file()

    if not pid_file.exists():
        return (False, None)

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return (False, None)

    try:
        os.kill(pid, 0)
        return (True, pid)
    except ProcessLookupError:
        # Stale PID file
        pid_file.unlink(missing_ok=True)
        return (False, None)
    except PermissionError:
        # Process exists but we can't signal it — assume running
        return (True, pid)
