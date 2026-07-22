# Testing and Evidence

- Select the smallest complete test triangle by risk: unit behavior first,
  integration at boundaries, and end-to-end only where the cross-system path is
  the behavior being protected.
- Use Arrange–Act–Assert or an equally obvious structure. Assert externally
  meaningful outcomes, not incidental implementation details.
- Cover the repaired failure path, a normal path, tenant/security boundaries,
  and retry/idempotency behavior when relevant.
- A broken local environment is `environment_unavailable`, never “passed.” Use
  CI as the final signal only when policy permits and the environment blocker is
  receipted.
- Keep exact commands, check/job identifiers, fixture identities, and concise
  results in durable local receipts. Do not paste raw logs into external text.
