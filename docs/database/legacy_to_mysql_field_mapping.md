# Legacy-to-MySQL Field Mapping

Status: complete for all active Phase A sources. `Review = Yes` means the value is preserved in `import_rows.raw_values_json`/`audit_records.details_json` but is not promoted to authoritative normalized data until the stated ambiguity is resolved.

## EOAT_Master_Tracker.xlsx - EOAT Inventory

| Legacy field | Meaning | MySQL table | MySQL field | Conversion rule | Review |
|---|---|---|---|---|---|
| Audit ID | Source audit identity | audit_records | audit_identifier | Trim; required unique; preserve source row | No |
| Audit Date | Audit occurrence date | audit_records | audit_date | Parse Excel date as UTC start-of-day when time absent | Yes - timezone convention |
| Auditor | Human performer | users / audit_records | display_name / performed_by_user_id | Match/create external-import actor only with approved identity rule | Yes |
| Plant/Area | Workbook location label | plants, areas, machines | plant_code/area_code, plant_id/area_id | Map Plant 4 and Cleanroom through approved crosswalk | Yes |
| Press/Machine # | Machine business number | machines, audit_records | machine_number, machine_id | Accept one canonical numeric token; qualifiers are issues | Yes for noncanonical values |
| Tool # | Tool/mold identifier | tools, audit_records | business_identifier/tool_number, tool_id | Trim as text; do not coerce to number | No |
| EOAT Assembly ID | EOAT business ID | eoats, audit_records | business_identifier, eoat_id | Preserve exact ID; required | No |
| Robot Type | Legacy robot make/model text | robots | manufacturer/model candidates | Normalize via Robot_Info; retain original | Yes |
| Robot Model/Controller | Robot controller/model | robots | model/controller_model | Split only with approved vocabulary | Yes |
| Part Family | Part family label | parts | part_family | Stage as candidate; part_number absent | Yes |
| Part Name/Description | Part description | parts | part_name | Stage as candidate; do not use Tool # as part_number | Yes |
| Cleanroom/Non-Cleanroom | Environmental classification | cleanroom_classifications / eoats | code / cleanroom_classification_id | Map Cleanroom, Whiteroom, Unknown through lookup | Yes - vocabulary |
| EOAT Type | EOAT category | eoat_types / eoats | code / eoat_type_id | Normalize to lookup; preserve original | Yes - vocabulary |
| EOAT Moves | Pick/move behavior | audit_records | details_json.eoat_moves | Preserve as audit evidence; future operational rule | Yes |
| Connection Type | Interface category | connection_types / eoats | code / connection_type_id | Normalize lookup | Yes - vocabulary |
| Number of Parts Picked | Pick count | eoats | number_of_parts_picked | Integer >= 0; N/A/unknown -> null | No |
| # of Cylinders | Cylinder count | audit_records | details_json.cylinder_count | Integer >= 0; retain for future component/BOM model | Yes |
| Cylinder Type | Cylinder description | audit_records | details_json.cylinder_type | Preserve text | Yes |
| # of Grippers | Gripper count | eoats | number_of_grippers | Integer >= 0; N/A -> null | No |
| Gripper Type | Gripper category | audit_records | details_json.gripper_type | Preserve; candidate future component lookup | Yes |
| Gripper Model | Gripper model | audit_records | details_json.gripper_model | Preserve | Yes |
| # of Cups | Vacuum-cup count | eoats | number_of_vacuum_cups | Integer >= 0; N/A -> null | No |
| Cup Type/Material | Cup material/type | eoats | cup_material | Trim; preserve original vocabulary | Yes - split type/material later |
| Cup Diameter/Size | Cup size | audit_records | details_json.cup_diameter_size | Preserve text with source unit | Yes |
| Vacuum Generator Type | Generator category | audit_records | details_json.vacuum_generator_type | Preserve | Yes |
| Air Circuit Architecture | Circuit arrangement | audit_records | details_json.air_circuit_architecture | Preserve; future normalized circuit tables | Yes |
| EOAT Vacuum Circuits | EOAT vacuum circuit count | audit_records | details_json.eoat_vacuum_circuits | Integer >= 0 or null | Yes |
| EOAT Pressure Circuits | EOAT pressure circuit count | audit_records | details_json.eoat_pressure_circuits | Integer >= 0 or null | Yes |
| EOAT Interchangeable Circuits | Interchangeable circuit count | audit_records | details_json.eoat_interchangeable_circuits | Integer >= 0 or null | Yes |
| External Vacuum Circuits | Robot/external vacuum count | audit_records | details_json.external_vacuum_circuits | Integer >= 0 or null; reconcile Robot_Info | Yes |
| External Pressure Circuits | Robot/external pressure count | audit_records | details_json.external_pressure_circuits | Integer >= 0 or null; reconcile Robot_Info | Yes |
| External Interchangeable Circuits | Robot/external interchangeable count | audit_records | details_json.external_interchangeable_circuits | Integer >= 0 or null; reconcile Robot_Info | Yes |
| Gripper Size | Gripper dimension | audit_records | details_json.gripper_size | Preserve with source unit | Yes |
| Sensors Present? | Any sensors present | eoats | sensors_present | Explicit yes/no mapping; unknown -> null | No |
| Sensor Type | Sensor category | audit_records | details_json.sensor_type | Preserve; future component model | Yes |
| Sensor Brand/Model | Sensor manufacturer/model | audit_records | details_json.sensor_brand_model | Preserve | Yes |
| Vacuum Confirmation Present? | Vacuum confirmation | eoats | vacuum_confirmation_sensor_present | Explicit boolean mapping | No |
| Part-Present Detection Present? | Part-present sensor | eoats | part_present_sensor_present | Explicit boolean mapping | No |
| Electrical/Wiring Present? | Wiring evidence | audit_records | details_json.electrical_wiring_present | Explicit boolean/unknown | Yes |
| Quick Disconnects Present? | Quick disconnect evidence | eoats | quick_disconnect_present | Explicit boolean/unknown | No |
| Pneumatic Quick Disconnect Type | Pneumatic interface | audit_records | details_json.pneumatic_quick_disconnect_type | Preserve; cross-check connection type | Yes |
| Electrical Quick Disconnect Type | Electrical interface | audit_records | details_json.electrical_quick_disconnect_type | Preserve | Yes |
| Tubing Condition | Inspection finding | audit_records | details_json.tubing_condition | Preserve categorical source value | Yes - vocabulary |
| Tubing Routing Notes | Inspection notes | audit_records | details_json.tubing_routing_notes | Preserve text | No |
| Cable Management Condition | Inspection finding | audit_records | details_json.cable_management_condition | Preserve categorical source value | Yes - vocabulary |
| Mounting Hardware Condition | Inspection finding | audit_records | details_json.mounting_hardware_condition | Preserve categorical source value | Yes - vocabulary |
| EOAT Alignment Condition | Inspection finding | audit_records | details_json.eoat_alignment_condition | Preserve categorical source value | Yes - vocabulary |
| Fastener/Locking Hardware Present? | Hardware evidence | audit_records | details_json.fastener_locking_hardware_present | Explicit boolean/unknown | Yes |
| Estimated EOAT Weight | Approximate weight | eoats | weight_kg | Parse only when unit is known/convertible to kg | Yes - source units |
| Known Issues | Free-text findings | audit_records | details_json.known_issues | Preserve; future audit_findings extraction | Yes |
| Drop/Mis-Pick History | Performance evidence | audit_records | details_json.drop_mispick_history | Preserve; do not invent event counts | Yes |
| Maintenance Frequency | PM hint | audit_records | details_json.maintenance_frequency | Preserve pending PM template mapping | Yes |
| Cycle Time Concern? | Risk flag | audit_records | details_json.cycle_time_concern | Explicit boolean/unknown | Yes |
| Scrap/Quality Concern? | Quality flag | audit_records | details_json.scrap_quality_concern | Explicit boolean/unknown | Yes |
| Changeover Difficulty | Changeover assessment | audit_records | details_json.changeover_difficulty | Preserve categorical/text value | Yes |
| Spare Parts Identified? | Documentation/parts flag | audit_records | details_json.spare_parts_identified | Explicit boolean/unknown | Yes |
| Drawing/CAD Available? | Documentation flag | audit_records | details_json.drawing_cad_available | Explicit boolean/unknown; document row requires path | Yes |
| BOM Available? | Documentation flag | audit_records | details_json.bom_available | Explicit boolean/unknown; document row requires path | Yes |
| Process Binder Complete? | Documentation flag | audit_records | details_json.process_binder_complete | Explicit boolean/unknown | Yes |
| Photos Taken? | Photo-evidence flag | audit_records | details_json.photos_taken | Explicit boolean/unknown; reconcile Photo Index | Yes |
| Photo Folder/Link | Legacy photo path | documents | storage_path | Normalize project-relative path; retain raw path | Yes if missing/unavailable |
| Status | Audit/asset status text | asset_statuses / audit_records | code / status_id | Context-specific lookup; do not automatically make asset status equal audit status | Yes |
| Priority | Audit follow-up priority | audit_records | details_json.priority | Preserve lookup candidate | Yes |
| Pilot Candidate? | Optimization flag | audit_records | details_json.pilot_candidate | Explicit boolean/unknown | Yes |
| Follow-Up Needed | Follow-up flag/text | audit_records | details_json.follow_up_needed | Preserve; future finding/action relationship | Yes |
| Notes | General audit notes | audit_records | notes | Preserve verbatim | No |
| Entry Type | Audited vs compatible evidence | audit_records / compatibility tables | details_json.entry_type / source | `Audited` creates audit evidence; `Compatible` creates relationship evidence only | No |
| Source Audit ID | Provenance link | audit_records | details_json.source_audit_id | Resolve to another audit_identifier when present | Yes if unresolved |
| Compatibility Source | Evidence origin | compatibility_sources / compatibility tables | code / verification_source_id | Normalize lookup; preserve original | No |
| Manual Completion Override | Administrative override | audit_records | details_json.manual_completion_override | Explicit boolean | No |
| Manual Completion Override Timestamp | Override time | audit_records | details_json.manual_completion_override_timestamp | Parse timezone-aware UTC | Yes if timezone absent |
| Manual Completion Override User | Override actor | users / audit_records | username/display_name / details_json | Resolve only through approved identity crosswalk | Yes |
| Ignored Empty Fields At Override | Override evidence | audit_records | details_json.ignored_empty_fields_at_override | Preserve list/text; do not discard | No |
| Audit Context | Context snapshot | audit_records | details_json.audit_context | Preserve structured/text source | No |
| Physical Audit Verified | Verification flag | audit_records | details_json.physical_audit_verified | Explicit boolean/unknown | No |
| Compatibility Confidence | Evidence/confidence label | compatibility tables | reason/conditions plus import provenance | Map known source-specific values; N/A -> unknown | Yes - not a numeric confidence |

