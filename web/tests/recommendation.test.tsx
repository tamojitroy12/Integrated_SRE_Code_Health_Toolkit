import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationPanel } from "@/components/findings/recommendation-panel";
import { ToastProvider } from "@/components/ui/toast";
import type { FindingDetail, Recommendation } from "@/lib/types";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: "u", email: "m@x", display_name: "M", role: "maintainer" }, can: () => true, status: "authenticated" }),
}));

const finding = { id: "f1", type: "dependency_vulnerability" } as FindingDetail;

const rec: Recommendation = {
  id: "r1", finding_id: "f1", kind: "upgrade_guidance", status: "completed", validation_status: "partially_validated",
  model: "claude-sonnet-5-5", summary: "Upgrade lodash to <b>4.17.19</b>.",
  claims: [
    { claim_id: "c1", type: "fixed_version", kind: "checkable", text: "4.17.19 fixes the advisory.", evidence_refs: ["ev-2"],
      validation: "supported", validation_note: "Matches advisory fixed range." },
    { claim_id: "c2", type: "fixed_version", kind: "checkable", text: "4.17.99 also works.", evidence_refs: ["ev-2"],
      validation: "unsupported", validation_note: "Version not found." },
  ],
  alternatives: [], suggested_steps: ["Update through a reviewed fix proposal."], proposed_patch: null, confidence: "medium",
  limitations: ["Reachability of the vulnerable code path was not analyzed."],
  evidence: [{ id: "ev-2", kind: "advisory_record", source: "osv", url: "https://osv.dev/vulnerability/GHSA-x", retrieved_at: "2026-10-13T09:00:00Z" }],
  error: null, feedback: null, label: "AI-generated, advisory", job: null, created_at: "2026-10-13T09:00:00Z",
};

describe("recommendation panel (FR-AI-05)", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation((url: string) => {
      const body = url.includes("/ai/status") ? { enabled: true, notice: "Evidence is sent to Anthropic's API." } : { items: [rec] };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows badge, AI label, evidence links, confidence note and limitations; unsupported claims are collapsed", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider><RecommendationPanel finding={finding} archived={false} /></ToastProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Partially validated")).toBeInTheDocument());
    expect(screen.getByText("AI-generated, advisory")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ev-2/ })).toHaveAttribute("href", "https://osv.dev/vulnerability/GHSA-x");
    expect(screen.getByText(/not a probability/)).toBeInTheDocument();
    expect(screen.getByText("Reachability of the vulnerable code path was not analyzed.")).toBeInTheDocument();
    expect(screen.getByText(/Show unsupported claims \(1 item\)/)).toBeInTheDocument();
    // Model text is rendered as text, never as HTML.
    expect(screen.getByText("Upgrade lodash to <b>4.17.19</b>.")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });
});
