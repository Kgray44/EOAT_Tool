from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def timestamped_filename(base_name: str, extension: str) -> str:
    suffix = extension if extension.startswith(".") else f".{extension}"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_{stamp}{suffix}"


def detect_existing_file_conflict(path: str | Path) -> bool:
    return Path(path).exists()


def backup_file(path: str | Path, backup_dir: str | Path) -> Path:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    target_dir = ensure_directory(backup_dir)
    backup_name = timestamped_filename(f"{source.stem}_backup", source.suffix)
    target = target_dir / backup_name
    shutil.copy2(source, target)
    return target


def safe_write_text(path: str | Path, text: str, overwrite: bool = False, encoding: str = "utf-8") -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
    ensure_directory(target.parent)
    if target.exists() and overwrite:
        backup_file(target, target.parent / "_backups")
    target.write_text(text, encoding=encoding)
    return target


def safe_copy_file(src: str | Path, dst: str | Path, overwrite: bool = False) -> Path:
    source = Path(src)
    target = Path(dst)
    if not source.exists():
        raise FileNotFoundError(source)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
    ensure_directory(target.parent)
    if target.exists() and overwrite:
        backup_file(target, target.parent / "_backups")
    shutil.copy2(source, target)
    return target

