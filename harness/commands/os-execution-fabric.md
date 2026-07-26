# /execution-fabric

Inspect, design, or validate the optional Execution Fabric OSProgram.

## Contract

1. Read `harness/shared_factory/00-programs/execution_fabric/`.
2. Run `agentic-os runtime config show` and `runtime config status`; report the effective
   `harness/config/execution-fabric.yml` source, fingerprint, drift, and
   `runtime.queue_mode`.
3. Treat `filesystem` as the compatibility default.
4. Require readiness and rollback evidence before proposing activation.
5. Report `execution_fabric.transport.mode` explicitly. In remote mode, require
   an HTTPS URL, distinct scoped token or `_FILE` sources, and server-side
   bearer enforcement before any worker is started.
   For `remote_with_local_fallback`, report the durable latch, consecutive
   failure count, primary readiness, and that failback is manual.
6. Use `agentic-os runtime submit`, `runtime work`, and `runtime status`; do not
   connect workflows directly to PostgreSQL, Valkey, or BullMQ.
7. Keep mutable queue and worker state out of the source-owned program.
8. Use `agentic-os runtime fallback status|probe|activate|failback`; never edit
   the fallback state JSON by hand.

This command does not enable the program or mutate runtime state by itself.
