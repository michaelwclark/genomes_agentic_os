# Local Context

This file explains how agents should understand work inside this directory.

## Purpose

Describe the room, customer, domain, workflow, or automation this directory
owns.

## Source Systems

| Source | Location | Use For |
| --- | --- | --- |
| Notion |  | Control plane and status |
| GitHub |  | Source, pull requests, and issues |
| Local files |  | Runtime artifacts and installed OS state |

## What To Load

| Need | Load | Skip By Default |
| --- | --- | --- |
| Understand the room | `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md` | unrelated domains |
| Resume active work | project status, run logs, source map | archived work |
| Run a workflow | workflow quick reference, context pack, runbook | unrelated automations |
| Review an automation | automation spec, permissions, tests | unrelated workflows |

## Done Means

- Work was routed to the correct local surface.
- Source evidence and validation are recorded.
- Approval rules were followed.
- Missing tools or route gaps were recorded.
- Durable next steps or learnings were captured where appropriate.

## Update Rule

Update this file when the local operating context changes.
