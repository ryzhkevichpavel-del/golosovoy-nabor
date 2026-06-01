from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import wave
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
                "-bo",
                "1",
                "-bs",
                "1",
                "-nf",
                "-sns",
            ]
            command.extend(["-l", self.settings.language or "ru"])
            if self.settings.language == "ru":
                command.extend(["--prompt", "Русская речь."])

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


class FasterWhisperTranscriber:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.model_name = settings.model_name if settings.model_name in {"tiny", "base", "small", "medium"} else "base"
        self._model = None
        self._lock = threading.Lock()

    def warm_up(self) -> None:
        self._get_model()

    def transcribe(self, wav_path: Path) -> Transcript:
        wav_path = wav_path.resolve()
        if not wav_path.exists():
            raise TranscriptionError("Не найден записанный аудиофайл.")

        model = self._get_model()
        try:
            language = None if self.settings.language == "auto" else (self.settings.language or "ru")
            duration = _wav_duration(wav_path)
            vad_choices = [duration >= 12.0, False] if duration is not None and duration >= 12.0 else [False]
            text = ""
            for vad_filter in dict.fromkeys(vad_choices):
                try:
                    text = self._transcribe_once(model, wav_path, language, vad_filter=vad_filter, beam_size=1)
                except Exception:
                    if vad_filter:
                        continue
                    raise
                if language == "ru" and _latin_ratio(text) > 0.25:
                    try:
                        retry_text = self._transcribe_once(model, wav_path, language, vad_filter=vad_filter, beam_size=3)
                    except Exception:
                        retry_text = ""
                    if retry_text and _latin_ratio(retry_text) < _latin_ratio(text):
                        text = retry_text
                if text:
                    break
        except Exception as exc:
            raise TranscriptionError(f"Не удалось распознать запись: {exc}") from exc

        if not text:
            raise TranscriptionError("Не услышал голос. Попробуй сказать чуть громче.")
        return Transcript(text=text, provider="faster_whisper", model=self.model_name)

    def _get_model(self):  # noqa: ANN202
        with self._lock:
            if self._model is not None:
                return self._model
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from faster_whisper import WhisperModel

            download_root = MODEL_DIR / "faster-whisper"
            download_root.mkdir(parents=True, exist_ok=True)
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, self.settings.threads),
                download_root=str(download_root),
            )
            return self._model

    @staticmethod
    def _transcribe_once(model, wav_path: Path, language: str | None, *, vad_filter: bool, beam_size: int) -> str:  # noqa: ANN001
        segments, _info = model.transcribe(
            str(wav_path),
            language=language,
            beam_size=beam_size,
            best_of=1,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def _wav_duration(wav_path: Path) -> float | None:
    try:
        with wave.open(str(wav_path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except (OSError, EOFError, wave.Error, ZeroDivisionError):
        return None


def _latin_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    latin = sum("a" <= char.lower() <= "z" for char in letters)
    return latin / len(letters)
