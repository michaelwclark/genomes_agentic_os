---
name: auto-dev-create-artifacts
description: Resolve root/domain/project Markdown contracts and create excellent Jira, Linear, Notion, Confluence, GitHub, Slack, or filesystem artifacts with provider-adapter rendering, evidence and semantic validation, explicit apply, readback, and receipts. Use implicitly for any artifact-authoring request.
---

# Auto-Dev Create Artifacts

Use this skill when a user asks to draft, create, update, rewrite, standardize,
or assess an artifact. Trigger on the intent, not only the phrases “Auto-Dev” or
“create artifacts.” Examples include “make this a Jira bug,” “write the RCA,”
“turn this into a Linear initiative,” “create the Notion program page,” “post a
ticket comment,” or “prepare the PR description.”

## Required context

1. Route to the narrowest domain/project and read its `AGENTS.md`, `ROUTER.md`,
   `CONTEXT.md`, `RULES.md`, and `TOOLS.md`.
2. Identify provider, artifact type, intended audience, exact destination, and
   whether the user authorized a draft or a write.
3. Resolve the contract before writing prose:

```bash
agentic-os artifacts resolve --provider <provider> --type <artifact-type> \
  --domain <domain> --project <project> --explain --json
```

The source order is root → domain → project → invocation overlay. At each scope
it is `any/any`, `any/type`, `provider/any`, `provider/type`. Narrower contracts
cannot weaken approval, sanitization, target verification, or readback.

## Evidence mapping

Create a local JSON/YAML evidence file in the routed work item or run folder.
Include only applicable fields:

- title, summary, audience, destination;
- source facts and timestamps;
- environment, tenant/account, release, and code version;
- expected and observed behavior, reproduction, impact;
- acceptance criteria, scope, non-goals, dependencies, risks;
- facts, evidence, inference, recommendations, gaps, and confidence;
- artifact-specific sections under `sections`.
- `evidence_receipts`, keyed by every inherited evidence requirement, with
  verified status, safe evidence reference, and capture time;
- `validation_assertions`, keyed by semantic rule, with passed status,
  evidence reference, and check time when the engine cannot validate it.

Never promote an allegation or hypothesis into a fact. Keep private/raw evidence
in local receipts and give external readers only audience-safe references.

## Render, validate, apply

```bash
agentic-os artifacts render --provider <provider> --type <artifact-type> \
  --domain <domain> --project <project> --input <evidence.yml> --output <draft.json>
agentic-os artifacts validate --artifact <draft.json>
```

Inspect `body_markdown` and `provider_payload` (`native` is a compatibility
alias). Jira payloads are native ADF; other providers receive normalized
adapter inputs. Repair every evidence, semantic, missing-section, or scrub
finding. A draft is local and non-mutating.

For an approved write:

```bash
agentic-os artifacts apply --artifact <draft.json> --target <verified-target> \
  --receipt <run>/apply.json --approval-receipt <run>/approval.json \
  --target-receipt <run>/target-verification.json --execute
```

- `filesystem` applies atomically and verifies content by readback.
- External providers return `awaiting_provider_adapter`. Use the exact
  registered provider route from the routed `TOOLS.md`; re-verify workspace,
  project/team/space/repository, parent, issue/page type, and audience before
  invoking it.
- Fetch the created/updated artifact. Hash the rendered readback and close the
  handoff from a typed provider receipt:

```bash
agentic-os artifacts record-readback --apply-receipt <run>/apply.json \
  --readback-receipt <run>/provider-readback.json
```

The readback receipt uses `artifact-provider-readback/v1` and includes provider,
target, external ID/URL, required observed fields, verification time, and the
normalized live `content`. The engine computes and checks its hash.

Do not claim completion from a provider create/update response alone.

## Provider quality

- Jira: use native ADF and verify rendered headings, task lists, links, fields,
  parent, fix version, and issue type.
- Linear: concise outcome/problem, acceptance, hierarchy, team/project/
  initiative/cycle readback.
- Notion: verify Genome's Notion, use visual hierarchy, callouts/tables/toggles,
  child pages, and images for non-trivial flows.
- Confluence: search for the canonical page first, preserve owner/status/
  last-verified data, and avoid knowledge forks.
- GitHub: render the effective PR template, including a `Linked Work` Markdown
  hyperlink to the supplied Jira, Linear, or GitHub work item; then verify exact
  repo/base/head and no local/private OS references.
- Slack: outcome or ask first, compact decisive evidence, owner, next action.
- Filesystem: routed folder, stable naming, atomic write, relative receipt.

## Failure handling

- Missing or malformed contract: run `agentic-os artifacts doctor`; fix policy
  rather than bypassing it.
- Missing evidence: leave the draft local and gather or explicitly record the
  gap. Do not delete a required section.
- Provider unavailable: retain the handoff receipt and resume it later; do not
  create a second artifact.
- Target mismatch or unauthorized workspace: stop before write.
- Readback mismatch: mark the run incomplete, preserve both hashes, and repair
  or roll back through the provider's governed route.

## Receipts

Every run retains the evidence mapping, effective contract fingerprint and
sources, rendered envelope, validation receipt, apply/handoff receipt, provider
ID/URL, readback hash, and unresolved gaps. External artifacts never expose
local receipt paths.
