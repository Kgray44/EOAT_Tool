# Project Mirrorline Exhaustive Runtime Review

This review starts from accepted Mirrorline commit
`328e4c487dd8970a56bc802d7becde63768968db`. The PySide6 Minimalist desktop
application remains the visual and interaction authority. Browser facts come
only from the read-only API; the browser never recreates compatibility or
location logic.

The final deterministic visual evidence is iteration 20 in the external,
task-owned evidence directory (intentionally not recorded in source): it
contains all 27 governed Qt/browser pairs, comparison artifacts, metrics, and
reviewed dispositions.

## Runtime inventory

| Desktop surface | Browser route or equivalent | Result |
| --- | --- | --- |
| Shell, title bar, logo, ambient background, menu, search, freshness status | All routes through `AppShell` | Matched with semantic modal/focus handling. |
| Home, recents, query handoff, stale and unavailable indicators | `/` | Matched; browser recents are local only. |
| Library, category views, query, retained context and profile entry | `/library` | Matched through read-only paginated API routes. |
| EOAT, Machine and Tool profiles | `/eoats/:identifier`, `/machines/:number`, `/tools/:identifier` | Matched through browser-safe profile/media metadata routes. |
| Fit Check, alternatives, result, error and local recents | `/fit-check` | Matched to the non-persisting web evaluation endpoint; browser recents are local only. |
| Display and accessibility settings | `/settings` | Browser-local theme, accent, motion and contrast settings; privileged desktop settings are inert and explicit. |
| Setup Packet builder | `/setup-packet` | Closest safe equivalent: links to a read-only Fit Check and explicitly excludes local PDF creation. |
| Standards & WI | `/standards` | Desktop is currently a coming-later surface; browser preserves that truthful state. |
| Data Health | `/data-health` | Desktop is currently a coming-later surface; browser preserves that truthful state and keeps API freshness where used. |

## Action and motion matrix

| Area | Exercised action | Browser result |
| --- | --- | --- |
| Shell | menu, outside close, Escape, focus restoration | Modal navigation closes and restores trigger focus. |
| Search | Ctrl/Meta+K, type-ahead, Escape, keyboard result navigation | Global search opens from the same triggers, debounces requests and closes safely. |
| Profiles | direct URL, refresh, Back to Library, browser back/forward | Route identity and Library context are retained. |
| Fit Check | full input, compatible/warning result, clear, recent restore | Evaluation uses only `/web-fit-checks/evaluate`; no evaluation is stored remotely. |
| Settings | dark, light, system, accent, animation, reduced motion, contrast | Preferences persist in browser storage and update shell tokens. |
| Responsive | 1760x1080, 1440x900, 1280x820, 1024x768, 768x1024, 430x932, 390x844, 360x800 | Functional test verifies no horizontal overflow and preserves profile/Fit Check interaction. |

## Governed visual-state matrix

The iteration-20 comparison is complete and reviewed for every governed
state: `home-dark`, `home-light`, `home-recents`, `home-live-search`,
`global-search`, `navigation-home`, `navigation-fit-check`,
`navigation-library`, `navigation-settings`, `library-default`,
`library-query`, `library-filters`, `eoat-profile`, `machine-profile`,
`tool-profile`, `fit-empty`, `fit-populated`, `fit-compatible`,
`fit-warning`, `settings-dark`, `settings-light`, `loading`, `empty`,
`api-unavailable`, `not-found`, `stale-data`, and `reduced-motion`.

Each state has a Qt reference, browser capture, side-by-side, 50 percent
overlay, difference image, metric record, and reviewed disposition. The
reviewed differences are limited to browser/Qt rasterization and compositing,
semantic browser interaction, responsive translation, and the narrow,
explicit browser-security boundaries described below.

## Narrow platform differences

- Desktop packet export, local file opening, administrator settings, and
  diagnostics controls require privileged local operating-system or authenticated
  behavior. Browser routes preserve safe information or a direct read-only
  equivalent and never present a fake working control.
- Browser focus rings, semantic dialog behavior, and reduced-motion behavior
  intentionally improve keyboard and assistive-technology use while preserving
  the desktop interaction meaning.

## Evidence

Visual capture output is intentionally external to source control. Each
iteration contains `qt`, `browser`, and `comparison` directories, with
side-by-side images, overlays, differences, metrics, and reviewed
dispositions. The capture command remains:

```powershell
python scripts\capture_mirrorline_qt.py --output "$evidence\qt"
$env:EOAT_MIRRORLINE_VISUAL_EVIDENCE = $evidence
Set-Location web
pnpm exec playwright test tests/e2e/mirrorline-visual-capture.spec.ts
Set-Location ..
python scripts\compare_mirrorline_visuals.py --evidence $evidence --require-complete --require-reviewed
```

The review never authorizes production access, API writes, direct MySQL access,
or the destructive reset of `eoat_atlas_dev`.
