from __future__ import annotations

import json
from pathlib import Path

from release_tools.versioning import canonical_version_from_payload


def windows_version_text(root: Path) -> str:
    metadata_path = root / "app" / "atlas" / "version.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = canonical_version_from_payload(payload, source=str(metadata_path))
    numeric = f"({version.major}, {version.minor}, {version.patch}, 0)"
    display = str(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric}, prodvers={numeric}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Nolato'),
    StringStruct('FileDescription', 'EOAT Atlas'),
    StringStruct('FileVersion', '{display}'),
    StringStruct('InternalName', 'EOAT Atlas'),
    StringStruct('OriginalFilename', 'EOAT Atlas.exe'),
    StringStruct('ProductName', 'EOAT Atlas'),
    StringStruct('ProductVersion', '{display}')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)\n"""


def write_windows_version_file(root: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(windows_version_text(root), encoding="utf-8", newline="\n")
    return destination
