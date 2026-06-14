# Plan: Feature 64 SSHFS Remote Mount Namespaces

Created: 2026-06-14

## Baseline

- Start from Feature 63 as implemented remote-source baseline.
- Preserve the current dirty worktree unless it is explicitly part of this feature.
- Re-run `.venv/bin/python -m pytest -q` and `bash .agentic-atlas/tools/validate-cli.sh`
  before implementation and after integration.

## Decomposition

| Unit | Deliverable | Owned files | Notes |
| --- | --- | --- | --- |
| U1: Spec hardening | Duel or project-lead review of `SPEC.md` and command safety contract | `features/64-sshfs-remote-mount-namespaces/*` | Press on macOS FUSE fragility, command execution, and path ambiguity. |
| U2: Metadata and path translation | mount metadata schema, typed helpers, SSH_ namespace detection, local-to-remote path translation | `src/genomes_agentic_os/mount_ops.py`, schemas, tests | No filesystem scans; fake fixtures only. |
| U3: CLI and scaffold | dry-run-first mount/unmount, remote exec, generated rules and project metadata wiring | `src/genomes_agentic_os/cli.py`, `scaffold.py`, templates/rules, tests | External effects require `--apply`; command exec uses remote cwd. |
| U4: Doctor and validation | offline metadata checks plus opt-in mount health probe | `src/genomes_agentic_os/validate.py`, tests | SSHFS availability is a warning, not a baseline blocker. |
| U5: Rollout to losmon | dry-run, operator-approved mount namespace, optional apply, final doctor | installed `~/agentic_os` only | Do not auto-install macFUSE or create root-owned mountpoints. |

## Implementation Guardrails

- Do not reintroduce broad filesystem scans.
- Do not run builds, tests, git, package managers, or watchers through the SSHFS path by
  default.
- Do not require SSHFS for existing remote projects.
- Do not store credentials or private connection details beyond host aliases.
- Keep mount and unmount commands dry-run by default.
- Prefer an explicit `project exec` transport over implicit shell wrapping.

## Open Questions

- Should the default namespace live under the installed OS root, `~/SSH_<host>`, or
  `/Volumes/SSH_<host>` on macOS?
- Should `project exec` be available only for remote-authoritative projects, or for any
  project with a declared remote?
- Should active mount health be stored in `manifest.yml`, a separate `mount.yml`, or only
  reported by doctor?
