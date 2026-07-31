# EOAT Atlas 0.25.4 release candidate receipt

## Candidate identity

- Source commit: `445fcbd62aa9f830f8da0fb74e111939ff6cabfa`
- Branch: `integration/mirrorline-parity-completion-0.25.2`
- Application version: `0.25.4`
- Target database schema: `20260729_0009`
- API contract: `1.4.0`
- Build timestamp: `2026-07-31T01:06:20Z`

## Artifacts

| Artifact | SHA-256 | Validation |
| --- | --- | --- |
| Deployment tar `eoat-atlas-server-0.25.4-445fcbd.tar.gz` | `46420dc9b228ec6fe8c99bbeca7721b481c7eb8619d900546a58e1eb33c89fe9` | `validate_deployment_archive` passed; embedded manifest and external checksum agree |
| Deployment payload | `90caa228cf82d4411cafc2101de336a72a69216bd9fc246ff54d4e0bdbbd2c40` | Exact source payload plus static bundle |
| Static bundle manifest | `f3eec2275754ce2406905358ba1d55d0870c882f88af2afde435863425a74be8` | Included in the deployment tar host-template manifest |
| Server zip `eoat-atlas-server-0.25.4-445fcbd.zip` | `d1bd4c98f9b2a1284e02ca6e7b62a8d865a710043ea0f9e7adccb6c9ff847d98` | Builder validates archive bytes and every schema-0009 migration hash |

The artifacts are retained only in ignored local candidate storage:
`.local/release-artifacts/0.25.4/candidate/`. No tag, GitHub Release,
publication, host activation, or production data operation was performed.

## Candidate validation

The static builder completed locked dependency install, generated OpenAPI
contract verification, formatting, lint, type checking, 52-test Vitest,
theme check, and production build. The deployment archive was then built and
self-validated. The independent server archive verified its embedded migration
inventory against source commit `445fcbd`.
