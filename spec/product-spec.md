# Product Spec

## Product

Genome's Agentic OS is a scaffold and standards package for creating reusable operating systems for agents, automations, workflows, and human approvals.

## Problem

Agentic work is currently distributed across chats, repos, Slack threads, Notion docs, local scripts, automations, and memory. The result is repeated context loading, inconsistent workflow execution, and weak resumability.

## Goals

- Create a reusable OS scaffold for internal and client work.
- Standardize domains, workflows, automations, context packs, run logs, and approvals.
- Make Claude and Codex operate from the same source standards.
- Make Notion a useful control plane without overloading it as the runtime database.
- Make it easy to instantiate a new client OS with clear customization points.

## Non-Goals

- Do not build a full web app in V1.
- Do not replace every existing project repo.
- Do not migrate all historical work before proving the operating model.
- Do not make Notion the only execution data store.
- Do not automate risky external actions before approval rules exist.

## Primary Users

- Solo operators and engineers.
- Agents operating inside Claude and Codex.
- Client-facing operators who need a cockpit for automations.
- Future customers who need a repeatable AI automation setup.

## Core Objects

| Object | Definition |
| --- | --- |
| Domain | A context/security/business boundary such as `internal_product`, `client_operations`, or `candidate_pipeline`. |
| Lane | Functional grouping inside a domain such as engineering, support, sales, or operations. |
| Workflow | Repeatable judgment-heavy process. |
| Automation | Triggered or scheduled process with guardrails. |
| Work Item | A unit of work tracked through state. |
| Run | One execution of a workflow, automation, or skill. |
| Context Pack | Minimal context needed to execute correctly. |
| Approval | Human authorization for a risky or external action. |
| Artifact | Output or evidence produced by a run. |
| Decision | Durable choice that changes future execution. |

## V1 Acceptance Criteria

- A new OS can be scaffolded locally from templates.
- A domain can be created with standard folders and context files.
- A workflow spec can be created and validated.
- An automation spec can be created and validated.
- Claude and Codex can load the same operating rules.
- Notion control-plane requirements are documented clearly enough to build.
- Example domains exist for internal product work, client operations, and candidate pipeline work.
