import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobProgress } from "@/components/project/job-progress";
import { ConfirmProvider } from "@/components/ui/confirm";
import { ToastProvider } from "@/components/ui/toast";
import type { Job } from "@/lib/types";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: "u", email: "m@x", display_name: "M", role: "maintainer" }, can: () => true, status: "authenticated" }),
}));

const base: Job = {
  id: "j1", type: "scan", status: "running", stage: "running_trivy", attempts: 1, error: null,
  resource: { type: "scan", id: "s1" }, cancel_requested: false,
  created_at: new Date(Date.now() - 5000).toISOString(), started_at: new Date(Date.now() - 4000).toISOString(), finished_at: null,
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("job progress (FR-DSH-05)", () => {
  const fetchMock = vi.fn();
  let polls = 0;
  beforeEach(() => {
    polls = 0;
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/jobs/j1/cancel") && init?.method === "POST") return json({ ...base, cancel_requested: true }, 202);
      polls += 1;
      if (polls === 1) return json(base);
      return json({ ...base, status: "partial", stage: null, finished_at: new Date().toISOString(),
        error: { code: "PROVIDER_FAILED", message: "Semgrep timed out." } });
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("polls the job, shows the current stage, then the terminal status with its error summary", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider><ConfirmProvider><JobProgress jobId="j1" label="Scan" /></ConfirmProvider></ToastProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText(/running trivy/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    // Cancelling asks for confirmation first; nothing is sent until the user confirms.
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/jobs/j1/cancel"), expect.anything());
    fireEvent.click(await screen.findByRole("button", { name: "Cancel scan" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/jobs/j1/cancel"), expect.anything()));
    // The hook re-polls every 2 s while the job is non-terminal and stops once it is terminal.
    await waitFor(() => expect(screen.getByText("PROVIDER_FAILED")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText("Semgrep timed out.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    const after = polls;
    await new Promise((r) => setTimeout(r, 2500));
    expect(polls).toBe(after);
  }, 15_000);
});
