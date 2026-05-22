# Investigation

Feature 01 adds:

- `agentic-os project create <domain> <project> --root <root>`
- project state under `<domain>/02-projects/<project>/`
- active-work rows under `<domain>/00-control-plane/active-work.md`
- source references in `source-map.md`
- additive rerun behavior
- `lenders` to `los` domain aliasing

Relevant source paths are `src/genomes_agentic_os/cli.py`,
`src/genomes_agentic_os/scaffold.py`, `tests/test_cli_scaffold.py`, and
`features/01-project-create-and-active-work/`.

