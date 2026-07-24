#!/usr/bin/env python3
"""Root-owned, transactional installer for the EOAT Atlas HTTP web host.

This file is intentionally self-contained.  It is copied to a root-controlled
directory before execution and never imports deployment code from a writable
checkout.  Its policy file pins both this program and the static-only bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


class InstallError(RuntimeError):
    pass


HOST = "eoat-atlas.gwplastics.com"
API_HEALTH = "http://127.0.0.1:8765/api/v1/health"
API_RELEASE_LINK = Path("/opt/eoat-atlas/current")
RUNTIME_ENV = Path("/etc/eoat-atlas/runtime.env")
UPSTREAM_TOKEN = Path("/etc/eoat-atlas/nginx-upstream-token.conf")
LEGACY_CONFIG = Path("/etc/nginx/conf.d/eoat-atlas-api.conf")
SITE_CONFIG = Path("/etc/nginx/sites-available/eoat-atlas-http-web.conf")
SITE_ENABLED = Path("/etc/nginx/sites-enabled/eoat-atlas-http-web.conf")
DEFAULT_ENABLED = Path("/etc/nginx/sites-enabled/default")
WEB_ROOT = Path("/var/www/eoat-atlas")
# This must not sit below /var/lib/eoat-atlas: that service-owned parent is an
# intentional EOAT boundary and therefore cannot anchor root-trusted files.
CONTROL_ROOT = Path("/var/lib/eoat-atlas-http-web-host")
TRANSACTION_ROOT = CONTROL_ROOT / "transactions"
FORBIDDEN_CONTENT = (b"EOAT_API_DEVICE_TOKEN", b"X-EOAT-Device-Token", b"mysql://")
DEVELOPMENT_API_URL = re.compile(rb"https?://(?:localhost|127[.]0[.]0[.]1)(?::[0-9]+)?/api(?:/|[^A-Za-z0-9_-])", re.I)
FORBIDDEN_PATH_PARTS = {"node_modules"}
FORBIDDEN_SUFFIXES = {".map", ".env", ".pem", ".key"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(items: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_root_owned(path: Path, *, executable: bool = False) -> None:
    if path.is_symlink():
        raise InstallError(f"symlink rejected for root-controlled path: {path}")
    info = path.stat()
    if info.st_uid != 0 or info.st_gid != 0:
        raise InstallError(f"root ownership required: {path}")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise InstallError(f"group/world writable path rejected: {path}")
    if executable and not info.st_mode & stat.S_IXUSR:
        raise InstallError(f"owner executable permission required: {path}")


def require_root_chain(path: Path) -> None:
    """Prevent replacement through a writable parent after the file hash check."""
    current = path.parent
    while current != current.parent:
        require_root_owned(current)
        current = current.parent


def require_root_tree(path: Path) -> None:
    require_root_owned(path)
    for item in path.rglob("*"):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise InstallError(f"unsafe root-controlled bundle member: {item}")
        require_root_owned(item)


def bundle_files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in sorted(root.rglob("*")):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise InstallError(f"unsafe bundle member: {item}")
        if item.is_file() and item.name not in {"manifest.json", "bundle.json"}:
            relative = item.relative_to(root).as_posix()
            if not relative.startswith("web/") and relative != "nginx/eoat-atlas-http-web.conf.template":
                raise InstallError(f"unexpected bundle member: {relative}")
            if any(part in FORBIDDEN_PATH_PARTS for part in Path(relative).parts) or item.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise InstallError(f"forbidden bundle path: {relative}")
            content = item.read_bytes()
            if relative.startswith("web/") and (any(value in content for value in FORBIDDEN_CONTENT) or DEVELOPMENT_API_URL.search(content)):
                raise InstallError(f"forbidden browser-visible content: {relative}")
            result[relative] = sha256(item)
    return result


def verify_bundle(root: Path, expected_sha: str) -> dict[str, object]:
    expected_dirs = {"web", "nginx"}
    expected_files = {"bundle.json", "manifest.json"}
    if not root.is_dir() or {p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink()} != expected_dirs or {p.name for p in root.iterdir() if p.is_file() and not p.is_symlink()} != expected_files:
        raise InstallError("bundle has unexpected top-level members")
    if set((root / "nginx").iterdir()) != {root / "nginx" / "eoat-atlas-http-web.conf.template"}:
        raise InstallError("bundle nginx directory has unexpected members")
    for required in (root / "web" / "index.html", root / "manifest.json", root / "bundle.json"):
        if not required.is_file():
            raise InstallError(f"required bundle file missing: {required}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    current = bundle_files(root)
    if not isinstance(manifest, dict) or manifest != current:
        raise InstallError("bundle manifest mismatch")
    metadata = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    if metadata.get("content_sha256") != canonical(manifest):
        raise InstallError("bundle content identity mismatch")
    actual = canonical({**manifest, "bundle.json": sha256(root / "bundle.json"), "manifest.json": sha256(root / "manifest.json")})
    if actual != expected_sha:
        raise InstallError("bundle SHA-256 does not match approved policy")
    return {"manifest": manifest, "metadata": metadata, "bundle_sha256": actual}


def policy_load(path: Path, installer: Path) -> dict[str, object]:
    require_root_owned(installer, executable=True)
    require_root_owned(path)
    require_root_chain(installer)
    require_root_chain(path)
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {"installer_sha256", "bundle_path", "bundle_sha256", "application_version", "api_release", "schema"}
    if not required.issubset(policy):
        raise InstallError("policy is missing required approved values")
    if sha256(installer) != policy["installer_sha256"]:
        raise InstallError("installer SHA-256 does not match approved policy")
    return policy


def http_json(url: str, timeout: float = 5.0) -> tuple[int, str, dict[str, object]]:
    request = urllib.request.Request(url, headers={"Host": HOST})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, response.headers.get("Content-Type", ""), json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            data: dict[str, object] = json.loads(raw)
        except json.JSONDecodeError:
            data = {"body": raw}
        return error.code, error.headers.get("Content-Type", ""), data


def api_health(policy: dict[str, object]) -> dict[str, object]:
    status, content_type, data = http_json(API_HEALTH)
    if status != 200 or "json" not in content_type or not isinstance(data, dict):
        raise InstallError(f"local API health failed: status={status} content_type={content_type}")
    schema = data.get("schema") if isinstance(data.get("schema"), dict) else {}
    if schema.get("current") != policy["schema"] or schema.get("expected") != policy["schema"]:
        raise InstallError("active schema differs from approved policy")
    if data.get("writes_enabled") is not False:
        raise InstallError("production writes are not disabled")
    return data


def wait_api(policy: dict[str, object], attempts: int = 12, interval: float = 1.0) -> None:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            api_health(policy)
            print(f"EOAT_API_READINESS attempt={attempt} result=ready", flush=True)
            return
        except Exception as error:  # readiness diagnostics intentionally contain no secrets
            errors.append(f"attempt={attempt} {error}")
            print(f"EOAT_API_READINESS attempt={attempt} result=not-ready detail={error}", flush=True)
            time.sleep(interval)
    raise InstallError("API readiness timeout: " + "; ".join(errors))


def active_release() -> str:
    if not API_RELEASE_LINK.is_symlink():
        raise InstallError(f"active API release link missing: {API_RELEASE_LINK}")
    return str(API_RELEASE_LINK.resolve())


def nginx_files() -> list[Path]:
    paths = [Path("/etc/nginx/nginx.conf")]
    for pattern in ("/etc/nginx/conf.d/*", "/etc/nginx/sites-enabled/*", "/etc/nginx/sites-available/*"):
        paths.extend(sorted(Path("/").glob(pattern.lstrip("/"))))
    return [path for path in paths if path.is_file() or path.is_symlink()]


def hostname_owners() -> list[Path]:
    return [path for path in nginx_files() if path.is_file() and HOST in path.read_text(encoding="utf-8", errors="replace")]


def mysql_loopback_only() -> bool:
    output = subprocess.run(["/usr/bin/ss", "-ltn"], text=True, capture_output=True, check=True).stdout
    mysql_lines = [line for line in output.splitlines() if re.search(r":3306(?:0)?\s", line)]
    return bool(mysql_lines) and all("127.0.0.1:" in line or "[::1]:" in line for line in mysql_lines)


def api_loopback_only() -> bool:
    output = subprocess.run(["/usr/bin/ss", "-ltn"], text=True, capture_output=True, check=True).stdout
    lines = [line for line in output.splitlines() if re.search(r":8765\s", line)]
    return bool(lines) and all("127.0.0.1:8765" in line for line in lines)


def nginx_worker_user() -> str:
    config = Path("/etc/nginx/nginx.conf").read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*user\s+([^\s;]+)", config, re.MULTILINE)
    return match.group(1) if match else "www-data"


def render(template: str, *, root: Path, token_include: Path) -> str:
    rendered = template.replace("@EOAT_WEB_ROOT@", str(root)).replace("@EOAT_UPSTREAM_TOKEN_INCLUDE@", str(token_include))
    if "@EOAT_" in rendered:
        raise InstallError("unresolved NGINX template token")
    prohibited = ("listen 443", "ssl_", "Strict-Transport-Security", "https://", "return 301 https", "return 302 https")
    if any(term.lower() in rendered.lower() for term in prohibited):
        raise InstallError("candidate NGINX config violates HTTP-only policy")
    required = ("listen 80", "server_name eoat-atlas.gwplastics.com", "location ^~ /api/", "try_files $uri $uri/ /index.html")
    if any(term not in rendered for term in required):
        raise InstallError("candidate NGINX config misses a required routing rule")
    return rendered


def validate_isolated(rendered: str, static_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="eoat-nginx-validate-") as temporary:
        temp = Path(temporary)
        token = temp / "token.conf"
        token.write_text("set $eoat_atlas_upstream_token validation_only;\n", encoding="utf-8")
        server = temp / "site.conf"
        server.write_text(rendered.replace(str(UPSTREAM_TOKEN), str(token)).replace(str(WEB_ROOT / "current"), str(static_root)), encoding="utf-8")
        config = temp / "nginx.conf"
        config.write_text("pid " + str(temp / "nginx.pid") + ";\nerror_log stderr notice;\nevents {}\nhttp {\n include /etc/nginx/mime.types;\n include " + str(server) + ";\n}\n", encoding="utf-8")
        completed = subprocess.run(["/usr/sbin/nginx", "-t", "-p", str(temp), "-c", str(config)], text=True, capture_output=True)
        if completed.returncode:
            raise InstallError("isolated nginx validation failed: " + (completed.stderr + completed.stdout).strip())


def assert_static_assets(root: Path) -> tuple[str, str | None]:
    index = (root / "index.html").read_text(encoding="utf-8")
    if "EOAT" not in index.upper():
        raise InstallError("frontend index does not identify EOAT Atlas")
    scripts = re.findall(r"(?:src)=['\"]([^'\"]+\.js)['\"]", index)
    styles = re.findall(r"(?:href)=['\"]([^'\"]+\.css)['\"]", index)
    if not scripts or not (root / scripts[0].lstrip("/")).is_file():
        raise InstallError("frontend JavaScript asset is missing")
    if styles and not (root / styles[0].lstrip("/")).is_file():
        raise InstallError("frontend CSS asset is missing")
    return scripts[0], styles[0] if styles else None


def preflight(policy: dict[str, object]) -> dict[str, object]:
    bundle = Path(str(policy["bundle_path"]))
    require_root_chain(bundle)
    require_root_tree(bundle)
    verified = verify_bundle(bundle, str(policy["bundle_sha256"]))
    metadata = verified["metadata"]
    if metadata.get("application_version") != policy["application_version"] or metadata.get("api_upstream") != "127.0.0.1:8765" or metadata.get("server_name") != HOST:
        raise InstallError("bundle metadata does not match approved policy")
    if active_release() != policy["api_release"]:
        raise InstallError("active API release differs from approved policy")
    health = api_health(policy)
    if not api_loopback_only() or not mysql_loopback_only():
        raise InstallError("API or MySQL listener violates localhost-only policy")
    owners = hostname_owners()
    if owners != [LEGACY_CONFIG]:
        raise InstallError("unexpected hostname conflict(s): " + ", ".join(map(str, owners)))
    if not LEGACY_CONFIG.is_file() or not DEFAULT_ENABLED.is_symlink():
        raise InstallError("legacy API config or enabled default site is not in expected state")
    template = (bundle / "nginx" / "eoat-atlas-http-web.conf.template").read_text(encoding="utf-8")
    assert_static_assets(bundle / "web")
    rendered = render(template, root=WEB_ROOT / "current", token_include=UPSTREAM_TOKEN)
    validate_isolated(rendered, bundle / "web")
    free_bytes = shutil.disk_usage("/var/www").free
    if free_bytes < 100 * 1024 * 1024:
        raise InstallError("insufficient free space for frontend deployment")
    return {"bundle_sha256": verified["bundle_sha256"], "api_health": health, "hostname_owner": str(LEGACY_CONFIG), "default_site": os.readlink(DEFAULT_ENABLED), "nginx_worker_user": nginx_worker_user(), "free_bytes": free_bytes}


def atomic_symlink(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(link.name + ".new-" + uuid.uuid4().hex)
    os.symlink(str(target), temporary)
    os.replace(temporary, link)


def stage_frontend(bundle_web: Path, release_id: str) -> Path:
    """Copy a verified static tree into an immutable, NGINX-readable release."""
    staging = WEB_ROOT / "releases" / (release_id + ".staging-" + uuid.uuid4().hex[:8])
    final = WEB_ROOT / "releases" / release_id
    if final.exists() or staging.exists():
        raise InstallError("refusing to overwrite an existing frontend release")
    shutil.copytree(bundle_web, staging, copy_function=shutil.copy2)
    for item in [staging, *staging.rglob("*")]:
        os.chown(item, 0, 0)
        os.chmod(item, 0o755 if item.is_dir() else 0o644)
    assert_static_assets(staging)
    os.replace(staging, final)
    return final


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=False)


def copy_path_backup(path: Path, backup: Path) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "exists": path.exists() or path.is_symlink(), "kind": "absent"}
    if path.is_symlink():
        record.update(kind="symlink", target=os.readlink(path))
    elif path.is_file():
        record.update(kind="file", backup=str(backup))
        copy_file(path, backup)
    return record


def restore_backup(record: dict[str, object]) -> None:
    path = Path(str(record["path"]))
    if path.exists() or path.is_symlink():
        path.unlink()
    if not record.get("exists"):
        return
    if record["kind"] == "symlink":
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(record["target"]), path)
    elif record["kind"] == "file":
        copy_file(Path(str(record["backup"])), path)


def write_receipt(transaction: Path, receipt: dict[str, object]) -> None:
    (transaction / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def set_runtime_token(token: str) -> None:
    original = RUNTIME_ENV.read_text(encoding="utf-8")
    lines = [line for line in original.splitlines() if not line.startswith("EOAT_API_DEVICE_TOKEN=")]
    lines.append("EOAT_API_DEVICE_TOKEN=" + token)
    RUNTIME_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    UPSTREAM_TOKEN.write_text("set $eoat_atlas_upstream_token " + token + ";\n", encoding="utf-8")
    os.chmod(UPSTREAM_TOKEN, 0o640)


def nginx_test_reload() -> None:
    tested = subprocess.run(["/usr/sbin/nginx", "-t"], text=True, capture_output=True)
    if tested.returncode:
        raise InstallError("nginx -t failed: " + (tested.stderr + tested.stdout).strip())
    reloaded = subprocess.run(["/bin/systemctl", "reload", "nginx"], text=True, capture_output=True)
    if reloaded.returncode:
        raise InstallError("nginx reload failed: " + (reloaded.stderr + reloaded.stdout).strip())


def request_check(name: str, url: str, expected: int, *, contains: str | None = None, excludes: str | None = None, json_body: bool = False, content_type_contains: str | None = None) -> dict[str, object]:
    command = ["/usr/bin/curl", "--silent", "--show-error", "--location", "--max-redirs", "0", "--resolve", HOST + ":80:127.0.0.1", "-D", "-", "-o", "-", "-w", "\nEOAT_STATUS:%{http_code}\nEOAT_CONTENT_TYPE:%{content_type}\nEOAT_CURL_EXIT:%{exitcode}\n", url]
    completed = subprocess.run(command, text=True, capture_output=True)
    payload = completed.stdout
    status_match = re.search(r"EOAT_STATUS:(\d+)", payload)
    type_match = re.search(r"EOAT_CONTENT_TYPE:([^\n]*)", payload)
    response = {"name": name, "url": url, "expected_status": expected, "actual_status": int(status_match.group(1)) if status_match else None, "content_type": type_match.group(1) if type_match else "", "curl_exit": completed.returncode, "excerpt_sha256": hashlib.sha256(payload[:512].encode()).hexdigest()}
    response_text = payload[: payload.rfind("EOAT_STATUS:")]
    response["excerpt"] = response_text[:160]
    print("EOAT_ACCEPTANCE " + json.dumps(response, sort_keys=True), flush=True)
    if completed.returncode or response["actual_status"] != expected or (contains and contains not in response_text) or (excludes and excludes in response_text) or (json_body and "json" not in str(response["content_type"])) or (content_type_contains and content_type_contains not in str(response["content_type"]).lower()):
        raise InstallError("acceptance failed: " + json.dumps(response, sort_keys=True))
    return response


def acceptance(release: Path, policy: dict[str, object]) -> list[dict[str, object]]:
    script, style = assert_static_assets(release)
    checks = [request_check("homepage", "http://" + HOST + "/", 200, contains="EOAT", excludes="Welcome to nginx!", content_type_contains="text/html"), request_check("javascript", "http://" + HOST + "/" + script.lstrip("/"), 200, content_type_contains="javascript")]
    if style:
        checks.append(request_check("css", "http://" + HOST + "/" + style.lstrip("/"), 200, content_type_contains="text/css"))
    checks.extend([request_check("api_health", "http://" + HOST + "/api/v1/health", 200, json_body=True, excludes="<html"), request_check("frontend_refresh", "http://" + HOST + "/fit-check", 200, contains="EOAT"), request_check("api_404", "http://" + HOST + "/api/v1/not-a-real-route", 404, json_body=True, excludes="<html")])
    headers = subprocess.run(["/usr/bin/curl", "--silent", "--show-error", "--resolve", HOST + ":80:127.0.0.1", "-D", "-", "-o", "/dev/null", "http://" + HOST + "/"], text=True, capture_output=True)
    header_text = headers.stdout.lower()
    if headers.returncode or "strict-transport-security:" in header_text or re.search(r"^location:\s*https://", header_text, re.MULTILINE):
        raise InstallError("HTTP-only acceptance failed")
    if not api_loopback_only() or not mysql_loopback_only() or active_release() != policy["api_release"]:
        raise InstallError("post-activation listener or release boundary failed")
    api_health(policy)
    return checks


def rollback(transaction: Path, policy: dict[str, object]) -> None:
    transaction = transaction.resolve()
    if TRANSACTION_ROOT not in transaction.parents:
        raise InstallError("rollback transaction is outside the approved transaction root")
    require_root_chain(transaction)
    require_root_owned(transaction)
    receipt = json.loads((transaction / "receipt.json").read_text(encoding="utf-8"))
    for record in reversed(receipt["backups"]):
        restore_backup(record)
    release = receipt.get("installed_release")
    if release:
        candidate = Path(str(release))
        if candidate.is_dir():
            shutil.rmtree(candidate)
    nginx_test_reload()
    # The transaction changes the server-side device token only during
    # activation.  Restart once after restoring its files so the healthy API
    # process and restored NGINX include agree; never touch MySQL.
    if receipt.get("runtime_token_changed") is True:
        restarted = subprocess.run(["/bin/systemctl", "restart", "eoat-atlas.service"], text=True, capture_output=True)
        if restarted.returncode:
            raise InstallError("rollback API restart failed: " + (restarted.stderr + restarted.stdout).strip())
        wait_api(policy)
    receipt["rollback_state"] = "complete"
    receipt["activation_state"] = "rolled_back"
    write_receipt(transaction, receipt)


def activate(policy: dict[str, object]) -> Path:
    preflight(policy)
    bundle = Path(str(policy["bundle_path"]))
    transaction = TRANSACTION_ROOT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    (transaction / "backup").mkdir(parents=True, mode=0o700)
    backups = [
        copy_path_backup(LEGACY_CONFIG, transaction / "backup" / "eoat-atlas-api.conf"),
        copy_path_backup(SITE_CONFIG, transaction / "backup" / "eoat-atlas-http-web.conf"),
        copy_path_backup(SITE_ENABLED, transaction / "backup" / "site-enabled"),
        copy_path_backup(DEFAULT_ENABLED, transaction / "backup" / "default-enabled"),
        copy_path_backup(WEB_ROOT / "current", transaction / "backup" / "frontend-current"),
        copy_path_backup(RUNTIME_ENV, transaction / "backup" / "runtime.env"),
        copy_path_backup(UPSTREAM_TOKEN, transaction / "backup" / "nginx-upstream-token.conf"),
    ]
    receipt: dict[str, object] = {"timestamp": datetime.now(timezone.utc).isoformat(), "backups": backups, "completed_steps": ["backup"], "activation_state": "started", "rollback_state": "not_needed", "runtime_token_changed": False, "hashes": {"bundle": policy["bundle_sha256"]}}
    write_receipt(transaction, receipt)
    try:
        release_id = str(verify_bundle(bundle, str(policy["bundle_sha256"]))["metadata"]["release_id"])
        final = stage_frontend(bundle / "web", release_id)
        receipt["installed_release"] = str(final)
        receipt["completed_steps"].append("frontend_staged")
        template = (bundle / "nginx" / "eoat-atlas-http-web.conf.template").read_text(encoding="utf-8")
        SITE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        SITE_CONFIG.write_text(render(template, root=WEB_ROOT / "current", token_include=UPSTREAM_TOKEN), encoding="utf-8")
        os.chown(SITE_CONFIG, 0, 0); os.chmod(SITE_CONFIG, 0o644)
        LEGACY_CONFIG.unlink()
        if DEFAULT_ENABLED.exists() or DEFAULT_ENABLED.is_symlink(): DEFAULT_ENABLED.unlink()
        atomic_symlink(SITE_CONFIG, SITE_ENABLED)
        atomic_symlink(final, WEB_ROOT / "current")
        receipt["completed_steps"].append("frontend_activated")
        token = hashlib.sha256(os.urandom(64)).hexdigest()
        receipt["runtime_token_changed"] = True
        write_receipt(transaction, receipt)
        set_runtime_token(token)
        receipt["completed_steps"].append("nginx_staged")
        write_receipt(transaction, receipt)
        nginx_test_reload()
        receipt["completed_steps"].append("nginx_activated")
        subprocess.run(["/bin/systemctl", "restart", "eoat-atlas.service"], check=True, text=True, capture_output=True)
        wait_api(policy)
        receipt["activation_state"] = "active"
        receipt["acceptance"] = acceptance(final, policy)
        write_receipt(transaction, receipt)
        return transaction
    except Exception as error:
        receipt["failure"] = str(error)
        write_receipt(transaction, receipt)
        try:
            rollback(transaction, policy)
        except Exception as rollback_error:
            raise InstallError(f"activation failed: {error}; rollback incomplete: {rollback_error}") from error
        raise InstallError(f"activation failed and rollback completed: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("action", choices=("preflight", "activate", "rollback"))
    parser.add_argument("--transaction", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise InstallError("root execution is required")
    policy = policy_load(args.policy, Path(__file__).resolve())
    if args.action == "preflight":
        print(json.dumps(preflight(policy), sort_keys=True))
    elif args.action == "activate":
        print(json.dumps({"transaction": str(activate(policy))}, sort_keys=True))
    else:
        if not args.transaction:
            raise InstallError("--transaction is required for rollback")
        rollback(args.transaction, policy)
        print(json.dumps({"transaction": str(args.transaction), "rollback": "complete"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as error:
        print("EOAT_HTTP_WEB_HOST_ERROR: " + str(error), flush=True)
        raise SystemExit(1)
