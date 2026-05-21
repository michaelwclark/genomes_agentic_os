# Investigation

- Existing routers, context files, active-work files, and project records already exist in the installed OS tree.
- Feature 01 added project records and source-map metadata, which are the durable linked-repo detection input.
- This feature can stay read-only by assembling context packets without mutating workflow context files or run logs.
- Low confidence should return a CLI error instead of guessing.
