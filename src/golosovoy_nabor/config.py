from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_ID = "GolosovoyNabor"
APP_NAME = "Голосовой набор"
APP_NAME_ASCII = "Golosovoy Nabor"


def _local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


def _documents_dir() -> Path:
    candidate = Path.home() / "Documents"
    if candidate.exists():
        return candidate
    return Path.home()


APP_DIR = _local_app_data() / APP_ID
BIN_DIR = APP_DIR / "bin"
MODEL_DIR = APP_DIR / "models"
AUDIO_DIR = APP_DIR / "audio"
LOG_DIR = APP_DIR / "logs"
SETTINGS_PATH = APP_DIR / "settings.json"
DEFAULT_HISTORY_DIR = _documents_dir() / "Голосовой набор" / "История"


@dataclass
class AppSettings:
    provider: str = "local_whisper_cpp"
    hotkey: str = "<ctrl>+<alt>+space"
    language: str = "auto"
    model_name: str = "base"
    history_dir: str = str(DEFAULT_HISTORY_DIR)
    save_history: bool = True
    auto_paste: bool = True
    show_status_window: bool = True
    device_index: int | None = None
    sample_rate: int = 16000
    threads: int = max(1, min(4, (os.cpu_count() or 2)))
    run_on_startup: bool = False
    openai_enabled: bool = False
    openai_model: str = "gpt-4o-mini-transcribe"
    openai_api_key_env: str = "OPENAI_API_KEY"


def ensure_app_dirs(settings: AppSettings | None = None) -> None:
    for path in (APP_DIR, BIN_DIR, MODEL_DIR, AUDIO_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    history_dir = Path(settings.history_dir) if settings else DEFAULT_HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> AppSettings:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        settings = AppSettings()
        save_settings(settings)
        ensure_app_dirs(settings)
        return settings

    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}

    defaults = asdict(AppSettings())
    merged: dict[str, Any] = {**defaults, **{k: v for k, v in raw.items() if k in defaults}}
    settings = AppSettings(**merged)
    ensure_app_dirs(settings)
    return settings


def save_settings(settings: AppSettings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def frozen_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.argv[0]).resolve()
