# 15 · Customer OS Factory

> **Purpose:** spin up a fully isolated, client-safe Agentic OS for a customer from
> a single profile YAML — complete with its own `ROUTER/CONTEXT/RULES/TOOLS`, approved
> domains, capability registries, and customer-facing assets — without any operator
> data leaking across the boundary.
>
> **You'll use:** `agentic-os customer init`, `agentic-os customer validate`,
> `agentic-os customer update`.
> **Prereqs:** an installed operator OS ([01 · Install & Quickstart](01-install-and-quickstart.md));
> a customer profile YAML (template at
> `templates/profile/customer-os-profile.yml`; example at
> `customer_profiles/example-customer.yml`).

---

## The factory model

A **customer OS** is a self-contained Agentic OS root for one client. It is not a
domain inside your operator OS — it lives at an independent directory path and carries
its own `AGENTS.md`, routing, context, and registries. When a harness operates inside a
customer OS root it sees only that customer's approved domains, source systems, and
approved tools; the operator's domains, skills, and private identifiers are
structurally excluded.

The factory is driven by a **customer profile YAML**. The working example
(`customer_profiles/example-customer.yml`, verbatim):

```yaml
customer:
  slug: acme_ops
  display_name: Acme Operations
  owner: Operations Lead
  notion_workspace: Acme Notion
  approved_domains:
    - support
  source_systems:
    - name: helpdesk
      role: customer support inbox
      access: read
  default_workflows:
    - domain: support
      lane: support
      name: intake_triage
  default_automations:
    - domain: support
      lane: support
      name: thread_intake
  approval_policy:
    external_writes_require_approval: true
    customer_visible_output_requires_approval: true
    production_changes_require_approval: true
    destructive_actions_require_approval: true
```

A blank template is at `templates/profile/customer-os-profile.yml` (use
`profile create --target <p>` to copy it). The same profile drives the real output
examples below.

**Filesystem is source of truth.** The profile YAML records intent; `customer init`
materialises it as files; `customer validate` confirms structure. There is no runtime
database; what is on disk is what the OS is.

---

## Diagram

