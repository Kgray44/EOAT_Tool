from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from .atlas_models import AtlasDataBundle, WarningItem

ENTRY_TYPE_LABELS = {
    "app_help": "App Help",
    "eoat_standard": "EOAT Standard",
    "compatibility_rule": "Compatibility Rule",
    "data_dictionary": "Data Dictionary",
    "troubleshooting": "Troubleshooting",
    "report_guide": "Report Guide",
    "pm_inspection": "PM / Inspection",
    "source_document": "Source Document",
}

BANNED_GENERIC_PHRASES = (
    "Use this when this Atlas area matches the question",
    "Results are read-only Atlas interpretations of cached workbook, photo, standards, and warning data",
    "Open related profile pages, inspect warning cards",
)


@dataclass(frozen=True)
class LibrarySource:
    source_type: str = "Atlas internal reference"
    document_name: str = "Atlas internal reference"
    section: str = ""
    file_path: str = ""
    modified: float = 0.0

    @property
    def file_exists(self) -> bool:
        return bool(self.file_path) and Path(self.file_path).exists()

    @property
    def file_label(self) -> str:
        return self.file_path or "Not applicable"

    @property
    def modified_label(self) -> str:
        if not self.modified:
            return "Not applicable"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.modified))

    @property
    def section_label(self) -> str:
        return self.section or "Not applicable"


@dataclass(frozen=True)
class InformationSection:
    title: str
    items: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(self.items)


@dataclass(frozen=True)
class LibraryExample:
    title: str
    inputs: tuple[str, ...] = ()
    logic: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        parts: list[str] = [self.title]
        if self.inputs:
            parts.extend(("Input:", *self.inputs))
        if self.logic:
            parts.extend(("Logic:", *self.logic))
        if self.outputs:
            parts.extend(("Output:", *self.outputs))
        return "\n".join(parts)


@dataclass(frozen=True)
class InformationLibraryEntry:
    entry_id: str
    entry_type: str
    category: str
    title: str
    summary: str
    key_takeaway: str
    sections: tuple[InformationSection, ...] = ()
    tags: tuple[str, ...] = ()
    related_fields: tuple[str, ...] = ()
    related_pages: tuple[str, ...] = ()
    related_references: tuple[str, ...] = ()
    examples: tuple[LibraryExample, ...] = ()
    warnings: tuple[str, ...] = ()
    source: LibrarySource = field(default_factory=LibrarySource)
    tree_path: tuple[str, ...] = ()
    indexed_at: float = 0.0

    @property
    def body(self) -> str:
        pieces: list[str] = []
        for section in self.sections:
            pieces.append(f"{section.title}:")
            pieces.extend(section.items)
        for example in self.examples:
            pieces.append(example.text)
        if self.warnings:
            pieces.append("Warnings / Common Mistakes:")
            pieces.extend(self.warnings)
        if self.related_fields:
            pieces.append("Related Atlas Fields:")
            pieces.extend(self.related_fields)
        if self.related_pages:
            pieces.append("Related Atlas Pages:")
            pieces.extend(self.related_pages)
        if self.related_references:
            pieces.append("Related References:")
            pieces.extend(self.related_references)
        pieces.append(f"Source document: {self.source.document_name}")
        pieces.append(f"Source type: {self.source.source_type}")
        return "\n".join(piece for piece in pieces if piece)

    @property
    def path(self) -> str:
        return self.source.file_path

    @property
    def source_section(self) -> str:
        return self.source.section

    @property
    def modified(self) -> float:
        return self.source.modified

    @property
    def related(self) -> tuple[str, ...]:
        return (*self.related_references, *self.related_pages)


def build_information_entries(bundle: AtlasDataBundle | None) -> list[InformationLibraryEntry]:
    if bundle is None:
        return []
    entries = [_resolve_entry_source(entry, bundle) for entry in _seed_entries()]
    entries.extend(_source_document_entries(bundle))
    entries.extend(_warning_entries(bundle))
    now = time.time()
    return [
        replace(entry, entry_id=f"{index:04d}-{entry.entry_id}", indexed_at=now)
        for index, entry in enumerate(entries, start=1)
    ]


def seed_information_entries() -> list[InformationLibraryEntry]:
    now = time.time()
    return [
        replace(entry, entry_id=f"{index:04d}-{entry.entry_id}", indexed_at=now)
        for index, entry in enumerate(_seed_entries(), start=1)
    ]


def information_score(entry: InformationLibraryEntry, query: str) -> int:
    terms = []
    if query.strip():
        terms.append(query.strip().casefold())
    terms.extend(term.casefold() for term in query.split() if term.strip())
    if not terms:
        return 1
    title = entry.title.casefold()
    summary = entry.summary.casefold()
    haystack = _entry_search_text(entry)
    score = 0
    for term in terms:
        if term in haystack:
            score += 5 if term in title else (3 if term in summary else 1)
    return score


def information_snippet(entry: InformationLibraryEntry, query: str, *, limit: int = 120) -> str:
    terms = []
    if query.strip():
        terms.append(query.strip().casefold())
    terms.extend(term.casefold() for term in query.split() if term.strip())
    text = " ".join([entry.summary, entry.key_takeaway, entry.body])
    compact = " ".join(text.split())
    if not compact:
        return ""
    lower = compact.casefold()
    index = -1
    term = ""
    for candidate in terms:
        index = lower.find(candidate)
        if index >= 0:
            term = compact[index : index + len(candidate)]
            break
    if index < 0:
        return _short(compact, limit)
    start = max(0, index - 45)
    end = min(len(compact), index + len(term) + 65)
    snippet = compact[start:end].strip()
    if start:
        snippet = f"... {snippet}"
    if end < len(compact):
        snippet = f"{snippet} ..."
    if term:
        snippet = snippet.replace(term, f"[{term}]", 1)
    return _short(snippet, limit)


def validate_information_library(entries: list[InformationLibraryEntry]) -> list[str]:
    errors: list[str] = []
    if not entries:
        return ["Information Library has no entries."]

    bodies = [_normalized_body(entry) for entry in entries]
    duplicate_count = sum(count for count in Counter(bodies).values() if count > 1)
    if duplicate_count / len(entries) > 0.20:
        errors.append("More than 20% of Information Library entries have duplicated body text.")

    for entry in entries:
        text = f"{entry.title}\n{entry.summary}\n{entry.key_takeaway}\n{entry.body}"
        for phrase in BANNED_GENERIC_PHRASES:
            if phrase.casefold() in text.casefold():
                errors.append(f"{entry.title}: banned generic phrase found: {phrase}")
        if entry.entry_type != "app_help" and len([section for section in entry.sections if section.items]) < 3:
            errors.append(f"{entry.title}: non-app-help entries must have at least 3 meaningful sections.")
        section_titles = {section.title.casefold() for section in entry.sections}
        if entry.entry_type == "compatibility_rule":
            if "inputs used" not in section_titles or "decision logic" not in section_titles:
                errors.append(f"{entry.title}: compatibility rules require Inputs Used and Decision Logic.")
        if entry.entry_type == "troubleshooting":
            required = {"symptom", "likely causes", "checks to run", "fix steps"}
            missing = required - section_titles
            if missing:
                errors.append(f"{entry.title}: troubleshooting entry missing {', '.join(sorted(missing))}.")
        if entry.entry_type == "data_dictionary":
            required = {"definition", "source of truth", "used by", "repair action"}
            missing = required - section_titles
            if missing:
                errors.append(f"{entry.title}: data dictionary entry missing {', '.join(sorted(missing))}.")
        metadata_values = [
            entry.source.source_type,
            entry.source.document_name,
            entry.source.section_label,
            entry.source.file_label,
            entry.source.modified_label,
        ]
        if any(value.strip() == "-" for value in metadata_values):
            errors.append(f"{entry.title}: source metadata contains a raw dash.")
    return errors


def entry_type_label(entry_type: str) -> str:
    return ENTRY_TYPE_LABELS.get(entry_type, entry_type.replace("_", " ").title())


def _entry_search_text(entry: InformationLibraryEntry) -> str:
    examples = " ".join(example.text for example in entry.examples)
    source = " ".join(
        [
            entry.source.source_type,
            entry.source.document_name,
            entry.source.section,
            entry.source.file_path,
        ]
    )
    return " ".join(
        [
            entry.title,
            entry.summary,
            entry.key_takeaway,
            entry.body,
            source,
            " ".join(entry.tags),
            " ".join(entry.related_fields),
            " ".join(entry.related_pages),
            " ".join(entry.related_references),
            " ".join(entry.tree_path),
            examples,
        ]
    ).casefold()


def _normalized_body(entry: InformationLibraryEntry) -> str:
    return " ".join(entry.body.casefold().split())


def _short(value: str, limit: int = 120) -> str:
    value = str(value or "").strip()
    return value if len(value) <= limit else f"{value[: limit - 3].rstrip()}..."


def _slug(*parts: str) -> str:
    raw = "|".join(str(part) for part in parts if str(part).strip())
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:150] or "library-entry"


def _section(title: str, *items: str) -> InformationSection:
    return InformationSection(title=title, items=tuple(item for item in items if item))


def _example(title: str, *, inputs=(), logic=(), outputs=()) -> LibraryExample:
    return LibraryExample(title=title, inputs=tuple(inputs), logic=tuple(logic), outputs=tuple(outputs))


def _source(document_name: str, *, section: str = "", source_type: str = "") -> LibrarySource:
    resolved_type = source_type or document_name or "Atlas internal reference"
    return LibrarySource(source_type=resolved_type, document_name=document_name or resolved_type, section=section)


def _entry(
    entry_type: str,
    title: str,
    summary: str,
    key_takeaway: str,
    sections: tuple[InformationSection, ...],
    *,
    category: str = "",
    tags: tuple[str, ...] = (),
    related_fields: tuple[str, ...] = (),
    related_pages: tuple[str, ...] = (),
    related_references: tuple[str, ...] = (),
    examples: tuple[LibraryExample, ...] = (),
    warnings: tuple[str, ...] = (),
    source: LibrarySource | None = None,
    tree_path: tuple[str, ...] = (),
) -> InformationLibraryEntry:
    category = category or entry_type_label(entry_type)
    return InformationLibraryEntry(
        entry_id=_slug(entry_type, title),
        entry_type=entry_type,
        category=category,
        title=title,
        summary=summary,
        key_takeaway=key_takeaway,
        sections=sections,
        tags=tags,
        related_fields=related_fields,
        related_pages=related_pages,
        related_references=related_references,
        examples=examples,
        warnings=warnings,
        source=source or _source("Atlas internal reference", source_type="Atlas internal reference"),
        tree_path=tree_path or (category, title),
    )


