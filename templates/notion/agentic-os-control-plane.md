# Agentic OS Control Plane

Use this template for the top-level Notion page named `Agentic OS`.

## Purpose

This page is the human cockpit for Genome's Agentic OS. Use it to capture work, see active state, approve risky actions, inspect outputs, and follow run history.

The filesystem OS remains the source of truth for routers, workflow specs, automation specs, templates, and run logs. Notion displays and initiates work; it does not replace the installed OS.

## Workspace Gate

Before creating this page or any database, verify the parent page is in Genome's Notion. Do not create fallback pages in another workspace.

## Dashboard Sections

Add linked database views for:

- Needs Approval.
- Active Work.
- Waiting On Me.
- Running Or Failed Runs.
- Recent Outputs.
- Automation Health.
- Inbox To Triage.
- Decisions This Week.

## MVP Databases

Create these databases under the `Agentic OS` page first.

### Domains

```sql
CREATE TABLE (
  "Name" TITLE,
  "Domain ID" RICH_TEXT,
  "Status" SELECT('Active':green, 'Paused':yellow, 'Archived':gray),
  "Purpose" RICH_TEXT,
  "Owner" PEOPLE,
  "OS Path" RICH_TEXT,
  "Notion Page ID" RICH_TEXT,
  "Last Sync" DATE
)
```

### OS Inbox

```sql
CREATE TABLE (
  "Name" TITLE,
  "Status" SELECT('New':blue, 'Triaged':yellow, 'Routed':green, 'Blocked':red, 'Archived':gray),
  "Source" SELECT('Chat':blue, 'Slack':purple, 'Email':yellow, 'Jira':green, 'Notion':gray, 'Manual':default),
  "Risk" SELECT('Low':green, 'Medium':yellow, 'High':red),
  "Requested Outcome" RICH_TEXT,
  "Raw Source URL" URL,
  "Captured At" DATE,
  "Routed To" RICH_TEXT
)
```

### Work Items

```sql
CREATE TABLE (
  "Name" TITLE,
  "Status" SELECT('Inbox':gray, 'Ready':blue, 'Running':yellow, 'Waiting':orange, 'Needs Approval':red, 'Done':green, 'Blocked':red),
  "Priority" SELECT('P0':red, 'P1':orange, 'P2':yellow, 'P3':gray),
  "Domain" RICH_TEXT,
  "Lane" RICH_TEXT,
  "Work Type" SELECT('Project':blue, 'Workflow':green, 'Automation':purple, 'Run':yellow, 'Decision':gray),
  "OS Path" RICH_TEXT,
  "Source URL" URL,
  "Next Action" RICH_TEXT,
  "Due" DATE
)
```

### Runs

```sql
CREATE TABLE (
  "Name" TITLE,
  "Status" SELECT('Running':yellow, 'Done':green, 'Waiting':orange, 'Failed':red, 'Needs Approval':red),
  "Domain" RICH_TEXT,
  "Workflow Or Automation" RICH_TEXT,
  "Agent" SELECT('Codex':blue, 'Claude':purple, 'Automation':green, 'Human':gray),
  "Started At" DATE,
  "Completed At" DATE,
  "Run Log Path" RICH_TEXT,
  "Validation Evidence" RICH_TEXT,
  "Artifacts" RICH_TEXT,
  "Next Action" RICH_TEXT
)
```

### Approvals

```sql
CREATE TABLE (
  "Name" TITLE,
  "Status" SELECT('Requested':yellow, 'Approved':green, 'Rejected':red, 'Expired':gray),
  "Risk Type" MULTI_SELECT('External Write':red, 'Production':red, 'Destructive':red, 'Billing':orange, 'Legal':orange, 'Customer Visible':yellow, 'Secrets':red),
  "Requested By" RICH_TEXT,
  "Approver" PEOPLE,
  "Requested At" DATE,
  "Decision At" DATE,
  "Decision Notes" RICH_TEXT,
  "Source Run" RICH_TEXT
)
```

## Second-Wave Databases

Create these after the MVP flow works:

- Workflows.
- Automations.
- Decisions.
- Sources.
- Artifacts.

## Operating Rules

- Every non-trivial run should appear in `Runs`.
- Every approval gate should appear in `Approvals`.
- Every active item should have a next action.
- Every Notion record that points to filesystem state should include an `OS Path`.
- External, production, destructive, billing, legal, secrets, and customer-visible actions require approval unless a workflow-specific rule is stricter.

## First Manual Test

1. Create one `OS Inbox` row for a real request.
2. Route it to a domain and create a `Work Items` row.
3. Run the work through Codex or Claude.
4. Create a `Runs` row pointing to the filesystem run log.
5. If approval is needed, create an `Approvals` row before the action.
6. Move the work item to `Done` only after validation evidence exists.
