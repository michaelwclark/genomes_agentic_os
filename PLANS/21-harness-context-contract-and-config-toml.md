# 21 - Harness Context Contract And Codex Config

## Intent

Normalize the installed OS prompt surface so Codex, Claude, and future harnesses
share the same routing, context, rules, and tool inventory without duplicated
markdown files.

The desired split is:

- `config.toml` handles Codex-specific startup, root discovery, MCP/tool
  registration, profiles, and execution defaults.
- Markdown context files carry the portable OS behavior that all harnesses and
  humans can inspect.

## Source Spec

- `spec/harness-context-contract.md`
- Related config plan: `config.toml.plan.md`
- Related registry spec: `spec/capability-registry.md`

## Build Order

1. Add source templates for the new file set.
   - `templates/agent-config/AGENTS.md`
   - `templates/agent-config/CLAUDE.md`
   - `templates/agent-config/RULES.md`
   - `templates/agent-config/TOOLS.md`
   - Update existing `ROUTER.md` and `CONTEXT.md` templates to reference the
     route-read-cd-repeat loop.

2. Retire generated `AGENT.md` by default.
   - Remove root/domain/customer generation of `AGENT.md`.
   - Keep an explicit compatibility flag for future harnesses that prove they
     need it.
   - Update README, CLI spec, install docs, and tests.

3. Make `CLAUDE.md` an adapter.
   - Render it as `@AGENTS.md`.
   - Add validation that generated Claude files stay short.
   - Document that shared behavior belongs in `AGENTS.md`, not duplicated in
     Claude-specific files.

4. Make `AGENTS.md` the route bootstrap.
   - Require agents to read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and
     `TOOLS.md`.
   - Require the route-read-cd-repeat loop before acting.
   - Require routing gaps and missing tools to be recorded.

5. Add `TOOLS.md` as the visible local tool registry.
   - Generate initial sections for skills, commands, MCP servers, plugins,
     libraries, wrappers, and disabled/missing tools.
   - Populate it from `harness/skills/skill-registry.yml` and the visible
     capability registry where possible.
   - Keep harness-specific install folders such as `.codex/skills/` as
     implementation details.

6. Add `RULES.md` as the local constraint surface.
   - Move approval/safety/coding/operating constraints out of overloaded
     `CONTEXT.md` bodies.
   - Apply strictest-rule-wins precedence across parent and child layers.

7. Update Codex config generation.
   - Keep `.agentic_root` in project root markers.
   - Configure Codex so the OS root is discoverable.
   - Point Codex profile/tool/skill behavior at the visible registry and
     context-file contract.
   - Keep large routing and business context out of `config.toml`.

8. Update validation and doctor checks.
   - Root requires `.agentic_root`, `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`,
     `CONTEXT.md`, `RULES.md`, and `TOOLS.md`.
   - Routeable layers with routers must either define or inherit context,
     rules, and tools.
   - Generated `AGENT.md` is a warning unless compatibility mode is enabled.
   - `TOOLS.md` entries must resolve to installed or declared capabilities.

9. Add tests.
   - Fresh install creates the new base file set.
   - Fresh install does not create `AGENT.md` by default.
   - `CLAUDE.md` contains `@AGENTS.md`.
   - Validation fails when root `RULES.md` or `TOOLS.md` is missing.
   - Domain/project routing fixtures demonstrate route-read-cd-repeat behavior.

## Acceptance Criteria

- A fresh temp install contains `.agentic_root`, `AGENTS.md`, `CLAUDE.md`,
  `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` at the root.
- A fresh temp install does not create `AGENT.md` by default.
- Root `CLAUDE.md` is an include adapter for `AGENTS.md`.
- Root `AGENTS.md` tells agents to read `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
  and `TOOLS.md`, then repeat after routing into a narrower directory.
- Domain/customer/profile scaffolds follow the same context-file contract.
- `config.toml.plan.md` explains that Codex config bootstraps discovery,
  profiles, MCPs, and tool paths, while markdown files carry portable operating
  behavior.
- `agentic-os validate` enforces the new root file contract.
- Existing tests are updated and pass.

## Notes

This is the cleanup that makes the OS less magical. The harness config should
make the agent land in the right place and see the right capabilities. The
markdown files should explain what the layer means, how to route, which rules
apply, and which tools are intended.

Do not solve tool installation entirely in this plan. It is enough for this plan
to make `TOOLS.md` the visible contract and require later installer work to make
Codex/Claude runtime paths match it.
