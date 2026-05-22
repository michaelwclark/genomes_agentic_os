# Judgment

The installer blocks on conflicts by default because `config.toml` can carry
security, approval, sandbox, MCP, and telemetry behavior. `--confirm-conflicts`
is intentionally explicit: it preserves existing values while allowing
non-conflicting managed additions.
