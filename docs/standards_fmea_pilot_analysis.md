# Standards, FMEA, Pilot, and Engineering Analysis

Phase 10 adds evidence-based analysis helpers. The app surfaces standards gaps, FMEA draft suggestions, pilot evidence packets, and Press View rollups, but it does not turn suggestions into final engineering conclusions.

## Standards Compliance

Core module: `core/standards_compliance.py`

Each physical audit receives category results with:

- `status`: `compliant`, `warning`, `fail`, `not applicable`, or `unknown`
- `score`
- `reason`
- `recommended_action`
- `related_fields`

Scored categories include:

- EOAT classification complete
- Tooling details complete
- Pneumatic routing condition
- Sensor standard/documentation
- Quick disconnect standard
- Cable management
- Mechanical mounting
- Safety concerns
- Documentation completeness
- PM readiness
- BOM/spare parts readiness
- Photo evidence readiness

Unknown values are scored differently from verified values. Valid N/A categories are excluded from score math when the category does not physically apply.

## FMEA Suggestions

Core module: `core/fmea_suggestions.py`

Suggestions can come from:

- Known issues
- Drop/mis-pick history
- Maintenance and condition fields
- Issue Log rows
- Notes and tags
- Open items
- Validation findings
- Photo evidence gaps
- Standards compliance failures

FMEA suggestions are drafts. The user must review/edit severity, frequency, and detectability before accepting suggestions into `FMEA Draft`.

Available actions:

- Accept Selected
- Edit Before Accepting
- Reject Selected
- Export Draft

Accepted suggestions are written as `Draft - Review` rows with workbook backup and activity logging.

## Pilot Evidence Packets

Core module: `core/pilot_evidence_packets.py`

Packets include:

- Machine/press
- Audit ID
- EOAT type
- Known issues
- Failure modes for review
- Standards gaps
- Downtime/scrap/cycle-time context when available
- Photo/evidence coverage
- Open items
- Expected improvement area
- Implementation difficulty
- Risks
- Recommended next action

Packets are Markdown-first and explicitly avoid claiming pilot success, ROI, downtime reduction, scrap reduction, or final engineering approval.

## Press View Rollups

Press View now includes analysis-side rollups:

- Average compliance score
- Worst compliance category
- Open standards issues
- Pilot candidate relevance through the existing pilot flags

These rollups are summaries for review, not approval decisions.