def _seed_entries() -> list[InformationLibraryEntry]:
    entries: list[InformationLibraryEntry] = []
    entries.extend(_app_help_entries())
    entries.extend(_standard_entries())
    entries.extend(_compatibility_entries())
    entries.extend(_data_dictionary_entries())
    entries.extend(_troubleshooting_entries())
    entries.extend(_report_guide_entries())
    entries.extend(_pm_inspection_entries())
    entries.extend(_static_source_document_entries())
    return entries


def _app_help_entries() -> list[InformationLibraryEntry]:
    source = _source("Atlas generated help", source_type="Atlas generated help")

    def app(
        title: str,
        summary: str,
        takeaway: str,
        use_cases: tuple[str, ...],
        dependencies: tuple[str, ...],
        mistakes: tuple[str, ...],
        troubleshooting: tuple[str, ...],
        related: tuple[str, ...],
        tags: tuple[str, ...],
    ) -> InformationLibraryEntry:
        return _entry(
            "app_help",
            title,
            summary,
            takeaway,
            (
                _section("Primary Use Cases", *use_cases),
                _section("Data Dependencies", *dependencies),
                _section("Common Mistakes", *mistakes),
                _section("Troubleshooting", *troubleshooting),
                _section("Related Pages", *related),
            ),
            category="Atlas App Help",
            tags=tags,
            related_pages=related,
            source=source,
            tree_path=("Atlas App Help", title),
        )

    return [
        app(
            "Home / Command Deck",
            "Start page for global lookup, source status, high-level metrics, and primary navigation.",
            "If the source chips are missing or stale, every downstream page can look incomplete.",
            ("Run a broad identifier search.", "Check source availability before trusting gaps.", "Jump to the major Atlas work areas."),
            ("EOAT Master Tracker", "Press Capacity Workbook", "Photo Folder Index", "Standards folder"),
            ("Treating dashboard metrics as live Excel values after a workbook changed.", "Ignoring missing source chips before troubleshooting a profile."),
            ("Use Refresh Data after source workbook changes.", "Open Settings / Diagnostics when load timing or source paths look wrong."),
            ("What Do I Need?", "Settings / Diagnostics", "Source workbook path is missing", "Audit Progress Report"),
            ("home", "source status", "metrics"),
        ),
        app(
            "What Do I Need?",
            "Recommendation page for turning a known tool, machine, EOAT, part, robot, or keyword into a ranked EOAT answer.",
            "The best result is only as good as the tool-machine and EOAT-tool relationships behind it.",
            ("Find the best EOAT for a known setup.", "Compare backup EOAT candidates.", "Launch profile, photo, tool, and machine context."),
            ("EOAT Master Tracker", "Press Capacity Workbook", "Robot Info when robot context is part of the decision"),
            ("Entering a part description when the workbook only carries a tool number.", "Skipping warnings because the top recommendation has a high score."),
            ("Search the exact Tool # if a keyword search is weak.", "Check Compatibility Confidence Levels when backup choices look close."),
            ("Compatibility Data Table", "EOAT Profiles", "Tool / Mold / Part", "Compatibility Confidence Levels"),
            ("recommendation", "search", "install"),
        ),
        app(
            "Changeover Packet Builder",
            "Builds a PDF setup/changeover packet for a selected machine, tool, and EOAT combination.",
            "A packet is a snapshot of the current Atlas cache; refresh first when source data just changed.",
            ("Create a setup handoff PDF.", "Include photos and QR payloads when enabled.", "Review compatibility warnings before export."),
            ("Selected machine", "Selected Tool #", "Selected EOAT Assembly ID", "Photo index for optional images"),
            ("Generating from stale cache after workbook edits.", "Treating a manual override as the same as confirmed compatibility."),
            ("Run compatibility review again after changing selections.", "Open the generated packet library if the PDF viewer is unavailable."),
            ("Compatibility Data Table", "Photos", "Changeover packet exports", "Manual override warning rules"),
            ("changeover packet", "setup packet", "pdf", "handoff"),
        ),
        app(
            "EOAT Profiles",
            "Profile page for one EOAT's identity, compatible tools and machines, readiness, photos, warnings, and technical context.",
            "Start with the header and readiness cards, then inspect source fields only when a warning points there.",
            ("Confirm what an EOAT supports.", "Review documentation and photo coverage.", "Open changeover packets or photos for a selected EOAT."),
            ("EOAT Assembly ID", "Tool # rows", "Machine compatibility rows", "Photo Folder Index"),
            ("Assuming a merged profile means all rows were physically audited.", "Ignoring compatible rows created from off-machine handling."),
            ("Search by normalized EOAT Assembly ID.", "Review EOAT-to-Tool Compatibility when tools are missing."),
            ("EOAT Assembly ID", "EOAT-to-Tool Compatibility", "Photo Coverage Status", "Compatibility Confidence Levels", "Documentation Requirements", "Photos do not preview"),
            ("eoat", "profile", "readiness"),
        ),
        app(
            "Machine Profiles",
            "Machine page for robot context, linked EOATs, linked tools, current EOAT notes, and machine-specific warnings.",
            "Missing EOATs usually means a relationship gap, not that the machine cannot run tooling.",
            ("Confirm which EOATs and tools are linked to a machine.", "Check robot type and controller context.", "Export a machine summary."),
            ("Press Capacity Workbook", "Robot Info", "EOAT Master Tracker machine rows"),
            ("Treating an empty EOAT list as a verified incompatibility.", "Comparing machine numbers without normalization."),
            ("Check Tool-to-Machine Compatibility first.", "Check Machine # and Robot Type field definitions."),
            ("Tool-to-Machine Compatibility", "Robot Type", "Machine #", "Press Capacity Workbook", "EOAT profile missing compatible machines"),
            ("machine", "robot", "compatibility"),
        ),
        app(
            "Tool / Mold / Part",
            "Lookup page for tool numbers, mold numbers, part descriptions, linked EOATs, and compatible machines.",
            "Tool # is the strongest key; free-text part search is helpful but less authoritative.",
            ("Find EOATs linked to a tool.", "Find machines from Press Capacity.", "Compare multiple tools in a family."),
            ("Tool # field", "Press Capacity Workbook", "EOAT Master Tracker tool rows"),
            ("Searching a display description when the source workbook stores a different part name.", "Forgetting that one tool can map to multiple machines."),
            ("Search the exact Tool #.", "Inspect Duplicate Compatibility Row Handling if counts look inflated."),
            ("Tool #", "Tool-to-Machine Compatibility", "EOAT-to-Tool Compatibility", "Tool search returns no results"),
            ("tool", "mold", "part"),
        ),
        app(
            "Compatibility Data Table",
            "Dense comparison table for EOAT, machine, tool, status, confidence, and warning relationships.",
            "Use the matrix to audit relationships; use profiles to answer one setup question quickly.",
            ("Sort and filter compatibility rows.", "Export compatibility data.", "Find duplicate or low-confidence relationships."),
            ("EOAT Master Tracker", "Press Capacity Workbook", "compatibility cache"),
            ("Reading a derived row as physical audit evidence.", "Exporting before refresh after source edits."),
            ("Filter by one identifier first.", "Open Compatibility Warning Rules when row status is unclear."),
            ("Tool-to-Machine Compatibility", "EOAT-to-Machine Compatibility", "Compatibility Export", "Duplicate Compatibility Row Handling"),
            ("matrix", "compatibility", "export"),
        ),
        app(
            "Analytics Dashboard",
            "Coverage view for machines, EOAT documentation, readiness, and cleanup planning.",
            "Maps are best for planning work, not confirming one setup.",
            ("Find low-coverage machines.", "Identify EOAT documentation gaps.", "Prioritize photo and standards cleanup."),
            ("Machine profile index", "EOAT documentation scores", "warning counts"),
            ("Using map color as a pass/fail install decision.", "Not checking the profile behind a low-score tile."),
            ("Open the affected profile from the tile.", "Run Documentation Gap Report for exportable cleanup work."),
            ("Documentation Gap Report", "Readiness Status", "Warning Severity", "Photo Coverage Status"),
            ("maps", "coverage", "readiness"),
        ),
        app(
            "Photos",
            "Photo library for EOAT folders, indexed image files, missing categories, and on-demand preview.",
            "Photo count is not the same as useful coverage; missing category chips show the real audit gap.",
            ("Open EOAT photo sets.", "Check missing required views.", "Use external folder access for original files."),
            ("Photo Folder Index", "EOAT Assembly ID", "supported image decoders"),
            ("Expecting HEIC/HEIF to preview without decoder support.", "Treating folder presence as complete coverage."),
            ("Open externally if preview decode fails.", "Review HEIC / HEIF images do not load for format issues."),
            ("Photo Coverage Status", "Photos do not preview", "HEIC / HEIF images do not load", "Documentation Requirements"),
            ("photos", "coverage", "preview"),
        ),
        app(
            "PM / Inspection",
            "Checklist guidance for weekly, monthly, pre-install, vacuum, tubing, sensor, hardware, and cable checks.",
            "PM entries should turn profile warnings into physical inspection actions.",
            ("Run repeatable EOAT inspections.", "Tie findings back to standards.", "Create checklist exports for offline use."),
            ("EOAT Preventive Maintenance Checklist", "EOAT profile warnings", "Photo coverage status"),
            ("Checking only visible wear and missing documentation cleanup.", "Skipping source update after a recurring finding."),
            ("Open the related standard for repeated findings.", "Export PM checklist when the inspection will happen away from Atlas."),
            ("Weekly EOAT Inspection", "Vacuum Cup Inspection", "Sensor Verification", "PM Checklist Export"),
            ("pm", "inspection", "maintenance"),
        ),
        app(
            "Standards & Work Instructions",
            "Read-only browser for standards and reference documents that Atlas can locate in the project.",
            "Standards explain what good documentation and EOAT condition should look like; they do not replace source workbook repair.",
            ("Open source standards.", "Confirm which standard supports a warning.", "Register likely standardization documents."),
            ("Standards folder", "EOAT Standard Design Guidelines", "source file paths"),
            ("Expecting Atlas to infer a missing standard from a filename alone.", "Ignoring the section name when a document has multiple topics."),
            ("Check Source Metadata for the file path.", "Use Settings / Diagnostics if the standards folder is missing."),
            ("EOAT Standard Design Guidelines", "Documentation Requirements", "Standards document does not appear"),
            ("standards", "source documents", "read-only"),
        ),
        app(
            "Reports & Handoff",
            "Exports timestamped CSV, PDF, or summary files from the currently loaded Atlas cache.",
            "Reports are evidence for review and cleanup; they are not a hidden second source of truth.",
            ("Export documentation gaps.", "Export compatibility rows.", "Export photo coverage and PM checklists."),
            ("Loaded Atlas bundle", "Generated Report folder", "source workbook paths for provenance"),
            ("Expecting an export to refresh data automatically.", "Comparing old and new exports without checking timestamps."),
            ("Refresh data first if source workbooks changed.", "Use Export looks stale when numbers do not match the UI."),
            ("Documentation Gap Report", "Audit Progress Report", "Standards Compliance Summary", "Compatibility Export", "Source workbook path is missing"),
            ("reports", "export", "generated report"),
        ),
        app(
            "Settings / Diagnostics",
            "Preferences, source status, photo loader controls, cache timing, and diagnostic views.",
            "Diagnostics explain why Atlas is showing a result; they should not be needed for normal lookup.",
            ("Change theme and startup page.", "Confirm source paths.", "Clear photo cache or review load timings."),
            ("User settings file", "project root source paths", "Atlas performance counters"),
            ("Changing settings to solve a missing workbook path.", "Clearing photo cache when the source folder itself is missing."),
            ("Check source status first.", "Use Refresh Data after source files are repaired."),
            ("Source workbook path is missing", "Export looks stale", "Photos do not preview", "Home / Command Deck"),
            ("settings", "diagnostics", "source status"),
        ),
    ]


