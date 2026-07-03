"""Main daemon loop for worklog-timer."""

import glob
import logging
import os
import signal
import sys
import time

from worklog_timer import notifier, popup, storage

logger = logging.getLogger(__name__)

running = True
trigger_popup = False


def _find_xauthority() -> str | None:
    """Discover the X authority file for the current session.

    On Wayland (GNOME/Mutter with Xwayland), the auth file lives at a
    dynamic path like ``/run/user/UID/.mutter-Xwaylandauth.XXXX`` rather
    than the traditional ``~/.Xauthority``.

    Returns:
        The path to the auth file, or None if none was found.
    """
    # 1. Check XDG_RUNTIME_DIR for Mutter Xwayland auth files
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    candidates = glob.glob(os.path.join(runtime_dir, '.mutter-Xwaylandauth.*'))
    for path in candidates:
        if os.path.isfile(path):
            return path

    # 2. Fallback to traditional ~/.Xauthority
    xauth = os.path.expanduser('~/.Xauthority')
    if os.path.exists(xauth):
        return xauth

    return None


def _handle_signal(signum, frame):
    """Handle SIGTERM/SIGINT by setting the running flag to False."""
    global running
    running = False


def _handle_sigusr1(signum, frame):
    """Handle SIGUSR1 to trigger an immediate popup (for ``worklog open``)."""
    global trigger_popup
    trigger_popup = True


def _cleanup():
    """Remove the PID file if it exists."""
    pid_file = storage.get_pid_file()
    if pid_file.exists():
        pid_file.unlink()


def _show_prompt(interval_start, interval_end, interval_minutes):
    """Send notification, show popup, save entry.

    This is the core prompt logic extracted so it can be called both from
    the regular timer loop and from the manual SIGUSR1 trigger.
    """
    # Send notification + sound, get Popen handle for action monitoring
    notifier.notify_check_in(interval_minutes)

    # Show popup
    try:
        description, status = popup.show_popup(
            interval_start, interval_end, timeout_seconds=120
        )
    except Exception:
        logger.warning('Popup failed', exc_info=True)
        description, status = '', 'skipped'

    # Save entry
    storage.append_entry(
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
def _run_loop(interval_minutes: int) -> None:
    """Main loop: sleep, notify, show popup, save entry.

    Flow per iteration:
    1. Sleep for *interval_minutes* (interruptible by SIGUSR1).
    2. Send a desktop notification with an "Open" action button.
    3. Wait a short grace period (10 s) for the user to click the
       notification.  If they click → open popup.  If not → open
       popup anyway (original behaviour).

    SIGUSR1 (``worklog open``) can interrupt the sleep at any time
    and immediately show the popup.
    """
    global running, trigger_popup

    while running:
        interval_start = storage.now_npt()

        # --- Phase 1: Sleep for the configured interval ---------------
        # Check every second for shutdown or manual trigger.
        interrupted = False
        for _ in range(interval_minutes * 60):
            if not running:
                return

            if trigger_popup:
                trigger_popup = False
                now = storage.now_npt()
                try:
                    description, status = popup.show_popup(
                        interval_start, now, timeout_seconds=120
                    )
                except Exception:
                    logger.warning('Popup failed', exc_info=True)
                    description, status = '', 'skipped'
                storage.append_entry(
                    interval_start=interval_start,
                    interval_end=now,
                    description=description,
                    status=status,
                    interval_minutes=interval_minutes,
                )
                logger.info(
                    f'[{status}] {interval_start.strftime("%H:%M")}–'
                    f'{now.strftime("%H:%M")}: {description or "(manual)"}'
                )
                interrupted = True
                break

            time.sleep(1)

        if interrupted:
            continue

        interval_end = storage.now_npt()

        # --- Phase 2: Send notification + sound ----------------------
        notify_proc = notifier.notify_check_in(interval_minutes)

        # --- Phase 3: Grace period — wait for notification click ------
        # Give the user up to 10 seconds to click the notification
        # before we show the popup ourselves.
        opened_via_click = False
        if notify_proc is not None:
            for _ in range(10):
                if not running:
                    notify_proc.terminate()
                    return

                # SIGUSR1 during grace period
                if trigger_popup:
                    trigger_popup = False
                    notify_proc.terminate()
                    break

                if notify_proc.poll() is not None:
                    # notify-send exited — read which action was clicked
                    try:
                        stdout = notify_proc.stdout.read().decode().strip()
                        notify_proc.stdout.close()
                    except Exception:
                        stdout = ''

                    if stdout == 'open':
                        opened_via_click = True
                    break

                time.sleep(1)
            else:
                # Grace period expired — kill the notification process
                if notify_proc.poll() is None:
                    notify_proc.terminate()
                    try:
                        notify_proc.stdout.close()
                    except Exception:
                        pass

        # --- Phase 4: Show the popup ----------------------------------
        # Whether the user clicked or not, show the popup now.
        try:
            description, status = popup.show_popup(
                interval_start, interval_end, timeout_seconds=120
            )
        except Exception:
            logger.warning('Popup failed', exc_info=True)
            description, status = '', 'skipped'

        storage.append_entry(
            interval_start=interval_start,
            interval_end=interval_end,
            description=description,
            status=status,
            interval_minutes=interval_minutes,
        )

        src = '(click)' if opened_via_click else ''
        logger.info(
            f'[{status}] {interval_start.strftime("%H:%M")}–'
            f'{interval_end.strftime("%H:%M")}: '
            f'{description or "(skipped)"} {src}'
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
        devnull_fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull_fd, sys.stdin.fileno())
        os.close(devnull_fd)

        # Redirect stdout/stderr to log file (append mode)
        log_dir = storage.get_timelogs_dir()
        log_file = log_dir / '.worklog-timer.log'
        log_fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log_fd, sys.stdout.fileno())
        os.dup2(log_fd, sys.stderr.fileno())
        os.close(log_fd)


    # Ensure DISPLAY is set for Tkinter
    if 'DISPLAY' not in os.environ:
        os.environ['DISPLAY'] = ':0'

    # Ensure XAUTHORITY is set – on Wayland (GNOME/Mutter) the auth file
    # lives at a dynamic path like /run/user/UID/.mutter-Xwaylandauth.XXXX
    # instead of ~/.Xauthority.  Discover it at runtime.
    if 'XAUTHORITY' not in os.environ:
        xauth = _find_xauthority()
        if xauth:
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
    signal.signal(signal.SIGUSR1, _handle_sigusr1)

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


def trigger_open() -> bool:
    """Send SIGUSR1 to the running daemon to trigger an immediate popup.

    This is used by ``worklog open`` to manually open the worklog entry
    popup at any time, without waiting for the next scheduled interval.

    Returns:
        True if the signal was sent successfully, False otherwise.
    """
    pid_file = storage.get_pid_file()

    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False

    try:
        os.kill(pid, signal.SIGUSR1)
        return True
    except (ProcessLookupError, PermissionError):
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

