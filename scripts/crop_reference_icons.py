"""Crop ENGEL HMI reference icons from collected source screenshots.

The output is reference-only and must not be used as final app art.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required. Install with: python -m pip install Pillow") from exc


ROOT = Path(__file__).resolve().parents[1]
REF_ROOT = ROOT / "assets" / "icon_reference_engel"
RAW_SOURCE = REF_ROOT / "source_images" / "raw"
PROCESSED_SOURCE = REF_ROOT / "source_images" / "processed"
RAW_CROPS = REF_ROOT / "cropped_icons" / "raw_crops"
NORMALIZED = REF_ROOT / "cropped_icons" / "normalized"
CONTACTS = REF_ROOT / "contact_sheets"
METADATA = REF_ROOT / "metadata"
NOTES = REF_ROOT / "notes"
CROP_BOXES = METADATA / "crop_boxes.json"
CROPPED_META = METADATA / "cropped_icons.json"
WATERMARK = "REFERENCE ONLY - DO NOT USE AS FINAL APP ASSETS"


@dataclass
class CropMeta:
    crop_filename: str
    normalized_128_filename: str
    normalized_256_filename: str
    source_image_filename: str
    crop_box: list[int]
    visible_label: str
    guessed_meaning: str
    confidence: str
    notes: str
    created_at: str


def make_dirs() -> None:
    for folder in (RAW_CROPS, NORMALIZED / "128", NORMALIZED / "256", CONTACTS, METADATA, NOTES):
        folder.mkdir(parents=True, exist_ok=True)


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def write_template() -> None:
    make_dirs()
    if CROP_BOXES.exists():
        print(f"Crop box file already exists: {CROP_BOXES}")
        return
    template = {
        "source_image_filename.png": [
            {
                "name": "robot_reference_001",
                "box": [0, 0, 64, 64],
                "visible_label": "Roboter",
                "guessed_meaning": "robot",
                "confidence": "medium",
                "notes": "Visible component icon from CC300 screen",
            }
        ]
    }
    CROP_BOXES.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote template: {CROP_BOXES}")


def source_path(filename: str) -> Path:
    for root in (PROCESSED_SOURCE, RAW_SOURCE):
        path = root / filename
        if path.exists():
            return path
    raise FileNotFoundError(f"Source image not found in raw/ or processed/: {filename}")


def trim_transparent_or_flat_bg(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha_bbox = rgba.getchannel("A").getbbox()
    if alpha_bbox:
        rgba = rgba.crop(alpha_bbox)
    bg = Image.new("RGBA", rgba.size, rgba.getpixel((0, 0)))
    diff = ImageChops.difference(rgba, bg)
    bbox = diff.getbbox()
    if bbox:
        return rgba.crop(bbox)
    return rgba


def normalize_crop(image: Image.Image, size: int) -> Image.Image:
    image = trim_transparent_or_flat_bg(image)
    image.thumbnail((size - 24, size - 24), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    canvas.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def crop_icons() -> list[CropMeta]:
    make_dirs()
    if not CROP_BOXES.exists():
        write_template()
        raise SystemExit(f"Edit {CROP_BOXES} and rerun with --crop.")
    crop_data = json.loads(CROP_BOXES.read_text(encoding="utf-8"))
    metadata: list[CropMeta] = []

    for filename, entries in crop_data.items():
        if filename.startswith("_"):
            continue
        try:
            image = Image.open(source_path(filename)).convert("RGBA")
            ImageOps.exif_transpose(image, in_place=True)
        except Exception as exc:
            print(f"Skipping {filename}: {exc}")
            continue
        for entry in entries:
            name = entry["name"]
            box = [int(value) for value in entry["box"]]
            visible_label = entry.get("visible_label", "")
            guessed_meaning = entry.get("guessed_meaning", "unknown")
            confidence = entry.get("confidence", "medium")
            notes = entry.get("notes", "")
            crop = image.crop(tuple(box))
            raw_name = f"{name}.png"
            norm_128 = f"{name}_128.png"
            norm_256 = f"{name}_256.png"
            crop.save(RAW_CROPS / raw_name)
            normalize_crop(crop, 128).save(NORMALIZED / "128" / norm_128)
            normalize_crop(crop, 256).save(NORMALIZED / "256" / norm_256)
            metadata.append(
                CropMeta(
                    crop_filename=raw_name,
                    normalized_128_filename=norm_128,
                    normalized_256_filename=norm_256,
                    source_image_filename=filename,
                    crop_box=box,
                    visible_label=visible_label,
                    guessed_meaning=guessed_meaning,
                    confidence=confidence,
                    notes=notes,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            print(f"Cropped {raw_name}")
    CROPPED_META.write_text(
        json.dumps({"reference_only": True, "crops": [asdict(item) for item in metadata]}, indent=2) + "\n",
        encoding="utf-8",
    )
    write_crop_contact_sheet(metadata)
    write_normalized_contact_sheet(metadata)
    write_reference_notes(metadata)
    write_visual_style_observations(metadata)
    return metadata


def make_thumb(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (255, 255, 255, 0))
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def draw_watermark(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.text((24, 50), WATERMARK, font=load_font(13, True), fill=(190, 50, 50, 255))


def write_crop_contact_sheet(items: list[CropMeta]) -> Path:
    columns = 6
    cell_w = 176
    cell_h = 184
    header_h = 78
    rows = max(1, (len(items) + columns - 1) // columns)
    sheet = Image.new("RGBA", (columns * cell_w + 32, header_h + rows * cell_h + 30), (246, 248, 250, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    draw.text((24, 20), "ENGEL HMI Cropped Reference Icons", font=load_font(23, True), fill=(30, 42, 50, 255))
    draw_watermark(draw, sheet.width, sheet.height)
    for index, item in enumerate(items):
        x = 16 + (index % columns) * cell_w
        y = header_h + (index // columns) * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 12, y + cell_h - 12), radius=8, fill=(255, 255, 255, 255), outline=(214, 222, 228, 255))
        thumb = make_thumb(RAW_CROPS / item.crop_filename, (112, 92))
        sheet.alpha_composite(thumb, (x + 26, y + 14))
        label = f"{item.guessed_meaning}\n{item.crop_filename}\n{item.source_image_filename}"
        draw.multiline_text((x + (cell_w - 12) // 2, y + 116), label, font=load_font(9), fill=(30, 42, 50, 255), anchor="ma", spacing=2)
    path = CONTACTS / "cropped_reference_icons_contact_sheet.png"
    sheet.save(path)
    return path


def write_normalized_contact_sheet(items: list[CropMeta]) -> Path:
    columns = 8
    cell_w = 150
    cell_h = 176
    header_h = 78
    rows = max(1, (len(items) + columns - 1) // columns)
    sheet = Image.new("RGBA", (columns * cell_w + 32, header_h + rows * cell_h + 30), (246, 248, 250, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    draw.text((24, 20), "ENGEL HMI Normalized Reference Icons", font=load_font(23, True), fill=(30, 42, 50, 255))
    draw_watermark(draw, sheet.width, sheet.height)
    for index, item in enumerate(items):
        x = 16 + (index % columns) * cell_w
        y = header_h + (index // columns) * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 12, y + cell_h - 12), radius=8, fill=(255, 255, 255, 255), outline=(214, 222, 228, 255))
        thumb = make_thumb(NORMALIZED / "128" / item.normalized_128_filename, (92, 92))
        sheet.alpha_composite(thumb, (x + 23, y + 12))
        draw.text((x + (cell_w - 12) // 2, y + 119), item.guessed_meaning, font=load_font(11, True), fill=(30, 42, 50, 255), anchor="mm")
        draw.text((x + (cell_w - 12) // 2, y + 138), item.visible_label or item.crop_filename, font=load_font(8), fill=(90, 102, 112, 255), anchor="mm")
    path = CONTACTS / "normalized_reference_icons_contact_sheet.png"
    sheet.save(path)
    return path


def write_reference_notes(items: list[CropMeta]) -> Path:
    lines = [
        "# Reference Icon Notes",
        "",
        "Reference-only cropped ENGEL HMI icons. Do not use as final EOAT Atlas app assets.",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"## {item.crop_filename}",
                "",
                f"- Visible label: {item.visible_label or 'N/A'}",
                f"- Guessed meaning: {item.guessed_meaning}",
                f"- Source image: {item.source_image_filename}",
                f"- Crop box: {item.crop_box}",
                f"- Confidence: {item.confidence}",
                f"- Notes: {item.notes or 'N/A'}",
                "",
            ]
        )
    path = NOTES / "reference_icon_notes.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_visual_style_observations(items: list[CropMeta]) -> Path:
    meanings = sorted({item.guessed_meaning for item in items})
    lines = [
        "# Visual Style Observations",
        "",
        "These are broad observations from the cropped reference set only. They are not instructions to copy exact ENGEL geometry.",
        "",
        f"- Cropped reference icons reviewed: {len(items)}",
        f"- Apparent meanings represented: {', '.join(meanings) if meanings else 'N/A'}",
        "",
        "## Broad Observations",
        "",
        "- Icons tend to use bold, tile-readable component silhouettes rather than thin web-icon outlines.",
        "- Cyan/teal frequently carries the main machine or component body.",
        "- Gray is useful for neutral rails, plates, bases, connectors, and mold/machine structure.",
        "- Lime green is best reserved for active motion, direction, selected state, airflow, or status confirmation.",
        "- Arrows and motion cues work best when they are chunky and attached to the mechanical action they describe.",
        "- Component icons are simplified into recognisable machine areas: robot, mold/tooling, injection unit, ejector/demolding, peripherals, pneumatics.",
        "- The industrial HMI feel comes from filled geometry, large pictogram scale, low detail density, and touchscreen tile framing.",
        "",
        "## Reminder",
        "",
        "Final Atlas icons must be original and should use these observations only as general style guidance.",
    ]
    path = NOTES / "visual_style_observations.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def coordinate_picker(filename: str) -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import RectangleSelector
    except ImportError as exc:
        raise SystemExit("matplotlib is required for --pick mode. Otherwise use an external image editor and edit crop_boxes.json.") from exc

    path = source_path(filename)
    image = Image.open(path)
    fig, ax = plt.subplots()
    ax.imshow(image)
    ax.set_title(f"Drag crop rectangles for {filename}; close window when done")
    coords: list[list[int]] = []

    def onselect(eclick, erelease):
        x1, y1 = int(eclick.xdata), int(eclick.ydata)
        x2, y2 = int(erelease.xdata), int(erelease.ydata)
        box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
        coords.append(box)
        print(box)

    RectangleSelector(ax, onselect, useblit=True, button=[1], minspanx=5, minspany=5, spancoords="pixels", interactive=True)
    plt.show()
    if coords:
        print(json.dumps({filename: [{"name": f"reference_{i+1:03d}", "box": box, "visible_label": "", "guessed_meaning": "unknown", "confidence": "low", "notes": ""} for i, box in enumerate(coords)]}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-template", action="store_true", help="Create metadata/crop_boxes.json template")
    parser.add_argument("--crop", action="store_true", help="Crop icons using metadata/crop_boxes.json")
    parser.add_argument("--pick", metavar="SOURCE_FILENAME", help="Open matplotlib crop picker for a source image")
    args = parser.parse_args()

    if args.write_template:
        write_template()
    if args.crop:
        items = crop_icons()
        print("ENGEL HMI reference crop summary")
        print(f"- Cropped reference icons: {len(items)}")
        print(f"- Crop metadata: {CROPPED_META.relative_to(ROOT)}")
        print(f"- Raw crop sheet: {(CONTACTS / 'cropped_reference_icons_contact_sheet.png').relative_to(ROOT)}")
        print(f"- Normalized crop sheet: {(CONTACTS / 'normalized_reference_icons_contact_sheet.png').relative_to(ROOT)}")
    if args.pick:
        coordinate_picker(args.pick)
    if not args.write_template and not args.crop and not args.pick:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
