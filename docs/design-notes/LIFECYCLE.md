# Lifecycle Location

This repository is the source package for Agentic OS code, templates, schemas,
docs, and tests. It no longer owns its own planning or work-history lifecycle
folders.

Canonical lifecycle state for this project lives in the installed Agentic OS
project:

```text
<os-root>/<work-domain>/02-projects/genomes_agentic_os/
```

Use these installed OS buckets:

- `SPECS/` for future work, product specs, and proposed changes.
- `work-items/` for lifecycle state from intake through completion.
- `worklogs/` for human-readable work history and migrated source feature
  packets.
- `logs/` for raw runtime, transcript, and tool output.
- `artifacts/` for migration manifests and generated evidence.

Canonical vocabulary:

```text
<os-root>/<work-domain>/02-projects/genomes_agentic_os/VOCABULARY.md
```

The previous source-repo lifecycle surfaces were consolidated on 2026-06-15:

- `PLANS/` -> installed `SPECS/`
- `spec/` -> installed `SPECS/source-product-specs/`
- `features/` -> installed `worklogs/source-features/`
- `BUILD_LOGS/` -> installed `worklogs/source-build-logs/`

Migration receipt:

```text
<os-root>/<work-domain>/02-projects/genomes_agentic_os/artifacts/source-lifecycle-consolidation-2026-06-15/MANIFEST.md
```
