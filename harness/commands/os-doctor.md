# OS Doctor

Use when the installed OS needs structural cleanup, validation, or drift detection.

## Procedure

1. Run `agentic-os validate --root ~/agentic_os`.
2. Check root for legacy active-work folders.
3. Check domains for missing context, references, and control-plane files.
4. Check projects for missing status and source maps.
5. Check workflows for missing required sections.
6. Check automations for missing permissions and tests.
7. Check run logs for final state and next action.
8. Propose repairs before moving or deleting files.

## Output

List findings by severity: blocker, fix soon, cleanup, observation.
