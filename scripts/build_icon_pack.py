"""Build the EOAT Atlas HMI-style 10-icon sample pack.

This script intentionally stops at the requested 10 sample icons. It does not
generate the full 30-icon pack until the sample style is approved.
"""

from __future__ import annotations

import importlib.util
import json
import math
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
ICON_ROOT = ROOT / "assets" / "icons"
SVG_STANDALONE = ICON_ROOT / "svg" / "standalone"
SVG_TILE = ICON_ROOT / "svg" / "tile"
PNG_ROOT = ICON_ROOT / "png"
PREVIEW = ICON_ROOT / "preview"

VIEWBOX = 64
ATLAS_CYAN = "#00A6C8"
ATLAS_LIME = "#A6CE39"
MACHINE_GRAY = "#9AA6AD"
DARK = "#1E2A32"
TILE_BG = "#FFFFFF"
TILE_BORDER = "#D6DEE4"
PAGE_BG = "#F6F8FA"
PNG_SIZES = (32, 64, 128, 256)


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
        fill: str = ATLAS_CYAN,
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
        fill: str = ATLAS_CYAN,
        stroke: str = "none",
        width: float = 0,
    ) -> None:
        self.elements.append(
            Element("circle", {"cx": cx, "cy": cy, "r": r, "fill": fill, "stroke": stroke, "width": width})
        )

    def polygon(
        self,
        points: list[tuple[float, float]],
        fill: str = ATLAS_CYAN,
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
        color: str = ATLAS_CYAN,
        width: float = 6,
    ) -> None:
        self.elements.append(
            Element("line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "stroke": color, "width": width})
        )

    def polyline(self, points: list[tuple[float, float]], color: str = ATLAS_CYAN, width: float = 6) -> None:
        self.elements.append(Element("polyline", {"points": points, "stroke": color, "width": width}))


def block_arrow(canvas: Canvas, x: float, y: float, w: float, h: float, direction: str = "right") -> None:
    if direction == "right":
        points = [
            (x, y + h * 0.28),
            (x + w * 0.58, y + h * 0.28),
            (x + w * 0.58, y),
            (x + w, y + h * 0.5),
            (x + w * 0.58, y + h),
            (x + w * 0.58, y + h * 0.72),
            (x, y + h * 0.72),
        ]
    elif direction == "down":
        points = [
            (x + w * 0.28, y),
            (x + w * 0.72, y),
            (x + w * 0.72, y + h * 0.58),
            (x + w, y + h * 0.58),
            (x + w * 0.5, y + h),
            (x, y + h * 0.58),
            (x + w * 0.28, y + h * 0.58),
        ]
    else:
        raise ValueError(direction)
    canvas.polygon(points, fill=ATLAS_LIME)


def check_shape(canvas: Canvas, x: float, y: float, s: float = 1.0) -> None:
    canvas.polygon(
        [
            (x, y + 5 * s),
            (x + 4 * s, y + 9 * s),
            (x + 13 * s, y),
            (x + 16 * s, y + 4 * s),
            (x + 4 * s, y + 16 * s),
            (x - 3 * s, y + 9 * s),
        ],
        fill=ATLAS_LIME,
    )


def suction_cup(canvas: Canvas, cx: float, top: float, scale: float = 1.0, fill: str = ATLAS_CYAN) -> None:
    top_half = 5.5 * scale
    bottom_half = 11 * scale
    height = 12 * scale
    canvas.polygon(
        [
            (cx - top_half, top),
            (cx + top_half, top),
            (cx + bottom_half, top + height),
            (cx - bottom_half, top + height),
        ],
        fill=fill,
    )
    canvas.rect(cx - 12 * scale, top + height + 2 * scale, 24 * scale, 4.5 * scale, rx=2.2 * scale, fill=MACHINE_GRAY)


def draw_robot(canvas: Canvas) -> None:
    canvas.rect(6, 9, 52, 9, rx=4.5, fill=MACHINE_GRAY)
    canvas.rect(9, 17, 8, 35, rx=3.5, fill=MACHINE_GRAY)
    canvas.rect(47, 17, 8, 35, rx=3.5, fill=MACHINE_GRAY)
    canvas.rect(23, 6, 18, 18, rx=5, fill=ATLAS_CYAN)
    canvas.rect(27, 21, 10, 25, rx=4, fill=ATLAS_CYAN)
    canvas.rect(21, 42, 22, 10, rx=4, fill=ATLAS_CYAN)
    canvas.rect(25, 52, 14, 5, rx=2.5, fill=MACHINE_GRAY)
    canvas.rect(29, 12, 6, 6, rx=2, fill=ATLAS_LIME)


def draw_mold(canvas: Canvas) -> None:
    canvas.rect(7, 11, 23, 42, rx=5, fill=ATLAS_CYAN)
    canvas.rect(34, 11, 23, 42, rx=5, fill=ATLAS_CYAN)
    canvas.rect(30, 8, 4, 48, rx=2, fill=MACHINE_GRAY)
    canvas.circle(19, 25, 5, fill=MACHINE_GRAY)
    canvas.circle(19, 39, 5, fill=MACHINE_GRAY)
    canvas.circle(45, 25, 5, fill=MACHINE_GRAY)
    canvas.circle(45, 39, 5, fill=MACHINE_GRAY)
    canvas.rect(27, 23, 4, 18, rx=2, fill=ATLAS_LIME)
    canvas.rect(33, 23, 4, 18, rx=2, fill=ATLAS_LIME)


def draw_eoat(canvas: Canvas) -> None:
    canvas.rect(10, 11, 44, 13, rx=5, fill=ATLAS_CYAN)
    canvas.rect(15, 26, 34, 10, rx=4, fill=ATLAS_CYAN)
    canvas.rect(18, 35, 8, 9, rx=3, fill=MACHINE_GRAY)
    canvas.rect(38, 35, 8, 9, rx=3, fill=MACHINE_GRAY)
    suction_cup(canvas, 22, 42, scale=0.75, fill=ATLAS_CYAN)
    suction_cup(canvas, 42, 42, scale=0.75, fill=ATLAS_CYAN)
    canvas.rect(25, 16, 14, 5, rx=2.5, fill=ATLAS_LIME)


def draw_injection_unit(canvas: Canvas) -> None:
    canvas.rect(6, 24, 32, 16, rx=8, fill=ATLAS_CYAN)
    canvas.polygon([(36, 21), (52, 32), (36, 43)], fill=ATLAS_CYAN)
    canvas.rect(53, 10, 6, 44, rx=3, fill=MACHINE_GRAY)
    canvas.rect(13, 29, 21, 6, rx=3, fill=MACHINE_GRAY)
    canvas.polygon([(44, 28), (53, 32), (44, 36)], fill=ATLAS_LIME)


def draw_ejector(canvas: Canvas) -> None:
    canvas.rect(6, 14, 20, 38, rx=5, fill=ATLAS_CYAN)
    canvas.rect(30, 14, 18, 38, rx=5, fill=ATLAS_CYAN)
    canvas.rect(26, 12, 4, 42, rx=2, fill=MACHINE_GRAY)
    canvas.rect(41, 27, 9, 10, rx=3, fill=MACHINE_GRAY)
    block_arrow(canvas, 47, 24, 13, 16, direction="right")
    canvas.rect(13, 24, 6, 17, rx=3, fill=MACHINE_GRAY)


def draw_vacuum(canvas: Canvas) -> None:
    canvas.rect(27, 7, 10, 22, rx=4, fill=ATLAS_CYAN)
    suction_cup(canvas, 32, 28, scale=1.12, fill=ATLAS_CYAN)
    canvas.rect(14, 54, 36, 5, rx=2.5, fill=MACHINE_GRAY)
    block_arrow(canvas, 26, 41, 12, 11, direction="down")


def draw_pressure_air(canvas: Canvas) -> None:
    canvas.rect(6, 25, 25, 14, rx=6, fill=ATLAS_CYAN)
    canvas.polygon([(29, 21), (45, 32), (29, 43)], fill=ATLAS_CYAN)
    canvas.rect(12, 30, 17, 4, rx=2, fill=MACHINE_GRAY)
    block_arrow(canvas, 43, 25, 15, 14, direction="right")


def draw_air_circuit(canvas: Canvas) -> None:
    canvas.line(13, 47, 13, 29, color=ATLAS_CYAN, width=8)
    canvas.line(13, 29, 26, 29, color=ATLAS_CYAN, width=8)
    canvas.line(26, 29, 26, 41, color=ATLAS_CYAN, width=8)
    canvas.line(26, 41, 44, 41, color=ATLAS_CYAN, width=8)
    canvas.line(44, 41, 44, 21, color=ATLAS_CYAN, width=8)
    canvas.circle(13, 47, 5, fill=MACHINE_GRAY)
    canvas.circle(44, 21, 5, fill=MACHINE_GRAY)
    block_arrow(canvas, 28, 34, 14, 12, direction="right")


def draw_compatibility(canvas: Canvas) -> None:
    canvas.rect(6, 28, 22, 20, rx=5, fill=ATLAS_CYAN)
    canvas.rect(11, 20, 6, 10, rx=3, fill=MACHINE_GRAY)
    canvas.rect(21, 20, 6, 10, rx=3, fill=MACHINE_GRAY)
    canvas.rect(39, 12, 20, 14, rx=5, fill=ATLAS_CYAN)
    canvas.rect(42, 26, 6, 16, rx=3, fill=ATLAS_CYAN)
    canvas.rect(51, 26, 6, 16, rx=3, fill=ATLAS_CYAN)
    canvas.rect(39, 44, 20, 5, rx=2.5, fill=MACHINE_GRAY)
    canvas.rect(28, 35, 11, 6, rx=3, fill=MACHINE_GRAY)
    canvas.circle(18, 38, 3.5, fill=ATLAS_LIME)
    canvas.circle(49, 35, 3.5, fill=ATLAS_LIME)
    canvas.line(21, 38, 32, 38, color=ATLAS_LIME, width=5)
    canvas.line(32, 38, 46, 35, color=ATLAS_LIME, width=5)
    check_shape(canvas, 25, 44, s=0.75)


def draw_machine(canvas: Canvas) -> None:
    canvas.rect(5, 38, 54, 13, rx=5, fill=ATLAS_CYAN)
    canvas.rect(9, 24, 16, 18, rx=4, fill=MACHINE_GRAY)
    canvas.rect(29, 20, 10, 22, rx=4, fill=ATLAS_CYAN)
    canvas.rect(41, 26, 15, 8, rx=4, fill=MACHINE_GRAY)
    canvas.polygon([(39, 28), (46, 32), (39, 36)], fill=ATLAS_CYAN)
    canvas.rect(9, 53, 48, 5, rx=2.5, fill=MACHINE_GRAY)
    canvas.circle(16, 44, 3, fill=ATLAS_LIME)
    canvas.circle(50, 44, 3, fill=ATLAS_LIME)


@dataclass(frozen=True)
class IconSpec:
    name: str
    display_name: str
    category: str
    description: str
    draw: Callable[[Canvas], None]


SPECS: tuple[IconSpec, ...] = (
    IconSpec("robot", "Robot", "Machine Components", "Cartesian gantry robot with rail, carriage, vertical axis, and EOAT head.", draw_robot),
    IconSpec("mold", "Mold", "Machine Components", "Two bold mold halves with center parting line and active lime center detail.", draw_mold),
    IconSpec("eoat", "EOAT", "EOAT Hardware", "Tool plate with suction cups and active pickup highlight.", draw_eoat),
    IconSpec("injection_unit", "Injection Unit", "Machine Components", "Chunky barrel and nozzle aimed into a mold plate.", draw_injection_unit),
    IconSpec("ejector", "Ejector", "Machine Components", "Mold blocks with a part pushed out by one bold lime motion arrow.", draw_ejector),
    IconSpec("vacuum", "Vacuum", "Pneumatics", "Large suction cup pulling onto a surface.", draw_vacuum),
    IconSpec("pressure_air", "Pressure Air", "Pneumatics", "Pressure nozzle with one bold outward airflow arrow.", draw_pressure_air),
    IconSpec("air_circuit", "Air Circuit", "Pneumatics", "Chunky routed tubing with connector endpoints and one airflow arrow.", draw_air_circuit),
    IconSpec("compatibility", "Compatibility", "App Navigation", "Machine/mold and EOAT blocks connected by a lime Atlas-style path and check.", draw_compatibility),
    IconSpec("machine", "Machine", "Machine Components", "Simplified injection molding machine silhouette with base, clamp area, and injection unit.", draw_machine),
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
        return f'<polyline points="{points}" fill="none" stroke="{escape(str(attrs["stroke"]))}" stroke-width="{fmt(attrs["width"])}" />'
    raise ValueError(f"Unknown element kind: {element.kind}")


def render_svg(spec: IconSpec, tile: bool = False) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-labelledby="{spec.name}-title {spec.name}-desc">',
        f'  <title id="{spec.name}-title">{escape(spec.display_name)}</title>',
        f'  <desc id="{spec.name}-desc">{escape(spec.description)}</desc>',
    ]
    if tile:
        lines.append(f'  <rect x="4" y="4" width="56" height="56" rx="12" fill="{TILE_BG}" stroke="{TILE_BORDER}" stroke-width="1.5" />')
        lines.append('  <g transform="translate(2.6 2.6) scale(0.92)" stroke-linecap="round" stroke-linejoin="round">')
    else:
        lines.append('  <g stroke-linecap="round" stroke-linejoin="round">')
    lines.extend(f"    {element_to_svg(element)}" for element in canvas_for(spec).elements)
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def svg_path(spec: IconSpec, tile: bool = False) -> Path:
    return (SVG_TILE if tile else SVG_STANDALONE) / f"{spec.name}.svg"


def png_path(spec: IconSpec, size: int, tile: bool = False) -> Path:
    return PNG_ROOT / str(size) / f"{spec.name}{'_tile' if tile else ''}.png"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def make_dirs() -> None:
    for folder in (SVG_STANDALONE, SVG_TILE, PREVIEW):
        folder.mkdir(parents=True, exist_ok=True)
    for size in PNG_SIZES:
        (PNG_ROOT / str(size)).mkdir(parents=True, exist_ok=True)


def clean_owned_outputs() -> None:
    paths: list[Path] = [
        ICON_ROOT / "icon_manifest.json",
        ICON_ROOT / "README.md",
        PREVIEW / "atlas_hmi_sample_contact_sheet.png",
        PREVIEW / "atlas_hmi_sample_preview.html",
        PREVIEW / "style_review_notes.md",
    ]
    for spec in SPECS:
        paths.extend([svg_path(spec), svg_path(spec, tile=True)])
        for size in PNG_SIZES:
            paths.extend([png_path(spec, size), png_path(spec, size, tile=True)])
    for path in paths:
        if path.exists() and path.is_file():
            path.unlink()


def write_svgs() -> int:
    count = 0
    for spec in SPECS:
        svg_path(spec).write_text(render_svg(spec), encoding="utf-8")
        svg_path(spec, tile=True).write_text(render_svg(spec, tile=True), encoding="utf-8")
        count += 2
    return count


def write_pngs() -> tuple[int, str]:
    if importlib.util.find_spec("cairosvg") is None:
        return 0, "PNG export skipped because CairoSVG is not installed. Install with: python -m pip install cairosvg"
    try:
        import cairosvg
    except Exception as exc:
        return 0, f"PNG export skipped because CairoSVG could not load its renderer: {exc}"

    count = 0
    try:
        for spec in SPECS:
            for size in PNG_SIZES:
                for tile in (False, True):
                    cairosvg.svg2png(
                        bytestring=render_svg(spec, tile=tile).encode("utf-8"),
                        write_to=str(png_path(spec, size, tile=tile)),
                        output_width=size,
                        output_height=size,
                    )
                    count += 1
    except Exception as exc:
        return 0, f"PNG export skipped because CairoSVG could not render in this environment: {exc}"
    return count, "PNG export completed with CairoSVG."


def tx(value: float, scale: float, tile: bool) -> float:
    return (2.6 + value * 0.92) * scale if tile else value * scale


def draw_round_line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], color: str, width: int) -> None:
    if len(points) < 2:
        return
    try:
        draw.line(points, fill=rgba(color), width=width, joint="curve")
    except TypeError:
        draw.line(points, fill=rgba(color), width=width)
    radius = width / 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rgba(color))


