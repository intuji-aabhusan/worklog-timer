"""Desktop notifications and sound alerts for worklog-timer.

Supports two notification backends:

1. **notify-send with --action** (notify-send ≥ 0.7.9 / libnotify ≥ 0.8):
   Sends a notification with an "Open" action button.  When the user clicks
   the button (or the notification body on some DEs), ``notify-send`` prints
   the action key to stdout and exits.  The daemon monitors this to know
   when to raise the popup window.

2. **Plain notify-send** (fallback):
   If the ``--action`` flag is not supported, falls back to a simple
   notification without click-to-open support.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Sound files to try, in order of preference
_SOUND_FILES = [
    Path('/usr/share/sounds/freedesktop/stereo/message-new-instant.ogg'),
    Path('/usr/share/sounds/freedesktop/stereo/bell.oga'),
    Path('/usr/share/sounds/freedesktop/stereo/complete.oga'),
]

# Cache whether notify-send supports --action (None = untested)
_notify_send_supports_action: bool | None = None


def _check_notify_send_action_support() -> bool:
    """Return True if notify-send supports the ``--action`` flag.

    The ``--action`` flag was introduced in libnotify 0.8 / notify-send 0.7.9.
    We probe by running ``notify-send --help`` and checking the output.
    """
    global _notify_send_supports_action
    if _notify_send_supports_action is not None:
        return _notify_send_supports_action

    if not shutil.which('notify-send'):
        _notify_send_supports_action = False
        return False

    try:
        result = subprocess.run(
            ['notify-send', '--help'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _notify_send_supports_action = '--action' in result.stdout
    except Exception:
        _notify_send_supports_action = False

    return _notify_send_supports_action


def send_notification(
    title: str,
    message: str,
    urgency: str = 'normal',
    icon: str = 'dialog-information',
    wait_for_action: bool = False,
) -> subprocess.Popen | None:
    """Send a desktop notification via ``notify-send``.

    Parameters
    ----------
    title:
        Notification title.
    message:
        Notification body.
    urgency:
        ``'low'``, ``'normal'``, or ``'critical'``.
    icon:
        Icon name or path.
    wait_for_action:
        If True **and** notify-send supports ``--action``, spawn in
        non-blocking mode with ``--wait`` so that clicking the notification
        prints the action key to stdout.  Returns the :class:`Popen` handle
        so the caller can monitor it.

    Returns
    -------
    subprocess.Popen | None
        The Popen handle when *wait_for_action* is True and the action flag
        is supported; ``None`` otherwise.
    """
    try:
        cmd = [
            'notify-send',
            title,
            message,
            f'--urgency={urgency}',
            f'--icon={icon}',
        ]

        if wait_for_action and _check_notify_send_action_support():
            cmd += [
                '--action=open=Open Worklog',
                '--wait',
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            return proc

        # Fire-and-forget fallback
        subprocess.run(cmd, capture_output=True, timeout=10)
    except FileNotFoundError:
        logger.debug('notify-send not found')
    except Exception:
        logger.debug('Failed to send notification', exc_info=True)

    return None


def play_sound() -> None:
    """Play a notification sound using paplay or aplay (fire-and-forget)."""
    try:
        # Find the first available sound file
        sound_file = None
        for path in _SOUND_FILES:
            if path.exists():
                sound_file = str(path)
                break

        if sound_file is None:
            logger.debug('No sound files found')
            return

        # Try paplay first, then aplay
        for player in ('paplay', 'aplay'):
            try:
                subprocess.Popen(
                    [player, sound_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
            except FileNotFoundError:
                continue

        logger.debug('No sound player available (tried paplay, aplay)')
    except Exception:
        pass


def notify_check_in(interval_minutes: int) -> subprocess.Popen | None:
    """Send a check-in notification with sound.

    Returns
    -------
    subprocess.Popen | None
        The Popen handle for the notification process (if action-aware
        notifications are supported), so the daemon can monitor whether
        the user clicked the notification.
    """
    proc = send_notification(
        '⏱ Worklog Timer',
        f'What did you do in the last {interval_minutes} minutes?',
        wait_for_action=True,
    )
    play_sound()
    return proc
