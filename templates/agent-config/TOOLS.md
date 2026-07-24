# Tools

List the visible capabilities intended for this layer.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `notification-operator` | A bounded local macOS alert is warranted and the agent needs the right severity, dedupe key, or source-registration guidance. | `harness/skills/notification-operator/SKILL.md` |
| `auto-dev` | A tracker-backed code change should run through the canonical SDLC family. | `harness/skills/auto-dev/SKILL.md` |
| `auto-dev-everything` | One tracker item should run through every applicable stage using one resumable state file. | `harness/skills/auto-dev-everything/SKILL.md` |
| `auto-dev-grooming` | Rough work needs to become a source-backed implementation-ready specification. | `harness/skills/auto-dev-grooming/SKILL.md` |
| `auto-dev-create-artifacts` | Any Jira, Linear, Notion, Confluence, GitHub, Slack, RCA, PR, report, or filesystem artifact must follow effective provider/type contracts. | `harness/skills/auto-dev-create-artifacts/SKILL.md` |
| `auto-dev-detective` | A bug, QA failure, ticket comment, log, alert, incident, suspected cause, or RCA question needs deployed-version-aware evidence and a resumable investigation. | `harness/skills/auto-dev-detective/SKILL.md` |
| `auto-dev-readiness` | Manually resolve tracker truth, repository/base, policies, isolation, and implementation plan. | `harness/skills/auto-dev-readiness/SKILL.md` |
| `auto-dev-implementation` | Manually implement and locally validate a planned task in isolation. | `harness/skills/auto-dev-implementation/SKILL.md` |
| `auto-dev-develop` | Use the plain-English entrypoint for implementation and local validation. | `harness/skills/auto-dev-develop/SKILL.md` |
| `auto-dev-document` | Document code, issues, architecture, operations, QA, releases, or handoffs. | `harness/skills/auto-dev-document/SKILL.md` |
| `auto-dev-qa` | Run the project-configured QA gates independently. | `harness/skills/auto-dev-qa/SKILL.md` |
| `auto-dev-review-repair` | Review the exact PR Create family, run opposing review, and perform quiet CI/review repair. | `harness/skills/auto-dev-review-repair/SKILL.md` |
| `auto-dev-review-self` | Review and repair our own active delivery. | `harness/skills/auto-dev-review-self/SKILL.md` |
| `auto-dev-review-others` | Review another author's live pull request. | `harness/skills/auto-dev-review-others/SKILL.md` |
| `auto-dev-finalize` | Converge our ticket's pull-request family and record merge readiness without merging. | `harness/skills/auto-dev-finalize/SKILL.md` |
| `auto-dev-merge` | Run the final live merge gate through the correct pull-request owner. | `harness/skills/auto-dev-merge/SKILL.md` |
| `auto-dev-release-propagation` | Compatibility alias for Auto-Dev PR Create family mode and its lower-level recorder. | `harness/skills/auto-dev-release-propagation/SKILL.md` |
| `auto-dev-release` | Create and verify the project version, tag, package, changelog, or provider release. | `harness/skills/auto-dev-release/SKILL.md` |
| `auto-dev-deploy` | Deploy or monitor the exact merged artifact and verify behavior. | `harness/skills/auto-dev-deploy/SKILL.md` |
| `auto-dev-closeout` | Reconcile tracker, pull-request, release, and deployment truth and prove delivery complete. | `harness/skills/auto-dev-closeout/SKILL.md` |
| `auto-dev-health` | Audit final receipts, retire only reconstructable local resources, and preserve the packet in the finished lane. | `harness/skills/auto-dev-health/SKILL.md` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `/notify` | A failed run, high-priority item, or other operator-actionable condition needs a governed local notification. | Uses `agentic-os-notify`; follow quiet hours, severity, source, dedupe, and anti-flood policy. |
| `/auto-dev` | Route to Everything or one named Auto-Dev workflow. | Selects by intent after project routing. |
| `/auto-dev-everything` | Run every applicable workflow against one `autodev.json`. | Stops only at a real gate and finishes with Health. |
| `/auto-dev-grooming` | Groom rough work into an implementation-ready source of truth. | Standalone stage. |
| `/auto-dev-create-artifacts` | Draft or write a configured artifact with native rendering and readback. | Resolve root/domain/project policy first; external apply is explicit. |
| `/auto-dev-detective` | Investigate a signal or suspected cause with a version gate and evidence receipts. | Read-only; pause one run when VPN/provider access is unavailable. |
| `/auto-dev-readiness` | Run context, policy, worktree, and plan readiness manually. | Records typed stage evidence. |
| `/auto-dev-implementation` | Run isolated implementation and local validation manually. | Records typed stage evidence. |
| `/auto-dev-develop` | Run the named Develop workflow. | Friendly route to canonical implementation. |
| `/auto-dev-document` | Document code or delivery state for the required audience. | Records verified output references. |
| `/auto-dev-qa` | Run configured QA independently. | Records exact revision and acceptance evidence. |
| `/auto-dev-review-repair` | Review the PR Create family and run CI/review repair convergence manually. | Records typed stage evidence. |
| `/auto-dev-review-self` | Review and repair our own change. | Friendly route to canonical review/repair. |
| `/auto-dev-review-others` | Review another author's live pull request. | Uses the canonical PR Review owner. |
| `/auto-dev-finalize` | Converge the ticket pull-request family. | Leaves immutable merge readiness or an exact hold; never merges. |
| `/auto-dev-merge` | Execute the final merge gate. | Requires PR-owner readiness, live provider readback, and merge authority. |
| `/auto-dev-release-propagation` | Invoke Auto-Dev PR Create family mode through the legacy name. | Preserves the lower-level `release_propagation` recorder. |
| `/auto-dev-release` | Create and verify a project release. | Uses project release policy and provider readback. |
| `/auto-dev-deploy` | Deploy and verify the exact artifact. | Records deployed-version evidence or a policy-backed skip. |
| `/auto-dev-closeout` | Reconcile providers and prove delivery complete. | Does not own lifecycle cleanup. |
| `/auto-dev-health` | Audit the full packet, remove exact reconstructable local resources, and finish the preserved packet. | Existing state only; no force, metadata sweep, host-wide/all selector, guessed identity, or shared runtime. |
| `agentic-os artifacts` | Inspect, render, validate, apply, read back, or doctor artifact contracts. | Local/dry-run until an explicit `apply --execute`; external providers use the registered tool handoff. |
| `agentic-os detective` | Resolve/start/status, record version/evidence, pause/resume, analyze/conclude, render, or doctor investigations. | For environment work, `record-version` gates all other evidence. |
| `agentic-os develop policy` | Explain the 1-N development, QA, or gitflow Markdown bundle for a project. | Adding a Markdown file affects the next run without code changes. |
| `agentic-os develop stage` | Validate typed stage-evidence receipts and advance a Development Delivery run. | Records verified actions; it never performs provider or code actions itself. |

