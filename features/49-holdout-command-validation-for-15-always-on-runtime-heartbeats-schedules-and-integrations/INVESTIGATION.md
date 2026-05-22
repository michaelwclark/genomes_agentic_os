# Investigation

Feature 15 added the file-backed runtime layer for Genome's Agentic OS:

- Runtime templates under `shared_factory/05-knowledge/templates/runtime/`.
- Runtime command prompts under `shared_factory/05-knowledge/commands/`.
- `runtime-operator` and `integration-setup` knowledge assets.
- CLI subcommands for `runtime`, `heartbeat`, `schedule`, `integration`, and `notion track-runtime`.
- Local runtime registries under `shared_factory/00-control-plane/`.

The current CLI entry point is `agentic-os = genomes_agentic_os.cli:main`.

Important command shape found during holdout:

- Top-level install uses `uv run agentic-os init --target <root>`.
- Runtime and validation commands use `--root <root>`.
- `notion track-runtime --apply` requires `--verified-workspace "Genome's Notion"` and fails closed without it.

The first attempted smoke run used `agentic-os init --root` and confirmed that `init` does not accept `--root`. The corrected run used `--target` and passed.
