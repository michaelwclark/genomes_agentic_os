# Holdout QA

## Checks

- Fresh runtime install includes all three new commands.
- Fresh runtime install includes all three new skills.
- `docs update` restores a missing managed playbook command without overwriting local manual edits.
- `agentic-os validate` fails if a required playbook command or skill is missing.
- The client automation brief distinguishes deterministic, rule-based, LLM-needed, and human-judgment work.
- The control-plane bootstrap skill keeps the filesystem as source of truth.
