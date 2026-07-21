# Domain Setup

Use when creating or improving a domain room inside the OS.

## Workflow

1. Confirm the domain name and operating boundary.
2. Fill `CONTEXT.md` with purpose, systems, work style, and common tasks.
3. Fill `REFERENCES.md` and `05-knowledge/source-map.md` with source systems.
4. Fill `00-control-plane/routing-rules.md` and `approval-rules.md`.
5. Inspect the domain's actual trackers, repositories, local rules, runtimes,
   integrations, environments, deployment surfaces, and support workflows.
6. Populate numbered, plain-English domain addenda under
   `05-knowledge/auto_dev`, `dev_standards`, `qa_gates`, `gitflow_topology`, and
   `environment_access`. Cover every applicable Auto-Dev stage, including
   documentation and Health cleanup. A README alone is not configured policy.
7. For every project, populate matching numbered addenda under `config/` using
   verified repository behavior. Keep domain-wide rules out of project files
   and repository-specific commands out of domain files.
8. Add known active work to the canonical active-work projection.
9. Run `agentic-os develop policy <domain> <project> --plane <plane> --root
   <os-root> --json` for all five planes. Confirm root, domain, and project
   sources and record the fingerprints in the work item.
10. Validate the domain structure and read back every generated/configured
    source path before claiming setup is complete.

## Guardrails

Do not create duplicate top-level domains when an existing domain can own the work.
Do not invent credentials, cloud identifiers, commands, owners, or framework
rules. Mark unknowns explicitly and route them to the source that can verify
them. Never describe placeholder directories or README-only packs as configured.
