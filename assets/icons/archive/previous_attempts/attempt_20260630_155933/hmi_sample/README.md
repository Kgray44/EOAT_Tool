# Chunky Industrial HMI Sample Icons

This folder contains an 8-icon sample set for reviewing a heavier industrial injection molding HMI pictogram style before rebuilding the full EOAT Atlas / EOAT Command Center icon pack.

The sample intentionally moves away from thin Lucide/Material/Tabler-style line icons. The direction uses larger filled geometry, chunky machine forms, simple component silhouettes, lime action markers, and tile-first HMI button presentation.

These icons are original generic pictograms. They are inspired by broad industrial machine-controller visual language, but they do not copy, trace, crop, or reproduce ENGEL, Wittmann, Nolato, or other proprietary HMI artwork.

## Files

- `svg/standalone/` contains transparent standalone SVG samples.
- `svg/tile/` contains HMI-style tile SVG samples.
- `png/256/` contains PNG previews generated with Pillow.
- `preview/hmi_sample_contact_sheet.png` shows standalone and tile versions side by side.
- `preview/hmi_sample_preview.html` previews the SVGs in a browser.

## Rebuild

Run from the repository root:

```powershell
python scripts/build_hmi_sample_icons.py
```

Pillow is used for PNG previews and the contact sheet. SVG generation uses the Python standard library.
