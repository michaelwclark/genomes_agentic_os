# Tools

This harness registry names the visible tool surface for the installed Agentic OS.
Folders under `harness/` and config files implement this contract; they are not
the source of truth by themselves.

## Canonical Local Registries

- `lib/registry/objects.json` is the compact read index for reusable OS objects;
  each selected object's `object.yml` is canonical for mutation.
- `harness/shared_factory/00-control-plane/active-now.json` is the compact read
  projection for current active work; `state.db` is authoritative.
- The skill, command, workflow, program, and automation paths listed below are
  compatibility routes when a matching library object exists. New definitions
  and normal edits go through `agentic-os library`.

## External Tool Routing

- For external SaaS/app tool use, follow the provider order in this file or the backing registry. For Jira work-item creation or updates, use the verified Atlassian CLI `acli` first with native Atlassian Document Format (ADF), then read the issue back through `acli` to verify rendering. Use MCP, connector, or direct API only after an ACLI authentication or capability failure, and record that fallback reason.
- If Composio is unauthorized, not connected, missing the needed slug/scope, or points at the wrong workspace/account, record that fallback reason and then use the native MCP/connector/CLI/direct API listed in this layer.
- Customer-visible, destructive, billing, deploy, email/message, tracker, database, and Notion writes still require explicit approval plus target verification.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `agentic-os-operating-contract` | Apply the shared OS operating contract before Agentic OS work in any harness. | `harness/skills/agentic-os-operating-contract/SKILL.md` |
| `os-navigator` | Route work through installed OS rooms. | `shared_factory/05-knowledge/skills/os-navigator/` |
| `workflow-builder` | Create or improve reusable workflows. | `shared_factory/05-knowledge/skills/workflow-builder/` |
| `program-builder` | Create or refine OSProgram and InstanceOSProgram contracts. | `shared_factory/05-knowledge/skills/program-builder/` |
| `status-report` | Generate recent-work OS status reports with markdown receipts, Notion projection, dirty-state scan, and next-action gap analysis. | `harness/skills/status-report/SKILL.md` |
| `doc-config-router` | Route document captures to configured filesystem and Notion destinations. | `shared_factory/05-knowledge/skills/doc-config-router/` |
| `spec-intake-router` | Capture new specs, proposed features, and planning packets through doc-config routing and work-item intake. | `shared_factory/05-knowledge/skills/spec-intake-router/` |
| `feature-intake-router` | Legacy alias for `spec-intake-router`. | `shared_factory/05-knowledge/skills/feature-intake-router/` |
| `bug-intake-router` | Capture bugs and missed enforcement through doc-config and work-item intake. | `shared_factory/05-knowledge/skills/bug-intake-router/` |
| `auto-spec-intake` | Create/update spec packets for long OS-shaping requests. | `shared_factory/05-knowledge/skills/auto-spec-intake/` |
| `auto-feature-intake` | Legacy alias for `auto-spec-intake`. | `shared_factory/05-knowledge/skills/auto-feature-intake/` |
| `aos-product-orchestrator` | Groom Agentic OS self-improvement proposals into spec packets and Linear issues. | `harness/skills/aos-product-orchestrator/SKILL.md` |
| `os-authoring-guard` | Apply compact OS authoring rules to reusable surface changes. | `shared_factory/05-knowledge/skills/os-authoring-guard/` |
| `automation-qualifier` | Decide whether a process is safe to automate. | `shared_factory/05-knowledge/skills/automation-qualifier/` |
| `quiet-async-runner` | Run long commands, tests, Docker setup, PR checks, and watchers through artifact-backed async state instead of chat polling. | `shared_factory/05-knowledge/skills/quiet-async-runner/` |
| `add-env` | Append environment variables to `~/.zshenv` on bigmac, genomesbox, and the Mac laptop in one step. | `harness/skills/add-env/SKILL.md` |
| `commitall` | Commit all local changes in logical groups until the repository is clean. | `harness/skills/commitall/SKILL.md` |
| `los-fast-workon` | Work a LOS Jira ticket or non-trivial LOS task in a dedicated fast worktree. | `harness/skills/los-fast-workon/SKILL.md` |
| `los-quiet-workon` | Work or resume LOS implementation in a fast worktree with minimal chat output. | `harness/skills/los-quiet-workon/SKILL.md` |
| `thread-finalizer` | Finalize substantive Agentic OS threads with source-of-truth closeout files, evidence receipts, memory decisions, and non-blocking Notion projection receipts. | `shared_factory/05-knowledge/skills/thread-finalizer/` |
| `os-cleaner` | Reconcile OS worktrees and work items after Jira terminal states or merged pull requests. | `shared_factory/05-knowledge/skills/os-cleaner/` |
| `quiet-workon-orchestrate` | Preferred LOS coding/testing orchestration entrypoint with quiet chat, subagents, receipt-backed artifacts, quality holdouts, and PR lifecycle management. | `harness/skills/quiet-workon-orchestrate/SKILL.md` |
| `pr-review` | Canonical review, report, and authority-aware standard-merge entrypoint for others' PRs, using DEV_STANDARDS and F2 family coverage. | `harness/skills/pr-review/SKILL.md` |
| `pull-request` | Compatibility alias to canonical `pr-review`; legacy flags are preserved, but no duplicate review policy remains. | `harness/skills/pull-request/SKILL.md` |
| `watch-pr-quiet` | Monitor GitHub PR checks through file-based watcher artifacts instead of repeated chat polling. | `harness/skills/watch-pr-quiet/SKILL.md` |
| `auto-dev-finalize` | Independently review and finalize every gitflow PR for one tracker ticket, with reciprocal GPT/FABLE review, per-PR opt-out, Copilot/CI/acceptance gates, and guarded family merge. | `harness/skills/auto-dev-finalize/SKILL.md` |
| `auto-dev-validate-production-release` | Read-only validation of the finalized release family, exact revisions, QA, and policy evidence before Merge. | `harness/skills/auto-dev-validate-production-release/SKILL.md` |
| `gitflow-pr-create` | Plan or create missing tracker-keyed PR-family targets from the F2 topology resolver; never merge. | `harness/skills/gitflow-pr-create/SKILL.md` |
| `los-tenant-data` | Route LOS tenant configuration, rules-engine, runtime-data, governed-change, and test-object requests through one local-first program. | `.agents/skills/los-tenant-data/SKILL.md` |
| `los-rules` | List, inspect, search, compare, and check freshness for local redacted LOS rules-engine snapshots. | `.agents/skills/los-rules/SKILL.md` |
| `los-tenant-runtime-operation` | Reuse or create inspect, plan, and approval-gated apply operations for LOS tenant runtime work. | `.agents/skills/los-tenant-runtime-operation/SKILL.md` |
| `los-test-loan` | Plan, generate, and approval-gate repeatable non-production synthetic LOS test loans. | `.agents/skills/los-test-loan/SKILL.md` |
| `composio-cli` | Operate the published Composio CLI for tool discovery, account links, schema inspection, execution, and troubleshooting. | `harness/skills/composio-cli/SKILL.md` |
| `os-doctor` | Audit installed OS structure and contracts. | `shared_factory/05-knowledge/skills/os-doctor/` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os library list/show` | Select a reusable object without scanning definition trees. | Reads the generated canonical registry. |
| `agentic-os library create/migrate-legacy/refresh/doctor` | Create, migrate, regenerate, or validate the versioned object library. | Dry-run first where supported; manifests are canonical. |
| `agentic-os work list/show/active-now` | Read canonical work truth and bounded resume context. | Does not require Jira, Linear, or code-path scans. |
| `agentic-os work upsert/set/import-legacy` | Reconcile lifecycle state, attention, ownership, source identity, blocker receipts, and verification. | Never express state by moving packet folders. |
| `/make-skill` | Create or improve a reusable skill. | Declared in `registries/commands.yml`. |
| `/make-domain` | Create a routed OS domain or room. | Declared in `registries/commands.yml`. |
| `/make-automation` | Create a guarded automation spec. | Declared in `registries/commands.yml`. |
| `/make-workflow` | Create a reusable workflow contract. | Declared in `registries/commands.yml`. |
| `/create-program` | Create a shared OSProgram contract and context bundle. | Declared in `registries/commands.yml`. |
| `/create-instance-program` | Create a domain-local InstanceOSProgram contract and context bundle. | Declared in `registries/commands.yml`. |
| `/status-report` | Generate a recent-work OS status report with markdown receipts, Notion projection, dirty-state scan, and gap analysis. | Declared in `registries/commands.yml`. |
| `/add-spec` | Capture a new spec, proposed feature, or idea through the configured intake workflow. | Declared in `registries/commands.yml`. |
| `/new-feature` | Legacy alias for `/add-spec`. | Declared in `registries/commands.yml`. |
| `/add-bug` | Capture a bug or missed OS enforcement into a routed work item. | Declared in `registries/commands.yml`. |
| `/auto-add-spec` | Create/update a spec packet for long OS-shaping requests. | Declared in `registries/commands.yml`. |
| `/auto-add-feature` | Legacy alias for `/auto-add-spec`. | Declared in `registries/commands.yml`. |
| `/orchestrate` | Decompose, delegate, verify, and merge feature work. | Declared in `registries/commands.yml`. |
| `/pr-review` | Review, report on, or authorized standard-merge others' PRs through M2. | Declared in `registries/commands.yml`. |
| `/gitflow-pr-create` | Plan or create missing F2-required PR-family targets without merging. | Declared in `registries/commands.yml`. |
| `/end-chat` | Finish a substantive thread with closeout artifacts, receipts, memory decisions, and a Notion projection receipt. | Declared in `registries/commands.yml`. |
| `/finalize` | Alias for `/end-chat`. | Declared in `registries/commands.yml`. |
| `/cleanup-thread` | Finalize the thread and classify generated dirt before allowlisted cleanup. | Declared in `registries/commands.yml`. |
| `/los-tenant-data` | Select the canonical workflow for tenant configuration, rules-engine, runtime investigation/change, or test-object work. | Declared in `registries/commands.yml`. |
| `/los-rules` | Analyze local per-environment and per-tenant rules-engine snapshots before live access. | Declared in `registries/commands.yml`. |
| `/los-test-loan` | Preview configuration-reference candidates or create one guarded, idempotent synthetic lower-environment loan at a requested task. | Declared in `registries/commands.yml`. |
| `/archive` | Finalize, then archive only when next action is resolved or explicitly parked. | Declared in `registries/commands.yml`. |
| `agentic-os validate` | Validate the installed root. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |
| `agentic-os program create` | Create a shared OSProgram. | Writes under `harness/shared_factory/00-programs/`. |
| `agentic-os instance-program create` | Create a domain-local InstanceOSProgram. | Writes under `<domain>/00-programs/`. |
| `agentic-os context build` | Build a deterministic context packet. | Use for handoffs and repeatable runs. |
| `agentic-os project onboard` | Create or repair a project-local agent/config surface. | Additive by default. |
| `agentic-os project worktree add` | Register a visible worktree link inside a project. | Keeps the real checkout outside the OS. |
| `agentic-os project worktree cleanup-closed` | Move terminal-status or merged-PR worktree registrations to `worktrees/closed.yml`. | `--remove-files` deletes merged-PR checkouts unless `REOPEN.md` is present. |
| `agentic-os project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. | Run before `finalize-lingering` in cleanup workflows. |
| `harness/rules/os-authoring-rules.md` | Compact authoring rule for OS surfaces and project worktrees. | Load for OS convention changes, not ordinary execution. |
| `harness/bin/agentic-os-quiet-run` | Start long-running local commands with artifact-backed state. | Use for tests, setup, and watchers expected to exceed two minutes. |
| `harness/bin/agentic-os-status-report` | Write recent-work status report bundles with gap analysis and Notion projection receipts. | Use for `/status-report` report generation. |
| `agentic-os config doctor` | Check Codex config contracts. | Does not store secrets. |
| `harness/bin/agentic-os-claude-desktop-bridge` | Build/audit the uploadable Claude Desktop skill and instruction payloads. | Does not claim to modify Claude's cloud-hosted settings. |
| `agentic-os doc-config` | Plan and validate document routing config. | Use before broad "Add this to Notion" writes. |
| `agentic-os config install-tree` | Install Codex config across routed OS layers. | Dry-run by default. |

