# Claude Code `settings.json`: Exhaustive Reference Catalog

A complete guide to every configuration key Claude Code supports, with types, defaults, examples, and gotchas. This is for the first time you write a `settings.json` from scratch.

---

## File Locations & Precedence

Claude Code reads settings from three locations, with later entries overriding earlier ones:

1. **`~/.claude/settings.json`** (global, user-scoped)
   - Applies to all projects and sessions
   - Baseline configuration across your development environment
   - Use for personal preferences, global permissions, trusted tools

2. **`<repo>/.claude/settings.json`** (project-scoped, relative to repo root)
   - Overrides global settings for this project only
   - Checked in to version control (shared team config)
   - Use for project-specific tools, conventions, CI/CD integrations
   - Team members see the same rules

3. **`<repo>/.claude/settings.local.json`** (project-local, not checked in)
   - Overrides both global and project settings (highest priority)
   - Gitignored; private to your machine
   - Use for machine-specific paths, local dev secrets, personal overrides
   - Example: `{ "permissions": { "allow": ["Bash(./my-local-script.sh)"] } }`

**Precedence formula:** built-in defaults &lt; `~/.claude/settings.json` &lt; `<repo>/.claude/settings.json` &lt; `<repo>/.claude/settings.local.json`

**Merge behavior:** Arrays merge (allow + deny rules accumulate); objects merge at each level. If you add a permission rule in `.local.json`, it combines with rules in `settings.json`, not replacing them.

**Adjacent files (not `settings.json`, but read alongside):**

- `~/.claude/mcp.json` and `<repo>/.claude/mcp.json` — canonical MCP server config (see MCP section)
- `~/.claude/keybindings.json` — keyboard shortcuts (see Keybindings section)
- `<repo>/.claude/policy-limits.json` — enterprise/managed restrictions
- `~/.claude/CLAUDE.md` and `<repo>/CLAUDE.md` — memory/instructions auto-loaded by the model (composes other files via `@path/to/file.md`)

---

## Model & Reasoning Configuration

### `model`
- **Type:** string (enum)
- **Default:** `"claude-opus-4-1"`
- **What it does:** Sets the default Claude model for main tasks, code generation, and reasoning. Subagents may use different models via `advisorModel`.
- **Valid values:**
  - `"claude-opus-4-1"` — latest Opus, best reasoning and multi-step work
  - `"claude-sonnet-4-20250514"` — mid-tier, good speed/quality balance
  - `"claude-haiku-4-5"` — fastest, lightweight lookup work
  - Other Claude 3+ models via version string
- **Example:**
  ```json
  { "model": "claude-opus-4-1" }
  ```
- **Notes:** Changing this affects ALL conversations in the session. Some environments (Bedrock, Vertex AI) may have different model names; Claude Code will map them at runtime.

### `advisorModel`
- **Type:** string (enum)
- **Default:** `"claude-opus-4-1"`
- **What it does:** Sets the model used by advisor/orchestrator roles (main thread logic, code review, architecture decisions). Separate from `model` so you can run fast generation (Sonnet main) but keep advisor reasoning on Opus.
- **Valid values:** Same as `model`
- **Example:**
  ```json
  { "advisorModel": "claude-opus-4-1", "model": "claude-sonnet-4-20250514" }
  ```
- **Notes:** Only used when the main thread role is explicitly "advisor" or when spawning subagents. If you only run conversations interactively, this may have no visible effect.

### `effortLevel`
- **Type:** string (enum)
- **Default:** `"high"`
- **What it does:** Balances speed vs thoroughness. Higher levels use more API calls, longer thinking, more exploratory work. Lower levels assume your task is simple and finish faster.
- **Valid values:**
  - `"low"` — minimal exploration, fast paths only
  - `"medium"` — balanced, typical use case
  - `"high"` — thorough, multiple approaches, verification steps
  - `"xhigh"` — exhaustive, parallel exploration, multiple attempts
- **Example:**
  ```json
  { "effortLevel": "xhigh" }
  ```
- **Notes:** This affects reasoning time, number of API calls, and tool invocations per task. `xhigh` is useful for complex system design, security reviews, or multi-step refactors; `low` is good for mechanical fixes you've already thought through.

---

## Permissions

Permissions control which tools Claude can use and when. They work as a filter at four decision points:

1. **Deny rules** — immediate block, never prompt
2. **Ask rules** — always prompt the user
3. **Allow rules** — automatic approval, no prompt
4. **defaultMode** — fallback when no rule matches

