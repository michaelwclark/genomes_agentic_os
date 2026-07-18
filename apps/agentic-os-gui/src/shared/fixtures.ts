import type { ConversationTranscript, GuiSnapshot } from "./contracts";

export const FIXTURE_NOW = "2026-07-13T18:00:00Z";

export const fixtureSnapshot: GuiSnapshot = {
  schema_version: "agentic-os-gui/v1",
  generated_at: FIXTURE_NOW,
  root: "/Users/operator/agentic_os",
  runtime: {
    status: "healthy",
    queue_mode: "execution_fabric",
    queue_depth: 3,
    running: 2,
    failed: 0,
    dead_letter: 0,
    active_workers: 2,
    unhealthy_workers: 0,
    reserved_interactive_slots: 1,
    queues: [],
    worker_pools: [],
  },
  navigation: {
    domains: [
      {
        id: "engineering",
        name: "Engineering",
        projects: [{ id: "acme_api", name: "Acme API", domain: "engineering", status: "active" }],
      },
      {
        id: "consulting",
        name: "Consulting",
        projects: [
          { id: "client_portal", name: "Client Portal", domain: "consulting", status: "active" },
          { id: "agentic_os", name: "Agentic OS", domain: "consulting", status: "active" },
        ],
      },
    ],
  },
  conversations: [
    {
      id: "019f5a20-8209-7712-a43f-82936e31f835",
      title: "Build the Agentic OS desktop cockpit",
      harness: "codex",
      provider: "openai",
      model: "gpt-5.6-sol",
      model_tier: "frontier",
      reasoning_effort: "high",
      status: "active",
      updated_at: "2026-07-13T17:02:00Z",
      domain: "consulting",
      project: "agentic_os",
      work_item: "041_agentic_os_gui",
      cwd: "/Users/operator/projects/agentic_os",
      pinned: true,
      can_continue: true,
      jira_keys: ["ACME-209"],
      pull_requests: [{ number: 5, repo: "example/agentic-os", url: "https://github.com/example/agentic-os/pull/5" }],
      assets: [{ label: "GUI work item", path: "consulting/02-projects/agentic_os/work-items/02-active/041_agentic_os_gui", kind: "work-item" }],
      git: { branch: "feat/aos-gui-041" },
      summary: "Build a native local driver for routed Agentic OS conversations.",
    },
    {
      id: "local_294b3242-0ed8-4a22-afb0-c431150aa548",
      title: "Review Acme API retry behavior",
      harness: "claude",
      provider: "anthropic",
      model: "claude-fable-5",
      model_tier: "balanced",
      reasoning_effort: "xhigh",
      status: "idle",
      updated_at: "2026-07-13T13:00:00Z",
      domain: "engineering",
      project: "acme_api",
      cwd: "/Users/operator/projects/acme-api",
      imported: true,
      cli_session_id: "294b3242-0ed8-4a22-afb0-c431150aa548",
      can_continue: true,
      continuation_note: "Imported Claude sessions resume under a single-writer lease. Approval prompts may require opening Claude Code.",
      jira_keys: ["ACME-2044"],
      slack_threads: ["https://acme.slack.com/archives/C0123456789/p1783951200000000"],
      summary: "Check the retry matrix and prepare a focused Django change.",
    },
    {
      id: "aos-client-session-001",
      title: "Client portal infrastructure status",
      harness: "codex",
      provider: "openai",
      model: "gpt-5.6-luna",
      model_tier: "economy",
      reasoning_effort: "medium",
      status: "idle",
      updated_at: "2026-07-12T15:00:00Z",
      domain: "consulting",
      project: "client_portal",
      cwd: "/Users/operator/projects/client-portal",
      can_continue: false,
      continuation_note: "This imported record is read-only; open it in the native harness.",
    },
  ],
  diagnostics: [],
};

export const fixtureTranscripts: Record<string, ConversationTranscript> = Object.fromEntries(
  fixtureSnapshot.conversations.map((conversation) => [
    conversation.id,
    {
      conversation_id: conversation.id,
      messages: [
        {
          id: `${conversation.id}-u1`,
          role: "user",
          content: conversation.summary ?? conversation.title,
          created_at: conversation.updated_at,
        },
        {
          id: `${conversation.id}-a1`,
          role: "assistant",
          content: "I have the routed project context and current metadata. The next action is ready.",
          created_at: conversation.updated_at,
        },
      ],
      continuation: {
        supported: Boolean(conversation.can_continue),
        mode: "resume",
        note: conversation.continuation_note,
      },
    },
  ]),
);