## MCP Servers

| Config ID | Server | Use When | Install Status | Boundary |
| --- | --- | --- | --- | --- |
| `notion` | Notion | Genome's Notion control-plane reads and approved writes. | installed at every layer | Verify Genome's Notion before writing; do not use Michael Clark's personal workspace. |
| `genomes_brain` | Genome's Brain | Durable cross-session memory reads and non-secret writes. | installed at every layer | No secrets; use project rules and memory policy before writing. |
| `github` | GitHub | GitHub repository, issue, pull request, and code-hosting work. | installed at every layer | Use least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values. |
| `context_mode` | Context Mode | Large-file, repo, and session-memory analysis without flooding prompt context. | installed at every layer | Use for analysis and retrieval; do not use context-mode subprocesses for file writes. |
| `sentry` | Sentry | LOS error, trace, release, and production incident investigation. | visible; LOS layers only | LOS layers only; production/customer-visible changes still require approval. |
| `datadog` | Datadog | LOS observability, logs, metrics, traces, and monitor investigation. | visible; LOS layers only | LOS layers only; do not expose customer data outside approved observability workflows. |
| `supabase` | Supabase | Clark consulting Supabase project work. | visible; clarks_consulting layers only | `clarks_consulting` layers only unless a customer profile explicitly approves Supabase. |
| `composio` | Composio | Federated SaaS tools, OAuth flows, triggers, and app actions routed through `harness/registries/composio-tools.yml`. | visible; route-specific provider order; MCP first when listed | Follow the route provider order in `harness/registries/composio-tools.yml`; for Jira, use Composio MCP before CLI/Rovo. Verify target connection/workspace/account before any write, and record unauthorized/not-connected fallback before native routes. |
| `orgo` | Orgo.io | Isolated cloud desktop and computer-use execution targets. | visible; endpoint or bridge approval required | Visible by default; install only through an approved Orgo MCP bridge or runtime execution target. |
| `playwright` | Playwright | Browser automation and UI validation workflows. | visible; opt in for browser automation layers | Visible by default; add to config only in layers that explicitly own browser automation. |

