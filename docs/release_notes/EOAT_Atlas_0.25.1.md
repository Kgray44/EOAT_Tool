# EOAT Atlas 0.25.1 release notes

EOAT Atlas 0.25.1 supersedes the branch-only 0.24.2 functional-parity
candidate before mainline convergence. Version 0.24.2 was never merged,
tagged, published, or deployed.

- Home typing remains in the center search; global search opens only by its
  explicit control or Ctrl/Cmd+K.
- EOAT, Machine, and Tool profiles use real, routable tabs. Library browsing
  adds server-backed filtering, sorting, pagination, thumbnail previews, and
  restored context.
- Settings now use the authorized administrator session flow with staged
  save, reload, reset, and typed Danger Zone controls. Operational EOAT
  writes remain disabled.
- Fit Check discovers compatible options server-side, supports every input
  selection order, clears invalid prior choices, and remains non-persisting.
- Press-capacity import and governed media-hosting tooling are included with
  cache-safe browser media delivery.
- The parity work is integrated with the 0.25.0 physical-identity model:
  schema migration `20260729_0009`, stable physical EOAT UUIDs, design/family
  identity, source aliases, and corrected physical-unit mappings are retained.

Production deployment requires the governed schema migration from
`20260721_0008` to `20260729_0009`, followed by verified press-capacity and
media migrations before coordinated API/web activation.
