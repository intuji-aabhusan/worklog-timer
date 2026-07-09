"""Runtime discovery of the graphical session environment.

The daemon typically starts at login, *before* the graphical session is
fully up.  On GNOME Wayland the Xwayland auth file
(``/run/user/UID/.mutter-Xwaylandauth.XXXXXX``) is created a moment after
login and is rotated on every new session, so any value captured at daemon
startup goes stale.  Everything here is therefore re-discovered on every
call — never cached.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path


def _runtime_dir() -> str:
    return os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'


def find_xauthority() -> str | None:
    """Return the current X authority file, or None if none exists.

    Prefers the newest Mutter Xwayland auth file (rotated per session),
    then common fixed locations.
    """
    runtime_dir = _runtime_dir()

    mutter_files = [
        p for p in glob.glob(os.path.join(runtime_dir, '.mutter-Xwaylandauth.*'))
        if os.path.isfile(p)
    ]
    if mutter_files:
        return max(mutter_files, key=lambda p: os.path.getmtime(p))

    for candidate in (
        os.path.join(runtime_dir, 'Xauthority'),
        os.path.join(runtime_dir, 'gdm', 'Xauthority'),
        os.path.expanduser('~/.Xauthority'),
    ):
        if os.path.isfile(candidate):
            return candidate

    return None


def _display_socket_exists(display: str) -> bool:
    """Check whether the X socket for a DISPLAY value like ':0' exists."""
    name = display.split(':')[-1].split('.')[0]
    return os.path.exists(f'/tmp/.X11-unix/X{name}')


def find_display() -> str | None:
    """Return a DISPLAY value derived from the X sockets in /tmp/.X11-unix."""
    sockets = sorted(glob.glob('/tmp/.X11-unix/X*'))
    for sock in sockets:
        number = os.path.basename(sock)[1:]
        if number.isdigit():
            return f':{number}'
    return None


def find_wayland_display() -> str | None:
    """Return the name of the first Wayland socket in the runtime dir."""
    for sock in sorted(glob.glob(os.path.join(_runtime_dir(), 'wayland-*'))):
        if not sock.endswith('.lock'):
            return os.path.basename(sock)
    return None


def build_gui_env() -> dict[str, str]:
    """Return a copy of os.environ with fresh graphical-session variables.

    Suitable for spawning GUI helpers (popup subprocess, notify-send,
    sound players).  Values already present in the environment are kept
    only if they still point at something real.
    """
    env = dict(os.environ)

    display = env.get('DISPLAY')
    if not display or not _display_socket_exists(display):
        display = find_display() or ':0'
    env['DISPLAY'] = display

    xauth = env.get('XAUTHORITY')
    if not xauth or not os.path.isfile(xauth):
        found = find_xauthority()
        if found:
            env['XAUTHORITY'] = found
        else:
            env.pop('XAUTHORITY', None)

    if not env.get('WAYLAND_DISPLAY'):
        wayland = find_wayland_display()
        if wayland:
            env['WAYLAND_DISPLAY'] = wayland

    if not env.get('DBUS_SESSION_BUS_ADDRESS'):
        bus = Path(_runtime_dir()) / 'bus'
        if bus.exists():
            env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={bus}'

    return env
