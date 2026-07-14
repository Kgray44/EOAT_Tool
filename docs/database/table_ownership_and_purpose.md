# Table Ownership and Purpose

| Owner boundary | Tables | Write policy |
|---|---|---|
| Reference-data service | Lookup tables | Administrator-controlled, audited |
| Asset service | plants, areas, storage_locations, eoats, machines, robots, tools, parts, relationship and compatibility tables | Optimistic concurrency; archive rather than normal hard delete |
| Installation service | eoat_installations, eoat_storage_assignments | Transactional move/storage operations only |
| Fit Check service | fit_check_records | Append historical result; never rewrite old outcomes |
| Audit service | audit_records | Preserve original source row and details; later evolve to template/response tables |
| Document service | documents, photos, document_links | Metadata/path authority; binary files remain on controlled storage |
| Identity/security service | users, roles, user_roles, application_instances, authentication_sessions, external_group_role_mappings, authentication_audit_events | Server-only Settings authentication, authorization, audit and application attribution boundary |
| History/audit service | entity_history_events, change_audit_log | Append-only under normal application operation |
| Synchronization service | change_feed | Append-only server cursor after successful business transaction |
| Migration service | import_batches, import_rows, import_issues | Administrator-only, batch traceability and review |
| Configuration service | system_settings, system_metadata | Non-secret centralized settings/metadata |
| Alembic | alembic_version | Migration tooling only |

Expected initial record volumes are small (tens to low thousands) except history, audit, change-feed, document and import-row tables, which are expected to grow append-only and require retention/backup monitoring.
