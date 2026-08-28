"""Contracts for zero-migration coordinated policy generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_coordinated_release_policy_test",
    ROOT / "scripts" / "release" / "generate_coordinated_release_policy.py",
)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def _inputs(tmp_path: Path, *, current_schema: str, revisions: str) -> argparse.Namespace:
    archive = tmp_path / "server.zip"
    canonical = b"revision = '20260721_0008'\ndown_revision = None\n"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("server/migrations/versions/20260721_0008_data_state_freshness.py", canonical)
    manifest = tmp_path / "server.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "source_git_commit": "a" * 40,
                "version": "0.26.15",
                "database_schema_revision": "20260827_0016",
                "api_contract_version": "1.4.0",
                "migration_inventory": {},
            }
        ),
        encoding="utf-8",
    )
    return argparse.Namespace(
        server_archive=archive,
        server_manifest=manifest,
        bundle_path=tmp_path / "web.bundle",
        bundle_sha256="b" * 64,
        web_release_id="eoat-atlas-web-0.26.15-aaaaaaa",
        expected_active_api="/opt/eoat-atlas/releases/eoat-atlas-server-0.26.15-e45e67d",
        expected_active_web="/var/www/eoat-atlas/releases/eoat-atlas-web-0.26.15-e45e67d",
        current_schema=current_schema,
        migration_revisions=revisions,
        write_transition="preserve_current",
        writes_required_before=True,
        writes_required_after=True,
        policy_artifact_root="/opt/eoat-atlas/incoming/5d862c3",
        tls_listener_policy="approved_self_signed_existing",
    )


def test_generator_accepts_an_attested_zero_migration_preserve_write_release(tmp_path: Path) -> None:
    value = generator.generate(_inputs(tmp_path, current_schema="20260827_0016", revisions=""))

    assert value["migration_plan"] == {
        "current_schema": "20260827_0016",
        "target_schema": "20260827_0016",
        "revisions": [],
    }
    assert value["write_state"] == {
        "transition": "preserve_current",
        "required_before": True,
        "required_after": True,
    }


def test_generator_rejects_replaying_a_migration_when_schema_is_already_current(tmp_path: Path) -> None:
    with pytest.raises(generator.PolicyError, match="zero-migration"):
        generator.generate(_inputs(tmp_path, current_schema="20260827_0016", revisions="20260827_0016"))
