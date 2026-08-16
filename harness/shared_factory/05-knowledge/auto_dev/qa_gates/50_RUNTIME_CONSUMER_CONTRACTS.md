# Runtime Consumer Contract Gate

Block delivery when a request/payload/serializer/configuration boundary changes
without proof that all rule and tenant consumers still receive the contract they
expect.

Required evidence for each affected contract:

- complete consumer inventory and tenant impact matrix;
- tests for legacy and canonical shapes through the actual evaluator/consumer;
- expected non-empty business result and the negative/missing-field behavior;
- exact effective rule/configuration identity and runtime readback;
- explicit compatibility preservation or a coordinated consumer migration.

Run `harness/bin/agentic-os-runtime-contract-gate` for request, serializer,
payload, rule, configuration, or persistence-adapter changes. A missing test,
inventory, tenant classification, consumer evaluation, or compatibility plan is
blocking.
