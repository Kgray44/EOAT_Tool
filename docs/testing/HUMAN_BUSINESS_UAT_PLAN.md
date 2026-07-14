# Human business UAT plan - Settings-only authentication

Environment: IT staging only. Development authentication is not acceptable for final UAT when a real staging provider is available.

Required representatives: Manufacturing Engineering, Maintenance, Operations as appropriate, Nolato IT and application owner.

Each execution record must contain test ID, tester, company role, date, prerequisites, steps, expected result, actual result, pass/fail, defect reference and approval/signature.

## Required scenarios

- UAT-01: Launch without signing in; no browser, login dialog or LDAP prompt.
- UAT-02: Home, search, Library and EOAT/machine/tool profiles work unsigned-in.
- UAT-03: History, Fit Check, Setup Packet, PDF, documents/photos/tags/annotations work unsigned-in.
- UAT-04: Normal writes, audits, maintenance, movement, refresh/deep refresh and multi-user workflows remain unsigned-in.
- UAT-05: Settings opens with all values/checked states visible and controls/save disabled.
- UAT-06: Admin button starts the approved company provider.
- UAT-07: Non-administrator receives controlled denial and Settings remain locked.
- UAT-08: Approved administrator unlocks only Settings; ordinary application does not change mode.
- UAT-09: Settings save succeeds and server rechecks permission.
- UAT-10: Immediate through five-minute auto-lock; leaving Settings and expiry behavior.
- UAT-11: Provider outage leaves EOAT Atlas fully usable and Settings locked with correct message.
- UAT-12: Role removal, disabled user, logout and revocation relock Settings.
- UAT-13: API outage preserves cached reads, blocks Settings write and queues nothing.
- UAT-14: Two users with different Settings roles and concurrent ordinary workflows.
- UAT-15: IT verifies no local password/development fallback, desktop LDAP connection or stored company credential.

No scenario is passed until a named human records actual results in the UAT report.
