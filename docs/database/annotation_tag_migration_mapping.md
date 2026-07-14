# Annotation and Tag Migration Mapping

Source: `EOAT_Standardization_Project/project_data/annotations.sqlite`, schema version 2. The importer opens it with SQLite `query_only`, compares SHA-256 before/after, and never initializes or migrates the source.

| Legacy table/field | MySQL target | Notes |
|---|---|---|
| `tags.id` | `tags.source_record_identifier` | Exact source ID retained; generated `tag_code` is unique |
| `tags.name` | `tags.display_name` | Exact text preserved |
| color/description/default/archive/timestamps | matching tag columns | Archive becomes `is_active=false` plus timestamp |
| `annotation_targets.id` | `annotation_targets.target_uuid` and source identifier | Stable UI target identity retained |
| target type/label/audit/machine/field/sheet/header/workbook/cell/object | matching normalized target columns | Generic target table is retained because all 52 source targets are audit-field targets and not every target is a verified MySQL asset FK |
| `tag_assignments` | `entity_tags` | Entity type `annotation_target`; comment/timestamps/source ID retained; generated unique active key prevents duplicates |
| `notes` | `annotations` | Subject/body/importance/status/collection/type/follow-up/archive/timestamps retained; body is copied exactly |
| `note_targets` | `annotation_target_links` | Strict FKs to annotation and target |
| `note_tags` | `entity_tags` with entity type `annotation` | None existed in the current source |
| `attachments` | controlled document metadata | None existed; importer refuses nonempty attachments pending an approved file mapping |
| suggestion ignores/open-item state | not migrated | Both current tables contained zero rows and remain legacy comparison data only |

Tradeoff: polymorphic asset tags use validated `entity_type`/`entity_id`, while legacy audit-field targets receive a strict `annotation_target_id` FK. This preserves actual behavior without fabricating asset relationships.
