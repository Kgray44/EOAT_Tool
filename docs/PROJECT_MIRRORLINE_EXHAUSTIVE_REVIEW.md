# Project Mirrorline Exhaustive Runtime Review

This review starts from accepted Mirrorline commit
`328e4c487dd8970a56bc802d7becde63768968db`. The PySide6 Minimalist desktop
application remains the visual and interaction authority. Browser facts come
only from the read-only API; the browser never recreates compatibility or
location logic.

Iteration 21 was a historical deterministic visual review in an external,
task-owned evidence directory (intentionally not recorded in source). This
branch changes browser Fit Check and Setup Packet composition, so its current
capture must be reviewed as a new iteration rather than inheriting that prior
approval. The refreshed capture contains all 27 governed Qt/browser pairs,
comparison artifacts, and a current reviewer disposition for every state.
Twenty-four dispositions are non-blocking; the three profile states remain
explicitly blocked on the pending authenticated application-write contract.

## Runtime inventory

| Desktop surface | Browser route or equivalent | Result |
| --- | --- | --- |
| Shell, title bar, logo, ambient background, menu, search, freshness status | All routes through `AppShell` | Covered with semantic modal/focus handling; current visual review remains open. |
| Home, recents, query handoff, stale and unavailable indicators | `/` | Covered; browser recents are local only. |
| Library, category views, query, retained context and profile entry | `/library` | Covered through read-only paginated API routes. |
| EOAT, Machine and Tool profiles | `/eoats/:identifier`, `/machines/:number`, `/tools/:identifier` | Covered through browser-safe profile/media metadata routes. |
| Fit Check, alternatives, result, error and local recents | `/fit-check` | Read-only evaluation and universal setup-item selection are covered; visual review remains open. |
| Display and accessibility settings | `/settings` | Browser-local theme, accent, motion and contrast settings; privileged controls remain fail-closed. |
| Setup Packet builder | `/setup-packet` | API-backed read-only packet with labelled data and browser print/save-PDF; it creates no Fit Check, assignment, audit, or history event. |
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

The current refreshed comparison is complete for every governed state:
`home-dark`, `home-light`, `home-recents`, `home-live-search`,
`global-search`, `navigation-home`, `navigation-fit-check`,
`navigation-library`, `navigation-settings`, `library-default`,
`library-query`, `library-filters`, `eoat-profile`, `machine-profile`,
`tool-profile`, `fit-empty`, `fit-populated`, `fit-compatible`,
`fit-warning`, `settings-dark`, `settings-light`, `loading`, `empty`,
`api-unavailable`, `not-found`, `stale-data`, and `reduced-motion`.

Each state has a Qt reference, browser capture, side-by-side, 50 percent
overlay, difference image, metric record, and reviewed disposition. The
`eoat-profile`, `machine-profile`, and `tool-profile` dispositions remain
unresolved blockers: their desktop edit/export workflows require authenticated
application permissions and browser editors that are not yet available.
Therefore `--require-reviewed` correctly remains nonzero until those three
states are resolved. Historical reviewed differences were not reused for the
changed browser surfaces.

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
side-by-side images, overlays, differences, metrics, and—only after a real
review—dispositions. The capture command remains:

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
