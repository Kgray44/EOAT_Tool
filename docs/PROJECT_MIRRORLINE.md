# Project Mirrorline

Project Mirrorline rebuilds the EOAT Atlas browser UI from the current
PySide6 Minimalist interface. The desktop remains the design and behavior
authority; the browser continues to use the existing same-origin, read-only
API and must never reproduce compatibility decisions or hold credentials.

## Acceptance state

**Current state: the desktop-composition corrections are finalized as a source
release candidate and are not deployed.** The canonical application version
is `0.23.3` after the deterministic convergence gates and final evidence
review passed. This does not authorize a deployment, API
writes, MySQL changes, or production activity. The canonical ledger records
the finalized application version only; a separately authorized host
transaction is still required to activate any generated artifact.

The states are deliberately separate:

| State | Meaning | Release-history entry | Production effect |
| --- | --- | --- | --- |
| Implementation candidate | Feature work exists on a review branch | No | None |
| Validation candidate | Deterministic validation and visual evidence are under review | No | None |
| Accepted release | A separate review authorizes finalization after all gates pass | Finalized entry created by the version tool | None by itself |
| Deployed release | A separately authorized host transaction activates a built artifact | Existing finalized entry required | Production changes only when explicitly authorized |

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
| Home, atmospheric shell, title accent, Get Started card | `/`, `FoundationPage` | Complete, visual + focused validation | 1760px desktop geometry translated responsively; API state remains truthful. |
| Hamburger menu, active page, outside/Escape close | `AppShell` menu overlay | Implemented, unit + Playwright coverage | Browser uses semantic navigation and focusable links. |
| Global command/entity search | `GlobalSearchOverlay` | Implemented, focused unit coverage | Browser limits results to API entities; desktop-only commands/reports remain unavailable. |
| Home contextual search | Home search dispatches global overlay | Implemented | Same 125ms debounce and exact entity route activation. |
| Library and retained filters | `/library` | Complete, visual + regression coverage | URL query/filter context and scroll restoration survive profile navigation. |
| EOAT profile | `/eoats/:identifier` | Complete, visual + regression coverage | Browser-safe document/photo routes only; desktop filesystem metadata remains excluded. |
| Machine profile | `/machines/:number` | Complete, visual + regression coverage | Browser-safe media only. |
| Tool profile | `/tools/:identifier` | Complete, visual + regression coverage | Browser-safe media only. |
| Fit Check | `/fit-check` | Complete, visual + regression coverage | Uses the authoritative non-persisting API endpoint only; browser-local recents can be restored or cleared without creating server history. |
| Settings: display/accessibility | `/settings` | Complete | Theme, accent, animation, reduced motion, and contrast are browser-local and persist only in browser storage. |
| Settings: privileged/data-source/file controls | `/settings` | Intentional safe exception | Clearly unavailable; no browser simulation or write path. |
| Setup packet, standards/work instructions, data health | `/setup-packet`, `/standards`, `/data-health` | Complete browser-safe boundary | Truthful direct routes preserve the coming-later desktop state or link to a read-only Fit Check; they never fabricate filesystem-dependent exports or privileged workflows. |
| Loading, empty, malformed, unavailable, unauthorized, not found | existing `StateViews`, API client | Complete, visual + regression coverage | API client preserves typed failures; no invented success state. |
| Dark/light/system/reduced motion | shell settings + generated tokens | Complete, focused validation | System follows the browser media preference; contrast and reduced motion use persistent, local-only preferences. |
| Responsive viewports | global styles and existing Playwright suite | Complete, desktop and responsive validation | Tested at 1760x1080, 1440x900, 1280x820, 1024x768, 768x1024, 430x932, 390x844, and 360x800 without horizontal overflow. |

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

The reviewed registry has a selection name that is intentionally separate
from the bundle identity:

```json
{
  "schema": 1,
  "generations": {
    "atlas": {
      "release_directory": "eoat-atlas-mirrorline",
      "manifest_sha256": "<mirrorline manifest SHA-256>",
      "expected_ui_generation": "mirrorline"
    },
    "legacy": {
      "release_directory": "eoat-atlas-legacy",
      "manifest_sha256": "<legacy manifest SHA-256>",
      "expected_ui_generation": "legacy"
    }
  }
}
```

Only `atlas` and `legacy` are valid deployment selections. The selector
rejects unknown selections, missing/unknown/mismatched UI identities, changed
files, changed manifests, traversal, and link/reparse-point release paths.

## Validation

## Governed visual evidence

The deterministic Qt driver captures the real Minimalist shell at 1760×1080
with offscreen Qt, the controlled test bundle, and fixed Windows font/DPI
settings. The opt-in Playwright capture uses the matching browser fixture and
state names. Both write outside the repository; generated PNGs are never
committed.

```powershell
$evidence = "C:\EOAT-artifacts\mirrorline-visual"
python scripts\capture_mirrorline_qt.py --output "$evidence\qt"
$env:EOAT_MIRRORLINE_VISUAL_EVIDENCE = $evidence
Set-Location web
pnpm exec playwright test tests/e2e/mirrorline-visual-capture.spec.ts
Set-Location ..
python scripts\compare_mirrorline_visuals.py --evidence $evidence --require-complete --require-reviewed
```

The comparator produces a side-by-side image, 50% overlay, difference image,
per-state metrics, and a discrepancy list. It fails `--require-complete` for
any missing governed state; dynamic masks require an explicit reviewed
`dynamic-masks.json` rectangle entry and are never used for geometry or
content defects.

The exhaustive review completed at visual-evidence iteration 21. All **27 of 27** governed
states have matching Qt/browser capture names, generated comparison artifacts,
and a reviewed, non-blocking disposition. The review manifest remains beside
the external evidence rather than in source control. `--require-complete`
fails missing pairs; `--require-reviewed` additionally fails an absent or
unresolved state disposition. The review covers the browser-safe responsive
translation and the explicit desktop-only boundary without treating either as
an API-write or production authorization.

## Browser validation

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
