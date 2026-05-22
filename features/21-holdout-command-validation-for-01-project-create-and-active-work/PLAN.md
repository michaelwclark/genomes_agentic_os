# Plan

1. Run the full repository test suite.
2. Create an isolated temporary OS root.
3. Create a `los/losmon_replacement` project with repo, Notion, Jira, and lane
   references.
4. Validate the root and check generated project files.
5. Add a manual status note, rerun creation, and confirm the note remains.
6. Create a project through the `lenders` alias and confirm it lands under
   `los`.
7. Attempt an invalid project name and confirm it is rejected.