## Composio Tool Routes

| Route ID | Toolkit | Use When | Layers | Provider Order | Known Tools | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `notion_genome` | `notion` | Genome's Notion page, database, user, and block reads plus approved page/database writes. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `notion_mcp` -> `composio_cli`/`composio` -> `notion_connector` -> `direct_api` | read: `NOTION_SEARCH_NOTION_PAGE`, `NOTION_RETRIEVE_PAGE`, `NOTION_GET_PAGE_MARKDOWN`, `NOTION_FETCH_DATA`, ...; write: `NOTION_CREATE_NOTION_PAGE`, `NOTION_INSERT_ROW_DATABASE`, `NOTION_UPSERT_ROW_DATABASE`, `NOTION_ADD_MULTIPLE_PAGE_CONTENT`, ... | Verify Genome's Notion, then attempt Composio CLI/MCP before connector/direct API fallback; never write to personal/Flywheel Notion. Status: active in Composio registry. |
| `agentmail_genome` | `agent_mail` | Inbox reads, message lookup, inbox discovery, and approved agent email sends. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `agentmail_api` -> `direct_api` | read: `AGENT_MAIL_LIST_INBOXES`, `AGENT_MAIL_LIST_MESSAGES`, `AGENT_MAIL_GET_MESSAGE`; write: `AGENT_MAIL_SEND_EMAIL`, `AGENT_MAIL_CREATE_INBOX` | Attempt Composio CLI/MCP first; sending email or creating inboxes requires explicit approval and recipient verification. Status: active in Composio registry. |
| `confluence_venturesgo` | `confluence` | Confluence page/space search, page reads, child-page traversal, and approved page/comment writes. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `atlassian_rovo` -> `direct_api` | read: `CONFLUENCE_GET_CURRENT_USER`, `CONFLUENCE_GET_SPACES`, `CONFLUENCE_CQL_SEARCH`, `CONFLUENCE_SEARCH_CONTENT`, ...; write: `CONFLUENCE_UPDATE_PAGE`, `CONFLUENCE_CREATE_PAGE`, `CONFLUENCE_ADD_COMMENT` | Attempt Composio CLI/MCP first for venturesgo.atlassian.net; writes require target space/page verification and approval. Status: active in Composio registry. |
| `linkedin_michael` | `linkedin` | LinkedIn profile reads and approved post/comment/share workflows. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `direct_api` | read: `LINKEDIN_GET_MY_INFO`, `LINKEDIN_GET_POST_CONTENT`, `LINKEDIN_GET_COMPANY_INFO`, `LINKEDIN_LIST_REACTIONS`; write: `LINKEDIN_CREATE_LINKED_IN_POST`, `LINKEDIN_CREATE_ARTICLE_OR_URL_SHARE`, `LINKEDIN_CREATE_COMMENT_ON_POST`, `LINKEDIN_REGISTER_IMAGE_UPLOAD` | Attempt Composio CLI/MCP first; public posts, comments, or shares require explicit final-text approval. Status: active in Composio registry. |
| `render_michael` | `render` | Render service, owner, deploy, log, instance, and metrics inspection plus approved deploy actions. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `direct_api` | read: `RENDER_LIST_OWNERS`, `RENDER_LIST_SERVICES`, `RENDER_RETRIEVE_SERVICE`, `RENDER_LIST_DEPLOYS`, ...; write: `RENDER_CREATE_DEPLOY`, `RENDER_TRIGGER_DEPLOY` | Attempt Composio CLI/MCP first; deploys, service changes, env changes, or restarts require explicit service/environment approval. Status: active in Composio registry. |
| `supabase_clarks` | `supabase` | Supabase project, schema, table, type, and read-only SQL inspection plus approved migrations/SQL. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `supabase_mcp` -> `direct_api` | read: `SUPABASE_LIST_ALL_PROJECTS`, `SUPABASE_GET_PROJECT`, `SUPABASE_LIST_TABLES`, `SUPABASE_GET_TABLE_SCHEMAS`, ...; write: `SUPABASE_BETA_RUN_SQL_QUERY`, `SUPABASE_APPLY_A_MIGRATION`, `SUPABASE_DISABLE_PROJECT_READONLY` | Attempt Composio CLI/MCP first; SQL writes, migrations, and readonly disable require explicit project approval. Status: active in Composio registry. |
| `telnyx_michael` | `telnyx` | Telnyx balance, phone number, messaging profile, connection, network, and audit-log inspection. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `direct_api` | read: `TELNYX_GET_USER_BALANCE`, `TELNYX_LIST_PHONE_NUMBERS`, `TELNYX_LIST_MESSAGING_PROFILES`, `TELNYX_LIST_CONNECTIONS`, ... | Attempt Composio CLI/MCP first; messages/calls, number changes, billing, or config writes require explicit approval. Status: active in Composio registry. |
| `slack_genome` | `slack` | Slack context lookup, DM/channel routing, and approved Slack notifications. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `slack_mcp` -> `slack_connector` -> `direct_api` | write: `SLACK_OPEN_DM`, `SLACK_SEND_MESSAGE` | Attempt Composio CLI/MCP first; if unauthorized, not connected, or workspace/channel verification fails, fall back to Slack MCP/connector. Sending requires explicit approval. Status: attempt-first route; active connection not confirmed. |
| `jira_genome` | `jira` | Jira issue/project reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `atlassian_cli` -> `agentic_os_jira` -> `composio_mcp` -> `composio` -> `jira_mcp` -> `composio_cli` -> `atlassian_rovo` -> `direct_api` | read: `acli jira workitem search/view`, `agentic-os-jira doctor/search/get/comments`, `JIRA_GET_ISSUE`, `JIRA_SEARCH_ISSUES`, `JIRA_LIST_ISSUE_COMMENTS`; write: `acli jira workitem ...` and `agentic-os-jira comment/transition --execute` after approval | Prefer official `acli` for Jira reads and approved writes; it is OAuth-authenticated to `venturesgo.atlassian.net`. Use `--description-file` with Jira-native ADF JSON when formatted descriptions, tables, or task lists need to render cleanly. Use `agentic-os-jira` as the scripted doctor/fallback path when CLI output shaping or auth is unreliable. Composio/Jira MCP is fallback only; Atlassian Rovo is last-resort fallback and commonly fails with `oauth_token_invalid_grant`. Writes require ticket-scope approval. |
| `linear_genome` | `linear` | Linear issue/team reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `linear_mcp` -> `linear_connector` -> `direct_api` | discover with `composio search`/`--get-schema` | Attempt Composio CLI/MCP first; if unauthorized, not connected, or workspace verification fails, fall back to Linear MCP/connector. External writes require approval. Status: attempt-first route; active connection not confirmed. |
| `email_genome` | `gmail` | Gmail search/read and approved outbound mail. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `gmail_mcp` -> `email_connector` -> `direct_api` | discover with `composio search`/`--get-schema` | Attempt Composio CLI/MCP first; if unauthorized, not connected, or account verification fails, fall back to Gmail MCP/connector. Sending mail requires approval and recipient verification. Status: attempt-first route; active connection not confirmed. |
| `github_genome` | `github` | GitHub issue, pull request, repo, and code-hosting actions. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli`/`composio` -> `github_mcp` -> `github_cli` -> `direct_api` | discover with `composio search`/`--get-schema` | Attempt Composio CLI/MCP first; if unauthorized, not connected, or repo/org verification fails, fall back to GitHub MCP or gh. Writes require repo/PR/issue scope verification. Status: attempt-first route; active connection not confirmed. |
| `granola_local` | `granola` | Meeting-note lookup and approved notes ingestion when a Granola integration is configured. | agentic_os_root, domain_or_lane, project, workflow_or_task | `composio_cli`/`composio` -> `granola_local` -> `direct_api` | discover with `composio search`/`--get-schema` | Attempt Composio CLI/MCP first; if unauthorized, not connected, or workspace verification fails, fall back to local Granola sources. Read-only by default and do not expose private notes without approval. Status: attempt-first route; active connection not confirmed. |
| `composio_discovery` | `composio` | Unknown slug discovery, schema inspection, connection listing/linking, dry-run validation, proxy fallback, and multi-tool scripting. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_mcp` -> `composio_cli` | read: `COMPOSIO_SEARCH_TOOLS`, `COMPOSIO_MANAGE_CONNECTIONS list`, `COMPOSIO_GET_TOOL_SCHEMAS`, `COMPOSIO_MULTI_EXECUTE_TOOL`; CLI fallback: `composio whoami`, `composio link --list`, `composio search`, `composio execute` | Attempt Composio MCP discovery before CLI/native app routes; execute only after connection and target workspace/account are verified. Record unauthorized/not-connected fallback before native providers. Status: MCP preferred; CLI whoami authenticated but CLI search returned HTTP 401 during verification. |

