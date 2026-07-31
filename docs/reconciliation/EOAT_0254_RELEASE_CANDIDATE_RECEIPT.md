# EOAT Atlas 0.25.4 release candidate receipt

## Candidate identity

- Source commit: `b67d9d053d3fb5223d06bc4acad75f9617a85b6e`
- Branch: `integration/mirrorline-parity-completion-0.25.2`
- Application version: `0.25.4`
- Target database schema: `20260729_0009`
- API contract: `1.4.0`
- Build timestamp: `2026-07-31T01:31:28Z`

## Artifacts

| Artifact | SHA-256 | Validation |
| --- | --- | --- |
| Deployment tar `eoat-atlas-server-0.25.4-b67d9d0.tar.gz` | `45aba99be122ef088522964a240234d41cc85dd78ffa770d0452f4545fabde70` | `validate_deployment_archive` passed; embedded manifest and external checksum agree |
| Deployment manifest | `62936aeb3361c23796cd4eb3691c5068d3fb14042c2cdcea427268ade3f9b12f` | External manifest binds exact commit, payload, static bundle, and deployment templates |
| Deployment payload | `e756c370e5db8858afe6d6960969c0b79ea40762a0a8aed32f56529bc3cf9094` | Exact source payload plus static bundle |
| Static bundle manifest | `4de3dc4b620fd7ae23c5367e2a5ea373861ab70abf9887c710b13ce351912ba2` | Included in the deployment tar host-template manifest |
| Server zip `eoat-atlas-server-0.25.4-b67d9d0.zip` | `4fd9a1691edec3d252b35d33de80cddcc5c4c293a34e95754b41df5ad6a5d23a` | Builder validates archive bytes and every schema-0009 migration hash |

The artifacts are retained only in ignored local candidate storage:
`.local/release-artifacts/0.25.4/candidate-b67d9d053d/`. No tag, GitHub Release,
publication, host activation, or production data operation was performed.

## Candidate validation

The static builder completed locked dependency install, generated OpenAPI
contract verification, formatting, lint, type checking, 52-test Vitest,
theme check, and production build. The deployment archive was then built and
self-validated. The independent server archive verified its embedded migration
inventory against source commit `b67d9d`.
