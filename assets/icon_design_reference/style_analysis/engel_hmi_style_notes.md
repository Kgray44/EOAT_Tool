# Industrial Injection Molding HMI Style Notes

These notes describe broad style observations for private reference and original EOAT Atlas icon design. They are not instructions to copy any proprietary ENGEL, Wittmann, Nolato, or other vendor artwork.

No source screenshots were provided in this turn, so this file captures the requested target language and the intended analysis categories. When private screenshots are added to `source_images/` and cropped, this document can be extended with observations from those references.

## Dominant Colors

Industrial molding-machine HMI pictograms commonly use a compact palette with strong functional roles:

- Cyan/teal for the primary machine component or active category.
- Gray for neutral machine structure such as rails, plates, bases, or hardware.
- Lime green for motion, airflow, active status, selected regions, checks, or part movement.
- Dark outlines only when needed for separation or readability.

## Stroke And Fill Balance

The target style is not thin line art. Most recognition should come from filled or semi-filled shapes: thick blocks, plates, rails, barrels, cups, mold halves, bases, and machine silhouettes. Strokes should support the pictogram, not define every detail.

## Shape Thickness

Shapes should feel touch-friendly and readable at dashboard-tile scale. Major forms should occupy most of the `64x64` canvas safe area, with thick geometry and minimal fragile detail.

## Corner Radius Style

Corners should be rounded but not cute. Rounded rectangles, pill-shaped barrels, chunky rails, and soft block corners help the icons feel like HMI touchscreen pictograms rather than mechanical CAD drawings.

## Arrow Style

Arrows should be bold filled indicators, not delicate line arrows. Use lime arrows sparingly for clear action: eject, airflow, vacuum pull, pressure output, active path, or compatibility connection.

## Gray Vs Cyan Vs Lime

Cyan carries the main component identity. Gray supports it as machine structure. Lime is reserved for action or active state. A strong icon may only need cyan and gray; lime appears only where it clarifies operation.

## Icon Scale Inside Tiles

Tile icons should feel like the primary design surface. The pictogram should be large, centered, and visually heavy inside a white rounded square tile with a subtle border.

## Machine Component Simplification

Components should be reduced to operator-recognizable pictograms:

- Mold: two heavy blocks and a parting line.
- Robot: gantry rail, carriage, vertical axis, EOAT head.
- EOAT: tool plate plus suction cups or gripper pads.
- Injection unit: barrel/nozzle aimed at a mold plate.
- Machine: base, clamp/mold area, and injection unit.
- Pneumatics: tubing/nozzle/cup with one clear lime action cue.

## Motion And Action

Motion should be represented with a single clear lime cue where possible. Avoid several arrows or scattered signal marks. The action marker should attach visually to the component it describes.

## Detail Level

Use few details. Details should be large enough to survive at `32x32`. Avoid internal hatching, tiny labels, thin beams, and decorative dots.

## Why This Feels Like HMI Instead Of Web Icons

Machine HMI pictograms are denser and more component-like than generic web icons. They use filled geometry, large silhouettes, tile-first scale, limited functional color, and simplified physical machine metaphors. Web icons tend to be thin, abstract, and metaphor-driven; Atlas icons should feel like they belong on a molding machine controller.
