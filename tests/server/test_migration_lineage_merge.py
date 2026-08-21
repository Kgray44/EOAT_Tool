"""Topology contracts for the additive production/Admin Alembic merge."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_HEAD = "20260729_0009"
ADMIN_HEAD = "20260820_0012"
MERGE_HEAD = "20260820_0013"
CURRENT_HEAD = "20260821_0015"
PRODUCTION_REVISIONS = {
    "20260714_0005",
    "20260715_0006",
    "20260717_0007",
    "20260721_0008",
    PRODUCTION_HEAD,
}
ADMIN_REVISIONS = {
    "20260811_0005",
    "20260811_0006",
    "20260811_0007",
    "20260813_0008",
    "20260813_0009",
    "20260813_0010",
    "20260814_0011",
    ADMIN_HEAD,
}


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "server" / "alembic.ini")))


def _upgrade_ids(script: ScriptDirectory, current: tuple[str, ...]) -> list[str]:
    return [step.revision.revision for step in script._upgrade_revs(MERGE_HEAD, current)]


def test_accepted_production_lineage_is_present_and_merge_is_the_only_head() -> None:
    script = _script()
    assert script.get_heads() == [CURRENT_HEAD]
    for revision in PRODUCTION_REVISIONS:
        assert script.get_revision(revision) is not None
    merge = script.get_revision(MERGE_HEAD)
    assert merge is not None
    assert tuple(merge.down_revision) == (PRODUCTION_HEAD, ADMIN_HEAD)


def test_upgrade_from_real_production_head_runs_only_missing_admin_branch_then_merge() -> None:
    planned = _upgrade_ids(_script(), (PRODUCTION_HEAD,))
    assert planned == [
        "20260811_0005",
        "20260811_0006",
        "20260811_0007",
        "20260813_0008",
        "20260813_0009",
        "20260813_0010",
        "20260814_0011",
        ADMIN_HEAD,
        MERGE_HEAD,
    ]
    assert not (set(planned) & PRODUCTION_REVISIONS)


def test_upgrade_from_admin_head_runs_only_missing_production_branch_then_merge() -> None:
    planned = _upgrade_ids(_script(), (ADMIN_HEAD,))
    assert planned == [
        "20260714_0005",
        "20260715_0006",
        "20260717_0007",
        "20260721_0008",
        PRODUCTION_HEAD,
        MERGE_HEAD,
    ]
    assert not (set(planned) & ADMIN_REVISIONS)


def test_verified_adoption_guard_covers_either_predecessor_of_the_merge() -> None:
    """Both verified predecessor schemas may safely adopt historical DDL."""
    source = (ROOT / "server" / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "_ADMIN_HEAD in revisions and revisions <= {_ADMIN_HEAD, *_PRODUCTION_LINEAGE}" in source
    assert "_ADOPTABLE_PRODUCTION_TABLES" in source
    assert "{**_ADOPTABLE_PRODUCTION_TABLES, **_ADOPTABLE_PHASE_TABLES}.items()" in source
    assert 'normalized.startswith(("CREATE ", "ALTER TABLE"))' in source


def test_data_state_seed_is_safe_when_verified_historical_data_already_exists() -> None:
    source = (ROOT / "server" / "migrations" / "versions" / "20260721_0008_data_state_freshness.py").read_text(
        encoding="utf-8"
    )
    assert "ON DUPLICATE KEY UPDATE id = data_state.id" in source


def test_fresh_upgrade_contains_both_historical_branches_and_one_final_merge() -> None:
    planned = _upgrade_ids(_script(), ())
    assert set(planned) >= PRODUCTION_REVISIONS | ADMIN_REVISIONS | {MERGE_HEAD}
    assert planned[-1] == MERGE_HEAD
    assert planned.count(MERGE_HEAD) == 1
