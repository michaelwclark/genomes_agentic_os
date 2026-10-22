# Releasing Agentic OS

The policy is owned by the [canonical release contract](docs/release-contract.md).
This page contains only the Agentic OS adapter values.

| Adapter field | Value |
| --- | --- |
| Repository role | Agentic OS |
| `integration_ref` | `main` |
| `release_ref` | `main` |
| Version source | `[project].version` in `pyproject.toml` |
| Current trigger | Push of an existing `v*` tag |
| `tag_mode` | `verify` (installed) |
| Publish targets | GitHub Release; five multi-architecture OCI images |
| Release assets | Wheel, source distribution, checksums, release manifest, image-lock receipt, emergency bundle, configuration-schema bundle, SPDX SBOM |
| Provenance | Adjacent to each OCI image build |

The two MinIO images package the exact signed upstream server and client
payloads selected in the [source input lock](deploy/execution-fabric/minio/upstream-lock.json).
Their [build and runtime checks](deploy/execution-fabric/minio/README.md) run
before the complete release is published. PostgreSQL and Valkey continue to
use their reviewed upstream multi-architecture images. The image lock contains
all seven runtime roles; the GitHub Release still requires all eight assets.
