"""Desktop notifications and a gentle chime for worklog-timer.

Notifications go through ``notify-send``.  When the installed version
supports ``--action`` (libnotify ≥ 0.8), the notification gets an "Open"
button and the daemon monitors the process to open the popup as soon as
the user clicks.

The alert sound is a soft three-note bell arpeggio (C5–E5–G5) synthesised
once with the stdlib and cached in ``~/.timelogs/``, then played through
pw-play / paplay / aplay — whichever exists.  No harsh system sounds.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from worklog_timer import storage

logger = logging.getLogger(__name__)

# Bump when the synthesis parameters change so the cached file regenerates.
_CHIME_VERSION = 1
_SAMPLE_RATE = 44100

# Sound players to try, in order of preference.
_PLAYERS = ('pw-play', 'paplay', 'aplay')

# Cache whether notify-send supports --action (None = untested)
_notify_send_supports_action: bool | None = None


# ----------------------------------------------------------------------
# Chime synthesis
# ----------------------------------------------------------------------

def _chime_path() -> Path:
    return storage.get_timelogs_dir() / f'.chime-v{_CHIME_VERSION}.wav'


def _synthesize_chime(path: Path) -> None:
    """Render a soft bell arpeggio to a 16-bit mono WAV file.

    Three notes (C5, E5, G5) staggered 280 ms apart, each a bell-like
    stack of three partials with a 15 ms attack and a slow exponential
    decay.  Peak amplitude is kept low so the result is a quiet,
    rounded chime rather than an alarm.
    """
    duration = 2.6
    notes = ((523.25, 0.00), (659.25, 0.28), (783.99, 0.56))
    # (frequency multiplier, relative amplitude) — slightly detuned upper
    # partials give a warmer, less synthetic tone.
    partials = ((1.0, 1.00), (2.0, 0.40), (2.98, 0.15))

    total = int(duration * _SAMPLE_RATE)
    samples = [0.0] * total
    two_pi = 2.0 * math.pi

    for freq, onset in notes:
        start = int(onset * _SAMPLE_RATE)
        for i in range(total - start):
            t = i / _SAMPLE_RATE
            envelope = min(t / 0.015, 1.0) * math.exp(-t / 0.5)
            value = 0.0
            for mult, amp in partials:
                value += amp * math.sin(two_pi * freq * mult * t)
            samples[start + i] += 0.16 * envelope * value

    # Soft ceiling: never louder than half full-scale.
    peak = max(max(samples), -min(samples), 1e-9)
    scale = min(0.5 / peak, 1.0)

    frames = bytearray()
    for s in samples:
        clipped = max(-1.0, min(1.0, s * scale))
        frames += struct.pack('<h', int(clipped * 32767))

    tmp_path = path.with_suffix('.wav.tmp')
    with wave.open(str(tmp_path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    os.replace(tmp_path, path)


def _ensure_chime() -> Path | None:
    """Return the path to the cached chime, synthesising it if needed."""
    path = _chime_path()
    if path.exists():
        return path
    try:
        _synthesize_chime(path)
        logger.info(f'Synthesised chime at {path}')
        return path
    except Exception:
        logger.warning('Failed to synthesise chime', exc_info=True)
        return None


def play_sound(env: dict[str, str] | None = None) -> None:
    """Play the notification chime (fire-and-forget)."""
    sound_file = _ensure_chime()
    if sound_file is None:
        return

    for player in _PLAYERS:
        if not shutil.which(player):
            continue
        try:
            subprocess.Popen(
                [player, str(sound_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            return
        except OSError:
            continue

    logger.debug('No sound player available (tried %s)', ', '.join(_PLAYERS))


# ----------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------

def _check_notify_send_action_support() -> bool:
    """Return True if notify-send supports the ``--action`` flag."""
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
    env: dict[str, str] | None = None,
) -> subprocess.Popen | None:
    """Send a desktop notification via ``notify-send``.

    When *wait_for_action* is True and notify-send supports ``--action``,
    the notification gets an "Open" button and the returned
    :class:`subprocess.Popen` handle can be monitored: notify-send prints
    the action key to stdout and exits when the user clicks.

    Returns None in fire-and-forget mode or on failure.
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
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
            )

        subprocess.run(cmd, capture_output=True, timeout=10, env=env)
    except FileNotFoundError:
        logger.debug('notify-send not found')
    except Exception:
        logger.debug('Failed to send notification', exc_info=True)

    return None


def notify_check_in(
    interval_minutes: int,
    env: dict[str, str] | None = None,
) -> subprocess.Popen | None:
    """Send a check-in notification with the chime.

    Returns the Popen handle for the notification process when
    action-aware notifications are supported, so the daemon can open the
    popup immediately if the user clicks.
    """
    proc = send_notification(
        '⏱ Worklog Timer',
        f'What did you do in the last {interval_minutes} minutes?',
        wait_for_action=True,
        env=env,
    )
    play_sound(env=env)
    return proc
