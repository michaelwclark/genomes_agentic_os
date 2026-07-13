import type { AgenticOSApi } from "../shared/contracts";

declare global {
  interface Window {
    agenticOS: AgenticOSApi;
  }
}

export {};
