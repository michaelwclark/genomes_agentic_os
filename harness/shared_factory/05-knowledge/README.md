# Shared policy library

This directory contains the plain-English behavior that every configured
domain and project inherits. It is policy, not source code and not a second
workflow engine.

## Active policy planes

- `auto_dev/` describes the complete Auto-Dev lifecycle and every independently
  callable stage.
- `dev_standards/` describes how software is designed, changed, secured,
  tested, documented, and observed.
- `qa_gates/` describes acceptance, regression, runtime, and evidence gates.
- `gitflow_topology/` describes branches, pull-request families, propagation,
  and merge relationships.
- `environment_access/` describes safe host, VPN, cloud, and runtime access
  without storing credentials.

Each plane is composed in the same order: shared root policy, domain policy,
project policy, then an explicit invocation overlay when one is supplied.
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
