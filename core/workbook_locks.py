from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkbookLockStatus:
    path: str
    exists: bool
    locked: bool
    writable: bool
    message: str
    error: str = ""

    @property
    def can_write(self) -> bool:
        return self.exists and self.writable and not self.locked


def detect_workbook_lock(workbook_path: str | Path) -> WorkbookLockStatus:
    path = Path(workbook_path)
    if not path.exists():
        return WorkbookLockStatus(
            path=str(path),
            exists=False,
            locked=False,
            writable=False,
            message=f"Workbook does not exist: {path}",
        )

    office_lock = path.with_name(f"~${path.name}")
    if office_lock.exists():
        return WorkbookLockStatus(
            path=str(path),
            exists=True,
            locked=True,
            writable=False,
            message=f"Workbook appears to be open or locked by Office: {path.name}",
            error=f"Found Office lock file: {office_lock.name}",
        )

    try:
        with path.open("r+b"):
            pass
    except PermissionError as exc:
        return WorkbookLockStatus(
            path=str(path),
            exists=True,
            locked=True,
            writable=False,
            message=f"Workbook is locked or not writable: {path.name}",
            error=str(exc),
        )
    except OSError as exc:
        return WorkbookLockStatus(
            path=str(path),
            exists=True,
            locked=True,
            writable=False,
            message=f"Workbook could not be opened for a safe write check: {path.name}",
            error=str(exc),
        )

    return WorkbookLockStatus(
        path=str(path),
        exists=True,
        locked=False,
        writable=True,
        message=f"Workbook is writable: {path.name}",
    )


__all__ = ["WorkbookLockStatus", "detect_workbook_lock"]
