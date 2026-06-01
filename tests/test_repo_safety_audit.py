from __future__ import annotations

from pathlib import Path

from scripts.repo_safety_audit import audit_paths, audit_repo, iter_files


def _messages(findings):
    return [finding.message for finding in findings]


def test_safety_audit_flags_private_paths(tmp_path: Path):
    risky = tmp_path / "notes.md"
    risky.write_text("Project root: \\\\example.invalid\\VT\\Users\\demo\\Private_Project\n", encoding="utf-8")

    findings = audit_repo(tmp_path)

    assert any(finding.severity == "BLOCKER" for finding in findings)
    assert any("UNC path" in message or "shared-drive" in message for message in _messages(findings))


def test_safety_audit_flags_local_config_files(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "local_config.json").write_text(
        '{"project_root": "C:\\\\Users\\\\demo\\\\private"}', encoding="utf-8"
    )

    findings = audit_repo(tmp_path)

    assert any(finding.severity == "BLOCKER" and "Local config" in finding.message for finding in findings)


def test_safety_audit_flags_workbooks_outside_allowed_paths(tmp_path: Path):
    workbook = tmp_path / "scratch" / "EOAT_Master_Tracker.xlsx"
    workbook.parent.mkdir()
    workbook.write_bytes(b"not a real workbook")

    findings = audit_repo(tmp_path)

    assert any(finding.severity == "BLOCKER" and "Workbook file" in finding.message for finding in findings)


def test_safety_audit_allows_sanitized_demo_files(tmp_path: Path):
    demo = tmp_path / "examples" / "demo_project"
    demo.mkdir(parents=True)
    (demo / "demo_notes.md").write_text(
        "Nolato public company context is allowed here. Customer: Demo Customer A. Part Number: DEMO-PN-001.\n",
        encoding="utf-8",
    )
    (demo / "EOAT_Master_Tracker.xlsx").write_bytes(b"synthetic workbook")

    findings = audit_repo(tmp_path)

    assert findings == []


def test_safety_audit_allows_template_workbooks(tmp_path: Path):
    template = tmp_path / "data_templates" / "template.xlsx"
    template.parent.mkdir()
    template.write_bytes(b"template workbook")

    findings = audit_repo(tmp_path)

    assert findings == []


def test_staged_scanner_helper_flags_generated_outputs(tmp_path: Path):
    report = tmp_path / "reports" / "generated" / "daily.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Generated\n", encoding="utf-8")

    findings = audit_paths(tmp_path, [report])

    assert any(finding.severity == "BLOCKER" and "Generated reports" in finding.message for finding in findings)


def test_safety_audit_allows_public_company_reference_without_private_data(tmp_path: Path):
    doc = tmp_path / "docs"
    doc.mkdir()
    (doc / "context.md").write_text(
        "This toolkit was developed for a manufacturing automation internship project at Nolato.\n",
        encoding="utf-8",
    )

    findings = audit_repo(tmp_path)

    assert findings == []


def test_safety_audit_warns_on_part_numbers_outside_allowlist(tmp_path: Path):
    doc = tmp_path / "notes.md"
    doc.write_text("Part Number: REAL-12345\n", encoding="utf-8")

    findings = audit_repo(tmp_path)

    assert any(finding.severity == "WARNING" and "Part-number-like" in finding.message for finding in findings)


def test_safety_audit_scans_docs_for_operational_warning_content(tmp_path: Path):
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()
    (doc_dir / "handoff.md").write_text("Customer: Real Customer\nPart Number: REAL-12345\n", encoding="utf-8")

    findings = audit_repo(tmp_path)

    assert any(finding.severity == "WARNING" and "Customer field" in finding.message for finding in findings)
    assert any(finding.severity == "WARNING" and "Part-number-like" in finding.message for finding in findings)


def test_safety_audit_file_walk_is_python_310_compatible(tmp_path: Path):
    nested = tmp_path / "safe" / "nested"
    nested.mkdir(parents=True)
    expected = nested / "notes.txt"
    expected.write_text("synthetic notes\n", encoding="utf-8")

    files = iter_files(tmp_path)

    assert expected in files
