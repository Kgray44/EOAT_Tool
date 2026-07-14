# EOAT Atlas / EOAT Command Center Icon Pack

This is an original, generic industrial HMI-inspired icon family for EOAT Atlas / EOAT Command Center. It is intended for an injection molding, robotics, EOAT documentation, and compatibility workflow.

The icons communicate broad manufacturing concepts such as robot, mold, injection unit, demolding, pneumatics, peripherals, documentation, settings, and analytics. They do not copy, trace, crop, or reproduce ENGEL, Wittmann, Nolato, or any other proprietary machine-interface assets.

## Style Rules

- Every standalone SVG uses `viewBox="0 0 64 64"`.
- Artwork is designed inside the visual safe area from `x=8..56` and `y=8..56`.
- Main icon strokes are exactly `4px`.
- Small internal details may use `3px`.
- All strokes use round caps and round joins.
- Standalone icons have transparent backgrounds.
- Tile icons use a rounded white square at `x=4 y=4 width=56 height=56 radius=12` with a `#D6DEE4` border.
- Main object color: `#00A6C8`.
- Supporting structure color: `#9AA6AD`.
- Accent color: `#A6CE39` for checks, arrows, airflow, and status only.

## Folder Layout

- `svg/standalone/` contains transparent standalone SVG icons.
- `svg/tile/` contains rounded dashboard tile SVG icons.
- `png/32/`, `png/64/`, `png/128/`, and `png/256/` contain exported PNGs when CairoSVG is installed. Tile PNGs use the `_tile.png` suffix.
- `preview/icon_contact_sheet.png` previews the full icon family. When CairoSVG export succeeds, it uses the exported PNGs; otherwise it is generated from the same vector primitives for visual QA.
- `preview/icon_preview.html` is generated every time and previews both SVG variants.
- `icon_manifest.json` contains names, categories, descriptions, recommended usage, and asset paths.

## Rebuild Icons

Run from the repository root:

```powershell
python scripts/build_icon_pack.py
```

The script overwrites only the known generated icon-pack files for the required icon names. It does not delete unrelated assets.

## Dependencies

SVG generation, metadata, README output, and the HTML preview use the Python standard library.

PNG export requires CairoSVG and the native Cairo renderer:

```powershell
python -m pip install cairosvg
```

The contact sheet is generated after PNG export and uses Pillow:

```powershell
python -m pip install Pillow
```

If CairoSVG is missing, the script skips per-size PNG export, then prints the install command.
If the Python package is installed but the native Cairo DLL/library is unavailable, the script also skips per-size PNG export gracefully and prints the renderer error. In that case, the SVGs, manifest, README, HTML preview, and contact sheet preview are still generated.

## Use the SVGs

Use standalone SVGs when the app already supplies its own button, navigation, or panel surface:

```html
<img src="assets/icons/svg/standalone/eoat.svg" alt="EOAT">
```

Use tile SVGs for dashboard buttons or launcher cards:

```html
<img src="assets/icons/svg/tile/compatibility.svg" alt="Compatibility">
```

## Use the PNGs

Use PNGs for tools that cannot render SVG, such as some reports, slide decks, or legacy documentation outputs.

Examples:

- `assets/icons/png/64/robot.png`
- `assets/icons/png/128/robot_tile.png`

## Add a New Icon

1. Add a new draw function in `scripts/build_icon_pack.py`.
2. Build it from the existing primitives: rounded rectangles, circles, lines, paths, and polylines.
3. Keep the artwork inside the `0 0 64 64` viewBox and the `8..56` safe area.
4. Use `#00A6C8` for the main object, `#9AA6AD` for structure, and `#A6CE39` only for status or motion.
5. Add a matching `IconSpec` entry with metadata.
6. Run `python scripts/build_icon_pack.py`.
7. Review `preview/icon_preview.html` and, when PNG export is enabled, `preview/icon_contact_sheet.png`.

## Original Asset Reminder

Keep this pack original and generic. Do not replace these icons with screenshot crops, traced vendor artwork, or proprietary HMI icon assets. New icons should share the same strict design system and communicate industrial concepts without copying protected interface art.
