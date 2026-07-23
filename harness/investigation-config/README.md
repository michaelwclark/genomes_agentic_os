# Investigation Configuration

This is the root policy library for Auto-Dev Detective. It is composed at run
time with optional domain and project additions:

```text
harness/investigation-config/
  -> domains/<domain>/investigation-config/
  -> domains/<domain>/02-projects/<project>/investigation-config/
  -> invocation overlays
```

Every non-README Markdown file has schema frontmatter plus readable operating
instructions. Add 1-N files under `standards/`, `safety/`, `phases/`,
`triggers/`, `sources/`, `environments/`, or `outputs/`. Reusing the same
`kind` + `id` extends or specializes that contract; lists and instructions are
composed, and inherited safety cannot be weakened.

Use `agentic-os detective resolve --trigger bug --explain` to see the ordered
plan and `agentic-os detective doctor` to validate every installed pack.

Runs pin that resolution into `source-manifest.json`. Evidence for undeclared
sources is rejected. Environment-scoped investigations require a verified
`investigation-version-authority/v1` receipt before gathering other evidence.
Unavailable sources require an explicit disposition; `deferred` still blocks
conclusion. Paused runs resume only with a matching
`investigation-availability/v1` probe receipt. Final facts, hypotheses,
disconfirming evidence, and conclusions cite recorded evidence IDs.
