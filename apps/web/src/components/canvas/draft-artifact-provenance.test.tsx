import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DraftArtifactProvenance } from "./canvas-node";

const citation = {
  id: "citation-a",
  sourceId: "chunk-a",
  documentId: "document-a",
  documentTitle: "A.pdf",
  chunkId: "chunk-a",
  chunkIndex: 0,
  startOffset: 0,
  endOffset: 6,
  pageNumber: 1,
  heading: null,
  excerpt: "Fact A",
  claim: "Claim A",
  ordinal: 1,
};
const provenance = {
  executionId: "exec",
  responseId: "response",
  traceId: "trace",
  originalText: "Immutable original",
  edited: true,
  insufficientEvidence: false,
  citations: [citation],
};

describe("saved draft provenance", () => {
  it("labels user edits and exposes read-only original evidence and exact citation navigation", async () => {
    const onOpenCitation = vi.fn();
    const user = userEvent.setup();
    render(<DraftArtifactProvenance provenance={provenance} onOpenCitation={onOpenCitation} />);
    expect(screen.getByText("User-edited content � original evidence unchanged")).toBeVisible();
    await user.click(screen.getByText("Original AI evidence"));
    expect(screen.getByTestId("draft-original-text")).toHaveTextContent("Immutable original");
    expect(
      screen.getByText("Original citations support the original response, not subsequent edits."),
    ).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Inspect original Trace" }).getAttribute("href"),
    ).toContain("trace");
    await user.click(screen.getByRole("button", { name: "Open source 1: A.pdf" }));
    expect(onOpenCitation).toHaveBeenCalledExactlyOnceWith(citation);
  });

  it("preserves refusal status when a refusal is saved and has no sources", async () => {
    render(
      <DraftArtifactProvenance
        provenance={{ ...provenance, edited: false, insufficientEvidence: true, citations: [] }}
        onOpenCitation={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByText("Original AI evidence"));
    expect(screen.getByText("Saved AI draft � editable copy")).toBeVisible();
    expect(screen.getByText("Original response: insufficient evidence")).toBeVisible();
    expect(screen.getByText("No source citations")).toBeVisible();
  });
});
