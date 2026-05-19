# Cliefnotes Source Analysis

This file records the one-by-one operating analysis of the local source dump at `/Users/genome/projects/factory/cliefnotes`. It is intentionally concise: the repo should encode reusable guidance, not republish the course.

## Export Inventory

| Course | Accessible Modules | OS Use |
| --- | ---: | --- |
| Getting Started | 3 | Orientation and level model. |
| The Foundation | 19 | Core folder OS, prompt, memory, router, and Claude Code model. |
| The Archive | 9 | Philosophy, human judgment, orchestration framing. |
| Implementation Playbooks | 12 | Concrete workflow, browser, inbox, GitHub, and pre-build patterns. |
| Building Your Stack | 8 | Custom UI, remote access, mobile sessions, persistence. |
| Davids Corner | 25 | Advanced packaging, memory, outcome, markdown tasks, chief-of-staff patterns. |
| No-access folders | 0 | Recorded as source gaps only. |

## Root

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `README.md` | Export index separates accessible courses from no-access folders. | Use this as source scope; do not infer content from locked folders. | Yes |

## Getting Started

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `getting-started/README.md` | Course orientation points users to the course map and progression. | OS docs need a clear reading path and install path. | Partial |
| `getting-started/001-navigating-the-course.md` | Navigation matters before deep work. | Root README and docs index should tell new users where to start. | Partial |
| `getting-started/002-levels-explained.md` | The program is structured by levels of maturity. | Explain OS levels: root, domain, project, workflow, automation, run, shared factory. | Yes |
| `getting-started/003-a-few-member-wins.md` | Proof comes from real outcomes, not theory. | Run logs and examples should capture evidence and repeatable wins. | Partial |

## The Foundation

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `the-foundation/README.md` | Foundation is durable capability, not a temporary trick. | Keep docs implementation-oriented and stable. | Partial |
| `the-foundation/001-1-1-what-you-need-5-min-setup.md` | Start with a small practical setup. | CLI setup should create a usable OS quickly. | Yes |
| `the-foundation/002-1-2-your-first-folder.md` | A first folder uses router/context/reference markdown to make the agent useful. | Generate domain `CONTEXT.md`, `REFERENCES.md`, and routers. | Yes |
| `the-foundation/003-1-3-how-to-structure-any-prompt.md` | Strong prompts separate identity, task, context, constraints, and output format. | Split those concerns into workflow files instead of one massive prompt. | Yes |
| `the-foundation/004-2-1-video-text-guide-series-overview.md` | Abstraction is the reason the method works. | Explain the OS as layered abstractions, not just folders. | Partial |
| `the-foundation/005-2-2-one-line-of-python-triggers-12k-lines-of-code.md` | Small interfaces can trigger large hidden systems. | CLI commands should create rich structures with minimal user input. | Partial |
| `the-foundation/006-2-3-how-a-1953-word-game-explains-ai-memory.md` | Memory depends on context and pattern, not magic recall. | Put durable context in files; use memory for stable learnings only. | Yes |
| `the-foundation/007-2-4-the-ladder-that-explains-every-ai-failure.md` | Failures often come from using the wrong abstraction level. | Add tool ladder and level rules so work is routed correctly. | Yes |
| `the-foundation/008-2-5-openclaw-has-350k-stars.md` | Existing open systems show reusable patterns. | Keep source maps and examples so agents can learn from references. | Partial |
| `the-foundation/009-2-6-video-as-code-my-ai-animation-stack.md` | Complex creative work can become code/spec driven. | Treat creative workflows as specs, assets, validation, and run evidence. | Partial |
| `the-foundation/010-2-7-from-nazi-psychology-to-ai-auditing.md` | AI output needs auditing and human judgment. | Approval gates and validation evidence are core, not optional. | Yes |
| `the-foundation/011-3-1-the-full-walkthrough-23-min-video.md` | The full method is map, rooms, and tools. | Root routers, domain folders, workflows/automations/skills are the core OS model. | Yes |
| `the-foundation/012-3-2-customizing-for-your-use-case.md` | The same architecture adapts to creators, consultants, developers, and other roles. | Domains should be configurable while retaining the same numbered structure. | Yes |
| `the-foundation/013-3-3-common-mistakes-and-how-to-fix-them.md` | Avoid giant root routers, too many spaces, stale context, and flat folders. | Root stays clean; domain context must be updated; start with a few domains. | Yes |
| `the-foundation/014-4-1-install-and-first-use.md` | Install and first use should lead to immediate hands-on execution. | CLI install docs need a smoke test and real `workflow create` path. | Yes |
| `the-foundation/015-4-2-claude-code-in-practice.md` | Claude Code is effective when operating against files and commands. | Workflows should be executable from Claude or Codex against the same repo files. | Yes |
| `the-foundation/016-4-3-claude-desktop-as-a-thinking-partner.md` | Chat is useful for thinking and planning. | Keep brainstorm/outcome/planning before dispatch, not as hidden chat history. | Yes |
| `the-foundation/017-4-4-making-claude-understand-your-project.md` | A project root instruction file explains overview, stack, commands, conventions, and avoid rules. | Generate `CLAUDE.md` alongside `AGENTS.md`; domain context teaches the room. | Yes |
| `the-foundation/018-4-5-where-this-goes.md` | The method expands into larger operating systems. | Docs should show path from folder to workflows, automations, and control plane. | Partial |
| `the-foundation/019-5-1-your-path-from-here.md` | Users should leave foundation with a next path. | Setup sequence should move from install to first domain to first workflow. | Yes |

