# `/auto-dev-create-artifacts`

Use this command whenever the user asks to draft, create, update, or standardize
a Jira, Linear, Notion, Confluence, GitHub, Slack, or filesystem artifact—even
when they do not name Auto-Dev.

1. Route to the domain/project and load its context.
2. Resolve the effective provider/type contract with `--explain`.
3. Build a structured evidence mapping that separates facts, inference, gaps,
   and recommendations.
4. Render and validate locally.
5. Show or inspect the draft before any external mutation.
6. On explicit approval, prepare `artifacts apply --execute`, perform the
   provider handoff through the registered tool in `TOOLS.md`, read back the
   result, and record the readback receipt.

```bash
agentic-os artifacts resolve --provider <provider> --type <type> \
  --domain <domain> --project <project> --explain
agentic-os artifacts render --provider <provider> --type <type> \
  --domain <domain> --project <project> --input <evidence.yml> --output <draft.json>
agentic-os artifacts validate --artifact <draft.json>
agentic-os artifacts apply --artifact <draft.json> --target <verified-target> \
  --receipt <run>/apply.json --execute
agentic-os artifacts record-readback --apply-receipt <run>/apply.json \
  --external-id <id> --external-url <url> --readback-sha256 <sha256>
```

External writes remain approval-gated. Never bypass failed validation, target
verification, sanitization, or readback.
