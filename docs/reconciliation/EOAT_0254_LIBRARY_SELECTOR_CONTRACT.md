# EOAT Atlas 0.25.4 Library selector contract

Library filters remain URL-backed. The browser requests bounded authoritative
options from `GET /api/v1/catalog-options/{kind}`; it never downloads catalog
records merely to invent selector choices. Supported kinds are status, EOAT
type, plant, area, cleanroom classification, machine, tool, mold, robot, and
EOAT. Requests are limited to 100 options and normally use 50.

Selectors are searchable native autocomplete controls. Their chosen values are
sent unchanged to the server catalog routes, preserving refresh, history,
pagination, sorting, category, and profile-return context. Invalid historic
URL values are treated as server-side filters and safely yield no matching
records rather than being translated into another value.

Machine options use the canonical `plant_code::machine_number` value, for
example `P4::27`, while the browser displays the readable Plant and Machine
label. This prevents a duplicate machine number at another plant from silently
changing a related EOAT or Tool filter, or a Library result route. Historic
plain-number URLs remain readable but the server's existing ambiguity guard
refuses to choose a plant arbitrarily. Option rows trim empty values and
deduplicate values before returning a bounded response.

`web/src/pages/DiscoveryPage.test.tsx` covers authoritative option retrieval,
an individual clear action, URL-backed combined filtering, and catalog requests.
`tests/test_catalog_options.py` verifies the bounded option endpoint contract
and plant-qualified machine-value parsing.
