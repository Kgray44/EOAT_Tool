# EOAT governed media-source manifest

Use this template only after the source owner has approved the media root for
browser delivery and a server administrator has confirmed its read-only mount.
It is a source-approval record, not an authorization to copy media or alter
database records.

| Field | Required value |
| --- | --- |
| Manifest identifier | `EOAT-MEDIA-SOURCE-YYYYMMDD-<owner>` |
| Logical source name | Human-readable approved source identity |
| Absolute source root | Approved server-side path; never expose to browser clients |
| Plant / area scope | Plant and area(s) covered by the root |
| Original files remain untouched | `Yes` / exception reference |
| Read-only mount confirmed | `Yes`; include verifier and date |
| Recursion allowed | `Yes` / `No` |
| Allowed extensions | e.g. `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf` |
| Filename / folder convention | EOAT identifier, physical identity, or documented crosswalk |
| Expected physical-identity source | Authoritative identity/alias source and schema revision |
| Approximate file count | Observed count and observation date |
| EOAT identifier coverage | Observed naming coverage and exceptions |
| Server mapping method | `EOAT_WEB_CONTENT_ROOTS` / path-mapping reference; no secret values |
| Approving owner | Name and role |
| Approval date | ISO-8601 date |
| Expiry / review date | ISO-8601 date or policy reference |
| Exception decisions | Unmapped, duplicate, or legacy-path decisions |

## Preflight checklist

- [ ] Source root is accessible through a read-only server mount.
- [ ] The root and any Windows-to-server mapping are configured only on the
      server; no path is sent to a browser client.
- [ ] A sample of filenames resolves to intended physical EOAT identities
      without inference.
- [ ] Unsupported files and ambiguous associations are recorded as exceptions.
- [ ] The controlled media dry-run report identifies the manifest above.
- [ ] The approving owner has explicitly authorized the scope.

Until every required field and checklist item is satisfied, classify the media
source as **Not located** or **Located but not yet approved** and leave the
browser delivery policy fail-closed.
