# EOAT Atlas 0.25.4 validation receipt

## Source identities

- Browser-parity implementation: `b6265466aba391cc3430b71919617ffd12f305d7`
- Authentication test/evidence update: `d4924810e496b3c9a152e88989366a3da63e9818`
- LDAP fail-closed fallback: `5db124fc05eddf97b037298d3e5465056a7a1d2d`
- Release-format-only head: `445fcbd62aa9f830f8da0fb74e111939ff6cabfa`

The last commit changes only the eleven web files named by the release
formatter. `git diff --name-only 5db124fc..445fcbd -- server core tests` is
empty, so successful backend evidence remains bound to identical backend and
test bytes. The governed web-release builder then reran locked install,
generated-contract check, format check, lint, typecheck, Vitest, theme check,
and the production build from `445fcbd`.

## Terminal validation evidence

| Collection | Result | Notes |
| --- | --- | --- |
| Web release-builder validation | PASS | At `445fcbd`: locked install, generated-contract check, format, lint, typecheck, 52-test Vitest, theme check, and production build. |
| Web Vitest | 52 passed | Candidate source: 12 files, 52 tests. |
| Focused Chromium Machine profile | 7 passed | Isolated candidate server; Machine 27, semantics, reload, and read-only requests. |
| Focused Chromium relationship layout | 1 passed | Zero/one/two/three/many, long text, mobile, font scale, and overflow contract. |
| Core backend | 131 passed | Bounded exact-source shard. |
| Top-level backend group 1 | 310 passed, 4 skipped, 1 warning | Re-run after the final LDAP fallback. |
| Top-level backend group 2 | 351 passed, 4 skipped | Bounded exact-source shard. |
| Top-level backend group 3 | 303 passed, 1 skipped, 1 warning | Four terminal subshards: 40, 87, 81/1 skipped, 95/1 warning. |
| Top-level backend group 4 | 216 passed, 1 skipped | Four terminal subshards: 33, 65, 67, 51/1 skipped. |
| Complete non-MySQL aggregate | 1,311 passed, 10 skipped | Core plus all 153 top-level test files. |
| Loopback MySQL integration | 137 passed, 7 skipped, 1 warning | Full `tests/integration` run against `eoat_atlas_test` at `5db124fc`; the later commit does not alter backend or test bytes; database dropped afterward. |
| Final LDAP fallback unit module | 11 passed | No LDAP network operation; confirms deterministic RFC 4515 escaping at final source content. |

The earlier monolithic full backend attempt was externally terminated at 68%
without a summary/JUnit result and is intentionally excluded from totals. An
initial MySQL attempt against the local configured development database was
blocked by the reset guard; it is likewise excluded. The successful MySQL run
used loopback `eoat_atlas_test` only and was followed by explicit database
drop. Shared development accounts were preserved because they were not proved
test-run-owned.

The successful final-source MySQL run and all backend shards operated only on
the loopback test database. The test database was dropped after each completed
MySQL run; shared development accounts were not removed because the tests did
not prove they were created for the run.
