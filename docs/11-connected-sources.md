# 11 · Connected Sources

> **Purpose:** give the OS a file-backed, provider-agnostic registry of external
> systems and the per-source polling contracts that describe when and how to turn
> external changes into local source events — which then feed the event ledger
> (page 10) and, eventually, chain rules and queued work.
>
> **You'll use:** `agentic-os connected-system list|doctor`,
> `agentic-os watch-source list|create|doctor|poll|run-due`.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md));
> familiarity with events ([10 · Events & Chains](10-events-and-chains.md)).

---

## Concept

Connected sources are described in two registries that the OS scaffolds under
`shared_factory/00-control-plane/`:

| Registry file | What it holds |
| --- | --- |
| `connected-systems.yml` | Durable external systems (Notion, Slack, GitHub…) with provider priority, credential references, workspace verification, and approval gates |
| `source-providers.yml` | Known provider capabilities (Composio, native MCP, connector, direct API, local script) |
| `watch-sources.yml` | Per-source polling contracts: what to watch, how often, what cursor to advance, which trigger rules to fire |
| `watch-cursors.yml` | Last applied cursor position per source — written by `poll --apply`, untouched by dry-run |
| `harness/registries/composio-tools.yml` | Composio toolkit routes: which toolkit/tool slugs are visible at which OS layers, provider fallback order, and approval boundaries |

A **connected system** is a durable, workspace-verified entry that is resolved once
and shared across many watch sources. A **watch source** is the specific polling
contract for one data stream inside that system — a Notion database, a GitHub repo,
a Slack channel.

**Provider selection** is deterministic. Each connected system declares a
`provider_priority` list. `connected-system list` resolves and displays the first
available provider at list time, so you always know which adapter would be used
before any polling happens.

**Composio routing is explicit.** The generic `composio` provider is not enough
for an agent to know which SaaS action to use. The installed OS also carries
`harness/registries/composio-tools.yml`, and every generated `TOOLS.md` includes
the same route table. Agents should match the request to that registry first,
then inspect a concrete slug with `composio execute <slug> --get-schema` or
discover missing slugs with `composio tools list <toolkit>` / `composio search`.
External writes remain approval-gated even when the Composio account is already
linked.

A **cursor** records the incremental position of each source: the last event ID,
timestamp, or file modification time written during the most recent apply-mode poll.
Dry-run polling never updates the cursor.

**Trigger rules** (inline in each watch source) convert a source event into an
event-ledger entry and/or a run-queue item. Writes are idempotent by the trigger
rule's idempotency key, so re-running `run-due` is always safe.

> **Gap F — partial:** GitHub (`github_repo`) and Slack (`slack_channel`) watch
> sources now have real direct-API adapters.  When the required env var is set the
> adapter fetches live data and populates the normalised event with real items.
> When the env var is absent the adapter falls back to the existing registry
> dry-run path — no behaviour change.  Remaining providers (Notion, Jira, Linear,
> email, Granola, AgentMail, filesystem) still use the registry dry-run path.
> Making those sources live requires the same pattern: (1) the secrets contract
> below, (2) a provider adapter in `source_providers.py`, and (3) a supervisor
> driving `run-due` on a schedule (see [09 · Runtime & Always-On](09-runtime-and-always-on.md)
> and Gap A).

`automation-control` has a narrower Notion status probe for gating expensive
runtime work. It reads a configured watch source's Notion database or data source
ID, counts rows whose status is actionable, and enqueues the target automation
only when capacity is available. That probe is for control decisions; it does not
replace the general `watch-source poll` provider adapter contract.

---

## Secrets contract

> **Rule: registry files and watch-source configs hold env var *names* only.
> Credential values live in the operator's shell environment (or OS keychain).
> The repo and all installed OS roots must never contain a token value.**

### How credentials flow

```
connected-systems.yml
  credential_refs:
    env_vars:
      - GITHUB_TOKEN          ← env var NAME, not value
      - SLACK_BOT_TOKEN       ← env var NAME, not value

Shell environment (set by operator, never committed)
  GITHUB_TOKEN=ghp_xxx...    ← value lives here only
  SLACK_BOT_TOKEN=xoxb-...   ← value lives here only
```

The polling layer reads the env var *name* from `credential_refs.env_vars`, then
resolves the value from `os.environ` at poll time.  The value is used for the
HTTP request and immediately discarded — it is never stored in any event file,
cursor record, or log entry.

