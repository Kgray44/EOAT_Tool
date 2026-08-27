from __future__ import annotations

from scripts import safety_delta_gate


def _finding(severity: str, line: int = 1) -> dict[str, object]:
    return {
        "severity": severity,
        "filename": "server/example.py",
        "line": line,
        "message": "example finding",
    }


def test_compare_treats_line_moves_as_inherited() -> None:
    inherited, introduced, resolved = safety_delta_gate._compare([_finding("BLOCKER", 4)], [_finding("BLOCKER", 9)])

    assert inherited == [_finding("BLOCKER", 9)]
    assert introduced == []
    assert resolved == 0


def test_compare_reports_an_added_blocker() -> None:
    inherited, introduced, resolved = safety_delta_gate._compare(
        [_finding("BLOCKER")], [_finding("BLOCKER"), _finding("BLOCKER", 2)]
    )

    assert inherited == [_finding("BLOCKER")]
    assert introduced == [_finding("BLOCKER", 2)]
    assert resolved == 0
