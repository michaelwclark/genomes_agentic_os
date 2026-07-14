# OS Add Bug

Compatibility command: `/add-bug`

This is a typed adapter for `/add-spec`, not a separate bug-intake workflow.

Invoke the canonical command with `--type bug`:

```bash
agentic-os spec add <domain> <project> \
  --root <root> \
  --title "Bug: <short failure>" \
  --summary "<current behavior, expected behavior, and evidence>" \
  --type bug \
  [--status idea] \
  [--adapter <filesystem|linear|jira>] \
  [--dry-run|--apply]
```

Follow `harness/commands/os-add-spec.md` and the `spec-engine` skill. Include
severity, reproduction evidence, current behavior, expected behavior, and the
next validation step in the Spec content. Do not create `BUG.md` as a competing
lifecycle object.
