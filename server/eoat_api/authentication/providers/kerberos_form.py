from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from ..provider_configuration import KerberosFormProviderConfiguration
from .base import AuthenticationProvider

_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SSF = re.compile(r"SASL SSF:\\s*(\\d+)")
_LIMITERS_LOCK = threading.Lock()
_SHARED_LOGIN_LIMITERS: dict[tuple[str, int, int], LoginAttemptLimiter] = {}
LOGGER = logging.getLogger("eoat_api.authentication")


def _safe_kerberos_failure_code(stage: str, stderr: bytes) -> str:
    message = stderr.decode("utf-8", "replace").casefold()
    if "cannot contact any kdc" in message or "cannot resolve network address" in message:
        return "KDC_UNREACHABLE"
    if "clock skew" in message:
        return "KERBEROS_CLOCK_SKEW"
    if stage == "KINIT_FAILED":
        if "client not found" in message or "principal unknown" in message:
            return "KINIT_PRINCIPAL_REJECTED"
        if "preauthentication failed" in message or "password incorrect" in message:
            return "KINIT_CREDENTIAL_REJECTED"
    return stage


def normalize_principal(username: str, realm: str) -> str:
    value = username.strip()
    if "\\" in value:
        domain, separator, account = value.partition("\\")
        if not separator or domain.casefold() != "gwp":
            raise AuthenticationUnavailableError("Invalid credentials")
    elif "@" in value:
        account, separator, supplied_realm = value.partition("@")
        if not separator or supplied_realm.casefold() not in {realm.casefold(), "gwplastics.com"}:
            raise AuthenticationUnavailableError("Invalid credentials")
    else:
        account = value
    if not _USERNAME.fullmatch(account):
        raise AuthenticationUnavailableError("Invalid credentials")
    return f"{account.casefold()}@{realm}"


def _ldap_escape(value: str) -> str:
    return value.replace("\\", r"\\5c").replace("*", r"\\2a").replace("(", r"\\28").replace(")", r"\\29").replace("\x00", r"\\00")


def _parse_ldif(output: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        if raw_line.startswith(" ") and current:
            result[current][-1] += raw_line[1:]
            continue
        if ":: " in raw_line:
            key, encoded = raw_line.split(":: ", 1)
            try:
                value = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                current = None
                continue
        elif ": " in raw_line:
            key, value = raw_line.split(": ", 1)
        else:
            current = None
            continue
        key = key.casefold()
        result.setdefault(key, []).append(value)
        current = key
    return result


@dataclass(frozen=True)
class DirectoryIdentity:
    username: str
    upn: str
    display_name: str
    distinguished_name: str
    groups: tuple[str, ...]


class LoginAttemptLimiter:
    def __init__(self, attempts: int, window_seconds: int):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, source: str) -> bool:
        now = time.monotonic()
        with self._lock:
            failures = self._failures[source]
            while failures and failures[0] <= now - self.window_seconds:
                failures.popleft()
            return len(failures) < self.attempts

    def record_failure(self, source: str) -> None:
        with self._lock:
            self._failures[source].append(time.monotonic())

    def reset(self, source: str) -> None:
        with self._lock:
            self._failures.pop(source, None)


def _shared_login_attempt_limiter(configuration: KerberosFormProviderConfiguration) -> LoginAttemptLimiter:
    key = (configuration.cache_directory, configuration.login_rate_limit_attempts, configuration.login_rate_limit_window_seconds)
    with _LIMITERS_LOCK:
        limiter = _SHARED_LOGIN_LIMITERS.get(key)
        if limiter is None:
            limiter = LoginAttemptLimiter(key[1], key[2])
            _SHARED_LOGIN_LIMITERS[key] = limiter
        return limiter


