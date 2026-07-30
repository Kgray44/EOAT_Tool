# EOAT Atlas 0.25.2 source-feature verification matrix

This matrix is source-and-test evidence for the browser parity requirements.
It does not claim production activation or LDAP readiness.

| # | Requirement | Source implementation | Direct automated evidence | Result |
| ---: | --- | --- | --- | --- |
| 1 | Home typing stays in Home search | `web/src/pages/FoundationPage.tsx` | `web/tests/e2e/discovery.spec.ts` Mirrorline shell case | PASS |
| 2 | Global search opens intentionally | `web/src/app/App.tsx` command-palette handling | Same browser case verifies `Ctrl+K` and Escape focus behavior | PASS |
| 3 | EOAT profile tabs are URL-backed | `web/src/pages/EoatProfilePage.tsx`, `components/profile/profileTabs.ts` | `web/src/pages/EoatProfilePage.test.tsx`, `eoat-profile.spec.ts` | PASS |
| 4 | Machine profile tabs are URL-backed | `web/src/pages/MachineProfilePage.tsx`, shared profile tabs | `web/src/pages/EntityProfilePage.test.tsx`, `machine-profile.spec.ts` | PASS |
| 5 | Tool profile tabs are URL-backed | `web/src/pages/ToolProfilePage.tsx`, shared profile tabs | `web/src/pages/EntityProfilePage.test.tsx`, `discovery.spec.ts` | PASS |
| 6 | Library context restores query, filters, sorting, page, and scroll | `web/src/app/libraryContext.ts`, Library back-navigation code | `web/tests/e2e/discovery.spec.ts` preserves filtered page state | PASS |
| 7 | Library catalogs load by default | `web/src/pages/LibraryPage.tsx` | `DiscoveryPage.test.tsx` default server-paginated catalog test | PASS |
| 8 | Library filters use authoritative selectors | `web/src/pages/LibraryPage.tsx`, API client filters | `DiscoveryPage.test.tsx` verifies server-side filter request | PASS |
| 9 | Settings controls stage edits | `web/src/pages/SettingsPage.tsx` draft queue/action bar | `SettingsPage.test.tsx` | PASS |
| 10 | Danger Zone uses typed confirmation | `web/src/pages/SettingsPage.tsx` | Settings page component coverage and source control guards | PASS |
| 11 | Fit Check has three universal polymorphic entity slots | `web/src/pages/FitCheckPage.tsx` `EntitySlot` state and slot type selectors | `DiscoveryPage.test.tsx` swaps slot roles and completes a valid setup | IMPLEMENTED DURING THIS GOAL |
| 12 | All six Fit Check selection orders work | `FitCheckPage.tsx` independent slot update/order tracking | `DiscoveryPage.test.tsx` executes all six permutations | IMPLEMENTED DURING THIS GOAL |
| 13 | Relationship cards size naturally | `components/profile/ProfileBlocks.tsx`, relationship presentation | `machine-profile.spec.ts` relationship card assertions | PASS |
| 14 | Relationship states retain distinct semantics | `api/presentation.ts`, machine/profile relationship rendering | `machine-profile.spec.ts` and sentinel assertions | PASS |
| 15 | Provenance is evidence detail, not primary label | API relationship contracts and profile presentation | MySQL read conversion and browser profile fixture coverage | PASS |
| 16 | Machine Overview carries useful canonical fields | `web/src/pages/MachineProfilePage.tsx` overview rows | `machine-profile.spec.ts` | PASS |
| 17 | Browser-safe image routes exist | `server/eoat_api/web_content.py` | `tests/test_web_content_delivery.py`, browser media fixtures | PASS |
| 18 | Raw source paths remain hidden | server root/mapping policy and browser-only metadata routes | `tests/test_web_content_delivery.py`, `web/README.md` contract | PASS |
| 19 | Physical EOAT identities remain distinct | migration `20260729_0009`, API models/repository | disposable MySQL identity integration tests | PASS |
| 20 | Subtitle and density cleanup is implemented | `api/presentation.ts`, profile/library CSS and components | responsive fixture browser coverage at desktop/tablet/mobile widths | PASS |

The matrix’s browser evidence was executed with controlled fixtures. Live
browser acceptance remains intentionally deferred until a governed live target
is supplied; this matrix does not substitute fixtures for production approval.
