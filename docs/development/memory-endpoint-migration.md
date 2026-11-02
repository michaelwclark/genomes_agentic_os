# Managed Brain endpoint migration

New managed HTTP consumers use `http://127.0.0.1:3166/mcp`. The stop emitter
uses `GENOMES_BRAIN_MCP_URL`, then `LOSMON_MEMORY_MCP_URL`, then this default.
Explicit custom URLs and native SSH-stdio configurations remain authoritative.
Normal configuration installation remains additive: it preserves existing values,
including an old managed URL. It is not an endpoint migration.

The optional `agentic-os config memory-endpoint` command changes only an exact
legacy `http://127.0.0.1:3155/mcp` declaration. It never contacts either service,
writes a memory record, starts a service, enables routing, or establishes a tunnel.
Run it locally as the owner of the installation. Python 3.11 or newer and POSIX
file locking are required for this operation; unrelated package commands retain
the package's Python compatibility.

## Qualify the service first

Separately verify the current Brain identity, health, host, installed source,
and transport through the authorized host procedure. This command accepts that
procedure's typed receipt; it cannot authenticate the author or prove that the
reported check happened. A fixture receipt is never live acceptance evidence.
Do not fabricate a receipt to work around an unreachable or unqualified service.
The receipt contains these fields, no credentials:

```json
{
  "schema": "memory-endpoint-service-verification/v1",
  "status": "verified",
  "service": "genomes_brain",
  "endpoint": "http://127.0.0.1:3166/mcp",
  "host": "your-logical-host",
  "machine": "the-exact-local-platform-node-name",
  "health_status": "healthy",
  "verified_at": "an-aware-ISO-8601-timestamp"
}
```

Planning and forward application require verification within fifteen minutes
(with at most one minute of clock skew). Keep the receipt and plan in an owned
private directory. The command refuses symlinks, hardlinks, foreign ownership,
unsafe modes, extended attributes and flags it cannot preserve. Use the physical
absolute root path; even ancestor symlinks are refused. Do not relax permissions
or erase metadata merely to make a refused migration proceed.

## Plan and review exact effects

```sh
agentic-os config memory-endpoint plan --root /physical/path/to/agentic_os \
  --host your-logical-host --service-receipt /private/path/service.json \
  --path harness/config.toml \
  --path harness/shared_factory/config.toml \
  --path harness/hooks/harness-emit-trace.sh > /private/path/plan.json
agentic-os config memory-endpoint apply --root /physical/path/to/agentic_os \
  --plan /private/path/plan.json
```

Only the three explicitly selected managed paths above are supported. Omit a
path that is not installed; the tool does not search for or create consumers.
A simple canonical TOML table and quoted URL declaration are required. Duplicate
or ambiguous TOML and mixed HTTP/stdio entries are refused. A stdio entry, custom
URL, current endpoint or absent managed server is preserved. The hook's exact
managed fallback expression is eligible; a custom fallback is preserved.

The plan contains digests, file identities and a nonsecret URL patch with its byte
offset, never an original credential configuration. Review its dispositions,
root/host/runtime bindings and intended paths. Preview creates no lock, journal
or target changes. Plans are bound to the exact migration module and package
version; rebuild a plan after changing the tool or verification receipt.

## Apply, verify and recover

```sh
agentic-os config memory-endpoint apply --root /physical/path/to/agentic_os \
  --plan /private/path/plan.json --apply
agentic-os config memory-endpoint rollback --root /physical/path/to/agentic_os \
  --plan /private/path/plan.json
agentic-os config memory-endpoint rollback --root /physical/path/to/agentic_os \
  --plan /private/path/plan.json --apply
```

The explicit `--apply` flag is required for effects. The command checks the
complete selected set, takes a nonblocking cooperative lock, writes a private
intent journal, checks the exact bytes and inode again before each replacement,
atomically replaces that single file, fsyncs it and its directory, and reads it
back. Unrelated bytes, ownership and mode remain unchanged. Cooperating writers
must honor the same lock. Compare-before-replace is not a kernel-wide compare
and swap; these three files are not one filesystem transaction. Stop other
configuration writers during the maintenance window.

The installation retains `.memory-endpoint-migration.lock` and private
`.memory-endpoint-migrations/<plan-id>.json`. These contain scoped patch identity,
effects and history, not original configuration bodies. A temporary replacement
necessarily contains the target bytes in its target directory; it has exclusive
creation and the original file's permissions, and is removed normally. A recorded
pending intent permits exact owned temporary cleanup or post-replacement recovery
on a later invocation. Never copy credential configurations or temporary files
into a repository, task artifact or ordinary backup directory. Whole-configuration
backup, if needed separately, requires private encrypted custody outside those
surfaces.

Failures preserve history and can leave an already-applied subset. A failed
`--apply` result therefore reports `target_changes: null`; inspect the journal
before deciding what happened. Retry with the same unchanged plan only after
resolving the actual cause. Repeated successful apply or rollback is idempotent.
Rollback reverses only this journal's exact current effects and refuses a later
edit, inode replacement or owner/mode drift. Rollback permits a stale service
verification so that an outage does not block local restoration; all original
host/runtime and file guards still apply. Retain the same qualified tool and plan
until the recovery window ends. Do not delete a journal to bypass a refusal.

After application, separately verify the harness consumer and the live Brain
service under the approved runtime procedure. Local source tests, a wheel install
and a successful file patch are distinct from installation, memory writes,
service availability and customer readiness. In particular this migration does
not enable LOSMON background processing or create another memory writer.
