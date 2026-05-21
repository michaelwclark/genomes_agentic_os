# Memory

- Use existing `normalize_domain` so `lenders` maps to `los`.
- Keep project writes additive; never rewrite an existing project file.
- Index updates are append-only rows so local project edits are preserved.
