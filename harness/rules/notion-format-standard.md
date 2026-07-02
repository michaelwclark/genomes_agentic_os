# Notion Format Standard

Every Notion page or database row an Agentic OS agent, automation, or skill writes
into Genome's Notion follows this standard. It exists so pages are scannable at
a glance instead of raw markdown dumps. The strictest-rule-wins chain applies:
this standard extends (never replaces) the external-output rules in `RULES.md`.

## Page anatomy — in this order

1. **Icon + title** — every page gets an emoji icon. Pick one that identifies the
   surface (🧭 intake, 🤖 automation, 📚 docs, 🩺 health, 📡 watcher, 🔁 sync).
2. **Status callout** — one colored callout at the top: green `✅ healthy/success`,
   yellow `⚠️ attention`, red `🛑 failing/blocked`, gray `ℹ️ informational`.
   One sentence, plain English, no jargon.
3. **Snapshot** — a short section (heading color blue) with a compact table or
   3-6 bullets: what this is, when it last ran/changed, who/what runs it, where
   the evidence lives.
4. **Plain-English explanation** — one paragraph a non-expert can read. What it
   does, when it happens, what the human needs to do (usually nothing).
5. **Details in toggles** — anything long (help text, run history, raw output,
   command references, field docs) goes inside `▶ toggle` blocks so the page
   stays short. Never paste long logs inline.
6. **Tables for enumerable facts** — schedules, flags, env vars, run results.
   Headers bold. No walls of prose where a table fits.
7. **Source & validation footer** — where the filesystem source of truth lives
   and how the page content was verified (gray text or gray_bg blocks).

## Colors

- Blue headings: structure/navigation sections.
- Green backgrounds: success facts. Yellow/orange: warnings, evidence pointers.
  Red: failures and blockers. Purple: identifiers/schedules. Gray: meta/footnotes.
- Use color to break up long pages; never more than one accent color per line.

## Databases

- Few, central databases beat many scattered ones. Before creating a database,
  check the control hub for one that already covers the shape.
- Every row's page body is self-contained: a reader opening the row cold gets
  the mini-spec (context, what, why, acceptance) without chasing links.
- Selects get colors that mean something (red=P0/bug, orange=gap, green=done).
- Rows written by automations carry a `Source` property so humans can tell
  automation writes from manual writes.

## Update behavior

- Latest-run automation pages REPLACE their body each run (single-page summary,
  no per-run page spam). Detailed history stays in filesystem run logs.
- Never delete or overwrite human-authored child pages or databases when
  replacing page content.
- Verify the workspace is Genome's Notion before any write; never write to
  personal/Flywheel workspaces.

## Enforcement

- Skills and automations that write Notion reference this file in their SKILL.md
  or runbook and link the page they maintain.
- `agentic-os notion-org doctor` checks new automation pages for: icon present,
  status callout present, at least one toggle when body exceeds 40 blocks.
