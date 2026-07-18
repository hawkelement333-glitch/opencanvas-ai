import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoModeBanner } from "./open-canvas-app";

describe("Build Week demo mode banner", () => {
  it("labels replay data and exposes Trace and evidence classifications", () => {
    const apiBaseUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
      /\/$/,
      "",
    );
    render(
      <DemoModeBanner
        runtime={{
          mode: "deterministic_replay",
          externalAiEnabled: false,
          label: "Build Week demo · deterministic replay · no external AI calls",
          demoCanvasId: "d3000000-0000-4000-8000-000000000001",
          demoTraceId: "d3000000-0000-4000-8000-000000000002",
        }}
      />,
    );

    expect(screen.getByText("DEMO · deterministic replay")).toBeInTheDocument();
    expect(screen.getByText(/no account, production data, credentials/i)).toBeInTheDocument();
    expect(screen.getByText("Supported")).toBeInTheDocument();
    expect(screen.getByText("Inference")).toBeInTheDocument();
    expect(screen.getByText("Conflict")).toBeInTheDocument();
    expect(screen.getByText("Unsupported")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-demo-trace")).toHaveAttribute(
      "href",
      `${apiBaseUrl}/traces/d3000000-0000-4000-8000-000000000002`,
    );
  });

  it("renders nothing in live mode", () => {
    const { container } = render(
      <DemoModeBanner
        runtime={{
          mode: "live",
          externalAiEnabled: true,
          label: "Live model mode",
          demoCanvasId: null,
          demoTraceId: null,
        }}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
