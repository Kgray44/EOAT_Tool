# ENGEL HMI Reference Library

This folder is a reference-only collection for studying public ENGEL HMI / CC300 / CC300+ interface screenshots.

It is separate from `assets/icons/`. Do not use any cropped reference images as final EOAT Atlas app icons.

## Folder Layout

- `source_images/raw/` contains downloaded or manually placed source images.
- `source_images/processed/` contains PNG-normalized source images for review.
- `cropped_icons/raw_crops/` contains manually defined icon crops.
- `cropped_icons/normalized/` contains normalized square reference crops.
- `contact_sheets/` contains source and crop contact sheets.
- `metadata/source_images.json` records download metadata.
- `metadata/crop_boxes.json` defines manual crop boxes.
- `metadata/cropped_icons.json` records crop metadata.
- `notes/` contains reference notes and broad style observations.

## Collect Public Source Images

Run:

```powershell
python scripts/collect_engel_hmi_references.py
```

Add more seed pages or image URLs:

```powershell
python scripts/collect_engel_hmi_references.py --seed-url "https://example.com/page" --image-url "https://example.com/image.png"
```

## Add Manual Screenshots

Drop screenshots into:

`assets/icon_reference_engel/source_images/raw/`

Then rerun:

```powershell
python scripts/collect_engel_hmi_references.py --manual-only
```

The script hashes files, adds metadata entries, creates processed PNG copies, and regenerates the source contact sheet.

## Crop Reference Icons

Create a crop template:

```powershell
python scripts/crop_reference_icons.py --write-template
```

Edit:

`assets/icon_reference_engel/metadata/crop_boxes.json`

Then crop:

```powershell
python scripts/crop_reference_icons.py --crop
```

The crops are reference-only and must not be placed in final app UI.
