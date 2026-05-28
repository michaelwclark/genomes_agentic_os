# Operator-Pushed Customer Updates And Backups

Genome's Agentic OS customer installs should be easy for Genome to update
remotely while still giving the customer a durable backup path. V1 should treat
customer installs as managed OS appliances, not as autonomous package managers.

This spec narrows the first update-channel implementation. The center of V1 is
operator-pushed update access plus backup sync. Phone-home is useful status
reporting, but it is not required for the customer OS to discover and apply
updates by itself.

## Goals

- Let Genome push known OS releases to customer installs quickly.
- Let customer installs pull managed OS updates from GitHub.
- Let customer installs push scrubbed OS-state backups to GitHub.
- Gate update and backup access on the customer's Genome license or API key.
- Use customer-specific SSH keys without Genome transmitting private keys.
- Preserve local customer edits, secrets, runtime logs, and customer data by
  default.
- Keep the design compatible with a later hosted fleet service.

## Non-Goals

- No V1 hosted fleet dashboard is required.
- No customer install should receive a private SSH key from Genome.
- No customer install should get write access to the release/update repository.
- No raw customer data, secrets, env files, or source repositories are backed up
  by default.
- No destructive updates apply automatically.

## Actors

| Actor | Role |
| --- | --- |
| Customer OS | Local installed OS root, usually `~/agentic_os`. Generates keys, applies updates, and writes backup snapshots. |
| Genome operator | Human or automation pushing releases and checking customer status. |
| Genomes Agentic MCP | License and provisioning service. Verifies API key and billing status, then registers public keys with GitHub. |
| GitHub | Transport for update packages and customer backup repositories. |

## Local Identity And Files

The installed OS should keep update identity visible enough for operators while
keeping private key material in a clearly named security directory.

```text
~/agentic_os/
  registries/
    customer-identity.json
    update-grant.json
    backup-policy.yml
  security/
    ssh/
      os_update_ed25519
      os_update_ed25519.pub
      os_backup_ed25519
      os_backup_ed25519.pub
  logs/
    updates/
    backups/
```

Private key files must be mode `0600`. They are generated on the customer host
and are never sent to Genome, GitHub, Notion, logs, or run artifacts.

## Grant Model

The customer's Genome API key is a license credential, not a GitHub credential.
It is used only to activate or renew the local update grant.

Registration flow:

1. Customer OS generates an update SSH keypair locally.
2. Customer OS generates a separate backup SSH keypair locally.
3. Customer OS sends the Genome API key, install identity, and public keys to
   Genomes Agentic MCP.
4. MCP verifies billing and customer status.
5. MCP registers the update public key as read-only access to the update repo.
6. MCP registers the backup public key as write-capable access to the
   customer-specific backup repo.
7. MCP returns remote URLs, allowed capabilities, expiration, and policy.

The two remotes should be separate:

```text
os-upstream     read-only    pulls managed OS releases and update manifests
os-backup       read-write   pushes customer OS backup snapshots
```

If billing becomes inactive, MCP may revoke or stop renewing GitHub access. The
local customer OS should keep running, but updates and backup pushes should fail
with a clear license status.

## Grant Record

`registries/update-grant.json` should be inspectable by humans and agents.

```json
{
  "customer_slug": "momba",
  "install_id": "customer-generated-install-id",
  "status": "active",
  "granted_at": "2026-05-26T00:00:00Z",
  "expires_at": "2026-06-25T00:00:00Z",
  "capabilities": {
    "updates_pull": true,
    "backups_push": true,
    "remote_operator_push": true
  },
  "remotes": {
    "os_upstream": "git@github.com-genomes-momba-update:genome/agentic-os-release.git",
    "os_backup": "git@github.com-genomes-momba-backup:genome-customer-backups/momba-agentic-os.git"
  },
  "safety": {
    "auto_apply": "additive_managed_assets",
    "requires_operator_approval": [
      "delete_files",
      "overwrite_local_edits",
      "change_secrets",
      "enable_external_writes",
      "change_hooks_or_executables"
    ]
  }
}
```

## CLI Surface

Customer-side commands:

```bash
agentic-os license activate --root ~/agentic_os --key <customer-api-key>
agentic-os update register --root ~/agentic_os
agentic-os update plan --root ~/agentic_os --source os-upstream
agentic-os update apply --root ~/agentic_os --source os-upstream
agentic-os update status --root ~/agentic_os
agentic-os backup plan --root ~/agentic_os
agentic-os backup push --root ~/agentic_os
agentic-os backup status --root ~/agentic_os
```

Operator-side command:

```bash
agentic-os fleet push <customer_slug> --source <release-or-ref>
```

The first implementation may make `fleet push` a thin wrapper around SSH or an
existing execution target. It does not need a hosted service.

## Update Safety

Safe additive changes may apply without extra customer ceremony:

- new commands
- new skills
- new templates
- new docs and manual pages
- new registry entries
- new config keys when absent
- managed files whose content hash still matches a prior managed version

Risky changes must stop at a plan until operator approval:

- deleting files
- overwriting local edits
- changing secrets or env files
- enabling new external write permissions
- changing hooks, executables, or launch behavior
- changing customer-visible automation behavior
- changing credentials, models, billing, or remote endpoints

## Backup Safety

Default backup includes OS state, not customer data.

Default include set:

- `registries/`
- runtime status and update grant records
- workflow and automation specs
- run logs and summaries
- OS inventory and capability registry state
- customer profile and handoff artifacts

Default exclude set:

- private keys
- `.env` and secret files
- raw customer files
- source repositories under `projects/`
- large generated artifacts unless explicitly allowed

If customer data backups are enabled later, backup snapshots must be encrypted
before push.

## Validation

Doctor checks should verify:

- install identity exists
- grant file exists and has not expired
- update and backup private keys exist with mode `0600`
- public keys match private keys
- update remote is read-only
- backup remote is separate from update remote
- backup policy has explicit include and exclude lists
- last update and backup status are visible locally

## Relation To Update Channel Spec

`spec/update-channel.md` remains the broader future-state update model. This
spec defines the simpler V1 path:

```text
operator-pushed release -> customer pulls update -> additive apply -> backup/status
```

Phone-home can be added as a heartbeat/status feature after the local update and
backup commands are reliable.

## Open Decisions

- Whether to use GitHub deploy keys first or a GitHub App from the start.
- Whether `fleet push` should use SSH, Orgo execution targets, or both.
- Whether backup repos are one repo per customer or one repo per install.
- Whether backup snapshots should be plain Git commits, tarballs, or both.
- Which files are considered managed assets for hash-based overwrite decisions.
