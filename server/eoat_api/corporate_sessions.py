"""Kerberos-form corporate authentication and opaque browser sessions.

Passwords are accepted only by :class:`KerberosCommandAuthenticator`, passed to
``kinit`` through stdin, then discarded.  Directory role identifiers never
leave this module as a browser response or audit payload.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import models as db
from .errors import APIError

CORPORATE_SESSION_COOKIE = "eoat_corporate_session"
CORPORATE_CSRF_COOKIE = "eoat_corporate_csrf"
CORPORATE_CSRF_HEADER = "X-EOAT-CSRF-Token"
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SSF = re.compile(r"SASL SSF:\s*(\d+)")
_ROLE_PRIORITY = ("ADMINISTRATOR", "ENGINEER", "TECHNICIAN", "VIEWER")


class CorporateAuthenticationFailure(Exception):
    """Safe failure which never includes a credential or directory response."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class KerberosFormConfiguration:
    realm: str
    base_dn: str
    cache_directory: str
    login_timeout_seconds: int
    min_sasl_ssf: int
    session_minutes: int

    @classmethod
    def from_environment(cls) -> KerberosFormConfiguration:
        try:
            timeout = int(os.getenv("EOAT_KERBEROS_LOGIN_TIMEOUT_SECONDS", "15"))
            minimum_ssf = int(os.getenv("EOAT_KERBEROS_MIN_SASL_SSF", "256"))
            session_minutes = int(os.getenv("EOAT_AUTH_SESSION_MINUTES", "15"))
        except ValueError as exc:
            raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="CONFIGURATION_INVALID") from exc
        result = cls(
            realm=os.getenv("EOAT_KERBEROS_REALM", "").strip().upper(),
            base_dn=os.getenv("EOAT_KERBEROS_BASE_DN", "").strip(),
            cache_directory=os.getenv("EOAT_KERBEROS_CACHE_DIRECTORY", "").strip(),
            login_timeout_seconds=timeout,
            min_sasl_ssf=minimum_ssf,
            session_minutes=session_minutes,
        )
        if not result.realm or not result.base_dn or not result.cache_directory:
            raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="CONFIGURATION_INCOMPLETE")
        if not 1 <= result.login_timeout_seconds <= 60 or result.min_sasl_ssf < 56 or not 1 <= result.session_minutes <= 60:
            raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="CONFIGURATION_INVALID")
        return result


@dataclass(frozen=True)
class DirectoryIdentity:
    username: str
    upn: str
    display_name: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class IssuedCorporateSession:
    token: str
    csrf_token: str
    session_reference: str
    expires_at: datetime
    username: str
    display_name: str
    roles: tuple[str, ...]


class DirectoryAuthenticator(Protocol):
    def authenticate(self, principal: str, password: str) -> DirectoryIdentity: ...


def normalize_principal(username: str, realm: str) -> str:
    value = username.strip()
    if "\\" in value:
        domain, separator, account = value.partition("\\")
        if not separator or domain.casefold() != "gwp":
            raise CorporateAuthenticationFailure("Invalid credentials.", reason_code="INVALID_CREDENTIALS")
    elif "@" in value:
        account, separator, supplied_realm = value.partition("@")
        if not separator or supplied_realm.casefold() not in {realm.casefold(), "gwplastics.com"}:
            raise CorporateAuthenticationFailure("Invalid credentials.", reason_code="INVALID_CREDENTIALS")
    else:
        account = value
    if not _USERNAME.fullmatch(account):
        raise CorporateAuthenticationFailure("Invalid credentials.", reason_code="INVALID_CREDENTIALS")
    return f"{account.casefold()}@{realm}"


def _ldap_escape(value: str) -> str:
    return value.replace("\\", r"\5c").replace("*", r"\2a").replace("(", r"\28").replace(")", r"\29").replace("\x00", r"\00")


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
        current = key.casefold()
        result.setdefault(current, []).append(value)
    return result


