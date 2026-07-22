import type { AgenticOSApi } from "../shared/contracts";

declare global {
  interface Window {
    agenticOS: AgenticOSApi;
  }
}

declare module "react" {
  // Allow CSS custom properties in style objects without assertions (layout widths, model accents).
  interface CSSProperties {
    [key: `--${string}`]: string | number | undefined;
  }
}

export {};