An optional `token_env` field may appear on an individual watch source to override
the system-level env var name for that source only:

```yaml
# watch-sources.yml — per-source override (name only, not value)
- id: my_github_source
  ...
  token_env: MY_CUSTOM_GITHUB_TOKEN   # env var NAME
```

### Token-shaped-value guard

The polling layer runs a heuristic check before any network call.  If a
token-shaped value (length ≥ 20, no spaces, matches known token prefixes such as
`ghp_`, `xoxb-`, `sk-`) is found in the watch-source config dict — for example,
an operator accidentally pasted a real token into `external_ref` — the poll is
**refused** with a `SECRETS_IN_CONFIG` finding:

```yaml
ok: false
findings:
  - severity: blocker
    code: SECRETS_IN_CONFIG
    message: "token-shaped values found in config keys: [token]; use
              credential_refs.env_vars to reference env var NAMES only"
```

No network request is made.  The operator must fix the config and re-run.

### Setting up credentials (operator steps)

**GitHub:**
```bash
# Add to ~/.zshenv (or equivalent) — never to any file tracked by git
export GITHUB_TOKEN="ghp_your_personal_access_token"
```
Scopes needed: `repo` (read) for PRs and issues.

**Slack:**
```bash
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
```
OAuth scopes needed: `channels:history`, `groups:history` (or `conversations:read`
for the workspace bot).

After setting the env var, verify with:
```bash
agentic-os watch-source poll <source_id> --root ~/agentic_os --dry-run
```
A successful live poll produces `"live": true` and `item_count > 0` in the adapter
summary.  A missing credential produces `"live": false` and a `dry_run_reason`
message — identical output to the pre-adapter dry-run path.

### What the polling layer stores

When `--apply` is used, the written event file contains:
- Provider-item summaries trimmed to safe fields (title, number, state, timestamps,
  user login — never body text beyond 500 characters for Slack messages)
- A `payload_ref` with `type: live`, `item_count`, and `provider`
- A `credential_env` field with the env var *name* used (never the value)
- A stable idempotency key derived from provider-issued event IDs (not timestamps)

Tokens, raw API responses, and full message bodies are never persisted.

---

## Flow diagram

![Connected sources flow: connected-system registry selects a provider; a watch-source definition with cursor passes doctor checks; dry-run poll previews a normalized event; apply-mode poll writes a source event file and advances the cursor; matching trigger rules append to the event ledger (page 10) and enqueue work; a supervisor tick (page 09) drives the loop](diagrams/sources-connected-flow.png)

---

## Registry files at a glance

### `connected-systems.yml` — key fields

| Field | Purpose |
| --- | --- |
| `id` | `snake_case` system identifier (e.g. `notion_genome`) |
| `system` | System type: `notion \| slack \| jira \| linear \| email \| github \| granola \| agentmail \| filesystem \| other` |
| `status` | `planned` until a live adapter is wired |
| `provider_priority` | Ordered list — first available wins at list/poll time |
| `credential_refs.env_vars` | Env var names that hold secrets (never stored here) |
| `workspace_verification` | Expected workspace/account — verified structurally by doctor |
| `approval_required_for` | Gates that must be recorded before an external write fires |
| `health_check.command` | The doctor command for this system |

### `harness/registries/composio-tools.yml` — key fields

| Field | Purpose |
| --- | --- |
| `id` | Stable route id, usually matching a connected-system id |
| `toolkit` | Composio toolkit slug or CLI family (`slack`, `github`, `agent_mail`, `composio`) |
| `route_when` | Plain-language task match for agents |
| `layer_scope` | Agentic OS layers where the route is visible |
| `provider_priority` | Ordered provider fallback for that toolkit |
| `read_tools` / `write_tools` / `trigger_tools` | Known concrete slugs or CLI operations; empty lists mean discover with `composio tools list <toolkit>` |
| `approval_required_for` | Effects that must be approved before execution |
| `boundary` | Workspace, account, data, and write restrictions |

### `watch-sources.yml` — key fields

