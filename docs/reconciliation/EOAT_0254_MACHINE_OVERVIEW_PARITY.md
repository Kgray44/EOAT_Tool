# EOAT Atlas 0.25.4 Machine Overview parity

## Governed browser sections

| Browser section | Governed fields | Truth rule |
| --- | --- | --- |
| Identity and status | Number, name, manufacturer, model, machine type, controller, active state | Missing values display `Not recorded`; no substitute value is invented. |
| Location and operation | Plant, section/area, cleanroom, operational status, installation date, notes | Uses available catalog fields only. |
| Press capacity | `press_capacity_tons` | A null remains null; the UI explicitly says missing capacity is not estimated. |
| Robot system | Robot number/name, manufacturer, model, controller, payload, reach, mounting, communication, status | No robot capacity is relabelled as press capacity. |
| Current assignment and compatibility | Current EOAT/tool plus translated evidence state | Unverified and historical states remain distinct from current/verified. |

## Machine 27 contract

The focused browser fixture resolves the Plant 4 identity for Machine 27 and
asserts a null current capacity, not the unimported candidate value. It shows
the fixture robot as a Machine 27 robot and asserts that `165` is absent.
The capacity readiness record preserves the separate candidate proof of 165 US
tons at workbook row 99. No browser, API, or production record conflates those
two states.

Focused evidence: `EntityProfilePage.test.tsx` (4 passed) and isolated
`machine-profile.spec.ts` (7 passed). The latter also verifies browser refresh,
read-only requests, relationship semantics, unavailable-media behavior, and
the P4 Machine 27 Overview fixture.
