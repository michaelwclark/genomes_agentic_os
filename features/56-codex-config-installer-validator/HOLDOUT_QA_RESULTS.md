# Holdout QA Results

Passed:

```bash
uv run --extra dev pytest -q
# 42 passed in 2.98s
```

Passed with expected optional warnings:

```bash
uv run --extra dev agentic-os validate-source --source .
```

Warnings were for optional feature-55-owned layer profile files:

- `docs/07-agent-surfaces/codex-config-profiles.md`
- `templates/agent-config/codex-profiles.toml`
- `templates/agent-config/codex-profile-manifest.yml`

Passed generated-install validation without mutating the install after generation:

```bash
tmpdir=$(mktemp -d)
uv run --extra dev agentic-os init --target "$tmpdir/os"
uv run --extra dev agentic-os validate --root "$tmpdir/os"
```
