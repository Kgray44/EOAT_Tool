from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


class MigrationIdentityError(RuntimeError):
    pass


def _ast_sha256(data: bytes) -> str:
    return hashlib.sha256(ast.dump(ast.parse(data.decode("utf-8")), annotate_fields=True, include_attributes=False).encode()).hexdigest()


def verify(path: str, revision: str, parent: str, canonical: bytes, production: bytes, attestations: Path, active_release: str) -> None:
    canonical_sha = hashlib.sha256(canonical).hexdigest()
    production_sha = hashlib.sha256(production).hexdigest()
    if b"\r\n" in canonical:
        raise MigrationIdentityError("package canonical-byte failure")
    if canonical_sha == production_sha:
        return
    normalized = production.replace(b"\r\n", b"\n")
    items = json.loads(attestations.read_text(encoding="utf-8"))["attestations"]
    match = next((x for x in items if x["migration_path"] == path and x["revision"] == revision and x["parent_revision"] == parent and x["canonical_sha256"] == canonical_sha and x["legacy_production_sha256"] == production_sha and x["active_production_release"] == active_release), None)
    if match is None:
        raise MigrationIdentityError("unattested legacy variant")
    if match["normalization"] != "CRLF_TO_LF_ONLY" or hashlib.sha256(normalized).hexdigest() != canonical_sha or normalized != canonical:
        raise MigrationIdentityError("normalization mismatch")
    if _ast_sha256(canonical) != match["canonical_ast_sha256"] or _ast_sha256(production) != match["legacy_ast_sha256"]:
        raise MigrationIdentityError("semantic mismatch")