def _standard_entries() -> list[InformationLibraryEntry]:
    source = _source("EOAT Standard Design Guidelines", section="Design and documentation standards")

    def standard(
        title: str,
        purpose: str,
        rules: tuple[str, ...],
        acceptable: tuple[str, ...],
        unacceptable: tuple[str, ...],
        inspection: tuple[str, ...],
        failures: tuple[str, ...],
        fields: tuple[str, ...],
        tags: tuple[str, ...],
        source_section: str = "",
    ) -> InformationLibraryEntry:
        return _entry(
            "eoat_standard",
            title,
            purpose,
            "Apply this standard when the EOAT profile has matching hardware, photos, or warning fields.",
            (
                _section("Purpose", purpose),
                _section("Standard Rules", *rules),
                _section("Acceptable Examples", *acceptable),
                _section("Unacceptable Examples", *unacceptable),
                _section("Inspection Points", *inspection),
                _section("Related Failure Modes", *failures),
                _section("Related Atlas Fields", *fields),
                _section("Source Documents", "EOAT Standard Design Guidelines"),
            ),
            category="EOAT Standards",
            tags=tags,
            related_fields=fields,
            related_pages=("Standards & Work Instructions", "EOAT Profiles", "PM / Inspection"),
            related_references=("Documentation Requirements", "Weekly EOAT Inspection"),
            warnings=unacceptable,
            source=replace(source, section=source_section or title),
            tree_path=("EOAT Standards", title),
        )

    return [
        standard(
            "Vacuum Cup Selection",
            "Select cup style, material, size, and placement so the EOAT can pick the part without marking, leaking, or overloading the circuit.",
            ("Cup material must match part surface and cleanliness needs.", "Cup quantity must support part weight and acceleration.", "Vacuum notes should identify unusual cup geometry or handling risk."),
            ("Silicone cups documented for delicate cosmetic surfaces.", "Cup photo shows all active pickup points and worn-item style."),
            ("Cup material blank while Vacuum Present is Yes.", "Cracked or flattened cups left in service.", "Cup count conflicts with # Parts Picked."),
            ("Check cup wear, cracks, hardening, loose fittings, and contact location.", "Confirm missing cup photos are captured during audit."),
            ("Dropped parts", "Vacuum leaks", "Part marking", "Low readiness confidence"),
            ("Vacuum Present", "Cup Material", "Grippers", "# Parts Picked", "Photo Coverage Status"),
            ("vacuum", "cups", "material"),
        ),
        standard(
            "Pneumatic Tubing Routing",
            "Route tubing so robot motion does not kink, rub, pinch, or pull fittings during normal movement.",
            ("Tubing should have strain relief near moving joints.", "Routes should leave service loops without loose snags.", "Tubing notes should call out special routing or pressure/vacuum circuits."),
            ("Tubing secured along EOAT frame with visible bend radius.", "Connection photo shows supply and vacuum lines clearly."),
            ("Tubing crosses a pinch point.", "Unlabeled loose tubing bundle.", "Route hidden in photos and not documented."),
            ("Check full wrist rotation, rub points, fittings, labels, and bend radius.", "Review photos before deciding routing is documented."),
            ("Intermittent vacuum", "Pressure loss", "Premature tubing wear", "Setup delay"),
            ("Connection Type", "Vacuum Present", "Moves", "Photo Coverage Status"),
            ("pneumatic", "tubing", "routing"),
        ),
        standard(
            "Sensor / Part-Present Standards",
            "Document sensors and confirmation logic well enough that setup can verify part-present behavior quickly.",
            ("Part-present sensors must be called out when used.", "Sensor photos should show mounting and cable route.", "Robot or machine context should explain required signal integration."),
            ("Sensor type listed with part-present flag set to Yes.", "Photo shows sensor target and bracket."),
            ("Sensors Present is Yes but sensor type is blank.", "Part-present sensor missing from both fields and photos.", "Cable routing not visible."),
            ("Verify sensor mount, cable strain relief, target alignment, and signal response.", "Compare source field with visible hardware."),
            ("False part confirmation", "Dropped part not detected", "Machine interlock confusion"),
            ("Sensors Present", "Part-Present Sensor", "Robot Type", "Machine #", "Photo Coverage Status"),
            ("sensor", "part present", "signal"),
        ),
        standard(
            "Quick Disconnect Standards",
            "Keep pneumatic and electrical disconnects identifiable, accessible, and compatible with the machine setup.",
            ("Connection Type should identify the expected disconnect.", "Disconnect photos should show fittings and labels.", "Damaged or unlabeled disconnects should create inspection work."),
            ("QD listed as present with connection photo.", "Machine profile robot context matches the EOAT connection requirement."),
            ("Quick disconnect present but Connection Type blank.", "Fitting damaged or hard to access.", "Electrical and pneumatic connectors not distinguished."),
            ("Check fitting condition, labels, accessibility, and matching machine services.", "Confirm source fields match visible connectors."),
            ("Incorrect hookup", "Changeover delay", "Air leak", "Sensor connection failure"),
            ("Quick Disconnect Present", "Connection Type", "Machine #", "Robot Type"),
            ("quick disconnect", "connections", "setup"),
        ),
        standard(
            "EOAT Weight and Rigidity",
            "Control EOAT mass and structure so robot payload, deflection, and repeatability stay within acceptable setup limits.",
            ("Weight notes should be captured when known.", "Large or flexible assemblies need photo and inspection context.", "Do not infer payload approval from compatibility rows alone."),
            ("Rigid frame visible with mounting points photographed.", "Known weight or construction notes included for heavy tools."),
            ("Long unsupported bracket with no rigidity note.", "Compatibility treated as payload confirmation.", "Missing mounting photos on a large EOAT."),
            ("Check frame cracks, bent brackets, loose mounts, and sag under load.", "Escalate missing payload data for heavy EOATs."),
            ("Robot overload", "Part placement drift", "Bracket fatigue", "Repeatability loss"),
            ("EOAT Type", "Moves", "Machine #", "Robot Type", "Readiness Status"),
            ("weight", "rigidity", "payload"),
        ),
        standard(
            "Mounting Hardware and Fasteners",
            "Mounting hardware must be secure, visible, and consistent enough for repeatable install and PM.",
            ("Mounting bolts and brackets should be visible in photos.", "Loose, missing, mixed, or damaged hardware should be recorded.", "Fastener issues require corrective action before normal reuse."),
            ("Mount face photo shows full bolt pattern.", "Inspection notes identify replaced hardware."),
            ("Missing bolt visible in photo.", "No mounting photo for EOAT with known install issue.", "Washer stack or bracket damage not recorded."),
            ("Check bolt tightness, witness marks, stripped holes, bracket cracks, and missing washers.", "Tie recurring hardware findings to PM actions."),
            ("EOAT shift", "Dropped part", "Robot crash risk", "Install repeatability issue"),
            ("EOAT Type", "Readiness Status", "Photo Coverage Status", "Warning Severity"),
            ("hardware", "fasteners", "mounting"),
        ),
        standard(
            "Cable Management",
            "Route cables so sensor and EOAT wiring survives motion without strain, pinching, or confusing setup.",
            ("Cable paths should be secured and serviceable.", "Sensor cables should be traceable to the device they support.", "Cable hazards should be documented as inspection findings."),
            ("Cable tie points visible and away from pinch points.", "Sensor photo shows cable exit and strain relief."),
            ("Cable crosses robot wrist pinch area.", "Loose cable bundle hides sensor identity.", "Cable damage visible but not noted."),
            ("Check abrasion, tie condition, strain relief, connector seating, and sensor response.", "Add missing photos when cable routing cannot be verified."),
            ("Intermittent sensor", "Broken cable", "Setup miswire", "False reject"),
            ("Sensors Present", "Part-Present Sensor", "Robot Type", "Photo Coverage Status"),
            ("cable", "sensor", "routing"),
        ),
        standard(
            "Documentation Requirements",
            "Minimum EOAT documentation should support identity, compatibility, photos, setup, inspection, and troubleshooting.",
            ("EOAT Assembly ID, Tool #, and Machine # must be normalized.", "Critical fields should not be left blank when hardware is present.", "Photos must show enough context to verify fields."),
            ("EOAT has ID, tools, compatible machines, connection, vacuum/sensor notes, and required photos.", "Warnings explain remaining uncertainty."),
            ("Tool # buried in notes only.", "Machine list conflicts with Press Capacity.", "Profile has photos but no identity fields."),
            ("Review critical missing fields, source workbook rows, and photo category chips.", "Repair source workbook values rather than only adding notes."),
            ("Bad search results", "Low confidence", "Stale changeover packet", "Missed PM finding"),
            ("EOAT Assembly ID", "Tool #", "Machine #", "Readiness Status", "Compatibility Confidence"),
            ("documentation", "readiness", "fields"),
        ),
        standard(
            "Process Binder Expectations",
            "Process binders should preserve the setup evidence needed to reproduce a known-good EOAT installation.",
            ("Binder content should connect Tool #, machine, EOAT, changeover packet, photos, and key warnings.", "Generated reports should include timestamp and source context.", "Manual notes should not contradict Atlas source fields."),
            ("Setup packet references the selected machine, tool, EOAT, photos, and warnings.", "Report timestamp matches review date."),
            ("Binder contains old export with no source date.", "EOAT photo folder missing from binder reference.", "Manual compatibility note conflicts with matrix."),
            ("Check export timestamp, source workbook path, selected identifiers, and warning list.", "Refresh and regenerate stale reports."),
            ("Wrong EOAT staged", "Old setup reused", "Audit trail confusion"),
            ("Tool #", "Machine #", "EOAT Assembly ID", "Export Location", "Warning Severity"),
            ("binder", "changeover packet", "setup packet", "handoff"),
            source_section="Process binder",
        ),
        standard(
            "Cleanroom Documentation Considerations",
            "Cleanroom EOAT documentation should make material, cleanliness, and handling constraints visible before setup.",
            ("Cup material and contact surfaces should be documented.", "Photos should support cleanliness-sensitive inspection.", "Avoid vague notes when materials or surfaces affect process risk."),
            ("Cup material listed for contact surfaces.", "Photos show contact points without contamination ambiguity."),
            ("Cup material blank on a cleanroom EOAT.", "Handling note says clean only with no material context.", "Photo coverage misses contact surfaces."),
            ("Check cup/gripper material, wear, residue, and source notes.", "Capture close photos of contact areas when cleanroom risk is present."),
            ("Contamination risk", "Part marking", "Audit finding", "Setup delay"),
            ("Cup Material", "EOAT Type", "Grippers", "Photo Coverage Status"),
            ("cleanroom", "documentation", "material"),
            source_section="Cleanroom documentation",
        ),
    ]


