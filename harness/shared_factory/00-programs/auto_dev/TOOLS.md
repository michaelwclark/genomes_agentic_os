# Auto-Dev Tools

## Manual workflow entrypoints

| Need | Command or skill | Result |
| --- | --- | --- |
| Full implementation delivery | `/auto-dev` or `agentic-os develop start ...` | state/worktree/quality/release receipts |
| Effective code/QA/gitflow policy | `agentic-os develop policy ...` | ordered sources and fingerprint |
| Excellent provider artifact | `/auto-dev-create-artifacts` or `agentic-os artifacts ...` | native draft, validation, apply/readback receipts |
| Deep bug/RCA investigation | `/auto-dev-detective` | versioned evidence packet and report |
| Others' PR review | `/pull-request` | blocker-focused review receipt |
| Effective inherited OS rules | `agentic-os rules effective ...` | strictest-wins rule projection |

## Provider routes

Use the final routed layer's `TOOLS.md` for the currently registered Jira,
Linear, Notion, Confluence, GitHub, Slack, observability, memory, VPN/runtime,
and filesystem adapters. Resolver/renderer code does not own authentication.

External provider apply follows: verified target → native payload → provider
tool → readback → hash/identity receipt. A provider response without readback is
not completion.