class KerberosCommandAuthenticator:
    def __init__(self, configuration: KerberosFormProviderConfiguration):
        self.configuration = configuration

    def authenticate(self, principal: str, password: str) -> DirectoryIdentity:
        root = Path(self.configuration.cache_directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        cache_dir = Path(tempfile.mkdtemp(prefix="krb5cc-", dir=root))
        os.chmod(cache_dir, 0o700)
        cache = cache_dir / "credential-cache"
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "KRB5CCNAME": f"FILE:{cache}"}
        try:
            self._run(["/usr/bin/kinit", "-c", environment["KRB5CCNAME"], principal], environment, password.encode() + b"\\n", failure_code="KINIT_FAILED")
            self._run(["/usr/bin/kvno", "ldap/us-vt-dc01.gwplastics.com"], environment, failure_code="LDAP_SERVICE_TICKET_FAILED")
            return self._lookup(self._discover_ldap_host(environment), principal, environment)
        finally:
            try:
                subprocess.run(["/usr/bin/kdestroy", "-c", environment["KRB5CCNAME"]], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
            finally:
                shutil.rmtree(cache_dir, ignore_errors=True)

    def _run(self, command: list[str], environment: dict[str, str], input_data: bytes | None = None, *, failure_code: str = "KERBEROS_COMMAND_FAILED") -> subprocess.CompletedProcess[bytes]:
        try:
            completed = subprocess.run(command, env=environment, input=input_data, capture_output=True, timeout=self.configuration.login_timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuthenticationUnavailableError("Kerberos authentication is unavailable", reason_code="KERBEROS_COMMAND_UNAVAILABLE") from exc
        if completed.returncode:
            reason_code = _safe_kerberos_failure_code(failure_code, completed.stderr)
            LOGGER.warning("kerberos_command_failed stage=%s reason_code=%s", failure_code, reason_code)
            raise AuthenticationUnavailableError("Kerberos authentication failed", reason_code=reason_code)
        return completed

    def _discover_ldap_host(self, environment: dict[str, str]) -> str:
        completed = self._run(["/usr/bin/dig", "+short", "_ldap._tcp.dc._msdcs.gwplastics.com", "SRV"], environment, failure_code="LDAP_SRV_DISCOVERY_FAILED")
        for line in completed.stdout.decode("utf-8", "replace").splitlines():
            values = line.split()
            if len(values) == 4 and values[3].endswith("."):
                return values[3].rstrip(".")
        raise AuthenticationUnavailableError("Kerberos directory discovery is unavailable", reason_code="LDAP_SRV_DISCOVERY_FAILED")

    def _lookup(self, host: str, principal: str, environment: dict[str, str]) -> DirectoryIdentity:
        account, _, _realm = principal.partition("@")
        query = "(&(objectClass=user)(|" f"(userPrincipalName={_ldap_escape(principal)})" f"(sAMAccountName={_ldap_escape(account)})" "))"
        completed = self._run(["/usr/bin/ldapsearch", "-LLL", "-Y", "GSSAPI", "-O", f"minssf={self.configuration.min_sasl_ssf}", "-H", f"ldap://{host}:389", "-b", self.configuration.base_dn, "-s", "sub", query, "sAMAccountName", "userPrincipalName", "displayName", "distinguishedName", "memberOf", "userAccountControl"], environment, failure_code="LDAP_GSSAPI_LOOKUP_FAILED")
        stderr = completed.stderr.decode("utf-8", "replace")
        ssf = _SSF.search(stderr)
        if not ssf or int(ssf.group(1)) < self.configuration.min_sasl_ssf or "SASL data security layer installed" not in stderr:
            raise AuthenticationUnavailableError("Kerberos directory security layer is unavailable", reason_code="LDAP_SASL_SECURITY_LAYER_UNAVAILABLE")
        values = _parse_ldif(completed.stdout.decode("utf-8", "replace"))
        account = values.get("samaccountname", [""])[0]
        upn = values.get("userprincipalname", [""])[0]
        distinguished_name = values.get("distinguishedname", values.get("dn", [""]))[0]
        missing = tuple(name for name, value in (("sAMAccountName", account), ("userPrincipalName", upn), ("dn", distinguished_name)) if not value)
        if missing:
            LOGGER.warning("ldap_identity_incomplete missing_fields=%s", ",".join(missing))
            raise AuthenticationUnavailableError("Directory identity lookup failed", reason_code="DIRECTORY_IDENTITY_UNAVAILABLE")
        control = int(values.get("useraccountcontrol", ["0"])[0])
        if control & 2:
            raise AuthenticationUnavailableError("Directory account is disabled", reason_code="DIRECTORY_ACCOUNT_DISABLED")
        return DirectoryIdentity(account, upn, values.get("displayname", [account])[0], distinguished_name, tuple(values.get("memberof", ())))


class KerberosFormAuthenticationProvider(AuthenticationProvider):
    name = "kerberos_form"

    def __init__(self, configuration: KerberosFormProviderConfiguration | None = None, authenticator: KerberosCommandAuthenticator | None = None):
        self.configuration = configuration or KerberosFormProviderConfiguration.from_environment()
        self.authenticator = authenticator or KerberosCommandAuthenticator(self.configuration)
        self.attempt_limiter = _shared_login_attempt_limiter(self.configuration)

    def begin_login(self, context: dict) -> dict:
        if self.configuration.missing_fields():
            raise AuthenticationUnavailableError("Kerberos login is unavailable")
        username, password = str(context.get("username") or ""), context.get("password")
        if not isinstance(password, str) or not password:
            raise AuthenticationUnavailableError("Invalid credentials")
        return {"principal": normalize_principal(username, self.configuration.realm), "password": password}

    def complete_login(self, response: dict) -> AuthenticatedIdentity:
        principal, password = str(response["principal"]), str(response["password"])
        directory = self.authenticator.authenticate(principal, password)
        groups = directory.groups
        if self.configuration.test_mode and directory.upn.casefold() in self.configuration.test_admin_upns:
            groups += ("kerberos-form-test-role:ADMINISTRATOR",)
        return AuthenticatedIdentity(external_subject=directory.upn.casefold(), username=directory.username, display_name=directory.display_name, email=directory.upn, provider=self.name, group_identifiers=groups, authentication_time=datetime.now(timezone.utc), authentication_method="kerberos_password_then_ldap_gssapi")

    def health_check(self) -> ProviderHealth:
        missing = self.configuration.missing_fields()
        return ProviderHealth(self.name, not missing, not missing, False, "Kerberos form login is configured" if not missing else "Kerberos form login is not configured", missing)
