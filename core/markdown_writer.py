from __future__ import annotations

from pathlib import Path

from .safe_files import safe_write_text, timestamped_filename


def write_markdown_report(
    output_dir: str | Path,
    base_name: str,
    markdown: str,
    overwrite: bool = False,
) -> Path:
    directory = Path(output_dir)
    filename = f"{base_name}.md" if overwrite else timestamped_filename(base_name, ".md")
    return safe_write_text(directory / filename, markdown, overwrite=overwrite)
