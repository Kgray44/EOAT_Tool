from __future__ import annotations

import json
from pathlib import Path

from scripts import build_portable_package, validate_portable_package


def test_portable_name_and_readme_state_the_direct_launch_contract(tmp_path) -> None:
    assert build_portable_package.portable_name("0.17.4") == "EOAT_Atlas_0.17.4_Portable"
    profile = dict(build_portable_package.REQUIRED_PROFILE)
    readme = tmp_path / "PORTABLE_README.txt"
    build_portable_package.write_portable_readme(readme, "0.17.4", profile)

    text = readme.read_text(encoding="utf-8")
    assert "EOAT Atlas.exe directly" in text
    assert "PowerShell script" in text
    assert profile["api_url"] in text
    assert r"%LOCALAPPDATA%\EOAT_Atlas\data\eoat_atlas_api_cache.db" in text
    assert "directly to MySQL" in text


def test_release_metadata_is_resolved_from_the_frozen_internal_payload(tmp_path) -> None:
    package = tmp_path / "EOAT_Atlas_0.17.4_Portable"
    metadata = package / "_internal" / "release_metadata.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{}", encoding="utf-8")

    assert build_portable_package.release_metadata_path(package) == metadata


def test_portable_output_replacement_requires_explicit_opt_in(tmp_path) -> None:
    output = tmp_path / "EOAT_Atlas_0.17.4_Portable"
    output.mkdir()
    (output / "generated.txt").write_text("generated", encoding="utf-8")

    try:
        build_portable_package._prepare_output_path(output, replace_output=False)
    except RuntimeError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("portable output replacement must be explicit")

    build_portable_package._prepare_output_path(output, replace_output=True)
    assert not output.exists()


def test_portable_validation_rejects_development_artifacts_and_database_drivers(tmp_path) -> None:
    portable = tmp_path / "EOAT_Atlas_0.17.4_Portable"
    (portable / "config").mkdir(parents=True)
    (portable / "EOAT Atlas.exe").write_bytes(b"portable-exe")
    (portable / "config" / "production.json").write_text(
        json.dumps(build_portable_package.REQUIRED_PROFILE), encoding="utf-8"
    )
    (portable / "config" / "development.json").write_text("{}", encoding="utf-8")
    (portable / "pymysql.pyd").write_bytes(b"")
    failures = validate_portable_package.validation_failures(portable, tmp_path / "missing.zip")

    assert any("development configuration" in failure for failure in failures)
    assert any("direct database dependency" in failure for failure in failures)


def test_production_spec_excludes_desktop_mysql_drivers_and_history_text_is_ascii() -> None:
    root = Path(__file__).resolve().parents[1]
    spec_text = (root / "EOAT_Atlas.spec").read_text(encoding="utf-8")
    library_text = (root / "app" / "atlas" / "minimalist" / "library.py").read_text(encoding="utf-8")

    assert '"pymysql"' in spec_text
    assert '"sqlalchemy"' in spec_text
    assert "â" not in library_text
    assert "Â" not in library_text
    assert 'f"{event.previous_machine_label} - {event.machine_label}"' in library_text
