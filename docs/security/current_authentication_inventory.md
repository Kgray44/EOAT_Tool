# Current authentication and authorization inventory

Inventory date: 2026-07-14

EOAT Atlas starts and performs normal work without user authentication. Phase 10 authentication is scoped only to temporarily unlocking Settings editing.

| Component | Location | Current purpose | Security authority | Production-safe? | Required replacement/status |
|---|---|---|---|---|---|
| Settings Admin button | `app/atlas/minimalist/settings_page.py` | Entry point for Settings unlock | API authentication session | Yes in new path | Starts provider login only when clicked |
| Legacy password dialog | `AdminAccessDialog` in `settings_page.py` | Historical local password UI | Local PBKDF2 file | No | Retained dormant for recovery; no production UI invokes it |
| Legacy password storage | `settings_store.py`, `eoat_atlas_admin_auth.json` | Salted PBKDF2 hash and hard-coded development seed | Local file | No | No longer initialized or consulted by Settings Admin path |
| Settings lock state | `MinimalistSettingsContent.admin_active` | Disables controls while preserving visible values | Client usability lock | Yes as secondary control | API rechecks `settings.edit` before save |
| Auto-lock | Settings timer, 0/15/30/60/120/300 seconds | Relocks after leaving Settings | Client usability lock | Yes | Token cleared; ordinary app remains available |
| Ordinary API actor | `server/eoat_api/security.py` | Attribution for ordinary writes | Application instance | Yes for product scope | No user login; cannot authorize `settings.*` |
| Settings authentication boundary | `server/eoat_api/authentication/` | Provider normalization and short-lived session | API | Development validated | Real provider awaits IT selection |
| Roles and permissions | `authentication/permissions.py` | Settings-specific authorization | API | Yes | Only ADMINISTRATOR currently receives Settings permissions |
| User and role tables | `users`, `roles`, `user_roles` | JIT identity and synchronized role record | MySQL/API | Yes | No company password or assertion fields |
| Session table | `authentication_sessions` | Hashed-token, expiry, revocation, roles and permissions | MySQL/API | Yes | Added by Alembic 0005 |
| Group mapping | `external_group_role_mappings` | Stable external group to role mapping | MySQL/API | Foundation only | Actual identifiers require IT |
| Authentication audit | `authentication_audit_events` | Settings admin login, denial, logout, expiry and changes | MySQL/API | Yes | Sensitive material excluded |
| Development provider | `providers/development.py` | Local Settings-flow testing | API configuration | Development only | Production startup rejects it |
| SAML adapter | `providers/saml.py` | Fail-closed provider boundary | API | Not configured | Await IT metadata, claims and approval |
| LDAP adapter | `providers/ldap.py` | Fail-closed provider boundary | API | Not configured | Await IT LDAPS/search/login decision |

The pre-Phase-10 ordinary role header remains accepted in development for regression attribution, but absence of that header no longer triggers user login or blocks normal workflows. No global login screen or persistent identity display was added.
