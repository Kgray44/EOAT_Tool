from __future__ import annotations

import json

from scripts import ruff_delta_gate


def _diagnostic(code: str, row: int = 1) -> dict[str, object]:
    return {"filename": "app/example.py", "code": code, "message": "example", "location": {"row": row, "column": 1}}


def test_delta_gate_reports_inherited_diagnostics_without_failing(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"diagnostics": [_diagnostic("F401")]}), encoding="utf-8")
    monkeypatch.setattr(ruff_delta_gate, "_run_ruff", lambda _root, _config=None: [_diagnostic("F401")])

    assert ruff_delta_gate.main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 0
    assert "1 inherited; 0 introduced" in capsys.readouterr().out


def test_delta_gate_fails_for_new_diagnostics(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"diagnostics": [_diagnostic("F401")]}), encoding="utf-8")
    monkeypatch.setattr(
        ruff_delta_gate,
        "_run_ruff",
        lambda _root, _config=None: [_diagnostic("F401"), _diagnostic("I001", 2)],
    )

    assert ruff_delta_gate.main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 1
    output = capsys.readouterr().out
    assert "1 inherited; 1 introduced" in output
    assert "Ruff I001" in output
