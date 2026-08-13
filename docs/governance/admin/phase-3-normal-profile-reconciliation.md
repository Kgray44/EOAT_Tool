# Phase 3 Normal-Web Lineage Reconciliation

## Acceptance continuation — 2026-08-13

The smallest safe reconciliation was completed without merging the unrelated
normal-client lineage: the unified router owns the normal profile routes and
the accepted backend exposes the normal application's read-only Fit Check
selector contract at `/api/v1/web-fit-checks/options`. The endpoint uses only
active, non-archived authoritative records and compatibility joins; it
performs no write. The normal Fit Check page rendered against the protected
real-MySQL acceptance path, and the normal profile routes retained their
relative same-origin identifiers.

Browser acceptance confirmed Audit Event Detail -> `/eoats/:identifier`, the
committed normal EOAT profile, Browser Back to the original event, direct
EOAT/Machine/Tool profile routes, and Machine refresh. No `/admin/eoats`,
`/admin/machines`, or `/admin/tools` substitute route was created.

## Decision and provenance

Phase 3 Audit Event Detail must return people to the normal EOAT Atlas
application, not to a lookalike Admin profile. The accepted normal-route
contract is deliberately relative and same-origin:

| Audit entity | Normal route | Authoritative identifier |
| --- | --- | --- |
| EOAT | `/eoats/:identifier` | `business_identifier` |
| Machine | `/machines/:identifier` | `machine_number` |
| Tool | `/tools/:identifier` | `business_identifier` |

The canonical normal-web router was located in the independent local worktree
`C:\Users\kgray\eoat-web-desktop-full-parity`, branch
`codex/web-desktop-full-parity`, commit
`7d9b6952ca9f2b8c19eea102800ab3b3f061e9a0`. Its
`web/src/app/router.tsx` declares precisely those route shapes (the Machine
parameter is named `number` there but carries the same `machine_number`
value). The accepted Machine deep-link implementation entered that lineage in
`6d39823d08309cba3a109edda698ad8c47563748`; the EOAT QR profile work entered
in `7918d0da79dc244081937d2f67a1fc2389123d39`.

`git merge-base feature/admin-phase3-governed-editing 7d9b6952ca` returned no
common ancestor. A broad history merge or blind large-scale cherry-pick remains
rejected. The current reconciliation is a reviewed source port, with
`89316fc6d4` as its Admin source and `7d9b6952ca` as its normal-web source; it
does not import server, deployment, database, cache, secret, or generated
release-history state from the unrelated lineage.

## Reviewed module inventory

| Normal-web family | Classification | Destination / decision |
| --- | --- | --- |
| `src/app/{App,router,providers}` | REQUIRED | Unified router and React Query provider; Admin is a sibling route, not a nested second browser app. |
| `src/pages/{Foundation,Library,FitCheck,*Profile}` | REQUIRED | Canonical normal read surfaces and their loading/error/history/media behavior. |
| `src/api/{client,errors,presentation,routes,recent,qr}` | REQUIRED TRANSITIVE DEPENDENCY | Same-origin typed normal-read client; generated contract is regenerated from the current Phase 3 backend. |
| `src/components/{layout,navigation,search,feedback,qr,profile blocks}` | REQUIRED TRANSITIVE DEPENDENCY | Normal shell, responsive navigation, safe presentation, and read-only profile blocks. |
| `src/styles/{tokens,global,generated-theme-tokens}` | REQUIRED TRANSITIVE DEPENDENCY | Normal application's design tokens and layout. |
| `src/app/ReleaseParityGate` | RECONCILE | Retained only as a no-op in local development; it does not replace backend authority or gate Admin authorization. |
| `src/components/profile/{EntityEditor,CompatibilityEditor,InstallationEditor,MediaUpload}` | NOT REQUIRED | Deliberately excluded: they are the old normal-lineage mutation system and would bypass governed Phase 3 Admin semantics. |
| Normal server/Python, deployment, release metadata, `dist`, `node_modules`, caches, and environment files | NOT REQUIRED / OBSOLETE | Not ported. The accepted Admin FastAPI/MySQL backend remains authoritative. |
| `src/app/AdminApp.tsx`, `src/api/admin.ts`, `src/components/AuditDiff.tsx`, `styles/admin.css` | ALREADY PROVIDED BY ADMIN LINEAGE | Preserved unchanged and mounted at `/admin/*`. |
| `package.json`, TypeScript/Vite/ESLint settings, OpenAPI generation | CONFLICTING / RECONCILE | Normal web tooling adopted where needed for aliases, React Query, and generated contracts; Admin test/API support remains present. |

## Route and backend ownership

| Route | Owner after reconciliation | Semantics |
| --- | --- | --- |
| `/` | Normal application | Canonical normal home shell. |
| `/library` | Normal application | Canonical normal search/library. |
| `/eoats/:identifier` | Normal application | Read-only EOAT profile using normal API resources. |
| `/machines/:identifier` | Normal application | Read-only Machine profile using `machine_number`. |
| `/tools/:identifier` | Normal application | Read-only Tool profile. |
| `/fit-check` | Normal application | Existing normal read-only fit-check behavior. |
| `/admin/*` | Accepted Admin Phase 1-3 application | Governed rehearsal/CSRF/capability workflows and immutable Audit Ledger. |

The FastAPI/MySQL backend at the accepted Phase 3 source remains authoritative.
No backend source from `7d9b6952ca` is used by this port. Normal profiles are
not Admin pages and expose no global audit, actor, request/correlation, access,
or security metadata.

## Port provenance

| Source at `7d9b6952ca` | Destination | Treatment |
| --- | --- | --- |
| `web/src/api/*` | `web/src/api/*` | Copied normal read client; `generated/*` regenerated from current backend. Existing `admin.ts` retained. |
| `web/src/app/{App,providers,browserSettings,libraryContext,ReleaseParityGate}` | matching `web/src/app` | Copied/adapted around a unified router. |
| `web/src/pages` | `web/src/pages` | Copied canonical normal pages; profile mutation widgets removed. |
| `web/src/components/{auth,feedback,layout,navigation,profile blocks,qr,search}` | matching `web/src/components` | Copied read/presentation dependencies; old mutation widgets excluded. |
| `web/src/styles/{tokens,global,generated-theme-tokens}` | matching `web/src/styles` | Copied. Existing Admin CSS retained. |
| `web` toolchain files | `web` | Reconciled for aliases, React Query, tests, and current contract generation. |

## Required integration boundary

The candidate normal client is substantially larger than the governed Admin
lineage: its router depends on the candidate application's providers, normal
authorization, search/navigation shell, React Query client, profile blocks,
normal editing, media, and several unrelated release-parity features. Importing
only a lookalike profile page would not reuse the proven normal profile
semantics. Importing the dependencies would be a broad reconciliation, not a
Phase 3 Admin change.

The earlier URL-only state is superseded by this authorized coherent port. The
port creates one browser router with normal pages and the preserved governed
Admin route family. It still does **not** create an Admin-shell substitute or
`/admin/eoats|machines|tools` route.

Audit Event Detail continues to generate its links from immutable Audit
`entity.display_id`, producing `/eoats/<business_identifier>`,
`/machines/<machine_number>`, or `/tools/<business_identifier>`. Events lacking
that canonical identity deliberately have no link.

## Validation and follow-through

The existing Admin Playwright checks still prove the three exact Audit Event
Detail hrefs and the no-link behavior for a historical event without canonical
identity. The unified router, normal direct route, refresh, authorization
separation, and real Audit-to-profile flows require their own acceptance
evidence after the port; they are intentionally not claimed by this record
until that work is complete.
