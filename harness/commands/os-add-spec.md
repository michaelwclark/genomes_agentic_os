# OS Add Spec

Canonical slash command: `/add-spec`

Use for any idea, ticket, backlog item, feature request, bug, or configuration
change that should be tracked now or later. The canonical object is a Spec.

## Invocation

Resolve the narrowest domain and project, then run:

```bash
agentic-os spec add <domain> <project> \
  --root <root> \
  --title "<short outcome>" \
  --summary "<raw intent and desired behavior>" \
  --type <bug|feature|config> \
  --status <idea|grooming|blocked|ready|in_progress|built> \
  [--id <stable-id>] \
  [--adapter <filesystem|linear|jira>] \
  [--dry-run|--apply]
```

Defaults are `--type feature`, `--status idea`, and the project policy's
adapter. Filesystem creation writes the local Spec by default. Linear and Jira
operations remain plans unless `--apply` is supplied.

## Procedure

1. Load routed root, domain, and project context.
2. Search for an existing matching Spec before creating another one.
3. Preserve the user's original wording in the summary; do not silently turn
   assumptions into requirements.
4. Let layered `spec_engine` policy choose authority, adapter, and placement.
   Use `--adapter` only for a deliberate invocation override.
5. Run `spec add`; keep the YAML receipt, including provider identity and
   readback evidence.
6. If the request needs deeper product/technical definition, continue with the
   `spec-engine` skill in grooming mode.
7. Report the Spec id, canonical status, adapter, external URL when present,
   and next action.

## Compatibility Aliases

| Alias | Canonical operation |
| --- | --- |
| `/add-bug` | `/add-spec --type bug` |
| `/new-feature` | `/add-spec --type feature` |
| `/add-feature` | `/add-spec --type feature` |
| `/new-idea` | `/add-spec --type feature --status idea` |
| `/groom-spec` | Add if needed, then groom/transition the Spec to `grooming` |
| `/auto-add-spec` | Automatically add or update a matching Spec |
| `/auto-add-feature` | `/auto-add-spec --type feature` |

## Guardrails

- Do not create a separate idea, ticket, feature, bug, or backlog lifecycle.
- Do not use Notion as a mandatory queue. Documentation projection is optional.
- Do not bypass project Jira/Linear intake rules unless the user explicitly
  requests an override permitted by policy.
- Do not include local paths, private Notion links, secrets, or harness-only
  details in external provider text.
- A failed adapter call must leave a retryable receipt and must not create a
  second Spec on retry.
