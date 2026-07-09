"""Main daemon loop for worklog-timer."""

import datetime
import logging
import os
import signal
import sys
import time

from worklog_timer import display, notifier, popup, storage

logger = logging.getLogger(__name__)

POPUP_TIMEOUT_SECONDS = 120

# Seconds to leave the notification up before showing the popup anyway.
NOTIFY_GRACE_SECONDS = 10

DEFAULT_ANCHOR = '08:45'

# If the next wall-clock slot is closer than this to the previous prompt
# (e.g. right after `worklog open`), skip ahead to the following slot so
# two popups never appear back to back.
MIN_SLOT_GAP_SECONDS = 300

running = True
trigger_popup = False


def parse_anchor(anchor: str) -> int:
    """Parse an ``HH:MM`` anchor time into minutes since midnight.

    Raises:
        ValueError: If the string is not a valid time of day.
    """
    parts = anchor.strip().split(':')
    if len(parts) != 2:
        raise ValueError(f'Invalid anchor time: {anchor!r} (expected HH:MM)')
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ValueError(f'Invalid anchor time: {anchor!r} (expected HH:MM)')
    return hours * 60 + minutes


def parse_overrides(
    specs: 'list[str] | None',
    interval_minutes: int,
    anchor_minutes: int,
) -> dict[int, int]:
    """Parse ``SLOT=TIME`` override specs into a minutes→minutes mapping.

    Each spec moves one grid slot to a custom wall-clock time, e.g.
    ``11:00=10:45``.  The left side must be a time that actually lies on
    the prompt grid; the right side can be any time of day.

    Raises:
        ValueError: On malformed specs or a left side not on the grid.
    """
    overrides: dict[int, int] = {}
    for spec in specs or []:
        slot_str, sep, repl_str = spec.partition('=')
        if not sep:
            raise ValueError(f'Invalid override: {spec!r} (expected SLOT=TIME)')
        slot_m = parse_anchor(slot_str)
        repl_m = parse_anchor(repl_str)
        if (slot_m - anchor_minutes) % interval_minutes != 0:
            before = slot_m - ((slot_m - anchor_minutes) % interval_minutes)
            after = before + interval_minutes
            raise ValueError(
                f'{slot_str.strip()} is not on the prompt grid '
                f'(nearest slots: {before // 60:02d}:{before % 60:02d} and '
                f'{after % 1440 // 60:02d}:{after % 60:02d})'
            )
        overrides[slot_m] = repl_m
    return overrides


def next_slot(
    now: datetime.datetime,
    interval_minutes: int,
    anchor_minutes: int,
    overrides: 'dict[int, int] | None' = None,
    min_gap_seconds: int = 0,
) -> datetime.datetime:
    """Return the next prompt time on the wall-clock grid.

    Slots lie at ``anchor + k * interval`` for every integer k (the grid
    extends across midnight in both directions), so with anchor 08:45 and
    a 45-minute interval the prompts land at 8:45, 9:30, 10:15, …
    regardless of when the daemon started.  *overrides* moves individual
    grid slots to custom times (minutes-since-midnight → replacement).
    """
    overrides = overrides or {}
    first = anchor_minutes % interval_minutes
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    candidates = []
    for day_offset in (0, 1):
        day_start = midnight + datetime.timedelta(days=day_offset)
        for m in range(first, 24 * 60, interval_minutes):
            slot_m = overrides.get(m, m)
            candidates.append(day_start + datetime.timedelta(minutes=slot_m))
    candidates.sort()

    threshold = now + datetime.timedelta(seconds=min_gap_seconds)
    for candidate in candidates:
        if candidate > now and candidate >= threshold:
            return candidate
    raise RuntimeError('No upcoming slot found')  # unreachable: tomorrow always has slots


def _handle_signal(signum, frame):
    """Handle SIGTERM/SIGINT: stop the loop and close any open popup."""
    global running
    running = False
    popup.terminate_active()


def _handle_sigusr1(signum, frame):
    """Handle SIGUSR1 to trigger an immediate popup (for ``worklog open``)."""
    global trigger_popup
    trigger_popup = True


def _cleanup():
    """Remove the PID file if it exists."""
    storage.get_pid_file().unlink(missing_ok=True)


def _sleep_until(target: datetime.datetime) -> str:
    """Sleep until *target*, waking every second to check for signals.

    Comparing against the wall clock (rather than counting seconds) means
    a suspend/resume can't push the schedule late — the slot fires as
    soon as the machine wakes past it.

    Returns:
        'elapsed' when the target time was reached, 'manual' when SIGUSR1
        requested an immediate popup, or 'shutdown' when the daemon is
        stopping.
    """
    global trigger_popup

    while True:
        if not running:
            return 'shutdown'
        if trigger_popup:
            trigger_popup = False
            return 'manual'
        if storage.now_npt() >= target:
            return 'elapsed'
        time.sleep(1)


