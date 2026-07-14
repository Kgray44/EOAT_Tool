# EOAT History PDF Export

`RecordHistoryTab` starts PDF generation through the application's background task mechanism. In `mysql_api` mode the export model is built from typed gateway/API history; it never reads Excel or legacy SQLite authority.

The report contains an EOAT cover/overview, generation timestamp and applied scope, API/MySQL or offline-cache source label, cache timestamp when applicable, event count, date range, type and machine summaries, the explicit pre-MySQL limitation, and complete matching activity. Events include applicable structured source, actor, machine/tool/robot/storage/document/photo references, reason/notes, verification, and scalar before/after changes.

Event details use split-safe ReportLab paragraphs so long notes can continue across pages without an oversized table-row failure. Standard headers/footers identify the EOAT and page. Empty history produces the honest `No documented lifecycle history is currently available for this EOAT.` state. Filenames are sanitized and timestamped.

The validated development artifact is `output/pdf/EOAT_History_P4-EOAT-0001_validation.pdf`: letter size, two pages, seven real MySQL-backed events, no credentials or internal connection information. Offline export is supported and labeled `Offline cached API history` with its cache timestamp.