Every EOAT Inventory row is also represented by `import_rows` with `source_sheet`, `source_row_number`, `source_identifier`, `raw_values_json`, `normalized_values_json`, and validation status.

## EOAT_Master_Tracker.xlsx - Photo Index

| Legacy field | MySQL table.field | Conversion | Review |
|---|---|---|---|
| Photo ID | documents.document_uuid / import_rows.source_identifier | Preserve Photo ID as legacy identifier; generate UUID separately | No |
| Date Taken | photos.captured_at | Parse UTC/timezone rule | Yes if date-only |
| Plant/Area | document_links + import provenance | Resolve related assets; preserve context | Yes |
| Press/Machine # | document_links.entity_id (MACHINE) | Resolve plant + canonical machine number | Yes if ambiguous |
| EOAT Area Shown | photos.photo_view_type | Normalize lookup-like code | Yes - vocabulary |
| Photo Filename | documents.file_name | Preserve filename | No |
| Folder Path | documents.storage_path | Legacy fallback path; prefer Stored Relative Path | Yes if fallback used |
| Description | documents.description / photos.caption | Preserve | No |
| Related Audit ID | document_links.entity_id (AUDIT_RECORD) | Resolve audit_identifier | Yes if unresolved |
| Related Issue ID | document_links.entity_id (future issue) | Preserve in import provenance until issue schema exists | Yes |
| Notes | photos.caption / documents.description | Preserve | No |
| Tool # | document_links.entity_id (TOOL) | Resolve tool business ID | Yes if missing |
| EOAT Assembly ID | document_links.entity_id (EOAT) | Resolve EOAT business ID | Yes if missing |
| Linked Audit Field | document_links.relationship_type | Normalize to `AUDIT_FIELD_EVIDENCE`; retain field name | No |
| Part Name | import_rows.normalized_values_json | Resolve only after part-number crosswalk | Yes |
| Photo Type | photos.photo_view_type | Preferred normalized source | Yes - vocabulary |
| Original Filename | import_rows.raw_values_json | Preserve provenance | No |
| Stored Filename | documents.file_name | Preferred file name | No |
| Stored Relative Path | documents.storage_path | Project-relative controlled path; validate existence | No when valid |
| Imported At | documents.created_at | Parse timezone-aware timestamp | Yes if timezone absent |

