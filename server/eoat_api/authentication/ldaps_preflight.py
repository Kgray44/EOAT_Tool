"""Anonymous, TLS-verified LDAPS readiness checks.

This module deliberately does not accept credentials and never emits raw LDAP
entries. It is suitable for a controlled production connectivity preflight,
not as a directory inventory tool.
"""
from __future__ import annotations

import hashlib
import socket
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class EndpointReceipt:
    address_fingerprint: str
    family: str
    tcp_connected: bool
    tls_verified: bool
    certificate_subject: str
    certificate_issuer: str
    certificate_san_matches_hostname: bool
    certificate_not_before: str | None
    certificate_not_after: str | None
    cipher: str | None
    rootdse_available: bool
    default_naming_context: str | None
    root_domain_naming_context: str | None
    configuration_naming_context: str | None
    supported_ldap_versions: tuple[str, ...]
    supported_controls: tuple[str, ...]
    error_classification: str | None = None


def _fingerprint_address(address: str) -> str:
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]


def _certificate_name(values: tuple[tuple[tuple[str, str], ...], ...] | tuple) -> str:
    parts = []
    for sequence in values or ():
        parts.extend(f"{key}={value}" for key, value in sequence)
    return ", ".join(parts)


def _iso_certificate_date(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).isoformat()


def _discover_rootdse(host: str, port: int, timeout: int, ca_path: str | None) -> dict[str, object]:
    """Perform a minimal anonymous RootDSE base search through ldap3."""
    from ldap3 import BASE, Connection, Server, Tls

    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_path or None, version=ssl.PROTOCOL_TLS_CLIENT)
    server = Server(host, port=port, use_ssl=True, tls=tls, connect_timeout=timeout)
    with Connection(server, auto_bind=True, receive_timeout=timeout, raise_exceptions=True) as connection:
        connection.search(
            search_base="",
            search_filter="(objectClass=*)",
            search_scope=BASE,
            attributes=[
                "defaultNamingContext",
                "rootDomainNamingContext",
                "configurationNamingContext",
                "supportedLDAPVersion",
                "supportedControl",
            ],
        )
        if not connection.entries:
            raise RuntimeError("RootDSE did not return an entry")
        values = connection.entries[0].entry_attributes_as_dict
    return {
        "default": _first(values.get("defaultNamingContext")),
        "root": _first(values.get("rootDomainNamingContext")),
        "configuration": _first(values.get("configurationNamingContext")),
        "versions": tuple(str(value) for value in values.get("supportedLDAPVersion", ())),
        "controls": tuple(str(value) for value in values.get("supportedControl", ())),
    }


def _first(value: object) -> str | None:
    if isinstance(value, list | tuple):
        value = value[0] if value else None
    return str(value) if value else None


def run_preflight(
    host: str = "gwplastics.com", port: int = 636, *, timeout_seconds: int = 5, attempts: int = 4, ca_path: str | None = None
) -> dict[str, object]:
    """Return a sanitized receipt for every resolved endpoint attempted.

    The platform trust store, hostname verification, and certificate-chain
    verification are mandatory. A failed endpoint is reported; no insecure
    fallback or retry with weaker TLS is attempted.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    unique: list[tuple[int, tuple]] = []
    seen: set[tuple[int, str]] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        key = (family, sockaddr[0])
        if key not in seen:
            seen.add(key)
            unique.append((family, sockaddr))
    context = ssl.create_default_context(cafile=ca_path)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    receipts: list[EndpointReceipt] = []
    for family, sockaddr in unique[: max(1, attempts)]:
        address = sockaddr[0]
        empty = dict(
            address_fingerprint=_fingerprint_address(address), family="ipv6" if family == socket.AF_INET6 else "ipv4",
            tcp_connected=False, tls_verified=False, certificate_subject="", certificate_issuer="",
            certificate_san_matches_hostname=False, certificate_not_before=None, certificate_not_after=None,
            cipher=None, rootdse_available=False, default_naming_context=None, root_domain_naming_context=None,
            configuration_naming_context=None, supported_ldap_versions=(), supported_controls=(),
        )
        try:
            with socket.socket(family, socket.SOCK_STREAM) as raw:
                raw.settimeout(timeout_seconds)
                raw.connect(sockaddr)
                empty["tcp_connected"] = True
                with context.wrap_socket(raw, server_hostname=host) as tls_socket:
                    certificate = tls_socket.getpeercert()
                    empty.update(
                        tls_verified=True,
                        certificate_subject=_certificate_name(certificate.get("subject", ())),
                        certificate_issuer=_certificate_name(certificate.get("issuer", ())),
                        certificate_san_matches_hostname=True,
                        certificate_not_before=_iso_certificate_date(certificate.get("notBefore")),
                        certificate_not_after=_iso_certificate_date(certificate.get("notAfter")),
                        cipher=tls_socket.cipher()[0] if tls_socket.cipher() else None,
                    )
            rootdse = _discover_rootdse(host, port, timeout_seconds, ca_path)
            empty.update(
                rootdse_available=True,
                default_naming_context=rootdse["default"], root_domain_naming_context=rootdse["root"],
                configuration_naming_context=rootdse["configuration"], supported_ldap_versions=rootdse["versions"],
                supported_controls=rootdse["controls"],
            )
        except ssl.SSLCertVerificationError as exc:
            empty["error_classification"] = f"certificate_validation:{exc.verify_code}"
        except TimeoutError:
            empty["error_classification"] = "timeout"
        except socket.gaierror:
            empty["error_classification"] = "dns_failure"
        except Exception as exc:  # diagnostics remain classification-only
            empty["error_classification"] = type(exc).__name__
        receipts.append(EndpointReceipt(**empty))
    return {
        "endpoint": f"ldaps://{host}:{port}",
        "host": host,
        "port": port,
        "resolved_address_count": len(unique),
        "attempted_endpoint_count": len(receipts),
        "all_tls_verified": bool(receipts) and all(row.tls_verified for row in receipts),
        "all_rootdse_available": bool(receipts) and all(row.rootdse_available for row in receipts),
        "endpoints": [asdict(row) for row in receipts],
    }
