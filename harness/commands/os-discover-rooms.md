# OS Discover Rooms

Use when creating a new Agentic OS install for a customer, project, or operator whose rooms should not inherit Genome's personal default domains.

## Procedure

1. Confirm whether this is Genome's personal OS or a customer/operator OS.
2. Ask diagnostic questions before creating rooms:
   - What work happens repeatedly?
   - What are the 3-5 main rooms or work areas in the operator's words?
   - What inputs arrive for each room?
   - What outputs should each room produce?
   - What references, standards, or source systems matter?
   - What should agents not load by default?
   - What tools or skills belong in each room or stage?
   - What actions require approval?
3. Convert answers into a profile using `templates/profile/customer-os-profile.yml`.
4. Generate room `CONTEXT.md` files from `templates/room/context.md`.
5. Generate routing tables from `templates/room/routing-table.md`.
6. Add shared references for naming, tools, style/output rules, and source priority.
7. Test one real workflow end to end before adding automations.

## Output

Return:

```text
profile_path:
rooms:
aliases:
routing_table:
references_to_create:
skills_to_install_or_link:
approval_gates:
first_workflow_to_test:
```

## Safety Rule

Do not create customer-visible or production-writing automations during discovery. Capture them as future automation candidates until workflow evidence exists.