| Field | Purpose |
| --- | --- |
| `connected_system` | Must match an id in `connected-systems.yml` |
| `source_type` | `notion_database \| slack_channel \| jira_jql \| linear_team \| email_search \| github_repo \| granola_folder \| agentmail_inbox \| filesystem_glob` |
| `external_ref` | Provider-specific identity (e.g. `database_id=<uuid>`) — no live call |
| `watch_method` | `poll` (only method today) |
| `cadence` | `manual` by default; a future supervisor reads this |
| `enabled` | `false` until doctor passes; disabled sources are skipped by `run-due` |
| `cursor.type` | `last_edited_time \| event_id \| timestamp \| page_token \| file_mtime` |
| `cursor.state_ref` | Always `shared_factory/00-control-plane/watch-cursors.yml` |
| `dedupe.idempotency_key` | Template string ensuring duplicate polls don't double-write |
| `trigger_rules` | Inline rules: when + then (emit event / enqueue) + approval + idempotency key |

---

## Commands & flags

### `connected-system list`

List all registered systems and their resolved (selected) providers.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

```bash
agentic-os connected-system list --root ~/agentic_os
```

Exit: **0** on success.

### `connected-system doctor <system_id>`

Structural health check for one connected system. Fails closed when:
- no `provider_priority` declared
- referenced providers missing from `source-providers.yml`
- no healthy selected provider resolves
- `workspace_verification` or `health_check` metadata absent

```bash
agentic-os connected-system doctor notion_genome --root ~/agentic_os
```

Exit: **0** healthy · **1** findings.

---

### `watch-source list`

List all configured watch sources (enabled and disabled).

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

```bash
agentic-os watch-source list --root ~/agentic_os
```

Exit: **0** on success.

### `watch-source create <source_id>`

Register a new watch source. Creates a disabled entry in `watch-sources.yml` with
a default trigger rule (also disabled). Enable only after doctor passes.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `source_id` | ✅ (positional) | `snake_case` identifier |
| `--root` | — | Installed OS root |
| `--connected-system` | — | System id (default: `notion_genome`) |
| `--source-type` | — | Source type (default: `notion_database`) |
| `--external-ref` | — | `key=value`; repeat for multiple refs |
| `--cadence` | — | Poll cadence hint (default: `manual`) |
| `--route-to` | — | Fallback domain (default: `shared_factory`) |
| `--enabled` | — | Enable immediately (only after doctor passes) |

```bash
agentic-os watch-source create agentic_os_kanban \
  --root ~/agentic_os \
  --external-ref database_id=366683b48dab81a1ab5fc73e7e1f5c60 \
  --enabled
```

Exit: **0** created or already exists.

### `watch-source doctor <source_id>`

Structural health check for one watch source. Fails closed when:
- connected system not found in registry
- `source_type`, `external_ref`, `cursor`, or `dedupe.idempotency_key` missing
- `route` command / context / fallback absent
- source is enabled but has no enabled trigger rule with id, event type, action, and idempotency key

```bash
agentic-os watch-source doctor agentic_os_kanban --root ~/agentic_os
```

Exit: **0** healthy · **1** findings.

### `watch-source poll <source_id>`

Poll one source. **Dry-run by default** — pass `--apply` to write.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `source_id` | ✅ (positional) | Source to poll |
| `--root` | — | Installed OS root |
| `--dry-run` | — | Preview only (default) — no files written, cursor unchanged |
| `--apply` | — | Write source event file + advance cursor + fire trigger rules |

```bash
# Preview
agentic-os watch-source poll agentic_os_kanban --root ~/agentic_os --dry-run

# Commit
agentic-os watch-source poll agentic_os_kanban --root ~/agentic_os --apply
```

