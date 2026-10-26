"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { AlertActionButtons } from "@/components/alerts/alert-actions";
import { Breadcrumbs } from "@/components/layout/shell";
import { Card, CardHeader, PageHeader } from "@/components/ui/card";
import { CodeBlock, Disclosure, TimeAgo } from "@/components/ui/misc";
import { AlertStatusBadge, SeverityBadge, StatusBadge } from "@/components/ui/status-badge";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { formatDuration, formatMetric, formatTime, METRIC_LABELS, METRIC_UNITS } from "@/lib/format";
import { useProject } from "@/lib/project";
import type { Alert, Delivery } from "@/lib/types";

function TimelineItem({ title, children, tone }: { title: string; children: React.ReactNode; tone?: "crit" | "warn" | "ok" }) {
  const dot = tone === "crit" ? "bg-crit" : tone === "warn" ? "bg-warn" : tone === "ok" ? "bg-ok" : "bg-ink-3";
  return (
    <li className="relative">
      <span aria-hidden="true" className={`absolute -left-[25px] top-1.5 size-2 rounded-full ring-4 ring-surface ${dot}`} />
      <div className="font-medium">{title}</div>
      <div className="text-caption text-ink-2">{children}</div>
    </li>
  );
}

export default function AlertDetailPage() {
  const { projectId, alertId } = useParams<{ projectId: string; alertId: string }>();
  const project = useProject(projectId);
  const q = useQuery({ queryKey: ["alert", alertId], queryFn: () => api<Alert>(`/alerts/${alertId}`), refetchInterval: 15_000 });
  const deliveries = useQuery({ queryKey: ["deliveries", alertId], queryFn: () => api<Delivery[]>(`/alerts/${alertId}/deliveries`) });
  const a = q.data;
  const metric = a?.evidence.metric ?? a?.evidence.query_name ?? "";
  const unit = METRIC_UNITS[metric] ?? "";
  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: project.data?.name ?? "Project", href: `/projects/${projectId}` },
        { label: "Alerts", href: `/projects/${projectId}/alerts` }, { label: a?.rule_name ?? "Alert" }]} />
      {q.isPending ? <LoadingRows /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : a ? (
        <>
          <PageHeader
            title={
              <span className="flex flex-wrap items-center gap-3">
                {a.status === "firing" ? <span aria-hidden="true" className="pulse-crit inline-block size-3 rounded-full bg-crit" /> : null}
                {a.rule_name}
              </span>
            }
            meta={
              <div className="flex flex-wrap items-center gap-3">
                <SeverityBadge severity={a.severity} emphasize={a.status === "firing"} />
                <AlertStatusBadge status={a.status} />
                <span className="text-ink-2">{a.target ? `${a.target.service_name} (${a.target.environment})` : "Deleted target"}</span>
              </div>
            }
            actions={<AlertActionButtons alert={a} projectId={projectId} archived={!!project.data?.archived_at} />}
          />
          <div className="grid grid-cols-[2fr_1fr] gap-6 max-xl:grid-cols-1">
            <Card>
              <CardHeader title="Evidence" subtitle="Snapshot taken when the alert fired." />
              <dl className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
                <div><dt className="text-caption text-ink-2">Observed value</dt><dd className="text-[24px] font-semibold tracking-[-0.02em]">{formatMetric(a.evidence.observed_value, unit)}</dd></div>
                <div><dt className="text-caption text-ink-2">Threshold</dt><dd className="text-[24px] font-semibold tracking-[-0.02em]">{a.evidence.rule_type === "anomaly" ? `|z| > ${a.evidence.threshold}` : a.evidence.rule_type === "absence" ? formatDuration(a.evidence.threshold ?? 0) : formatMetric(a.evidence.threshold, unit)}</dd></div>
                <div><dt className="text-caption text-ink-2">Metric</dt><dd className="font-medium">{METRIC_LABELS[metric] ?? metric}</dd></div>
                <div><dt className="text-caption text-ink-2">Evaluation window</dt><dd className="mono">{a.evidence.window}</dd></div>
                {a.evidence.z_score !== undefined ? <div><dt className="text-caption text-ink-2">z-score</dt><dd className="font-medium">{a.evidence.z_score}</dd></div> : null}
                {a.evidence.last_observed_value !== undefined ? <div><dt className="text-caption text-ink-2">Latest observed</dt><dd className="font-medium">{formatMetric(a.evidence.last_observed_value ?? null, unit)}</dd></div> : null}
              </dl>
              <div className="mt-6">
                <h3 className="mb-2 text-[13.5px] font-semibold">Guidance</h3>
                <p className="max-w-[72ch] text-ink-2">{a.evidence.guidance || "No guidance was written for this rule."}</p>
              </div>
              <div className="mt-6">
                <Disclosure summary="Query used">
                  <CodeBlock label="PromQL">{a.evidence.query}</CodeBlock>
                </Disclosure>
              </div>
              <p className="mt-4 text-caption text-ink-2">
                The alert reports what the metrics show. It does not identify a code-level cause.{" "}
                <Link href={`/projects/${projectId}/monitoring?target=${a.target_id ?? ""}`} className="text-accent">Back to monitoring</Link>
              </p>
            </Card>
            <div className="flex flex-col gap-6">
              <Card>
                <CardHeader title="Timeline" as="h3" />
                <ol className="relative ml-1.5 flex flex-col gap-4 border-l border-line pl-5 text-[13.5px]">
                  <TimelineItem tone="crit" title="Fired"><span>{formatTime(a.first_seen_at, "local", true)}</span></TimelineItem>
                  <TimelineItem title="Last breach"><TimeAgo iso={a.last_seen_at} /> · {a.occurrence_count} evaluations</TimelineItem>
                  {a.acknowledged_at ? <TimelineItem tone="warn" title="Acknowledged">by {a.acknowledged_by?.display_name ?? "a user"}, <TimeAgo iso={a.acknowledged_at} /></TimelineItem> : null}
                  {a.resolved_at ? <TimelineItem tone="ok" title="Resolved">{a.resolved_by ? `by ${a.resolved_by.display_name}` : "automatically"}, <TimeAgo iso={a.resolved_at} /></TimelineItem> : null}
                </ol>
              </Card>
              <Card>
                <CardHeader title="Notifications" as="h3" />
                {deliveries.isPending ? <LoadingRows rows={2} /> : deliveries.isError ? <ErrorState error={deliveries.error} /> :
                  deliveries.data.length === 0 ? <p className="text-ink-2">No notification channels were configured when this alert changed state.</p> : (
                    <ul className="flex flex-col gap-2 text-[13.5px]">
                      {deliveries.data.map((d) => (
                        <li key={d.id} className="flex flex-wrap items-center justify-between gap-2">
                          <span>{d.channel_name ?? "Channel"} <span className="text-ink-2">({d.event})</span></span>
                          <span className="flex items-center gap-2">
                            <StatusBadge tone={d.status === "delivered" ? "healthy" : d.status === "failed" ? "critical" : "neutral"}>{d.status}</StatusBadge>
                            {d.error ? <span className="mono text-caption text-ink-2">{d.error}</span> : null}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
              </Card>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