## MCP Servers

| Config ID | Server | Use When | Install Status | Boundary |
| --- | --- | --- | --- | --- |
| `notion` | Notion | Notion control-plane reads and approved writes. | installed at every layer | Verify the intended control-plane workspace before writing. |
| `genomes_brain` | Genome's Brain | Durable cross-session memory reads and non-secret writes. | installed at every layer | No secrets; use project rules and memory policy before writing. |
| `github` | GitHub | GitHub repository, issue, pull request, and code-hosting work. | installed at every layer | Use least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values. |
| `context_mode` | Context Mode | Large-file, repo, and session-memory analysis without flooding prompt context. | installed at every layer | Use for analysis and retrieval; do not use context-mode subprocesses for file writes. |
| `sentry` | Sentry | Error, trace, release, and production incident investigation. | visible; domain-gated via mcp-domain-gating registry | Production/customer-visible changes still require approval. |
| `datadog` | Datadog | Observability, logs, metrics, traces, and monitor investigation. | visible; domain-gated via mcp-domain-gating registry | Do not expose customer data outside approved observability workflows. |
| `supabase` | Supabase | Supabase project work in domains that opt in. | visible; domain-gated via mcp-domain-gating registry | Install only in layers the gating registry approves. |
| `composio` | Composio | Federated SaaS tools, OAuth flows, triggers, and app actions. | visible; endpoint approval required | Install only after generating an approved Composio MCP server URL for the target layer. |
| `orgo` | Orgo.io | Isolated cloud desktop and computer-use execution targets. | visible; bridge approval required | Install only through an approved Orgo MCP bridge or runtime execution target. |
| `playwright` | Playwright | Browser automation and UI validation workflows. | visible; opt in for browser automation layers | Add to config only in layers that explicitly own browser automation. |

