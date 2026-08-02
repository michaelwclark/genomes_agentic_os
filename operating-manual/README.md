---
sidebar_position: 0
sidebar_label: Overview
---

# Agentic OS Operating Manual

This manual is installed into `~/agentic_os/harness/shared_factory/05-knowledge/operating-manual/`.

Use it when you are operating inside the installed OS and need to know what to create, where to put it, what format to use, and what evidence to leave behind.

**Canonical doc split:** Use this `operating-manual/` when you are an installed-OS operator or agent working from `~/agentic_os`. For evaluator/developer documentation about the source package, architecture, install path, validated command behavior, and extension model, use the [`docs/` handbook](../docs/README.md).

**Never used this system before?** This manual assumes you already know the
vocabulary. Read [Start here](../docs/start/index.md) first — a plain-English
introduction with a [glossary](../docs/start/glossary.md) of every internal term.

**Overlapping material:** three sections here cover the same ground as a handbook
page, from the operator's side rather than the developer's. If one does not land,
read the other.

| This manual | The handbook |
| --- | --- |
| [`01-concepts/`](01-concepts/README.md) | [00 · Overview](../docs/00-overview.md) |
| [`08-harness-commands/`](08-harness-commands/README.md) | [17 · CLI reference](../docs/17-cli-reference.md) |
| [`09-troubleshooting/`](09-troubleshooting/README.md) | [18 · Troubleshooting and FAQ](../docs/18-troubleshooting-and-faq.md) |

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
