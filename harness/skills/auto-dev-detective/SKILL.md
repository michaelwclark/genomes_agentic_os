---
name: auto-dev-detective
description: Investigate reported bugs, failed QA, ticket comments, log entries, alerts, incidents, regressions, suspected causes, and RCA questions with deployed-version awareness, root/domain/project evidence-source policies, read-only gathering, competing hypotheses, pause/resume for VPN or provider availability, and durable receipts. Use implicitly whenever a user asks why something happened, what may be causing environment- or tenant-specific behavior, whether code/config/rules/data explain a failure, or for evidence needed to create or refine a ticket—even when Auto-Dev or Detective is not named.
---

# Auto-Dev Detective

Produce the strongest evidence-backed explanation available without mutating the
system being investigated. Treat code, configuration, rules, logs, historical
RCAs, tracker state, tests, and memory as distinct sources with explicit
authority and freshness.

## Route and resolve

1. Read the root contract, then the narrowest domain/project route.
2. Normalize the signal into a question, trigger, environment, tenant, time
   window, observed behavior, expected behavior, and impact.
3. Resolve the dynamic evidence plan:

```bash
agentic-os detective resolve --trigger <bug|qa-failure|ticket-comment|log-entry|alert|incident|question> \
  --domain <domain> --project <project> --environment <environment> --explain --json
```

The source order is root → domain → project → invocation overlay. Same-id files
compose; narrower packs may add tools and authority but cannot weaken safety.

## Start one run

Store the normalized signal as JSON/YAML/Markdown in the routed work item or run
folder, then start one idempotent packet:

```bash
agentic-os detective start --input <signal.yml> --trigger <trigger> \
  --domain <domain> --project <project> --environment <env> --tenant <tenant> \
  --run-id <stable-id> --json
```

Use `detective status --run-dir <run>` before every resume. Never discard a run
to escape a pause or create a cleaner-looking history.

## Pass the version gate

For environment-scoped work, resolve the exact deployed release/tag/commit from
the domain's declared authority before using source code as evidence:

```bash
agentic-os detective record-version --run-dir <run> \
  --authority-receipt <investigation-version-authority.json>
```

Never substitute the default branch, newest checkout, or expected release. If
no exact version exists, preserve the uncertainty and stop causal code claims.
The receipt must be a verified `investigation-version-authority/v1` readback
matching the run environment, tenant, declared authority class, and source.

## Gather bounded evidence

Follow `source-manifest.json` in priority order. Start with durable local
snapshots and receipts; use live read-only providers or environment shells only
for stale, missing, or runtime-only facts. For each source record authority,
capture time, facts, limitations, and a safe reference:

```bash
agentic-os detective record-evidence --run-dir <run> --source <source-id> \
  --summary <bounded-summary> --fact <fact> --limitation <limitation> \
  --authority <policy-authority-class> --evidence-ref <safe-ref> \
  --prerequisite <exact-non-automatic-prerequisite>
```

Undeclared sources fail closed. Add a policy overlay before starting if a new
source is needed. When a planned source is unavailable or not applicable,
record its disposition rather than silently omitting it:

```bash
agentic-os detective source-status --run-dir <run> --source <source-id> \
  --status <not-applicable|unavailable|deferred> --reason <reason> \
  --evidence-ref <safe-ref>
```

`deferred` remains incomplete and blocks conclusion.

- Keep facts separate from inference and reporter claims.
- Search for disconfirming evidence and contradictions.
- Do not copy secrets, tokens, customer data, raw payloads, local paths, or
  private workspace links into an external output.
- Read-only investigation does not authorize fixes, config changes, data
  mutation, deployments, or external artifact writes.

## Pause without failure storms

If VPN, an environment, authentication, or a provider is unavailable, record
one pause and return control:

```bash
agentic-os detective pause --run-dir <run> --reason vpn-unavailable \
  --resume-when "VPN connectivity and the target environment are verified"
```

Do not poll repeatedly. When fresh evidence shows the dependency is available:

```bash
agentic-os detective resume --run-dir <run> \
  --availability-receipt <investigation-availability.json>
```

The receipt must use `investigation-availability/v1`, match the paused reason,
and carry a verified probe reference and timestamp. Resume the same source plan
at its prior state.

## Analyze and conclude

Create an analysis mapping with evidence-backed facts; hypotheses with support
evidence IDs and a falsifier; evidence-backed contradictions and disconfirming
evidence; unknowns; causes; bounded scope; conclusion evidence IDs; confidence;
recommendations; and next owner. Use `analyze` for an intermediate receipt and
`conclude` only after every declared source is completed or explicitly resolved:

```bash
agentic-os detective analyze --run-dir <run> --analysis <analysis.yml>
agentic-os detective conclude --run-dir <run> --analysis <analysis.yml>
```

Say “confirmed” only when the causal chain is directly supported. Otherwise use
“most likely,” “consistent with,” or “unknown,” with confidence and the check
that would change the conclusion.

## Render the output

Render the concluded result through the shared artifact contract:

```bash
agentic-os detective render --run-dir <run> --provider <provider> \
  --type <investigation-report|root-cause-analysis>
```

Then follow `$auto-dev-create-artifacts` for validation, approved external
apply, target verification, readback, and hash receipt. A local conclusion is
complete investigation work; publishing or fixing remains a separate governed
action.

## Required receipts

Keep `request.json`, `policy-resolution.json`, `source-manifest.json`,
`deployed-version.json`, `evidence.jsonl`, `hypotheses.json`, `events.jsonl`,
`run.json`, and—after conclusion—`result.json` plus `result.md`. Rendered
artifacts add their own contract and validation receipts.

Run `agentic-os detective doctor` when policies fail to resolve or a fresh
agent cannot explain the source plan.