## Composio Connection Status

CLI status checked on 2026-06-23: `composio` version `0.2.31`; `composio whoami` returns a human session. `composio search` returned HTTP 401 during verification, so agents must still attempt Composio first and record unauthorized/not-connected fallback before native providers.
Registry-confirmed active Composio routes: `notion`, `agent_mail`, `confluence`, `jira` via Composio MCP connection `jira_razz-bae`, `linkedin`, `render`, `supabase`, and `telnyx`. Attempt-first routes with active connection not confirmed in registry: `slack`, `gmail`, `github`, `linear`, and `granola`.

## Direct API Tool Routes

| Route ID | System | Use When | Layers | Provider Order | Credential Ref | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `smartsheet_direct` | `smartsheet` | Smartsheet sheet links, sheet IDs, field matrices, row exports, and derived summaries. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `direct_api` | `SMARTSHEET_API` from environment or `~/.zshenv` | Use the Smartsheet API before browser/login inspection. Never print, log, or write token values; store exports and summaries under the active work item when one exists. Writes require explicit approval. |
## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
| host tool registry | Shell, terminal, runtime, package-manager, and cleanup work. | `shared_factory/05-knowledge/host-tool-registry.<host>.yml` |
| `agentic-os-quiet-run` | Detached artifact-backed execution for long local commands. | `harness/bin/agentic-os-quiet-run` |
| `agentic-os-status-report` | Generate recent-work report bundles. | `harness/bin/agentic-os-status-report` |
| `agentic-os-automation-run-summary` | Replace a pre-mapped automation's Genome Notion Automations child page with the latest run summary. | `harness/bin/agentic-os-automation-run-summary` |