### `permissions.allow`
- **Type:** array of strings (tool patterns)
- **Default:** `[]`
- **What it does:** Tools and commands Claude can use without asking for permission.
- **Pattern syntax:**
  - **Bash:** `"Bash(git status)"` exact match, `"Bash(git *)"` with args, `"Bash(git:*)"` any git subcommand
  - **Other tools:** `"Read"`, `"Write"`, `"Edit"`, `"WebFetch"`, `"WebSearch"`
  - **MCP tools:** `"mcp__github"` all tools from GitHub server, `"mcp__github__create_pr"` specific tool
  - **Wildcards:** `"*"` matches all tools (unrestricted mode)
- **Example:**
  ```json
  {
    "permissions": {
      "allow": [
        "Bash(git status)",
        "Bash(git log*)",
        "Read",
        "mcp__github__list_pull_requests"
      ]
    }
  }
  ```
- **Notes:** Allow rules are evaluated AFTER deny rules. A tool matching both allow and deny will be denied.

### `permissions.deny`
- **Type:** array of strings (tool patterns)
- **Default:** `[]`
- **What it does:** Tools and commands Claude is forbidden to use, always blocks without prompting.
- **Pattern syntax:** Same as `allow`
- **Example:**
  ```json
  {
    "permissions": {
      "deny": [
        "Bash(rm -rf *)",
        "Bash(git push --force*)",
        "Bash(docker compose down*)"
      ]
    }
  }
  ```
- **Notes:** Deny rules are evaluated FIRST; if any deny rule matches, the tool is blocked immediately regardless of allow rules. Use these for dangerous patterns (force push, destructive deletes).

### `permissions.ask`
- **Type:** array of strings (tool patterns)
- **Default:** `[]` (but behavior varies by tool risk)
- **What it does:** Tools and commands that should always prompt, even if allowed. Used for high-impact operations where you want explicit approval every time.
- **Pattern syntax:** Same as `allow`
- **Example:**
  ```json
  {
    "permissions": {
      "ask": [
        "Bash(git push*)",
        "Edit",
        "mcp__jira__update_issue"
      ]
    }
  }
  ```
- **Notes:** Ask rules take precedence over allow rules. If a tool matches both, the user is prompted.

### `permissions.defaultMode`
- **Type:** string (enum)
- **Default:** `"default"` (ask for most tools)
- **What it does:** Sets the fallback behavior when no explicit allow, deny, or ask rule matches a tool.
- **Valid values:**
  - `"default"` — prompt the user (safe, interactive)
  - `"acceptEdits"` — auto-approve most write operations
  - `"plan"` — auto-approve reads and planning tools, ask on writes
  - `"dontAsk"` — auto-approve everything except truly destructive (rm -rf, etc.)
  - `"bypassPermissions"` — auto-approve all tools (unrestricted, use only in isolated/sandboxed environments)
- **Example:**
  ```json
  {
    "permissions": {
      "defaultMode": "plan"
    }
  }
  ```
- **Notes:** `bypassPermissions` skips permission checks entirely, including writes to `.git/`, `.claude/`, `.vscode/`, and `.idea/` directories. Only use in Docker, CI/CD, or truly isolated environments.

### `permissions.additionalDirectories`
- **Type:** array of strings (absolute paths)
- **Default:** `[]`
- **What it does:** Marks additional directories as "safe" for writes, so Claude can edit files there without extra permission prompts. By default, writes to `.git/`, `.claude/`, `.vscode/`, `.idea/`, and `.husky/` require explicit approval unless `defaultMode` is very permissive.
- **Example:**
  ```json
  {
    "permissions": {
      "additionalDirectories": [
        "/Users/genome/.local/bin",
        "/opt/custom-tools"
      ]
    }
  }
  ```
- **Notes:** Use this for project-wide tool directories or shared scripts. Paths are absolute; relative paths are not expanded.

---

## Hooks

Hooks are scripts or commands that run at specific lifecycle points in Claude Code's execution, allowing you to validate, transform, or block actions.

### Hook File Locations

Hooks are configured in `settings.json` under the `hooks` object. Each hook is a command or script that receives context via stdin (JSON) and can exit with a decision code.

### Hook Event Types

#### Session-level hooks (once per session)

**`hooks.SessionStart`**

- **When:** Claude Code starts or resumes a conversation
- **Matcher:** Optional; `"startup"`, `"resume"`, `"clear"` match different session starts
- **Payload:** Session metadata (correlationId, version, workingDirectory)
- **Use case:** Initialize tools, fetch credentials, validate environment
- **Example:**
  ```json
  {
    "hooks": {
      "SessionStart": [
        {
          "matcher": "startup|resume",
          "hooks": [
            {
              "type": "command",
              "command": "/path/to/init-session.sh",
              "timeout": 10,
              "statusMessage": "Initializing session..."
            }
          ]
        }
      ]
    }
  }
  ```

