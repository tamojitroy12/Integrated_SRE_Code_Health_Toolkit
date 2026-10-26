"use client";

import { ArrowRightIcon, Cog6ToothIcon, PlayIcon, ShieldCheckIcon, SignalIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { JobProgress } from "@/components/project/job-progress";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardHeader, PageHeader, Stat } from "@/components/ui/card";
import { Sha, TimeAgo } from "@/components/ui/misc";
import { StaleFor } from "@/components/ui/stale-for";
import { AlertStatusBadge, Chip, JobStatusBadge, SeverityBadge, StatusBadge, TargetStatusBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows, Skeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { formatMetric, plural, sentence, providerName } from "@/lib/format";
import { useProjectParam } from "@/lib/project";
import type { Job, Overview } from "@/lib/types";

const SEVERITIES = ["critical", "high", "medium", "low", "info", "unrated"] as const;
const SEVERITY_BAR: Record<string, string> = {
  critical: "bg-crit", high: "bg-warn", medium: "bg-ink-2", low: "bg-ink-3", info: "bg-surface-3", unrated: "bg-surface-3",
};

function SectionError({ error, onRetry }: { error?: { message: string }; onRetry: () => void }) {
  return <ErrorState error={new Error(error?.message ?? "This section is unavailable.")} onRetry={onRetry} />;
}

function ViewAll({ href, children = "View all" }: { href: string; children?: ReactNode }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-1 text-[13px] font-medium text-ink-2 transition-colors hover:text-ink">
      {children}
      <ArrowRightIcon className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
    </Link>
  );
}

