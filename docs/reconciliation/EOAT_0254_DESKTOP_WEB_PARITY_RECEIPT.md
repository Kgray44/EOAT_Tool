# EOAT Atlas 0.25.4 desktop/browser parity receipt

## Result

`SOURCE_COMPARISON_COMPLETE`; `LIVE_VISUAL_PARITY_NOT_EXECUTED`.

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

## Remaining visual gate

No installed desktop application session and no hash-matched browser candidate
session are available here for a same-record screenshot/interaction
comparison. Required follow-up is a controlled desktop/browser session at the
agreed desktop and mobile viewports, including long relationship evidence and
increased font scale, followed by a difference register. The owner’s bounded
browser-matrix exception remains in force; this record does not claim a new
complete browser matrix.