class KerberosCommandAuthenticator:
    """Authenticate one credential through a private cache and protected LDAP."""

    def __init__(self, configuration: KerberosFormConfiguration) -> None:
        self.configuration = configuration

    def _run(
        self,
        command: list[str],
        environment: dict[str, str],
        password: bytes | None = None,
        *,
        credential_check: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            completed = subprocess.run(
                command,
                env=environment,
                input=password,
                capture_output=True,
                timeout=self.configuration.login_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="KERBEROS_UNAVAILABLE") from exc
        if completed.returncode:
            raise CorporateAuthenticationFailure(
                "Invalid credentials." if credential_check else "Authentication is unavailable.",
                reason_code="KERBEROS_REJECTED" if credential_check else "DIRECTORY_LOOKUP_FAILED",
            )
        return completed

    def authenticate(self, principal: str, password: str) -> DirectoryIdentity:
        root = Path(self.configuration.cache_directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        cache_dir = Path(tempfile.mkdtemp(prefix="krb5cc-", dir=root))
        os.chmod(cache_dir, 0o700)
        cache = cache_dir / "credential-cache"
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "KRB5CCNAME": f"FILE:{cache}"}
        try:
            self._run(
                ["/usr/bin/kinit", "-c", environment["KRB5CCNAME"], principal],
                environment,
                password.encode() + b"\n",
                credential_check=True,
            )
            self._run(["/usr/bin/kvno", "ldap/us-vt-dc01.gwplastics.com"], environment)
            discovered = self._run(
                ["/usr/bin/dig", "+short", "_ldap._tcp.dc._msdcs.gwplastics.com", "SRV"], environment
            )
            hosts = [line.split()[3].rstrip(".") for line in discovered.stdout.decode("utf-8", "replace").splitlines() if len(line.split()) == 4 and line.split()[3].endswith(".")]
            if not hosts:
                raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="LDAP_DISCOVERY_FAILED")
            account, _, _ = principal.partition("@")
            query = f"(&(objectClass=user)(|(userPrincipalName={_ldap_escape(principal)})(sAMAccountName={_ldap_escape(account)})))"
            lookup = self._run(
                [
                    "/usr/bin/ldapsearch", "-LLL", "-Y", "GSSAPI", "-O", f"minssf={self.configuration.min_sasl_ssf}",
                    "-H", f"ldap://{hosts[0]}:389", "-b", self.configuration.base_dn, "-s", "sub", query,
                    "sAMAccountName", "userPrincipalName", "displayName", "memberOf", "userAccountControl",
                ],
                environment,
            )
            stderr = lookup.stderr.decode("utf-8", "replace")
            secured = _SSF.search(stderr)
            if not secured or int(secured.group(1)) < self.configuration.min_sasl_ssf or "SASL data security layer installed" not in stderr:
                raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="LDAP_SECURITY_UNAVAILABLE")
            values = _parse_ldif(lookup.stdout.decode("utf-8", "replace"))
            username = values.get("samaccountname", [""])[0]
            upn = values.get("userprincipalname", [""])[0]
            if not username or not upn or int(values.get("useraccountcontrol", ["0"])[0]) & 2:
                raise CorporateAuthenticationFailure("Invalid credentials.", reason_code="DIRECTORY_IDENTITY_REJECTED")
            return DirectoryIdentity(username, upn, values.get("displayname", [username])[0], tuple(values.get("memberof", ())))
        finally:
            try:
                subprocess.run(["/usr/bin/kdestroy", "-c", environment["KRB5CCNAME"]], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
            finally:
                shutil.rmtree(cache_dir, ignore_errors=True)


class CorporateSessionService:
    def __init__(self, session: Session, *, authenticator: DirectoryAuthenticator | None = None) -> None:
        self.session = session
        self.configuration = KerberosFormConfiguration.from_environment()
        self.authenticator = authenticator or KerberosCommandAuthenticator(self.configuration)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _roles(self, groups: tuple[str, ...]) -> tuple[str, ...]:
        if not groups:
            return ()
        rows = self.session.scalars(
            select(db.ExternalGroupRoleMapping).where(
                db.ExternalGroupRoleMapping.provider == "kerberos_form",
                db.ExternalGroupRoleMapping.external_group_identifier.in_(groups),
                db.ExternalGroupRoleMapping.is_active.is_(True),
            )
        ).all()
        if any(row.explicit_deny for row in rows):
            return ()
        return tuple(sorted({row.role_code for row in rows if row.role_code in _ROLE_PRIORITY}))

    def _event(self, event_type: str, result: str, *, user_id: int | None = None, reason_code: str | None = None) -> None:
        self.session.add(
            db.CorporateAuthenticationEvent(
                event_uuid=str(uuid4()),
                event_type=event_type,
                occurred_at=datetime.now(timezone.utc),
                result=result,
                user_id=user_id,
                provider="kerberos_form",
                reason_code=reason_code,
            )
        )

    def login(self, username: str, password: str) -> IssuedCorporateSession:
        try:
            principal = normalize_principal(username, self.configuration.realm)
            identity = self.authenticator.authenticate(principal, password)
        except CorporateAuthenticationFailure as exc:
            self._event("LOGIN", "DENIED", reason_code=exc.reason_code)
            status = 503 if exc.reason_code not in {"INVALID_CREDENTIALS", "KERBEROS_REJECTED", "DIRECTORY_IDENTITY_REJECTED"} else 401
            raise APIError(
                status,
                "CORPORATE_AUTHENTICATION_UNAVAILABLE" if status == 503 else "CORPORATE_AUTHENTICATION_FAILED",
                "Corporate authentication is temporarily unavailable." if status == 503 else "Corporate sign-in could not be verified.",
                retryable=status == 503,
            ) from exc
        subject = identity.upn.casefold()
        user = self.session.scalar(select(db.User).where(db.User.external_identity == subject))
        now = datetime.now(timezone.utc)
        if user is None:
            user = db.User(
                external_identity=subject,
                username=identity.username.casefold(),
                display_name=identity.display_name,
                authentication_provider="kerberos_form",
                last_login_at=now,
                source_system="corporate_auth",
                created_at=now,
                updated_at=now,
            )
            self.session.add(user)
            self.session.flush()
        elif not user.is_active or user.archived_at is not None:
            self._event("LOGIN", "DENIED", user_id=user.id, reason_code="USER_INACTIVE")
            raise APIError(403, "CORPORATE_IDENTITY_INACTIVE", "Corporate sign-in is not authorized.")
        else:
            user.username = identity.username.casefold()
            user.display_name = identity.display_name
            user.authentication_provider = "kerberos_form"
            user.last_login_at = now
        roles = self._roles(identity.groups)
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=self.configuration.session_minutes)
        row = db.CorporateAuthenticationSession(
            session_reference=str(uuid4()),
            token_hash=self._hash(token),
            csrf_token_hash=self._hash(csrf_token),
            user_id=user.id,
            provider="kerberos_form",
            roles_json=list(roles),
            authenticated_at=now,
            issued_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
        self.session.add(row)
        self._event("LOGIN", "SUCCEEDED", user_id=user.id)
        return IssuedCorporateSession(token, csrf_token, row.session_reference, expires_at, user.username, user.display_name, roles)

    def resolve(self, token: str) -> tuple[db.CorporateAuthenticationSession, db.User]:
        if not token:
            raise APIError(401, "CORPORATE_SESSION_REQUIRED", "A corporate session is required.")
        row = self.session.scalar(select(db.CorporateAuthenticationSession).where(db.CorporateAuthenticationSession.token_hash == self._hash(token)))
        now = datetime.now(timezone.utc)
        if row is None or row.revoked_at is not None or _as_utc(row.expires_at) <= now:
            raise APIError(401, "CORPORATE_SESSION_EXPIRED", "The corporate session is expired or unavailable.")
        user = self.session.get(db.User, row.user_id)
        if user is None or not user.is_active or user.archived_at is not None:
            row.revoked_at = now
            row.revoke_reason = "identity_inactive"
            self._event("SESSION", "DENIED", user_id=row.user_id, reason_code="USER_INACTIVE")
            raise APIError(403, "CORPORATE_SESSION_REVOKED", "The corporate session is no longer authorized.")
        row.last_seen_at = now
        return row, user

    def revoke(self, token: str) -> None:
        row, user = self.resolve(token)
        row.revoked_at = datetime.now(timezone.utc)
        row.revoke_reason = "logout"
        self._event("LOGOUT", "SUCCEEDED", user_id=user.id)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def corporate_csrf_valid(row: db.CorporateAuthenticationSession, submitted: str) -> bool:
    return bool(submitted) and hmac.compare_digest(row.csrf_token_hash, hashlib.sha256(submitted.encode("utf-8")).hexdigest())
