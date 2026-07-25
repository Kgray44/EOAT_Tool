# EOAT Atlas HTTP web-host deployment

`install_http_web_host.py` is a self-contained privileged installer. It is
not executed from the repository or a home directory. The approved bootstrap
copies the installer, bundle, and JSON policy to root-owned paths and verifies
their SHA-256 values after the copy. The policy pins the installer hash, bundle
hash, active API release, schema, and expected frontend version.

The installer is currently versioned as `1.1.0` and has three actions:

- `preflight` is non-destructive. It validates root control, the complete
  bundle manifest, active API/schema/write state, local listener boundaries,
  the legacy hostname owner, the enabled default site, static assets, and an
  isolated complete NGINX configuration.
- `activate` creates a root-owned transaction under
  `/var/lib/eoat-atlas-http-web-host/transactions`, backs up the legacy API
  host config, site links, current frontend link, runtime token files, and
  then stages static files in `/var/www/eoat-atlas/releases/<release-id>`.
  Only after validation does it atomically point `current` at that release,
  replace the legacy hostname owner, disable the default enabled site, validate
  and reload NGINX, restart the API only because the server-side proxy token
  changed, wait for bounded health readiness, and run instrumented acceptance.
- `rollback` restores the recorded files and links, validates restored NGINX
  before reload, and does not touch MySQL, schema, release contents, or data.

The candidate server block is HTTP port 80 only. `/api/` is a separate,
non-SPA proxy location and forwards the original request URI to the localhost
API. The only token is generated during activation, held in root-controlled
server files, and injected by NGINX; it is never included in the bundle or
browser JavaScript.

The previous `install_http_web_host_0_20_1.sh` is an incident artifact and is
not a component of this mechanism.

The deployment-control root is deliberately a sibling of `/var/lib/eoat-atlas`,
not a child. The latter is service-owned and must remain outside the root trust
chain.

Static release permissions are a destination policy, never a property copied
from a bundle or developer checkout. The installer rejects links and special
files, copies bytes without preserving modes, then makes every served directory
`root:root 0755` and every regular file `root:root 0644`. Before it can point
`/var/www/eoat-atlas/current` at the release, it drops to the configured NGINX
worker account and verifies traversal, reads every index-referenced JavaScript
and CSS asset, reads a byte from each, and proves that account cannot write the
assets or their directories. Each result is emitted as a
`WEB_PERMISSION_CHECK` diagnostic. This prevents a restrictive source tree
such as `0750` from producing an activated but unreadable site.
