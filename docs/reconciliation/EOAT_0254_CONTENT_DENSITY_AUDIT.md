# EOAT Atlas 0.25.4 content-density audit

This source-level audit compares the canonical desktop minimalist modules with
the browser candidate. It is not a claim of completed live side-by-side visual
acceptance; that evidence belongs in the parity receipt.

| Surface | Original browser text / treatment | Final treatment | Decision | Desktop comparison |
| --- | --- | --- | --- | --- |
| Home | Center search and local result guidance | Retained; typing stays local and global search remains intentional | Retain | `minimalist/home.py` has the same Home-centered search model |
| Library | Free-form filter spelling and mixed activity/status wording | Authoritative labelled selectors, short activity control, URL-backed state | Revise | Desktop Library owns browse/filter defaults; browser avoids duplicate explanatory copy |
| EOAT, Machine, Tool profiles | Raw legacy relationship/source wording could become primary content | Shared business-semantic label with expandable evidence | Revise | Desktop records distinguish observations; browser removes migration vocabulary from primary text |
| Machine Overview | Ungrouped null-prone details | Identity, operation, capacity, robot, and current setup sections; truthful unknowns | Revise | Desktop Machine details are grouped; browser exposes only governed fields |
| Fit Check | Safety and stale-result explanations | Retained because engineering-use ambiguity is material | Retain | Desktop Fit Check warns on stale/incomplete results |
| Settings navigation and sections | Lock/authentication state | Retained and concise; no browser edit path is implied | Retain | Desktop Settings locks administration until authentication |
| Diagnostics, Support, Danger Zone | Destructive/safety context | Retained where present; not decorative | Retain | Desktop exposes those as safety-oriented sections |
| Menus and search overlays | Generic navigation labels | Retained; no implementation wording introduced | Retain | Desktop overlay has Home, Fit Check, Library, Settings |
| Dialogs | Confirmation/error copy | Retained only for failure, destructive action, or ambiguity | Retain | Desktop confirmations carry the same purpose |
| Empty/loading/error states | Raw sentinel and backend state exposure risk | State components use user-facing unknown/unavailable labels | Revise | Desktop uses explicit no-record and locked/unavailable messages |
| Authentication-disabled state | Potential suggestion that administrator sign-in works | States Settings authentication is unavailable and controls remain locked | Revise | Desktop says normal use is unaffected while Settings remain locked |

No decorative replacement text was added. Safety, provenance disclosure,
accessibility labels, and meaningful unknown/stale states remain intentionally
visible. Focused browser and component evidence covers the revised relationship
and Machine content; the full visual parity evidence is still tracked
separately.
