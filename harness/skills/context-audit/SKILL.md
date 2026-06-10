# Context Audit

Use this skill to audit the context load contract for a room, workflow, automation, or customer OS. The goal is to ensure each room loads only what the current stage needs and no more. Findings are severity-ranked and actionable.

## When To Use

- A room's CONTEXT.md does not have all six load-contract fields.
- An agent is loading too many files before it can act in a room.
- Onboarding a new room or migrating a room from a different structure.
- After adding new references, tools, or workflows to a room.

---

## Procedure

### Step 1 — Identify the Task Boundary

Before auditing, establish scope:

1. Which room (domain) is being audited?
2. What is the primary task an agent performs in this room?
3. What stage is this? (intake / active work / review / delivery)

The task boundary determines what "needs to be loaded" — a file that is needed for intake is not needed for delivery, and vice versa.

---

### Step 2 — Check the Six Load-Contract Fields

Open the room's `CONTEXT.md`. Verify all six load-contract fields are present and populated:

| Field | Expected Location in CONTEXT.md | Pass Condition |
| --- | --- | --- |
| **Read First** | `## Read First` section | Lists files an agent must always load before acting. At minimum: `ROUTER.md`, `RULES.md`, `TOOLS.md`. |
| **Read When Needed** | `## Read When Needed` section | Lists files loaded only when the task specifically requires them. Not empty. |
| **Do Not Load By Default** | `## Do Not Load By Default` section | Lists files that should be skipped unless explicitly requested. Not empty (silence here is a gap). |
| **Tools And Skills** | `## Tools And Skills` table | Names tools/skills with use-when and stop condition. |
| **Output Folders** | `## Output Folders` section | Lists where work products go. |
| **Done Criteria** | `## Done Means` section | Lists observable conditions that mean the task is complete. |

Mark each field as: Present and complete / Present but incomplete / Missing.

---

### Step 3 — Load Creep Check

For each file currently in Read First:

1. Is it genuinely needed before the agent can start? If not → move to Read When Needed.
2. Is it a cross-room file that belongs in a shared reference? If so → note it.

For each file in Read When Needed:

1. Is it ever actually loaded in practice? If not → move to Do Not Load By Default.

For each file NOT listed in Do Not Load By Default:

1. Are there obvious files in the room (archive, old runs, unrelated references) that an agent might load by default? If so → add them explicitly to Do Not Load.

**Escalation:** if the Read First list is longer than 6 files, that is a load-creep signal. Flag it as a medium finding.

---

### Step 4 — Source Priority Check

Load `shared_factory/05-knowledge/references/source-priority.md` if it exists. Verify:

1. The room's CONTEXT.md references the same source systems that appear in `source-priority.md`.
2. There are no source systems in the room's CONTEXT.md that are NOT in `source-priority.md` without a note explaining why.

If `source-priority.md` does not exist for this customer install, note it as a gap but do not block the audit.

---

### Step 5 — Tool and Skill Routing Check

In the `Tools And Skills` table:

1. Every tool/skill entry should have a `Use When` condition that names a specific task or stage.
2. Every tool/skill entry should have a stop condition (approval gate, quality gate, or explicit hand-off).
3. Tools listed here should appear in the room's `TOOLS.md` or the customer's `TOOLS.md`.

Flag any tool that is listed without a stop condition as a medium finding.

---

### Step 6 — Produce Findings List

Format findings as a ranked list. Severity levels:

| Severity | When To Use |
| --- | --- |
| **Critical** | Missing section blocks agent from acting (no Read First, no Done Means). |
| **High** | Missing Do Not Load section — agent may load too much silently. Missing approval gate in Tools. |
| **Medium** | Load creep (Read First > 6 items). Read When Needed has files never actually needed. Tool without stop condition. |
| **Low** | Minor wording issues, missing display name, empty placeholders. |

Each finding includes:

1. Severity
2. Section and file path
3. What was found
4. Recommended fix (move / add / remove / reword)

---

### Step 7 — Apply Fixes

For Critical and High findings: apply fixes immediately.

For Medium and Low findings: list them with recommended actions and let the operator decide.

After applying fixes:
- Re-read the CONTEXT.md and verify all six fields are present.
- Confirm the Read First list is 6 files or fewer where possible.
- If the room is profile-managed (`<!-- room-profile-managed -->` comment present), update the profile source and re-run `agentic-os room update`.

---

## Output Format

Return findings as:

```
Room: <room_slug>
Audited: <date>
Fields present: <count>/6
Findings: <count> (<critical> critical, <high> high, <medium> medium, <low> low)

CRITICAL
- [<file>] <what was found> → <recommended fix>

HIGH
- [<file>] <what was found> → <recommended fix>

MEDIUM
- [<file>] <what was found> → <recommended fix>

LOW
- [<file>] <what was found> → <recommended fix>
```

If there are no findings, output: `Room: <slug> — all 6 load-contract fields present. No findings.`

---

## Done

- All six load-contract fields are checked.
- Findings are severity-ranked.
- Critical and High findings are resolved.
- The agent can load less context and still act correctly.
- Approval risks and stop conditions are explicit.
- Output is a findings list the operator can act on.
