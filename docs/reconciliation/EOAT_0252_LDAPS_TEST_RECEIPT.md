# EOAT Atlas 0.25.3 LDAPS test receipt

Date: 2026-07-30

| Gate | Result |
| --- | --- |
| Focused enterprise-authentication and configuration tests | `16 passed`, 2 dependency deprecation warnings |
| Python authentication module compile | Passed |
| Web validation | Typecheck, ESLint, production build, and Vitest: `43 passed` |
| Browser fixture suite | Playwright: `12 passed, 4 skipped`; skips are live-production or visual-capture tests that require an explicit live base URL or capture request |
| Real-directory testing | No user authentication attempted; separate anonymous preflight recorded in `EOAT_0252_LDAPS_PREFLIGHT_RECEIPT.md` |

Focused unit coverage includes production development-provider rejection,
unconfigured fail-closed behavior, identifier normalization, RFC 4515 escaping
of wildcard/parenthesis/backslash/NUL/apostrophe/at-sign data, and the missing
administrator-group authorization lock. The existing Settings integration
suite retains permission, typed-confirmation, logout, expiry, and audit paths;
the browser client no longer stores a Settings bearer token.
