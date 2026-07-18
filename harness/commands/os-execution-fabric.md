# /execution-fabric

Inspect, design, or validate the optional Execution Fabric OSProgram.

## Contract

1. Read `harness/shared_factory/00-programs/execution_fabric/`.
2. Report the installed `enabled` and `runtime.queue_mode` values.
3. Treat `filesystem` as the compatibility default.
4. Require readiness and rollback evidence before proposing activation.
5. Keep mutable queue and worker state out of the source-owned program.

This command does not enable the program or mutate runtime state by itself.
