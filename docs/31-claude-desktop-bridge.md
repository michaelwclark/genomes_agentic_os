# Claude Desktop Bridge

Agentic OS has three distinct Claude surfaces:

| Surface | How it receives the operating contract |
| --- | --- |
| Claude Code or Claude Desktop local-folder conversation | Root `CLAUDE.md`/`AGENTS.md` dispatch adapters, then the canonical `harness/` contract and local routed layer. |
| Claude Desktop ordinary chat that is not opened from an Agentic OS folder | Account-level Instructions for Claude plus an enabled custom skill. |
| Claude Desktop project or Cowork project | The local-folder contract when it is opened from the OS root; otherwise the enabled custom skill plus the project's instructions and knowledge. |

`~/.claude/settings.json` and the skill symlinks managed by
`register-harness-skills` are Claude Code surfaces. They are not a supported
way to impose rules on ordinary Claude Desktop chats. Conversely, when a
conversation is opened from `~/agentic_os`, the installed root must retain its
root `CLAUDE.md` and `AGENTS.md` discovery adapters; the full contract remains
canonical under `harness/`.

## Build the Desktop artifacts

Run the bridge against the installed OS:

```sh
harness/bin/agentic-os-claude-desktop-bridge --root ~/agentic_os --build
```

It writes these deterministic artifacts under
`harness/artifacts/claude-desktop/`:

- `agentic-os-operating-contract.zip` — upload in Claude Desktop under
  Customize > Skills, then enable it.
- `PROFILE_INSTRUCTIONS.md` — paste in Settings > Instructions for Claude to
  require the skill for Agentic OS work in standard chats.
- `PROJECT_INSTRUCTIONS.md` — paste into an Agentic OS Claude project's
  instructions for a stronger project-local contract.
- `manifest.json` — records hashes and the manual installation boundary.

Run the same command with `--audit` to verify that local artifacts still match
their source. The local tool deliberately does not modify or claim to inspect
Claude's cloud-hosted account/project settings; those UI actions are the final
activation step.

The operating-contract skill is also in the shared skill registry, so
`register-harness-skills --user-scope` exposes the same procedure to Codex and
Claude Code. It is optional for local-folder conversations once the root
dispatch adapters are present; it remains useful for regular Claude Desktop
chats that are not opened from the Agentic OS root.