export default function OverviewPage() {
  const projectId = useProjectParam();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["overview", projectId],
    queryFn: () => api<Overview>(`/projects/${projectId}/overview`),
    refetchInterval: 15_000,
  });
  const scan = useMutation({
    mutationFn: () => api<{ job: Job }>(`/projects/${projectId}/scans`, { method: "POST", body: {} }),
    onSuccess: (r) => {
      setJobId(r.job.id);
      toast.show("Scan started. Results appear here when it finishes.", { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["overview", projectId] });
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });

  const data = q.data;
  const scanRunning = data?.latest_scan.scan_status === "queued" || data?.latest_scan.scan_status === "running";
  const canScan = can("maintainer") && !!data?.latest_scan.has_repository && !data.project.archived_at;
  const base = `/projects/${projectId}`;
  const targets = data?.monitoring.targets ?? [];
  const receiving = targets.filter((t) => t.status === "receiving").length;
  const openBySev = data?.top_findings.open_by_severity ?? {};
  const openFindings = Object.values(openBySev).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader
        title={data?.project.name ?? <Skeleton className="h-7 w-56" />}
        subtitle={data?.project.description ?? undefined}
        actions={
          <>
            {can("maintainer") ? <ButtonLink href={`${base}/settings`} icon={<Cog6ToothIcon />}>Settings</ButtonLink> : null}
            {canScan ? (
              <Button variant="primary" icon={<PlayIcon />} onClick={() => scan.mutate()}
                softDisabled={scanRunning || scan.isPending} title={scanRunning ? "A scan is already running" : undefined}>
                {scanRunning ? "Scan running…" : "Run scan"}
              </Button>
            ) : null}
          </>
        }
      />
      {jobId ? <div className="mb-5"><JobProgress jobId={jobId} label="Scan" onDone={() => setJobId(null)} /></div> : null}
      {q.isError ? <div className="mb-5"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div> : null}

      <div className="mb-6 grid grid-cols-4 gap-3 max-xl:grid-cols-2">
        {!data ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[84px] rounded-control" />) : (
          <>
            <Stat label="Services receiving" value={targets.length ? `${receiving} / ${targets.length}` : "—"}
              tone={targets.length && receiving === targets.length ? "healthy" : targets.length ? "warning" : undefined}
              hint={targets.length ? (receiving === targets.length ? "All targets reporting" : `${targets.length - receiving} not reporting`) : "No monitoring target"} />
            <Stat label="Open alerts" value={data.alerts.open_count}
              tone={data.alerts.unacknowledged_count ? "critical" : undefined}
              hint={data.alerts.unacknowledged_count ? `${data.alerts.unacknowledged_count} unacknowledged` : "Nothing needs attention"} />
            <Stat label="Open findings" value={data.latest_scan.status === "empty" ? "—" : openFindings}
              tone={(openBySev.critical ?? 0) > 0 ? "critical" : undefined}
              hint={data.latest_scan.status === "empty" ? "No scan yet" : `${openBySev.critical ?? 0} critical · ${openBySev.high ?? 0} high`} />
            <Stat label="Last scan" value={data.latest_scan.scan_status ? sentence(data.latest_scan.scan_status) : "—"}
              tone={data.latest_scan.scan_status === "succeeded" ? "healthy" : data.latest_scan.scan_status === "partial" ? "warning" : data.latest_scan.scan_status === "failed" ? "critical" : undefined}
              hint={data.latest_scan.created_at ? <TimeAgo iso={data.latest_scan.finished_at ?? data.latest_scan.created_at} /> : data.latest_scan.has_repository ? "Never scanned" : "No repository"} />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <section aria-labelledby="runtime-h" className="flex min-w-0 flex-col gap-5">
          <h2 id="runtime-h" className="sr-only">Runtime health</h2>
          <Card>
            <CardHeader title="Monitoring" subtitle="Live request rate, error ratio and p95 latency per service." action={<ViewAll href={`${base}/monitoring`}>Charts</ViewAll>} />
            {!data ? <LoadingRows rows={2} /> : data.monitoring.status === "error" ? (
              <div className="flex flex-col gap-3">
                <SectionError error={data.monitoring.error} onRetry={() => q.refetch()} />
                <TargetList data={data} projectId={projectId} />
              </div>
            ) : data.monitoring.status === "empty" ? (
              <EmptyState icon={SignalIcon} title="No monitoring target yet." action={can("maintainer") ? (
                <ButtonLink href={`${base}/settings`} size="sm">Add a target</ButtonLink>) : null}>
                Add one to see live metrics.
              </EmptyState>
            ) : (
              <TargetList data={data} projectId={projectId} />
            )}
          </Card>
          <Card>
            <CardHeader title="Alerts" subtitle={data && data.alerts.status !== "error" ? plural(data.alerts.open_count, "open alert") : undefined}
              action={<ViewAll href={`${base}/alerts`} />} />
            {!data ? <LoadingRows rows={2} /> : data.alerts.status === "error" ? <SectionError error={data.alerts.error} onRetry={() => q.refetch()} /> :
              data.alerts.status === "empty" ? (
                <p className="text-[13px] text-ink-2">No alerts. This does not prove the service is healthy; it means no rule is currently breached.</p>
              ) : (
                <ul className="-mx-5 flex flex-col divide-y divide-line border-t border-line max-md:-mx-4">
                  {data.alerts.recent.map((a) => (
                    <li key={a.id}>
                      <Link href={`${base}/alerts/${a.id}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-2.5 hover:bg-surface-2/60 max-md:px-4">
                        <span className="flex min-w-0 items-center gap-2.5">
                          <SeverityBadge severity={a.severity} emphasize />
                          <span className="truncate text-[13.5px] font-medium">{a.rule_name}</span>
                        </span>
                        <span className="flex items-center gap-3 text-caption text-ink-2">
                          <AlertStatusBadge status={a.status} />
                          <TimeAgo iso={a.last_seen_at} />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
          </Card>
        </section>

        <section aria-labelledby="code-h" className="flex min-w-0 flex-col gap-5">
          <h2 id="code-h" className="sr-only">Code health</h2>
          <Card>
            <CardHeader title="Latest scan" status={data?.latest_scan.scan_status ? <JobStatusBadge status={data.latest_scan.scan_status} /> : null}
              action={<ViewAll href={`${base}/code-health/scans`}>All scans</ViewAll>} />
            {!data ? <LoadingRows rows={2} /> : data.latest_scan.status === "error" ? <SectionError error={data.latest_scan.error} onRetry={() => q.refetch()} /> :
              data.latest_scan.status === "empty" ? (
                <EmptyState icon={ShieldCheckIcon} title={data.latest_scan.has_repository ? "No scan yet." : "No repository connected."}
                  action={!data.latest_scan.has_repository && can("maintainer") ? <ButtonLink href={`${base}/settings`} size="sm">Connect a repository</ButtonLink> : null}>
                  {data.latest_scan.has_repository ? "Run the first scan." : "Connect a GitHub repository to scan its dependencies and code."}
                </EmptyState>
              ) : (
                <div className="flex flex-col gap-4">
                  {data.latest_scan.scan_status === "partial" ? (
                    <Banner>Results may be incomplete: {(data.latest_scan.providers ?? []).filter((p) => p.status === "failed").map((p) => providerName(p.name)).join(", ")} failed.</Banner>
                  ) : null}
                  <div className="grid grid-cols-3 gap-3 max-sm:gap-2">
                    {(["new", "unchanged", "resolved"] as const).map((k) => (
                      <Stat key={k} label={sentence(k)} value={data.latest_scan.summary?.[k] ?? 0} />
                    ))}
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3 text-[13px]">
                    <span className="flex items-center gap-4 text-ink-2">
                      <span className="flex items-center gap-1.5">Commit <Sha sha={data.latest_scan.commit_sha} /></span>
                      <span>Finished <TimeAgo iso={data.latest_scan.finished_at ?? data.latest_scan.created_at} /></span>
                    </span>
                    <ul className="flex flex-wrap gap-1.5" aria-label="Providers">
                      {(data.latest_scan.providers ?? []).map((p) => (
                        <li key={p.name}>
                          <StatusBadge tone={p.status === "ok" ? "healthy" : p.status === "failed" ? "critical" : "neutral"} title={p.error ?? undefined}>
                            {providerName(p.name)}
                          </StatusBadge>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
          </Card>
          <Card>
            <CardHeader title="Top findings" subtitle={openFindings ? plural(openFindings, "open finding") : undefined}
              action={<ViewAll href={`${base}/code-health`}>Explorer</ViewAll>} />
            {!data ? <LoadingRows rows={3} /> : data.top_findings.status === "error" ? <SectionError error={data.top_findings.error} onRetry={() => q.refetch()} /> :
              data.top_findings.status === "empty" ? <p className="text-[13px] text-ink-2">{data.latest_scan.status === "empty" ? "Run a scan to see findings." : "No open findings in the latest scans."}</p> : (
                <>
                  {openFindings ? (
                    <div className="mb-4">
                      <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                        {SEVERITIES.map((s) => (openBySev[s] ? (
                          <span key={s} className={cn("h-full", SEVERITY_BAR[s])} style={{ width: `${(100 * (openBySev[s] ?? 0)) / openFindings}%` }} />
                        ) : null))}
                      </div>
                      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-2">
                        {SEVERITIES.filter((s) => openBySev[s]).map((s) => (
                          <li key={s} className="flex items-center gap-1.5">
                            <span className={cn("size-2 rounded-full", SEVERITY_BAR[s])} aria-hidden="true" />
                            {sentence(s)} <span className="font-medium text-ink">{openBySev[s]}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <ul className="-mx-5 flex flex-col divide-y divide-line border-t border-line max-md:-mx-4">
                    {data.top_findings.items.map((f) => (
                      <li key={f.id}>
                        <Link href={`${base}/code-health/findings/${f.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-2/60 max-md:px-4">
                          <SeverityBadge severity={f.severity} />
                          <span className="min-w-0 flex-1 truncate text-[13.5px]">{f.title}</span>
                          {f.change === "new" ? <Chip>New</Chip> : null}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}
          </Card>
          <Card>
            <CardHeader title="Fix proposals" subtitle="Dependency upgrades validated in a sandbox, delivered as draft pull requests."
              action={<ViewAll href={`${base}/code-health/fix-proposals`} />} />
            <p className="text-[13px] text-ink-2">{data ? plural(data.open_fix_proposals, "open proposal") : "…"}</p>
          </Card>
        </section>
      </div>
    </>
  );
}

function TargetList({ data, projectId }: { data: Overview; projectId: string }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {data.monitoring.targets.map((t) => (
        <li key={t.id} className="rounded-control border border-line bg-surface-2/40 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link href={`/projects/${projectId}/monitoring?target=${t.id}`} className="min-w-0 hover:underline">
              <span className="font-medium">{t.name}</span>
              <span className="ml-2 text-caption text-ink-2">{t.service_name} · {t.environment}</span>
            </Link>
            <TargetStatusBadge status={t.status} />
          </div>
          {t.status === "stale" && t.last_seen_at ? (
            <p className="mt-1 text-caption text-warn"><StaleFor since={t.last_seen_at} /></p>
          ) : null}
          <dl className="mt-3 grid grid-cols-3 gap-3">
            <Metric label="Request rate" value={formatMetric(t.current?.request_rate ?? null, "requests_per_second")} />
            <Metric label="Error ratio" value={t.current?.request_rate === 0 ? "No traffic" : formatMetric(t.current?.error_ratio ?? null, "ratio")} />
            <Metric label="p95 latency" value={formatMetric(t.current?.latency_p95_seconds ?? null, "seconds")} />
          </dl>
        </li>
      ))}
    </ul>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-caption text-ink-2">{label}</dt>
      <dd className="mt-0.5 text-[16px] font-semibold tracking-[-0.01em]">{value}</dd>
    </div>
  );
}
