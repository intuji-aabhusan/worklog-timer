#!/usr/bin/env python3
"""
Dark-themed Tkinter popup dialog for worklog entry.

The public API (:func:`show_popup`) runs the dialog in an isolated
subprocess: this file re-executed with ``--start/--end/--timeout`` args.
That buys three things over running Tk inside the daemon process:

* A fresh ``DISPLAY``/``XAUTHORITY`` environment applies on every popup
  (the Xwayland auth file rotates per login session).
* A Tk crash or hang can never take the daemon down — the parent
  enforces a hard timeout and kills the child.
* Each dialog gets a pristine Tcl interpreter (repeated in-process
  ``tk.Tk()`` create/destroy cycles are notoriously flaky).

The child prints a single JSON object to stdout:
``{"description": "...", "status": "logged"|"skipped"}``.

This module is intentionally self-contained (stdlib only, no package
imports) so the child can run it directly as a script.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120

# Extra seconds the parent waits beyond the dialog's own auto-skip
# timeout before force-killing the child.
_HARD_KILL_GRACE = 30

# Exit code the child uses when it cannot open the display.
_EXIT_NO_DISPLAY = 3

# The currently running popup subprocess, if any.  The daemon's signal
# handler uses terminate_active() so `worklog stop` also closes an open
# popup instead of leaving it orphaned.
_active_proc: subprocess.Popen | None = None


# ----------------------------------------------------------------------
# Parent-side API
# ----------------------------------------------------------------------

def show_popup(
    interval_start: datetime,
    interval_end: datetime,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Show the worklog popup in an isolated subprocess.

    Parameters
    ----------
    interval_start:
        Start of the work interval.
    interval_end:
        End of the work interval.
    timeout_seconds:
        Seconds before the dialog auto-skips.
    env:
        Environment for the child process (pass a fresh GUI env from
        :func:`worklog_timer.display.build_gui_env`).  ``None`` inherits
        the parent's environment.

    Returns
    -------
    tuple[str, str]
        ``(description, status)`` where *status* is ``"logged"`` or
        ``"skipped"`` and *description* is the user's text (empty string
        when skipped).  Any failure degrades to ``("", "skipped")``.
    """
    global _active_proc

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        '--start', interval_start.isoformat(),
        '--end', interval_end.isoformat(),
        '--timeout', str(timeout_seconds),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError:
        logger.warning('Failed to spawn popup subprocess', exc_info=True)
        return ('', 'skipped')

    _active_proc = proc
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds + _HARD_KILL_GRACE)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        logger.warning('Popup subprocess hung and was killed')
        return ('', 'skipped')
    finally:
        _active_proc = None

    err_text = stderr.decode(errors='replace').strip()

    if proc.returncode != 0:
        if proc.returncode == _EXIT_NO_DISPLAY:
            logger.warning('Popup could not open display: %s', err_text[-300:])
        else:
            logger.warning(
                'Popup subprocess exited with code %s: %s',
                proc.returncode, err_text[-300:],
            )
        return ('', 'skipped')

    try:
        data = json.loads(stdout.decode())
        description = str(data.get('description', '')).strip()
        status = data.get('status')
    except (ValueError, UnicodeDecodeError, AttributeError):
        logger.warning('Popup subprocess returned invalid output: %r', stdout[:200])
        return ('', 'skipped')

    if status != 'logged' or not description:
        return ('', 'skipped')
    return (description, 'logged')


def terminate_active() -> None:
    """Terminate the popup subprocess if one is currently showing."""
    proc = _active_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


# ----------------------------------------------------------------------
# Child-side dialog
# ----------------------------------------------------------------------

