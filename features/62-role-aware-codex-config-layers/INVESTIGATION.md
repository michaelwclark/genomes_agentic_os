# Investigation

## Current Evidence

- `src/genomes_agentic_os/config_ops.py` defines seven layer tokens:
  `global_harness`, `agentic_os_root`, `customer_os_root`, `domain_or_lane`,
  `project`, `workflow_or_task`, and `automation`.
- `discover_config_tree_targets` discovers installed OS root, domain roots,
  project roots, workflow roots, and automation roots for `config install-tree`.
- `config_template` still hardcodes `model = "gpt-5.2"` at the root and profile
  levels.
- `src/genomes_agentic_os/customer.py::customer_layer_config` also hardcodes
  `model = "gpt-5.2"`.
- `docs/13-agent-surfaces.md` already documents seven config layers and says
  `config.toml` gives Codex runtime posture.
- Feature 55 says richer Agentic OS metadata should live outside native Codex
  keys.
- Feature 57 says config merge conflicts should block by default and preserve
  local values.

## Current Gap

The repo has structural config layer coverage, but not the user's desired
role-aware/model-tiered policy:

- no `gpt-5.5` generated defaults;
- no navigator/orchestrator distinction in generated config;
- no prompt-visible role identity;
- no tests proving role identity appears in model input;
- no customer-safe variant of the same model/role policy.

## Implementation Implication

This should be implemented as a policy-rendering change, not one-off string
replacement. A single policy source should feed:

- `config.toml`;
- prompt-visible role artifact;
- structured sidecar metadata;
- docs and tests.

## Dirty Worktree Note

The repo currently has unrelated modified files. Implementation agents must not
revert or overwrite those changes. Work with existing edits and keep changes
scoped to the files required by this feature.