## Robot_Info.xlsx

| Legacy field | MySQL table.field | Conversion | Review |
|---|---|---|---|
| Plant/Area | plants/areas + robots.plant_id/area_id | Approved location crosswalk | Yes |
| Machine Number | machine_robot_assignments.machine_id | Resolve canonical machine | No |
| Robot Type | robots.manufacturer/model | Split through approved vocabulary | Yes |
| Robot Identifier | robots.robot_number | Required unique within plant | Yes - currently blank |
| Robot Vacuum Circuits | import_rows.normalized_values_json | Preserve for future robot utility model | Yes |
| Robot Pressure Circuits | import_rows.normalized_values_json | Preserve for future robot utility model | Yes |
| Robot Interchangeable Circuits | import_rows.normalized_values_json | Preserve for future robot utility model | Yes |
| Last Audit ID | machine_robot_assignments provenance | Resolve audit record | Yes if unresolved |
| Last Updated | robots.updated_at | Parse UTC | No |
| Notes | robots.notes | Preserve | No |
| Robot Notes | robots.notes | Concatenate with labeled provenance, never overwrite Notes | No |

## master_press_list.xlsx - Machine Specifications

| Legacy field(s) | MySQL target | Conversion / disposition | Review |
|---|---|---|---|
| Machine Number | machines.machine_number | Required text business number; unique within plant | No |
| U.S. Tons | machines.press_capacity_tons | Decimal tons > 0 | No |
| Press Brand | machines.manufacturer | Trim | No |
| Model # | machines.model | Trim | No |
| Year Mfg., Year Mfg | machines.installation_date/import provenance | Store year only after approved date convention; preserve both columns | Yes |
| Serial Number, Serial # | machines.serial_number/import provenance | Reconcile duplicate source columns | Yes |
| Controller Type | machines.controller_type | Trim | No |
| Robot/Picker Brand | robots.manufacturer | Resolve with machine assignment | Yes if robot ID absent |
| Robot/Picker Model # | robots.model | Preserve | Yes if robot ID absent |
| Robot/Picker Serial # | robots.serial_number and candidate robot_number | Use serial only as business ID if approved | Yes |
| Robot/Picker Mfg. Date | robots/import provenance | Parse date | Yes |
| Vacuum Circuits, Compressed Air Circuits | import provenance | Future robot/machine utility model | Yes |
| Full Servo | import provenance | Explicit boolean normalization | Yes |
| Number of Mold Heater Zones; Mold Heater Zones Max. Amperage; Injection Pressure PSI; Injection Capacity (oz); Clamp Maximium Stroke; Hydraulic Oil Capacity Gallons; Injection Unit; Injection pressure psi; Injection Capacity (ounces); Hydraulic Oil Capacity in Gallons; Screw Diamter (mm); Injection Capacity (in3); Injection Stroke (in); Injection Rate (in3/sec); Injection Speed (in/sec); Intensifaction Ratio; Recovery Rate (oz./sec.); Platen Size Horizontal; Platen Size Vertical; Tie Bar Space Horizontal; Tie Bar Spacing Vertical; Mold Thickness Minimium; Clamp Maximum Stroke; Mold Thickness Maximium; Ejector Maximium Stroke; Ejector Pattern 4x16; Ejector Pattern 7; Ejector Pattern Center; Core 1; Core 2; Core 3; Valve Gates Hydraulic or Pneumatic; Cavity Pressure Kistler/RJG Capability/QTY; # of TCU's; EDART UNIT PRESS SIDE | import_rows.raw_values_json / future machine specification tables | Preserve every value and header exactly; Phase A has no safe normalized destination | Yes |