**`hooks.SessionEnd`** (and `hooks.Stop` in modern Claude Code)

- **When:** Claude Code shuts down or session ends
- **Matcher:** Optional
- **Payload:** Final session state
- **Use case:** Cleanup, save state, emit traces, archive logs
- **Example:**
  ```json
  {
    "hooks": {
      "Stop": [
        {
          "hooks": [
            { "type": "command", "command": "/path/to/session-cleanup.sh", "timeout": 5 }
          ]
        }
      ]
    }
  }
  ```

#### Turn-level hooks (once per user prompt)

**`hooks.UserPromptSubmit`**

- **When:** User submits a prompt to Claude
- **Matcher:** Optional; filter by intent/keywords
- **Payload:** The user's prompt text, intent classification
- **Use case:** Validate prompt, check for banned terms, route to specialized handlers
- **Example:**
  ```json
  {
    "hooks": {
      "UserPromptSubmit": [
        {
          "matcher": "security|audit",
          "hooks": [{ "type": "command", "command": "/path/to/security-gate.sh" }]
        }
      ]
    }
  }
  ```

**`hooks.Stop`** (end of turn)

- **When:** Claude completes a turn (submits response, tool calls complete)
- **Matcher:** Optional
- **Use case:** Capture turn metrics, emit analytics, validate output

#### Tool-call hooks (runs inside the agentic loop, per tool)

**`hooks.PreToolUse`**

- **When:** Before Claude executes a tool (Write, Edit, Bash, MCP, etc.)
- **Matcher:** Required; filter by tool name, e.g., `"Bash(rm *)"`, `"Write"`, `"mcp__github*"`
- **Payload:** Tool name, arguments, file path (if applicable), operation type
- **Exit code:**
  - `0` — allow tool (continue)
  - `1` — error (block tool, show error to user)
  - `2` — deny (block tool silently, try alternative)
- **Decision field:** Can output JSON with `{ "decision": "allow" | "block" }` to override
- **Use case:** Validate before dangerous operations, enforce patterns, gate risky commands
- **Example:**
  ```json
  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Bash(git push*)",
          "hooks": [{ "type": "command", "command": "/path/to/validate-git-push.sh" }]
        }
      ]
    }
  }
  ```

**`hooks.PostToolUse`**

- **When:** After Claude completes a tool execution
- **Matcher:** Required; same syntax as PreToolUse
- **Payload:** Tool name, arguments, result/output, execution time
- **Exit code:**
  - `0` — success
  - `1` — error (log the error, continue)
  - `2` — retry (re-run the tool)
- **Use case:** Format output, run linters, test changed files, clean up side effects
- **Example:**
  ```json
  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Write|Edit",
          "hooks": [{ "type": "command", "command": "/path/to/lint-on-save.sh" }]
        }
      ]
    }
  }
  ```

**`hooks.SubagentStop`**

- **When:** A spawned subagent (Agent tool, /orchestrate, /pull-request, etc.) finishes
- **Matcher:** Optional (filter by subagent type)
- **Payload:** Subagent type, exit reason, summary
- **Use case:** Aggregate parallel work, verify subagent return contract, fail-fast on subagent error

#### Permission & notification hooks

**`hooks.PermissionRequest`**

- **When:** Claude Code displays a permission dialog
- **Matcher:** Optional; filter by tool/permission type
- **Payload:** Tool name, command, permission type
- **Exit code:**
  - `0` — allow
  - `1` — deny
  - `2` — prompt user (default)
- **Use case:** Auto-approve or auto-deny certain patterns based on policy
- **Example:**
  ```json
  {
    "hooks": {
      "PermissionRequest": [
        {
          "matcher": "Bash(npm run *)",
          "hooks": [{ "type": "command", "command": "/path/to/auto-approve-npm.sh" }]
        }
      ]
    }
  }
  ```

**`hooks.Notification`**

- **When:** Claude Code sends an alert or notification to the user
- **Matcher:** Optional
- **Payload:** Notification type, message, severity
- **Use case:** Log notifications, route critical alerts to Slack/email

#### Context & maintenance hooks

**`hooks.PreCompact`**

- **When:** Before Claude Code compacts the conversation history (removes old messages to save tokens)
- **Matcher:** Optional
- **Payload:** Messages to be removed, summary context
- **Use case:** Archive old context, persist important decisions, emit metrics
- **Example:**
  ```json
  {
    "hooks": {
      "PreCompact": [
        {
          "hooks": [{ "type": "command", "command": "/path/to/pre-compaction-archive.sh", "timeout": 30 }]
        }
      ]
    }
  }
  ```

### Hook Payload Format

Hooks receive JSON via stdin with this structure:

