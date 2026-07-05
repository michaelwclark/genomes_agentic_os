# Agentic OS Operating Manual

This manual is installed into `~/agentic_os/shared_factory/05-knowledge/operating-manual/`.

Use it when you are operating inside the installed OS and need to know what to create, where to put it, what format to use, and what evidence to leave behind.

**Canonical doc split:** Use this `operating-manual/` when you are an installed-OS operator or agent working from `~/agentic_os`. For evaluator/developer documentation about the source package, architecture, install path, validated command behavior, and extension model, use the [`docs/` handbook](../docs/README.md).

## Start Here

| Need | Read |
| --- | --- |
| First use | `00-start-here/README.md` |
| Update safety | `00-start-here/update-contract.md` |
| Conceptual model | `01-concepts/README.md` |
| Folder and layer map | `02-layer-map/README.md` |
| File formats | `03-file-formats/README.md` |
| Common recipes | `04-recipes/README.md` |
| Good examples | `05-good-examples/README.md` |
| Validation checklists | `06-checklists/README.md` |
| Visual maps | `07-diagrams/` |
| Harness commands and skills | `08-harness-commands/README.md` |
| Common problems | `09-troubleshooting/README.md` |
| Build plans and future ideas | `../plans/README.md` |

## Operating Rule

Do not start by inventing a new shape. Pick the current layer, use the expected format, then record the run or routing update that proves what changed.

## Update Rule

Install and update commands are additive and idempotent. They may add missing manual, command, skill, template, plan, or scaffold files, but they must not overwrite existing runtime files by default.

## Visual Index

Open `index.html` in a browser for the color-coded reading map.
