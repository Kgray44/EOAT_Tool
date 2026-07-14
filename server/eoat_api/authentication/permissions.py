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

ROLE_PERMISSIONS = {
    "VIEWER": frozenset(),
    "TECHNICIAN": frozenset(),
    "ENGINEER": frozenset(),
    "ADMINISTRATOR": SETTINGS_PERMISSIONS,
}


def effective_permissions(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    result: set[str] = set()
    for role in roles:
        result.update(ROLE_PERMISSIONS.get(str(role).upper(), frozenset()))
    return frozenset(result)