```json
{
  "hookType": "PreToolUse",
  "hookVersion": 1,
  "timestamp": "2026-05-26T14:23:45Z",
  "sessionId": "sess_abc123",
  "workingDirectory": "/Users/genome/projects/los",
  "tool": {
    "name": "Bash",
    "arguments": {
      "command": "git push origin main"
    }
  },
  "decision": null,
  "context": {
    "branch": "feature/DLOS-40000",
    "dirty": false
  }
}
```

### Hook Fields

#### `hooks[EventType][].type`
- **Type:** string (enum: `"command"` or `"script"`)
- **Default:** `"command"`
- **What it does:** Whether the hook is an external command (shell invocation) or inline script
- **Example:** `{ "type": "command", "command": "/path/to/hook.sh" }`

#### `hooks[EventType][].command`
- **Type:** string (path to executable or script)
- **Default:** none (required if `type` is `"command"`)
- **What it does:** The command to execute. Receives hook payload via stdin.
- **Example:** `"/Users/genome/.claude/hooks/validate.sh"`

#### `hooks[EventType][].script`
- **Type:** string (inline script code)
- **Default:** none (required if `type` is `"script"`)
- **What it does:** Inline script content (bash, JavaScript, Python, etc.), receives payload via stdin
- **Example:**
  ```json
  {
    "type": "script",
    "script": "#!/bin/bash\njq '.tool.name' | grep -q Bash && exit 0 || exit 1"
  }
  ```

#### `hooks[EventType][].timeout`
- **Type:** number (seconds)
- **Default:** `30`
- **What it does:** Maximum time the hook can run before being killed
- **Example:** `{ "timeout": 60 }`
- **Notes:** Long-running hooks (archive, emit) should have higher timeouts; validation hooks should be &lt;10s.

#### `hooks[EventType][].statusMessage`
- **Type:** string
- **Default:** Tool command name or `"Running hook"`
- **What it does:** Message shown in Claude Code's status line while the hook runs
- **Example:** `{ "statusMessage": "Linting changes..." }`

#### `hooks[EventType][].matcher`
- **Type:** string (tool/event pattern)
- **Default:** none (optional; if absent, hook runs for all tools/events)
- **What it does:** Filter which tools/events trigger this hook
- **Pattern syntax:**
  - `"Bash(git push*)"` — Bash tool with git push command
  - `"Write|Edit"` — Write OR Edit tool
  - `"mcp__github*"` — Any tool from GitHub MCP
  - `"*"` — match all
  - `"startup|resume"` — for SessionStart, match startup or resume events
- **Example:** `{ "matcher": "Bash(npm test*)" }`

#### `hooks[EventType][].hooks`
- **Type:** array of hook objects
- **Default:** `[]`
- **What it does:** Nested array of hooks to run in sequence. All hooks in the array execute unless one fails/blocks.
- **Example:**
  ```json
  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Write",
          "hooks": [
            { "type": "command", "command": "/path/to/lint.sh" },
            { "type": "command", "command": "/path/to/test.sh" }
          ]
        }
      ]
    }
  }
  ```

### Hook Exit Codes

- **`0`** — Success; continue normally
- **`1`** — Error; block the operation and show error to user
- **`2`** — Block/deny; silently skip the operation (used by PreToolUse to deny without verbose error)
- **Any other code** — Treated as error

### Hook Output Styles

Hooks can output to stdout/stderr. Common patterns:

```bash
# JSON decision override (PreToolUse / PermissionRequest)
echo '{ "decision": "allow" }'

# Error message and block
echo "Hook failed: unsafe pattern detected" >&2
exit 1

# Simple status/log and continue
echo "Validated push to $(jq -r '.tool.arguments.command' < /dev/stdin)"
exit 0

# Inject content into the model's next turn (SessionStart hook)
cat ~/.notes/project-X-context.md
```

---

## MCP (Model Context Protocol) Configuration

MCP servers extend Claude Code with custom tools. Configuration can live in two places:

### In `.claude/settings.json`

**`mcpServers`** (legacy/fallback location)
- **Type:** object mapping server names to configurations
- **Default:** `{}`
- **What it does:** Define MCP servers inline in settings.json (deprecated; use `mcp.json` instead)
- **Structure:**
  ```json
  {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["@modelcontextprotocol/server-github"]
      }
    }
  }
  ```
- **Notes:** This is being phased out in favor of `.claude/mcp.json`.

### In `.claude/mcp.json` (canonical location)

MCP server configuration now lives in a separate `mcp.json` file at the project root or user home. This file defines how Claude Code discovers and connects to MCP servers.

