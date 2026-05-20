from __future__ import annotations

from core.final_summary import build_final_summary_markdown, generate_final_project_summary


def test_final_summary_generates_markdown_with_placeholders(fake_project):
    markdown, warnings, metrics = build_final_summary_markdown(fake_project)

    assert "Final Project Summary Draft" in markdown
    assert "Not available yet" in markdown
    assert metrics["Total EOATs identified"] == 0
    assert warnings == []


def test_final_summary_writes_report(fake_project):
    result = generate_final_project_summary(fake_project, notes="Manual closeout note.")

    assert result.success is True
    assert result.output_reports
    text = open(result.output_reports[0], encoding="utf-8").read()
    assert "Manual closeout note." in text