## Programs

| Program | Use When | Source |
| --- | --- | --- |
| `thread_management` | Plan and operate configurable Codex thread inventory, finalizer prompts, duplicate-work detection, Threads Health projection, reminders, and guarded archive policy. | `shared_factory/00-programs/thread_management/` |
| `los_tenant_data` | Route LOS tenant configuration, rules-engine research, runtime data investigation, governed changes, and non-production test-object creation through one operator-facing program. | `../lib/programs/domains/los/los_tenant_data/` |
| `los_config` | LOS tenant configuration values, drift, metadata, freshness, snapshot refresh, live-read fallback, and mutation routing; mutable outputs live under the installed program's `artifacts/`. | `../lib/programs/domains/los/los_config/` |
| `los_rules_engine` | LOS rules output, versions, drift, freshness, twice-daily refresh, and live-read fallback; mutable outputs live under the installed program's `artifacts/`. | `../lib/programs/domains/los/los_rules_engine/` |

## Hooks

| Hook | Use When | Source |
| --- | --- | --- |
| `session-prayer-start` | Commit the session and work to Jesus before startup work begins. | `harness/hooks/session-prayer-start.sh` |
| `memory-write-router` | Routes durable memory writes to the correct substrate without writing CLAUDE.md. | `harness/hooks/memory-session-start.sh` |
| `memory-session-start` | Injects Genome's Brain memory discipline at session start, resume, or clear. | `harness/hooks/memory-session-start.sh` |
| `memory-stop` | Reminds agents to write durable memory before ending substantive turns. | `harness/hooks/memory-stop.sh` |
| `harness-trace-emitter` | Emits non-blocking AGENT_TRACE memory records from Stop hook payloads. | `harness/hooks/harness-emit-trace.sh` |
| `conversation-auto-log` | Writes redacted conversation transcripts and tool-call sidecars to the routed project or work item; resolves explicit active-work-item env/payload values and unique transcript mentions before falling back to project logs. | `harness/hooks/conversation-auto-log.py` |
| `context-mode-cache-heal` | Repairs stale Claude context-mode plugin cache symlinks after auto-updates. | `harness/hooks/context-mode-cache-heal.mjs` |
| `context-mode-codex-hooks` | Preserve context-mode Codex event hooks for session, tool, prompt, compaction, and stop capture. | `context-mode hook codex ...` |
| `mempalace-claude-hooks` | Preserve MemPalace Claude hooks for session-start, stop, and precompact capture. | `~/.local/share/mempalace-venv/bin/mempalace hook run ...` |
| `quiet-pr-watch` | Writes PR check status artifacts instead of long-polling in chat. | `` |
| `stale-thread-finalizer` | Planned conservative sweep for threads untouched more than three days. | `thread-finalizer` |

## Rules

| Rule | Use When | Source |
| --- | --- | --- |
| `external-output-sanitization` | Jira, GitHub, Slack, and work email outputs must omit local filesystem, OS-internal, Mac-only, and Genome's Notion references; small Jira support docs are included directly when practical. | `RULES.md` |

## When To Use What

- Use skills for repeatable agent workflows.
- Use commands for deterministic filesystem or runtime operations.
- Use MCP servers only when the current layer's rules and source boundaries allow them.

## Missing Or Disabled

| Capability | Needed For | Status |
| --- | --- | --- |
| `agentic-os doc-config` CLI route | Planned document-routing CLI flow before broad Notion/filesystem writes. | Registry/docs mention it, but the installed CLI currently rejects `doc-config`; use `doc-config-router` and `shared_factory/00-control-plane/doc-config.yml` meanwhile. |
