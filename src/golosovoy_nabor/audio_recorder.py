from __future__ import annotations

import threading
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd


@dataclass(frozen=True)
class AudioRecording:
    path: Path
    seconds: float
    sample_rate: int


class AudioRecorder:
    def __init__(self, audio_dir: Path, sample_rate: int = 16000, device_index: int | None = None):
        self.audio_dir = audio_dir
        self.sample_rate = sample_rate
        self.device_index = device_index
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._started_at: datetime | None = None
        self._first_frame = threading.Event()

    def start(self) -> None:
        if self._stream is not None:
            return
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._frames = []
        self._first_frame.clear()
        self._started_at = datetime.now()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=self.device_index,
            callback=self._callback,
        )
        self._stream.start()
        self._first_frame.wait(timeout=0.5)

    def stop(self) -> AudioRecording:
        if self._stream is None:
            raise RuntimeError("Запись не была запущена.")
        self._stream.stop()
        self._stream.close()
        self._stream = None

        with self._lock:
            if not self._frames:
                raise RuntimeError("Звук не записался. Проверь микрофон.")
            audio = np.concatenate(self._frames, axis=0)

        started_at = self._started_at or datetime.now()
        seconds = len(audio) / float(self.sample_rate)
        path = self.audio_dir / f"recording-{started_at.strftime('%Y%m%d-%H%M%S')}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(audio.tobytes())
        return AudioRecording(path=path, seconds=seconds, sample_rate=self.sample_rate)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        del frames, time_info, status
        with self._lock:
            self._frames.append(indata.copy())
        self._first_frame.set()


def list_input_devices() -> list[tuple[int, str]]:
    devices = sd.query_devices()
    result: list[tuple[int, str]] = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) > 0:
            result.append((index, str(device.get("name", f"Device {index}"))))
    return result
