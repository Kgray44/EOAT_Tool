SETTINGS_PERMISSIONS = frozenset(
    {
        "settings.read",
        "settings.edit",
        "settings.set_default",
        "settings.import",
        "settings.restore",
        "settings.authentication.configure",
    }
)

TECHNICIAN_PERMISSIONS = frozenset(
    {
        "installation.write",
        "audit.write",
        "maintenance.write",
        "annotation.write",
        "tag.assign",
        "fit_check.write",
        "instance.register",
    }
)

ENGINEER_PERMISSIONS = TECHNICIAN_PERMISSIONS | frozenset(
    {
        "asset.write",
        "compatibility.write",
        "document.write",
        "tag.manage",
        "installation.override_compatibility",
    }
)

ADMINISTRATOR_PERMISSIONS = ENGINEER_PERMISSIONS | SETTINGS_PERMISSIONS | frozenset({"*"})

ROLE_PERMISSIONS = {
    "VIEWER": frozenset(),
    "TECHNICIAN": TECHNICIAN_PERMISSIONS,
    "ENGINEER": ENGINEER_PERMISSIONS,
    "ADMINISTRATOR": ADMINISTRATOR_PERMISSIONS,
}


def effective_permissions(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    result: set[str] = set()
    for role in roles:
        result.update(ROLE_PERMISSIONS.get(str(role).upper(), frozenset()))
    return frozenset(result)
