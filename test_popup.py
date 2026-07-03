#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime, timezone, timedelta
NPT = timezone(timedelta(hours=5, minutes=45))
now = datetime.now(tz=NPT)
start = now.replace(minute=max(now.minute - 10, 0))

from worklog_timer.popup import show_popup
desc, status = show_popup(start, now, timeout_seconds=30)
print(f"Result: status={status}, description={desc!r}")
