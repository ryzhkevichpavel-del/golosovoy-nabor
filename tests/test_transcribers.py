from __future__ import annotations

from golosovoy_nabor.transcribers import clean_whisper_text


def test_clean_whisper_text_removes_timestamps() -> None:
    raw = "[00:00:00.000 --> 00:00:02.000]  Привет, мир.\n\n[00:00:02.000 --> 00:00:04.000]  Это тест."
    assert clean_whisper_text(raw) == "Привет, мир.\nЭто тест."


def test_clean_whisper_text_keeps_plain_text() -> None:
    assert clean_whisper_text("  Просто текст.  \n") == "Просто текст."
