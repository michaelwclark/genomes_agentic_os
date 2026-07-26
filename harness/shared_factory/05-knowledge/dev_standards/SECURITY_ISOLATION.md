# Security And Isolation

Focus: explicit authn/authz, object-level ownership, tenant scoping, bounded input, no leaked secrets or PII.

## Write
- Every new endpoint/action declares authentication and authorization
  explicitly; object-level access checks ownership (no IDOR).
- Tenant scoping on every query in multi-tenant code; validate and bound all
  external input; no secrets in code, config, or logs; no PII in logs or
  error messages.

## Review
- Attempt the bypass: unauthenticated call, other-tenant id, other user's
  object id, oversized/malformed input.
- Identity resolution uses the trusted relationship, never a caller-supplied
  email/name alone.

Blocking: always.
