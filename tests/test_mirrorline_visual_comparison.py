from __future__ import annotations

from PIL import Image

from scripts.compare_mirrorline_visuals import run


def test_visual_comparison_emits_review_artifacts_for_matching_state(tmp_path) -> None:
    for root in (tmp_path / "qt", tmp_path / "browser"):
        root.mkdir()
        Image.new("RGBA", (8, 6), (3, 4, 5, 255)).save(root / "home-dark.png")
    report = run(tmp_path, require_complete=False)
    home = next(state for state in report["states"] if state["state"] == "home-dark")
    assert home["status"] == "compared"
    assert home["changed_pixels"] == 0
    assert report["unreviewed"] == 27
    comparison = tmp_path / "comparison"
    assert (comparison / "home-dark.side-by-side.png").is_file()
    assert (comparison / "home-dark.overlay.png").is_file()
    assert (comparison / "home-dark.difference.png").is_file()
    assert (comparison / "comparison-metrics.json").is_file()
    assert (comparison / "discrepancies.json").is_file()
    assert (comparison / "home-dark.discrepancy.json").is_file()
