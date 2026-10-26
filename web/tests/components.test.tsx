import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { LineChart } from "@/components/charts/line-chart";
import { DiffViewer } from "@/components/ui/misc";
import { AlertStatusBadge, SeverityBadge, ValidationBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { ToastProvider } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("state primitives (FR-DSH-06)", () => {
  it("renders loading as content-shaped skeletons, not spinners", () => {
    render(<LoadingRows rows={3} label="Loading findings" />);
    expect(screen.getByRole("status", { name: "Loading findings" })).toBeInTheDocument();
  });
  it("renders empty states with an action", () => {
    render(<EmptyState title="No scan yet." action={<button>Run scan</button>}>Run the first scan.</EmptyState>);
    expect(screen.getByText("No scan yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run scan" })).toBeInTheDocument();
  });
  it("renders errors with a retry and a selectable request ID", () => {
    let retried = false;
    render(<ErrorState error={new ApiError(503, "PROMETHEUS_UNAVAILABLE", "Metrics store unreachable.", [], "req-42")} onRetry={() => { retried = true; }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Metrics store unreachable.");
    expect(screen.getByText("req-42")).toHaveClass("select-all");
    screen.getByRole("button", { name: "Retry" }).click();
    expect(retried).toBe(true);
  });
  it("banners are persistent text, not dismissible", () => {
    render(<Banner>Results may be incomplete: osv failed.</Banner>);
    expect(screen.getByRole("status")).toHaveTextContent("osv failed");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("badges never rely on colour alone", () => {
  it("severity and status badges carry words", () => {
    render(<><SeverityBadge severity={null} /><SeverityBadge severity="critical" /><AlertStatusBadge status="acknowledged" /><ValidationBadge status="partially_validated" /></>);
    expect(screen.getByText("Unrated")).toHaveAttribute("title", "The source provided no severity.");
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
    expect(screen.getByText("Partially validated")).toBeInTheDocument();
  });
});

describe("hostile strings render as inert text (SC-12, TH-21)", () => {
  const hostile = `<img src=x onerror="alert(1)"><script>alert(2)</script>`;
  it("diff viewer escapes content", () => {
    const { container } = render(<DiffViewer diff={`+${hostile}\n-old`} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(2)</script>");
  });
  it("empty state escapes titles", () => {
    const { container } = render(<EmptyState title={hostile} />);
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("line chart", () => {
  it("draws gaps for missing samples and labels the time zone", () => {
    const points = [
      { t: "2026-10-13T09:00:00Z", v: 1 }, { t: "2026-10-13T09:00:15Z", v: null }, { t: "2026-10-13T09:00:30Z", v: 3 },
    ];
    const { container } = render(<LineChart title="Request rate" unit="requests_per_second" zone="utc" series={[{ label: "req/s", points }]} />);
    const d = container.querySelector("path")!.getAttribute("d")!;
    expect(d.match(/M/g)?.length).toBe(2); // the null breaks the line instead of interpolating
    expect(container.textContent).toContain("UTC");
    expect(screen.getByRole("img", { name: "Request rate" })).toBeInTheDocument();
  });
});

describe("toast provider", () => {
  it("mounts", () => {
    wrap(<p>child</p>);
    expect(screen.getByText("child")).toBeInTheDocument();
  });
});
