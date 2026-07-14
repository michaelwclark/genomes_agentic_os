# Local Resource Graph

The Agentic OS resource graph is a bounded, read-only GraphQL projection over
materialized local state. It is the client query contract for Command Center;
it is not a provider gateway, source of truth, event bus, or generic CRUD API.

## Ownership and routing

- Provider adapters own authentication, cursors, polling, webhooks, retries,
  rate limits, and writes.
- Agentic OS files and the local state database remain the authoritative local
  projections.
- `genomes_agentic_os.resource_graph.ResourceGraphService` owns schema
  execution and provider-neutral resource identity.
- Command Center or another trusted local process supplies one installed OS
  root when constructing the service. The root must contain `.agentic_root`;
  GraphQL clients cannot supply paths.

## Resource identity

Every resource includes:

- a stable `id` and `kind`;
- `scope` with domain and project;
- `provenance` with source, native identity, and an OS-root-relative path;
- `freshness` describing when the local projection was observed and updated;
- external references, links, and explicit privacy flags.

The first projections are specs from `work.yml` plus `SPEC.md` and normalized
events from an existing read-only `state.db`. The spec compatibility reader
supports both legacy top-level work-item metadata and the canonical nested
`spec` plus `scope` shape. Spec status values use the canonical vocabulary,
including `in_progress`, and the projection exposes `disposition` and
`blockedFrom` separately so terminal filing is not confused with delivery state.

## Safety contract

- The schema exposes queries only. There is no `Mutation` type.
- Resolver reads remain underneath the resolved allowlisted OS root. Symlinked
  sources that escape it are rejected or skipped.
- GraphQL has no path argument and the CLI accepts query text, not query files.
- Existing SQLite files are opened with `mode=ro`; querying never creates a
  database.
- Provider network calls are forbidden in resolvers.
- Query text, source documents, scans, and result counts have fixed limits.
- Errors are JSON-safe and carry stable extension codes where the service owns
  the failure.

## Query surface

```graphql
query ProjectSpecs($domain: String!, $project: String!) {
  specs(domain: $domain, project: $project, limit: 25) {
    id
    title
    status
    type
    resource {
      provenance { sourceId nativeId relativePath }
      freshness { state sourceUpdatedAt }
      externalRefs { provider nativeId url }
    }
  }
}
```

Standard GraphQL introspection is available so trusted local clients can build
typed views. Writes must use named Agentic OS commands, skills, workflows, or
future action handlers that preserve approval, idempotency, readback, and run
receipts. Generic GraphQL mutations are intentionally out of scope.

## Validation

Run `pytest -q tests/test_resource_graph.py`. The suite covers scope filters,
provenance and freshness, legacy and canonical spec shapes, introspection,
root-boundary attacks, mutation rejection, bounded results, and offline
resolver execution.
