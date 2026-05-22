# Investigation

Feature 04 is implemented in `src/genomes_agentic_os/automation_ops.py` and
exposed through the `agentic-os automation` command group.

Relevant command surfaces:

- `agentic-os automation create <domain> <lane> <name> --root <root>`
- `agentic-os automation check <domain> <lane> <name> --root <root>`
- `agentic-os automation set-maturity <domain> <lane> <name> <level> --root <root>`
- `agentic-os automation attach <domain> <lane> <name> --project <project> --root <root>`
- `agentic-os validate --root <root>`

The holdout intentionally uses a generated temp root instead of inspecting only
source tests. This confirms the installed runtime files, decision log, project
status, and source map are written coherently.
