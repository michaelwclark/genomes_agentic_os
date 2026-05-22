# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
uv run agentic-os config doctor --root <installed-root> --layer agentic_os_root
```

Verify that missing OTEL/MCP config reports remediation and generated templates
name environment variables without printing token values.
