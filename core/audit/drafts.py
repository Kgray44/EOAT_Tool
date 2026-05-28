from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import resolve_project_paths
from core.safe_files import ensure_directory

DRAFT_VERSION = 1
DRAFT_FILE_NAME = "latest_audit_draft.json"


@dataclass(frozen=True)
class AuditDraft:
    version: int
    saved_at: str
    project_root: str
    audit_id: str
    mode: str
    form_values: dict[str, str] = field(default_factory=dict)
    baseline_values: dict[str, str] = field(default_factory=dict)


def audit_draft_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).cache / "audit_drafts"


def audit_draft_path(project_root: str | Path) -> Path:
    return audit_draft_dir(project_root) / DRAFT_FILE_NAME


def normalize_form_values(values: MappingLike | None) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in values.items()}


def form_values_changed(current: MappingLike | None, baseline: MappingLike | None) -> bool:
    current_values = normalize_form_values(current)
    baseline_values = normalize_form_values(baseline)
    keys = set(current_values) | set(baseline_values)
    return any(current_values.get(key, "") != baseline_values.get(key, "") for key in keys)


def save_audit_draft(
    project_root: str | Path,
    *,
    audit_id: str,
    mode: str,
    form_values: dict[str, Any],
    baseline_values: dict[str, Any],
) -> Path:
    path = audit_draft_path(project_root)
    ensure_directory(path.parent)
    draft = AuditDraft(
        version=DRAFT_VERSION,
        saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        project_root=str(project_root),
        audit_id=str(audit_id or ""),
        mode=str(mode or "new"),
        form_values=normalize_form_values(form_values),
        baseline_values=normalize_form_values(baseline_values),
    )
    path.write_text(json.dumps(asdict(draft), indent=2), encoding="utf-8")
    return path


def load_audit_draft(project_root: str | Path) -> AuditDraft | None:
    path = audit_draft_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return AuditDraft(
        version=int(data.get("version") or 0),
        saved_at=str(data.get("saved_at") or ""),
        project_root=str(data.get("project_root") or project_root),
        audit_id=str(data.get("audit_id") or ""),
        mode=str(data.get("mode") or "new"),
        form_values=normalize_form_values(data.get("form_values")),
        baseline_values=normalize_form_values(data.get("baseline_values")),
    )


def discard_audit_draft(project_root: str | Path) -> bool:
    path = audit_draft_path(project_root)
    if not path.exists():
        return False
    path.unlink()
    return True


MappingLike = dict[str, Any]
