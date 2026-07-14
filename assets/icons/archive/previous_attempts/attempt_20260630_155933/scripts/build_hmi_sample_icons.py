"""Build an 8-icon chunky industrial HMI pictogram sample set.

This is intentionally separate from the full 30-icon generator. It creates a
small review sample for the heavier filled/outlined injection molding HMI
direction before the full pack is rebuilt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Callable

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "assets" / "icons" / "hmi_sample"
SVG_STANDALONE = OUT_ROOT / "svg" / "standalone"
SVG_TILE = OUT_ROOT / "svg" / "tile"
PNG_256 = OUT_ROOT / "png" / "256"
PREVIEW = OUT_ROOT / "preview"

VIEWBOX = 64
PRIMARY = "#00A6C8"
ACCENT = "#A6CE39"
MACHINE = "#9AA6AD"
DARK = "#1E2A32"
TILE_BG = "#FFFFFF"
TILE_BORDER = "#D6DEE4"
PAGE_BG = "#F6F8FA"

SAMPLE_NAMES = (
    "robot",
    "mold",
    "eoat",
    "injection_unit",
    "vacuum",
    "pressure_air",
    "compatibility",
    "machine",
)


def fmt(value: float | int) -> str:
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def rgba(color: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    raw = color.lstrip("#")
    return (
        int(raw[0:2], 16),
        int(raw[2:4], 16),
        int(raw[4:6], 16),
        max(0, min(255, round(alpha * 255))),
    )


@dataclass(frozen=True)
class Element:
    kind: str
    attrs: dict[str, object] = field(default_factory=dict)


class Canvas:
    def __init__(self) -> None:
        self.elements: list[Element] = []

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        rx: float = 4,
        fill: str = PRIMARY,
        stroke: str = "none",
        width: float = 0,
    ) -> None:
        self.elements.append(
            Element(
                "rect",
                {"x": x, "y": y, "w": w, "h": h, "rx": rx, "fill": fill, "stroke": stroke, "width": width},
            )
        )

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        fill: str = PRIMARY,
        stroke: str = "none",
        width: float = 0,
    ) -> None:
        self.elements.append(
            Element("circle", {"cx": cx, "cy": cy, "r": r, "fill": fill, "stroke": stroke, "width": width})
        )

    def ellipse(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        fill: str = PRIMARY,
        stroke: str = "none",
        width: float = 0,
    ) -> None:
        self.elements.append(
            Element(
                "ellipse",
                {"cx": cx, "cy": cy, "rx": rx, "ry": ry, "fill": fill, "stroke": stroke, "width": width},
            )
        )

    def polygon(
        self,
        points: list[tuple[float, float]],
        fill: str = PRIMARY,
        stroke: str = "none",
        width: float = 0,
    ) -> None:
        self.elements.append(Element("polygon", {"points": points, "fill": fill, "stroke": stroke, "width": width}))

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str = PRIMARY,
        width: float = 4,
    ) -> None:
        self.elements.append(
            Element("line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "stroke": color, "width": width})
        )

    def polyline(self, points: list[tuple[float, float]], color: str = PRIMARY, width: float = 4) -> None:
        self.elements.append(Element("polyline", {"points": points, "stroke": color, "width": width}))


def arrow_block(canvas: Canvas, x: float, y: float, w: float, h: float, direction: str = "right") -> None:
    if direction == "right":
        pts = [
            (x, y + h * 0.25),
            (x + w * 0.58, y + h * 0.25),
            (x + w * 0.58, y),
            (x + w, y + h * 0.5),
            (x + w * 0.58, y + h),
            (x + w * 0.58, y + h * 0.75),
            (x, y + h * 0.75),
        ]
    elif direction == "down":
        pts = [
            (x + w * 0.25, y),
            (x + w * 0.75, y),
            (x + w * 0.75, y + h * 0.58),
            (x + w, y + h * 0.58),
            (x + w * 0.5, y + h),
            (x, y + h * 0.58),
            (x + w * 0.25, y + h * 0.58),
        ]
    else:
        raise ValueError(direction)
    canvas.polygon(pts, fill=ACCENT)


def suction_cup(canvas: Canvas, cx: float, top: float, scale: float = 1.0, fill: str = PRIMARY) -> None:
    half_top = 5.5 * scale
    half_bottom = 11 * scale
    height = 12 * scale
    canvas.polygon(
        [
            (cx - half_top, top),
            (cx + half_top, top),
            (cx + half_bottom, top + height),
            (cx - half_bottom, top + height),
        ],
        fill=fill,
    )
    canvas.rect(cx - 12 * scale, top + height + 2 * scale, 24 * scale, 4 * scale, rx=2 * scale, fill=MACHINE)


def draw_robot(canvas: Canvas) -> None:
    canvas.rect(7, 9, 50, 9, rx=4, fill=MACHINE)
    canvas.rect(10, 17, 7, 35, rx=3, fill=MACHINE)
    canvas.rect(47, 17, 7, 35, rx=3, fill=MACHINE)
    canvas.rect(23, 7, 18, 16, rx=5, fill=PRIMARY)
    canvas.rect(27, 21, 10, 24, rx=4, fill=PRIMARY)
    canvas.rect(22, 42, 20, 10, rx=4, fill=PRIMARY)
    canvas.rect(25, 52, 14, 5, rx=2.5, fill=MACHINE)


def draw_mold(canvas: Canvas) -> None:
    canvas.rect(8, 12, 22, 40, rx=5, fill=PRIMARY)
    canvas.rect(34, 12, 22, 40, rx=5, fill=PRIMARY)
    canvas.rect(30, 10, 4, 44, rx=2, fill=MACHINE)
    canvas.circle(19, 25, 5, fill=MACHINE)
    canvas.circle(19, 39, 5, fill=MACHINE)
    canvas.circle(45, 25, 5, fill=MACHINE)
    canvas.circle(45, 39, 5, fill=MACHINE)
    canvas.rect(27, 24, 4, 16, rx=2, fill=ACCENT)
    canvas.rect(33, 24, 4, 16, rx=2, fill=ACCENT)


def draw_eoat(canvas: Canvas) -> None:
    canvas.rect(12, 12, 40, 13, rx=5, fill=PRIMARY)
    canvas.rect(16, 26, 32, 9, rx=4, fill=PRIMARY)
    canvas.rect(18, 35, 8, 9, rx=3, fill=MACHINE)
    canvas.rect(38, 35, 8, 9, rx=3, fill=MACHINE)
    suction_cup(canvas, 22, 42, scale=0.75, fill=PRIMARY)
    suction_cup(canvas, 42, 42, scale=0.75, fill=PRIMARY)
    canvas.rect(25, 17, 14, 4, rx=2, fill=ACCENT)


def draw_injection_unit(canvas: Canvas) -> None:
    canvas.rect(7, 24, 31, 16, rx=7, fill=PRIMARY)
    canvas.polygon([(36, 22), (51, 32), (36, 42)], fill=PRIMARY)
    canvas.rect(52, 12, 6, 40, rx=3, fill=MACHINE)
    canvas.rect(13, 29, 21, 6, rx=3, fill=MACHINE)
    canvas.polygon([(44, 29), (52, 32), (44, 35)], fill=ACCENT)


def draw_vacuum(canvas: Canvas) -> None:
    canvas.rect(27, 8, 10, 21, rx=4, fill=PRIMARY)
    suction_cup(canvas, 32, 28, scale=1.12, fill=PRIMARY)
    canvas.rect(14, 54, 36, 5, rx=2.5, fill=MACHINE)
    arrow_block(canvas, 26, 41, 12, 11, direction="down")


def draw_pressure_air(canvas: Canvas) -> None:
    canvas.rect(7, 25, 24, 14, rx=5, fill=PRIMARY)
    canvas.polygon([(29, 22), (44, 32), (29, 42)], fill=PRIMARY)
    canvas.rect(12, 30, 17, 4, rx=2, fill=MACHINE)
    arrow_block(canvas, 43, 25, 15, 14, direction="right")


def draw_compatibility(canvas: Canvas) -> None:
    canvas.rect(7, 24, 20, 22, rx=5, fill=PRIMARY)
    canvas.rect(12, 17, 5, 10, rx=2.5, fill=MACHINE)
    canvas.rect(20, 17, 5, 10, rx=2.5, fill=MACHINE)
    canvas.rect(37, 13, 20, 14, rx=5, fill=PRIMARY)
    canvas.rect(40, 27, 6, 16, rx=3, fill=PRIMARY)
    canvas.rect(49, 27, 6, 16, rx=3, fill=PRIMARY)
    canvas.rect(39, 45, 18, 5, rx=2.5, fill=MACHINE)
    canvas.rect(27, 32, 10, 6, rx=3, fill=MACHINE)
    canvas.polygon([(22, 47), (27, 52), (36, 41), (32, 38), (27, 45), (25, 43)], fill=ACCENT)


def draw_machine(canvas: Canvas) -> None:
    canvas.rect(6, 38, 52, 13, rx=5, fill=PRIMARY)
    canvas.rect(10, 24, 15, 18, rx=4, fill=MACHINE)
    canvas.rect(29, 21, 10, 21, rx=4, fill=PRIMARY)
    canvas.rect(41, 26, 14, 8, rx=4, fill=MACHINE)
    canvas.polygon([(39, 28), (46, 32), (39, 36)], fill=PRIMARY)
    canvas.rect(10, 53, 46, 5, rx=2.5, fill=MACHINE)
    canvas.circle(16, 44, 3, fill=ACCENT)
    canvas.circle(49, 44, 3, fill=ACCENT)


@dataclass(frozen=True)
class IconSpec:
    name: str
    display_name: str
    description: str
    draw: Callable[[Canvas], None]


SPECS: tuple[IconSpec, ...] = (
    IconSpec("robot", "Robot", "Chunky gantry robot with rail, carriage, and vertical arm.", draw_robot),
    IconSpec("mold", "Mold", "Bold paired mold blocks with center parting strip and cavity marks.", draw_mold),
    IconSpec("eoat", "EOAT", "Filled EOAT tooling plate with suction cup tooling.", draw_eoat),
    IconSpec("injection_unit", "Injection Unit", "Heavy barrel and nozzle shape aimed at a mold plate.", draw_injection_unit),
    IconSpec("vacuum", "Vacuum", "Large suction cup pulling onto a surface.", draw_vacuum),
    IconSpec("pressure_air", "Pressure Air", "Chunky pressure nozzle pushing air outward.", draw_pressure_air),
    IconSpec("compatibility", "Compatibility", "Machine and EOAT blocks connected by a fit/check symbol.", draw_compatibility),
    IconSpec("machine", "Machine", "Simplified injection molding machine silhouette.", draw_machine),
)


def canvas_for(spec: IconSpec) -> Canvas:
    canvas = Canvas()
    spec.draw(canvas)
    return canvas


def element_to_svg(element: Element) -> str:
    attrs = element.attrs
    if element.kind == "rect":
        return (
            f'<rect x="{fmt(attrs["x"])}" y="{fmt(attrs["y"])}" width="{fmt(attrs["w"])}" height="{fmt(attrs["h"])}" '
            f'rx="{fmt(attrs["rx"])}" fill="{escape(str(attrs["fill"]))}" stroke="{escape(str(attrs["stroke"]))}" '
            f'stroke-width="{fmt(attrs["width"])}" />'
        )
    if element.kind == "circle":
        return (
            f'<circle cx="{fmt(attrs["cx"])}" cy="{fmt(attrs["cy"])}" r="{fmt(attrs["r"])}" '
            f'fill="{escape(str(attrs["fill"]))}" stroke="{escape(str(attrs["stroke"]))}" stroke-width="{fmt(attrs["width"])}" />'
        )
    if element.kind == "ellipse":
        return (
            f'<ellipse cx="{fmt(attrs["cx"])}" cy="{fmt(attrs["cy"])}" rx="{fmt(attrs["rx"])}" ry="{fmt(attrs["ry"])}" '
            f'fill="{escape(str(attrs["fill"]))}" stroke="{escape(str(attrs["stroke"]))}" stroke-width="{fmt(attrs["width"])}" />'
        )
    if element.kind == "polygon":
        points = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in attrs["points"])
        return (
            f'<polygon points="{points}" fill="{escape(str(attrs["fill"]))}" stroke="{escape(str(attrs["stroke"]))}" '
            f'stroke-width="{fmt(attrs["width"])}" />'
        )
    if element.kind == "line":
        return (
            f'<line x1="{fmt(attrs["x1"])}" y1="{fmt(attrs["y1"])}" x2="{fmt(attrs["x2"])}" y2="{fmt(attrs["y2"])}" '
            f'stroke="{escape(str(attrs["stroke"]))}" stroke-width="{fmt(attrs["width"])}" />'
        )
    if element.kind == "polyline":
        points = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in attrs["points"])
        return (
            f'<polyline points="{points}" fill="none" stroke="{escape(str(attrs["stroke"]))}" '
            f'stroke-width="{fmt(attrs["width"])}" />'
        )
    raise ValueError(f"Unknown element type: {element.kind}")


def render_svg(spec: IconSpec, tile: bool = False) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-labelledby="{spec.name}-title {spec.name}-desc">',
        f'  <title id="{spec.name}-title">{escape(spec.display_name)}</title>',
        f'  <desc id="{spec.name}-desc">{escape(spec.description)}</desc>',
    ]
    if tile:
        lines.append(f'  <rect x="4" y="4" width="56" height="56" rx="12" fill="{TILE_BG}" stroke="{TILE_BORDER}" stroke-width="1.5" />')
        lines.append('  <g transform="translate(3.2 3.2) scale(0.9)" stroke-linecap="round" stroke-linejoin="round">')
    else:
        lines.append('  <g stroke-linecap="round" stroke-linejoin="round">')
    lines.extend(f"    {element_to_svg(element)}" for element in canvas_for(spec).elements)
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def svg_path(spec: IconSpec, tile: bool = False) -> Path:
    return (SVG_TILE if tile else SVG_STANDALONE) / f"{spec.name}.svg"


def png_path(spec: IconSpec, tile: bool = False) -> Path:
    return PNG_256 / f"{spec.name}{'_tile' if tile else ''}.png"


def make_dirs() -> None:
    for folder in (SVG_STANDALONE, SVG_TILE, PNG_256, PREVIEW):
        folder.mkdir(parents=True, exist_ok=True)


def clean_owned_outputs() -> None:
    paths = [OUT_ROOT / "README.md", OUT_ROOT / "sample_manifest.json", PREVIEW / "hmi_sample_contact_sheet.png", PREVIEW / "hmi_sample_preview.html"]
    for spec in SPECS:
        paths.extend([svg_path(spec), svg_path(spec, tile=True), png_path(spec), png_path(spec, tile=True)])
    for path in paths:
        if path.exists() and path.is_file():
            path.unlink()


def tx(value: float, scale: float, tile: bool) -> float:
    return (3.2 + value * 0.9) * scale if tile else value * scale


def render_element(draw: ImageDraw.ImageDraw, element: Element, scale: float, tile: bool) -> None:
    attrs = element.attrs
    if element.kind == "rect":
        box = (
            tx(float(attrs["x"]), scale, tile),
            tx(float(attrs["y"]), scale, tile),
            tx(float(attrs["x"]) + float(attrs["w"]), scale, tile),
            tx(float(attrs["y"]) + float(attrs["h"]), scale, tile),
        )
        draw.rounded_rectangle(box, radius=float(attrs["rx"]) * scale * (0.9 if tile else 1), fill=rgba(str(attrs["fill"])))
    elif element.kind == "circle":
        cx = float(attrs["cx"])
        cy = float(attrs["cy"])
        r = float(attrs["r"])
        draw.ellipse((tx(cx - r, scale, tile), tx(cy - r, scale, tile), tx(cx + r, scale, tile), tx(cy + r, scale, tile)), fill=rgba(str(attrs["fill"])))
    elif element.kind == "ellipse":
        cx = float(attrs["cx"])
        cy = float(attrs["cy"])
        rx = float(attrs["rx"])
        ry = float(attrs["ry"])
        draw.ellipse((tx(cx - rx, scale, tile), tx(cy - ry, scale, tile), tx(cx + rx, scale, tile), tx(cy + ry, scale, tile)), fill=rgba(str(attrs["fill"])))
    elif element.kind == "polygon":
        draw.polygon([(tx(x, scale, tile), tx(y, scale, tile)) for x, y in attrs["points"]], fill=rgba(str(attrs["fill"])))
    elif element.kind == "line":
        width = max(1, round(float(attrs["width"]) * scale * (0.9 if tile else 1)))
        draw.line((tx(float(attrs["x1"]), scale, tile), tx(float(attrs["y1"]), scale, tile), tx(float(attrs["x2"]), scale, tile), tx(float(attrs["y2"]), scale, tile)), fill=rgba(str(attrs["stroke"])), width=width)
    elif element.kind == "polyline":
        width = max(1, round(float(attrs["width"]) * scale * (0.9 if tile else 1)))
        draw.line([(tx(x, scale, tile), tx(y, scale, tile)) for x, y in attrs["points"]], fill=rgba(str(attrs["stroke"])), width=width, joint="curve")


def render_png(spec: IconSpec, size: int = 256, tile: bool = False) -> Image.Image:
    supersample = 3
    scale = size * supersample / VIEWBOX
    image = Image.new("RGBA", (size * supersample, size * supersample), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    if tile:
        draw.rounded_rectangle(
            (4 * scale, 4 * scale, 60 * scale, 60 * scale),
            radius=12 * scale,
            fill=rgba(TILE_BG),
            outline=rgba(TILE_BORDER),
            width=max(1, round(1.5 * scale)),
        )
    for element in canvas_for(spec).elements:
        render_element(draw, element, scale, tile)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def write_svgs() -> int:
    count = 0
    for spec in SPECS:
        svg_path(spec).write_text(render_svg(spec), encoding="utf-8")
        svg_path(spec, tile=True).write_text(render_svg(spec, tile=True), encoding="utf-8")
        count += 2
    return count


def write_png_previews() -> int:
    if not PIL_AVAILABLE:
        return 0
    count = 0
    for spec in SPECS:
        render_png(spec, 256).save(png_path(spec))
        render_png(spec, 256, tile=True).save(png_path(spec, tile=True))
        count += 2
    return count


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


def write_contact_sheet() -> Path | None:
    if not PIL_AVAILABLE:
        return None
    cols = 4
    cell_w = 254
    cell_h = 188
    header_h = 70
    image = Image.new("RGBA", (cols * cell_w + 36, header_h + 2 * cell_h + 32), rgba(PAGE_BG))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((24, 22), "Chunky Industrial HMI Sample Icons", font=load_font(24, True), fill=rgba(DARK))
    draw.text((24, 49), "8-icon review sample: filled pictogram direction, standalone + tile", font=load_font(12), fill=rgba(MACHINE))

    for index, spec in enumerate(SPECS):
        x = 16 + (index % cols) * cell_w
        y = header_h + (index // cols) * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 14, y + cell_h - 14), radius=9, fill=rgba("#FFFFFF"), outline=rgba(TILE_BORDER), width=1)
        stand = render_png(spec, 82)
        tile = render_png(spec, 92, tile=True)
        image.alpha_composite(stand, (x + 42, y + 34))
        image.alpha_composite(tile, (x + 132, y + 29))
        draw.text((x + (cell_w - 14) // 2, y + 132), spec.display_name, font=load_font(16, True), fill=rgba(DARK), anchor="mm")
        draw.text((x + (cell_w - 14) // 2, y + 153), spec.name, font=load_font(12), fill=rgba(MACHINE), anchor="mm")

    path = PREVIEW / "hmi_sample_contact_sheet.png"
    image.save(path)
    return path


def write_preview_html() -> Path:
    cards = []
    for spec in SPECS:
        cards.append(
            f"""
      <article class="card">
        <div class="icons">
          <div class="checker"><img src="../svg/standalone/{spec.name}.svg" alt="{escape(spec.display_name)} standalone"></div>
          <img class="tile" src="../svg/tile/{spec.name}.svg" alt="{escape(spec.display_name)} tile">
        </div>
        <h2>{escape(spec.display_name)}</h2>
        <code>{escape(spec.name)}</code>
      </article>"""
        )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chunky Industrial HMI Sample Icons</title>
  <style>
    :root {{
      --primary: {PRIMARY};
      --accent: {ACCENT};
      --machine: {MACHINE};
      --dark: {DARK};
      --page: {PAGE_BG};
      --border: {TILE_BORDER};
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--page); color: var(--dark); font-family: "Segoe UI", Arial, sans-serif; }}
    header {{ padding: 28px 32px 18px; background: #fff; border-bottom: 1px solid var(--border); }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    main {{ padding: 24px 32px 36px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 16px; min-height: 178px; }}
    .icons {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: center; min-height: 94px; }}
    img {{ width: 82px; height: 82px; justify-self: center; }}
    .tile {{ width: 92px; height: 92px; }}
    .checker {{ display: grid; place-items: center; height: 94px; border-radius: 8px; background:
      linear-gradient(45deg, #eef2f5 25%, transparent 25%),
      linear-gradient(-45deg, #eef2f5 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #eef2f5 75%),
      linear-gradient(-45deg, transparent 75%, #eef2f5 75%);
      background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; }}
    h2 {{ margin: 12px 0 5px; font-size: 16px; letter-spacing: 0; }}
    code {{ color: var(--primary); font-size: 12px; }}
  </style>
</head>
<body>
  <header><h1>Chunky Industrial HMI Sample Icons</h1></header>
  <main><section class="grid">{''.join(cards)}
  </section></main>
</body>
</html>
"""
    path = PREVIEW / "hmi_sample_preview.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_manifest() -> Path:
    manifest = {
        "name": "chunky_industrial_hmi_sample_icons",
        "status": "sample_for_review",
        "scope": "8 icons only; full 30-icon pack not rebuilt",
        "colors": {"PRIMARY": PRIMARY, "ACCENT": ACCENT, "MACHINE": MACHINE, "DARK": DARK},
        "icons": [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "description": spec.description,
                "svg_standalone": str(svg_path(spec).relative_to(ROOT)).replace("\\", "/"),
                "svg_tile": str(svg_path(spec, tile=True).relative_to(ROOT)).replace("\\", "/"),
                "png_preview": str(png_path(spec).relative_to(ROOT)).replace("\\", "/"),
                "png_tile_preview": str(png_path(spec, tile=True).relative_to(ROOT)).replace("\\", "/"),
            }
            for spec in SPECS
        ],
    }
    path = OUT_ROOT / "sample_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def write_readme() -> Path:
    readme = """# Chunky Industrial HMI Sample Icons

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
"""
    path = OUT_ROOT / "README.md"
    path.write_text(readme, encoding="utf-8")
    return path


