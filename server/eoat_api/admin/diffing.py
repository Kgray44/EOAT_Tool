from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .redaction import redact


@dataclass(frozen=True)
class MaterialDiff:
    changed_fields: list[str]
    before: dict[str, Any]
    after: dict[str, Any]


def material_diff(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> MaterialDiff:
    """Produce a shallow, material-field diff after persistence normalization.

    A missing key is preserved by omission, while a present null remains null.
    Callers supply authoritative values read from the transaction, not browser
    payloads.  Nested objects remain safely structured values at Phase 1.
    """
    old = dict(before or {})
    new = dict(after or {})
    changed = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key) or (key in old) != (key in new))
    return MaterialDiff(
        changed_fields=changed,
        before={key: redact(old[key], key=key) for key in changed if key in old},
        after={key: redact(new[key], key=key) for key in changed if key in new},
    )
