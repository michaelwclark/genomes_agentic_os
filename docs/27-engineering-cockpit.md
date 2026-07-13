# Engineering Cockpit

The Agentic OS cockpit is a local-first projection that makes the operating
system easier to see without moving authority into a new app.

It answers nine daily questions:

1. What matters today?
2. What work is active?
3. Which Claude and Codex conversations belong to that work?
4. Which PRs need attention?
5. Where are the useful reports?
6. What workflows and automations exist?
7. Which Slack, Jira, GitHub, and local sources are actually being used?
8. What is known about each host?
9. What lifecycle state needs cleanup?

## Storage Model

The cockpit does not become a source of truth. It collects canonical Agentic OS
files into `agentic-os-cockpit/v1`, then renders a disposable `index.html`.
Collectors are isolated behind that contract so a future database-backed state
repository can replace file scans without rewriting the UI.

## Commands

```bash
agentic-os cockpit snapshot --root ~/agentic_os
agentic-os cockpit build --root ~/agentic_os
agentic-os cockpit open --root ~/agentic_os
```

The default bundle is written to:

```text
~/agentic_os/harness/shared_factory/06-runs-and-logs/cockpit/latest/
```

## Conversation Boundary

V1 inventories OS-owned conversation sidecars plus bounded metadata from local
Claude and Codex JSONL stores. It does not depend on private vendor APIs or try
to replace proprietary chat rendering. Raw prompts remain in their canonical
transcripts; the snapshot keeps route, harness, status, references, and evidence
metadata.

## Dynamic Sources

Observed Jira keys, GitHub repositories and PRs, Slack channels, work-item
references, and conversation activity are ranked as suggestions. Suggestions
are not configured watches. Enabling a watch remains an explicit guarded action
through the existing source-watch surface. The snapshot preserves total signal
and evidence counts while bounding rendered evidence and the ranked suggestion
queue, so the discovery layer stays useful when OS activity becomes large.

## Reports

Report cards use progressive disclosure:

- one sentence for the first screen;
- short detail with scope, status, and next action;
- a link to the canonical report or evidence.

The renderer does not copy twenty pages of implementation documentation into a
daily summary.

## Hygiene And Host Safety

Hygiene findings and host cards are read-only. The cockpit may show an existing
guarded command for stale worktrees, quiet threads, or live host diagnostics,
but it never runs that command implicitly and never contacts a remote host while
building a static snapshot.
