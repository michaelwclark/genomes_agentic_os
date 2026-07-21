# Auto-Dev Everything for Genomes Agentic OS

This repository is the reference project for a complete Auto-Dev Everything
delivery. The project policy lives in the installed Agentic OS project
`config/development.yml`; this page defines the source-repository side of that
contract.

## Delivery sequence

An implementation request is groomed into the Linear **Genomes Agentic OS**
project before source work starts. Auto-Dev creates or resumes one date-prefixed
packet in the project's canonical `work-items/` root, creates an isolated
worktree from `main`, and runs all sixteen stages through Health.

New packets never use `01-intake`, `02-active`, or `03-complete`.
Terminal packets remain in place for seven days and are then moved by **Work
Item Archive Health** to `work-items/99-archived/`. A returned ticket must
search that archive before new state is created.

Projects may configure retention with `archive.retention.value` and
`archive.retention.unit`; supported units are `days`, `weeks`, and `months`
(months use a 30-day operational interval). `retention_days` remains readable
for older instances.

## Reinstall-safe QA

Every source change must prove both a clean install and installation over an
existing instance:

```bash
uv sync --extra dev
uv run pytest -q
scripts/qa/reinstall-agentic-os.sh --root ~/agentic_os_qa
```

The script creates a temporary fresh installation, then installs twice over the
stable secondary root. It validates after every pass and verifies that an
operator-owned sentinel is unchanged. It never deletes the secondary root.

## Review, merge, and release

Claude is the preferred opposing reviewer. If the Claude review path is
unavailable, Auto-Dev records that fact and continues for this repository.
Automatic squash merge is allowed only after acceptance evidence, local QA,
exact-head CI, and GitHub mergeability readback pass.

After merge, Auto-Dev chooses a semantic version bump, updates
`pyproject.toml` and `src/genomes_agentic_os/__init__.py` together, tags the
exact merged revision as `v<version>`, creates source-backed GitHub release
notes, and reads back the tag and release.

## Documentation projection

Auto-Dev Document updates the repository handbook first. It then projects the
release to the registered Genomes Agentic OS hub in **Genome's Notion** and the
`/genomes_agentic_os/` section of Clark's Consulting. Notion writes require
workspace verification and readback. Website changes use a separate source
branch/PR, must pass the site build, and require public URL readback.
