from __future__ import annotations

from datetime import datetime

from golosovoy_nabor.history import list_history, safe_filename_from_dt, save_transcript


def test_safe_filename_from_dt() -> None:
    assert safe_filename_from_dt(datetime(2026, 5, 31, 15, 20, 30)) == "2026-05-31 15-20-30"


def test_save_and_list_history(tmp_path) -> None:  # noqa: ANN001
    path = save_transcript("Привет, мир.", tmp_path, datetime(2026, 5, 31, 15, 20, 30))
    assert path.name == "2026-05-31 15-20-30.txt"
    assert path.read_text(encoding="utf-8").strip() == "Привет, мир."
    entries = list_history(tmp_path)
    assert len(entries) == 1
    assert entries[0].title == "Привет, мир."
