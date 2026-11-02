"""Application resources and per-user writable data are kept separate."""
import os
import sys
from pathlib import Path

APP_NAME = "汇报有方"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def user_data_dir():
    if sys.platform == "win32":
        base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / "AppData" / "Local"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def resolve_data_dir(explicit=None):
    return Path(explicit or os.environ.get("WORK_REPORT_DATA_DIR") or user_data_dir()).expanduser().resolve()
