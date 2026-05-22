# Specification

Feature 56 adds a read-only source-package preflight for Codex configuration assets.

The validator checks required source files before install or sync and reports optional profile-layer files as warnings. Required failures block the command. Optional layer files are warning-level so the installer can continue while profile templates are introduced by adjacent work.

The CLI entrypoint is:

```bash
agentic-os validate-source --source /path/to/genomes_agentic_os
```

Generated installs remain validated through:

```bash
agentic-os validate --root /path/to/generated/os
```
