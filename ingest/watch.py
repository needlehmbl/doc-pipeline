"""
Stage 1: Find files waiting in data/inbox/ ready to process.

Kept deliberately simple — a directory scan, not a filesystem watcher
daemon — since this pipeline is meant to be run on demand or via a
cron job, matching the "no paid services / no always-on infra" theme
of the whole project. A `watchdog`-based live version is a reasonable
future extension if you want to demo that separately.

TODO(implementation):
    - list_pending(inbox_dir) -> list[Path]: glob for files with
      extensions in extract.extractor.SUPPORTED_EXTENSIONS, skip
      dotfiles (e.g. .gitkeep).
    - move_to(file_path, dest_dir): shutil.move, used by run_pipeline.py
      to archive to data/processed/ or data/failed/ after handling.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from extract.extractor import SUPPORTED_EXTENSIONS


def list_pending(inbox_dir: str) -> list[Path]:
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return []
    return sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.name != ".gitkeep" and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def move_to(file_path: Path, dest_dir: str) -> Path:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    target = dest / file_path.name
    if target.exists():
        stem, suffix = file_path.stem, file_path.suffix
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = dest / f"{stem}-{stamp}{suffix}"
        counter = 1
        while target.exists():
            target = dest / f"{stem}-{stamp}-{counter}{suffix}"
            counter += 1

    return Path(shutil.move(str(file_path), str(target)))
