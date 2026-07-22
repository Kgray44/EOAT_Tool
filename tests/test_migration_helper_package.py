from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deployment" / "privileged"


def test_administrator_package_hash_manifest_and_restricted_sudo_contract() -> None:
    helper = ROOT / "eoat_atlas_deploy_helper.py"
    expected = (ROOT / "helper.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == expected
    manifest = json.loads((ROOT / "helper.manifest.json").read_text(encoding="utf-8"))
    assert manifest["helper_version"] == 2
    assert manifest["helper_sha256"] == expected
    assert manifest["installed_helper"] == "/usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py"
    sudoers = (ROOT / "eoat-atlas-deploy.sudoers").read_text(encoding="utf-8")
    assert "--request-b64 *" in sudoers
    for forbidden in ("/bin/sh", "mysql ", "alembic ", "systemctl ", "ALL=(ALL)"):
        assert forbidden not in sudoers


def test_installer_is_atomic_and_restores_the_prior_package_on_verification_failure() -> None:
    installer = (ROOT / "install_migration_helper.sh").read_text(encoding="utf-8")
    verifier = (ROOT / "verify_migration_helper.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "rollback_migration_helper.sh").read_text(encoding="utf-8")
    for token in ("id -u", "sha256sum -c helper.sha256", "visudo -cf", "backup_root", "restore()", "trap", ".eoat-helper.new"):
        assert token in installer
    assert "systemctl" not in installer and "mysql" not in installer
    assert "visudo -cf" in verifier and "self-check" in verifier
    assert "unsafe backup path" in rollback and "systemctl" not in rollback
