---
name: los-config-change
description: Prepare, validate, approve, promote, verify, and roll back ticket-backed LOS tenant configuration changes using local redacted snapshot baselines first and live read-only evidence only for freshness or coverage gaps.
---

# LOS Configuration Change

Use this skill for tenant, product, form, policy, document, integration, or
other LOS configuration changes that must be tracked against a FLYWL or LOSIMP
ticket.

1. Read `los/00-programs/los_config/` for baseline evidence, then
   `los/00-programs/los_configuration_change/` and the linked mutation workflow.
2. Require a ticket, tenant, configuration interface, source environment, and
   target environment before preparing a change.
3. Use `$los-config` to read each environment's local redacted snapshot
   `configmeta.json` and matching tenant/config files first. Record sync/coverage metadata, current
   selections, and source/target hashes; use a live read-only shell only for
   missing, stale, redacted, selector, or runtime evidence.
4. Classify the change as `content` or `shape`. For shape changes, validate
   the target code ref, inventory consumers, and run the declared target-code
   tests before requesting apply approval.
5. Prepare patches with `los_config_change.py`; do not directly edit a
   configuration row or selector map.
6. Stop for explicit approval before Jira writes, authenticated admin/API
   writes, or any production-target change.
7. After apply, verify the resolved target configuration and acceptance
   scenarios, record rollback details, and update the ticket only after the
   result is known.

Snapshot JSON is evidence only: it may be stale, must not be edited/replayed,
and never grants mutation approval.
