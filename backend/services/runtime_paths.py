"""
Runtime path helpers for local development and server deployment.

By default the app keeps using ~/.meeting-assistant so existing users are not
affected. On servers, MEETING_ASSISTANT_HOME / MEETING_ASSISTANT_DATA_DIR can
pin data to a stable location that does not depend on the service account's
home directory.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _resolve_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def get_app_home() -> Path:
    explicit_home = os.getenv("MEETING_ASSISTANT_HOME", "").strip()
    explicit_data_dir = os.getenv("MEETING_ASSISTANT_DATA_DIR", "").strip()

    if explicit_home:
        return _resolve_path(explicit_home)
    if explicit_data_dir:
        return _resolve_path(explicit_data_dir).parent
    return Path.home() / ".meeting-assistant"


APP_HOME = get_app_home()
DATA_DIR = _resolve_path(os.getenv("MEETING_ASSISTANT_DATA_DIR", "").strip()) if os.getenv("MEETING_ASSISTANT_DATA_DIR", "").strip() else APP_HOME / "data"
DB_PATH = DATA_DIR / "main.db"
VECTORS_DIR = DATA_DIR / "vectors"
USER_SKILLS_DIR = APP_HOME / "skills"
CLASSIFICATION_OUTPUTS_DIR = DATA_DIR / "classification_outputs"
IMPORTED_FILES_DIR = DATA_DIR / "imported_files"
