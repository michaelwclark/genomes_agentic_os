# Tests: Spec Engine

## Focused Tests

- `python -m pytest tests/test_cli_scaffold.py::test_init_creates_domain_first_tree_and_shared_templates -q`
- `python -m pytest tests/test_cli_scaffold.py::test_spec_grooming_program_installs_contract -q`
- `python -m pytest tests/test_doc_config.py::test_docs_update_merges_doc_config_registry_entries -q`

## Full Checks

- `python -m pytest tests/ -q`
- `agentic-os validate --root <installed-root>`

## Manual Holdouts

- A filesystem-only project completes add/show/list/transition/sync without a
  tracker dependency.
- A Linear-primary project creates one idempotent backlog projection.
- An LOS Jira project defaults to backlog and requires an explicit active-sprint
  override.
- Block/unblock restores the prior lifecycle status.
- A rough LOS Django story routes to `$jira-product-orchestrator`.
- A request overlapping an existing OSProgram records `extend_existing`.
- A Notion projection stops if the workspace is not Genome's Notion.
- A Linear/Jira draft contains no local filesystem path or private Notion link.
