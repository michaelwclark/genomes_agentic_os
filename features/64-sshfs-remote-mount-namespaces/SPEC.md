# Feature 64: SSHFS Remote Mount Namespaces

## Status

- Status: planned
- Owner: Genome operators
- Created: 2026-06-14
- Target OS layer: source package and installed runtime
- Source feature: `63-remote-ssh-project-sources`

## Problem

Feature 63 made remote SSH project sources first-class, but it intentionally represented
remote code with marker files and synced manifests instead of mounts. That kept v1 safe,
but it still leaves agents with a split experience: project metadata lives in the OS tree,
while the authoritative files live behind SSH commands.

For trusted hosts such as `genomesbox`, operators want a local-looking path that is
obviously remote-backed:

```text
.../SSH_genomesbox/losmon/
  -> genomesbox:/home/genome/projects/losmon
```

The path should be hard to miss, require no broad file scans, and avoid a sync step. At
the same time, Agentic OS must not accidentally run builds, tests, package installs, git
operations, or long-running watchers locally against an SSHFS mount.

## Outcome

Agentic OS supports an optional SSHFS-backed file access layer for remote projects while
keeping command execution remote by default. A path component named `SSH_<host>` is a
visible, operator-readable marker that the subtree is remote-backed. Agents may read and
edit files through the mounted path, but project commands are translated to `ssh <host>`
with the remote working directory from the project manifest.

## Design

### Root path convention

Any path component matching this pattern marks an SSHFS namespace:

```text
SSH_<host>
```

Examples:

```text
/Users/genome/agentic_os/SSH_genomesbox/losmon
/Volumes/SSH_genomesbox/losmon
~/SSH_genomesbox/losmon
```

Rules:

- The `SSH_` prefix is the signal. Agents do not scan the subtree to discover whether it
  is remote.
- `<host>` maps to a key in `<root>/config/hosts.yml`; host aliases remain the only
  connectivity reference stored in the OS.
- The child folder name, such as `losmon`, is only a mount label. It must not be the only
  source of truth for the remote path.
- The project remote manifest or `project.yml sources.remotes[]` entry maps the mount to
  the remote path.

### Project metadata

Extend a remote source with optional mount metadata:

```yaml
sources:
  remotes:
    - name: losmon
      host: genomesbox
      path: /home/genome/projects/losmon
      kind: git
      authority: remote
      mount:
        namespace: SSH_genomesbox
        local_path: /Users/genome/agentic_os/SSH_genomesbox/losmon
        access: sshfs
        execution: remote
```

The mount metadata is declarative. It records intent and lets agents translate paths. It
does not mean the mount is currently active.

### Command execution rule

If the current working directory or target file path is under an `SSH_<host>` namespace,
Agentic OS treats it as remote-backed.

Allowed through the local mounted path:

- read files
- inspect small files
- edit files
- create or remove files as part of explicit source edits

Run remotely by default:

- `git`
- package-manager commands
- builds
- tests
- dev servers
- services
- file watchers
- commands that recursively traverse the repo
- commands whose effects depend on OS, sockets, processes, or installed runtimes

Remote command shape:

```bash
ssh -o BatchMode=yes <host> 'cd <remote-path> && <command>'
```

The implementation should use argv-list subprocess invocation and quote remote paths using
the same security posture as `remote_ops.py`. It must not use `shell=True` locally.

### Path translation

Translation is deterministic and metadata-backed:

```text
local:  /Users/genome/agentic_os/SSH_genomesbox/losmon/src/index.ts
remote: genomesbox:/home/genome/projects/losmon/src/index.ts
```

Required behavior:

- Match the nearest path component named `SSH_<host>`.
- Resolve `<host>` through `config/hosts.yml`.
- Match the remainder against declared mount metadata.
- Translate the relative suffix onto `sources.remotes[].path`.
- Refuse ambiguous matches instead of guessing.

### CLI surface

Planned commands:

```bash
agentic-os project mount-remote <domain> <project> [--name <remote-name>] [--namespace <path>] [--apply]
agentic-os project unmount-remote <domain> <project> [--name <remote-name>] [--apply]
agentic-os project exec <domain> <project> [--name <remote-name>] -- <command...>
```

Behavior:

- `mount-remote` dry-runs by default and prints the exact SSHFS command it would run.
- `--apply` performs the mount only if `sshfs` is available and the destination is inside
  an approved namespace path.
- `unmount-remote` dry-runs by default and uses the platform-appropriate unmount command
  only with `--apply`.
- `project exec` always runs on the remote host for a remote-authoritative project.
- Mount commands never install macFUSE, system extensions, packages, or kernel modules.

### Generated rules

Root and project generated rules should include a concise managed section:

```md
Any path component named `SSH_<host>` is an SSHFS remote namespace. Files under it
may be read or edited locally, but repo commands run on `<host>` with the remote
cwd from the project manifest. Do not run builds, tests, package installs, git,
or watchers locally from an SSHFS path unless the operator explicitly asks for
local-mount execution.
```

This rule belongs in surfaces visible to both Claude and Codex.

## Scope

- Add schemas and typed helpers for mount metadata.
- Add path detection and path translation helpers.
- Add dry-run-first mount and unmount operations.
- Add remote execution helper for remote project commands.
- Update project scaffolding so remote projects can expose mount metadata and generated
  rules.
- Add doctor checks for malformed mount declarations, unknown SSH_ hosts, missing host
  registry entries, ambiguous mount paths, and stale or unavailable active mounts.
- Add tests with fake runners; no test may require a real SSHFS mount.

## Out Of Scope

- Automatic macFUSE, sshfs, or package installation.
- Root-owned `/SSH_<host>` mountpoint creation by default.
- Two-way sync, rsync mirrors, or background reconciliation.
- Running heavy commands locally through SSHFS.
- Long-running auto-reconnect daemons.
- Using SSHFS as a required dependency for remote projects. Marker-file remotes from
  Feature 63 remain the safe baseline.

## Affected Surfaces

- CLI: `project mount-remote`, `project unmount-remote`, `project exec`
- Runtime OS files: project `project.yml`, remote manifest, generated AGENTS/CONTEXT/RULES
- Source package modules: likely `remote_ops.py`, a new `mount_ops.py`, `scaffold.py`,
  `validate.py`, `cli.py`
- Schemas: remote mount metadata and host-reference validation
- Tests: new `tests/test_remote_mounts.py`

## Acceptance Criteria

- A path under `SSH_genomesbox/losmon` is detected as remote-backed without scanning
  folder contents.
- The same path translates to `genomesbox:/home/genome/projects/losmon/...` only when a
  project remote declares that mount.
- Agents receive prompt-visible rules that local file access is allowed but repo commands
  are remote by default.
- `mount-remote` and `unmount-remote` are dry-run by default and never install system
  software.
- `project exec` runs commands over SSH in the remote cwd and does not depend on SSHFS
  being mounted.
- Doctor is offline by default, validates metadata, and has an explicit opt-in check for
  active mount health.
- Full test suite and atlas CLI validation pass.

## Rollout Notes

Feature 63's marker-file representation remains the default. This feature adds an optional
mounted file-access layer for trusted hosts. Rollout to `losmon` should first update the
source package, then run the new dry-run commands against `~/agentic_os`, then apply the
mount only after confirming the operator-approved local namespace path.
