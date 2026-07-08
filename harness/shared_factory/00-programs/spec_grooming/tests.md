# Tests: spec_grooming

## Focused Tests

- `python -m pytest tests/test_cli_scaffold.py::test_init_creates_domain_first_tree_and_shared_templates -q`
- `python -m pytest tests/test_cli_scaffold.py::test_spec_grooming_program_installs_contract -q`
- `python -m pytest tests/test_doc_config.py::test_docs_update_merges_doc_config_registry_entries -q`

## Full Checks

- `python -m pytest tests/ -q`
- `agentic-os validate --root <installed-root>`

## Manual Holdouts

- A rough LOS Django story routes to `$jira-product-orchestrator`.
- A request overlapping an existing OSProgram records `extend_existing`.
- A Notion projection stops if the workspace is not Genome's Notion.
- A Linear/Jira draft contains no local filesystem path or private Notion link.

