# Index Reference

Live MySQL inspection reported 195 index definitions (including primary/unique indexes exposed by the dialect inspector).

Explicit search/relationship indexes cover EOAT legacy ID/display name; machine number/area; robot number; tool/mold numbers; part name/family; all compatibility pairs; installation time/removal state; Fit Check entities/time; audit entities/date; document checksum/number/targets; history and audit timelines; change-feed cursors; and import diagnostics.

Indexes should be refined from measured API queries; the first revision avoids indexing every descriptive field.

