import type { ConversationFilter, ConversationSummary, ModelTier, Provider, ReasoningEffort } from "./contracts";

export function compactAge(iso: string, nowMs = Date.now()): string {
  const timestamp = Date.parse(iso);
  if (!Number.isFinite(timestamp)) return "?";
  const seconds = Math.max(0, Math.floor((nowMs - timestamp) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  const weeks = Math.floor(days / 7);
  if (weeks < 52) return `${weeks}w`;
  return `${Math.floor(weeks / 52)}y`;
}

const TIER_INTENSITY: Record<ModelTier, [number, number]> = {
  economy: [0.61, 0.1],
  balanced: [0.68, 0.13],
  frontier: [0.75, 0.17],
  frontier_max: [0.81, 0.2],
  human_gate: [0.81, 0.2],
  unknown: [0.66, 0.05],
};
const EFFORT_BUMP: Record<ReasoningEffort, number> = {
  low: -0.025,
  medium: 0,
  high: 0.018,
  xhigh: 0.032,
  max: 0.045,
  ultra: 0.055,
  unknown: 0,
};
const PROVIDER_HUE: Record<Provider, number> = { openai: 165, anthropic: 40, unknown: 255 };

export function modelColor(
  provider: Provider,
  tier: ModelTier = "unknown",
  effort: ReasoningEffort = "unknown",
): string {
  const [baseLightness, chroma] = TIER_INTENSITY[tier];
  const lightness = Math.min(0.86, Math.max(0.52, baseLightness + EFFORT_BUMP[effort]));
  return `oklch(${lightness.toFixed(3)} ${chroma.toFixed(3)} ${PROVIDER_HUE[provider]})`;
}

export function filterConversations(
  conversations: ConversationSummary[],
  filter: ConversationFilter,
): ConversationSummary[] {
  const query = filter.query?.trim().toLocaleLowerCase() ?? "";
  return conversations
    .filter((conversation) => !filter.domain || conversation.domain === filter.domain)
    .filter((conversation) => !filter.project || conversation.project === filter.project)
    .filter((conversation) => {
      if (!query) return true;
      return [
        conversation.title,
        conversation.summary,
        conversation.domain,
        conversation.project,
        conversation.work_item,
        conversation.model,
        ...(conversation.jira_keys ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(query);
    })
    .sort((left, right) => {
      const pinOrder = Number(Boolean(right.pinned)) - Number(Boolean(left.pinned));
      return pinOrder || Date.parse(right.updated_at) - Date.parse(left.updated_at) || left.title.localeCompare(right.title);
    });
}