**`mcpServers`** (in `mcp.json`)
- **Type:** object mapping server names to configurations
- **Default:** `{}`
- **What it does:** Define all MCP servers available to Claude Code in this project/session
- **Server entry structure:**
  ```json
  {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["@modelcontextprotocol/server-github"]
      },
      "filesystem": {
        "command": "python3",
        "args": ["/path/to/mcp_server.py"]
      },
      "remote-codesearch": {
        "command": "ssh",
        "args": ["-o", "ClearAllForwardings=yes", "myhost", "/path/to/mcp-server.sh"]
      }
    }
  }
  ```
- **Fields:**
  - `command` — executable to run (can be `ssh`, `npx`, `python3`, custom script, etc.)
  - `args` — array of arguments passed to the command
  - `env` (optional) — object of environment variables for the server process
  - `disabled` (optional) — set to `true` to disable this server without removing it

**Example `.claude/mcp.json`:**
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}"
      }
    },
    "jira": {
      "command": "node",
      "args": ["/opt/mcp/jira-server.js"],
      "disabled": false
    },
    "local-search": {
      "command": "python3",
      "args": ["/home/genome/services/codesearch/mcp_server.py"]
    }
  }
}
```

### Marketplace Sources

MCP servers can also be discovered from package registries via `extraKnownMarketplaces` in settings.json.

### `extraKnownMarketplaces`
- **Type:** object mapping marketplace names to source configurations
- **Default:** `{}`
- **What it does:** Register additional MCP package registries beyond the official Anthropic marketplace
- **Source types:**
  - `github` — GitHub repository (owner/repo format)
  - `git` — Any git URL (HTTPS or SSH)
  - `directory` — Local filesystem directory (for development)
  - `hostPattern` — Regex pattern matching hostnames (advanced)
- **Example:**
  ```json
  {
    "extraKnownMarketplaces": {
      "context-mode": {
        "source": {
          "source": "github",
          "repo": "mksglu/context-mode"
        }
      },
      "internal-tools": {
        "source": {
          "source": "directory",
          "path": "/opt/mcp-servers"
        }
      }
    }
  }
  ```
- **Notes:** This is separate from `mcpServers` — it registers WHERE to find servers, not which servers to use. Actual server activation is determined by `mcpServers` config and `enabledPlugins`.

---

## Plugins & Extensions

### `enabledPlugins`
- **Type:** object mapping plugin identifiers to boolean
- **Default:** `{}`
- **What it does:** Toggle which installed plugins are active. Plugin identifiers are in the format `plugin-name@namespace`.
- **Example:**
  ```json
  {
    "enabledPlugins": {
      "context-mode@context-mode": true,
      "some-plugin@name": false
    }
  }
  ```
- **Notes:** Plugins are discovered from marketplaces and the Anthropic plugin registry. Disabling a plugin here prevents it from loading without uninstalling it.

### `extraKnownMarketplaces`
- See MCP section above; the same key registers plugin sources as well as MCP sources.

---

## Auto-update & Telemetry

### `autoUpdatesChannel`
- **Type:** string (enum)
- **Default:** `"stable"`
- **What it does:** Sets how often Claude Code auto-updates
- **Valid values:**
  - `"stable"` — stable releases only (recommended for production)
  - `"beta"` — includes beta/pre-release versions
  - `"nightly"` — latest development builds (unstable)
  - `"disabled"` (or `"off"`) — disable auto-updates
- **Example:** `{ "autoUpdatesChannel": "stable" }`
- **Notes:** Updates are applied after Claude Code restarts; you will not lose any unsaved work.

### `agentPushNotifEnabled`
- **Type:** boolean
- **Default:** `true`
- **What it does:** Enable/disable push notifications from Claude Code and running agents
- **Example:** `{ "agentPushNotifEnabled": false }`
- **Notes:** Disabling this silences alerts, subagent status updates, and permission requests sent via system notifications.

### `telemetryEnabled`
- **Type:** boolean
- **Default:** `true`
- **What it does:** Enable/disable anonymous usage telemetry (crashes, feature usage, latency metrics)
- **Example:** `{ "telemetryEnabled": false }`
- **Notes:** Environment variable `NO_TELEMETRY=1` (or `DISABLE_TELEMETRY=1`) also disables this.

---

## UI & Appearance

### `theme`
- **Type:** string (enum)
- **Default:** `"auto"` (matches system setting)
- **What it does:** Sets Claude Code's color theme
- **Valid values:**
  - `"auto"` — follow system setting (light/dark)
  - `"light"` — force light theme
  - `"dark"` — force dark theme
  - `"highContrast"` — high-contrast mode for accessibility
- **Example:** `{ "theme": "dark" }`

### `statusLineStyle` (and `statusLine`)
- **Type:** string (enum) or object
- **Default:** `"full"`
- **What it does:** Controls how much information Claude Code displays in its status line. Some builds expose a richer `statusLine` object that accepts a custom format string.
- **Valid values for `statusLineStyle`:**
  - `"full"` — show model, token usage, current task
  - `"compact"` — show only task name
  - `"minimal"` — hide status line entirely
- **Example:** `{ "statusLineStyle": "compact" }`
- **Custom format example (statusLine):**
  ```json
  { "statusLine": { "format": "[{{ model }}] {{ workingDir }}" } }
  ```

### `includeCoAuthoredBy`
- **Type:** boolean
- **Default:** `false`
- **What it does:** Add a `Co-Authored-By: Claude <...>` trailer to git commits (most projects ignore this)
- **Example:** `{ "includeCoAuthoredBy": true }`
- **Notes:** Many projects explicitly forbid this in their `CLAUDE.md` or git hooks. Check before enabling.

---

## Context & Cleanup

### `cleanupPeriodDays`
- **Type:** number (days)
- **Default:** `30`
- **What it does:** How long to keep Claude Code's session history, cached files, and temporary artifacts before auto-cleanup
- **Example:** `{ "cleanupPeriodDays": 365 }`
- **Notes:** Artifacts older than this period are deleted during maintenance. Set higher for long-running projects, lower for privacy-sensitive work.

### `additionalDirectories` (top-level, not permissions)
- **Type:** array of strings (absolute paths)
- **Default:** `[]`
- **What it does:** Some Claude Code versions expose a top-level `additionalDirectories` separate from `permissions.additionalDirectories`. The top-level variant grants the model read/index access to paths outside the workspace; the permissions variant grants WRITE access. Most users only need the permissions one.
- **Example:**
  ```json
  { "additionalDirectories": ["/Users/genome/notes", "/opt/shared-context"] }
  ```

---

## API & Authentication

### `apiKey` (not in settings.json; use env var or keychain)
- **Where to set:** `ANTHROPIC_API_KEY` environment variable or Claude Code's built-in key manager (File &gt; Settings &gt; API Key)
- **Notes:** Never hardcode API keys in settings.json files that are checked into version control. Use environment variables or the keychain/credential manager.

### Cloud Provider Configuration (advanced)

If you use Claude Code with Bedrock, Vertex AI, or other cloud providers:

**`bedrock`** (Bedrock configuration, if using AWS Bedrock)
- **Type:** object
- **Fields:**
  - `region` — AWS region (e.g., `"us-east-1"`)
  - `modelId` — Bedrock model identifier
- **Example:**
  ```json
  {
    "bedrock": {
      "region": "us-west-2",
      "modelId": "anthropic.claude-opus-4-1"
    }
  }
  ```
- **Notes:** Requires `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables; also enabled via `CLAUDE_CODE_USE_BEDROCK=1`.