def render_element(draw: ImageDraw.ImageDraw, element: Element, scale: float, tile: bool) -> None:
    attrs = element.attrs
    if element.kind == "rect":
        x = float(attrs["x"])
        y = float(attrs["y"])
        w = float(attrs["w"])
        h = float(attrs["h"])
        factor = 0.92 if tile else 1.0
        draw.rounded_rectangle(
            (tx(x, scale, tile), tx(y, scale, tile), tx(x + w, scale, tile), tx(y + h, scale, tile)),
            radius=float(attrs["rx"]) * scale * factor,
            fill=rgba(str(attrs["fill"])),
        )
    elif element.kind == "circle":
        cx = float(attrs["cx"])
        cy = float(attrs["cy"])
        r = float(attrs["r"])
        draw.ellipse((tx(cx - r, scale, tile), tx(cy - r, scale, tile), tx(cx + r, scale, tile), tx(cy + r, scale, tile)), fill=rgba(str(attrs["fill"])))
    elif element.kind == "polygon":
        draw.polygon([(tx(x, scale, tile), tx(y, scale, tile)) for x, y in attrs["points"]], fill=rgba(str(attrs["fill"])))
    elif element.kind == "line":
        width = max(1, round(float(attrs["width"]) * scale * (0.92 if tile else 1.0)))
        draw_round_line(
            draw,
            [
                (tx(float(attrs["x1"]), scale, tile), tx(float(attrs["y1"]), scale, tile)),
                (tx(float(attrs["x2"]), scale, tile), tx(float(attrs["y2"]), scale, tile)),
            ],
            str(attrs["stroke"]),
            width,
        )
    elif element.kind == "polyline":
        width = max(1, round(float(attrs["width"]) * scale * (0.92 if tile else 1.0)))
        draw_round_line(draw, [(tx(x, scale, tile), tx(y, scale, tile)) for x, y in attrs["points"]], str(attrs["stroke"]), width)