`--apply` writes one event YAML to `shared_factory/06-runs-and-logs/source-events/`
and records the cursor in `watch-cursors.yml`. If a trigger rule matches, it also
appends to the event ledger and/or enqueues work in `run-queue.yml` (idempotent by
the trigger rule's idempotency key).

Exit: **0** success · **1** doctor findings blocked the poll.

### `watch-source run-due`

Poll every **enabled** watch source. Disabled sources are skipped. **Dry-run by
default.**

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root |
| `--dry-run` | — | Preview all due sources (default) |
| `--apply` | — | Execute polling for all enabled sources |

```bash
# Preview all
agentic-os watch-source run-due --root ~/agentic_os --dry-run

# Execute all
agentic-os watch-source run-due --root ~/agentic_os --apply
```

Exit: **0** on completion (per-source failures reported in output, not as exit 1).

---

## Real output examples

### `connected-system list` (excerpt — first two of eight systems)

```text
# CMD: agentic-os connected-system list --root /tmp/aos-validate/root
# ---
connected_systems:
- id: notion_genome
  display_name: Genome Notion
  system: notion
  status: planned
  owner: Genome
  provider_priority:
  - notion_mcp
  - notion_connector
  - direct_api
  credential_refs:
    env_vars:
    - GENOMES_NOTION_PAT
  workspace_verification:
    required: true
    expected_workspace: Genome's Notion
  permissions:
    read:
    - database.query
    write: []
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor notion_genome
  selected_provider: notion_mcp
- id: slack_genome
  display_name: Genome Slack
  system: slack
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - slack_mcp
  - slack_connector
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
  ...
  selected_provider: composio
```

Note `status: planned` and `selected_provider` resolved at list time from the
`source-providers.yml` registry — `list` makes no live connection. Live polling
happens in `watch-source poll`, which has real GitHub and Slack providers
(Gap F status: [18 · Troubleshooting, Part B](18-troubleshooting-and-faq.md)).

### `watch-source list` (fresh install — no sources yet)

```text
# CMD: agentic-os watch-source list --root /tmp/aos-validate/root
# ---
watch_sources: []
```

Sources are created with `watch-source create` and start disabled. Run
`watch-source list` after creation to confirm registration.

---

## Running this from Claude vs Codex

> Same registry files, same doctor and poll logic, same cursor — only the trigger
> differs.

- **Claude:** run the `/os-watch-source` command, or invoke the **`source-watcher`**
  skill (it walks you through connected-system verification, watch source definition,
  doctor checks, and dry-run poll before any apply path).
- **Codex:** run `agentic-os watch-source poll <source_id> --dry-run --root ~/agentic_os`
  directly, or `watch-source run-due --dry-run` for all enabled sources. The
  `agentic_os_root` profile in `config.toml` governs the model and tool allow-list
  for the session.

Full mechanics and setup: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **Doctor before enable.** A source that fails `watch-source doctor` blocks
  `poll` — the poll returns the doctor findings and exits 1. Keep sources
  `enabled: false` until doctor is green.
- **Dry-run is the default.** Both `poll` and `run-due` require an explicit
  `--apply` flag to write anything. Omitting it is always safe.
- **`poll` takes a positional `source_id`.** Running `watch-source poll --dry-run`
  without naming a source is a usage error (exit 2).
- **Live polling for GitHub and Slack (Gap F partial).** When `GITHUB_TOKEN` or
  `SLACK_BOT_TOKEN` is set, `poll` makes a real API call and populates live items
  in the event.  When the credential is absent, the existing registry dry-run path
  is used unchanged — no error.  Other providers (Jira, Linear, etc.) still use
  the registry dry-run path. Notion has a narrow status probe in
  `automation-control` for gating, not a general source-event adapter (see
  [Secrets contract](#secrets-contract) above).
- **Secrets are never stored in registry files.** `credential_refs.env_vars` lists
  env var *names* only. The values must be present in the shell environment when a
  live adapter eventually reads them.
- **Approval gates are declared, not enforced yet.** `approval_required_for` fields
  in connected-system entries are structural declarations. Enforcement depends on
  automation maturity + approval rules (see [07 · Automations](07-automations.md)).
- **Names are `snake_case`.** `watch-source create my-source` is rejected (exit 2).
  Use `my_source`.
- **`run-due` does not schedule itself.** It polls what is due when you run it.
  Autonomous periodic polling requires a supervisor driving `run-due --apply` on a
  cadence — the supervisor is a planned capability (see
  [09 · Runtime & Always-On](09-runtime-and-always-on.md)).

---

## Related

- [09 · Runtime & Always-On](09-runtime-and-always-on.md) — the supervisor that
  drives `run-due` on a cadence once installed per host (Gap A closed).
- [10 · Events & Chains](10-events-and-chains.md) — the event ledger that source
  events feed; chain rules that react to them.
- [07 · Automations](07-automations.md) — maturity and approval rules that gate
  what trigger rules can enqueue.
- [17 · CLI Reference](17-cli-reference.md) — full flag listing for all commands.
- [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) — doctor failures,
  cursor resets, disabled-source skips.
- Atlas: [`command-reference.md §8`](architecture/command-reference.md) ·
  Gap F status (GitHub + Slack live): [18 · Troubleshooting, Part B](18-troubleshooting-and-faq.md)
