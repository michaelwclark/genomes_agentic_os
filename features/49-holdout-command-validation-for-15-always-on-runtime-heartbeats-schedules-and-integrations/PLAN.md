# Plan

1. Inspect feature 15 artifacts and the runtime CLI command surface.
2. Create a fresh temporary OS root.
3. Validate managed runtime knowledge repair by deleting one runtime command and one runtime template, then running `docs update`.
4. Execute the runtime, heartbeat, schedule, integration, and Notion runtime tracking command matrix.
5. Verify Notion apply fails closed without a verified Genome's Notion workspace and only writes local tracking state when the verified workspace is supplied.
6. Run the full pytest suite.
7. Record the holdout result in the canonical feature 49 artifact set.