## press_capacity.xlsx - P4 Capacity

| Legacy field(s) | MySQL target | Conversion / disposition | Review |
|---|---|---|---|
| Machine No. | machines.machine_number and tool_machine_compatibility.machine_id | Split comma-separated lists only with explicit validation | Yes for multi-machine cells |
| NGW Part Number | parts.part_number candidate / tools relationship evidence | Do not assume equivalence to Tool # without crosswalk | Yes |
| NGW Part Description | parts.part_name candidate | Preserve | Yes pending part-number crosswalk |
| Bill-to | parts.customer candidate | Preserve | Yes |
| Cycle Time (S) | import provenance / future process metrics | Numeric seconds; formula results are not compatibility authority | Yes |
| Cavitation | tools.cavity_count candidate | Integer >= 0; reconcile master/tool source | Yes |
| 2026 F1 Forecast QTY YTD; 2026 F1 MTD; 2025 Forecast Qty YTD; 2025 Forecast Qty MTD; 2024 Forecast Qty YTD; 2024 Forecast Qty MTD; Hours per year; Hours per month; Max parts per month; Parts per Day; Forecasted Capacity; Available Capacity; Days per Month; Hours Allocated per month; Hours per week; Commited Hours per Year; blank trailing column | import_rows.raw_values_json / future analytics tables | Preserve values/formulas; exclude formula errors from normalized authority | Yes |

## annotations.sqlite

| Legacy table/field group | MySQL target | Rule | Review |
|---|---|---|---|
| notes.* | Future notes table (not Phase A) | Preserve UUIDs, markdown, state, dates, archive timestamp | Phase B/application conversion |
| tags.* | Future tags table | Preserve IDs, names, colors, default/archive flags | Phase B |
| annotation_targets.* | Future annotation_targets plus normalized entity links | Preserve workbook/sheet/header/cell/object references during transition | Yes - target resolution |
| tag_assignments.*, note_targets.*, note_tags.* | Future relationship tables | Preserve all relationship IDs and timestamps | Phase B |
| attachments.* | documents/document_links plus future note link | Preserve path metadata; validate files | Yes |
| annotation_suggestion_ignores.*, open_item_states.* | Future workflow tables | Preserve values and fingerprints | Phase B |
| schema_migrations.* | No direct import | Record source schema in import batch; Alembic remains MySQL schema authority | No |

## Generated/current-view sheet disposition

`Audit by Press` is derived from EOAT Inventory and will not be imported as an independent authority. It is used only for output comparison. Placeholder-only sheets remain mapped to future domain modules and their raw rows may be preserved in import batches, but they do not block the Phase A EOAT foundation.

