# Client Automation Brief

Use this skill to turn a customer workflow discovery conversation into a signed-off automation brief. The brief separates deterministic, rule-based, LLM-needed, and human-judgment steps before any build decision is made. Nothing is automated until the brief is complete and approved.

## When To Use

- An operator wants to automate a repeated customer workflow.
- A customer discovery session produced candidate processes.
- You need to decide whether to build a workflow, automation, or manual runbook.

## Prerequisites

- A customer OS root exists (`agentic-os customer init` has run).
- The target domain is identified.
- At least one discovery conversation has happened.

---

## Procedure

### Step 1 — Discovery Questions

Ask the following questions. Do not proceed past this step until you have enough answers to fill the brief template.

**Process questions:**
1. What is the business outcome this process produces?
2. What are the steps, in order, as they happen today?
3. Which systems are touched (source, destination, intermediate)?
4. What inputs arrive and from where?
5. What outputs are produced and where do they go?
6. How often does this run (daily / weekly / per-event)?

**Cost and risk questions:**
7. How long does a human take per run?
8. What happens when a run is late, missed, or wrong?
9. Which steps require a human to make a judgment call?
10. Which steps must never be automated (compliance, legal, billing, approvals)?

**Fit questions:**
11. Is the process stable and documented, or still changing?
12. Who owns the process and can approve changes?
13. How would you measure success?
14. What is the smallest useful pilot using real data?

---

### Step 2 — Layer Triage

Before writing the brief, classify every step using the four-layer triage. This separation is required — it is what prevents premature automation.

| Layer | Definition | Examples |
| --- | --- | --- |
| Deterministic | Same input always produces same output. No ambiguity. | File move, API call with fixed payload, format conversion |
| Rule-based | Decision tree with explicit rules; no natural language understanding needed. | Route by status field, apply discount if condition met |
| LLM-needed | Requires language understanding, synthesis, or generation. | Classify email intent, draft reply, summarize thread |
| Human judgment | Requires accountability, context outside the system, or compliance sign-off. | Approve customer-visible output, billing decisions, legal review |

Record each step against one of these layers in the `Step Classification` table of the brief.

**Rule:** do not automate a step classified as Human Judgment. Do not build LLM-needed steps into the first pilot unless deterministic and rule-based steps have already been validated.

---

### Step 3 — Automation Fit Gate

Before writing the brief, apply the automation fit check using `templates/customer/automation-fit-matrix.md`. If the process fails the gate, stop and write a manual runbook instead.

**Good first automation — must meet at least 5 of 7:**
- Frequent (runs at least weekly)
- Painful (measurable human time cost or error rate)
- Visible (operator can inspect outputs)
- Measurable (clear success metric exists)
- Stable (process is documented and not actively changing)
- Low enough risk for a pilot (reversible or sandboxable)
- Has a clear human approval gate before external or customer-visible output

**Bad first automation — stop if any of these are true:**
- High compliance risk with no approval model
- Undocumented or unstable process
- No clear owner
- No measurable success criterion
- Requires full system replacement before it can be automated
- Asks for fully autonomous irreversible actions

If the process fails the gate, record why in the brief's `Must Stay Manual` section and close the brief without a build decision.

---

### Step 4 — Fill the Brief Template

Load the brief template from one of:
- `<customer-root>/customer/client-automation-brief.md` (the customer-rendered copy)
- `shared_factory/05-knowledge/templates/customer/client-automation-brief.md` (the canonical template)

Or scaffold a named instance:

```
agentic-os customer brief --root <customer-root> --domain <domain> --name <slug>
```

This creates `<customer-root>/<domain>/01-intake/<slug>-brief.md` — write-once, refuses overwrite.

Fill every section from your discovery answers and layer-triage table. Required sections:

- `Outcome` — what business result changes
- `Current Manual Workflow` — steps as they happen today
- `Systems Involved` — system, role, access needed
- `Inputs` and `Outputs`
- `Frequency`, `Current Time Cost`, `Error Cost`
- `Step Classification` — layer-triage table
- `Must Stay Manual` — human-judgment steps that are never automated
- `Automation Candidate Steps` — deterministic and rule-based steps suitable for a pilot
- `Acceptance Criteria` — how you will know the pilot succeeded
- `Approval Gate` — who approves before any customer-visible or production output
- `Rollback` — how to undo or recover from a bad run
- `Pilot Scope` — smallest useful pilot using real data
- `Data Boundaries` — allowed systems, prohibited systems, retention, deletion, credential policy
- `Metrics Baseline` — current and target values with measurement source

---

### Step 5 — Approval Gate

The brief must be reviewed and approved by the operator before any build begins. Record approval in the brief file with date and approver name.

**Do not:**
- Start building before approval
- Skip the Pilot Scope section
- Merge automation steps and human-judgment steps into a single pipeline

---

## Where The Brief Lives

In a customer install, brief instances go under:

```
<customer-root>/<domain>/01-intake/<name>-brief.md
```

The `customer/` folder also contains a rendered copy of the blank template:

```
<customer-root>/customer/client-automation-brief.md
```

---

## Done

- Discovery questions are answered.
- Every step is classified in the layer-triage table.
- Automation fit gate is documented (pass or stop with reason).
- Brief is complete with all required sections filled.
- Approval gate names the approver and is recorded in the file.
- The pilot is small, measurable, and reversible.
- No build decision exists without an approved brief.

## Canonical artifact projection

This skill owns discovery questions, layer classification, and approval
judgment. The `customer brief` command may create the routed source scaffold,
but the completed filesystem or Notion brief must be rendered and validated as
`client-automation-brief` through `$auto-dev-create-artifacts`. External Notion
apply requires verified Genome's Notion target, typed approval/target receipts,
and provider readback. Do not maintain a second presentation or readback policy
in this skill.
