"""Classify the noninteractive sudo surface used by Phase 3 automation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .common import DeploymentError

HELPER_COMMAND = "/usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *"
_ENTRY = re.compile(r"^\s*\((?P<runas>[^)]*)\)\s+(?:(?P<nopasswd>NOPASSWD):\s+)?(?P<command>.+?)\s*$")
_INTERACTIVE_ALL = re.compile(r"^\(ALL\s*:\s*ALL\)\s+ALL$")


@dataclass(frozen=True)
class SudoPolicyAudit:
    classifications: tuple[str, ...]
    restricted_helper_available: bool
    blocking_violations: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.restricted_helper_available and not self.blocking_violations


def audit_sudo_list(output: str) -> SudoPolicyAudit:
    """Audit `sudo -n -l` without confusing password-gated admin with NOPASSWD.

    The approved helper has a wildcard only for its opaque base64 payload. Any
    wildcard in a privileged executable path, shell, or broad NOPASSWD grant
    is a blocking deployment-policy violation.
    """
    classifications: list[str] = []
    violations: list[str] = []
    helper = False
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("("):
            continue
        match = _ENTRY.fullmatch(line)
        if not match:
            continue
        command = match.group("command").strip()
        nopasswd = bool(match.group("nopasswd"))
        if not nopasswd:
            if _INTERACTIVE_ALL.fullmatch(line):
                classifications.append("INTERACTIVE_PASSWORD_REQUIRED")
            continue
        if command == HELPER_COMMAND and match.group("runas").strip() == "root":
            classifications.append("RESTRICTED_NOPASSWD_HELPER")
            helper = True
            continue
        if command == "ALL":
            classifications.append("UNRESTRICTED_NOPASSWD")
            violations.append("NOPASSWD: ALL is prohibited")
            continue
        classifications.append("UNSAFE_NOPASSWD")
        if "/bin/sh" in command or "/bin/bash" in command:
            violations.append(f"NOPASSWD shell command is prohibited: {command}")
        elif "*" in command or "?" in command:
            violations.append(f"NOPASSWD wildcard command is prohibited: {command}")
        else:
            violations.append(f"Unexpected NOPASSWD command is prohibited: {command}")
    if not helper:
        violations.append("Exact EOAT Atlas NOPASSWD helper command is absent")
    return SudoPolicyAudit(tuple(classifications), helper, tuple(violations))


def require_safe_noninteractive_sudo(output: str) -> SudoPolicyAudit:
    audit = audit_sudo_list(output)
    if not audit.accepted:
        raise DeploymentError("Unsafe noninteractive sudo policy: " + "; ".join(audit.blocking_violations))
    return audit
