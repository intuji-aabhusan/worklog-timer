"""Storage module for worklog-timer.

Handles reading and writing JSONL worklog entries to ~/.timelogs/.
Each day gets its own file named YYYY-MM-DD.jsonl, where each line
is a JSON object representing one worklog entry.
"""

import datetime
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Nepal Standard Time (UTC+05:45)
NPT = datetime.timezone(datetime.timedelta(hours=5, minutes=45))


def now_npt() -> datetime.datetime:
    """Return the current datetime in Nepal Standard Time (NPT, UTC+05:45)."""
    return datetime.datetime.now(tz=NPT)


def get_timelogs_dir() -> Path:
    """Return the path to ~/.timelogs/, creating it if it does not exist.

    Returns:
        Path: The timelogs directory path.
    """
    timelogs_dir = Path.home() / ".timelogs"
    timelogs_dir.mkdir(parents=True, exist_ok=True)
    try:
        timelogs_dir.chmod(0o700)
    except OSError:
        pass
    return timelogs_dir


def get_log_file(date: "datetime.date | None" = None) -> Path:
    """Return the path to the JSONL log file for the given date.

    If no date is provided, defaults to today in NPT.

    Args:
        date: The date for which to get the log file. Defaults to today in NPT.

    Returns:
        Path: The path to the YYYY-MM-DD.jsonl file.
    """
    if date is None:
        date = now_npt().date()
    filename = f"{date.isoformat()}.jsonl"
    return get_timelogs_dir() / filename


def append_entry(
    interval_start: datetime.datetime,
    interval_end: datetime.datetime,
    description: str,
    status: str,
    interval_minutes: int,
) -> dict:
    """Append a single worklog entry to the day's JSONL file.

    The entry is written to the file corresponding to the interval_end date
    in NPT. All timestamps are formatted as ISO 8601 with the NPT offset.

    Args:
        interval_start: The start of the work interval.
        interval_end: The end of the work interval.
        description: What the user typed (empty string if skipped).
        status: Either "logged" or "skipped".
        interval_minutes: The interval length in minutes (the N value).

    Returns:
        dict: The entry dict that was written to the file.
    """
    entry = {
        "timestamp": now_npt().isoformat(),
        "interval_start": interval_start.astimezone(NPT).isoformat(),
        "interval_end": interval_end.astimezone(NPT).isoformat(),
        "description": description,
        "status": status,
        "interval_minutes": interval_minutes,
    }

    log_file = get_log_file(interval_end.astimezone(NPT).date())
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())

    return entry


def read_entries(date: "datetime.date | None" = None) -> list:
    """Read all worklog entries from a day's JSONL file.

    If no date is provided, defaults to today in NPT.

    Args:
        date: The date for which to read entries. Defaults to today in NPT.

    Returns:
        list[dict]: A list of entry dicts. Empty list if the file doesn't exist.
    """
    log_file = get_log_file(date)
    if not log_file.exists():
        return []

    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f'Corrupt entry at {log_file}:{line_num}, skipping')
    return entries


def get_pid_file() -> Path:
    """Return the path to the PID file at ~/.timelogs/.worklog-timer.pid.

    Returns:
        Path: The PID file path.
    """
    return get_timelogs_dir() / ".worklog-timer.pid"


def get_config_file() -> Path:
    """Return the path to the config file at ~/.timelogs/.config.json.

    Returns:
        Path: The config file path.
    """
    return get_timelogs_dir() / ".config.json"


def save_config(interval: int) -> None:
    """Save the timer configuration to the config JSON file.

    Args:
        interval: The interval length in minutes.
    """
    config = {"interval_minutes": interval}
    config_file = get_config_file()
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f)


def load_config() -> dict:
    """Load the timer configuration from the config JSON file.

    If the config file does not exist or cannot be read, returns a default
    configuration with interval_minutes set to 45.

    Returns:
        dict: The configuration dictionary.
    """
    config_file = get_config_file()
    if not config_file.exists():
        return {"interval_minutes": 45}

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"interval_minutes": 45}
