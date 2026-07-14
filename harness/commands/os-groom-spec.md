# OS Groom Spec

Compatibility command: `/groom-spec`

This invokes the canonical `spec-engine` skill in grooming mode. It does not
own a separate lifecycle.

1. Find the existing Spec or create it through `/add-spec`.
2. Transition it to grooming:

```bash
agentic-os spec transition <domain> <project> <spec_id> grooming \
  --root <root> \
  [--adapter <filesystem|linear|jira>] \
  [--dry-run|--apply]
```

3. Preserve `ORIGINAL_INTENT.md`, run capability discovery, record one route
   decision, and complete the product, technical, acceptance, QA, rollout, and
   open-question sections described by `harness/skills/spec-engine/SKILL.md`.
4. Transition to `ready` only when the configured readiness gates pass.

LOS or Jira-primary work still follows project policy and any configured team
grooming adapter; `/groom-spec` does not bypass backlog, discussion, or sprint
placement rules.