![Profile YAML is fed to customer init, which checks that the CLI slug matches the profile's customer.slug, then renders the customer OS tree: root context files (ROUTER, CONTEXT, RULES, TOOLS), approved domain scaffolds, customer/ assets, and registries. The resulting customer OS root is then validated by customer validate, which exits 0 on success or 1 with a core_errors list.](diagrams/customer-os-factory.png)

---

## Commands & flags

### `agentic-os customer init <slug> --profile <p> --target <t>`

Create a customer OS from a profile. All three arguments are required.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `customer_slug` | Yes | Customer identifier (snake\_case). Must match `customer.slug` in the profile. |
| `--profile` | Yes | Path to the customer profile YAML. |
| `--target` | Yes | Destination directory for the new customer OS root. |

Writes: full OS directory tree at `--target`, shaped by the profile.

**Slug-match rule:** if the profile's `customer.slug` field is set to a concrete
value (not the `<customer_slug>` placeholder), it must equal the `customer_slug`
argument. A mismatch is caught at startup:

```
error: profile customer.slug 'acme_ops' does not match 'acme_corp'
```

Exit code: **2** (raised as a `ValueError` before any files are written).

---

### `agentic-os customer validate --root <r>`

Validate a customer OS root. `--root` is **required** — there is no default.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | Yes | Customer OS root path. |

Reads: the customer OS tree at `--root`. Writes: nothing.

Exit 0 if `ok: true`; exit 1 if validation errors are found. Checks:
required root files (`ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`,
`customer.yml`, etc.), required registries (`customer-identity.json`,
`backup-policy.yml`), runtime folders (`security/ssh`, `logs/updates`,
`logs/backups`), and, if `customer.yml` is present, the approved-domain scaffolds.

---

### `agentic-os customer update <slug> --root <r>`

Add missing customer OS assets (additive — does not overwrite existing files).
`--root` is **required** — there is no default.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `customer_slug` | Yes | Customer identifier. |
| `--root` | Yes | Customer OS root path. |

Use after editing a profile to add a new approved domain or asset without
rebuilding from scratch.

---

## What `customer init` creates

Running `customer init acme_ops --profile …/example-customer.yml --target /tmp/example-corp-os` produces:

**Root-level context files (the harness entry points):**
```
/tmp/example-corp-os/ROUTER.md
/tmp/example-corp-os/AGENTS.md
/tmp/example-corp-os/CLAUDE.md
/tmp/example-corp-os/CONTEXT.md
/tmp/example-corp-os/RULES.md
/tmp/example-corp-os/TOOLS.md
/tmp/example-corp-os/customer.yml
```

**Capability registries:**
```
/tmp/example-corp-os/registries/capabilities.yml
/tmp/example-corp-os/registries/commands.yml
/tmp/example-corp-os/registries/skills.yml
/tmp/example-corp-os/registries/mcp-servers.yml
/tmp/example-corp-os/registries/customer-identity.json
/tmp/example-corp-os/registries/backup-policy.yml
```

**Customer-facing assets (under `customer/`):**
```
/tmp/example-corp-os/customer/client-automation-brief.md
/tmp/example-corp-os/customer/automation-fit-matrix.md
/tmp/example-corp-os/customer/handoff-checklist.md
/tmp/example-corp-os/customer/update-contract.md
```

**Approved domain scaffold** (`support/`, from `example-customer.yml`):
```
/tmp/example-corp-os/support/ROUTER.md
/tmp/example-corp-os/support/CONTEXT.md
/tmp/example-corp-os/support/RULES.md
/tmp/example-corp-os/support/TOOLS.md
/tmp/example-corp-os/support/domain.yml
/tmp/example-corp-os/support/00-control-plane/
/tmp/example-corp-os/support/01-inbox/
/tmp/example-corp-os/support/03-workflows/
/tmp/example-corp-os/support/04-automations/
… (full numbered-lane scaffold)
```

**Runtime and security folders:**
```
/tmp/example-corp-os/security/ssh/
/tmp/example-corp-os/logs/updates/
/tmp/example-corp-os/logs/backups/
```

---

## Real output

### `customer init`

```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os customer init acme_ops --profile /Users/genome/projects/genomes_agentic_os/customer_profiles/example-customer.yml --target /tmp/aos-validate/customer
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/customer
customer: acme_ops
created:
- /private/tmp/aos-validate/customer/.agentic_root
- /private/tmp/aos-validate/customer/bin
- /private/tmp/aos-validate/customer/commands
- /private/tmp/aos-validate/customer/skills
- /private/tmp/aos-validate/customer/mcp
- /private/tmp/aos-validate/customer/plugins
- /private/tmp/aos-validate/customer/libraries
- /private/tmp/aos-validate/customer/hooks
- /private/tmp/aos-validate/customer/rules
- /private/tmp/aos-validate/customer/registries
- /private/tmp/aos-validate/customer/registries/capabilities.yml
- /private/tmp/aos-validate/customer/registries/commands.yml
- /private/tmp/aos-validate/customer/registries/skills.yml
- /private/tmp/aos-validate/customer/registries/mcp-servers.yml
- /private/tmp/aos-validate/customer/registries/libraries.yml
- /private/tmp/aos-validate/customer/registries/hooks.yml
- /private/tmp/aos-validate/customer/registries/plugins.yml
- /private/tmp/aos-validate/customer/registries/rules.yml
- /private/tmp/aos-validate/customer/INVENTORY.md
- /private/tmp/aos-validate/customer/agentic-os.lock.json
- /private/tmp/aos-validate/customer/UPDATE_POLICY.md
- /private/tmp/aos-validate/customer/registries/updates.yml
- /private/tmp/aos-validate/customer/security
- /private/tmp/aos-validate/customer/security/ssh
- /private/tmp/aos-validate/customer/logs
- /private/tmp/aos-validate/customer/logs/updates
- /private/tmp/aos-validate/customer/logs/backups
- /private/tmp/aos-validate/customer/registries/customer-identity.json
- /private/tmp/aos-validate/customer/registries/backup-policy.yml
- /private/tmp/aos-validate/customer/README.md
- /private/tmp/aos-validate/customer/ROUTER.md
- /private/tmp/aos-validate/customer/AGENTS.md
- /private/tmp/aos-validate/customer/CLAUDE.md
- /private/tmp/aos-validate/customer/CONTEXT.md
- /private/tmp/aos-validate/customer/RULES.md
- /private/tmp/aos-validate/customer/TOOLS.md
- /private/tmp/aos-validate/customer/customer.yml
- /private/tmp/aos-validate/customer/customer/README.md
- /private/tmp/aos-validate/customer/customer/handoff-checklist.md
- /private/tmp/aos-validate/customer/customer/automation-fit-matrix.md
- /private/tmp/aos-validate/customer/customer/client-automation-brief.md
- /private/tmp/aos-validate/customer/customer/update-contract.md
… (50+ paths total — support/ domain scaffold, shared_factory/ templates, and skipped: [])
```

### `customer validate`

```text
# CMD: agentic-os customer validate --root /tmp/aos-validate/customer
# ---
root: /private/tmp/aos-validate/customer
ok: true
core_errors: []
profile_warnings: []
```

---

## Customer profile fields

| Field | Required | Description |
| --- | --- | --- |
| `customer.slug` | Yes | Snake\_case identifier. Must match the `customer_slug` CLI argument. |
| `customer.display_name` | No (defaults to slug) | Human-readable name used in generated headers. |
| `customer.owner` | No | Contact name for the customer account. |
| `customer.notion_workspace` | No | Notion workspace name; flagged as warning if empty on validate. |
| `customer.approved_domains` | Yes (or derived from `rooms[].id`) | List of domain slugs to scaffold. Defaults to `["operations"]` if empty. |
| `customer.source_systems` | No | Systems the customer OS may read; flagged as warning if absent. |
| `customer.default_workflows` | No | Workflow stubs to pre-scaffold; flagged as warning if absent. |
| `customer.default_automations` | No | Automation stubs to pre-scaffold; flagged as warning if absent. |
| `approval_policy.*` | No | Four boolean gates (external writes, customer-visible output, production changes, destructive actions). |

**Private-term guard:** domain slugs and the customer slug must not match the
reserved operator-identity terms (`genome`, `clark`, `clarks_consulting`, `los`,
`lenders`). Attempting to use one exits 2 with `error: approved domain uses a
private Genome source name: 'genome'` (the offending value is named).

---

## The customer data boundary

A customer OS sets `content_boundary.public_customer_install: true` and
`source_owner_domains_excluded: true` in the normalised profile. These flags drive
the context files generated inside the OS:

- `RULES.md` prohibits copying private source-package terms, internal client
  names, or unrelated tenant data into customer artifacts.
- `CONTEXT.md` scopes approved source systems to the customer's declared list.
- `TOOLS.md` surfaces only the customer-safe capability registry (a curated subset
  of the operator's full registry).

When Codex operates inside a customer OS root it picks up the `customer_os_root`
config layer from `<customer_os>/.codex/config.toml`. That layer sets the customer
data boundary, customer-scoped MCP servers, and approval policy — overriding the
operator-level Codex config for all work done inside that root. See
[13 · Agent Surfaces](13-agent-surfaces.md) for the full five-layer config model.

---

## Room-first installs (related profile-driven path)

`profile create` / `profile validate` / `room create` / `room update` (backed by
`room_profile.py`) are the **room-first** counterpart: instead of a
`customer.slug`-keyed profile they use an `os`-keyed profile whose `rooms[]` array
drives domain creation directly via `agentic-os init --profile`.

| Command | `--root` required? | Description |
| --- | --- | --- |
| `profile create --target <p>` | — | Write a room-first profile template to `<p>`. |
| `profile validate <profile>` | — | Validate a room-first profile YAML. |
| `room create <slug>` | No (default `~/agentic_os`) | Scaffold a room inside the operator OS. |
| `room update <slug>` | No (default `~/agentic_os`) | Apply profile changes to an existing room. |

**Real `profile validate` output:**

```text
# CMD: agentic-os profile validate /tmp/aos-validate/os.yml
# ---
profile: /tmp/aos-validate/os.yml
rooms:
- writing_room
ok: true
```

Use the room-first path when setting up named working rooms inside your own
operator OS. Use the customer factory path (`customer init`) when delivering an
isolated OS to a client that should have no visibility into your operator context.

---

## Running this from Claude vs Codex

| Harness | How to invoke |
| --- | --- |
| **Claude** | Run the `client-automation-brief` skill first to capture the customer's workflow and boundaries; then invoke `agentic-os customer init` via the CLI. Use `room-builder` if creating rooms inside the operator OS. |
| **Codex CLI** | `agentic-os customer init <slug> --profile <p> --target <t>` — same binary, same flags. Codex picks up the `customer_os_root` config layer automatically once the OS is initialised. |

Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **Slug must match the profile.** If `customer.slug` is concrete (not the
  `<customer_slug>` placeholder), the CLI slug argument must be identical. Mismatch
  exits 2 before any files are written: `error: profile customer.slug 'X' does not
  match 'Y'`.
- **`--root` is required for `validate` and `update`.** Neither command has a
  default path. Omitting `--root` is a parse error (argparse exits 2 with a usage
  message), not a runtime warning.
- **`customer init` uses `--target`, not `--root`.** The distinction matters: `--target`
  is a write destination (a new tree is created there); `--root` reads an existing
  tree.
- **`customer update` is additive.** It will not overwrite files that already
  exist. Re-run `validate` after to confirm the tree is complete.
- **Private-term guard is strict.** The terms `genome`, `clark`, `clarks_consulting`,
  `los`, and `lenders` are blocked in slugs and domain names at init time, not just
  at validate time. Exit 2; the offending value is named in the error message.
- **macOS path expansion.** The CLI resolves `~/` and symlinks; output paths may
  show `/private/tmp/…` when you passed `/tmp/…`. This is expected.
- **`profile_warnings` are non-blocking.** Empty `notion_workspace`,
  `source_systems`, `default_workflows`, and `default_automations` produce warnings
  on validate but do not set `ok: false`.

---

## Related

- [08 · Client OS Patterns](08-client-os-patterns/README.md) — the operating patterns
  (Client Domain Shape, Client Operations, Candidate Pipeline, Internal Product) that
  customer OS roots are designed to support.
- [13 · Agent Surfaces](13-agent-surfaces.md) — the five-layer Codex config model,
  including the `customer_os_root` layer.
- [14 · Config, Update & Backup](14-config-update-backup.md) — `update register`,
  `backup run`, and key management for customer OS installs.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — running
  `doctor` inside a customer OS to detect missing files and broken links.
- [17 · CLI Reference](17-cli-reference.md) — full flag tables for every command.
- Atlas: [`architecture/system-architecture.md`](../.agentic-atlas/architecture/system-architecture.md) ·
  [`command-reference.md §13`](../.agentic-atlas/architecture/command-reference.md)
