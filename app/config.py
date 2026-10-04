"""Paths and settings.

Your data lives in ~/Library/Application Support/Budget (outside the project and
the .app), so rebuilding or updating the app never touches it:

    budget.db      the database
    backups/       copies made with "Back up now"
    .env           optional settings (API key, quick-add token, LAN mode)

Set BUDGET_DATA_DIR to use a different folder (handy for testing a build).
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "Budget"

# Source checkout (dev) or the unpacked bundle (inside Budget.app).
BASE_DIR = Path(__file__).resolve().parent.parent
FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
STATIC_DIR = RESOURCE_DIR / "static"

DATA_DIR = Path(
    os.environ.get("BUDGET_DATA_DIR") or Path.home() / "Library" / "Application Support" / APP_NAME
).expanduser()
DB_PATH = DATA_DIR / "budget.db"
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME


def _project_dir() -> Path | None:
    """The source folder the app was built from (recorded by build.sh), or this checkout."""
    if not FROZEN:
        return BASE_DIR
    try:
        from . import _build_info  # written by build.sh, not in git
        return Path(_build_info.PROJECT_DIR)
    except ImportError:
        return None


PROJECT_DIR = _project_dir()
# Where the database used to live before it moved to Application Support.
LEGACY_DATA_DIR = PROJECT_DIR / "data" if PROJECT_DIR else None

# Settings: the Application Support .env, plus the project's .env during development.
load_dotenv(DATA_DIR / ".env")
if PROJECT_DIR and not FROZEN:
    load_dotenv(PROJECT_DIR / ".env")


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def quickadd_token() -> str | None:
    return os.environ.get("QUICKADD_TOKEN", "").strip() or None


def lan_enabled() -> bool:
    return os.environ.get("BUDGET_LAN", "").strip().lower() in {"1", "true", "yes", "on"}


def lan_port() -> int:
    try:
        return int(os.environ.get("BUDGET_PORT", "8000"))
    except ValueError:
        return 8000
