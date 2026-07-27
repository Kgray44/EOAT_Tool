"""Produce deterministic, reviewable Qt-to-browser visual comparison artifacts.

The capture drivers write PNGs under ``<evidence>/qt`` and
``<evidence>/browser`` using the same state identifier. This script never
captures or changes application data; it normalizes only documented dynamic
rectangles from a manifest and emits review artifacts under ``comparison``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat


GOVERNED_STATES = (
    "home-dark",
    "home-light",
    "home-recents",
    "home-live-search",
    "global-search",
    "navigation-home",
    "navigation-fit-check",
    "navigation-library",
    "navigation-settings",
    "library-default",
    "library-query",
    "library-filters",
    "eoat-profile",
    "machine-profile",
    "tool-profile",
    "fit-empty",
    "fit-populated",
    "fit-compatible",
    "fit-warning",
    "settings-dark",
    "settings-light",
    "loading",
    "empty",
    "api-unavailable",
    "not-found",
    "stale-data",
    "reduced-motion",
)


@dataclass(frozen=True)
class Comparison:
    state: str
    status: str
    message: str
    mean_difference: float | None = None
    changed_pixels: int | None = None


def _load_masks(path: Path) -> dict[str, list[list[int]]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("visual comparison mask manifest must be an object")
    values = payload.get("masks", {})
    if not isinstance(values, dict):
        raise ValueError("visual comparison mask manifest masks must be an object")
    normalized: dict[str, list[list[int]]] = {}
    for state, rectangles in values.items():
        if not isinstance(state, str) or not isinstance(rectangles, list):
            raise ValueError("visual comparison masks are invalid")
        normalized[state] = []
        for rectangle in rectangles:
            if not isinstance(rectangle, list) or len(rectangle) != 4 or not all(isinstance(value, int) for value in rectangle):
                raise ValueError("visual comparison masks must be [x, y, width, height]")
            normalized[state].append(rectangle)
    return normalized


def _masked(image: Image.Image, rectangles: list[list[int]]) -> Image.Image:
    copy = image.copy()
    painter = ImageDraw.Draw(copy)
    for x, y, width, height in rectangles:
        painter.rectangle((x, y, x + width, y + height), fill=(0, 0, 0, 0))
    return copy


def _compare(state: str, qt_path: Path, browser_path: Path, destination: Path, masks: list[list[int]]) -> Comparison:
    qt = Image.open(qt_path).convert("RGBA")
    browser = Image.open(browser_path).convert("RGBA")
    if qt.size != browser.size:
        return Comparison(state, "dimension-mismatch", f"Qt {qt.size} does not match browser {browser.size}")
    qt = _masked(qt, masks)
    browser = _masked(browser, masks)
    side_by_side = Image.new("RGBA", (qt.width * 2, qt.height))
    side_by_side.alpha_composite(qt, (0, 0))
    side_by_side.alpha_composite(browser, (qt.width, 0))
    overlay = Image.blend(qt, browser, 0.5)
    difference = ImageChops.difference(qt, browser)
    changed = sum(1 for pixel in difference.get_flattened_data() if pixel[:3] != (0, 0, 0))
    mean = sum(ImageStat.Stat(difference).mean[:3]) / 3
    side_by_side.save(destination / f"{state}.side-by-side.png")
    overlay.save(destination / f"{state}.overlay.png")
    difference.save(destination / f"{state}.difference.png")
    return Comparison(state, "compared", "", round(mean, 4), changed)


def run(evidence: Path, *, require_complete: bool) -> dict[str, object]:
    evidence = evidence.resolve()
    qt_root = evidence / "qt"
    browser_root = evidence / "browser"
    output = evidence / "comparison"
    output.mkdir(parents=True, exist_ok=True)
    masks = _load_masks(evidence / "dynamic-masks.json")
    comparisons: list[Comparison] = []
    for state in GOVERNED_STATES:
        qt_path = qt_root / f"{state}.png"
        browser_path = browser_root / f"{state}.png"
        if not qt_path.is_file() or not browser_path.is_file():
            missing = ", ".join(name for name, path in (("Qt", qt_path), ("browser", browser_path)) if not path.is_file())
            comparisons.append(Comparison(state, "missing", f"missing {missing} capture"))
            continue
        comparisons.append(_compare(state, qt_path, browser_path, output, masks.get(state, [])))
    report = {
        "schema": 1,
        "states": [comparison.__dict__ for comparison in comparisons],
        "compared": sum(comparison.status == "compared" for comparison in comparisons),
        "incomplete": sum(comparison.status != "compared" for comparison in comparisons),
    }
    (output / "comparison-metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "discrepancies.json").write_text(
        json.dumps([entry for entry in report["states"] if entry["status"] != "compared"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.evidence, require_complete=args.require_complete)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.require_complete and report["incomplete"] else 0


if __name__ == "__main__":
    sys.exit(main())
