import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ResponseCitations } from "./canvas-node";

const citation = {
  id: "citation-1",
  sourceId: "S1",
  documentId: "document-1",
  documentTitle: "Verified facts.pdf",
  chunkId: "chunk-1",
  chunkIndex: 2,
  startOffset: 120,
  endOffset: 164,
  pageNumber: 3,
  heading: "Launch timeline",
  excerpt: "The launch date is October 14.",
  claim: "The launch is scheduled for October 14.",
  ordinal: 1,
};

describe("response citations", () => {
  it("renders an exact source title and page and opens the validated citation", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ResponseCitations citations={[citation]} onOpen={onOpen} />);

    expect(screen.getByText("Verified facts.pdf")).toBeInTheDocument();
    expect(screen.getByText("Page 3 · Launch timeline")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open source 1/i }));
    expect(onOpen).toHaveBeenCalledWith(citation);
  });

  it("labels uncited output without implying that it is grounded", () => {
    render(<ResponseCitations citations={[]} onOpen={vi.fn()} />);
    expect(screen.getByText("No source citations")).toBeInTheDocument();
  });

  it("renders passage and character bounds when page and heading metadata are unavailable", () => {
    render(
      <ResponseCitations
        citations={[{ ...citation, pageNumber: null, heading: null }]}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("Passage 3 · chars 120–164")).toBeInTheDocument();
  });
});