def _wait_for_notification_click(notify_proc) -> bool:
    """Give the user a short grace period to click the notification.

    Returns True if the "Open" action was clicked, False otherwise.
    Always leaves *notify_proc* terminated/reaped.
    """
    global trigger_popup

    clicked = False
    try:
        for _ in range(NOTIFY_GRACE_SECONDS):
            if not running or trigger_popup:
                break
            if notify_proc.poll() is not None:
                try:
                    stdout = notify_proc.stdout.read().decode().strip()
                except Exception:
                    stdout = ''
                clicked = stdout == 'open'
                break
            time.sleep(1)
    finally:
        if notify_proc.poll() is None:
            notify_proc.terminate()
        try:
            notify_proc.stdout.close()
        except Exception:
            pass

    return clicked


def _show_prompt(interval_start, interval_end, interval_minutes, manual=False):
    """Notify, show the popup, and save the resulting entry.

    The graphical environment (DISPLAY/XAUTHORITY/…) is re-discovered on
    every call: the daemon usually starts at login before the session is
    fully up, and the Xwayland auth file rotates per session, so values
    captured at startup go stale.
    """
    global trigger_popup

    env = display.build_gui_env()

    # Report the real elapsed window in the notification — with slot
    # scheduling the first window after daemon start can be shorter than
    # the configured interval.
    elapsed_minutes = max(
        1, round((interval_end - interval_start).total_seconds() / 60)
    )

    opened_via_click = False
    if not manual:
        notify_proc = notifier.notify_check_in(elapsed_minutes, env=env)
        if notify_proc is not None:
            opened_via_click = _wait_for_notification_click(notify_proc)

    if not running:
        return

    try:
        description, status = popup.show_popup(
            interval_start,
            interval_end,
            timeout_seconds=POPUP_TIMEOUT_SECONDS,
            env=env,
        )
    except Exception:
        logger.warning('Popup failed', exc_info=True)
        description, status = '', 'skipped'

    # Swallow any SIGUSR1 that arrived while the popup was already open,
    # so `worklog open` during a popup doesn't queue a second one.
    trigger_popup = False

    storage.append_entry(
        interval_start=interval_start,
        interval_end=interval_end,
        description=description,
        status=status,
        interval_minutes=interval_minutes,
    )

    src = '(manual)' if manual else '(click)' if opened_via_click else ''
    logger.info(
        f'[{status}] {interval_start.strftime("%H:%M")}–'
        f'{interval_end.strftime("%H:%M")}: '
        f'{description or "(skipped)"} {src}'.rstrip()
    )


def _run_loop(
    interval_minutes: int,
    anchor_minutes: int,
    overrides: dict[int, int],
) -> None:
    """Main loop: sleep until the next wall-clock slot (interruptible by
    SIGUSR1), then notify, show the popup, and save the entry."""
    prompted = False

    while running:
        interval_start = storage.now_npt()

        # The back-to-back guard only makes sense right after a prompt —
        # applying it on the first iteration would make a daemon restart
        # silently swallow a slot due within the next 5 minutes.
        target = next_slot(
            interval_start,
            interval_minutes,
            anchor_minutes,
            overrides=overrides,
            min_gap_seconds=MIN_SLOT_GAP_SECONDS if prompted else 0,
        )
        reason = _sleep_until(target)
        if reason == 'shutdown':
            return

        _show_prompt(
            interval_start,
            storage.now_npt(),
            interval_minutes,
            manual=(reason == 'manual'),
        )
        prompted = True


def run_daemon(
    interval_minutes: int = 45,
    anchor: str = DEFAULT_ANCHOR,
    overrides: 'list[str] | None' = None,
    foreground: bool = False,
) -> None:
    """Main entry point for the daemon process.

    Args:
        interval_minutes: Minutes between check-in prompts.
        anchor: HH:MM wall-clock time the prompt grid is anchored to.
        overrides: SLOT=TIME specs moving individual grid slots.
        foreground: If True, run in foreground (for systemd). Otherwise daemonize.
    """
    # Validate before forking so bad args fail loudly in the caller's terminal
    anchor_minutes = parse_anchor(anchor)
    override_map = parse_overrides(overrides, interval_minutes, anchor_minutes)

    if not foreground:
        # --- Double-fork daemonization ---
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            logger.error(f'First fork failed: {e}')
            sys.exit(1)

        os.setsid()
        os.umask(0o022)

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
    storage.save_config(interval_minutes, anchor, overrides)

    logger.info(
        f'Daemon started (PID {os.getpid()}, interval={interval_minutes}m, '
        f'anchor={anchor}, overrides={overrides or []}, foreground={foreground})'
    )

    try:
        _run_loop(interval_minutes, anchor_minutes, override_map)
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
