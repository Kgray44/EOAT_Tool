# EOAT Atlas Admin Phase 2: Read-Only Administration Design

Status: implementation design record.  This document records the Phase B
solution before and alongside implementation; it does not grant Phase 3+ scope.

## Baseline and architecture decision

Phase 2 starts at accepted Phase 1 commit `8634a55649` on the isolated
`feature/admin-phase2-readonly` worktree.  The accepted source contains the
FastAPI/MySQL audit foundation and PySide desktop application, but no browser
client.  Phase 2 therefore introduces a small React/TypeScript client under
`web/`, the repository's established browser-client location, without changing
the normal desktop routes or importing later, unaccepted product work.

The browser client is a presentation layer only.  It uses typed HTTP calls to
`/api/v1/admin`; it never reads MySQL, derives Administrator privilege, or
stores an authoritative role in local state.  The server retains the Phase 1
`require_admin` boundary for every Admin route.

## Reused Phase 1 foundation

* `AuditEventRepository` provides parameterized filters, bounded server
  pagination, and canonical `occurred_at_utc DESC, event_id DESC` ordering.
* `/api/v1/admin/audit/catalog`, list, and detail contracts provide controlled
  taxonomy values, redacted event data, and immutable event deep links.
* Trusted request identity and `require_admin` distinguish unsigned, Viewer,
  and Administrator callers independently of browser navigation.
* The audit writer, structured diff, redaction policy, and MySQL schema remain
  governed Phase 1 behavior and are not redesigned in this phase.

## Phase 2 additions

The Admin API gains safe read-only overview, system, diagnostics, and access
status contracts.  Overview metrics and recent activity are calculated by the
repository from the authoritative ledger, with an explicit server observation
time.  They expose no environment dump, credentials, filesystem paths, or raw
secret values.

The browser Admin shell provides `/admin`, `/admin/audit`,
`/admin/audit/events/:eventId`, `/admin/system`, and `/admin/diagnostics`.
It has keyboard-accessible navigation, an access-denied state, loading/error/
empty states, and a path back to the ordinary application.  The audit screen
uses URL query parameters as the investigation state and sends each accepted
filter to the server.  Pagination is server-side.  Catalog selectors use
server-owned codes, while labels remain human readable.

Event detail renders a reusable structured before/after component.  It
distinguishes absent, null, blank, and redacted values, bounds long structured
values, and presents a sanitized raw representation only on request.  Request
and correlation IDs link back to filtered ledger views.  Entity links use only
stable event entity IDs and remain separate from normal operational History.

## Explicit deferrals and read-only boundary

No Admin mutation, audit edit/delete, data correction, export, access/group
mapping change, settings change, diagnostics command, SQL console, filesystem
browser, or Danger Zone action is implemented.  Data management, Settings and
Access administration are Phase 3; export, operations, and Danger Zone are
Phase 4; enterprise identity is Phase 5; production deployment/privileges are
Phase 6.  The only identity mapping in this phase is the existing isolated
development/staging rehearsal seam.

## Verification strategy

Backend tests cover overview aggregation, authorization negative cases,
filtering, pagination, detail/not-found behavior, redaction, and tied timestamp
ordering.  Frontend tests cover URL state, authorization presentation, ledger
loading/empty/error behavior, detail/diff semantics, and navigation.  Browser
tests exercise the same user-visible flows against an isolated API fixture.
Real MySQL acceptance remains restricted to `eoat_atlas_test`; production and
development schemas are excluded.
