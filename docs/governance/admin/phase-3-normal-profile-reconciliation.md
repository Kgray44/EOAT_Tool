# Phase 3 Normal-Profile Route Reconciliation

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
common ancestor. A broad merge or cherry-pick would therefore import unrelated
normal-client state, including normal editing and media workflows, and would
rewrite the governed Admin delivery boundary. That was not performed.

## Required integration boundary

The candidate normal client is substantially larger than the governed Admin
lineage: its router depends on the candidate application's providers, normal
authorization, search/navigation shell, React Query client, profile blocks,
normal editing, media, and several unrelated release-parity features. Importing
only a lookalike profile page would not reuse the proven normal profile
semantics. Importing the dependencies would be a broad reconciliation, not a
Phase 3 Admin change.

Accordingly, this branch deliberately does **not** create a replacement normal
profile component, Admin-shell substitute, or `/admin/eoats|machines|tools`
route. It implements only the canonical URL generation contract in Audit Event
Detail. The existing normal API resources (EOAT profile/relationships/history/
media; Machine and Tool profile/relationships/history) are recorded here to
bound the smallest future reconciliation, but no current Admin UI consumes
them.

Audit Event Detail continues to generate its links from immutable Audit
`entity.display_id`, producing `/eoats/<business_identifier>`,
`/machines/<machine_number>`, or `/tools/<business_identifier>`. Events lacking
that canonical identity deliberately have no link.

## Validation and remaining dependency

`web/tests/e2e/admin.spec.ts` proves the three exact Audit Event Detail hrefs
and proves that a historical event without a canonical display identifier has
no deceptive normal-profile link. This is URL-contract evidence only. Direct
normal-profile refresh, browser Back from the normal profile, and confirmation
that ordinary users see only the canonical normal UI require reconciliation of
the actual normal-client source at `7d9b6952ca` with this Admin lineage. They
cannot be claimed from the Admin-only branch.
