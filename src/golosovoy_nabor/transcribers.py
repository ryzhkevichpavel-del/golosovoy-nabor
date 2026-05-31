from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import BIN_DIR, MODEL_DIR, AppSettings


class TranscriptionError(RuntimeError):
    pass


class MissingBackendError(TranscriptionError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str
    model: str


def whisper_cli_path() -> Path:
    return BIN_DIR / "whisper-cli.exe"


def whisper_model_path(model_name: str) -> Path:
    return MODEL_DIR / f"ggml-{model_name}.bin"


def clean_whisper_text(raw: str) -> str:
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^\[[0-9:.>\-\s]+\]\s*", "", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


class WhisperCppTranscriber:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.exe_path = whisper_cli_path()
        self.model_path = whisper_model_path(settings.model_name)

    def transcribe(self, wav_path: Path) -> Transcript:
        wav_path = wav_path.resolve()
        if not self.exe_path.exists():
            raise MissingBackendError("Не найден локальный Whisper. Открой настройки и нажми 'Скачать Whisper'.")
        if not self.model_path.exists():
            raise MissingBackendError(f"Не найдена модель {self.settings.model_name}. Открой настройки и скачай модель.")
        if not wav_path.exists():
            raise TranscriptionError("Не найден записанный аудиофайл.")

        with tempfile.TemporaryDirectory(prefix="golosovoy-nabor-") as tmp:
            out_base = Path(tmp) / "transcript"
            command = [
                str(self.exe_path),
                "-m",
                str(self.model_path),
                "-f",
                str(wav_path),
                "-otxt",
                "-of",
                str(out_base),
                "-nt",
                "-np",
                "-t",
                str(max(1, self.settings.threads)),
            ]
            if self.settings.language != "auto":
                command.extend(["-l", self.settings.language])

            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW

            completed = subprocess.run(
                command,
                cwd=str(self.exe_path.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags,
                timeout=600,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise TranscriptionError(f"Whisper не смог распознать запись. {detail[:800]}")

            text_file = out_base.with_suffix(".txt")
            if text_file.exists():
                raw_text = text_file.read_text(encoding="utf-8", errors="replace")
            else:
                raw_text = completed.stdout
            text = clean_whisper_text(raw_text)
            if not text:
                raise TranscriptionError("Whisper вернул пустой текст. Возможно, запись была слишком тихой.")
            return Transcript(text=text, provider="local_whisper_cpp", model=self.settings.model_name)
