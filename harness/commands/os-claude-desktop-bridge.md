# Claude Desktop Bridge

Build the versioned Agentic OS package for Claude Desktop:

```sh
harness/bin/agentic-os-claude-desktop-bridge --root ~/agentic_os --build
```

Upload the resulting `agentic-os-operating-contract.zip` in Claude Desktop's
Customize > Skills, enable it, then paste the generated profile instructions
into Settings > Instructions for Claude. For an Agentic OS Claude project, also
paste the project instructions into that project's settings.

Run `--audit` after generation to validate the local package. The audit cannot
inspect Claude's cloud-hosted account or project settings, so enablement remains
an explicit UI action.