**`vertexAi`** (Vertex AI configuration, if using Google Cloud)
- **Type:** object
- **Fields:**
  - `projectId` — Google Cloud project ID
  - `region` — GCP region
  - `modelId` — Vertex AI model identifier
- **Example:**
  ```json
  {
    "vertexAi": {
      "projectId": "my-gcp-project",
      "region": "us-central1",
      "modelId": "claude-opus-4-1"
    }
  }
  ```
- **Notes:** Requires `GOOGLE_APPLICATION_CREDENTIALS` environment variable; also enabled via `CLAUDE_CODE_USE_VERTEX=1`.

### Proxy / Network

Set these as environment variables (no settings.json key):

- `HTTP_PROXY`, `HTTPS_PROXY` — outbound proxy
- `NO_PROXY` — host patterns to bypass
- `ANTHROPIC_BASE_URL` — override API base URL (self-hosted relays, regional endpoints)

---

## Environment Variables

These environment variables affect Claude Code's behavior. They can be set in your shell, `.env` file, or in settings.json via the `env` object (see below).

### Setting Environment Variables in settings.json

**`env`** (object of environment variables)
- **Type:** object mapping env var names to values
- **Default:** `{}`
- **What it does:** Set environment variables that Claude Code passes to all tool executions
- **Example:**
  ```json
  {
    "env": {
      "ANTHROPIC_LOG": "debug",
      "NODE_ENV": "development",
      "CUSTOM_TOOL_PATH": "/opt/my-tools"
    }
  }
  ```
- **Notes:** Values in settings.json override shell environment. Be careful not to commit secrets here; use `.local.json` for private env vars.