## The Archive

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `the-archive/README.md` | Archive material provides evidence that the thinking has history. | Archive folder stores retired decisions and historical runs. | Partial |
| `the-archive/001-lesson-1-1-welcome.md` | Orient the learner before method. | Keep README and docs path direct. | Partial |
| `the-archive/002-lesson-1-2-a-2-000-year-overnight-success.md` | Durable methods often look sudden because foundation work is hidden. | Record decisions and run evidence so progress is inspectable. | Partial |
| `the-archive/003-lesson-2-1-the-mindset-before-the-method.md` | Mindset precedes method. | Docs should state operating principles before command details. | Partial |
| `the-archive/004-lesson-2-2-raise-the-bar.md` | The bar for AI work should be higher, not lower. | Validation, approval, and run logs are required standards. | Yes |
| `the-archive/005-lesson-2-3-more-human.md` | AI systems should amplify human judgment. | Control plane and approval rules keep humans accountable. | Yes |
| `the-archive/006-lesson-3-1-beyond-the-turing-test.md` | Do not judge AI only by chat imitation. | Measure outcomes, evidence, and repeatability. | Partial |
| `the-archive/007-lesson-3-2-the-questions-schools-should-be-asking.md` | Better questions produce better learning systems. | Add alignment questions before PRD/planning. | Yes |
| `the-archive/008-lesson-3-3-the-real-cost-of-knowledge.md` | Knowledge has storage, retrieval, and maintenance costs. | Source maps and memory policy prevent context sprawl. | Yes |
| `the-archive/009-lesson-3-4-computational-orchestration.md` | Work can be orchestrated across tools and steps. | Workflows, automations, scripts, and agents need explicit handoffs. | Yes |

## Implementation Playbooks

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `implementation-playbooks/README.md` | Playbooks are concrete build guides that end in real output. | Workflows should produce artifacts and validation, not abstract notes. | Yes |
| `implementation-playbooks/001-1-1-building-animations-with-claude-code.md` | Script, spec, build, render, and review form a repeatable creative workflow. | Workflow specs should include inputs, build stages, output contracts, and validation. | Yes |
| `implementation-playbooks/002-1-2-turn-illustrator-designs-into-web-animations.md` | Prepared assets and clear names make agent editing surgical. | Context packs should name source files and asset rules explicitly. | Partial |
| `implementation-playbooks/003-1-3-ai-animation-workflow-course-companion.md` | A short companion page helps users run a workflow without rereading everything. | Generate `quick-reference.md` for each workflow. | Yes |
| `implementation-playbooks/004-1-4-community-challenge-build-a-30s-explainer.md` | A bounded challenge proves the workflow. | Examples and run logs should capture pilot runs and retrospectives. | Partial |
| `implementation-playbooks/005-claude-design-folder-structure-as-a-design-system.md` | Folder structure, reusable components, and skills can form a design system. | Shared factory stores reusable patterns; domain workflows stay portable. | Yes |
| `implementation-playbooks/006-2-1-setting-up-claude-in-chrome-5-min.md` | Browser automation needs setup, permissions, and operational safety. | Automation docs need connector setup and permission boundaries. | Partial |
| `implementation-playbooks/007-2-2-pull-structured-data-from-any-page.md` | Browser extraction should specify visible fields, format, and verification. | Add source-linked context and output contracts for extraction workflows. | Yes |
| `implementation-playbooks/008-2-3-teach-claude-your-workflow.md` | Record repeatable browser workflows and automate only stable steps. | Add workflow documentation template and worth-automating checklist. | Yes |
| `implementation-playbooks/009-2-4-inbox-and-scheduling-on-autopilot.md` | Email/calendar assistants need ask-before-acting guardrails. | Strengthen automation permissions and approval defaults. | Yes |
| `implementation-playbooks/010-3-1-build-and-deploy-a-website.md` | Analyze first, create markdown handoff, then build/deploy. | Add dispatch handoffs and deployment/verification fields before execution. | Yes |
| `implementation-playbooks/011-3-2-github-and-folder-structure.md` | Clean folder structure, `.gitignore`, compact instructions, and GitHub basics matter. | Keep generated structure clean and include `.gitignore` guidance in docs/tests. | Yes |
| `implementation-playbooks/012-3-3-pre-build-planning-and-prompt-sequencing.md` | Analyze, brief, set boundaries, ask questions, then create a PRD before building. | Generate outcome brief, alignment questions, PRD, implementation plan, and handoff. | Yes |

