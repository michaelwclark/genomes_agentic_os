import type { ReactElement } from "react";
import type { RuntimeHealth } from "../../shared/contracts";
import { ExecutionFabricView } from "../components/ExecutionFabricView";

export type PageId = "execution-fabric";

export interface PageRenderProps {
  runtime: RuntimeHealth;
  refreshRuntime(): Promise<void>;
  runtimeRefreshing: boolean;
}

export interface PageDefinition {
  title: string;
  render(props: PageRenderProps): ReactElement;
}

/** Non-conversation workspace pages; add an id to PageId and an entry here to host a new page tab. */
export const pageRegistry: Record<PageId, PageDefinition> = {
  "execution-fabric": {
    title: "Execution Fabric",
    render: ({ runtime, refreshRuntime, runtimeRefreshing }) => (
      <ExecutionFabricView runtime={runtime} onRefresh={refreshRuntime} refreshing={runtimeRefreshing} />
    ),
  },
};
