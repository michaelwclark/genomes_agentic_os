# Installer Validation

Installer validation has two read-only checks.

## Source Package Preflight

Run this from any checkout before install or sync:

```bash
agentic-os validate-source --source /path/to/genomes_agentic_os
```

Required Codex config sources fail the command when missing:

- `docs/07-agent-surfaces/codex-config-toml-inventory.md`
- `templates/agent-config/codex-config-layer-map.yml`

Optional layer configs produce warnings so early installs remain possible while profile templates are being introduced:

- `docs/07-agent-surfaces/codex-config-profiles.md`
- `templates/agent-config/codex-profiles.toml`
- `templates/agent-config/codex-profile-manifest.yml`

## Generated Install Check

Validate a generated install without mutating it:

```bash
tmpdir=$(mktemp -d)
agentic-os init --target "$tmpdir/os"
agentic-os validate --root "$tmpdir/os"
agentic-os validate-source --source /path/to/genomes_agentic_os
```

`validate-source` checks source package readiness. `validate` checks the installed OS tree. Neither command writes to the generated install.