def _compatibility_entries() -> list[InformationLibraryEntry]:
    def compat(
        title: str,
        purpose: str,
        inputs: tuple[str, ...],
        logic: tuple[str, ...],
        confidence: tuple[str, ...],
        warnings: tuple[str, ...],
        repair: tuple[str, ...],
        related: tuple[str, ...],
        source: LibrarySource,
        examples: tuple[LibraryExample, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> InformationLibraryEntry:
        return _entry(
            "compatibility_rule",
            title,
            purpose,
            "Compatibility is an evidence ranking, not a substitute for confirming the physical EOAT condition.",
            (
                _section("Purpose", purpose),
                _section("Inputs Used", *inputs),
                _section("Decision Logic", *logic),
                _section("Confidence Rules", *confidence),
                _section("Warning Conditions", *warnings),
                _section("Repair Actions", *repair),
                _section("Related Pages", *related),
            ),
            category="Compatibility Logic",
            tags=tags or ("compatibility",),
            related_fields=("Tool #", "Machine #", "EOAT Assembly ID", "Compatibility Confidence", "Warning Severity"),
            related_pages=related,
            related_references=("Compatibility Confidence Levels", "Compatibility Warning Rules"),
            examples=examples,
            warnings=warnings,
            source=source,
            tree_path=("Compatibility Logic", title),
        )

    press = _source("Press Capacity Workbook", section="Tool-machine relationships")
    tracker = _source("EOAT Master Tracker", section="EOAT inventory rows")
    internal = _source("Atlas internal reference", source_type="Atlas internal reference")
    return [
        compat(
            "Tool-to-Machine Compatibility",
            "Determines which machines can run a tool based on Press Capacity and normalized tool identifiers.",
            ("Tool # from search/profile row.", "Press Capacity part number or tool number.", "Machine number from capacity row."),
            ("Normalize Tool #.", "Look up matching capacity rows.", "Return all machines linked to the tool.", "Do not require an EOAT row for this relationship."),
            ("High when exact normalized Tool # is found.", "Medium when only related descriptive text matches.", "Low when no Press Capacity source is available."),
            ("Tool # not found in Press Capacity.", "Capacity workbook missing.", "Machine number cannot be normalized."),
            ("Repair or add the tool-machine row in Press Capacity.", "Normalize Tool # formatting in source workbook.", "Refresh Atlas data."),
            ("Machine Profiles", "Tool / Mold / Part", "Compatibility Data Table"),
            press,
            examples=(
                _example(
                    "Tool lookup",
                    inputs=("Tool #: 12345", "Press Capacity rows: 12345 -> Machine 12, 14"),
                    logic=("Normalize 12345.", "Read all capacity rows with that key."),
                    outputs=("Compatible machines: Machine 12, Machine 14",),
                ),
            ),
            tags=("tool", "machine", "press capacity"),
        ),
        compat(
            "EOAT-to-Tool Compatibility",
            "Determines which tools an EOAT is linked to through EOAT inventory and audit rows.",
            ("EOAT Assembly ID.", "Tool # field.", "Audit rows merged into the EOAT profile."),
            ("Normalize EOAT Assembly ID.", "Collect all tool values from rows in the EOAT group.", "Display unique tools on the EOAT profile."),
            ("High when Tool # is present on an audited row.", "Medium when the EOAT is present but Tool # comes from a merged row.", "Low when Tool # exists only in notes."),
            ("Tool # blank.", "Conflicting tool values on duplicate EOAT rows.", "Tool appears in notes but not the Tool # field."),
            ("Move tool numbers into the Tool # field.", "Split or correct duplicate EOAT rows.", "Refresh Atlas after workbook repair."),
            ("EOAT Profiles", "Tool / Mold / Part", "Documentation Gap Report"),
            tracker,
            tags=("eoat", "tool", "inventory"),
        ),
        compat(
            "EOAT-to-Machine Compatibility",
            "Connects EOATs to machines from direct audit rows and tool-derived capacity relationships.",
            ("EOAT Assembly ID.", "Machine # from inventory rows.", "Tool # linked to the EOAT.", "Press Capacity machines for that tool."),
            ("Prefer explicit machine rows when present.", "Expand compatible machines from Tool # and Press Capacity.", "Merge and deduplicate the machine list."),
            ("High when direct machine and tool-derived machine agree.", "Medium when machine comes from capacity only.", "Low when robot info or machine normalization is missing."),
            ("Machine # blank or N/A.", "Tool has no capacity row.", "Robot Info missing for machine."),
            ("Confirm Tool # in Press Capacity.", "Repair Machine # formatting.", "Add Robot Info for the machine where available."),
            ("EOAT Profiles", "Machine Profiles", "Compatibility Data Table"),
            tracker,
            tags=("eoat", "machine", "derived"),
        ),
        compat(
            "Off-Machine EOAT Audit Handling",
            "Preserves physical off-machine audit evidence while offering machine rows derived from tool capacity.",
            ("Tool #.", "Machine # value such as N/A or blank.", "EOAT Assembly ID.", "Press Capacity tool-machine rows."),
            ("Keep the original off-machine audit row.", "Search Press Capacity for the Tool #.", "Offer compatibility rows for found machines.", "Mark derived rows separately from physical audit rows when that status exists."),
            ("High for the preserved physical audit evidence.", "Medium for capacity-derived compatibility rows until verified on-machine.", "Low if Tool # cannot be found."),
            ("Tool # not found in Press Capacity.", "Derived rows look like physical audits.", "Duplicate rows already exist."),
            ("Correct Tool #.", "Use Entry Type or audit context to distinguish derived compatibility.", "Deduplicate rows before adding new derived records."),
            ("EOAT Profiles", "Compatibility Data Table", "Audit Progress Report"),
            tracker,
            examples=(
                _example(
                    "Off-machine audit expansion",
                    inputs=("Tool #: 12345", "Machine #: N/A", "EOAT Assembly ID: P4-EOAT-0021"),
                    logic=("Search Press Capacity for Tool # 12345.", "Find all compatible machines.", "Preserve original off-machine audit row.", "Offer derived compatibility rows."),
                    outputs=("Original audit remains Machine # N/A.", "Compatibility rows created for Machine 12, Machine 14, Machine 22.", "Warning shown if Tool # is not found in Press Capacity."),
                ),
            ),
            tags=("off-machine", "audit", "derived rows"),
        ),
        compat(
            "Compatibility Confidence Levels",
            "Explains why Atlas labels a relationship high, medium, low, or warning-prone.",
            ("Direct EOAT row evidence.", "Press Capacity evidence.", "Robot Info availability.", "Documentation and photo completeness.", "Open warnings."),
            ("Raise confidence when independent sources agree.", "Lower confidence for missing source fields or derived-only links.", "Surface warning severity next to the relationship."),
            ("High: direct row plus capacity support and no critical gaps.", "Medium: useful relationship with source gaps.", "Low: inferred or missing source support."),
            ("Source workbook missing.", "Tool or machine key ambiguous.", "Critical documentation fields blank."),
            ("Repair the missing source field.", "Refresh data.", "Open the profile warning card for the specific cause."),
            ("Compatibility Data Table", "EOAT Profiles", "Machine Profiles"),
            internal,
            tags=("confidence", "warnings", "readiness"),
        ),
        compat(
            "Compatibility Warning Rules",
            "Defines the main conditions that should make a compatibility answer display a warning.",
            ("Missing Tool #.", "Missing Machine #.", "Missing EOAT Assembly ID.", "Press Capacity lookup status.", "Duplicate row status.", "Source workbook status."),
            ("Attach warnings to the affected profile or row.", "Keep the compatibility answer visible when partial evidence is still useful.", "Do not hide low-confidence rows without explanation."),
            ("Warning severity increases when a critical identifier is missing.", "Informational warnings are used for cleanup hints that do not block lookup."),
            ("Machine profile missing EOATs.", "EOAT has tools but no machines.", "Source path is missing.", "Duplicate compatible rows inflate counts."),
            ("Fix identifiers first.", "Repair source path second.", "Rebuild exports after refresh."),
            ("Compatibility Data Table", "Settings / Diagnostics", "Documentation Gap Report"),
            internal,
            tags=("warnings", "severity", "rules"),
        ),
        compat(
            "Duplicate Compatibility Row Handling",
            "Prevents repeated audit or derived rows from inflating counts and confusing profiles.",
            ("EOAT Assembly ID.", "Tool #.", "Machine #.", "Entry Type or audit context.", "Source row identifier if present."),
            ("Normalize the compatibility key.", "Group rows with the same EOAT-tool-machine relationship.", "Prefer physical audited evidence over derived compatibility when summarizing."),
            ("High when duplicate rows agree and one audited row exists.", "Medium when duplicates are derived-only.", "Warning when duplicates conflict."),
            ("Same EOAT-tool-machine appears multiple times.", "Rows disagree on Entry Type.", "Source ID missing on compatible rows."),
            ("Remove accidental duplicates.", "Fill Source Audit ID for derived rows.", "Keep one physical audit row as the primary evidence."),
            ("Compatibility Data Table", "EOAT Profiles", "Audit Progress Report"),
            tracker,
            tags=("duplicates", "rows", "audit"),
        ),
        compat(
            "EOAT Assembly ID Logic",
            "Explains how Atlas treats EOAT identity as the primary key for profile grouping and lookup.",
            ("EOAT Assembly ID.", "Audit ID fallback.", "Display ID normalization.", "Source rows sharing the same normalized EOAT ID."),
            ("Normalize spacing and punctuation.", "Group rows with the same EOAT Assembly ID.", "Use fallback identifiers only when the EOAT ID is missing."),
            ("High when normalized EOAT ID is present.", "Medium when fallback audit ID is used.", "Low when only descriptive text identifies the EOAT."),
            ("Blank EOAT Assembly ID.", "Two physical EOATs share one ID.", "Same EOAT appears with multiple spellings."),
            ("Assign or correct EOAT Assembly ID.", "Split rows for different physical EOATs.", "Refresh after repair."),
            ("EOAT Profiles", "Data Dictionary", "Documentation Gap Report"),
            tracker,
            tags=("eoat id", "identity", "normalization"),
        ),
        compat(
            "Compatible Tool # List on EOAT",
            "Explains how the EOAT profile builds the list of tools shown as compatible.",
            ("All source rows for the EOAT.", "Tool # values.", "Normalized duplicate handling.", "Optional capacity cross-check."),
            ("Collect Tool # from each EOAT row.", "Remove duplicate normalized values.", "Show display values in stable order.", "Warn when tools have no machine support."),
            ("High when tools are present and capacity rows exist.", "Medium when tools exist but capacity is unavailable.", "Low when tool values are missing or inconsistent."),
            ("Tool # list empty.", "Same tool appears with different formatting.", "Compatible machines missing for a listed tool."),
            ("Repair Tool # fields.", "Check Press Capacity for each tool.", "Refresh and re-open the EOAT profile."),
            ("EOAT Profiles", "Tool / Mold / Part", "Compatibility Data Table"),
            tracker,
            tags=("tool list", "eoat profile", "normalization"),
        ),
    ]


def _data_dictionary_entries() -> list[InformationLibraryEntry]:
    tracker = _source("EOAT Master Tracker", section="EOAT Inventory")
    press = _source("Press Capacity Workbook", section="Capacity rows")
    photo = _source("Photo Folder Index", section="Photo index")
    internal = _source("Atlas internal reference", source_type="Atlas internal reference")

    def field_entry(
        field_name: str,
        definition: str,
        allowed: tuple[str, ...],
        source_truth: str,
        edited_by: str,
        used_by: tuple[str, ...],
        bad: tuple[str, ...],
        validation: tuple[str, ...],
        repair: str,
        source: LibrarySource,
        tags: tuple[str, ...] = (),
    ) -> InformationLibraryEntry:
        return _entry(
            "data_dictionary",
            field_name,
            definition,
            repair,
            (
                _section("Definition", definition),
                _section("Allowed Values", *allowed),
                _section("Source Of Truth", source_truth),
                _section("Edited By", edited_by),
                _section("Used By", *used_by),
                _section("Common Bad Values", *bad),
                _section("Validation Rules", *validation),
                _section("Repair Action", repair),
            ),
            category="Data Dictionary",
            tags=("field", *tags),
            related_fields=(field_name,),
            related_pages=used_by,
            source=source,
            tree_path=("Data Dictionary", field_name),
        )

    return [
        field_entry("EOAT Assembly ID", "Unique identifier for a physical EOAT assembly or documented EOAT group.", ("Normalized plant EOAT ID such as P4-EOAT-0021.", "Blank only for incomplete source rows."), "EOAT Master Tracker.", "Audit owner or workbook maintainer.", ("EOAT Profiles", "Compatibility Data Table", "Changeover Packet Builder"), ("TBD", "same EOAT with two spellings", "tool number used as EOAT ID"), ("Normalize punctuation and spacing.", "Must not collide across different physical EOATs."), "Assign or correct the EOAT Assembly ID in the tracker, then refresh Atlas.", tracker, ("identity",)),
        field_entry("Tool #", "Tool or mold identifier used to connect EOAT rows to Press Capacity.", ("Numeric or plant-approved tool identifier.", "Multiple values only when the source supports a clear separator."), "EOAT Master Tracker and Press Capacity Workbook.", "Tooling or audit owner.", ("Tool / Mold / Part", "What Do I Need?", "Compatibility Data Table"), ("part description only", "tool family name", "mold number in notes only"), ("Normalize leading zeros consistently.", "Should match Press Capacity for machine expansion."), "Move the actual tool number into Tool # and repair the capacity row if needed.", tracker, ("tool",)),
        field_entry("Machine #", "Machine or press number connected to an audited or compatible EOAT relationship.", ("Plant machine number.", "N/A only for off-machine physical audit rows."), "EOAT Master Tracker for audited rows; Press Capacity for derived compatibility.", "Audit owner or process engineering.", ("Machine Profiles", "Compatibility Data Table", "Changeover Packet Builder"), ("press text with no number", "N/A on a row that is actually installed", "multiple machines in free text"), ("Normalize machine tokens.", "N/A must not be treated as a confirmed installed machine."), "Correct the machine number or preserve N/A only for true off-machine evidence.", tracker, ("machine",)),
        field_entry("Robot Type", "Robot family or automation type associated with a machine or EOAT setup.", ("Known robot type from Robot Info.", "Blank when unknown."), "Robot Info workbook or machine profile source.", "Automation or maintenance owner.", ("Machine Profiles", "Compatibility Confidence Levels", "Changeover Packet Builder"), ("controller model only", "brand nickname", "copied machine number"), ("Should align with machine number.", "Missing Robot Info lowers compatibility confidence."), "Update Robot Info or the tracker row with the correct robot type.", internal, ("robot",)),
        field_entry("EOAT Type", "High-level EOAT construction or handling style.", ("Vacuum", "Gripper", "Hybrid", "Custom plant-approved type"), "EOAT Master Tracker.", "Audit owner.", ("EOAT Profiles", "PM / Inspection", "Standards & Work Instructions"), ("misc", "unknown but hardware visible", "part name"), ("Should agree with vacuum/gripper/sensor fields.", "Blank type lowers readiness."), "Choose the closest approved EOAT type and add notes for unusual hardware.", tracker, ("type",)),
        field_entry("Connection Type", "Pneumatic/electrical connection description needed for setup.", ("Quick disconnect type.", "Pneumatic/electrical notes.", "Blank only when not recorded."), "EOAT Master Tracker and photos.", "Audit owner or maintenance.", ("EOAT Profiles", "Changeover Packet Builder", "Quick Disconnect Standards"), ("yes", "air", "see photo"), ("Should explain the actual connection, not just presence.", "Should align with Quick Disconnect Present."), "Replace vague values with fitting or connection details and add a connection photo.", tracker, ("connection",)),
        field_entry("Moves", "Motion or pick/place behavior notes that affect setup and inspection.", ("Short engineering note.", "Blank when not captured."), "EOAT Master Tracker.", "Process engineering or audit owner.", ("EOAT Profiles", "EOAT Weight and Rigidity", "Pneumatic Tubing Routing"), ("good", "normal", "operator initials"), ("Should describe movement risk or count when relevant.", "Should not duplicate status."), "Capture the motion detail needed for routing, rigidity, or setup review.", tracker, ("motion",)),
        field_entry("Grippers", "Mechanical gripping hardware description or count.", ("Jaw/gripper type.", "Count or notes.", "Blank when no grippers or unknown."), "EOAT Master Tracker and photos.", "Audit owner or maintenance.", ("EOAT Profiles", "Vacuum Cup Inspection", "Mounting Hardware Inspection"), ("yes with no type", "cup info in gripper field", "unknown with visible gripper"), ("Should align with EOAT Type.", "Should be supported by photos for wear review."), "Document gripper type/count and add close-up photos of contact points.", tracker, ("gripper",)),
        field_entry("Vacuum Present", "Boolean indicator that vacuum hardware is part of the EOAT.", ("Yes", "No", "Unknown/blank when not audited"), "EOAT Master Tracker and photos.", "Audit owner.", ("EOAT Profiles", "Vacuum Cup Selection", "Photo Coverage Report"), ("Y?", "has cups maybe", "blank while vacuum cups visible"), ("If Yes, vacuum/cup details should be populated.", "If No, vacuum cup fields should not claim active cups."), "Set Yes/No from visible hardware and fill vacuum details when Yes.", tracker, ("vacuum",)),
        field_entry("Sensors Present", "Boolean indicator that sensors are used on the EOAT.", ("Yes", "No", "Unknown/blank when not audited"), "EOAT Master Tracker and photos.", "Audit owner or automation.", ("Sensor / Part-Present Standards", "EOAT Profiles", "Machine Profiles"), ("sensor maybe", "photo only", "blank while sensor visible"), ("If Yes, sensor description or part-present status should be captured.", "Should agree with photos."), "Set the value from the physical EOAT and document sensor type or function.", tracker, ("sensor",)),
        field_entry("Part-Present Sensor", "Specific indicator that the EOAT verifies part presence.", ("Yes", "No", "Unknown/blank when not audited"), "EOAT Master Tracker or automation notes.", "Automation owner or audit owner.", ("What Do I Need?", "Sensor Verification", "Changeover Packet Builder"), ("sensor", "photo", "blank with part-present hardware"), ("Should not be Yes unless the sensor confirms part presence.", "Should have matching sensor notes/photos."), "Confirm signal purpose and update the field with Yes or No.", tracker, ("part present",)),
        field_entry("Quick Disconnect Present", "Boolean indicator that the EOAT uses quick disconnect hardware.", ("Yes", "No", "Unknown/blank when not audited"), "EOAT Master Tracker and connection photos.", "Maintenance or audit owner.", ("Quick Disconnect Standards", "Changeover Packet Builder", "PM / Inspection"), ("QD?", "connector", "blank while fitting visible"), ("If Yes, Connection Type should identify the connection.", "Should be visible in photos when practical."), "Set the value and document the fitting or connector type.", tracker, ("quick disconnect",)),
        field_entry("Cup Material", "Material of vacuum cups or contact cups where it affects handling or cleanroom risk.", ("Silicone", "Nitrile", "Urethane", "Plant-approved material", "Blank when not applicable"), "EOAT Master Tracker and standards.", "Process engineering or audit owner.", ("Vacuum Cup Selection", "Cleanroom Documentation Considerations", "EOAT Profiles"), ("rubber", "unknown", "color only"), ("Required when vacuum cups are present and material matters.", "Should not conflict with cleanroom notes."), "Confirm cup material from parts list, standard, or physical inspection.", tracker, ("cup", "material")),
        field_entry("# Parts Picked", "Number of parts picked per cycle by the EOAT.", ("Positive integer.", "Blank when unknown."), "EOAT Master Tracker or process setup.", "Process engineering or audit owner.", ("What Do I Need?", "Changeover Packet Builder", "Vacuum Cup Selection"), ("many", "2?", "cavity count in notes only"), ("Must be numeric when known.", "Should align with cup/gripper count and changeover packet context."), "Enter the verified number of parts picked per cycle.", tracker, ("parts picked",)),
        field_entry("Photo Coverage Status", "Atlas-derived status for whether required EOAT photo categories are present.", ("Complete", "Partial", "Missing folder", "No photos"), "Photo Folder Index and photo scan.", "Atlas generated from source folders.", ("Photos", "EOAT Profiles", "Photo Coverage Report"), ("manual status in notes", "folder exists but no category coverage", "old path"), ("Folder presence alone is not complete coverage.", "Missing categories should remain visible."), "Add or index the missing required photo categories, then refresh Atlas.", photo, ("photos", "coverage")),
        field_entry("Readiness Status", "Atlas-derived status that summarizes whether profile data is complete enough for confident reuse.", ("Ready", "Review", "Needs cleanup", "Unknown"), "Atlas generated from documentation, compatibility, photos, and warnings.", "Atlas generated.", ("EOAT Profiles", "Analytics Dashboard", "Executive Summary Export"), ("manual override without evidence", "status copied from old report"), ("Should be derived from current cache.", "Warnings and missing critical fields lower readiness."), "Repair the underlying missing fields, photos, or source paths rather than editing readiness text.", internal, ("readiness",)),
        field_entry("Compatibility Confidence", "Atlas-derived confidence label for a relationship between EOAT, tool, and machine.", ("High", "Medium", "Low", "Unknown"), "Atlas compatibility logic.", "Atlas generated.", ("Compatibility Data Table", "What Do I Need?", "Changeover Packet Builder"), ("manually typed confidence", "green without source", "blank on warning row"), ("Must reflect source evidence and warning conditions.", "Derived rows are not the same as physical audits."), "Repair source evidence or review the warning rather than forcing the confidence label.", internal, ("confidence",)),
        field_entry("Warning Severity", "Severity label used to prioritize source-data, compatibility, photo, or standards issues.", ("Info", "Warning", "Critical"), "Atlas validation and compatibility checks.", "Atlas generated.", ("EOAT Profiles", "Machine Profiles", "Reports & Handoff"), ("urgent", "red", "operator note"), ("Critical means the lookup may be materially misleading.", "Info means cleanup or context, not necessarily blocked use."), "Fix the root warning condition in the relevant source or document the exception.", internal, ("warnings", "severity")),
    ]


def _troubleshooting_entries() -> list[InformationLibraryEntry]:
    internal = _source("Atlas internal reference", source_type="Atlas internal reference")
    photo = _source("Photo Folder Index", section="Photo paths and image formats")
    tracker = _source("EOAT Master Tracker", section="EOAT Inventory")
    press = _source("Press Capacity Workbook", section="Tool-machine relationships")
    generated = _source("Generated Report", section="Export output")

    def trouble(
        title: str,
        symptom: str,
        causes: tuple[str, ...],
        checks: tuple[str, ...],
        fixes: tuple[str, ...],
        workaround: str,
        diagnostics: tuple[str, ...],
        related: tuple[str, ...],
        source: LibrarySource,
        tags: tuple[str, ...],
    ) -> InformationLibraryEntry:
        return _entry(
            "troubleshooting",
            title,
            symptom,
            fixes[0] if fixes else workaround,
            (
                _section("Symptom", symptom),
                _section("Likely Causes", *causes),
                _section("Checks To Run", *checks),
                _section("Fix Steps", *fixes),
                _section("Manual Workaround", workaround),
                _section("Related Diagnostics", *diagnostics),
                _section("Related Pages", *related),
            ),
            category="Troubleshooting",
            tags=tags,
            related_pages=related,
            related_references=diagnostics,
            source=source,
            tree_path=("Troubleshooting", title),
        )

    return [
        trouble("Photos do not preview", "A photo path is listed, but the in-app preview panel shows an error, blank image, or fallback message.", ("Unsupported file format.", "File moved after indexing.", "Corrupt image.", "Network path temporarily unavailable."), ("Open the same file externally.", "Check the file path in the photo card tooltip.", "Review photo loader failure count in diagnostics."), ("Refresh Atlas after restoring the photo file.", "Convert unsupported files to JPG or PNG when preview is required.", "Clear photo cache if a replaced image still shows the old failure."), "Use Open Folder or Open Externally to inspect the original image.", ("Photo loader stats", "Photo Coverage Status"), ("Photos", "Settings / Diagnostics"), photo, ("photos", "preview")),
        trouble("HEIC / HEIF images do not load", "Phone images with HEIC or HEIF extensions are indexed but fail to render in the Atlas preview.", ("Qt image plugins may not decode HEIC.", "Pillow HEIF support may be unavailable in the runtime.", "File extension does not match actual content."), ("Try Open Externally.", "Check whether the same folder contains JPG/PNG alternatives.", "Review photo decode error text."), ("Convert inspection images to JPG or PNG for reliable in-app preview.", "Install or package HEIF decoder support only if the deployment target allows it."), "Keep the original HEIC in the folder and add a JPG copy for Atlas preview.", ("Photo loader stats", "Supported image suffixes"), ("Photos", "Photo Coverage Report"), photo, ("heic", "heif", "format")),
        trouble("EOAT profile missing compatible machines", "An EOAT profile opens, but the compatible machine chips are empty or lower than expected.", ("Tool # missing on EOAT row.", "Tool not found in Press Capacity.", "Machine # stored as N/A for off-machine audit.", "Machine tokens use inconsistent formatting."), ("Open EOAT profile Tool # list.", "Search the Tool # directly.", "Check Press Capacity source status.", "Look for off-machine audit rows."), ("Repair Tool # in the tracker.", "Add or correct Press Capacity rows.", "Preserve off-machine rows but create verified compatibility rows where appropriate."), "Use Tool / Mold / Part to inspect the tool-machine side while source data is repaired.", ("Compatibility Warning Rules", "Off-Machine EOAT Audit Handling"), ("EOAT Profiles", "Compatibility Data Table", "Tool / Mold / Part"), tracker, ("eoat", "machines", "compatibility")),
        trouble("Machine profile missing EOATs", "A machine profile has robot or tool context, but no linked EOATs appear.", ("Press Capacity has tools but tracker lacks EOAT-tool links.", "Machine number mismatch.", "Only derived compatibility exists and source rows are missing.", "Atlas cache is stale."), ("Search a known Tool # for that machine.", "Check Machine # formatting.", "Review source status on Home.", "Refresh data."), ("Repair EOAT-tool rows in the tracker.", "Normalize machine values.", "Refresh Atlas and re-open the machine profile."), "Use Press Capacity to list likely tools while EOAT links are corrected.", ("Tool-to-Machine Compatibility", "EOAT-to-Machine Compatibility"), ("Machine Profiles", "Compatibility Data Table"), press, ("machine", "eoats", "missing")),
        trouble("Tool search returns no results", "A tool, mold, or part search returns no matching tool cards or recommendations.", ("Tool # formatting differs from source.", "Identifier is stored as Mold # or part description only.", "Source workbook path is missing.", "Atlas cache predates the workbook change."), ("Search exact Tool #.", "Search part description fragment.", "Check source status.", "Refresh data."), ("Move the tool number into Tool #.", "Repair Press Capacity key.", "Refresh Atlas after workbook changes."), "Open the source workbook read-only and verify the tool exists before editing.", ("Source workbook path is missing", "Tool # data dictionary"), ("Tool / Mold / Part", "What Do I Need?"), tracker, ("tool", "search")),
        trouble("Compatibility confidence is lower than expected", "Atlas shows a relationship but labels confidence as medium, low, or warning-prone.", ("Source evidence is derived-only.", "Robot Info missing.", "Documentation or photos incomplete.", "Warnings attached to the EOAT or machine."), ("Open the row's warnings.", "Compare EOAT, tool, and machine profile evidence.", "Check Robot Type and photo coverage."), ("Repair missing source fields.", "Add photo categories.", "Add Robot Info where available.", "Refresh and re-export if needed."), "Treat the relationship as usable for investigation but not as fully verified until warnings are resolved.", ("Compatibility Confidence Levels", "Warning Severity"), ("Compatibility Data Table", "EOAT Profiles"), internal, ("confidence", "warnings")),
        trouble("Off-machine audit did not create expected rows", "An EOAT audited off-machine remains visible, but expected machine compatibility rows are absent.", ("Tool # missing or not in Press Capacity.", "Duplicate row protection skipped rows already present.", "Compatibility-derived row creation was not requested.", "Source row type is not recognized as off-machine."), ("Check Tool # and Machine # on the source row.", "Search Tool # in Press Capacity.", "Review duplicate compatibility warnings."), ("Correct Tool #.", "Resolve duplicates.", "Create or verify compatibility rows with source audit context preserved."), "Use the original off-machine EOAT profile as physical evidence and inspect tools separately.", ("Off-Machine EOAT Audit Handling", "Duplicate Compatibility Row Handling"), ("EOAT Profiles", "Compatibility Data Table", "Audit Progress Report"), tracker, ("off-machine", "audit")),
        trouble("Source workbook path is missing", "Home or Settings shows a required or optional source as missing.", ("Workbook not created in the expected project folder.", "Project root points to the wrong location.", "Network path unavailable.", "Workbook renamed."), ("Open Settings / Diagnostics source status.", "Verify project root.", "Check file exists in expected numbered folder.", "Try refresh after network reconnect."), ("Restore the workbook path.", "Rename or place the workbook in the expected folder.", "Update project configuration if the root is wrong."), "Use available pages that do not depend on the missing source, but do not trust missing-data conclusions.", ("Source Status", "Settings / Diagnostics"), ("Home / Command Deck", "Settings / Diagnostics"), internal, ("source", "workbook", "path")),
        trouble("Standards document does not appear", "A standards or PM reference file exists, but it is not listed in Standards & Work Instructions or Information Library.", ("File is outside the standards folder or project root detection path.", "Filename lacks EOAT standardization keywords.", "File type is not indexed.", "Atlas cache is stale."), ("Check the Standards source status.", "Confirm file location.", "Refresh data.", "Review filename and extension."), ("Move or copy the file into the standards folder.", "Use a descriptive standardization filename.", "Refresh Atlas."), "Open the file from Windows while the standards index is repaired.", ("Standards source status", "EOAT Standard Design Guidelines"), ("Standards & Work Instructions", "Information Library"), internal, ("standards", "documents")),
        trouble("Export looks stale", "A generated report or changeover packet does not match the current source workbook or UI expectation.", ("Export was generated before refresh.", "Source workbook changed after export.", "User is comparing two report timestamps.", "Atlas opened an older file from the output folder."), ("Check export timestamp.", "Check Atlas loaded_at time.", "Refresh data.", "Regenerate the report."), ("Refresh Atlas.", "Regenerate the export.", "Archive or rename older reports when comparing deliverables."), "Use the UI profile as current cache context and treat the old export as historical evidence.", ("Generated Report", "Reports & Handoff"), ("Reports & Handoff", "Changeover Packet Builder"), generated, ("export", "stale", "reports")),
    ]


def _report_guide_entries() -> list[InformationLibraryEntry]:
    generated = _source("Generated Report", section="Report output")

    def report(
        title: str,
        purpose: str,
        inputs: tuple[str, ...],
        columns: tuple[str, ...],
        read: tuple[str, ...],
        good: tuple[str, ...],
        warnings: tuple[str, ...],
        actions: tuple[str, ...],
        location: str,
        tags: tuple[str, ...],
    ) -> InformationLibraryEntry:
        return _entry(
            "report_guide",
            title,
            purpose,
            actions[0] if actions else "Use the report to drive source cleanup.",
            (
                _section("Purpose", purpose),
                _section("Inputs Used", *inputs),
                _section("Key Columns", *columns),
                _section("How To Read", *read),
                _section("What Good Looks Like", *good),
                _section("Warning Meanings", *warnings),
                _section("Recommended Actions", *actions),
                _section("Export Location", location),
            ),
            category="Reports & Handoff Guides",
            tags=("report", *tags),
            related_pages=("Reports & Handoff",),
            source=generated,
            tree_path=("Reports & Handoff Guides", title),
        )

    return [
        report("Documentation Gap Report", "Lists missing critical fields, weak documentation scores, photo gaps, and warnings that need cleanup.", ("EOAT Master Tracker", "Photo Folder Index", "Atlas warning cache"), ("EOAT Assembly ID", "Missing Field", "Severity", "Suggested Repair", "Source"), ("Sort by severity first.", "Group by field to plan workbook cleanup.", "Use EOAT ID to open the profile before editing."), ("Critical missing fields are rare.", "Every row has a clear repair action."), ("Critical means lookup or setup confidence can be misleading.", "Warning means cleanup is needed before high confidence."), ("Repair the source field.", "Refresh Atlas.", "Re-export for handoff evidence."), "Reports & Handoff output folder.", ("documentation", "gaps")),
        report("Audit Progress Report", "Summarizes audited, compatible, off-machine, and incomplete audit coverage.", ("EOAT Master Tracker", "Entry Type", "Audit context fields"), ("Entry Type", "Count", "Missing Required Fields", "Coverage Percent"), ("Separate physical audited rows from compatible rows.", "Use missing required fields as audit backlog."), ("Audited rows have required identifiers.", "Compatible rows preserve source audit context."), ("Unknown entry type means Atlas had to infer context.", "Missing source audit ID weakens derived rows."), ("Fix Entry Type values.", "Complete required fields.", "Use off-machine handling guidance where applicable."), "Reports & Handoff output folder.", ("audit", "progress")),
        report("Standards Compliance Summary", "Summarizes EOAT warnings and documentation issues against the standards library.", ("Standards index", "EOAT warnings", "Documentation status"), ("Standard Area", "Affected EOAT", "Finding", "Severity", "Related Field"), ("Use standard area to batch similar fixes.", "Open the referenced standard before changing rules."), ("Few repeated findings.", "Every finding maps to a source field or inspection action."), ("Repeated findings suggest a standard needs training or template updates.", "Missing source standard means compliance context is incomplete."), ("Review the related standard.", "Repair source fields/photos.", "Add PM actions for physical findings."), "Reports & Handoff output folder.", ("standards", "compliance")),
        report("Compatibility Export", "Exports the dense EOAT-tool-machine relationship table for offline review.", ("EOAT Master Tracker", "Press Capacity Workbook", "Compatibility logic"), ("EOAT Assembly ID", "Tool #", "Machine #", "Confidence", "Warnings", "Source Type"), ("Filter low confidence rows first.", "Check duplicate relationship keys.", "Compare source type before treating rows as physical audit evidence."), ("High-confidence rows dominate.", "Derived rows are labeled clearly."), ("Low confidence means missing evidence, not automatic incompatibility.", "Duplicate warnings mean counts may be inflated."), ("Repair relationship keys.", "Resolve duplicates.", "Refresh and export again."), "Reports & Handoff output folder.", ("compatibility", "csv")),
        report("Photo Coverage Report", "Shows EOAT photo folder presence, image counts, and missing required categories.", ("Photo Folder Index", "EOAT profile index", "required category rules"), ("EOAT Assembly ID", "Folder Status", "Photo Count", "Missing Categories", "Source Path"), ("Do not use photo count alone.", "Prioritize missing connection, sensor, vacuum, and mounting views."), ("Most EOATs have folder found and required categories covered.", "Missing categories are specific enough for a photo pass."), ("Missing folder blocks visual verification.", "Partial coverage means the profile may still be hard to use."), ("Capture missing categories.", "Fix folder naming or index rows.", "Refresh Atlas."), "Reports & Handoff output folder.", ("photos", "coverage")),
        report("PM Checklist Export", "Creates inspection checklist content for offline weekly, monthly, or targeted EOAT review.", ("PM guidance", "EOAT profile warnings", "Standards entries"), ("Checklist Item", "Pass/Fail Criteria", "Finding", "Corrective Action", "Related Standard"), ("Use each row as a physical inspection task.", "Record findings back into the maintenance process."), ("Every item has pass/fail criteria.", "Findings map to corrective actions."), ("Repeated failures suggest standards or design issues.", "Blank findings after inspection reduce traceability."), ("Complete the checklist during inspection.", "Update source data and photos after corrective action."), "Reports & Handoff output folder.", ("pm", "checklist")),
        report("Executive Summary Export", "Condenses Atlas status into leadership-friendly coverage, risks, and next actions.", ("Atlas metrics", "Documentation gaps", "Compatibility counts", "Photo coverage"), ("Metric", "Current Value", "Risk", "Recommended Action"), ("Read it as project health, not setup instructions.", "Use linked detail reports for root cause."), ("Coverage is high and risks have named actions.", "Metrics match the refreshed Atlas UI."), ("Large gaps mean source data is not ready for handoff.", "Stale timestamp means regenerate before presenting."), ("Refresh data.", "Regenerate supporting reports.", "Use detail exports for action owners."), "Reports & Handoff output folder.", ("executive", "summary")),
    ]


def _pm_inspection_entries() -> list[InformationLibraryEntry]:
    source = _source("EOAT Preventive Maintenance Checklist", section="Inspection checklist")

    def pm(
        title: str,
        frequency: str,
        checklist: tuple[str, ...],
        criteria: tuple[str, ...],
        findings: tuple[str, ...],
        corrective: tuple[str, ...],
        standard: str,
        tags: tuple[str, ...],
    ) -> InformationLibraryEntry:
        return _entry(
            "pm_inspection",
            title,
            f"{frequency} inspection guidance for EOAT condition and documentation.",
            corrective[0] if corrective else "Record the finding and repair before reuse when safety or part handling is affected.",
            (
                _section("Inspection Frequency", frequency),
                _section("Checklist Items", *checklist),
                _section("Pass/Fail Criteria", *criteria),
                _section("Common Findings", *findings),
                _section("Corrective Actions", *corrective),
                _section("Related Standard", standard),
                _section("Source Documents", "EOAT Preventive Maintenance Checklist", "EOAT Standard Design Guidelines"),
            ),
            category="PM / Inspection",
            tags=("pm", "inspection", *tags),
            related_pages=("PM / Inspection", "EOAT Profiles", "Photos"),
            related_references=(standard,),
            source=source,
            tree_path=("PM / Inspection", title),
        )

    return [
        pm("Weekly EOAT Inspection", "Weekly or before high-risk reuse.", ("Inspect cups, grippers, tubing, sensors, cables, quick disconnects, and mounting hardware.", "Review current profile warnings.", "Confirm required photos exist for any new finding."), ("No loose hardware.", "No cracked cups or damaged grippers.", "No tubing/cable pinch risk.", "Warnings reviewed."), ("Worn cups.", "Loose cable ties.", "Missing photo evidence.", "Unresolved warning repeated across weeks."), ("Replace worn components.", "Secure routing.", "Update source notes/photos.", "Escalate repeated findings."), "Documentation Requirements", ("weekly",)),
        pm("Monthly EOAT Inspection", "Monthly or after repeated setup issues.", ("Review documentation completeness.", "Check repeated warnings.", "Verify spare/wear item notes.", "Confirm photos still represent current EOAT condition."), ("Critical fields complete.", "Recurring findings have corrective actions.", "Photos match current hardware."), ("Old photos.", "Same warning every month.", "Unknown cup or sensor type."), ("Run Documentation Gap Report.", "Update source workbook.", "Capture new photos.", "Review standards for recurring issues."), "Process Binder Expectations", ("monthly",)),
        pm("Vacuum Cup Inspection", "Weekly for active EOATs and during setup after storage.", ("Inspect cup wear, cracks, flattening, contamination, fittings, and cup count.", "Compare Cup Material and # Parts Picked with visible hardware."), ("Cups flexible and intact.", "Fittings tight.", "Cup material documented when relevant.", "Cup count supports pick pattern."), ("Cracked cup.", "Missing cup.", "Unknown material.", "Vacuum leak at fitting."), ("Replace cups.", "Tighten or replace fitting.", "Update Cup Material.", "Add close-up cup photo."), "Vacuum Cup Selection", ("vacuum", "cups")),
        pm("Pneumatic Tubing Inspection", "Weekly and after any EOAT repair or rerouting.", ("Check kinks, rubbing, pinch points, bend radius, fittings, and labels.", "Move the wrist through expected motion if safe."), ("Tubing stays clear through motion.", "No leaks or damaged fittings.", "Routes are visible or documented."), ("Pinched tube.", "Rubbing against bracket.", "Unlabeled branch.", "Loose fitting."), ("Reroute tubing.", "Add strain relief.", "Replace damaged tube.", "Update routing notes and photos."), "Pneumatic Tubing Routing", ("pneumatic", "tubing")),
        pm("Sensor Verification", "Before production run and after sensor or cable maintenance.", ("Confirm sensor mount.", "Check cable strain relief.", "Verify part-present response where used.", "Compare fields with visible hardware."), ("Sensor response is repeatable.", "Cable is secured.", "Part-present status is documented correctly."), ("Loose sensor bracket.", "False signal.", "Cable abrasion.", "Part-present field wrong."), ("Tighten or realign sensor.", "Repair cable.", "Update Part-Present Sensor field.", "Capture sensor photo."), "Sensor / Part-Present Standards", ("sensor",)),
        pm("Mounting Hardware Inspection", "Weekly for active EOATs and before setup after storage.", ("Check mounting bolts, brackets, adapter plate, cracks, witness marks, and missing washers.", "Confirm mounting photos exist."), ("Hardware tight and complete.", "No bent or cracked brackets.", "Mounting surface documented."), ("Missing bolt.", "Cracked bracket.", "Stripped thread.", "Mounting photo missing."), ("Replace hardware.", "Repair or quarantine damaged bracket.", "Add mounting photo.", "Record corrective action."), "Mounting Hardware and Fasteners", ("hardware", "fasteners")),
        pm("EOAT Alignment Check", "After EOAT changeover, collision, or part handling complaint.", ("Check pickup points, part contact, robot path clearance, and tool alignment.", "Review Moves and known issue notes."), ("Pickup is repeatable.", "No unexpected contact.", "Known alignment offsets are documented."), ("Part shift.", "Contact mark.", "Robot path rub.", "Undocumented adjustment."), ("Adjust EOAT alignment.", "Document offset or setup note.", "Capture updated photos.", "Escalate repeated alignment drift."), "EOAT Weight and Rigidity", ("alignment", "setup")),
        pm("Quick Disconnect Inspection", "Before setup and during weekly inspection for frequently changed EOATs.", ("Inspect pneumatic and electrical disconnects, labels, O-rings, locking action, and accessibility."), ("Disconnect locks securely.", "No damaged fittings.", "Connection Type matches visible hardware."), ("Air leak.", "Loose connector.", "Label missing.", "Wrong fitting type in source field."), ("Replace damaged fitting.", "Relabel connector.", "Update Connection Type.", "Add connection photo."), "Quick Disconnect Standards", ("quick disconnect",)),
        pm("Cable Management Check", "Weekly and after any sensor/cable repair.", ("Check tie points, abrasion, strain relief, connector seating, and pinch hazards."), ("Cables clear motion paths.", "Connectors seated.", "Sensor wires traceable."), ("Cable rubbing frame.", "Tie broken.", "Connector loose.", "Cable hides sensor identity."), ("Secure cable.", "Replace damaged wiring.", "Add strain relief.", "Update sensor/cable photos."), "Cable Management", ("cable",)),
    ]


def _static_source_document_entries() -> list[InformationLibraryEntry]:
    docs = [
        ("EOAT Standard Design Guidelines", "Design, documentation, and inspection expectations used by EOAT standard entries.", "Open it when a standards entry needs the original engineering context."),
        ("EOAT Preventive Maintenance Checklist", "Inspection checklist source for recurring PM and condition checks.", "Open it when an inspection item needs pass/fail wording or corrective action detail."),
        ("Robot EOAT Intern Project Charter", "Project scope reference for why Atlas emphasizes source traceability, handoff, and documentation quality.", "Use it to distinguish project deliverables from operating data."),
        ("Press Capacity Workbook", "Primary source for tool-to-machine compatibility.", "Repair capacity rows here when tools do not expand to machines."),
        ("EOAT Master Tracker", "Primary source for EOAT identity, tool links, technical fields, audit context, and documentation status.", "Repair source values here instead of editing Atlas output."),
        ("Photo Folder Index", "Source for folder and image paths used by the Photos page and photo coverage reports.", "Repair folder naming, source paths, or missing category photos here."),
        ("Generated Report", "Timestamped export produced from the loaded Atlas cache.", "Use the report timestamp to decide whether it reflects current source data."),
    ]
    entries = []
    for name, summary, takeaway in docs:
        entries.append(
            _entry(
                "source_document",
                name,
                summary,
                takeaway,
                (
                    _section("What It Contains", summary),
                    _section("How Atlas Uses It", takeaway),
                    _section("When To Open It", "Open the source when a warning, report, or profile needs provenance before repair."),
                    _section("Repair Boundary", "Source documents are opened read-only from Atlas; repairs happen in the owning workbook or document workflow."),
                ),
                category="Source Document References",
                tags=("source", "reference"),
                related_pages=("Standards & Work Instructions", "Settings / Diagnostics", "Reports & Handoff"),
                source=_source(name),
                tree_path=("Source Document References", name),
            )
        )
    return entries


def _source_document_entries(bundle: AtlasDataBundle) -> list[InformationLibraryEntry]:
    entries = []
    seen_paths: set[str] = set()
    for standard in bundle.standards:
        if not standard.path or standard.path in seen_paths:
            continue
        seen_paths.add(standard.path)
        source = LibrarySource(
            source_type=standard.title or "EOAT Standard Design Guidelines",
            document_name=standard.title or Path(standard.path).name,
            section=standard.category or "Standards & Work Instructions",
            file_path=standard.path,
            modified=_file_mtime(standard.path),
        )
        entries.append(
            _entry(
                "source_document",
                f"Source: {standard.title or Path(standard.path).name}",
                standard.snippet or "Indexed standards document available from the project standards library.",
                "Open the source document when the library summary is not enough for an engineering decision.",
                (
                    _section("What It Contains", standard.snippet or "Standards or project reference content indexed by Atlas."),
                    _section("How Atlas Uses It", "Adds source-aware reference entries and links EOAT profiles to likely standards context."),
                    _section("When To Open It", "Open before changing a standard, resolving a disputed interpretation, or preparing a handoff packet."),
                ),
                category="Source Document References",
                tags=("source", "standard", Path(standard.path).suffix.upper().lstrip(".") or "DOC"),
                related_pages=("Standards & Work Instructions", "Information Library"),
                source=source,
                tree_path=("Source Document References", "Indexed Standards", standard.title or Path(standard.path).name),
            )
        )
    return entries


def _warning_entries(bundle: AtlasDataBundle) -> list[InformationLibraryEntry]:
    warnings: list[WarningItem] = list(bundle.warnings)
    for eoat in bundle.eoats:
        warnings.extend(eoat.warnings[:2])
    entries: list[InformationLibraryEntry] = []
    for index, warning in enumerate(warnings[:60], start=1):
        title = warning.title or f"Atlas warning {index}"
        symptom = warning.message or title
        source_name = _known_source_name(warning.source)
        entries.append(
            _entry(
                "troubleshooting",
                f"Live warning: {title}",
                symptom,
                warning.suggested_fix or "Repair the source condition named by the warning, then refresh Atlas.",
                (
                    _section("Symptom", symptom),
                    _section("Likely Causes", warning.why_it_matters or "A source value, path, or relationship did not pass Atlas validation."),
                    _section("Checks To Run", "Open the related EOAT, machine, tool, or Settings source status.", "Check the source named in metadata."),
                    _section("Fix Steps", warning.suggested_fix or "Repair the source data and refresh Atlas."),
                    _section("Manual Workaround", "Use the visible warning context as a read-only note until the source can be repaired."),
                ),
                category="Troubleshooting",
                tags=tuple(value for value in (warning.severity, warning.source, warning.related_eoat_id, warning.machine, warning.tool) if value),
                related_fields=tuple(value for value in (warning.related_eoat_id, warning.machine, warning.tool) if value),
                related_pages=("EOAT Profiles", "Machine Profiles", "Settings / Diagnostics"),
                source=_source(source_name),
                tree_path=("Troubleshooting", "Live Atlas Warnings", title),
            )
        )
    return [_resolve_entry_source(entry, bundle) for entry in entries]


def _known_source_name(value: str) -> str:
    folded = str(value or "").casefold()
    if "press" in folded or "capacity" in folded:
        return "Press Capacity Workbook"
    if "photo" in folded:
        return "Photo Folder Index"
    if "standard" in folded:
        return "EOAT Standard Design Guidelines"
    if "robot" in folded:
        return "Robot EOAT Intern Project Charter"
    if "master" in folded or "inventory" in folded or "eoat" in folded:
        return "EOAT Master Tracker"
    return "Atlas internal reference"


def _resolve_entry_source(entry: InformationLibraryEntry, bundle: AtlasDataBundle) -> InformationLibraryEntry:
    source = entry.source
    if source.file_path:
        return entry
    paths = _source_path_lookup(bundle)
    key_candidates = [source.document_name, source.source_type]
    for key in key_candidates:
        path = paths.get(key.casefold())
        if path:
            return replace(entry, source=replace(source, file_path=path, modified=_file_mtime(path)))
    return entry


def _source_path_lookup(bundle: AtlasDataBundle) -> dict[str, str]:
    paths: dict[str, str] = {}
    for status in bundle.source_statuses:
        label = status.label.casefold()
        if "eoat master" in label:
            paths["eoat master tracker"] = status.path
        elif "press capacity" in label:
            paths["press capacity workbook"] = status.path
        elif "photo" in label:
            paths["photo folder index"] = status.path
        elif "standard" in label:
            paths.setdefault("eoat standard design guidelines", status.path)
    for standard in bundle.standards:
        folded = f"{standard.title} {standard.category} {standard.path}".casefold()
        if "pm" in folded or "maintenance" in folded:
            paths.setdefault("eoat preventive maintenance checklist", standard.path)
        if "standard" in folded or "guideline" in folded or "standardization" in folded:
            paths.setdefault("eoat standard design guidelines", standard.path)
    return paths


def _file_mtime(path: str | Path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0