## Composio Tool Routes

| Route ID | Toolkit | Use When | Layers | Provider Order | Known Tools | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `agentmail_genome` | `agent_mail` | Inbox reads, message lookup, and approved agent email sends. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `agentmail_api` -> `direct_api` | read: `AGENT_MAIL_LIST_INBOXES`, `AGENT_MAIL_LIST_MESSAGES`, `AGENT_MAIL_GET_MESSAGE`; write: `AGENT_MAIL_SEND_EMAIL` | Use for Genome AgentMail only; sending email requires explicit approval. |
| `slack_genome` | `slack` | Slack context lookup, DM/channel routing, and approved Slack notifications. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `slack_mcp` -> `slack_connector` -> `direct_api` | write: `SLACK_OPEN_DM`, `SLACK_SEND_MESSAGE` | Verify Genome Slack workspace and channel/user target before sending. |
| `notion_blocks` | `notion` | Fallback block-content reads when the Notion MCP/connector cannot fetch the needed page blocks. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `notion_mcp` -> `notion_connector` -> `composio` -> `direct_api` | read: `NOTION_FETCH_ALL_BLOCK_CONTENTS` | Prefer Notion MCP; verify Genome's Notion before any Notion write path. |
| `jira_genome` | `jira` | Jira issue/project reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `jira_mcp` -> `jira_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Use the configured Genome Jira workspace; writes require ticket-scope approval. |
| `linear_genome` | `linear` | Linear issue/team reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `linear_mcp` -> `linear_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Use only for Genome Linear routes; external writes require approval. |
| `email_genome` | `gmail` | Email search/read and approved outbound mail. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `gmail_mcp` -> `email_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Read only by default; sending mail requires explicit approval and recipient verification. |
| `github_genome` | `github` | GitHub issue, pull request, repo, and code-hosting actions when MCP/gh are unavailable or Composio is the approved route. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `github_mcp` -> `github_cli` -> `composio` -> `direct_api` | discover with `composio tools list <toolkit>` | Prefer GitHub MCP or gh for repo work; writes require repo/PR/issue scope verification. |
| `granola_local` | `granola` | Meeting-note lookup and approved notes ingestion when a Granola integration is configured. | agentic_os_root, domain_or_lane, project, workflow_or_task | `composio` -> `granola_local` -> `direct_api` | discover with `composio tools list <toolkit>` | Read-only by default; do not expose private notes into customer-visible output without approval. |
| `composio_discovery` | `composio` | Unknown slug discovery, schema inspection, dry-run validation, proxy fallback, and multi-tool scripting. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli` | read: `composio search`, `composio tools list`, `composio tools info`, `composio execute --get-schema`, `composio execute --dry-run`, `composio proxy`, `composio run --dry-run` | Use execute before search when a slug is known; link accounts only after confirming the target toolkit/workspace. |

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Notes |
| --- | --- | --- |
| `harness/bin/agentic-os-notify` | A watcher, automation, or agent-side helper has a bounded attention signal for the operator. | Native macOS Notification Center delivery with severity, quiet hours, source policy, durable local history, 48-hour retention, and anti-flood controls. Do not use it for routine progress narration. |

## When To Use What

- Bug, QA/log/alert, suspected cause, or RCA: Auto-Dev Detective.
- Artifact creation/update in any provider: Auto-Dev Create Artifacts.
- Coding from tracker item through delivery: Auto-Dev / `agentic-os develop`.
- Provider authentication and mutation: the routed provider tool, only after
  the Auto-Dev workflow has resolved policy and verified the target.

## Missing Or Disabled

-
