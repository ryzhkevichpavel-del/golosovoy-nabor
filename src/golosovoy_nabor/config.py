from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_ID = "GolosovoyNabor"
APP_NAME = "Глас"
APP_NAME_ASCII = "Glas"


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
DEFAULT_HISTORY_DIR = _documents_dir() / "Глас" / "История"


@dataclass
class AppSettings:
    settings_version: int = 5
    provider: str = "faster_whisper"
    hotkey: str = "<f8>"
    language: str = "ru"
    model_name: str = "base"
    history_dir: str = str(DEFAULT_HISTORY_DIR)
    save_history: bool = True
    auto_paste: bool = True
    show_status_window: bool = True
    floating_x: int | None = None
    floating_y: int | None = None
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
    if int(raw.get("settings_version", 0) or 0) < 2:
        if merged.get("hotkey") == "<ctrl>+<alt>+space":
            merged["hotkey"] = defaults["hotkey"]
        if merged.get("language") == "auto":
            merged["language"] = defaults["language"]
        merged["settings_version"] = defaults["settings_version"]
    if int(raw.get("settings_version", 0) or 0) < 3:
        if merged.get("model_name") in {"tiny", "base"}:
            merged["model_name"] = defaults["model_name"]
        merged["settings_version"] = defaults["settings_version"]
    if int(raw.get("settings_version", 0) or 0) < 4:
        if merged.get("model_name") == "base":
            merged["model_name"] = defaults["model_name"]
        merged["settings_version"] = defaults["settings_version"]
    if int(raw.get("settings_version", 0) or 0) < 5:
        merged["provider"] = defaults["provider"]
        merged["model_name"] = "base"
        merged["settings_version"] = defaults["settings_version"]
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
