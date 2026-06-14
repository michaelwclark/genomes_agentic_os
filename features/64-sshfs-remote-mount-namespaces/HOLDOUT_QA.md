# Holdout QA: Feature 64 SSHFS Remote Mount Namespaces

## Goals

Verify that SSHFS mounts improve file access without weakening remote execution safety.

## Test Matrix

| Scenario | Expected |
| --- | --- |
| Path contains `SSH_genomesbox` and project mount metadata exists | Detect host `genomesbox` and translate to the declared remote path. |
| Path contains `SSH_genomesbox` but no project mount metadata matches | Refuse translation with a clear ambiguity or missing-mount error. |
| Path contains ordinary folder `genomesbox/losmon` without `SSH_` | Treat as a normal local path. |
| `mount-remote` without `--apply` | Print planned mount command and write no mount state. |
| `mount-remote --apply` without `sshfs` available | Fail cleanly with an actionable message and no partial metadata mutation. |
| `project exec` for remote-authoritative losmon | Runs through SSH in `/home/genome/projects/losmon`, independent of mount status. |
| Agent-visible rules generated for project | Rules state that file edits may use the mount and repo commands run remotely by default. |
| Doctor without live checks | Validates metadata and does not probe SSHFS or network. |
| Doctor with live mount check | Reports mount health as warning/finding without treating SSHFS absence as baseline failure. |

## Security Checks

- No `shell=True` in local command invocation.
- Remote paths are quoted or passed through the existing safe command builder.
- No secrets, SSH keys, token values, or hostnames-with-passwords appear in generated files.
- Root-owned mountpoints are never created unless the operator explicitly supplies one and
  the command is in apply mode.

## Regression Checks

- Feature 63 remote marker-file behavior still works when no mount metadata exists.
- `project sync-remote` remains usable without SSHFS.
- Existing local `src/` symlink behavior is unchanged.
- Full test suite and atlas CLI validation pass.
