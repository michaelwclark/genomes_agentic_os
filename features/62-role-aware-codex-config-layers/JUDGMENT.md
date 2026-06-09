# Judgment

The layer coverage is structurally present, but the generated config is not yet
role-aware. The right correction is a single policy map that renders TOML,
structured sidecar metadata, prompt-visible role text, managed ownership fields,
and tests.

Keep native Codex keys in `config.toml`: model, reasoning effort, approval,
sandbox, MCP registration, and root/discovery keys. Keep richer Agentic OS
metadata in `config/*.yml` and short prompt-visible markdown. Do not depend on
unknown nested TOML metadata becoming model-visible.

Navigation should stay cheaper by default. Project, workflow, and automation
layers should default to a more capable model because those layers carry
orchestration, implementation, verification, and safety risk.

The duel pass locked the important edge cases: compatibility discovery before
profile renames, explicit aliases for discovered public profile names, managed
conflict behavior for new files, split customer privacy scans, and temporary-root
prompt-input validation rather than live-profile validation.
