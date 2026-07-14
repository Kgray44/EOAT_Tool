# EOAT Atlas HMI Icon Style Guide

This guide defines the original EOAT Atlas / EOAT Command Center icon system. The icons should feel like industrial injection molding machine HMI pictograms while remaining original and app-safe.

## Intent

Atlas icons are for manufacturing users documenting EOATs, robots, molds, machine compatibility, air circuits, maintenance, standards, photos, and analytics. Recognition matters more than artistic cleverness.

The style should feel:

- Industrial machine HMI pictogram
- Chunky and bold
- Touchscreen tile-first
- Injection molding and robotics oriented
- Original, generic, and not copied from any vendor

The style should not feel:

- Lucide, Tabler, Material, or generic web dashboard
- Thin outline-only
- Cute clipart
- Abstract random geometry
- Humanoid robot or character-like

## Canvas

- SVG viewBox: `0 0 64 64`
- Visual safe area: `x=5..59`, `y=5..59`
- Icons should fill most of the available canvas.
- Each pictogram should feel visually large and centered.
- Details must remain readable at `32x32`.

## Color Tokens

- `ATLAS_CYAN = #00A6C8`
- `ATLAS_LIME = #A6CE39`
- `MACHINE_GRAY = #9AA6AD`
- `DARK = #1E2A32`
- `TILE_BG = #FFFFFF`
- `TILE_BORDER = #D6DEE4`

## Color Logic

- Cyan is the primary component or category body.
- Gray is machine structure, rails, plates, bases, or neutral hardware.
- Lime is action, motion, airflow, active connection, confirmation, or selected state.
- Dark is optional and should be used sparingly.
- Use no random colors outside the token set.
- Do not use lime just to decorate.

## Shape Language

Use repeated chunky HMI primitives:

- Filled rounded rectangles
- Pill-shaped barrels and rails
- Heavy mold blocks and clamp plates
- Bold component bases
- Filled suction cups and nozzles
- Large tile-scaled silhouettes
- Rounded filled arrows
- Minimal internal detail

Avoid:

- Thin line drawings
- Fragile strokes
- Tiny labels or hatching
- Multiple unrelated floating shapes
- Excessive arrows
- Perspective or pseudo-3D

## Atlas Identity

Atlas identity should be subtle and functional:

- Lime path or connection line for compatibility
- Small locator/path motif for map-like navigation concepts
- Clean cyan machine body with lime active highlight
- Grid/map references only where relevant

Do not make every icon a compass, map, or globe.

## Tile Icons

Tile icons are the primary review surface.

- Tile viewBox remains `0 0 64 64`.
- Tile background: white rounded square.
- Tile border: subtle `#D6DEE4`.
- Icon should be large and centered.
- Tile art may be slightly scaled and adjusted, but should not become a different icon.

## Originality Rule

Reference crops are for private study only. Final Atlas SVGs and PNGs must be original. Do not copy, trace, crop, vectorize, or reproduce proprietary HMI icons.