def render_preview_png(spec: IconSpec, size: int = 96, tile: bool = False) -> Image.Image:
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


def write_contact_sheet(png_count: int) -> tuple[Path | None, str]:
    if not PIL_AVAILABLE:
        return None, "Contact sheet skipped because Pillow is not installed."
    columns = 5
    cell_w = 226
    cell_h = 178
    header_h = 72
    rows = math.ceil(len(SPECS) / columns)
    image = Image.new("RGBA", (columns * cell_w + 34, header_h + rows * cell_h + 28), rgba(PAGE_BG))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((24, 21), "EOAT Atlas HMI Sample Icons", font=load_font(24, bold=True), fill=rgba(DARK))
    draw.text((24, 49), "10-icon sample: chunky industrial pictograms, standalone + tile", font=load_font(12), fill=rgba(MACHINE_GRAY))

    for index, spec in enumerate(SPECS):
        x = 16 + (index % columns) * cell_w
        y = header_h + (index // columns) * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 12, y + cell_h - 12), radius=8, fill=rgba("#FFFFFF"), outline=rgba(TILE_BORDER), width=1)
        if png_count:
            standalone = Image.open(png_path(spec, 128, tile=False)).convert("RGBA").resize((76, 76), Image.Resampling.LANCZOS)
            tile = Image.open(png_path(spec, 128, tile=True)).convert("RGBA").resize((84, 84), Image.Resampling.LANCZOS)
        else:
            standalone = render_preview_png(spec, 76)
            tile = render_preview_png(spec, 84, tile=True)
        image.alpha_composite(standalone, (x + 36, y + 31))
        image.alpha_composite(tile, (x + 122, y + 27))
        center = x + (cell_w - 12) // 2
        draw.text((center, y + 122), spec.display_name, font=load_font(15, bold=True), fill=rgba(DARK), anchor="mm")
        draw.text((center, y + 143), spec.category, font=load_font(11), fill=rgba(MACHINE_GRAY), anchor="mm")

    path = PREVIEW / "atlas_hmi_sample_contact_sheet.png"
    image.save(path)
    if png_count:
        return path, "Contact sheet generated from exported PNGs."
    return path, "Contact sheet generated with internal preview renderer because CairoSVG PNG export was unavailable."


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
        <p>{escape(spec.category)}</p>
        <code>{escape(spec.name)}</code>
      </article>"""
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EOAT Atlas HMI Sample Icons</title>
  <style>
    :root {{
      --cyan: {ATLAS_CYAN};
      --lime: {ATLAS_LIME};
      --gray: {MACHINE_GRAY};
      --dark: {DARK};
      --page: {PAGE_BG};
      --border: {TILE_BORDER};
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--page); color: var(--dark); font-family: "Segoe UI", Arial, sans-serif; }}
    header {{ padding: 28px 32px 18px; background: #fff; border-bottom: 1px solid var(--border); }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    main {{ padding: 24px 32px 36px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 16px; min-height: 184px; }}
    .icons {{ display: grid; grid-template-columns: 1fr 1fr; align-items: center; gap: 12px; min-height: 96px; }}
    img {{ width: 78px; height: 78px; justify-self: center; }}
    .tile {{ width: 88px; height: 88px; }}
    .checker {{ display: grid; place-items: center; height: 94px; border-radius: 8px; background:
      linear-gradient(45deg, #eef2f5 25%, transparent 25%),
      linear-gradient(-45deg, #eef2f5 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #eef2f5 75%),
      linear-gradient(-45deg, transparent 75%, #eef2f5 75%);
      background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; }}
    h2 {{ margin: 12px 0 3px; font-size: 16px; letter-spacing: 0; }}
    p {{ margin: 0 0 8px; color: var(--gray); font-size: 12px; }}
    code {{ color: var(--cyan); font-size: 12px; }}
  </style>
</head>
<body>
  <header><h1>EOAT Atlas HMI Sample Icons</h1></header>
  <main><section class="grid">
{''.join(cards)}
  </section></main>
</body>
</html>
"""
    path = PREVIEW / "atlas_hmi_sample_preview.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_manifest() -> Path:
    manifest = {
        "name": "eoat_atlas_hmi_sample_icons",
        "version": "0.1.0-sample",
        "status": "sample_for_review",
        "scope": "10 sample icons only; full pack intentionally not generated",
        "viewBox": "0 0 64 64",
        "safe_area": "x=5..59, y=5..59",
        "colors": {
            "ATLAS_CYAN": ATLAS_CYAN,
            "ATLAS_LIME": ATLAS_LIME,
            "MACHINE_GRAY": MACHINE_GRAY,
            "DARK": DARK,
            "TILE_BG": TILE_BG,
            "TILE_BORDER": TILE_BORDER,
        },
        "icons": [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "category": spec.category,
                "description": spec.description,
                "svg_standalone_path": rel(svg_path(spec)),
                "svg_tile_path": rel(svg_path(spec, tile=True)),
                "png_paths": {
                    str(size): {
                        "standalone": rel(png_path(spec, size, tile=False)),
                        "tile": rel(png_path(spec, size, tile=True)),
                    }
                    for size in PNG_SIZES
                },
            }
            for spec in SPECS
        ],
    }
    path = ICON_ROOT / "icon_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def write_readme() -> Path:
    readme = """# EOAT Atlas HMI Sample Icon Pack

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
"""
    path = ICON_ROOT / "README.md"
    path.write_text(readme, encoding="utf-8")
    return path


