# Context: Spec Engine

`spec_engine` is the shared Agentic OS capability for turning rough intent into
a durable, implementation-grade Spec and moving it through one lifecycle:
`idea`, `grooming`, `blocked`, `ready`, `in_progress`, and `built`.

The only canonical Spec types are `bug`, `feature`, and `config`. Terms such as
idea, ticket, Jira, Linear item, backlog item, and feature name the intake or
projection surface; they do not create separate lifecycle objects.

The engine owns raw intent capture, capability discovery, route selection,
packet completeness, lifecycle transitions, adapter selection, assumption
tracking, and projection receipts. Domain and project policy decides whether
filesystem, Linear, or Jira owns content and lifecycle state.

## Policy Precedence

1. shipped Spec Engine defaults;
2. installed-root policy;
3. domain policy;
4. project policy;
5. explicit invocation override.

Filesystem always retains local identity, provenance, and receipts. A narrower
policy may make Linear or Jira authoritative for lifecycle state. Notion is an
optional documentation projection and never a required queue between the Spec
Engine and a tracker.
