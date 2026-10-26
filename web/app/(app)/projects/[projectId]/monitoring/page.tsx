"use client";

import { SignalIcon } from "@heroicons/react/20/solid";
import { useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { LineChart } from "@/components/charts/line-chart";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardHeader, MetaList, PageHeader } from "@/components/ui/card";
import { SegmentedControl, TimeAgo } from "@/components/ui/misc";
import { StaleFor } from "@/components/ui/stale-for";
import { TargetStatusBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingBlock, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { type Zone } from "@/lib/format";
import { usePreference } from "@/lib/hooks";
import { useProjectParam } from "@/lib/project";
import type { ChartMetric, MetricSeries, RangeKey, Target } from "@/lib/types";

const RANGES: { value: RangeKey; label: string }[] = [
  { value: "15m", label: "15 min" }, { value: "1h", label: "1 h" }, { value: "6h", label: "6 h" }, { value: "24h", label: "24 h" },
];

function ChartCard({ title, children, query }: { title: string; children: React.ReactNode; query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => void; data?: MetricSeries } }) {
  return (
    <Card>
      <CardHeader title={title} as="h3" />
      {query.isPending ? <LoadingBlock height="h-[200px]" label={`Loading ${title}`} /> : query.isError ? (
        <ErrorState error={query.error} title="Metrics store unreachable" onRetry={query.refetch} />
      ) : query.data?.status === "no_data" ? (
        <EmptyState title="No samples for this service yet.">Check the service’s OpenTelemetry setup in project settings.</EmptyState>
      ) : query.data?.status === "no_traffic" ? (
        <EmptyState title="The service reported no requests in this range." />
      ) : (
        children
      )}
    </Card>
  );
}

function Detail({ target, range, zone }: { target: Target; range: RangeKey; zone: Zone }) {
  const metrics: ChartMetric[] = ["request_rate", "error_ratio", "latency_p50", "latency_p95", "latency_p99"];
  const results = useQueries({
    queries: metrics.map((m) => ({
      queryKey: ["metrics", target.id, m, range],
      queryFn: () => api<MetricSeries>(`/monitoring-targets/${target.id}/metrics`, { query: { metric: m, range } }),
      refetchInterval: 15_000,
    })),
  });
  const [rate, errors, p50, p95, p99] = results;
  return (
    <div className="flex min-w-0 flex-col gap-5">
      {target.status === "stale" ? (
        <Banner><StaleFor since={target.last_seen_at} /></Banner>
      ) : target.status === "waiting" ? (
        <Banner tone="info">Waiting for the first sample. Open Settings → Monitoring targets → Setup instructions to configure the service.</Banner>
      ) : null}
      <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
        <ChartCard title="Request rate" query={rate!}>
          <LineChart title="Request rate" unit="requests_per_second" zone={zone} series={[{ label: "req/s", points: rate!.data?.series ?? [] }]} />
        </ChartCard>
        <ChartCard title="Error ratio (5xx)" query={errors!}>
          <LineChart title="Error ratio" unit="ratio" zone={zone} series={[{ label: "5xx ratio", points: errors!.data?.series ?? [] }]} />
        </ChartCard>
        <ChartCard title="Latency" query={p95!}>
          <LineChart title="Latency percentiles" unit="seconds" zone={zone} series={[
            { label: "p50", points: p50!.data?.series ?? [], color: "var(--ctx1)", dash: "none" },
            { label: "p95", points: p95!.data?.series ?? [], color: "var(--c1)", dash: "7 4" },
            { label: "p99", points: p99!.data?.series ?? [], color: "var(--ctx2)", dash: "2 4" },
          ]} />
        </ChartCard>
        <Card>
          <CardHeader title="Target status" as="h3" status={<TargetStatusBadge status={target.status} />} />
          <MetaList items={[
            { label: "Service", value: <span className="mono">{target.service_name}</span> },
            { label: "Environment", value: target.environment },
            { label: "Last sample", value: <TimeAgo iso={target.last_seen_at} /> },
            { label: "Ingestion", value: target.ingestion_mode === "otlp_push" ? "OTLP push" : "Scrape" },
          ]} />
          <p className="mt-4 text-caption text-ink-2">
            Status means data is arriving. It does not mean the application is healthy.
          </p>
        </Card>
      </div>
    </div>
  );
}

function MonitoringInner() {
  const projectId = useProjectParam();
  const { can } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const [savedRange, saveRange] = usePreference<RangeKey>(`toolkit.range.${projectId}`, "1h", "session");
  const [zone, setZone] = usePreference<Zone>("toolkit.zone", "local");
  const range = (params.get("range") as RangeKey | null) ?? savedRange;
  const targets = useQuery({
    queryKey: ["targets", projectId],
    queryFn: () => api<Target[]>(`/projects/${projectId}/monitoring-targets`),
    refetchInterval: 15_000,
  });
  const selectedId = params.get("target") ?? targets.data?.[0]?.id;
  const selected = targets.data?.find((t) => t.id === selectedId);

  function setParam(key: string, value: string) {
    const sp = new URLSearchParams(params.toString());
    sp.set(key, value);
    router.replace(`${path}?${sp.toString()}`);
  }
  useEffect(() => {
    if (params.get("range")) saveRange(params.get("range") as RangeKey);
  }, [params, saveRange]);

  return (
    <>
      <PageHeader
        title="Monitoring"
        subtitle="Live metrics from OpenTelemetry. Charts refresh every 15 seconds."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl label="Time range" value={range} options={RANGES} onChange={(v) => setParam("range", v)} />
            <SegmentedControl label="Time zone" value={zone} options={[{ value: "local", label: "Local" }, { value: "utc", label: "UTC" }]} onChange={setZone} />
          </div>
        }
      />
      {targets.isPending ? <LoadingRows /> : targets.isError ? <ErrorState error={targets.error} onRetry={() => targets.refetch()} /> :
        targets.data.length === 0 ? (
          <EmptyState icon={SignalIcon} title="No monitoring target yet." action={can("maintainer") ? (
            <ButtonLink href={`/projects/${projectId}/settings`} variant="primary">Add a target</ButtonLink>) : null}>
            Register a service to see request rate, error ratio and latency.
          </EmptyState>
        ) : (
          <div className="grid grid-cols-[260px_minmax(0,1fr)] gap-5 max-lg:grid-cols-1">
            <nav aria-label="Targets" className="self-start rounded-panel border border-line bg-surface p-1.5 shadow-card">
              <div className="px-2.5 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Services</div>
              <ul className="flex flex-col gap-0.5 max-lg:flex-row max-lg:flex-wrap">
                {targets.data.map((t) => (
                  <li key={t.id}>
                    <Link
                      href={`${path}?target=${t.id}&range=${range}`}
                      aria-current={t.id === selectedId ? "true" : undefined}
                      className={cn("chrome hit flex flex-col gap-1 rounded-control px-2.5 py-2 transition-colors duration-150",
                        t.id === selectedId ? "bg-surface-3" : "hover:bg-surface-2")}
                    >
                      <span className="truncate text-[13.5px] font-medium">{t.name}</span>
                      <span className="flex items-center gap-2 text-caption text-ink-2">
                        <span className="mono">{t.environment}</span>
                        <TargetStatusBadge status={t.status} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            {selected ? <Detail target={selected} range={range} zone={zone} /> : <EmptyState title="Select a target." />}
          </div>
        )}
    </>
  );
}

export default function MonitoringPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <MonitoringInner />
    </Suspense>
  );
}
