# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
```

Then verify:

- The guide names all six profiles.
- The manifest includes model behavior, skills, prompt files, MCP availability,
  environment assumptions, and logging/telemetry posture for each profile.
- The guide documents the universal agent/brain convention.
- The guide documents precedence and merge behavior for nested directories.
