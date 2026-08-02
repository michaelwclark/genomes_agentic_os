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
| Publish targets | GitHub Release; three multi-architecture OCI images |
| Release assets | Wheel, source distribution, checksums, release manifest, image-lock receipt, emergency bundle, configuration-schema bundle, SPDX SBOM |
| Provenance | Adjacent to each OCI image build |
