# Context Mode

Intended Notion path: `Projects -> Genome's Agentic OS -> Experiments -> Context Mode`

Source: https://github.com/mksglu/context-mode

Status: candidate experiment, not yet approved for full-time Genome's Agentic OS usage.

Final decision: graduate Context Mode into the working default for Genome's Agentic OS on `bigmac` and `genomesbox`.

Final report date: 2026-05-27.

Final measured status:

- `bigmac`: Context Mode ON for Claude and Codex; `94.1 MB` kept out of context, `15.7 MB/day`, across 2 tools.
- `genomesbox`: Context Mode ON for Claude and Codex; `45.0 MB` kept out of context, `7.5 MB/day`, across 2 tools.

Decision rationale:

- The savings are material and continued to accumulate over multiple days.
- Claude plugin, Codex MCP, and Codex hooks remained enabled on both primary hosts.
- No Context Mode-specific breakage was captured during the experiment.
- The kill switch was tested and remains available via `agentic-os-context-mode`.
- Composio remains a separate routing/tooling experiment and should not block Context Mode graduation.

Follow-up operating rule:

- Keep Context Mode ON by default on `bigmac` and `genomesbox`.
- Keep the kill switch installed.
- Treat future Composio routing work as a separate Tool Router / MCP routing design problem.
- Do not keep recurring Context Mode experiment check-ins running after this final report.

## Current Implementation Status

Updated: 2026-05-20.

Context Mode is installed and enabled on the two requested operating hosts:

- `bigmac` Claude Code: installed through the official Claude plugin marketplace as `context-mode@context-mode`.
- `bigmac` Codex: installed through npm, registered as a Codex MCP server, and wired into Codex hooks.
- `genomesbox` Claude Code: installed through the official Claude plugin marketplace as `context-mode@context-mode`.
- `genomesbox` Codex: installed through npm, registered as a Codex MCP server, and wired into Codex hooks.

Verification completed:

- Claude doctor passed on both hosts.
- Codex doctor passed on both hosts.
- Codex `PreToolUse`, `PostToolUse`, `SessionStart`, `PreCompact`, `UserPromptSubmit`, and `Stop` hooks passed on both hosts.
- FTS5 / SQLite passed on both hosts.
- The official Codex marketplace source `mksglu/context-mode` is registered on both hosts.
- `genomesbox` uses an explicit `~/.local/bin/context-mode` wrapper so Context Mode runs under the existing Node 22 runtime instead of the system Node 20 runtime.

Kill switch:

- Command: `agentic-os-context-mode status|on|off|hooks-off|mcp-off|purge`
- Installed on both `bigmac` and `genomesbox` at `~/.local/bin/agentic-os-context-mode`.
- `off` disables the Claude plugin and removes only the Context Mode Codex hook entries while leaving the Codex MCP registration available for MCP-only comparison.
- `on` re-enables the Claude plugin and restores the Codex MCP/hooks wiring.
- The OFF -> ON cycle was tested on both hosts and left Context Mode enabled.

Still not done:

- Real-work ON/OFF token and context comparisons.
- Decision on whether Context Mode should become a full-time Genome's Agentic OS default.
- Documentation of observed savings from `ctx stats` after actual Claude/Codex sessions use it.

Related concurrent experiment:

- Composio is also being tested as a possible MCP tooling layer.
- Treat Composio as a confounding variable for Context Mode results because it may change tool names, routing behavior, MCP payload shape, auth behavior, and failure modes.
- If Context Mode appears to save less context, break tools, or miss MCP payloads, separate whether the cause is Context Mode itself or the Composio MCP path.
- For ON/OFF comparisons, record whether Composio was enabled, which MCP tools were routed through it, and whether failures happened in native MCP, Composio, or Context Mode hooks.

## Results Log

Notion should carry the running experiment log. Each row should capture:

- Date/time
- Host: `bigmac` or `genomesbox`
- Harness: Claude or Codex
- Context Mode state: ON, OFF, hooks-only, MCP-only, or purged
- Composio state: ON, OFF, partial, or unknown
- `ctx stats` summary
- Token/context observation
- Failure or friction observed
- Benefit observed
- Decision impact: promote, keep testing, keep optional, or remove

Use this log before deciding whether Context Mode graduates into a full-time Genome's Agentic OS default.

## Summary

Context Mode is an MCP/plugin layer for AI coding agents that tries to keep large tool output out of the conversation window. Instead of sending raw logs, snapshots, fetched pages, or large file reads directly into context, it routes work through sandboxed tools, indexes the larger material into SQLite FTS5, and returns smaller, intent-focused results.

The project claims large context reductions, exposes `ctx stats` for measurement, and supports Claude Code and Codex CLI through plugin manifests, MCP tools, and hooks. Claude has the stronger integration surface today. Codex support is useful but should be treated as experimental because the README says Codex hooks still depend on gated feature flags and upstream hook behavior.

## Why This Is Interesting

Genome's Agentic OS depends on long-running agent sessions, cross-project continuity, and clean handoffs between Claude, Codex, local files, Notion, and memory. Context Mode is aimed directly at that problem area:

- It reduces raw tool-output pressure on the context window.
- It records session events such as file edits, git operations, errors, tasks, decisions, and compaction snapshots.
- It can search indexed material on demand instead of re-reading everything.
- It gives a measurable stats surface for context savings and tool behavior.
- It has a purge command, which matters for privacy and clean-session tests.

