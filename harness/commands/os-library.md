# Versioned Object Library

Use the installed `lib/` Git repository for reusable programs, workflows,
automations, commands, skills, hooks, rules, references, templates, and toolkits.

```bash
agentic-os library list --root <os-root>
agentic-os library show <canonical-object-id> --root <os-root>
agentic-os library create <kind> <id> --root <os-root> [scope options]
agentic-os library refresh --root <os-root> --apply
agentic-os library doctor --root <os-root>
```

Read `lib/registry/objects.json` before scanning definition folders. Mutate the
object's `object.yml` and content, never generated registry files. Refresh and
run doctor before committing. Keep mutable runtime content outside `lib/`.

Legacy migration is copy-first and dry-run-first:

```bash
agentic-os library migrate-legacy --root <os-root>
agentic-os library migrate-legacy --root <os-root> --apply
```
