# Information Architecture

Top-level folders should represent context, security, and operating boundaries. Functional lanes belong inside those domains.

Prefer this shape:

```text
domains/
  personal/
  internal_product/
  client_operations/
  client_delivery/
  candidate_pipeline/
  shared_services/
  archive/
```

Avoid making `engineering`, `marketing`, and `sales` the top-level split unless they are truly separate operating worlds. Those are usually lanes inside a domain.

## Domain Layout

Each domain should be able to stand alone:

```text
domains/<domain>/
  README.md
  domain.yml
  lanes/
  workflows/
  automations/
  context/
  decisions/
  runbooks/
  notion/
```

## Lanes

Lanes group repeatable work by function:

```text
lanes/
  engineering/
  support/
  sales/
  marketing/
  operations/
  finance/
```

Lanes should not own global state. They should point to workflows, automations, and context packs that live inside the domain.

## Naming Rules

- Use lowercase snake case for filesystem names.
- Use human-readable titles in Notion.
- Keep stable object IDs in YAML front matter or sidecar config when an object maps to Notion, Jira, GitHub, Slack, or a database row.
- Do not encode transient status in filenames.

## Example: Internal Product

```text
domains/internal_product/
  workflows/
    engineering/
      feature_dev/
      pull_request_review/
      release_management/
    support/
      production_issue_triage/
  automations/
    engineering/
      tagged_pr_review/
    support/
      production_thread_intake/
```

This keeps the product or business area as the boundary while allowing engineering and support to have separate operating patterns.