def write_style_review_notes() -> Path:
    notes = """# EOAT Atlas HMI Sample Style Review Notes

## Difference From Previous Generic Version

The previous attempts read as thin monoline web-app icons. This sample uses filled component masses, chunky machine blocks, large cyan silhouettes, gray rails/plates/bases, and lime-only action markers. The tile version is treated as the primary design surface.

## Closer Industrial HMI Pictogram Qualities

- Robot uses a gantry rail, carriage, vertical axis, and EOAT head rather than a humanoid metaphor.
- Mold uses heavy mold halves, cavity marks, and a center parting structure.
- Injection unit uses a bold barrel/nozzle aimed at a mold plate.
- Pneumatic icons use physical cups, nozzles, tubing, and one functional lime motion cue.
- Machine uses a simplified molding-machine silhouette with base, clamp area, and injection unit.

## Atlas Twist

Compatibility uses lime locator points and a connected path/check to suggest Atlas-style navigation and fit validation. The motif is functional and not applied to every icon.

## Icons Needing Review

- Compatibility: review whether the machine/EOAT relationship is clear enough for operators.
- Air circuit: review whether the chunky routed tubing feels pneumatic enough without becoming too diagrammatic.
- Ejector: review whether the part-and-motion cue reads as ejection rather than generic movement.

## Quality Check

The sample is intentionally bolder, chunkier, and more tile-oriented than generic Lucide/Material/Tabler icons. Lime is used for action/status only, and the robot is not humanoid.
"""
    path = PREVIEW / "style_review_notes.md"
    path.write_text(notes, encoding="utf-8")
    return path


