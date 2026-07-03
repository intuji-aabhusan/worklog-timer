"""
Dark-themed Tkinter popup dialog for worklog entry.

Presents a Catppuccin Mocha–styled window asking the user what they did
during a given time interval.  Auto-skips after a configurable timeout.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def show_popup(
    interval_start: datetime,
    interval_end: datetime,
    timeout_seconds: int = 120,
) -> tuple[str, str]:
    """Show a blocking popup asking the user what they did.

    Parameters
    ----------
    interval_start:
        Start of the work interval.
    interval_end:
        End of the work interval.
    timeout_seconds:
        Seconds before the dialog auto-skips.

    Returns
    -------
    tuple[str, str]
        ``(description, status)`` where *status* is ``"logged"`` or
        ``"skipped"`` and *description* is the user's text (empty string
        when skipped).
    """
    try:
        import tkinter as tk  # noqa: E402 – deferred to detect missing display
    except ImportError:
        logger.warning("tkinter is not available – skipping popup")
        return ("", "skipped")

    # ------------------------------------------------------------------
    # Theme tokens  (Catppuccin Mocha)
    # ------------------------------------------------------------------
    BG = "#1e1e2e"
    SURFACE = "#313244"
    TEXT = "#cdd6f4"
    SUBTEXT = "#a6adc8"
    ENTRY_BG = "#45475a"

    LOG_FG = "#a6e3a1"
    LOG_BG = "#2d4a2d"
    LOG_HOVER = "#3d6a3d"

    SKIP_FG = "#f38ba8"
    SKIP_BG = "#4a2d2d"
    SKIP_HOVER = "#6a3d3d"

    # ------------------------------------------------------------------
    # State held in a mutable container so callbacks can write to it
    # ------------------------------------------------------------------
    result: list[tuple[str, str]] = [("", "skipped")]
    remaining = [timeout_seconds]

    # ------------------------------------------------------------------
    # Build root window
    # ------------------------------------------------------------------
    try:
        root = tk.Tk()
    except tk.TclError:
        logger.warning("Cannot open display – skipping popup")
        return ("", "skipped")

    root.title("Worklog Timer")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.wm_attributes("-topmost", True)
    root.overrideredirect(False)

    # Centre the window on screen
    win_w, win_h = 420, 280
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - win_w) // 2
    y = (screen_h - win_h) // 2
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # ------------------------------------------------------------------
    # Header label
    # ------------------------------------------------------------------
    tk.Label(
        root,
        text="What did you do?",
        font=("Helvetica", 16, "bold"),
        fg=TEXT,
        bg=BG,
    ).pack(pady=(18, 2))

    # ------------------------------------------------------------------
    # Time-window label
    # ------------------------------------------------------------------
    time_fmt = "%H:%M"
    time_text = (
        f"{interval_start.strftime(time_fmt)} → "
        f"{interval_end.strftime(time_fmt)}"
    )
    tk.Label(
        root,
        text=time_text,
        font=("Helvetica", 12),
        fg=SUBTEXT,
        bg=BG,
    ).pack(pady=(0, 10))

    # ------------------------------------------------------------------
    # Text entry (wrapped in a surface-coloured frame for a border effect)
    # ------------------------------------------------------------------
    entry_border = tk.Frame(root, bg=SURFACE, padx=2, pady=2)
    entry_border.pack(padx=20, pady=(0, 10))

    text_entry = tk.Text(
        entry_border,
        height=4,
        width=45,
        font=("Helvetica", 11),
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

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _submit(_event: "tk.Event | None" = None) -> None:
        desc = text_entry.get("1.0", tk.END).strip()
        result[0] = (desc, "logged")
        root.destroy()

    def _skip(_event: "tk.Event | None" = None) -> None:
        result[0] = ("", "skipped")
        root.destroy()

    # ------------------------------------------------------------------
    # Button frame
    # ------------------------------------------------------------------
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=(0, 6))

    def _make_button(
        parent: tk.Frame,
        label: str,
        fg: str,
        bg_normal: str,
        bg_hover: str,
        command,  # noqa: ANN001
    ) -> tk.Label:
        btn = tk.Label(
            parent,
            text=label,
            font=("Helvetica", 11, "bold"),
            fg=fg,
            bg=bg_normal,
            padx=20,
            pady=6,
            cursor="hand2",
        )
        btn.bind("<Enter>", lambda _e: btn.configure(bg=bg_hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg_normal))
        btn.bind("<Button-1>", command)
        return btn

    log_btn = _make_button(
        btn_frame, "✓ Log It", LOG_FG, LOG_BG, LOG_HOVER, _submit,
    )
    log_btn.pack(side=tk.LEFT, padx=(0, 8))

    skip_btn = _make_button(
        btn_frame, "✗ Skip", SKIP_FG, SKIP_BG, SKIP_HOVER, _skip,
    )
    skip_btn.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Countdown label
    # ------------------------------------------------------------------
    countdown_var = tk.StringVar(value=f"Auto-skip in {remaining[0]}s")
    countdown_label = tk.Label(
        root,
        textvariable=countdown_var,
        font=("Helvetica", 9),
        fg=SUBTEXT,
        bg=BG,
    )
    countdown_label.pack(pady=(2, 0))

    def _update_countdown() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            _skip()
            return
        countdown_var.set(f"Auto-skip in {remaining[0]}s")
        root.after(1000, _update_countdown)

    root.after(1000, _update_countdown)

    # ------------------------------------------------------------------
    # Key / protocol bindings
    # ------------------------------------------------------------------
    root.bind("<Control-Return>", _submit)
    root.bind("<Escape>", _skip)
    root.protocol("WM_DELETE_WINDOW", _skip)

    # Focus the text entry
    text_entry.focus_set()

    # ------------------------------------------------------------------
    # Run the event loop (blocks until destroy)
    # ------------------------------------------------------------------
    root.mainloop()

    return result[0]
