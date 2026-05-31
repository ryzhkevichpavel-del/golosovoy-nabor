from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .config import BIN_DIR, MODEL_DIR
from .transcribers import whisper_cli_path, whisper_model_path

WHISPER_CPP_VERSION = "v1.8.5"
WHISPER_CPP_URL = (
    "https://github.com/ggml-org/whisper.cpp/releases/download/"
    f"{WHISPER_CPP_VERSION}/whisper-bin-x64.zip"
)
MODEL_URLS = {
    "tiny": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
    "base": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
    "base-q5_1": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin",
    "small": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
    "small-q5_1": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin",
    "medium": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
}

ProgressCallback = Callable[[str], None]


def backend_ready(model_name: str = "base") -> bool:
    return whisper_cli_path().exists() and whisper_model_path(model_name).exists()


def ensure_backend(model_name: str = "base", progress: ProgressCallback | None = None) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not whisper_cli_path().exists():
        _download_and_extract_whisper(progress)
    if not whisper_model_path(model_name).exists():
        download_model(model_name, progress)


def download_model(model_name: str, progress: ProgressCallback | None = None) -> Path:
    if model_name not in MODEL_URLS:
        raise ValueError(f"Неизвестная модель Whisper: {model_name}")
    target = whisper_model_path(model_name)
    if target.exists():
        _notify(progress, f"Модель {model_name} уже скачана.")
        return target

    temp_path = target.with_suffix(".download")
    _notify(progress, f"Скачиваю модель {model_name}...")
    _download(MODEL_URLS[model_name], temp_path, progress)
    temp_path.replace(target)
    _notify(progress, f"Модель {model_name} готова.")
    return target


def _download_and_extract_whisper(progress: ProgressCallback | None = None) -> None:
    temp_zip = BIN_DIR / "whisper-bin-x64.zip"
    temp_extract = BIN_DIR / "_extract"
    if temp_extract.exists():
        shutil.rmtree(temp_extract)
    temp_extract.mkdir(parents=True, exist_ok=True)

    _notify(progress, "Скачиваю локальный Whisper...")
    _download(WHISPER_CPP_URL, temp_zip, progress)
    _notify(progress, "Распаковываю Whisper...")
    with zipfile.ZipFile(temp_zip, "r") as archive:
        archive.extractall(temp_extract)

    exe_candidates = list(temp_extract.rglob("whisper-cli.exe"))
    if not exe_candidates:
        raise RuntimeError("В архиве Whisper не найден whisper-cli.exe.")

    source_dir = exe_candidates[0].parent
    for item in source_dir.iterdir():
        destination = BIN_DIR / item.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    shutil.rmtree(temp_extract, ignore_errors=True)
    temp_zip.unlink(missing_ok=True)
    _notify(progress, "Локальный Whisper готов.")


def _download(url: str, target: Path, progress: ProgressCallback | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    last_percent = -1

    def hook(block_count: int, block_size: int, total_size: int) -> None:
        nonlocal last_percent
        if not progress or total_size <= 0:
            return
        downloaded = min(block_count * block_size, total_size)
        percent = int(downloaded * 100 / total_size)
        rounded = percent - (percent % 10)
        if rounded != last_percent:
            last_percent = rounded
            progress(f"Скачано {percent}%")

    urllib.request.urlretrieve(url, target, reporthook=hook)


def _notify(progress: ProgressCallback | None, message: str) -> None:
    if progress:
        progress(message)
