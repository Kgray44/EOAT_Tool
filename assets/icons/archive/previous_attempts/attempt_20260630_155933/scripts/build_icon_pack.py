"""Build the EOAT Atlas / EOAT Command Center icon pack.

The icons generated here are original, generic industrial HMI-inspired line
icons. The script owns the generated files for the known icon names and can be
rerun safely without touching unrelated assets.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Callable

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional contact sheet dependency
    PIL_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[1]
ICON_ROOT = ROOT / "assets" / "icons"
SVG_STANDALONE_DIR = ICON_ROOT / "svg" / "standalone"
SVG_TILE_DIR = ICON_ROOT / "svg" / "tile"
PNG_ROOT = ICON_ROOT / "png"
PREVIEW_DIR = ICON_ROOT / "preview"

VIEWBOX = 64
STROKE = 4
DETAIL_STROKE = 3
ICON_SIZES = (32, 64, 128, 256)

PRIMARY = "#00A6C8"
SECONDARY = "#9AA6AD"
ACCENT = "#A6CE39"
DARK = "#1E2A32"
LIGHT = "#F6F8FA"
TILE_BG_LIGHT = "#FFFFFF"
TILE_BORDER = "#D6DEE4"


def fmt(value: float | int) -> str:
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def hex_to_rgba(color: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
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

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str = PRIMARY,
        width: float = STROKE,
    ) -> None:
        self.elements.append(
            Element(
                "line",
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": "none",
                },
            )
        )

    def polyline(
        self,
        points: list[tuple[float, float]],
        color: str = PRIMARY,
        width: float = STROKE,
    ) -> None:
        self.elements.append(
            Element(
                "polyline",
                {
                    "points": points,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": "none",
                },
            )
        )

    def path(
        self,
        d: str,
        color: str = PRIMARY,
        width: float = STROKE,
        fill: str = "none",
    ) -> None:
        self.elements.append(
            Element(
                "path",
                {
                    "d": d,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": fill,
                },
            )
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        rx: float = 3,
        color: str = PRIMARY,
        width: float = STROKE,
        fill: str = "none",
    ) -> None:
        self.elements.append(
            Element(
                "rect",
                {
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "rx": rx,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": fill,
                },
            )
        )

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        color: str = PRIMARY,
        width: float = STROKE,
        fill: str = "none",
    ) -> None:
        self.elements.append(
            Element(
                "circle",
                {
                    "cx": cx,
                    "cy": cy,
                    "r": r,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": fill,
                },
            )
        )

    def ellipse(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        color: str = PRIMARY,
        width: float = STROKE,
        fill: str = "none",
    ) -> None:
        self.elements.append(
            Element(
                "ellipse",
                {
                    "cx": cx,
                    "cy": cy,
                    "rx": rx,
                    "ry": ry,
                    "stroke": color,
                    "stroke_width": width,
                    "fill": fill,
                },
            )
        )


def arrow_head(
    canvas: Canvas,
    tip: tuple[float, float],
    tail: tuple[float, float],
    color: str = ACCENT,
    width: float = STROKE,
    length: float = 6,
) -> None:
    angle = math.atan2(tip[1] - tail[1], tip[0] - tail[0])
    for delta in (math.radians(150), math.radians(-150)):
        x = tip[0] + math.cos(angle + delta) * length
        y = tip[1] + math.sin(angle + delta) * length
        canvas.line(tip[0], tip[1], x, y, color=color, width=width)


def arrow(
    canvas: Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str = ACCENT,
    width: float = STROKE,
) -> None:
    canvas.line(x1, y1, x2, y2, color=color, width=width)
    arrow_head(canvas, (x2, y2), (x1, y1), color=color, width=width)


def check(canvas: Canvas, x: float, y: float, scale: float = 1.0) -> None:
    canvas.polyline(
        [(x, y + 4 * scale), (x + 4 * scale, y + 8 * scale), (x + 12 * scale, y)],
        color=ACCENT,
        width=STROKE,
    )


def cup(canvas: Canvas, cx: float, y: float, color: str = PRIMARY) -> None:
    canvas.path(f"M{fmt(cx - 7)} {fmt(y)} H{fmt(cx + 7)} L{fmt(cx + 10)} {fmt(y + 10)} H{fmt(cx - 10)} Z", color=color)
    canvas.line(cx - 8, y + 14, cx + 8, y + 14, color=SECONDARY, width=DETAIL_STROKE)


def mini_eoat(canvas: Canvas, x: float, y: float) -> None:
    canvas.rect(x, y, 18, 8, rx=2, color=PRIMARY)
    canvas.line(x + 5, y + 8, x + 5, y + 15, color=PRIMARY)
    canvas.line(x + 13, y + 8, x + 13, y + 15, color=PRIMARY)
    canvas.line(x + 2, y + 15, x + 8, y + 15, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(x + 10, y + 15, x + 16, y + 15, color=SECONDARY, width=DETAIL_STROKE)


def mini_machine(canvas: Canvas, x: float, y: float) -> None:
    canvas.rect(x, y + 14, 24, 8, rx=2, color=PRIMARY)
    canvas.rect(x + 4, y, 6, 16, rx=2, color=SECONDARY)
    canvas.rect(x + 14, y + 1, 5, 15, rx=1.5, color=PRIMARY)
    canvas.line(x, y + 25, x + 24, y + 25, color=SECONDARY, width=DETAIL_STROKE)


def draw_robot(canvas: Canvas) -> None:
    canvas.path("M12 50 V14 H52 V50", color=SECONDARY)
    canvas.rect(23, 10, 18, 8, rx=2, color=PRIMARY)
    canvas.line(32, 18, 32, 36, color=PRIMARY)
    canvas.rect(24, 36, 16, 8, rx=2, color=PRIMARY)
    canvas.path("M26 44 V52 H38 V44", color=PRIMARY)


def draw_mold(canvas: Canvas) -> None:
    canvas.rect(12, 16, 16, 32, rx=3, color=PRIMARY)
    canvas.rect(36, 16, 16, 32, rx=3, color=PRIMARY)
    canvas.line(32, 14, 32, 50, color=ACCENT)
    canvas.line(16, 24, 24, 24, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(16, 40, 24, 40, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(40, 24, 48, 24, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(40, 40, 48, 40, color=SECONDARY, width=DETAIL_STROKE)


def draw_eoat(canvas: Canvas) -> None:
    canvas.path("M16 20 H48 V30 H38 V38 M26 30 V38 M16 30 H48", color=PRIMARY)
    cup(canvas, 26, 38)
    cup(canvas, 38, 38)
    canvas.line(12, 25, 16, 25, color=SECONDARY)
    canvas.line(48, 25, 52, 25, color=SECONDARY)


def draw_injection_unit(canvas: Canvas) -> None:
    canvas.path("M10 28 H38 L48 32 L38 36 H10 Z", color=PRIMARY)
    canvas.line(17, 32, 36, 32, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(22, 28, 28, 36, color=SECONDARY, width=DETAIL_STROKE)
    canvas.rect(51, 18, 5, 28, rx=2, color=SECONDARY)


def draw_ejector(canvas: Canvas) -> None:
    canvas.rect(10, 16, 14, 32, rx=3, color=PRIMARY)
    canvas.rect(30, 16, 14, 32, rx=3, color=PRIMARY)
    canvas.line(27, 16, 27, 48, color=SECONDARY)
    canvas.rect(38, 28, 8, 8, rx=2, color=SECONDARY)
    arrow(canvas, 42, 32, 54, 32)


def draw_peripherals(canvas: Canvas) -> None:
    canvas.path("M18 32 H46 M32 20 V44", color=SECONDARY)
    canvas.rect(12, 24, 14, 16, rx=3, color=PRIMARY)
    canvas.rect(25, 12, 14, 16, rx=3, color=PRIMARY)
    canvas.rect(38, 36, 14, 16, rx=3, color=PRIMARY)
    canvas.circle(32, 32, 3, color=ACCENT, width=DETAIL_STROKE)


def draw_air_circuit(canvas: Canvas) -> None:
    canvas.path("M14 44 V28 C14 20 24 20 24 28 V36 C24 44 38 44 38 36 V24 H50", color=PRIMARY)
    canvas.circle(14, 44, 3, color=SECONDARY, width=DETAIL_STROKE)
    canvas.circle(50, 24, 3, color=SECONDARY, width=DETAIL_STROKE)
    arrow(canvas, 28, 40, 38, 40)


def draw_vacuum(canvas: Canvas) -> None:
    canvas.line(32, 12, 32, 24, color=PRIMARY)
    cup(canvas, 32, 26)
    canvas.line(20, 52, 44, 52, color=SECONDARY)
    arrow(canvas, 32, 38, 32, 48)


def draw_pressure_air(canvas: Canvas) -> None:
    canvas.path("M10 28 H28 L38 32 L28 36 H10 Z", color=PRIMARY)
    arrow(canvas, 38, 32, 54, 32)


def draw_interchangeable_air(canvas: Canvas) -> None:
    canvas.line(14, 32, 24, 32, color=SECONDARY)
    canvas.line(40, 32, 50, 32, color=SECONDARY)
    canvas.rect(24, 24, 16, 16, rx=4, color=PRIMARY)
    arrow(canvas, 18, 22, 44, 22)
    arrow(canvas, 46, 42, 20, 42)


def draw_sensor(canvas: Canvas) -> None:
    canvas.rect(10, 24, 18, 16, rx=3, color=PRIMARY)
    canvas.line(28, 32, 48, 32, color=ACCENT)
    canvas.circle(52, 32, 4, color=SECONDARY)
    canvas.circle(20, 32, 2, color=SECONDARY, width=DETAIL_STROKE)


def draw_quick_disconnect(canvas: Canvas) -> None:
    canvas.path("M10 24 H27 V40 H10 Z", color=PRIMARY)
    canvas.path("M37 22 H54 V42 H37 Z", color=PRIMARY)
    canvas.line(27, 30, 36, 30, color=SECONDARY)
    canvas.line(27, 34, 36, 34, color=SECONDARY)


def draw_tubing(canvas: Canvas) -> None:
    canvas.path("M14 46 V30 C14 20 30 20 30 32 V34 C30 44 50 44 50 34 V18", color=PRIMARY)
    canvas.circle(14, 46, 4, color=SECONDARY)
    canvas.circle(50, 18, 4, color=SECONDARY)


def draw_gripper(canvas: Canvas) -> None:
    canvas.rect(28, 28, 8, 8, rx=2, color=SECONDARY)
    canvas.path("M22 16 H42 M22 16 V32 L18 44 H26 M42 16 V32 L46 44 H38", color=PRIMARY)


def draw_vacuum_cup(canvas: Canvas) -> None:
    canvas.line(32, 10, 32, 22, color=PRIMARY)
    canvas.rect(27, 20, 10, 8, rx=2, color=SECONDARY)
    cup(canvas, 32, 30)


def draw_part_present(canvas: Canvas) -> None:
    canvas.rect(14, 22, 26, 20, rx=3, color=PRIMARY)
    canvas.circle(47, 38, 7, color=ACCENT)
    check(canvas, 43, 33, scale=0.7)


def draw_compatibility(canvas: Canvas) -> None:
    canvas.path("M10 30 H30 V44 H10 Z", color=PRIMARY)
    canvas.path("M17 30 V24 M24 30 V24", color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(30, 37, 38, 37, color=SECONDARY)
    canvas.path("M38 18 H54 V28 H38 Z M43 28 V42 M49 28 V42", color=PRIMARY)
    canvas.line(40, 45, 52, 45, color=SECONDARY, width=DETAIL_STROKE)
    check(canvas, 22, 44, scale=0.55)


def draw_machine(canvas: Canvas) -> None:
    canvas.path("M8 48 H56 M10 38 H56 V48 H10 Z", color=PRIMARY)
    canvas.rect(14, 20, 10, 18, rx=2, color=SECONDARY)
    canvas.rect(28, 20, 8, 18, rx=2, color=PRIMARY)
    canvas.path("M38 31 H48 C52 31 54 29 54 27 C54 25 52 24 49 24 H42", color=SECONDARY)


def draw_press(canvas: Canvas) -> None:
    canvas.path("M18 12 H46 V20 H18 Z M18 44 H46 V52 H18 Z M22 20 V44 M42 20 V44", color=PRIMARY)
    arrow(canvas, 32, 24, 32, 31)
    arrow(canvas, 32, 40, 32, 33)


def draw_cleanroom(canvas: Canvas) -> None:
    canvas.rect(12, 14, 40, 36, rx=3, color=PRIMARY)
    canvas.line(12, 26, 52, 26, color=SECONDARY)
    canvas.line(32, 26, 32, 50, color=SECONDARY)
    check(canvas, 38, 17, scale=0.55)


def draw_maintenance(canvas: Canvas) -> None:
    canvas.rect(12, 38, 24, 10, rx=2, color=SECONDARY)
    canvas.path("M18 43 H30", color=PRIMARY, width=DETAIL_STROKE)
    canvas.path("M22 34 L43 13 L51 21 L30 42", color=PRIMARY)
    canvas.circle(22, 34, 4, color=PRIMARY)


def draw_warning(canvas: Canvas) -> None:
    canvas.path("M32 12 L54 52 H10 Z", color=PRIMARY)
    canvas.line(32, 25, 32, 38, color=ACCENT)
    canvas.circle(32, 45, 1.8, color=ACCENT, width=DETAIL_STROKE, fill=ACCENT)


def draw_analytics(canvas: Canvas) -> None:
    canvas.line(12, 52, 54, 52, color=PRIMARY)
    canvas.line(12, 52, 12, 14, color=PRIMARY)
    canvas.line(23, 52, 23, 40, color=SECONDARY)
    canvas.line(34, 52, 34, 32, color=SECONDARY)
    canvas.line(45, 52, 45, 24, color=SECONDARY)
    canvas.polyline([(18, 36), (28, 31), (38, 34), (50, 20)], color=ACCENT)
    arrow_head(canvas, (50, 20), (38, 34), color=ACCENT)


def draw_photos(canvas: Canvas) -> None:
    canvas.rect(14, 22, 36, 26, rx=4, color=PRIMARY)
    canvas.path("M23 22 L27 16 H37 L41 22", color=PRIMARY)
    canvas.circle(32, 35, 7, color=ACCENT)
    canvas.line(43, 29, 45, 29, color=SECONDARY, width=DETAIL_STROKE)


def draw_standards(canvas: Canvas) -> None:
    canvas.rect(18, 12, 28, 40, rx=3, color=PRIMARY)
    canvas.path("M38 12 V20 H46", color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(24, 27, 38, 27, color=SECONDARY, width=DETAIL_STROKE)
    check(canvas, 25, 39, scale=0.8)


def draw_checklist(canvas: Canvas) -> None:
    canvas.rect(16, 14, 32, 40, rx=3, color=PRIMARY)
    canvas.rect(24, 10, 16, 8, rx=3, color=SECONDARY)
    for y in (26, 36, 46):
        canvas.rect(22, y - 3, 6, 6, rx=1.5, color=SECONDARY, width=DETAIL_STROKE)
        canvas.line(34, y, 42, y, color=SECONDARY, width=DETAIL_STROKE)
    check(canvas, 21, 21, scale=0.45)
    check(canvas, 21, 31, scale=0.45)
    check(canvas, 21, 41, scale=0.45)


def draw_documentation(canvas: Canvas) -> None:
    canvas.path("M16 20 H40 V50 H16 Z M22 14 H48 V44 H40", color=PRIMARY)
    canvas.line(28, 25, 41, 25, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(28, 33, 41, 33, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(28, 41, 36, 41, color=SECONDARY, width=DETAIL_STROKE)


def draw_settings(canvas: Canvas) -> None:
    for y, knob_x in ((20, 42), (32, 24), (44, 36)):
        canvas.line(12, y, 52, y, color=SECONDARY)
        canvas.circle(knob_x, y, 5, color=PRIMARY)


def draw_map(canvas: Canvas) -> None:
    canvas.rect(12, 14, 40, 36, rx=3, color=PRIMARY)
    canvas.line(25, 14, 25, 50, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(39, 14, 39, 50, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(12, 27, 52, 27, color=SECONDARY, width=DETAIL_STROKE)
    canvas.line(12, 40, 52, 40, color=SECONDARY, width=DETAIL_STROKE)
    canvas.polyline([(18, 44), (29, 34), (39, 37), (48, 22)], color=ACCENT)


def draw_what_do_i_need(canvas: Canvas) -> None:
    canvas.path("M17 23 C17 16 23 12 30 12 C37 12 42 16 42 23 C42 29 37 31 34 34 C31 37 31 39 31 42", color=PRIMARY)
    canvas.circle(31, 50, 2, color=PRIMARY, width=DETAIL_STROKE, fill=PRIMARY)
    canvas.path("M39 38 H53 V48 H39 Z M46 38 V32 H55", color=SECONDARY, width=DETAIL_STROKE)
    check(canvas, 42, 42, scale=0.55)


@dataclass(frozen=True)
class IconSpec:
    name: str
    display_name: str
    category: str
    description: str
    recommended_usage: str
    draw: Callable[[Canvas], None]


ICON_SPECS: tuple[IconSpec, ...] = (
    IconSpec("robot", "Robot", "Machine Components", "Cartesian or linear gantry robot with a vertical Z axis and EOAT block.", "Robot pages, automation views, and robot compatibility selectors.", draw_robot),
    IconSpec("mold", "Mold", "Machine Components", "Two mold halves with a center parting line and simple cavity marks.", "Mold-area navigation, tooling records, and mold references.", draw_mold),
    IconSpec("eoat", "EOAT", "EOAT Hardware", "End-of-arm tooling plate with suction cups and side mounting rails.", "EOAT records, tool summaries, and dashboard entry points.", draw_eoat),
    IconSpec("injection_unit", "Injection Unit", "Machine Components", "Injection barrel and nozzle pointing toward a mold face.", "Injection-side documentation and machine component maps.", draw_injection_unit),
    IconSpec("ejector", "Ejector", "Machine Components", "Mold halves with a part pushed out by a single clean arrow.", "Ejection, demolding, and part-removal process notes.", draw_ejector),
    IconSpec("peripherals", "Peripherals", "Machine Components", "Connected external IO or peripheral modules.", "Auxiliary equipment, external controllers, and cell devices.", draw_peripherals),
    IconSpec("air_circuit", "Air Circuit", "Pneumatics", "Routed pneumatic tubing with one airflow arrow.", "Pneumatic circuit overviews and air-routing documentation.", draw_air_circuit),
    IconSpec("vacuum", "Vacuum", "Pneumatics", "Suction cup pulling toward a surface with one accent arrow.", "Vacuum controls, suction validation, and vacuum process notes.", draw_vacuum),
    IconSpec("pressure_air", "Pressure Air", "Pneumatics", "Air nozzle with one outward airflow arrow.", "Pressure-air outputs, blowoff notes, and pneumatic references.", draw_pressure_air),
    IconSpec("interchangeable_air", "Interchangeable Air", "Pneumatics", "Air port with two clean swap arrows for pressure/vacuum dual use.", "Connections that can switch between pressure and vacuum service.", draw_interchangeable_air),
    IconSpec("sensor", "Sensor", "EOAT Hardware", "Rectangular sensor block with a beam and target dot.", "Sensor lists, part-detect devices, and IO validation.", draw_sensor),
    IconSpec("quick_disconnect", "Quick Disconnect", "Pneumatics", "Aligned plug and socket halves for a disconnectable coupling.", "Couplers, fittings, and changeover documentation.", draw_quick_disconnect),
    IconSpec("tubing", "Tubing", "Pneumatics", "Smooth routed tubing with two connector ends.", "Tube routing, hose lists, and pneumatic bill-of-materials views.", draw_tubing),
    IconSpec("gripper", "Gripper", "EOAT Hardware", "Opposing gripper fingers around a part block.", "Mechanical grippers and EOAT actuation details.", draw_gripper),
    IconSpec("vacuum_cup", "Vacuum Cup", "EOAT Hardware", "Single suction cup on a stem.", "Vacuum cup inventory, cup placement, and replacement notes.", draw_vacuum_cup),
    IconSpec("part_present", "Part Present", "EOAT Hardware", "Part block with a compact check indicator.", "Part-present checks, verification status, and sensor confirmation.", draw_part_present),
    IconSpec("compatibility", "Compatibility", "App Navigation", "Machine and EOAT mini-symbols linked by a compatibility check.", "Compatibility matrices, fit checks, and machine-to-EOAT matching.", draw_compatibility),
    IconSpec("machine", "Machine", "Machine Components", "Simplified injection molding machine with base, clamp area, and injection unit.", "Machine records, press pages, and cell-level navigation.", draw_machine),
    IconSpec("press", "Press", "Machine Components", "Two clamp plates with compression arrows.", "Clamp-unit details, press capacity, and molding-machine sections.", draw_press),
    IconSpec("cleanroom", "Cleanroom", "App Navigation", "Simple room/window outline with a small sterility sparkle.", "Cleanroom requirements and controlled-environment indicators.", draw_cleanroom),
    IconSpec("maintenance", "Maintenance", "App Navigation", "Clean wrench over a compact machine/EOAT block.", "Maintenance tasks, spare parts, and service workflows.", draw_maintenance),
    IconSpec("warning", "Warning", "App Navigation", "Standard caution triangle with machine-base cue.", "Risk notes, validation warnings, and attention states.", draw_warning),
    IconSpec("analytics", "Analytics", "Analytics", "Bar chart with one trend line arrow.", "Metrics dashboards, usage reports, and compatibility analytics.", draw_analytics),
    IconSpec("photos", "Photos", "Documentation", "Stacked photo frame with camera/lens cue.", "Image galleries, setup photos, and visual references.", draw_photos),
    IconSpec("standards", "Standards", "Documentation", "Checked standard document with simple rule lines.", "Standards, specifications, and compliance documentation.", draw_standards),
    IconSpec("checklist", "Checklist", "Documentation", "Clipboard with three checked rows.", "Setup checklists, validation steps, and inspection workflows.", draw_checklist),
    IconSpec("documentation", "Documentation", "Documentation", "Stacked documents with consistent line details.", "Manuals, reference files, and EOAT documentation sections.", draw_documentation),
    IconSpec("settings", "Settings", "App Navigation", "Three clean configuration sliders.", "Settings screens, filters, and configurable options.", draw_settings),
    IconSpec("map", "Map", "App Navigation", "Factory-style grid map with route line.", "Factory maps, cell layouts, and location-based navigation.", draw_map),
    IconSpec("what_do_i_need", "What Do I Need?", "App Navigation", "Question mark combined with machine and EOAT selection symbols.", "Guided selection, requirement discovery, and onboarding flows.", draw_what_do_i_need),
)


def canvas_for(spec: IconSpec) -> Canvas:
    canvas = Canvas()
    spec.draw(canvas)
    return canvas


def style_attrs(attrs: dict[str, object], vector_effect: bool = True) -> str:
    pairs = [
        ("fill", str(attrs.get("fill", "none"))),
        ("stroke", str(attrs["stroke"])),
        ("stroke-width", fmt(float(attrs["stroke_width"]))),
    ]
    if vector_effect:
        pairs.append(("vector-effect", "non-scaling-stroke"))
    return " ".join(f'{key}="{escape(value)}"' for key, value in pairs)


def points_attr(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{fmt(x)},{fmt(y)}" for x, y in points)


def element_to_svg(element: Element, vector_effect: bool = True) -> str:
    attrs = element.attrs
    style = style_attrs(attrs, vector_effect)
    if element.kind == "line":
        return (
            f'<line x1="{fmt(float(attrs["x1"]))}" y1="{fmt(float(attrs["y1"]))}" '
            f'x2="{fmt(float(attrs["x2"]))}" y2="{fmt(float(attrs["y2"]))}" {style} />'
        )
    if element.kind == "polyline":
        points = attrs["points"]
        return f'<polyline points="{points_attr(points)}" {style} />'
    if element.kind == "path":
        return f'<path d="{escape(str(attrs["d"]))}" {style} />'
    if element.kind == "rect":
        return (
            f'<rect x="{fmt(float(attrs["x"]))}" y="{fmt(float(attrs["y"]))}" '
            f'width="{fmt(float(attrs["width"]))}" height="{fmt(float(attrs["height"]))}" '
            f'rx="{fmt(float(attrs["rx"]))}" {style} />'
        )
    if element.kind == "circle":
        return (
            f'<circle cx="{fmt(float(attrs["cx"]))}" cy="{fmt(float(attrs["cy"]))}" '
            f'r="{fmt(float(attrs["r"]))}" {style} />'
        )
    if element.kind == "ellipse":
        return (
            f'<ellipse cx="{fmt(float(attrs["cx"]))}" cy="{fmt(float(attrs["cy"]))}" '
            f'rx="{fmt(float(attrs["rx"]))}" ry="{fmt(float(attrs["ry"]))}" {style} />'
        )
    raise ValueError(f"Unknown element kind: {element.kind}")


def render_svg(spec: IconSpec, tile: bool = False) -> str:
    canvas = canvas_for(spec)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-labelledby="{spec.name}-title {spec.name}-desc">',
        f'  <title id="{spec.name}-title">{escape(spec.display_name)}</title>',
        f'  <desc id="{spec.name}-desc">{escape(spec.description)}</desc>',
    ]
    if tile:
        lines.append(f'  <rect x="4" y="4" width="56" height="56" rx="12" fill="{TILE_BG_LIGHT}" stroke="{TILE_BORDER}" stroke-width="1.5" />')
        lines.append('  <g transform="translate(4.8 4.8) scale(0.85)" stroke-linecap="round" stroke-linejoin="round">')
    else:
        lines.append('  <g stroke-linecap="round" stroke-linejoin="round">')
    lines.extend(f"    {element_to_svg(element)}" for element in canvas.elements)
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def svg_path(spec: IconSpec, tile: bool = False) -> Path:
    return (SVG_TILE_DIR if tile else SVG_STANDALONE_DIR) / f"{spec.name}.svg"


def png_path(spec: IconSpec, size: int, tile: bool = False) -> Path:
    suffix = "_tile" if tile else ""
    return PNG_ROOT / str(size) / f"{spec.name}{suffix}.png"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def make_dirs() -> None:
    SVG_STANDALONE_DIR.mkdir(parents=True, exist_ok=True)
    SVG_TILE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        (PNG_ROOT / str(size)).mkdir(parents=True, exist_ok=True)


def clean_owned_outputs() -> None:
    paths: list[Path] = [
        ICON_ROOT / "README.md",
        ICON_ROOT / "icon_manifest.json",
        PREVIEW_DIR / "icon_preview.html",
        PREVIEW_DIR / "icon_contact_sheet.png",
    ]
    for spec in ICON_SPECS:
        paths.extend([svg_path(spec), svg_path(spec, tile=True)])
        for size in ICON_SIZES:
            paths.extend([png_path(spec, size), png_path(spec, size, tile=True)])
    for path in paths:
        if path.exists() and path.is_file():
            path.unlink()


def write_svgs() -> int:
    count = 0
    for spec in ICON_SPECS:
        svg_path(spec).write_text(render_svg(spec, tile=False), encoding="utf-8")
        svg_path(spec, tile=True).write_text(render_svg(spec, tile=True), encoding="utf-8")
        count += 2
    return count


def write_pngs() -> tuple[int, str]:
    if importlib.util.find_spec("cairosvg") is None:
        return (
            0,
            "PNG export skipped because CairoSVG is not installed. Install with: python -m pip install cairosvg",
        )
    try:
        import cairosvg
    except Exception as exc:  # CairoSVG may exist while the native Cairo DLL is missing.
        return (
            0,
            f"PNG export skipped because CairoSVG could not load its renderer: {exc}",
        )

    count = 0
    try:
        for spec in ICON_SPECS:
            for size in ICON_SIZES:
                for tile in (False, True):
                    cairosvg.svg2png(
                        bytestring=render_svg(spec, tile=tile).encode("utf-8"),
                        write_to=str(png_path(spec, size, tile=tile)),
                        output_width=size,
                        output_height=size,
                    )
                    count += 1
    except Exception as exc:
        return (
            0,
            f"PNG export skipped because CairoSVG could not render in this environment: {exc}",
        )
    return count, "PNG export completed with CairoSVG."


def transform_point(x: float, y: float, scale: float, tile: bool) -> tuple[float, float]:
    if tile:
        x = 4.8 + x * 0.85
        y = 4.8 + y * 0.85
    return x * scale, y * scale


def draw_round_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    if len(points) < 2:
        return
    try:
        draw.line(points, fill=color, width=width, joint="curve")
    except TypeError:
        draw.line(points, fill=color, width=width)
    radius = width / 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 18,
) -> list[tuple[float, float]]:
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        inv = 1 - t
        x = inv**3 * p0[0] + 3 * inv**2 * t * p1[0] + 3 * inv * t**2 * p2[0] + t**3 * p3[0]
        y = inv**3 * p0[1] + 3 * inv**2 * t * p1[1] + 3 * inv * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def path_to_subpaths(d: str) -> list[list[tuple[float, float]]]:
    tokens = re.findall(r"[A-Za-z]|-?\d+(?:\.\d+)?", d)
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    active: list[tuple[float, float]] = []
    subpaths: list[list[tuple[float, float]]] = []

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def flush() -> None:
        nonlocal active
        if len(active) > 1:
            subpaths.append(active)
        active = []

    while index < len(tokens):
        if re.match(r"[A-Za-z]", tokens[index]):
            command = tokens[index]
            index += 1
        if command == "M":
            flush()
            current = (number(), number())
            start = current
            active = [current]
        elif command == "H":
            current = (number(), current[1])
            active.append(current)
        elif command == "V":
            current = (current[0], number())
            active.append(current)
        elif command == "L":
            current = (number(), number())
            active.append(current)
        elif command == "C":
            p1 = (number(), number())
            p2 = (number(), number())
            p3 = (number(), number())
            active.extend(cubic(current, p1, p2, p3))
            current = p3
        elif command == "Z":
            active.append(start)
            flush()
            command = ""
        else:
            raise ValueError(f"Unsupported SVG path command in generated icon: {command}")
    flush()
    return subpaths


def render_element_to_draw(
    draw: ImageDraw.ImageDraw,
    element: Element,
    scale: float,
    tile: bool,
) -> None:
    attrs = element.attrs
    color = hex_to_rgba(str(attrs["stroke"]))
    width = max(1, round(float(attrs["stroke_width"]) * scale))

    if element.kind == "line":
        p1 = transform_point(float(attrs["x1"]), float(attrs["y1"]), scale, tile)
        p2 = transform_point(float(attrs["x2"]), float(attrs["y2"]), scale, tile)
        draw_round_polyline(draw, [p1, p2], color, width)
    elif element.kind == "polyline":
        points = [transform_point(x, y, scale, tile) for x, y in attrs["points"]]
        draw_round_polyline(draw, points, color, width)
    elif element.kind == "path":
        for subpath in path_to_subpaths(str(attrs["d"])):
            draw_round_polyline(draw, [transform_point(x, y, scale, tile) for x, y in subpath], color, width)
    elif element.kind == "rect":
        x = float(attrs["x"])
        y = float(attrs["y"])
        w = float(attrs["width"])
        h = float(attrs["height"])
        rx = float(attrs["rx"]) * scale
        x1, y1 = transform_point(x, y, scale, tile)
        x2, y2 = transform_point(x + w, y + h, scale, tile)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=rx, outline=color, width=width)
    elif element.kind == "circle":
        cx = float(attrs["cx"])
        cy = float(attrs["cy"])
        r = float(attrs["r"])
        x1, y1 = transform_point(cx - r, cy - r, scale, tile)
        x2, y2 = transform_point(cx + r, cy + r, scale, tile)
        fill = str(attrs.get("fill", "none"))
        draw.ellipse((x1, y1, x2, y2), outline=color, width=width, fill=hex_to_rgba(fill) if fill != "none" else None)
    elif element.kind == "ellipse":
        cx = float(attrs["cx"])
        cy = float(attrs["cy"])
        rx = float(attrs["rx"])
        ry = float(attrs["ry"])
        x1, y1 = transform_point(cx - rx, cy - ry, scale, tile)
        x2, y2 = transform_point(cx + rx, cy + ry, scale, tile)
        draw.ellipse((x1, y1, x2, y2), outline=color, width=width)
    else:
        raise ValueError(f"Unsupported element kind for contact sheet: {element.kind}")


def render_icon_preview_image(spec: IconSpec, size: int = 64, tile: bool = False) -> Image.Image:
    supersample = 4
    scale = size * supersample / VIEWBOX
    image = Image.new("RGBA", (size * supersample, size * supersample), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    if tile:
        x1, y1 = transform_point(4, 4, scale, False)
        x2, y2 = transform_point(60, 60, scale, False)
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=12 * scale,
            fill=hex_to_rgba(TILE_BG_LIGHT),
            outline=hex_to_rgba(TILE_BORDER),
            width=max(1, round(1.5 * scale)),
        )

    for element in canvas_for(spec).elements:
        render_element_to_draw(draw, element, scale, tile)

    return image.resize((size, size), Image.Resampling.LANCZOS)


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
    cell_w = 214
    cell_h = 150
    header_h = 64
    rows = math.ceil(len(ICON_SPECS) / columns)
    width = columns * cell_w + 32
    height = header_h + rows * cell_h + 28
    image = Image.new("RGBA", (width, height), hex_to_rgba(LIGHT))
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = load_font(23, bold=True)
    label_font = load_font(15, bold=True)
    code_font = load_font(12)

    draw.text((24, 22), "EOAT Atlas / EOAT Command Center Icon Pack", font=title_font, fill=hex_to_rgba(DARK))
    draw.text((24, 47), f"{len(ICON_SPECS)} original strict-system industrial HMI line icons", font=code_font, fill=hex_to_rgba(SECONDARY))

    for index, spec in enumerate(ICON_SPECS):
        row = index // columns
        col = index % columns
        x = 16 + col * cell_w
        y = header_h + row * cell_h
        draw.rounded_rectangle((x, y, x + cell_w - 12, y + cell_h - 12), radius=8, fill=hex_to_rgba("#FFFFFF"), outline=hex_to_rgba(TILE_BORDER), width=1)

        if png_count:
            standalone = Image.open(png_path(spec, 64, tile=False)).convert("RGBA")
            tile = Image.open(png_path(spec, 64, tile=True)).convert("RGBA")
        else:
            standalone = render_icon_preview_image(spec, 64, tile=False)
            tile = render_icon_preview_image(spec, 64, tile=True)
        image.alpha_composite(standalone, (x + 44, y + 26))
        image.alpha_composite(tile, (x + 120, y + 26))

        center_x = x + (cell_w - 12) // 2
        draw.text((center_x, y + 108), spec.display_name, font=label_font, fill=hex_to_rgba(DARK), anchor="mm")
        draw.text((center_x, y + 130), spec.name, font=code_font, fill=hex_to_rgba(SECONDARY), anchor="mm")

    path = PREVIEW_DIR / "icon_contact_sheet.png"
    image.save(path)
    if png_count:
        return path, "Contact sheet generated from exported PNGs."
    return path, "Contact sheet generated with internal SVG primitive preview renderer; per-size PNG export remains skipped."


def write_manifest() -> Path:
    entries = []
    for spec in ICON_SPECS:
        entries.append(
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "category": spec.category,
                "description": spec.description,
                "recommended_usage": spec.recommended_usage,
                "svg_standalone_path": rel(svg_path(spec)),
                "svg_tile_path": rel(svg_path(spec, tile=True)),
                "png_paths": {
                    str(size): {
                        "standalone": rel(png_path(spec, size, tile=False)),
                        "tile": rel(png_path(spec, size, tile=True)),
                    }
                    for size in ICON_SIZES
                },
            }
        )

    manifest = {
        "name": "eoat_atlas_command_center_icon_pack",
        "version": "2.0.0",
        "style": "Original generic strict-system industrial HMI line icons.",
        "viewBox": f"0 0 {VIEWBOX} {VIEWBOX}",
        "safe_area": "x=8..56, y=8..56",
        "stroke_width": STROKE,
        "detail_stroke_width": DETAIL_STROKE,
        "colors": {
            "PRIMARY": PRIMARY,
            "SECONDARY": SECONDARY,
            "ACCENT": ACCENT,
            "DARK": DARK,
            "LIGHT": LIGHT,
            "TILE_BG_LIGHT": TILE_BG_LIGHT,
            "TILE_BORDER": TILE_BORDER,
        },
        "icons": entries,
    }
    path = ICON_ROOT / "icon_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def write_html_preview() -> Path:
    cards = []
    for spec in ICON_SPECS:
        cards.append(
            f"""
      <article class="icon-card">
        <div class="icon-pair">
          <div class="transparent-swatch">
            <img src="../svg/standalone/{spec.name}.svg" alt="{escape(spec.display_name)} standalone">
          </div>
          <img class="tile-icon" src="../svg/tile/{spec.name}.svg" alt="{escape(spec.display_name)} tile">
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
  <title>EOAT Atlas Icon Pack Preview</title>
  <style>
    :root {{
      --primary: {PRIMARY};
      --secondary: {SECONDARY};
      --accent: {ACCENT};
      --dark: {DARK};
      --light: {LIGHT};
      --border: {TILE_BORDER};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--light);
      color: var(--dark);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      padding: 28px 32px 18px;
      background: #fff;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .tokens {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
      color: var(--secondary);
      font-size: 12px;
    }}
    .token {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .swatch {{
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 1px solid rgba(30, 42, 50, 0.16);
    }}
    main {{
      padding: 24px 32px 36px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
      gap: 14px;
    }}
    .icon-card {{
      min-height: 168px;
      padding: 14px;
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .icon-pair {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      align-items: center;
      gap: 10px;
      min-height: 72px;
    }}
    .transparent-swatch {{
      display: grid;
      place-items: center;
      height: 64px;
      border-radius: 8px;
      background:
        linear-gradient(45deg, #eef2f5 25%, transparent 25%),
        linear-gradient(-45deg, #eef2f5 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #eef2f5 75%),
        linear-gradient(-45deg, transparent 75%, #eef2f5 75%);
      background-size: 14px 14px;
      background-position: 0 0, 0 7px, 7px -7px, -7px 0;
    }}
    img {{
      width: 56px;
      height: 56px;
    }}
    .tile-icon {{
      width: 64px;
      height: 64px;
      justify-self: center;
    }}
    h2 {{
      margin: 12px 0 3px;
      font-size: 15px;
      letter-spacing: 0;
    }}
    p {{
      margin: 0 0 8px;
      color: var(--secondary);
      font-size: 12px;
    }}
    code {{
      color: var(--primary);
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <header>
    <h1>EOAT Atlas / EOAT Command Center Icon Pack</h1>
    <div class="tokens" aria-label="Color tokens">
      <span class="token"><span class="swatch" style="background:{PRIMARY}"></span>PRIMARY</span>
      <span class="token"><span class="swatch" style="background:{SECONDARY}"></span>SECONDARY</span>
      <span class="token"><span class="swatch" style="background:{ACCENT}"></span>ACCENT</span>
      <span class="token"><span class="swatch" style="background:{TILE_BORDER}"></span>BORDER</span>
    </div>
  </header>
  <main>
    <section class="grid" aria-label="Icon preview">
{''.join(cards)}
    </section>
  </main>
</body>
</html>
"""
    path = PREVIEW_DIR / "icon_preview.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_readme() -> Path:
    readme = f"""# EOAT Atlas / EOAT Command Center Icon Pack

This is an original, generic industrial HMI-inspired icon family for EOAT Atlas / EOAT Command Center. It is intended for an injection molding, robotics, EOAT documentation, and compatibility workflow.

The icons communicate broad manufacturing concepts such as robot, mold, injection unit, demolding, pneumatics, peripherals, documentation, settings, and analytics. They do not copy, trace, crop, or reproduce ENGEL, Wittmann, Nolato, or any other proprietary machine-interface assets.

## Style Rules

- Every standalone SVG uses `viewBox="0 0 64 64"`.
- Artwork is designed inside the visual safe area from `x=8..56` and `y=8..56`.
- Main icon strokes are exactly `{STROKE}px`.
- Small internal details may use `{DETAIL_STROKE}px`.
- All strokes use round caps and round joins.
- Standalone icons have transparent backgrounds.
- Tile icons use a rounded white square at `x=4 y=4 width=56 height=56 radius=12` with a `{TILE_BORDER}` border.
- Main object color: `{PRIMARY}`.
- Supporting structure color: `{SECONDARY}`.
- Accent color: `{ACCENT}` for checks, arrows, airflow, and status only.

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
4. Use `{PRIMARY}` for the main object, `{SECONDARY}` for structure, and `{ACCENT}` only for status or motion.
5. Add a matching `IconSpec` entry with metadata.
6. Run `python scripts/build_icon_pack.py`.
7. Review `preview/icon_preview.html` and, when PNG export is enabled, `preview/icon_contact_sheet.png`.

## Original Asset Reminder

Keep this pack original and generic. Do not replace these icons with screenshot crops, traced vendor artwork, or proprietary HMI icon assets. New icons should share the same strict design system and communicate industrial concepts without copying protected interface art.
"""
    path = ICON_ROOT / "README.md"
    path.write_text(readme, encoding="utf-8")
    return path


def validate_svgs() -> list[str]:
    missing: list[str] = []
    for spec in ICON_SPECS:
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
    png_count, png_message = write_pngs()
    contact_path, contact_message = write_contact_sheet(png_count)
    manifest_path = write_manifest()
    html_path = write_html_preview()
    readme_path = write_readme()
    missing = validate_svgs()

    print("EOAT icon pack build summary")
    print(f"- Icons: {len(ICON_SPECS)}")
    print(f"- Standalone SVGs: {len(ICON_SPECS)}")
    print(f"- Tile SVGs: {len(ICON_SPECS)}")
    print(f"- SVG files written: {svg_count}")
    print(f"- PNG files written: {png_count}")
    print(f"- PNG status: {png_message}")
    print(f"- Contact sheet status: {contact_message}")
    print(f"- Manifest: {rel(manifest_path)}")
    print(f"- README: {rel(readme_path)}")
    print(f"- HTML preview: {rel(html_path)}")
    if contact_path:
        print(f"- Contact sheet: {rel(contact_path)}")
    if missing:
        print("- Validation failed:")
        for item in missing:
            print(f"  - {item}")
        return 1
    print("- Validation: every required standalone and tile SVG exists with viewBox 0 0 64 64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
