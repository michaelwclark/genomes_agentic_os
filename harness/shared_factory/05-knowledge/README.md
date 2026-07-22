# Shared policy library

This directory contains the plain-English behavior that every configured
domain and project inherits. It is policy, not source code and not a second
workflow engine.

## Five active policy planes

All five development planes live under one `auto_dev/` parent at every scope:

```text
auto_dev/                         Auto-Dev stage behavior (`*.md` here)
├── environment_access/          hosts, VPN, cloud, and runtime access
├── dev_standards/               design, code, security, tests, docs, observability
├── qa_gates/                    acceptance, regression, runtime, and evidence gates
└── gitflow_topology/            branches, PR families, propagation, and merges
```

This containment is part of the contract. Do not recreate
`dev_standards/`, `qa_gates/`, `gitflow_topology/`, or
`environment_access/` as active siblings of `auto_dev/`.

Each of the five planes is composed in the same order: shared root policy,
domain policy, project policy, then an explicit invocation overlay when one is
supplied.

Later layers may add verified specifics or stricter rules; they may not remove
inherited safety, evidence, approval, or readback requirements.

## How to verify configuration

README files are indexes and are not active policy. A domain or project is
configured only when it has substantive numbered Markdown and policy readback
selects the expected root, domain, and project sources. Verify with:

`agentic-os develop policy <domain> <project> --plane <plane> --root <os-root> --json`

Store no secrets, tokens, private keys, kubeconfig content, customer data, or
unbounded logs in these policy folders. Project source instructions remain
authoritative for repository-local behavior, and live provider readback
remains authoritative for external state.
