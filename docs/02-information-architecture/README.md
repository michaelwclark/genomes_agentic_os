# Information Architecture

Top-level folders should represent context, security, and operating boundaries. Functional lanes belong inside those domains.

The purpose of the information architecture is to make the next agent's loading path obvious. If a folder exists, it should tell the agent what kind of object it contains and what authority that object has.

## Source Package Versus Installed OS

| Location | Role |
| --- | --- |
| This repository | Product source for templates, schemas, documentation, examples, and CLI code. |
| `~/agentic_os` | Runtime operating state for real domains, workflows, automations, context packs, and run logs. |
| `~/projects/*` | Product, client, content, or code repositories the OS operates on. |
| Your Notion workspace or a client-owned workspace | Human cockpit, dashboards, approvals, and readable status. |

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

The domain is the unit of operating policy. Put access rules, approval rules, source systems, stakeholder context, and default lanes there.

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

## Object Placement

| Object | Preferred Location | Notes |
| --- | --- | --- |
| Domain context | `domains/<domain>/context/` | Stable facts about the operating boundary. |
| Workflow spec | `domains/<domain>/workflows/<lane>/<name>.md` | Process for judgment-heavy repeated work. |
| Automation spec | `domains/<domain>/automations/<lane>/<name>.md` | Triggered process with permissions and audit rules. |
| Run log | `runs/<timestamp>-<domain>-<name>.md` | One execution record, not a reusable spec. |
| Decision record | `domains/<domain>/decisions/` | Durable design or operating decision. |
| Notion mapping | `domains/<domain>/notion/` | IDs and mapping notes for the control plane. |
| Shared template copy | `templates/` | Runtime copy of source templates. |

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

## Anti-Patterns

Avoid these shapes:

- One global `workflows/` folder with no domain ownership.
- Client-specific forks of the whole source package.
- Status in filenames, such as `feature_dev_done.md`.
- Secrets inside context packs or Notion mapping files.
- Chat transcript dumps as the only run evidence.
- Separate Claude and Codex workflows for the same operating process.
