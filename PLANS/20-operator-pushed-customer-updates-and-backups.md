# 20 - Operator-Pushed Customer Updates And Backups

## Intent

Build the first practical customer update system around Genome-managed remote
pushes, customer-generated SSH keys, GitHub-backed update pulls, and
GitHub-backed OS-state backups.

This plan intentionally narrows the heavier auto-updater direction. Customer
installs are mostly operated by Genome or by automation under Genome's control,
so V1 should optimize for easy, repeatable operator-pushed updates rather than
for a fully autonomous customer-side package manager.

## Source Spec

- `spec/operator-pushed-customer-updates.md`
- Related future-state spec: `spec/update-channel.md`

## Build Order

1. Add update and backup identity files to fresh installs.
   - Create `registries/customer-identity.json`.
   - Create `registries/update-grant.json` only after registration.
   - Create `registries/backup-policy.yml`.
   - Create `security/ssh/` and `logs/{updates,backups}/`.
   - Add templates under `templates/runtime/`.

2. Add schemas for grant and backup policy.
   - `schemas/update-grant.schema.json`
   - `schemas/backup-policy.schema.json`
   - Validate generated files from `agentic-os validate`.

3. Add customer license activation.
   - Command: `agentic-os license activate --root <path> --key <key>`.
   - Write customer identity and license status without printing the key.
   - Store only non-secret license metadata in the OS root.

4. Add local SSH key generation.
   - Command: `agentic-os update register --root <path>`.
   - Generate separate update and backup SSH keypairs locally.
   - Enforce private key mode `0600`.
   - Send only public keys to the provisioning client.

5. Add a mockable Genomes Agentic MCP provisioning client.
   - Verify customer API key and billing status.
   - Register update public key as read-only GitHub access.
   - Register backup public key as write-capable GitHub access.
   - Return remote URLs, expiration, policy, and allowed capabilities.
   - Implement a local fake provider for tests before wiring real MCP/GitHub.

6. Add Git remote and SSH config setup.
   - Configure `os-upstream` for read-only update pulls.
   - Configure `os-backup` for backup pushes.
   - Use host aliases so update and backup keys remain separate.
   - Never give the backup key access to the release/update repo.

7. Add update planning and apply commands.
   - `agentic-os update plan --root <path> --source os-upstream`
   - `agentic-os update apply --root <path> --source os-upstream`
   - Reuse the additive managed-asset behavior from `docs update`.
   - Block overwrites, deletes, hook changes, credential changes, and external
     write permission changes unless explicitly approved by the operator.

8. Add backup planning and push commands.
   - `agentic-os backup plan --root <path>`
   - `agentic-os backup push --root <path>`
   - Include OS state, manifests, run logs, workflow specs, automation specs,
     registries, customer profile, and update status.
   - Exclude private keys, secrets, env files, raw customer data, and
     `projects/` by default.

9. Add operator push command.
   - `agentic-os fleet push <customer_slug> --source <release-or-ref>`
   - V1 can invoke a remote command over SSH or an existing execution target.
   - Report update status, backup status, and blocked risky changes.
   - Do not require a hosted fleet dashboard for V1.

10. Add doctor checks and tests.
    - Grant file exists and has not expired.
    - Update and backup keys exist and match their public keys.
    - Private key permissions are `0600`.
    - Update and backup remotes are separate.
    - Backup policy has explicit include and exclude lists.
    - Inactive billing blocks registration and update pulls.
    - Tests run from a fresh temp install and from an existing OS root.

## Acceptance Criteria

- A fresh temp install can activate a fake customer license without printing or
  storing the API key in logs.
- `agentic-os update register` generates customer-local update and backup keys
  and sends only public keys to the provisioning client.
- A fake active billing response writes `registries/update-grant.json` with
  update and backup remotes.
- A fake inactive billing response blocks registration with a clear error.
- Update and backup remotes use separate SSH identities.
- Update access is read-only and backup access is separate from the update repo.
- `agentic-os update plan` identifies safe additive changes and risky blocked
  changes.
- `agentic-os update apply` adds safe managed assets without overwriting local
  edits.
- `agentic-os backup plan` excludes private keys, env files, secrets, raw
  customer data, and `projects/` by default.
- `agentic-os backup push` records a local backup run log even when the remote
  push is skipped or unavailable in tests.
- `agentic-os validate` and `agentic-os doctor` report update/backup grant
  health.

## Notes

Do not ship a private SSH key from Genome to a customer OS. The customer OS owns
the private key, and Genome only provisions access for the public key after
billing verification.

This should become the V1 update implementation. The broader phone-home and
fleet-status model can remain as a future layer after update pull, backup push,
and operator push are reliable.