## Building Your Stack

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `building-your-stack/README.md` | This level builds tools around workflows. | Custom interfaces should wrap proven workflows, not replace the OS. | Yes |
| `building-your-stack/001-1-1-starting-the-build-process.md` | Use a tool ladder and PRD-first process; build custom only when native tools fail. | Add tool ladder and PRD template. | Yes |
| `building-your-stack/002-1-2-how-i-use-claude-code-in-the-build-process.md` | Claude Code can be controlled by a purpose-built interface. | Treat custom UI as a control surface over the same file contracts. | Yes |
| `building-your-stack/003-1-3-designing-for-your-use-case.md` | Plan mode, subagents, workspace context, and resumable sessions shape the build. | Add dispatch ownership and progress files. | Yes |
| `building-your-stack/004-1-4-repo-tour-open-source-references.md` | Study existing tools selectively. | Keep `REFERENCES.md` and source maps for reusable patterns. | Partial |
| `building-your-stack/005-2-1-why-remote-access.md` | Remote access lets local work be controlled from elsewhere. | Document remote/mobile as transport, not source truth. | Yes |
| `building-your-stack/006-2-2-setting-up-remote-sessions.md` | Named sessions and reconnect behavior matter. | Add progress and run-log handoff requirements for remote sessions. | Yes |
| `building-your-stack/007-2-3-mobile-workflow-patterns.md` | Mobile work is good for checks, approvals, and small interventions. | Mobile sessions should update state before disconnecting. | Yes |
| `building-your-stack/008-2-4-session-persistence-across-devices.md` | Workspace files are long-term memory; progress/status files make sessions resumable. | Generate `progress.md` and require resume prompts. | Yes |

