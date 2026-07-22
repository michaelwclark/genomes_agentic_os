# Host and environment access

Readiness, Detective, QA, Release, Deploy, and Closeout must resolve this plane
before touching a remote environment.

1. Use the project/domain environment identifier, not a remembered hostname.
2. Resolve hosts through the installed host registry and routed transport.
3. Verify VPN, authentication, tenant, account, region, and environment before
   reading sensitive/runtime-only state or mutating anything.
4. Prefer the narrowest read-only check. Keep secrets and raw customer data out
   of receipts and chat.
5. If access is unavailable, record the exact prerequisite and resume point.
6. Production, deployment, destructive, billing, and customer-visible actions
   retain their explicit approval gates.
