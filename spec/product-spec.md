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
| Domain | A top-level context/security/business boundary such as `personal`, `clarks_consulting`, `los`, `shared_factory`, or a client domain. |
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

- A new OS can be scaffolded locally with top-level domain roots.
- A domain can be created with router files, control plane, inbox, projects, workflows, automations, knowledge, run logs, metrics, and archive folders.
- A workflow folder can be created and validated at `<domain>/03-workflows/<lane>/<workflow>/`.
- An automation folder can be created and validated at `<domain>/04-automations/<lane>/<automation>/`.
- Claude and Codex can load the same operating rules.
- Notion control-plane requirements are documented clearly enough to build.
- The default installed roots cover `personal`, `clarks_consulting`, `los`, `shared_factory`, and `archive`.
