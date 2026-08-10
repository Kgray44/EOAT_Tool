# EOAT Atlas desktop and web parity matrix

EOAT Atlas Desktop (PySide) and EOAT Atlas Web (React) are supported clients
of the same platform. The desktop implementation under `app/atlas/minimalist/`
is the established behavior reference unless a shared API contract deliberately
supersedes it. Browser presentation may reflow for smaller viewports, but it
must preserve terminology, information hierarchy, truth states, and supported
actions.

## Scope and status vocabulary

- `PASS` — equivalent behavior is present and exercised by existing coverage.
- `FIXED` — this parity change was implemented in the current branch.
- `BLOCKED-AUTH` — a browser write remains unavailable only because the active
  Kerberos/LDAP authentication contract is being developed in a separate
  worktree. It must stay fail-closed until that work is reconciled.
- `BLOCKED-EXTERNAL` — a required acceptance activity depends on a controlled
  environment or reviewer disposition that this branch cannot truthfully
  synthesize.
- `INTENTIONAL-DIFFERENCE` — the platform behavior differs without changing
  the product result or security boundary.
- `NOT-APPLICABLE` — the desktop surface itself is marked unavailable or has
  no browser-safe source/API contract.
- `OPEN` — an identified non-auth parity correction remains to be implemented;
  this status is deliberately not treated as release acceptance.

## Matrix

