"""Build the stable EOAT Atlas bootstrap component from a clean source tree."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if (
        subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        and os.getenv("EOAT_ATLAS_ALLOW_DIRTY_BUILD") != "1"
    ):
        print("ERROR: refusing bootstrap build from dirty tracked tree", file=sys.stderr)
        return 1
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist" / "bootstrap"),
            "--workpath",
            str(ROOT / "build" / "bootstrap"),
            str(ROOT / "EOAT_Atlas_Bootstrap.spec"),
        ],
        cwd=ROOT,
    )
    if completed.returncode:
        return completed.returncode
    executable = ROOT / "dist" / "bootstrap" / "EOAT Atlas Bootstrap.exe"
    if not executable.is_file():
        print("ERROR: bootstrap executable missing", file=sys.stderr)
        return 1
    version = json.loads((ROOT / "bootstrap" / "bootstrap_version.json").read_text(encoding="utf-8"))[
        "bootstrap_version"
    ]
    executable.with_name("bootstrap_release_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "component_kind": "bootstrap",
                "component_version": version,
                "product_version": json.loads((ROOT / "app" / "atlas" / "version.json").read_text(encoding="utf-8"))[
                    "version"
                ],
                "release_id": os.getenv("EOAT_RELEASE_RELEASE_ID", ""),
                "build_id": os.getenv("EOAT_RELEASE_BUILD_ID", ""),
                "candidate_id": os.getenv("EOAT_RELEASE_CANDIDATE_ID", ""),
                "source_commit": os.getenv("EOAT_RELEASE_SOURCE_COMMIT", ""),
                "source_tree": os.getenv("EOAT_RELEASE_SOURCE_TREE", ""),
                "artifact_sha256": _sha(executable),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
