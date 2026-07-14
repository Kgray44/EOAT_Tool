# EOAT Atlas HMI Sample Icon Pack

This is a 10-icon sample for reviewing a restarted EOAT Atlas / EOAT Command Center icon direction.

The sample uses original chunky industrial HMI pictograms. It intentionally does not generate the full icon pack yet.

## Generated Sample Icons

- robot
- mold
- eoat
- injection_unit
- ejector
- vacuum
- pressure_air
- air_circuit
- compatibility
- machine

## Style Direction

- Filled cyan component bodies
- Gray machine structure
- Lime action, airflow, active path, and status accents
- Large tile-first pictograms
- Minimal detail for 32px readability
- Original generic machine-interface symbols

## Rebuild

Run from the repository root:

```powershell
python scripts/build_icon_pack.py
```

PNG export requires CairoSVG:

```powershell
python -m pip install cairosvg
```

If CairoSVG or the native Cairo renderer is unavailable, SVGs, manifest, README, HTML preview, style notes, and the contact sheet preview are still generated.

Reference crops in `assets/icon_design_reference/` are for private style analysis only and must not be used as final app assets.
