# Auto-Dev: create artifacts

Use `/auto-dev-create-artifacts` whenever Auto-Dev creates or updates a durable
artifact: Jira, Linear, Notion, Confluence, GitHub, Slack, a report, RCA,
pull-request body, review, release note, handoff, or local Markdown/JSON output.
Other stages delegate their authoring work here rather than inventing provider
formatting and write behavior.

## Inputs

- provider and artifact type;
- intended audience, purpose, destination, and update-versus-create intent;
- structured source evidence and freshness boundary;
- effective root, domain, project, and invocation artifact contracts;
- verified target plus the required write/customer-visible approval.

If provider, account, workspace, repository, project, channel, issue, page, or
audience is ambiguous, stop before a write.

## Authoring loop

1. Resolve the effective artifact contract and record its source list and
   fingerprint.
2. Map evidence into the required semantic fields. Never fill a required fact
   with plausible prose.
3. Draft locally using provider-native structure: for example, Jira-native ADF
   when headings, lists, tables, task lists, or code blocks matter.
4. Validate required sections, evidence references, language, links, rendering,
   length, and audience-safety assertions.
5. Remove secrets, unnecessary customer data, local filesystem paths, private
   Notion links, internal OS names, local-only commands, and unsupported claims
   from external output.
6. Verify the exact target account/workspace/project/repository/item.
7. Apply only when the routed rules authorize the external mutation.
8. Read the live artifact back through the provider and compare normalized
   content with the validated draft.
9. Store typed approval, target-verification, apply, and provider-readback
   receipts in the work item.

An API success response is not enough. If readback is unavailable, stale, in a
different target, or does not match, the artifact stage is blocked or failed.

## Quality expectations

Write for the actual audience in plain English. Preserve useful existing
content, distinguish facts from decisions, state owners and dates when they
matter, and make the next action obvious. Do not paste raw logs when a concise
evidence-backed summary is clearer. Links must be valid for the target audience.

Provider-specific formatting belongs in `artifact-config`, not in source code
or one-off prompts. Add or improve a Markdown contract when a repeated quality
rule is missing.

## Done criteria

The artifact is complete only when the local draft passes the effective
contract and, for an external write, the provider readback proves the right
content at the right target. The work log records what was created or updated,
where it was verified, and any intentionally omitted sensitive information.
