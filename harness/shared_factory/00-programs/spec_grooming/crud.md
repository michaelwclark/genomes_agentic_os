# CRUD: Spec Engine

## Create

Use `/add-spec`, `spec-engine`, or `agentic-os spec add`. The first content write
must preserve original intent. Adapter creation must be idempotent and conclude
with a readback receipt.

## Read

Use `agentic-os spec show` for one normalized record or `spec list` for a scoped
inventory. Load packet detail only when grooming or implementation requires it.

## Update

Use `agentic-os spec transition` for lifecycle changes and `spec sync` for
adapter reconciliation. When changing the engine contract, update the skill,
command, templates, program docs, registries, generated install behavior, and
tests together.

## Delete Or Retire

Retirement requires removing the command and skill from registries, preserving
historical packets, and recording a replacement route. Destructive deletion of
installed or external surfaces requires explicit approval.
