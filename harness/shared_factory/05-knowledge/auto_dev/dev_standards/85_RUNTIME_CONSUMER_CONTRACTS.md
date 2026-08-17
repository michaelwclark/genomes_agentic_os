# Runtime Consumer Contract Safety

A serializer, view, request adapter, canonical payload builder, or persistence
adapter is a public compatibility boundary whenever its output is consumed by
rules, templates, jq, configuration, integrations, or tenant-specific logic.
Changing where a value is read from, flattening or nesting a field, replacing a
browser payload with a persisted projection, or silently dropping a field is a
contract change even when the endpoint schema itself appears unchanged.

Auto-Dev must fail closed until it proves all of the following for each changed
contract:

1. **Consumer inventory** — locate every direct and indirect consumer of the
   previous shape: application code, persisted rules, tenant overrides,
   templates, jq, integrations, and operational tooling. Record the search
   scope, the full inventory, and the owner of each consumer.
2. **Impact matrix** — classify every tenant/configuration using the affected
   path as compatible, migrated, unaffected, or blocked. "No known tenants" is
   valid only with the inventory and query/readback that prove it.
3. **Dual-shape contract tests** — exercise the pre-change shape and the new
   canonical shape through the real consumer/evaluator, not merely serializer
   output. Assert the externally meaningful result for each affected edge.
4. **Compatibility or coordinated migration** — preserve the old shape until
   every consumer is migrated, or make the consumer migration atomic with the
   producer change. A producer-only change is prohibited when any persisted or
   tenant-owned consumer remains on the old shape.
5. **Negative and empty-result behavior** — prove that a missing or misplaced
   value cannot turn a valid configured result into a silent empty success.
   Tests must assert the expected documents/results and the diagnostic failure
   path, not only that the handler returned HTTP success.
6. **Runtime evidence** — run the exact relevant tenant/configuration fixture
   and retain the request shape, effective rule/configuration identity, result
   count/content, revision, and environment in the receipt.

Do not accept a unit test of a serializer, a mocked rule call, a response-code
assertion, or a test of only the new shape as proof. The test must cross the
producer/consumer boundary at least once for every affected contract class.

Run `harness/bin/agentic-os-runtime-contract-gate` before self-review,
opposing review, readiness, and merge. It is a fail-closed preflight for
request/payload/rule contract changes; its passing result does not replace the
real consumer tests or the receipt matrix above.

## Production Release Check

- `check_id`: `runtime_consumer_contracts`
- Required inputs: exact-head consumer inventory, tenant impact matrix,
  pre-change and canonical-shape test evidence, and effective runtime
  configuration/rule readback.
- Pass criteria: every listed consumer has passing exact-revision evidence or a
  completed coordinated migration; no affected tenant is unclassified; and no
  formerly valid request can degrade to a silent empty result.
- Receipt fields: `consumer_contract_matrix`, `tenant_impact_matrix`,
  `compatibility_strategy`, `contract_test_runs`, and `runtime_readbacks`.
