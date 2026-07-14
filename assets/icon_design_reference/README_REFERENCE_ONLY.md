# EOAT Atlas Icon Design Reference Board

This folder is for private visual study only. Reference screenshots and cropped icons placed here must not be used as final EOAT Atlas / EOAT Command Center app assets.

Reference material may be used to study broad visual language only:

- Chunky industrial HMI pictogram proportions
- General color relationships
- Tile scale and spacing
- How machine components are simplified
- How action, airflow, and status are indicated

Reference material must not be copied, traced, vectorized into final art, cropped into the app, or included in any EOAT Atlas UI.

## Folder Layout

- `source_images/` stores manually provided screenshots.
- `cropped_reference_icons/` stores private cropped reference images.
- `reference_contact_sheets/` stores watermarked reference contact sheets.
- `style_analysis/` stores written observations and style notes.

## Cropping Workflow

1. Place manually provided screenshots in `source_images/`.
2. Run the crop helper to create a template:

```powershell
python scripts/crop_reference_icons.py --write-template
```

3. Edit `assets/icon_design_reference/crop_boxes.json` with crop boxes.
4. Generate crops and a watermarked contact sheet:

```powershell
python scripts/crop_reference_icons.py --crop
```

The contact sheet is marked:

`REFERENCE ONLY - DO NOT USE AS FINAL APP ASSETS`

No crops from this folder should ever be placed in `assets/icons/`.
