"""Desktop notifications and sound alerts for worklog-timer."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Sound files to try, in order of preference
_SOUND_FILES = [
    Path('/usr/share/sounds/freedesktop/stereo/message-new-instant.ogg'),
    Path('/usr/share/sounds/freedesktop/stereo/bell.oga'),
    Path('/usr/share/sounds/freedesktop/stereo/complete.oga'),
]


def send_notification(
    title: str,
    message: str,
    urgency: str = 'normal',
    icon: str = 'dialog-information',
) -> None:
    """Send a desktop notification via notify-send."""
    try:
        subprocess.run(
            ['notify-send', title, message, f'--urgency={urgency}', f'--icon={icon}'],
            capture_output=True,
        )
    except Exception:
        pass


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
                subprocess.Popen([player, sound_file])
                return
            except FileNotFoundError:
                continue

        logger.debug('No sound player available (tried paplay, aplay)')
    except Exception:
        pass


def notify_check_in(interval_minutes: int) -> None:
    """Send a check-in notification with sound."""
    send_notification(
        '⏱ Worklog Timer',
        f'What did you do in the last {interval_minutes} minutes?',
    )
    play_sound()