### Common Claude Code Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key for Claude (use keychain, not settings.json) | — |
| `ANTHROPIC_BASE_URL` | Override the Claude API endpoint | api.anthropic.com |
| `ANTHROPIC_LOG` | Logging level for API calls | `"error"` |
| `NO_TELEMETRY` / `DISABLE_TELEMETRY` | Disable telemetry (set to `1`) | unset |
| `CLAUDE_CODE_USE_BEDROCK` | Route requests through AWS Bedrock | unset |
| `CLAUDE_CODE_USE_VERTEX` | Route requests through Google Vertex AI | unset |
| `CLAUDE_CODE_CUSTOM_MODEL` | Override model selection | unset |
| `CLAUDE_CODE_DEBUG` | Enable debug logging | unset |
| `HTTP_PROXY` / `HTTPS_PROXY` | Proxy settings for network requests | unset |
| `NO_PROXY` | Hostnames to bypass proxy | unset |
| `MAX_THINKING_TOKENS` | Cap on reasoning token budget | model default |

---

## Keybindings

Keybindings are NOT configured in settings.json; instead, they live in `~/.claude/keybindings.json`. This file is usually managed by Claude Code's settings UI, but you can edit it manually.

**Common keybinding patterns:**

```json
{
  "keybindings": {
    "submit": "ctrl+enter",
    "stop": "escape",
    "viewHistory": "cmd+/",
    "openSettings": "cmd+,",
    "newConversation": "cmd+n"
  }
}
```

See the skill `/keybindings-help` to customize keyboard shortcuts programmatically.

---

## Subagent & Orchestration Configuration

Claude Code does not expose subagent model/config through settings.json directly. Instead, subagent behavior is controlled through:

1. **Prompts** — the orchestrator passes a task description to subagents
2. **Environment variables** — subagents inherit `env` settings
3. **Permissions** — subagents inherit permission rules
4. **`advisorModel`** — used for orchestrator/advisor roles
5. **Skills / agents directories** — agent definitions in `~/.claude/agents/*.md` and `<repo>/.claude/agents/*.md` (their YAML frontmatter sets `model:` and `tools:` per agent)

For fine-grained subagent control, see the Agent SDK documentation.

---

## Policy & Enterprise Settings

Enterprise deployments may have additional settings in `<repo>/.claude/policy-limits.json` that enforce restrictions:

```json
{
  "restrictions": {
    "allow_remote_control": { "allowed": false },
    "allow_routines": { "allowed": false },
    "allow_quick_web_setup": { "allowed": false }
  },
  "compliance_taints": []
}
```

These are typically set by administrators and cannot be overridden by user settings.

---

## Full Kitchen-Sink Example

A comprehensive `settings.json` that uses nearly every key:

```json
{
  "model": "claude-opus-4-1",
  "advisorModel": "claude-opus-4-1",
  "effortLevel": "high",

  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git log*)",
      "Bash(npm run *)",
      "Bash(make *)",
      "Read",
      "WebFetch",
      "mcp__github__list_pull_requests",
      "mcp__github__create_pr"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(git push --force*)",
      "Bash(docker compose down -v*)"
    ],
    "ask": [
      "Bash(git push*)",
      "Edit",
      "mcp__jira__update_issue"
    ],
    "defaultMode": "plan",
    "additionalDirectories": [
      "/Users/genome/.local/bin",
      "/opt/project-tools"
    ]
  },

  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/genome/.claude/hooks/init-session.sh",
            "timeout": 15,
            "statusMessage": "Initializing environment..."
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash(git push*)",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/genome/.claude/hooks/validate-push.sh",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/genome/.claude/hooks/check-file-size.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "npm run lint -- --fix",
            "timeout": 30,
            "statusMessage": "Linting..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/genome/.claude/hooks/emit-session-metrics.sh",
            "timeout": 10,
            "statusMessage": "Saving session state..."
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/genome/.claude/hooks/archive-context.sh",
            "timeout": 30
          }
        ]
      }
    ]
  },

  "env": {
    "NODE_ENV": "development",
    "ANTHROPIC_LOG": "error"
  },

  "enabledPlugins": {
    "context-mode@context-mode": true,
    "losmon-memory@losmon": true
  },

  "extraKnownMarketplaces": {
    "context-mode": {
      "source": {
        "source": "github",
        "repo": "mksglu/context-mode"
      }
    },
    "internal-tools": {
      "source": {
        "source": "directory",
        "path": "/opt/mcp-servers"
      }
    }
  },

  "theme": "auto",
  "statusLineStyle": "full",
  "autoUpdatesChannel": "stable",
  "agentPushNotifEnabled": true,
  "telemetryEnabled": true,
  "cleanupPeriodDays": 365,
  "includeCoAuthoredBy": false,
  "additionalDirectories": [
    "/Users/genome/notes"
  ]
}
```

---

## Common Gotchas

