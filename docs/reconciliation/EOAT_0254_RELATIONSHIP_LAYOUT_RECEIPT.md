# EOAT Atlas 0.25.4 relationship layout receipt

## Shared implementation

`RelationshipFlow` is shared by EOAT, Machine, and Tool profiles. Its cards
use responsive grid bounds of 180px minimum and 240px maximum, centered node
containers, wrapping identifiers, and mobile connector suppression. The
layout does not branch on relationship count.

## Focused browser evidence

On 2026-07-30, the isolated candidate Vite server ran
`web/tests/e2e/relationship-layout.spec.ts` in Chromium: **1 passed**.

The test exercised a machine-profile fixture with zero, one, two, three, and
ten relationships; it verified the zero state, a one-card 180-240px governed
width and centered position, long identifier/text rendering, semantic labels,
desktop overflow, a 390px mobile viewport, and increased root font size.
Every checked viewport had no document horizontal overflow.

This is focused layout evidence, not a replacement for the recorded bounded
browser-matrix exception.
