# Investigation

Feature 54 established the Codex config surface and Agentic OS layer map. This
feature uses those layer IDs to define concrete profiles while keeping
Codex-facing TOML separate from OS metadata that may not be native Codex config.

The profile manifest carries skills, prompt files, MCP availability,
environment assumptions, and telemetry posture. The TOML template keeps native
profile selection concise.