def validate_svgs() -> list[str]:
    missing: list[str] = []
    for spec in SPECS:
        for path in (svg_path(spec), svg_path(spec, tile=True)):
            if not path.exists():
                missing.append(rel(path))
            elif 'viewBox="0 0 64 64"' not in path.read_text(encoding="utf-8"):
                missing.append(f"{rel(path)} missing required viewBox")
    return missing


def main() -> int:
    make_dirs()
    clean_owned_outputs()
    svg_count = write_svgs()
    png_count, png_status = write_pngs()
    contact_path, contact_status = write_contact_sheet(png_count)
    html_path = write_preview_html()
    manifest_path = write_manifest()
    readme_path = write_readme()
    review_path = write_style_review_notes()
    missing = validate_svgs()

    print("EOAT Atlas HMI sample build summary")
    print(f"- Sample icons: {len(SPECS)}")
    print(f"- SVG files written: {svg_count}")
    print(f"- PNG files written: {png_count}")
    print(f"- PNG status: {png_status}")
    print(f"- Contact sheet status: {contact_status}")
    print(f"- Contact sheet: {rel(contact_path) if contact_path else 'not generated'}")
    print(f"- HTML preview: {rel(html_path)}")
    print(f"- Manifest: {rel(manifest_path)}")
    print(f"- README: {rel(readme_path)}")
    print(f"- Style review notes: {rel(review_path)}")
    if missing:
        print("- Validation failed:")
        for item in missing:
            print(f"  - {item}")
        return 1
    print("- Validation: all 10 standalone and tile SVGs exist with viewBox 0 0 64 64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
