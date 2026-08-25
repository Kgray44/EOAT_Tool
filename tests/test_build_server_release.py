from scripts.release.build_server_release import RELEVANT_PREFIXES, SERVER_PATHS


def test_server_release_includes_migration_tools_needed_by_deployed_backfills():
    assert "tools/migration" in SERVER_PATHS
    assert "tools/migration/" in RELEVANT_PREFIXES