def validate() -> list[str]:
    missing: list[str] = []
    for spec in SPECS:
        for path in (svg_path(spec), svg_path(spec, tile=True)):
            if not path.exists():
                missing.append(str(path.relative_to(ROOT)))
            elif 'viewBox="0 0 64 64"' not in path.read_text(encoding="utf-8"):
                missing.append(f"{path.relative_to(ROOT)} missing viewBox")
    return missing


def main() -> int:
    make_dirs()
    clean_owned_outputs()
    svg_count = write_svgs()
    png_count = write_png_previews()
    contact = write_contact_sheet()
    html = write_preview_html()
    manifest = write_manifest()
    readme = write_readme()
    missing = validate()

    print("Chunky industrial HMI sample build summary")
    print(f"- Sample icons: {len(SPECS)}")
    print(f"- SVG files written: {svg_count}")
    print(f"- PNG preview files written: {png_count}")
    print(f"- Contact sheet: {contact.relative_to(ROOT) if contact else 'skipped; Pillow missing'}")
    print(f"- HTML preview: {html.relative_to(ROOT)}")
    print(f"- Manifest: {manifest.relative_to(ROOT)}")
    print(f"- README: {readme.relative_to(ROOT)}")
    if missing:
        print("- Validation failed:")
        for item in missing:
            print(f"  - {item}")
        return 1
    print("- Validation: all 8 standalone and tile SVG samples exist with viewBox 0 0 64 64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
