# 44 · Integration Adapter Routing

The adapter policy is deliberately small: it selects one reviewed provider
boundary before a workflow makes a call. It does not hold credentials or make
network calls. The policy is exposed by
`genomes_agentic_os.adapter_routing` and each adapter owns its own transport.

| System / operation | Primary adapter | Fallback | Non-negotiable boundary |
| --- | --- | --- | --- |
| Atlassian read | `acli` | Jira REST bridge, Jira MCP | Preserve the resolved Jira site and issue/project scope. |
| Atlassian write | `acli` | Jira REST bridge, Jira MCP | Require ticket-scope approval and provider readback. |
| JSM/service-desk comment | Jira REST bridge | None | Default the comment to internal. Only REST can set that flag. |
| Notion interactive read | Notion MCP | Notion REST bridge | Keep the read inside the intended workspace/page scope. |
| Notion write | Notion REST bridge | None | Verify Genome's Notion and the approved parent identity before writing. |
| Slack channel history | `SlackClient` | None | The client only normalizes trimmed messages; source-watch owns cursors and persistence. |
| Valkey delivery | BullMQ `DeliveryPort` | None | Valkey is reconstructable delivery signaling only; PostgreSQL is the canonical task/effect ledger. |

## Known provider limitations

- Do not route JSM or service-desk comments through `acli` or MCP when they
  must be internal. Neither route can set the internal-comment flag.
- Notion MCP's `update_content` cannot reliably match image blocks. The REST
  bridge is therefore the only write path, and it retains workspace/parent
  identity checks.
- Slack workflow behavior is intentionally not part of `SlackClient`. Its only
  responsibility is bounded `conversations.history` retrieval and safe event
  normalization; the watcher decides when to poll and where to persist events.
- Workflows, producers, and workers do not connect to Valkey. They use the
  Execution Fabric control-plane API; the `BullMqDelivery` implementation is
  behind that service boundary and can be reconstructed from PostgreSQL rows.
