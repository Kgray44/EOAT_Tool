# EOAT Atlas Phase 5 Frontend Reconciliation

Status: source reconciliation and local validation complete; staging deployment
and real-corporate acceptance remain blocked on a browser-trusted certificate.

## Provenance and observed regression

Read-only production inspection on 2026-08-15 established that the live normal
frontend is release `eoat-atlas-0.26.10-725e97f-20260811T141252Z`, built from
`725e97fa4603f10d32312a9b41f9b52c310dedb5` on
`origin/codex/web-desktop-full-parity`. The retained pre-Phase-5 staging
release `eoat-atlas-0.26.10-725e97f` has that same frontend identity.

The deployed Phase-5 staging release `eoat-atlas-phase5-a2b91c6c` instead
records source `a2b91c6c642e7c6456a47389e599fadd239ad07c` from
`feature/admin-phase5-corporate-auth`. Its build identifies itself as the
older Administration UI and contains a different static asset set. It is not
the normal production UI simply because its backend/authentication lineage is
newer.

The source comparison found 54 changed web files (12,257 additions and 14,809
deletions) between the production frontend commit and the Phase-5 candidate.
The Phase-5 tree had dropped the current Mirrorline application shell, normal
Home search and Library behavior, profile/media presentation, Fit Check,
browser-preference Settings, responsive design tokens, and their normal-route
tests. It retained the Admin application and a corporate form only inside the
Admin surface, so signed-out normal users had no discoverable Sign In action.

## Comparison

| Area | Production and pre-Phase-5 staging (`725e97f`) | Phase-5 staging (`a2b91c6c`) | Reconciled candidate |
| --- | --- | --- | --- |
| Shell, Home, Library, search, profiles, Fit Check | Current Mirrorline normal UI | Older Admin-focused shell | Production normal UI restored |
| Navigation, responsive layout, typography, media/history | Current tokens and route components | Older layout and missing normal components | Production components and tests restored |
| Settings | Browser-local display/accessibility preferences | Obsolete client contract | Browser preferences; Administrator-only governed link |
| Documents/photos | Safe metadata and content/thumbnail behavior | Metadata but no delivery boundary | Fail-closed delivery boundary restored |
| Admin, Audit, governed mutation, Danger | Not normal frontend authority | Accepted Phase 1-4 UI | Retained from Phase 5 |
| Corporate identity | No normal-shell affordance | Corporate form only within Admin | Shell Sign In, signed-in state, Sign Out, role-gated Admin link |

## Reconciliation strategy

No unrelated-history merge or bulk cherry-pick was used. The smallest coherent
normal-web boundary was restored from the known live production source. The
accepted Phase-5 `AdminApp`, Admin API/client integration, Admin styles/audit
diff, current FastAPI API client contract, and corporate session controls were
then re-applied. OpenAPI types were regenerated from the current Phase-5 API.

The isolated `server/eoat_api/web_content.py` read-only delivery module and its
three UUID endpoints were restored because current normal profile media renders
those URLs. It validates configured roots and any UNC mapping on the server,
rejects traversal/symlink escapes, does not serialize storage paths, and
returns no content if roots are not explicitly approved. No donor backend,
schema, authentication implementation, migration, or environment file was
imported.

Explicitly excluded: stale donor Settings/session endpoints, donor backend
routes/configuration, Git history, caches, environment files, credentials, and
release artifacts. The reconciled Settings page uses browser-local preferences;
governed server configuration remains behind the Phase 1-4 Administrator API
and is not linked for non-administrators.

## Corporate UI behavior

The normal shell exposes `Sign in` while unsigned. The form sends credentials
only to the existing `kerberos_form` endpoint; its `type=password` input is
cleared after every attempt and is not placed in browser storage. Success shows
a safe display name and `Sign out`. The Admin and Administrator Settings links
appear only when the server-derived role is `ADMINISTRATOR`. Backend
authorization remains authoritative.

There is no rehearsal selector, URL switch, client-state toggle, password
memory, token display, or provider implementation detail. Safe login errors
remain generic. A provider outage fails closed through the existing endpoint.

## Validation and deployment plan

Before staging switch: regenerate OpenAPI, TypeScript, ESLint, Vitest,
production build, focused web-content tests, and Playwright. Local work passes
the regenerated client, TypeScript, ESLint, production build, 53 web Vitest
tests, and 10 focused web-content tests. Browser parity must compare Home,
Library, an EOAT, Machine, Tool, Fit Check, account area, and responsive
viewport, with the account UI as the only intentional shell difference.

The corrected release must be a new versioned staging server/static release;
it must not overwrite `eoat-atlas-phase5-a2b91c6c`. The former Phase-5 release
and `eoat-atlas-0.26.10-725e97f` remain rollback candidates. Only the test
service, its staging release pointer, and separate staging static pointer may
change. Production is read-only verification only.

## TLS prerequisite

Read-only NGINX and OpenSSL inspection found both production `:443` and staging
`:8443` reference `/etc/ssl/certs/eoat-atlas-test.crt` and its test key. It has
the required hostname/SAN `eoat-atlas.gwplastics.com`, but is self-issued and
OpenSSL verification fails with error 18 (`self-signed certificate`). Repointing
staging to the same files would not establish browser trust.

IT must provide a browser-trusted corporate-CA certificate chain and protected
key for `eoat-atlas.gwplastics.com`, or establish the approved CA trust path.
A staging-vhost-only change may use that material after `nginx -t` and a
preserved staging configuration backup. No self-signed replacement, certificate
bypass, validation disablement, or corporate credential entry is authorized.
