# Settings And Defaults

Date: 2026-05-27

Phase: 2 - Audit Workflow Stabilization

## Local Config

Settings are saved to ignored local config:

`config/local_config.json`

Do not commit local config files. They may contain project roots or local operational preferences.

## Audit Defaults

The Settings page now includes an initial Audit Defaults section. These values feed new Audit page forms while preserving the prior behavior by default.

Initial editable defaults include:

- Auditor.
- Plant/Area.
- Cleanroom/Non-Cleanroom.
- Status.
- Priority.
- Follow-Up Needed.
- Quick Disconnects Present.
- Pneumatic Quick Disconnect Type.
- Vacuum Generator Type.
- EOAT Interchangeable Circuits.
- Robot Interchangeable Circuits.
- Photos Taken.

Defaults are defined centrally in `core/audit/defaults.py` and can be overridden by local config.

## Connection Defaults

The Settings page also exposes initial connection defaults for changeover difficulty:

- ATI.
- DoveTail.

These values are used by the Audit page smart default behavior when Changeover Difficulty has not been manually set.

## Operational Sections

The Settings page includes initial read-only operational sections for:

- Scheduled Reports.
- Safety / Backups.

These sections are intentionally informational in Phase 2. Scheduled report editing and deeper backup management remain future-phase work.