| Area | Desktop reference | Web reference | Before this branch | Current status | Tests / boundary |
| --- | --- | --- | --- | --- | --- |
| Product shell and terminology | `shell.py`, `topbar.py` | `AppShell.tsx`, `Navigation.tsx` | Matched Atlas navigation hierarchy | PASS | Router keyboard-navigation coverage |
| Responsive navigation | desktop window layout | `global.css` responsive shell | Responsive browser adaptation | INTENTIONAL-DIFFERENCE | Mobile preserves actions and labels |
| Home dashboard and local search | `home.py` | `FoundationPage.tsx` | Local Home search and separate global search implemented | PASS | Router focus/reopen tests |
| Global search | `entity_search.py` | `GlobalSearchOverlay.tsx`, `SearchPage.tsx` | API-backed entity discovery implemented | PASS | Keyboard focus-trap tests |
| Library catalogs | `library.py` | `LibraryPage.tsx` | Machine, Tool, EOAT tabs with server paging | PASS | Discovery tests |
| Library filtering and sorting | `library.py` browse state | `LibraryPage.tsx`, `api/client.ts` | Server-side filter query, status, sort, and return state | PASS | Discovery filter contract |
| Authoritative selector values | desktop catalog bundle | catalog API and Library selectors | Text filters were API-representable but not all were bounded selectors | FIXED | Bounded `catalog-options` API and typed selector tests; plant-qualified machine values preserve ambiguity |
| Machine profile identity and overview | `library.py` record view | `MachineProfilePage.tsx` | Identity, setup, relationships, documents, photos, history | PASS | Profile-route tests |
| Tool profile identity and overview | `library.py` record view | `ToolProfilePage.tsx` | Identity, relationships, documents, photos, history | PASS | Entity profile tests |
| EOAT profile identity/location | `library.py` record view | `EoatProfilePage.tsx` | Immutable identifier, current-location evidence, QR route | PASS | QR/deep-link tests |
| Profile relationship semantics | desktop relationship cards | `ProfileBlocks.tsx` | Labels and source/evidence fields are browser-visible | PASS | ProfileBlocks tests |
| Documents | desktop document panel | `DocumentList` / web-document endpoints | Metadata and browser-safe open/download only | PASS | No internal file paths exposed |
| Photos | desktop gallery/lightbox | `PhotoGallery` / web-photo endpoints | Thumbnails, full browser-safe content, unavailable states | PASS | Browser-safe media endpoints |
| History | desktop history panel | `HistoryList` | Read ordering and empty/error states | PASS | Profile query coverage |
| Entity editing | desktop write workflows | no entity editor yet | API supports writes, but current browser has no active application-write session | BLOCKED-AUTH | Kerberos/LDAP branch owns write-session contract; anonymous writes remain prohibited |
| Media upload/archive/supersede | desktop write workflows | no browser write UI | API contracts exist but browser must not send unauthenticated writes | BLOCKED-AUTH | Requires reconciled authorization and audit verification |
| Audit generation after writes | desktop/API write services | API write services | No browser entity write can currently execute | BLOCKED-AUTH | Verify post-write history only with permitted test identity |
| Settings read | `settings_page.py` | `SettingsPage.tsx` | Full catalog and read-only state display | PASS | Settings component test |
| Settings administration | `settings_page.py` | `SettingsPage.tsx` | Development settings session, permissions, dirty drafts, confirmations | PASS | Existing authenticated-settings test; real LDAP remains blocked |
| Settings danger-zone actions | `settings_page.py` | `SettingsPage.tsx` | Typed confirmation and permission checks | PASS | Fail-closed when session absent |
| Fit Check selection | `fit_check.py` universal selectors | `FitCheckPage.tsx` | Fixed Machine/Tool/EOAT fields | FIXED | Compact desktop-aligned setup-item surface; Unit and Chromium coverage for all 6 orders; duplicate types disable evaluation rather than coercing values |
| Fit Check evaluation and truth states | `fit_check.py`, API rules | `FitCheckPage.tsx` | Authoritative API evaluation, warnings, unknowns, alternatives | PASS | Browser-safe POST; does not create history |
| Recent Fit Checks | desktop local recents | `fitCheckRecents.ts` | Browser-local recent list | INTENTIONAL-DIFFERENCE | Explicitly does not simulate server history |
| Setup packet / PDF | `fit_check.py`, `packet_builder.py` | `SetupPacketPage.tsx` | Desktop-only boundary page | FIXED | API-backed labelled compatibility and profile fields; browser print/save-PDF produces no write |
| Standards/work instructions | desktop coming-later surface | `DesktopBoundaryPage.tsx` | No browser-safe document source | NOT-APPLICABLE | Do not invent unverified document links |
| Data-health tools | desktop diagnostics | `DesktopBoundaryPage.tsx`, health/freshness UI | No authenticated read-only report contract | NOT-APPLICABLE | Browser shows available API freshness only |
| Freshness, loading, error, unknown | desktop data status | `StateViews.tsx`, `FoundationPage.tsx` | Explicit loading/error/unavailable and fetched timestamp | PASS | No "just now" claim without source timestamp |
| Authentication-aware UI | desktop admin state | `SettingsPage.tsx` | Settings login/logout surface and locked controls | PASS | Real LDAP activation is external to this branch |
| Authorization-aware entity actions | desktop write controls | future authenticated editor seam | No visible active browser write actions | BLOCKED-AUTH | Must consume, not duplicate, Kerberos/LDAP policy |
| QR/deep links | desktop navigation | React routes, QR labels | Canonical EOAT/Machine/Tool routes | PASS | Router and EOAT profile tests |
| Refresh/direct route/back-forward | desktop controller navigation | React Router | Browser history/direct routing | PASS | Route tests; host rewrite remains deployment-owned |
| Keyboard and accessibility | Qt accessible controls | semantic controls, skip link, dialog focus | Core keyboard paths implemented | PASS | Router keyboard tests |
| Browser visual regression capture | minimalist theme | deterministic Playwright capture | Desktop-only capture had no tablet/phone coverage | FIXED | 30 fixture screenshots across desktop, tablet, and phone; Settings uses an authoritative-shape locked-state fixture with a desktop-width overflow assertion; mobile header clearance is asserted; refreshed Qt/browser comparison has all 27 governed pairs present |
| Direct desktop-to-browser visual review | offscreen PySide/installed desktop | Playwright capture artifacts | No current same-record side-by-side reviewer disposition | BLOCKED-EXTERNAL | The refreshed 27-pair comparison remains deliberately unreviewed; requires controlled desktop session and reviewed difference register; browser screenshots do not substitute for that review |
| Tablet/mobile behavior | desktop not applicable | responsive CSS | Reflow rather than desktop-window emulation | INTENTIONAL-DIFFERENCE | Must preserve capability inventory; phone header overlap regression-tested |
| API contract usage | desktop gateway/API | `api/client.ts` | Read paths use authoritative API | PASS | Generated OpenAPI types and client tests |
| Production safety | desktop/API runtime | browser client | Writes remain disabled without permitted identity | PASS | No production change or credential exposure |

## Maintenance rule

A new user-facing desktop capability must be implemented in the web client in
the same release, or have an explicit row in this matrix with a justified
`BLOCKED-AUTH`, `INTENTIONAL-DIFFERENCE`, or `NOT-APPLICABLE` status. The same
rule applies to new web capabilities. A status may not be changed to `PASS`
without tests appropriate to its risk and an API-contract review where data or
authorization is involved.

## Authentication reconciliation

The active parallel worktree `codex/kerberos-ldap-foundation-0241` currently
changes `web/src/api/client.ts`, generated API types, `web/src/styles/global.css`,
the app shell, profile pages, Settings, and shared server authentication
contracts. This branch deliberately did not merge or alter that work. Before
integration, reconcile only the new setup-packet read method and the Fit Check
UI/routes against the final authenticated API client; preserve its fail-closed
write policy and validate browser entity writes only under the approved
development/test identity.
