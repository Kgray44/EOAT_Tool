from __future__ import annotations

import pytest

from deployment.common import DeploymentError
from deployment.sudo_policy import audit_sudo_list, require_safe_noninteractive_sudo

HELPER = "(root) NOPASSWD: /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *"


@pytest.mark.parametrize(
    ("entries", "classification"),
    [
        ("(ALL : ALL) ALL\n" + HELPER, "INTERACTIVE_PASSWORD_REQUIRED"),
        (HELPER, "RESTRICTED_NOPASSWD_HELPER"),
    ],
)
def test_password_gated_admin_and_exact_helper_are_allowed(entries: str, classification: str) -> None:
    audit = require_safe_noninteractive_sudo(entries)
    assert classification in audit.classifications
    assert audit.restricted_helper_available


@pytest.mark.parametrize(
    "entry",
    [
        "(root) NOPASSWD: ALL",
        "(root) NOPASSWD: /bin/sh",
        "(root) NOPASSWD: /usr/local/libexec/eoat-atlas/*.py --request-b64 *",
    ],
)
def test_unrestricted_shell_and_wildcard_nopasswd_are_blocking(entry: str) -> None:
    output = HELPER + "\n" + entry
    audit = audit_sudo_list(output)
    assert not audit.accepted
    with pytest.raises(DeploymentError, match="Unsafe noninteractive sudo policy"):
        require_safe_noninteractive_sudo(output)


def test_missing_exact_helper_is_blocking() -> None:
    audit = audit_sudo_list("(ALL : ALL) ALL")
    assert not audit.restricted_helper_available
    assert "Exact EOAT Atlas NOPASSWD helper command is absent" in audit.blocking_violations


def test_exact_helper_is_only_noninteractive_transport_used_by_client() -> None:
    # Invocation construction is tested in test_phase3_client.  This policy
    # test makes the intended operational rule explicit: password-gated admin
    # is classified but never used as a deployment fallback.
    audit = require_safe_noninteractive_sudo("(ALL : ALL) ALL\n" + HELPER)
    assert audit.classifications == ("INTERACTIVE_PASSWORD_REQUIRED", "RESTRICTED_NOPASSWD_HELPER")
