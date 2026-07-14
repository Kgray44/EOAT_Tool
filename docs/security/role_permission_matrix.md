# Settings administration role and permission matrix

This Phase 10 matrix does not restrict ordinary EOAT Atlas use. Viewer, Technician, Engineer and Administrator labels affect only the protected Settings administration session.

| Permission | Viewer | Technician | Engineer | Administrator |
|---|---:|---:|---:|---:|
| `settings.read` | No special session required | No special session required | No special session required | No special session required |
| `settings.edit` | No | No | No | Yes |
| `settings.set_default` | No | No | No | Yes |
| `settings.import` | No | No | No | Yes |
| `settings.restore` | No | No | No | Yes |
| `settings.authentication.configure` | No | No | No | Yes, subject to recent-auth policy |

All users, including unsigned-in users, retain ordinary Home, search, Library, profiles, History, Fit Check, exports, documents, photos, tags, annotations, EOAT workflows, audits, maintenance, refresh and offline read-only behavior. The matrix requires Engineering and IT approval before production.
