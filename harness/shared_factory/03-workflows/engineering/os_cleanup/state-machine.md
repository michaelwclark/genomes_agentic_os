# State Machine: OS cleanup

| From | To | Condition |
| --- | --- | --- |
| `new` | `authority_verified` | Existing item is `delivery_complete`; typed Merge receipt binds reviewed source head, provider, PR reference, merge SHA, and verified readback; Health authority matches it. |
| `authority_verified` | `receipts_audited` | Every required receipt is readable, item-relative, and hashed; missing list is empty. |
| `receipts_audited` | `resume_ready` | Resume manifest and useful worktree-local evidence are durable in the packet. |
| `resume_ready` | `cleanup_preflight` | Packet-local Health preflight freezes exact identities, authority snapshots, holds, paths, branches, ownership, and `clean_only`; live Git status is clean. |
| `cleanup_preflight` | `runtime_reconciled` | Runtime receipt matches the exact identity, records verified readback, and binds `preflight_sha256`. |
| `runtime_reconciled` | `resources_reconciled` | Guarded cleanup consumes all five item-scoping inputs; one atomic resource receipt records both final dispositions. |
| `resources_reconciled` | `registry_reconciled` | Packet-local closed-worktree readback contains the exact live closed row or `not_managed` and is audited under `resource_cleanup`. |
| `registry_reconciled` | `packet_finished` | Packet is moved to `03-complete`; canonical work is finished and pointers are reconciled. |
| `packet_finished` | `validated` | Registries, packet, canonical state, and active indexes agree on readback. |
| `validated` | `done` | Strict Health evidence is accepted from the readable completed packet. |
| any nonterminal state | `blocked` | Authority, receipt, hold, scope, ownership, teardown, removal, move, or readback fails. |
| `blocked` | prior safe state | The named blocker is resolved and preflight evidence is refreshed. |

## Invariants

- State advances only with durable evidence; caller assertions are not receipts.
- Resource mutation cannot occur before `cleanup_preflight`, and worktree
  removal cannot occur before the bound runtime readback.
- A dirty checkout cannot advance through physical removal. A separate operator
  workflow must reconcile it before Health is rerun.
- A failed or skipped removal cannot close or hide the active registry entry.
- A managed closed-worktree snapshot must match live `worktrees/closed.yml`.
- The packet is never deleted.
- `done` requires no residual hold and a readable finished packet.