## Davids Corner

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `davids-corner/README.md` | This section is a resource collection, not a linear course. | Pull patterns selectively; do not treat every link as core V1. | Partial |
| `davids-corner/001-new-here-welcome-to-the-no-fluff-zone.md` | Orient new users with direct, practical guidance. | Keep docs concise and operational. | Partial |
| `davids-corner/002-ai-acronym-overload-here-s-the-cheat-sheet.md` | Terminology can block execution. | Domain glossary and docs index should define operational vocabulary. | Partial |
| `davids-corner/003-looking-for-design-inspiration.md` | Reference material improves output quality. | Store useful references in `REFERENCES.md` and source maps. | Partial |
| `davids-corner/004-some-of-my-favorite-resources.md` | Curated resources are part of the operating environment. | Shared factory can hold reusable resource lists and examples. | Partial |
| `davids-corner/005-this-one-s-golden-vibe-coding-rules.md` | Coding standards and rules improve AI coding output. | Use project/domain instruction files and validation scripts. | Yes |
| `davids-corner/006-tools-for-your-toolchest.md` | Tool choice matters by task. | Tool ladder should route to skills, scripts, MCPs, hooks, or plugins as needed. | Yes |
| `davids-corner/007-obsidian-is-bloat-batter-up.md` | Lightweight markdown can beat heavy knowledge tools for execution. | Markdown remains a first-class OS surface. | Yes |
| `davids-corner/008-flip-the-script-it-s-all-about-the.md` | Business value should drive tooling. | Outcome briefs must define value, not just activity. | Yes |
| `davids-corner/009-do-you-have-a-soul.md` | Human voice and judgment still matter. | Approval and review surfaces remain human-owned. | Partial |
| `davids-corner/010-my-ai-workflow-evolution.md` | Workflows mature over time. | Run logs should feed improvements back to templates and routers. | Yes |
| `davids-corner/011-building-companies-intelligence-layers.md` | Companies need intelligence layers across work. | OS should make work queryable, routable, and closed-loop. | Yes |
| `davids-corner/012-have-you-figured-out-the-code.md` | Stop only prompting; package repeatable work as prompts, skills, connectors, MCPs, hooks, scripts, and plugins. | Shared factory should own reusable packaged workflow assets. | Yes |
| `davids-corner/013-leaked-ten-prompts-from-experts.md` | Strong prompts can be reusable assets. | Store reusable prompts as templates with constraints and output contracts. | Partial |
| `davids-corner/014-introducing-the-hermes-stack.md` | Advanced private memory stacks can support persistent recall. | Treat Hermes/Cognee-style stacks as future memory-plane options, not V1 prerequisites. | Yes |
| `davids-corner/015-advanced-coding-best-practices.md` | Advanced code work needs conventions, testing, and disciplined execution. | Keep validation commands, file ownership, and code review gates in handoffs. | Yes |
| `davids-corner/016-start-here.md` | A curated start point reduces wandering. | Each workflow gets `quick-reference.md`. | Partial |
| `davids-corner/017-helping-your-ai-remember-tasks-between-sessions.md` | Task memory should track open work, recent activity, and threads. | Use `progress.md`, active-work tables, and run logs before advanced memory. | Yes |
| `davids-corner/018-i-run-four-phases-before-any-ai-builds-anything.md` | Brainstorm, plan, hand off, then dispatch. | Generate outcome brief, implementation plan, and dispatch handoff as mandatory pre-build artifacts. | Yes |
| `davids-corner/019-stop-prompting-start-defining-outcomes.md` | Define outcomes instead of wishes. | Outcome brief becomes the first workflow artifact. | Yes |
| `davids-corner/020-why-your-cold-emails-get-ignored.md` | Outreach should be outcome and audience aware. | Marketing/sales workflows need audience, proof, and approval fields. | Partial |
| `davids-corner/021-a-completely-markdown-based-task-management-system.md` | Markdown can operate a task system with ideas, focus, recurring work, and sync. | Keep inbox, active work, progress, and run logs in markdown-friendly formats. | Yes |
| `davids-corner/022-built-always-on-ai-chief-of-staff-that-texts-me.md` | Always-on assistants need triggers, narrow permissions, and notifications. | Model chief-of-staff behavior as guarded automation, not generic chat. | Yes |
| `davids-corner/023-first-big-win-first-client-is-signed.md` | Real business wins should feed back into the system. | Capture validated examples and outcomes in run logs/examples. | Partial |
| `davids-corner/024-allan-s-mini-series-parts-1-2.md` | Mini-series/resource content can become reusable learning paths. | Use shared factory or knowledge folders for curated learning sequences. | Partial |
| `davids-corner/025-gpt-5-5-what-actually-changed.md` | Model changes affect capability and tool choice. | Treat model recommendations as drift-prone; verify current docs before prescribing. | Partial |

## No Accessible Modules Returned

| Source | Core Guidance | Agentic OS Impact | Include |
| --- | --- | --- | --- |
| `the-vault/README.md` | README describes assets/templates but export returned no modules. | Record as a source gap; do not derive scaffold specifics from locked content. | No |
| `the-drawing-room-vip/README.md` | README describes live/VIP support but no modules. | No scaffold impact beyond noting human support is outside repo. | No |
| `lifetime-vip-access/README.md` | README describes purchase/access, no modules. | No OS impact. | No |
| `title-unlock-margin/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-highlight/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-annotation/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-abstract/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-index/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-compiler/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-architect/README.md` | Title unlock only. | No OS impact. | No |
| `title-unlock-orchestrator/README.md` | Title unlock only. | No OS impact. | No |

## Implementation Summary

High-confidence changes made from this analysis:

- Generate Claude and Codex routers from the same contract.
- Add domain context/reference files.
- Add workflow pre-build files for outcome, questions, PRD, plan, handoff, progress, and quick reference.
- Strengthen automation permissions with worthiness and ask-before-acting rules.
- Document remote/mobile sessions as transport layers.
- Keep private memory stacks and custom UI as later layers over the same file contracts.
