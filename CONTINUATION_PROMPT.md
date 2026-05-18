# Continuation Prompt: Make Genome's Agentic OS Installable

Use this prompt with a new GPT-5.5 agent in this repository.

```text
You are GPT-5.5 working in the repository root.

Mission:
Make Genome's Agentic OS installable enough that I can test it in the morning.

Use orchestration. You are the orchestrator. Spawn bounded subagents where safe, verify their work yourself, integrate one return at a time, and do not trust unverified agent output.

Current repo state:
- Repository remote: inspect with git remote -v
- Branch: main
- Current cleaned public commit when this prompt was written: c2b963f
- Product display name: Genome's Agentic OS
- Package/repo slug may remain filesystem-safe as genomes_agentic_os.
- CLI command should be generic: agentic-os
- Default installed OS root should be generic: ~/agentic_os
- This is a public, generic tool. Do not include real client names, private workspace names, private channel names, or private project names.

Hard constraints:
- Do not reintroduce private/client/internal names.
- Do not use Mermaid diagrams. Durable diagrams must be SVG or PNG.
- Do not reference any private Notion workspace by name. Say "your Notion workspace" or "client-owned Notion workspace".
- Do not write secrets into docs, config, tests, run logs, memory, or examples.
- Do not force-push main. If you need a branch, create a normal branch and push it.
- Preserve any user changes in the worktree. Do not revert work you did not make.
- Use apply_patch for manual edits.
- Before non-trivial reconnaissance/debugging, call losmon memory_read with a focused query.
- At the end of substantive work, call losmon memory_write with the durable outcome and any non-obvious decisions.

Public scrub gate:
Run this before committing and again before final handoff.

Do not write a private denylist into the repository. If the user provides one through memory, environment, or direct prompt, keep it out of committed files and run it locally only.

Run denylist checks from values that live outside the repository:

rg -n -i "$PRIVATE_DENYLIST_REGEX" .

Expected result: no true positives.

The denylist should include private names, private workspace labels, internal channel names, legacy private paths, and any old branding that should not appear in public docs.

If there are false positives, explain them. Do not ignore true positives.

Primary goal:
Create the smallest useful installable V1. The morning test should be able to install the CLI, scaffold an OS root, scaffold a domain, scaffold a workflow, scaffold an automation, create a run log, and validate the result.

Recommended implementation:
- Python package with pyproject.toml.
- Console script: agentic-os.
- Source package path: src/genomes_agentic_os/.
- Keep runtime dependencies minimal.
- Prefer stdlib where reasonable.
- If YAML support is needed, use PyYAML and document it.
- If schema validation is implemented, use jsonschema and document it.
- Tests with pytest.

V1 command surface:
- agentic-os --help
- agentic-os init --target ~/agentic_os
- agentic-os domain create <name> --root ~/agentic_os
- agentic-os workflow create <domain> <lane> <name> --root ~/agentic_os
- agentic-os automation create <domain> <lane> <name> --root ~/agentic_os
- agentic-os run-log create <domain> <workflow-or-automation> --root ~/agentic_os
- agentic-os validate --root ~/agentic_os

V1 behavior:
- init creates the base tree:
  - domains/
  - workflows/
  - automations/
  - inbox/
  - runs/
  - context/
  - memory/
  - notion/
  - config/
  - templates/
- init copies the repo templates into the installed OS.
- domain create creates:
  - domains/<domain>/README.md
  - domains/<domain>/domain.yml
  - domains/<domain>/context/business.md
  - domains/<domain>/context/systems.md
  - domains/<domain>/context/stakeholders.md
  - domains/<domain>/context/access-policy.md
  - domains/<domain>/workflows/
  - domains/<domain>/automations/
  - domains/<domain>/decisions/
  - domains/<domain>/notion/
- workflow create copies the workflow template into the right domain/lane path.
- automation create copies the automation template into the right domain/lane path.
- run-log create creates a timestamped run log under runs/.
- validate checks required folders and basic JSON schema validity. If full YAML validation is too much for V1, validate folder shape and parse YAML safely.

Orchestration plan:

1. Baseline and project loading
   - Read AGENTS.md, README.md, spec/README.md, spec/cli-spec.md, spec/install-surface.md, templates/README.md.
   - Capture:
     - git status --short
     - git rev-parse HEAD
     - current file tree
     - whether pyproject.toml/package code already exists

2. Decompose into bounded workers
   - Worker A owns packaging and CLI implementation:
     - pyproject.toml
     - src/genomes_agentic_os/__init__.py
     - src/genomes_agentic_os/cli.py
     - src/genomes_agentic_os/scaffold.py
   - Worker B owns validation and tests:
     - src/genomes_agentic_os/validate.py
     - tests/
     - test fixtures or tmpdir tests
   - Worker C owns install docs and public examples:
     - README.md install section
     - docs or spec updates only if needed
     - no private names
   - Worker D is read-only QA/scrub:
     - run public scrub gate
     - run command help
     - run install/scaffold smoke test
     - report exact failures

3. Integration rules
   - Workers are not alone in the codebase.
   - Workers must not revert edits made by others.
   - Workers must list every file they changed.
   - Main orchestrator verifies every returned diff.
   - Integrate one worker at a time.

4. Verification commands
   Run the strongest available form of these:
   - python3 -m compileall src
   - python3 -m pytest
   - python3 -m pip install -e .
   - agentic-os --help
   - tmpdir=$(mktemp -d)
   - agentic-os init --target "$tmpdir/os"
   - agentic-os domain create internal_product --root "$tmpdir/os"
   - agentic-os workflow create internal_product engineering feature_dev --root "$tmpdir/os"
   - agentic-os automation create internal_product support production_thread_intake --root "$tmpdir/os"
   - agentic-os run-log create internal_product feature_dev --root "$tmpdir/os"
   - agentic-os validate --root "$tmpdir/os"
   - git grep public scrub gate above

5. Documentation acceptance
   README must include:
   - Install command.
   - Smoke-test commands.
   - What V1 does.
   - What V1 intentionally does not do.
   - Public/generic customization guidance.

6. Commit and handoff
   - Commit changes in a focused commit.
   - Prefer branch dev/installable-v1 unless the user explicitly says to push main.
   - Push the branch if credentials work.
   - Final handoff must include:
     - branch/commit
     - exact install command
     - exact smoke-test commands
     - verification results
     - remaining risks
     - what to test in the morning

Definition of done for overnight:
- A clean install path exists.
- The CLI can scaffold a local OS root.
- The generated tree is usable and generic.
- Basic validation passes.
- Tests pass.
- Public scrub gate passes.
- No private/client/internal names are present.
- No Mermaid diagrams are added.

If time is short:
Prioritize a working CLI and smoke test over additional docs. Do not overbuild Notion API integration tonight. For V1, Notion scaffolding can remain a documented/spec-level surface unless the CLI basics are already green.
```
