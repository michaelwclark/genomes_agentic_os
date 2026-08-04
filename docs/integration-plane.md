# Integration Plane

The Integration Plane is the boundary between Agentic OS and external systems.
It gives application code a stable, policy-selected port for a provider instead
of scattering provider SDK calls, credentials, retries, and error handling
through workflows.

## Start with the routing policy

Every provider route answers four questions: which capability is being used,
which provider owns it, which transport is allowed, and which constraints must
hold before a side effect can occur. The authoritative policy is generated from
the platform source; this handbook deliberately links to it instead of copying
it, because a stale routing policy is unsafe.

- [Generated provider policy](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/TOOLS.md)
- [Machine-readable policy](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/TOOLS.routing.json)
- [How routing works](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/ROUTING.md)

## What the platform provides

| Capability | What the port owns | Reference |
| --- | --- | --- |
| Logging | configured sinks, correlation IDs, structured output, and safe failure behaviour | [Logging](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/LOGGING.md) |
| Durable side effects | a persisted outbox, dedupe keys, leases, retries, and operator actions | [Outbox](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/OUTBOX.md) |
| GitHub | provider capabilities, pagination, retry/deadline behaviour, and a testable adapter boundary | [GitHub port](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/GITHUB.md) |
| Linear | issue identity, state transitions, pagination, error classification, and mutation safety | [Linear port](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/LINEAR.md) |
| Architecture | the enforced layer graph, deliberate constraints, and the tests that prove the boundary remains intact | [Platform architecture](https://github.com/michaelwclark/genomes_agentic_platform/blob/main/docs/ARCHITECTURE.md) |

## How to use it safely

1. Choose a declared capability rather than calling a provider client directly.
2. Let the selected adapter apply deadlines, retry rules, logging, and
   provider-specific validation.
3. Put a provider mutation through the outbox when it must survive process
   restarts or avoid duplicate delivery.
4. Keep provider credentials and local machine paths out of artifacts and
   provider-facing text.
5. Test code against the port contract first; use a live provider only for a
   separately governed acceptance check.

The platform source is the detailed reference because it is versioned and
tested with the implementation. This page is the discovery entry point for
Agentic OS operators and agents.