### 1. Permission precedence is deny &gt; ask &gt; allow &gt; defaultMode
If you add a rule to both `deny` and `allow`, the deny rule wins. Use mutually exclusive patterns:

```json
{
  "allow": ["Bash(npm run *)"],
  "deny": ["Bash(npm run remove*)"]
}
```
This BLOCKS `npm run remove`, even though `npm run *` is allowed.

### 2. Hooks are synchronous and block the turn
If a hook takes 30s to run, Claude Code waits. Use `timeout` to prevent hangs. Make hooks as fast as possible.

### 3. MCP tools in allow/deny need exact format
- ✅ `"mcp__github__create_pr"` (specific tool)
- ✅ `"mcp__github"` (whole server)
- ❌ `"mcp__github(create_pr)"` — parentheses not allowed for MCP
- ❌ `"mcp.github.create_pr"` — dots not allowed

### 4. Relative paths in hooks don't expand
Hooks must use absolute paths. These WON'T work:
```json
{ "command": "./scripts/hook.sh" }     // Bad
{ "command": "~/.claude/hooks/hook.sh" } // Bad (~ doesn't expand)
```
Use full paths:
```json
{ "command": "/Users/genome/.claude/hooks/hook.sh" } // Good
```

### 5. `settings.json` vs `settings.local.json` merge behavior
Arrays DON'T replace; they MERGE. If you want to disable a permission rule set in `settings.json`, you can't just omit it in `.local.json`. Instead, use explicit deny rules.

### 6. Hooks receive JSON via stdin, not as environment variables
Hooks can't access tool info via `$1`, `$2`, etc. Parse stdin:
```bash
#!/bin/bash
TOOL=$(jq -r '.tool.name' < /dev/stdin)
echo "Tool was: $TOOL"
```

### 7. Bash patterns are case-sensitive and require exact syntax
- `"Bash(git status)"` matches exactly `git status`, not `git status --porcelain`
- `"Bash(git status*)"` matches `git status` with anything after
- `"Bash(git:*)"` matches any git subcommand (`git clone`, `git push`, etc.)

### 8. API keys in settings.json are a security risk
Never commit `ANTHROPIC_API_KEY` to version control. Use:
- Environment variables (shell export)
- `.local.json` with `env` object (gitignored)
- System keychain (Claude Code can manage this)

### 9. `theme: "auto"` respects system setting at startup
If you switch OS theme while Claude Code is running, the setting doesn't update until the next session start.

### 10. Hooks exit codes are easy to misinterpret
- Exit `0` = success/allow
- Exit `1` = error (show error to user)
- Exit `2` = deny/block (silent)

For PreToolUse, exit 2 is "don't show an error, just skip"; exit 1 is "show the error message".

### 11. `enabledPlugins` keys are `plugin@namespace`, not `namespace/plugin`
- ✅ `"context-mode@context-mode": true`
- ❌ `"context-mode/context-mode": true`
- ❌ `"@context-mode/plugin": true`

### 12. CLAUDE.md filename is not configurable
There is no settings.json key to rename or replace the auto-loaded memory file. Use `@path/to/file.md` imports inside `CLAUDE.md` to compose memory from multiple files, or use a `SessionStart` hook that prints custom markdown into the model's first turn.

---

## Bibliography

Sources used to compile this catalog:

- [Claude Code Official Settings Docs](https://code.claude.com/docs/en/settings)
- [Claude Code Official Hooks Docs](https://code.claude.com/docs/en/hooks)
- [Claude Code Official Permissions Docs](https://code.claude.com/docs/en/permissions)
- [Claude Code Official MCP Docs](https://code.claude.com/docs/en/mcp)
- [Complete settings.json Reference (GitHub Gist, April 2026)](https://gist.github.com/mculp/c082bd1e5a439410158974de90c89db7)
- [Claude.fast Blog: Settings Reference](https://claudefa.st/blog/guide/settings-reference)
- [Claude.fast Blog: Hooks Guide](https://claudefa.st/blog/tools/hooks/hooks-guide)
- [Claude.fast Blog: Permissions Management](https://claudefa.st/blog/guide/development/permission-management)
- [Morph Blog: Claude Code settings.json](https://www.morphllm.com/claude-code-settings-json)
- [EEsel AI Blog: Claude Code Settings (2026)](https://www.eesel.ai/blog/settings-json-claude-code)
- [yaw.sh: Claude Code Settings in Production](https://yaw.sh/claude-code-in-production/claude-code-settings/)
- [Vincent's Blog: Permissions & Settings](https://blog.vincentqiao.com/en/posts/claude-code-settings-permissions/)
- [GitHub: claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice)
- Live configuration files: `~/.claude/settings.json`, `~/.claude/mcp.json`, `<repo>/.claude/policy-limits.json`
