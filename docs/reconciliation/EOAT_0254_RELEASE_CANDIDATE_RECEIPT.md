# EOAT Atlas 0.25.4 release candidate receipt

## Candidate identity

- Source commit: `9312533239c9230f32aaefc852a8d5e0650f52b9`
- Branch: `integration/mirrorline-parity-completion-0.25.2`
- Application version: `0.25.4`
- Target database schema: `20260729_0009`
- API contract: `1.4.0`
- Build timestamp: `2026-07-31T01:19:18Z`

## Artifacts

| Artifact | SHA-256 | Validation |
| --- | --- | --- |
| Deployment tar `eoat-atlas-server-0.25.4-9312533.tar.gz` | `52114a2b3757e9e4af9130e4f4c4a758b36e3ef283f7f2e2df88d6e3ddcc4554` | `validate_deployment_archive` passed; embedded manifest and external checksum agree |
| Deployment manifest | `a14040571768eb523da08ba69627b2ab7599535d8d10fbb757299bff29caa86a` | External manifest binds exact commit, payload, static bundle, and deployment templates |
| Deployment payload | `6a504ad8a1747484d54ed3aa5bf014904aa52e300420fcb1ef59b150c4513d38` | Exact source payload plus static bundle |
| Static bundle manifest | `6ae8da765a11d6d29d61bedd1ac14eb783d1d66f63714ec10d319cdb665caf07` | Included in the deployment tar host-template manifest |
| Server zip `eoat-atlas-server-0.25.4-9312533.zip` | `9dcc00f47157c23c05f24806e975be858c7959731d6587e287f5524c53e71ea4` | Builder validates archive bytes and every schema-0009 migration hash |

The artifacts are retained only in ignored local candidate storage:
`.local/release-artifacts/0.25.4/candidate-9312533239/`. No tag, GitHub Release,
publication, host activation, or production data operation was performed.

## Candidate validation

The static builder completed locked dependency install, generated OpenAPI
contract verification, formatting, lint, type checking, 52-test Vitest,
theme check, and production build. The deployment archive was then built and
self-validated. The independent server archive verified its embedded migration
inventory against source commit `9312533`.
