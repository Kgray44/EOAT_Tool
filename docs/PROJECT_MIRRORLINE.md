# Project Mirrorline

Project Mirrorline rebuilds the EOAT Atlas browser UI from the current
PySide6 Minimalist interface. The desktop remains the design and behavior
authority; the browser continues to use the existing same-origin, read-only
API and must never reproduce compatibility decisions or hold credentials.

## Design authority and drift control

`app/atlas/minimalist/theme.py` is the token authority. Run the following
from the repository root whenever that module changes:

```powershell
python scripts/export_minimalist_theme_tokens.py
python scripts/export_minimalist_theme_tokens.py --check
```

The exporter writes `web/src/styles/generated-theme-tokens.css` and JSON.
`pnpm run theme:check` is included in the deterministic web-release checks,
so a browser token cannot silently drift from the desktop authority.

Desktop geometry used by the initial shell comes directly from
`minimalist/topbar.py`, `minimalist/shell.py`, `minimalist/home.py`, and
`page_transition.py`: a 106px top bar; menu at 42/27/52px; centered 244px
logo; 58px search control; 125ms search debounce; and desktop-style
OutCubic/320ms transitions translated to CSS.

## Parity matrix

| Desktop surface/state | Browser route/component | Status | Evidence / intentional difference |
| --- | --- | --- | --- |
| Home, atmospheric shell, title accent, Get Started card | `/`, `FoundationPage` | Implemented, focused validation | 1760px desktop geometry translated responsively; API state remains truthful. |
| Hamburger menu, active page, outside/Escape close | `AppShell` menu overlay | Implemented, unit + Playwright coverage | Browser uses semantic navigation and focusable links. |
| Global command/entity search | `GlobalSearchOverlay` | Implemented, focused unit coverage | Browser limits results to API entities; desktop-only commands/reports remain unavailable. |
| Home contextual search | Home search dispatches global overlay | Implemented | Same 125ms debounce and exact entity route activation. |
| Library and retained filters | `/library` | Existing behavior restyled, regression covered | URL query/filter context survives direct navigation; scroll restoration remains a follow-up visual gate. |
| EOAT profile | `/eoats/:identifier` | Existing behavior restyled, regression covered | Browser-safe document/photo routes only; desktop filesystem metadata remains excluded. |
| Machine profile | `/machines/:number` | Existing behavior restyled, regression covered | Browser-safe media only. |
| Tool profile | `/tools/:identifier` | Existing behavior restyled, regression covered | Browser-safe media only. |
| Fit Check | `/fit-check` | Existing behavior restyled, regression covered | Uses the authoritative non-persisting API endpoint only. |
| Settings: display/accessibility | `/settings` | Implemented | Theme, accent, animation, reduced motion, and contrast are browser-local. |
| Settings: privileged/data-source/file controls | `/settings` | Intentional safe exception | Clearly unavailable; no browser simulation or write path. |
| Setup packet, standards/work instructions, data health | Desktop-only command/profile surfaces | Intentional safe exception | Browser preserves profile facts but does not fabricate filesystem-dependent exports or privileged workflows. |
| Loading, empty, malformed, unavailable, unauthorized, not found | existing `StateViews`, API client | Regression covered | API client preserves typed failures; no invented success state. |
| Dark/light/system/reduced motion | shell settings + generated tokens | Implemented, focused validation | System follows the browser media preference. |
| Responsive viewports | global styles and existing Playwright suite | Partial validation | Existing responsive test passes; governed visual capture comparison remains required before release acceptance. |

Do not label a row complete until its cited evidence is current. Qt and browser
font rasterization can differ; that is not permission to hide layout defects.

## Legacy preservation and recovery

The legacy production-web source is immutable:

- Annotated tag: `web-ui-legacy-0.22.12`
- Archive branch: `archive/web-ui-legacy-0.22.12`
- Target: `0ddf66bfff6dd23c07279d55576736290d040dca`

Build the legacy source from its exact reference in an isolated directory;
never check it out over a working Project Mirrorline tree. Record the Node
version, lockfile SHA-256, build command, static manifest SHA-256, and file
inventory alongside the generated archive. The legacy static tree retains its
0.22.12 identity; Project Mirrorline uses `ui_generation: mirrorline` in
`frontend-release.json`.

Recovery selection is deployment-only. It must be driven by a reviewed,
root-owned generation registry and the transactional web-host release path;
ordinary users never see a theme switcher. The selector verifies the selected
static release manifest before changing the host's `current` symlink, and a
rollback selects the prior registered generation rather than copying files.

## Validation

```powershell
Set-Location web
pnpm install --frozen-lockfile
pnpm run format:check
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run theme:check
pnpm run build
pnpm run test:e2e
```

Use the repository's pinned Node 22.13 runtime. No production deployment,
MySQL migration, API write enablement, or browser credential is authorized by
this project.
