"""Create a launcher update ZIP and signed-manifest-ready evidence from a packaged launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package a validated immutable EOAT Atlas launcher update")
    parser.add_argument("launcher_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--smoke-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.launcher_root.resolve()
    exe = root / "EOAT Atlas Launcher.exe"
    metadata = root / "launcher_release_metadata.json"
    manifest = root / "launcher_package_manifest.json"
    if not exe.is_file() or not metadata.is_file() or not manifest.is_file() or not args.smoke_receipt.is_file():
        raise SystemExit("launcher package, metadata, package manifest, and smoke receipt are required")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise SystemExit("launcher package manifest is malformed")
    for item in files:
        path = root / str(item.get("path") or "")
        if not path.is_file() or path.stat().st_size != item.get("size") or _sha(path) != item.get("sha256"):
            raise SystemExit("launcher package manifest does not match package bytes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
        archive.write(args.smoke_receipt, "launcher_smoke_receipt.json")
    print(
        json.dumps(
            {
                "package": str(args.output),
                "sha256": _sha(args.output),
                "size": args.output.stat().st_size,
                "launcher_metadata_sha256": _sha(metadata),
                "package_manifest_sha256": _sha(manifest),
                "smoke_receipt_sha256": _sha(args.smoke_receipt),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
