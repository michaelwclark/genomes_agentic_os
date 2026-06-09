# Pre-Duel Brief

## Question

Harden `SPEC.md` for Feature 62: Role Aware Codex Config Layers.

The spec should be implementation-ready for an agent that will modify
`genomes_agentic_os` so Codex config layers become role-aware and model-tiered.

## User Preference

- Codex is the user's daily driver.
- Cheaper/lighter models are fine for navigation and routing.
- Heavy work should use more capable models, primarily `gpt-5.5`.
- Agents should not be expected to infer their role from folder position alone.
- Role identity must be prompt-visible.

## Existing Repo Facts

- `config_ops.py` already has layer tokens and install-tree discovery.
- `config_ops.py` and `customer.py` still hardcode `gpt-5.2`.
- `docs/13-agent-surfaces.md` documents seven config layers.
- Feature 55 judgment says native Codex keys should stay in TOML and richer
  Agentic OS metadata should live in YAML.
- Feature 57 judgment says config merge conflicts should block by default.

## Critic Focus

- Identify ambiguity that would cause implementation agents to diverge.
- Check whether model/profile names are backward-compatible enough.
- Check whether prompt visibility is testable.
- Check whether customer OS behavior is safe.
- Check whether tests and acceptance criteria are concrete enough.
- Flag any contradiction with prior Features 54-59.
