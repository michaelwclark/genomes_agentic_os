# Rationale

Genome's Agentic OS exists to make repeated agentic work cheaper, more reliable, and easier to resume.

The problem is not lack of agents. The problem is that every chat starts by rebuilding context: what project this is, where state lives, what process should run, what has already happened, what artifacts matter, and where the output should go.

The OS fixes that by making the operating structure explicit.

## Expected Improvements

- Fewer tokens spent on rediscovery.
- Better continuity across Claude, Codex, automations, and manual work.
- More predictable handoffs between human decisions and agent execution.
- Reusable client setups instead of bespoke one-off automation piles.
- Cleaner distinction between source code repos, operating state, and human dashboards.

## What This Is Not

- Not a replacement for project repos.
- Not a generic task manager.
- Not a single giant prompt.
- Not a web app by default.
- Not a place to hide business logic in chat history.

## Operating Principle

Every durable workflow should answer these questions without asking the human again:

1. What kind of work is this?
2. What domain owns it?
3. What context is needed?
4. What workflow or automation should run?
5. What state transition happened?
6. What evidence was produced?
7. What needs approval or follow-up?

If those answers are stored in predictable places, agents can operate with less prompt mass and less guessing.