def _run_dialog(
    interval_start: datetime,
    interval_end: datetime,
    timeout_seconds: int,
) -> tuple[str, str]:
    """Build and run the Tk dialog. Runs in the child process only."""
    import tkinter as tk

    # Theme tokens (Catppuccin Mocha)
    BG = '#1e1e2e'
    SURFACE = '#313244'
    TEXT = '#cdd6f4'
    SUBTEXT = '#a6adc8'
    ENTRY_BG = '#45475a'
    WARN = '#f9e2af'

    LOG_FG = '#a6e3a1'
    LOG_BG = '#2d4a2d'
    LOG_HOVER = '#3d6a3d'

    SKIP_FG = '#f38ba8'
    SKIP_BG = '#4a2d2d'
    SKIP_HOVER = '#6a3d3d'

    result: list[tuple[str, str]] = [('', 'skipped')]
    remaining = [timeout_seconds]

    root = tk.Tk()

    # Withdraw while we configure — window-type hints must be set before
    # the window is first mapped for the WM to honour them.
    root.withdraw()
    root.title('Worklog Timer')
    root.configure(bg=BG)
    root.resizable(False, False)
    try:
        # Mark as a dialog so the WM keeps it floating/centred/on-top.
        root.attributes('-type', 'dialog')
    except tk.TclError:
        pass
    root.attributes('-topmost', True)

    win_w, win_h = 440, 300
    x = (root.winfo_screenwidth() - win_w) // 2
    y = (root.winfo_screenheight() - win_h) // 3
    root.geometry(f'{win_w}x{win_h}+{x}+{y}')

    # Header
    tk.Label(
        root,
        text='What did you do?',
        font=('Helvetica', 16, 'bold'),
        fg=TEXT,
        bg=BG,
    ).pack(pady=(18, 2))

    # Time window
    time_text = (
        f'{interval_start.strftime("%H:%M")} → '
        f'{interval_end.strftime("%H:%M")}'
    )
    tk.Label(
        root,
        text=time_text,
        font=('Helvetica', 12),
        fg=SUBTEXT,
        bg=BG,
    ).pack(pady=(0, 10))

    # Text entry (wrapped in a surface-coloured frame for a border effect)
    entry_border = tk.Frame(root, bg=SURFACE, padx=2, pady=2)
    entry_border.pack(padx=20, pady=(0, 8))

    text_entry = tk.Text(
        entry_border,
        height=4,
        width=46,
        font=('Helvetica', 11),
        bg=ENTRY_BG,
        fg=TEXT,
        insertbackground=TEXT,
        relief=tk.FLAT,
        padx=8,
        pady=8,
        wrap=tk.WORD,
        highlightthickness=0,
        borderwidth=0,
    )
    text_entry.pack()

    # Callbacks
    def _flash_entry() -> None:
        entry_border.configure(bg=SKIP_FG)
        root.after(250, lambda: entry_border.configure(bg=SURFACE))

    def _submit(_event: 'tk.Event | None' = None) -> str:
        desc = text_entry.get('1.0', tk.END).strip()
        if not desc:
            _flash_entry()
            return 'break'
        result[0] = (desc, 'logged')
        root.destroy()
        return 'break'

    def _skip(_event: 'tk.Event | None' = None) -> None:
        result[0] = ('', 'skipped')
        root.destroy()

    # Buttons
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=(0, 4))

    def _make_button(label, fg, bg_normal, bg_hover, command):  # noqa: ANN001
        btn = tk.Label(
            btn_frame,
            text=label,
            font=('Helvetica', 11, 'bold'),
            fg=fg,
            bg=bg_normal,
            padx=20,
            pady=6,
            cursor='hand2',
        )
        btn.bind('<Enter>', lambda _e: btn.configure(bg=bg_hover))
        btn.bind('<Leave>', lambda _e: btn.configure(bg=bg_normal))
        btn.bind('<Button-1>', command)
        return btn

    _make_button('✓ Log It', LOG_FG, LOG_BG, LOG_HOVER, _submit).pack(
        side=tk.LEFT, padx=(0, 8),
    )
    _make_button('✗ Skip', SKIP_FG, SKIP_BG, SKIP_HOVER, _skip).pack(side=tk.LEFT)

    # Hint + countdown
    tk.Label(
        root,
        text='Enter to log  ·  Shift+Enter for newline  ·  Esc to skip',
        font=('Helvetica', 9),
        fg=SUBTEXT,
        bg=BG,
    ).pack(pady=(4, 0))

    countdown_var = tk.StringVar(value=f'Auto-skip in {remaining[0]}s')
    countdown_label = tk.Label(
        root,
        textvariable=countdown_var,
        font=('Helvetica', 9),
        fg=SUBTEXT,
        bg=BG,
    )
    countdown_label.pack(pady=(2, 0))

    def _tick() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            _skip()
            return
        countdown_var.set(f'Auto-skip in {remaining[0]}s')
        countdown_label.configure(fg=WARN if remaining[0] <= 15 else SUBTEXT)
        root.after(1000, _tick)

    root.after(1000, _tick)

    # Typing resets the auto-skip countdown so it can never dismiss the
    # dialog out from under the user mid-sentence.
    def _on_activity(_event: 'tk.Event') -> None:
        remaining[0] = timeout_seconds

    text_entry.bind('<Key>', _on_activity, add='+')

    # Key / protocol bindings.  Plain Return submits from the text widget
    # (the more specific Shift-Return binding falls through to the class
    # binding, which inserts the newline).
    text_entry.bind('<Return>', _submit)
    text_entry.bind('<Shift-Return>', lambda _e: None)
    root.bind('<Control-Return>', _submit)
    root.bind('<Escape>', _skip)
    root.protocol('WM_DELETE_WINDOW', _skip)

    # Present the window and fight for focus.  Window managers (GNOME in
    # particular) apply focus-stealing prevention to windows mapped by
    # background processes, so lift/focus is re-asserted a few times.
    root.deiconify()

    def _grab_focus() -> None:
        try:
            root.lift()
            root.attributes('-topmost', True)
            root.focus_force()
            text_entry.focus_set()
            root.grab_set()
        except tk.TclError:
            pass  # window already destroyed

    _grab_focus()
    root.after(150, _grab_focus)
    root.after(700, _grab_focus)

    root.mainloop()
    return result[0]


def _child_main() -> int:
    parser = argparse.ArgumentParser(description='Worklog popup (internal)')
    parser.add_argument('--start', required=True, help='Interval start (ISO 8601)')
    parser.add_argument('--end', required=True, help='Interval end (ISO 8601)')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    try:
        interval_start = datetime.fromisoformat(args.start)
        interval_end = datetime.fromisoformat(args.end)
    except ValueError as e:
        print(f'Invalid timestamp: {e}', file=sys.stderr)
        return 2

    try:
        import tkinter as tk
    except ImportError:
        print('tkinter is not available', file=sys.stderr)
        return _EXIT_NO_DISPLAY

    try:
        description, status = _run_dialog(
            interval_start, interval_end, max(args.timeout, 5),
        )
    except tk.TclError as e:
        # Covers "couldn't connect to display" and similar X errors.
        print(f'Tk error: {e}', file=sys.stderr)
        return _EXIT_NO_DISPLAY

    print(json.dumps({'description': description, 'status': status}))
    return 0


if __name__ == '__main__':
    sys.exit(_child_main())
