from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import models as db


def resolve_roles(session: Session, provider: str, groups: tuple[str, ...]) -> tuple[str, ...]:
    if provider == "development":
        roles = [value.split(":", 1)[1] for value in groups if value.startswith("development-role:")]
        return tuple(sorted(set(roles)))
    temporary_roles = {
        value.split(":", 1)[1]
        for value in groups
        if provider == "kerberos_form" and value.startswith("kerberos-form-test-role:")
    }
    directory_groups = tuple(value for value in groups if not value.startswith("kerberos-form-test-role:"))
    if not directory_groups:
        return tuple(sorted(temporary_roles))
    if not groups:
        return ()
    rows = session.scalars(
        select(db.ExternalGroupRoleMapping).where(
            db.ExternalGroupRoleMapping.provider == provider,
            db.ExternalGroupRoleMapping.external_group_identifier.in_(directory_groups),
            db.ExternalGroupRoleMapping.is_active.is_(True),
        )
    ).all()
    if any(row.explicit_deny for row in rows):
        return ()
    return tuple(sorted({*temporary_roles, *(row.role_code for row in rows)}))
