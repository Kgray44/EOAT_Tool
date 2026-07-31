# EOAT Atlas 0.25.4 desktop/browser parity receipt

## Result

`DETERMINISTIC_VISUAL_COMPARISON_COMPLETE`; `REVIEW_DISPOSITIONS_PENDING`.

The canonical desktop implementation is under `app/atlas/minimalist/`. The
browser implementation was compared to that source and to focused
component/Chromium contracts. This receipt does not equate a source comparison
with a live, same-record visual comparison.

| Surface | Desktop source | Browser result | Evidence | Status |
| --- | --- | --- | --- | --- |
| Home/search | `home.py`, `entity_search.py` | Local Home search retained; global search remains distinct | Content-density audit | Source aligned |
| Library | `library.py` | Authoritative labelled filters and bounded catalog options | 3 catalog-option and 6 Discovery tests | Source-aligned intent |
| Entity relationships | `data.py`, `simple_pages.py` | Business labels plus expandable source evidence | 11 component and 7 Machine Chromium tests | Source-aligned intent |
| Machine overview | Desktop grouped data model | Browser identity/operation/press/robot/setup groups | 7 Machine Chromium tests | Source-aligned intent |
| Fit Check | `fit_check.py` | Safety/staleness information retained | Discovery contract covers six orders | Source aligned |
| Settings | `settings_page.py` | Authentication-disabled controls stay locked | Content-density audit | Source aligned |

## Deterministic capture evidence

At candidate `b67d9d`, the real offscreen PySide desktop shell and a
candidate-local Chromium browser fixture each captured all 27 governed states
at 1760×1080. The comparator generated side-by-side, overlay, difference, and
per-state metric artifacts for all 27 pairs with `incomplete: 0`. The Machine
fixture now carries required plant code `P4`, and the browser capture asserts
that no `undefined:` identifier is rendered. Evidence is retained at
`.local/visual-evidence-b67d9d053d/` and is not committed.

## Remaining review gate

The generated evidence has no reviewer-owned `reviewed-dispositions.json`;
the comparator therefore reports 27 unreviewed states. It must not be treated
as parity approval. Required follow-up is a direct human review of every
side-by-side state, recording the intentional browser safety/responsive
differences or actionable defects in that manifest. The owner’s bounded
browser-matrix exception remains in force; this is a visual-review gate, not
a new complete browser matrix.
