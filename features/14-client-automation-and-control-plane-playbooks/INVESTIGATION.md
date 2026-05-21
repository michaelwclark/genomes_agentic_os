# Investigation

The reusable customer templates already existed under `templates/customer/` and `templates/notion/`.

The missing runtime pieces were:

- `harness/commands/os-client-automation-brief.md`
- `harness/commands/os-control-plane-bootstrap.md`
- `harness/commands/os-context-audit.md`
- `harness/skills/client-automation-brief/SKILL.md`
- `harness/skills/control-plane-bootstrap/SKILL.md`
- `harness/skills/context-audit/SKILL.md`

`install_docs` already copies commands and skills into `shared_factory/05-knowledge/`, so no new installer path was needed.