## Initial Rollout Goal

Install and test Context Mode in Claude and Codex on both `genomesbox` and `bigmac`, but keep it behind an obvious kill switch until the behavior is measured.

Target surfaces:

- `genomesbox` Claude
- `genomesbox` Codex
- `bigmac` Claude
- `bigmac` Codex

Do not make it the permanent default until ON/OFF test runs show that it improves context health without hiding important evidence, breaking tools, or adding enough friction that it changes the working style.

## Install Notes From Upstream

Claude Code:

- Plugin marketplace install is the preferred path.
- Verify with `/context-mode:ctx-doctor`.
- Monitor with `/context-mode:ctx-stats`.
- Optional status line can show session savings in `~/.claude/settings.json`.

Codex CLI:

- Requires Node.js `>=22.5` or Bun.
- Preferred path is Codex plugin marketplace install.
- Hook usage currently requires enabling `[features].hooks = true` and `[features].plugin_hooks = true`.
- `ctx stats` verifies that MCP is reachable, but does not prove hooks are trusted or running.
- Hook behavior must be verified separately after Codex accepts or trusts the plugin hook commands.
- Manual fallback is available with global `context-mode`, a `~/.codex/config.toml` MCP block, and a `~/.codex/hooks.json` file.

## Experiment Plan

1. Capture a baseline before install.
   - Current Claude/Codex versions on each host.
   - Current Node/Bun versions on each host.
   - Current Claude/Codex plugin/MCP/hook config.
   - One representative task run without Context Mode.
   - Token/context behavior from normal Codex and Claude usage where available.

2. Install on one host and one harness first.
   - Start with the lowest-risk path, likely Claude on one host.
   - Run `ctx doctor` and `ctx stats`.
   - Confirm no project files are polluted by auto-written routing files.
   - Confirm purge and disable paths before moving to the next surface.

3. Expand to the four target surfaces.
   - Claude on `genomesbox`.
   - Codex on `genomesbox`.
   - Claude on `bigmac`.
   - Codex on `bigmac`.

4. Run paired ON/OFF tests.
   - Same repo.
   - Same style of task.
   - Same agent harness where possible.
   - Record tool-call count, context savings, wall-clock time, failure rate, and whether the final answer lost important detail.

5. Decide whether it graduates into Genome's Agentic OS.
   - Approve only if it is measurable, reversible, and compatible with existing memory and harness conventions.

## Metrics To Track

- `ctx stats` context savings by session.
- Raw tool output avoided.
- Indexed/search retrieval hit rate.
- Number of times the agent still reads large raw data directly.
- Session resume quality after compaction.
- Whether important evidence is hidden by aggressive filtering.
- Failed or blocked tool calls introduced by hooks.
- Latency added by hook and MCP routing.
- Storage growth under Context Mode data directories.
- Privacy posture: what is persisted, where it is stored, and whether secrets are redacted.

## Kill Switch Requirements

The experiment is not acceptable without a fast OFF path.

Required kill-switch behavior:

- Disable Context Mode for Claude without deleting unrelated Claude config.
- Disable Context Mode for Codex without deleting unrelated Codex config.
- Disable only hooks while leaving MCP available for comparison testing.
- Disable only MCP while preserving install files for quick re-enable.
- Purge Context Mode indexed/session data when needed.
- Keep host-specific changes obvious in a short manifest.

Proposed kill-switch shape:

- Add a small local wrapper or script per host, for example `agentic-os-context-mode off|on|status|purge`.
- Keep a backup of touched config files before first mutation.
- Use a single environment flag or config toggle where upstream supports it.
- For Codex, make `[features].plugin_hooks` and hook trust/config state part of the status check.
- For Claude, make plugin enabled/disabled state and optional status line part of the status check.

## Risks And Open Questions

- Codex hook support is not as mature as Claude support. Codex should not be considered fully proven until hook execution and trust prompts are verified live.
- Context Mode persists session and indexed data. Confirm exact storage paths, retention behavior, and purge coverage before using it on sensitive client work.
- It may interact oddly with existing memory systems. The OS should define whether Context Mode is a short-term context optimizer, a durable memory source, or only an evidence cache.
- Composio is being tested at the same time for MCP tooling. Keep it tracked separately so Context Mode is not blamed for Composio-specific auth, routing, payload, or tool-shape issues.
- Aggressive filtering can hide useful raw evidence. Tests need to include debugging tasks where exact logs matter.
- The Elastic License 2.0 license should be checked before bundling or redistributing anything in public Agentic OS artifacts.
- Multi-host parity needs an inventory: versions, install method, config files touched, and enablement status for `genomesbox` and `bigmac`.

## Acceptance Criteria For Full-Time Use

- Claude and Codex installs are reproducible on both hosts.
- ON/OFF tests show real context savings without meaningful quality loss.
- The kill switch is documented and tested.
- `ctx stats`, `ctx doctor`, and purge commands work on each surface.
- Storage paths and retention are documented.
- The integration does not overwrite or conflict with existing Claude/Codex global instructions.
- Genome's Agentic OS docs clearly state when to use Context Mode tools versus normal shell/file tools.

## Next Check-In

Review this experiment after a few days of real use. The check-in should answer:

- Is it installed on all four target surfaces?
- Did it reduce context usage in real work?
- Did it break or slow anything?
- Is the kill switch good enough?
- Should it become a default part of Genome's Agentic OS, stay optional, or be removed?
