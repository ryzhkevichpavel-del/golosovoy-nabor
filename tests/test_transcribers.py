from __future__ import annotations

from types import SimpleNamespace

from golosovoy_nabor.config import AppSettings
from golosovoy_nabor.transcribers import FasterWhisperTranscriber, clean_whisper_text


def test_clean_whisper_text_removes_timestamps() -> None:
    raw = "[00:00:00.000 --> 00:00:02.000]  Привет, мир.\n\n[00:00:02.000 --> 00:00:04.000]  Это тест."
    assert clean_whisper_text(raw) == "Привет, мир.\nЭто тест."


def test_clean_whisper_text_keeps_plain_text() -> None:
    assert clean_whisper_text("  Просто текст.  \n") == "Просто текст."


def test_faster_whisper_falls_back_when_vad_is_unavailable(monkeypatch, tmp_path) -> None:
    wav_path = tmp_path / "recording.wav"
    wav_path.write_bytes(b"fake")
    calls: list[bool] = []

    class FakeModel:
        def transcribe(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            calls.append(bool(kwargs["vad_filter"]))
            if kwargs["vad_filter"]:
                raise FileNotFoundError("silero_vad_v6.onnx")
            return [SimpleNamespace(text="Текст восстановлен.")], None

    transcriber = FasterWhisperTranscriber(AppSettings())
    monkeypatch.setattr(transcriber, "_get_model", lambda: FakeModel())
    monkeypatch.setattr("golosovoy_nabor.transcribers._wav_duration", lambda _path: 45.0)

    transcript = transcriber.transcribe(wav_path)

    assert transcript.text == "Текст восстановлен."
    assert calls == [True, False]
