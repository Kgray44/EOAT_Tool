from __future__ import annotations

from pathlib import Path
from typing import Any

from .atlas_models import StandardReference
from .paths import resolve_project_paths
from .safe_files import safe_copy_file

STANDARD_EXTENSIONS = {".docx", ".pdf", ".md", ".txt"}
STANDARD_CATEGORIES = {
    "eoat standards": ("eoat standardization", "eoat standards", "eoat standard", "standard design", "design guidelines"),
    "vacuum": ("vacuum", "cup", "venturi"),
    "tubing/routing": ("tubing", "routing", "cable"),
    "sensors": ("sensor", "part-present", "confirmation"),
    "quick disconnects": ("quick", "disconnect", "m12"),
    "weight reduction": ("weight", "lightweight"),
    "fasteners/hardware": ("fastener", "hardware", "mounting"),
    "safety": ("safety", "guard", "risk"),
    "documentation": ("documentation", "binder", "bom", "cad", "drawing"),
    "pm / maintenance": ("pm", "maintenance", "inspection", "wear"),
}
STANDARDIZATION_KEYWORDS = (
    "eoat standardization",
    "eoat standard",
    "standard design",
    "design guidelines",
    "eoat standards",
)


def build_standards_index(
    project_root: str | Path,
    *,
    standards_root: str | Path | None = None,
) -> tuple[list[StandardReference], list[str]]:
    paths = resolve_project_paths(project_root)
    standards_folder = Path(standards_root).expanduser() if standards_root else paths.standards
    import_warnings = _import_root_standardization_documents(Path(project_root), standards_folder)
    folders = [
        standards_folder,
        paths.work_instructions,
        Path(project_root) / "Project_Help_Documents",
        Path(project_root) / "output" / "documents",
        Path(project_root) / "output" / "pdf",
    ]
    references: list[StandardReference] = []
    warnings: list[str] = list(import_warnings)
    for folder in folders:
        if not folder.exists():
            continue
        try:
            files = sorted(
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix.lower() in STANDARD_EXTENSIONS and not path.name.startswith("~$")
            )
        except OSError as exc:
            warnings.append(f"Could not scan standards folder {folder}: {exc}")
            continue
        for path in files:
            references.append(
                StandardReference(
                    title=_title_for_path(path),
                    path=str(path),
                    category=_category_for_text(path.name),
                    snippet=_snippet_for_path(path),
                )
            )
    return _dedupe_references(references), warnings


def standards_for_record(row: dict[str, Any], references: list[StandardReference]) -> tuple[StandardReference, ...]:
    haystack = " ".join(str(value or "") for value in row.values()).casefold()
    categories = set()
    if "vacuum" in haystack or "cup" in haystack:
        categories.add("vacuum")
    if "gripper" in haystack:
        categories.add("fasteners/hardware")
    if "sensor" in haystack:
        categories.add("sensors")
    if "quick disconnect" in haystack or "m12" in haystack:
        categories.add("quick disconnects")
    if "tubing" in haystack or "routing" in haystack:
        categories.add("tubing/routing")
    if "maintenance" in haystack or "pm" in haystack or "wear" in haystack:
        categories.add("pm / maintenance")
    if not categories:
        categories.update({"documentation", "safety"})
    selected = [reference for reference in references if reference.category in categories]
    if selected:
        return tuple(selected[:8])
    return tuple(references[:4])


def search_standards(
    references: list[StandardReference] | tuple[StandardReference, ...], query: str
) -> list[StandardReference]:
    needle = query.strip().casefold()
    if not needle:
        return list(references)
    terms = [term for term in needle.split() if term]
    matches: list[tuple[int, StandardReference]] = []
    for reference in references:
        haystack = " ".join([reference.title, reference.category, reference.snippet, reference.path]).casefold()
        score = sum(term in haystack for term in terms)
        if score:
            matches.append((score, reference))
    return [reference for _score, reference in sorted(matches, key=lambda item: (-item[0], item[1].title.casefold()))]


def _title_for_path(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title() or path.name


def _category_for_text(text: str) -> str:
    folded = text.casefold()
    for category, tokens in STANDARD_CATEGORIES.items():
        if any(token in folded for token in tokens):
            return category
    return "documentation"


def _snippet_for_path(path: Path) -> str:
    if _is_standardization_document(path):
        return "Primary EOAT standardization guidance. Open the source document for full design and documentation rules."
    if path.suffix.lower() not in {".md", ".txt"}:
        return "Open the source document for full guidance."
    try:
        text = " ".join(path.read_text(encoding="utf-8", errors="ignore").split())
    except OSError:
        return ""
    return text[:320]


def _import_root_standardization_documents(project_root: Path, standards_folder: Path) -> list[str]:
    warnings: list[str] = []
    if not project_root.exists():
        return warnings
    try:
        candidates = [
            path
            for path in sorted(project_root.iterdir())
            if path.is_file() and path.suffix.lower() in STANDARD_EXTENSIONS and _is_standardization_document(path)
        ]
    except OSError as exc:
        return [f"Could not scan project root for EOAT standardization documents: {exc}"]
    if not candidates:
        return warnings
    standards_folder.mkdir(parents=True, exist_ok=True)
    for source in candidates:
        try:
            existing = [
                path
                for path in standards_folder.glob(f"{source.stem}*{source.suffix}")
                if path.is_file() and path.stat().st_size == source.stat().st_size
            ]
            if existing:
                warnings.append(f"Root standardization document already registered in {standards_folder}: {source.name}")
                continue
            target = _unique_standard_target(standards_folder / source.name)
            safe_copy_file(source, target, overwrite=False)
            warnings.append(f"Copied root EOAT standardization document into standards library: {target}")
        except OSError as exc:
            warnings.append(f"Could not register root standardization document {source.name}: {exc}")
    return warnings


def _unique_standard_target(target: Path) -> Path:
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{target.stem}_copy{target.suffix}")


def _is_standardization_document(path: Path) -> bool:
    folded = path.name.casefold().replace("_", " ").replace("-", " ")
    return any(keyword in folded for keyword in STANDARDIZATION_KEYWORDS)


def _dedupe_references(references: list[StandardReference]) -> list[StandardReference]:
    deduped: dict[str, StandardReference] = {}
    for reference in references:
        deduped.setdefault(reference.path.casefold(), reference)
    return sorted(deduped.values(), key=lambda item: (item.category.casefold(), item.title.casefold()))


__all__ = [
    "STANDARD_CATEGORIES",
    "STANDARDIZATION_KEYWORDS",
    "build_standards_index",
    "search_standards",
    "standards_for_record",
]
