#!/usr/bin/env python3
"""Manual smoke test: show the popup once and print the result."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging
from datetime import timedelta

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

from worklog_timer import display, storage
from worklog_timer.popup import show_popup

now = storage.now_npt()
start = now - timedelta(minutes=10)

env = display.build_gui_env()
print(f"DISPLAY={env.get('DISPLAY')} XAUTHORITY={env.get('XAUTHORITY')}")

desc, status = show_popup(start, now, timeout_seconds=30, env=env)
print(f"Result: status={status}, description={desc!r}")
