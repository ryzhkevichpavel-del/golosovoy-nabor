from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class HistoryEntry:
    path: Path
    created_at: datetime
    title: str


def safe_filename_from_dt(created_at: datetime) -> str:
    return created_at.strftime("%Y-%m-%d %H-%M-%S")


def save_transcript(text: str, history_dir: Path, created_at: datetime | None = None) -> Path:
    created_at = created_at or datetime.now()
    history_dir.mkdir(parents=True, exist_ok=True)
    base = safe_filename_from_dt(created_at)
    path = history_dir / f"{base}.txt"
    counter = 2
    while path.exists():
        path = history_dir / f"{base}-{counter}.txt"
        counter += 1
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def list_history(history_dir: Path, limit: int = 300) -> list[HistoryEntry]:
    if not history_dir.exists():
        return []
    entries: list[HistoryEntry] = []
    for path in sorted(history_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            created_at = datetime.fromtimestamp(path.stat().st_mtime)
            first_line = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            title = first_line[0][:90] if first_line else path.stem
            entries.append(HistoryEntry(path=path, created_at=created_at, title=title))
        except OSError:
            continue
        if len(entries) >= limit:
            break
    return entries
