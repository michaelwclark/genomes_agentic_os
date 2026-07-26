# Reuse Before Reimplementation

Focus: existing helpers, managers, and services are used instead of re-implemented.

## Write
- Search for the existing helper/manager/service before writing one. Extend
  the nearest existing pattern; match the sibling module.
- New utility code requires evidence the capability does not already exist.

## Review
- Flag inline re-implementations of existing helpers, copy-paste blocks with
  one variable renamed, and new catch-all utility modules.
- Duplication of an existing tested path is blocking when it can drift.

Blocking: when a tested existing path is duplicated.
