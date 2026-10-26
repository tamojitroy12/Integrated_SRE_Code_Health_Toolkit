"use client";

import { BellSlashIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AlertActionButtons } from "@/components/alerts/alert-actions";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/field";
import { SegmentedNav, TimeAgo } from "@/components/ui/misc";
import { AlertStatusBadge, SeverityBadge } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { formatMetric, METRIC_UNITS } from "@/lib/format";
import { useProject, useProjectParam } from "@/lib/project";
import type { Alert, Page, Target } from "@/lib/types";

function AlertsInner() {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const view = params.get("view") ?? "active";
  const severity = params.get("severity") ?? "";
  const targetId = params.get("target") ?? "";
  const status = view === "active" ? ["firing", "acknowledged"] : view === "resolved" ? ["resolved"] : [];
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<Target[]>(`/projects/${projectId}/monitoring-targets`) });
  const q = useQuery({
    queryKey: ["alerts", projectId, view, severity, targetId],
    queryFn: () => api<Page<Alert>>("/alerts", {
      query: { project_id: projectId, status, severity: severity || undefined, target_id: targetId || undefined, limit: 100 },
    }),
    refetchInterval: 15_000,
  });
  // Rows render from the set of alert IDs the operator has already seen, so incoming alerts never
  // reflow the table under the pointer; they wait behind the "N new — Show" pill.
  const filterKey = `${view}|${severity}|${targetId}`;
  const [seen, setSeen] = useState<{ key: string; ids: Set<string> | null }>({ key: filterKey, ids: null });
  if (seen.key !== filterKey) setSeen({ key: filterKey, ids: null });
  else if (q.data && seen.ids === null) setSeen({ key: filterKey, ids: new Set(q.data.items.map((a) => a.id)) });
  const shown = q.data && seen.ids ? q.data.items.filter((a) => seen.ids!.has(a.id)) : null;
  const fresh = q.data && seen.ids ? q.data.items.length - (shown?.length ?? 0) : 0;
  const showAll = () => q.data && setSeen({ key: filterKey, ids: new Set(q.data.items.map((a) => a.id)) });

  const setParam = (key: string, value: string) => {
    const sp = new URLSearchParams(params.toString());
    if (value) sp.set(key, value);
    else sp.delete(key);
    router.replace(`${path}?${sp.toString()}`);
  };
  const archived = !!project.data?.archived_at;

  return (
    <>
      <PageHeader title="Alerts" subtitle="Rules are evaluated every 30 seconds against Prometheus." />
      <SegmentedNav items={[{ href: `/projects/${projectId}/alerts`, label: "Active", exact: true },
        { href: `/projects/${projectId}/alerts/rules`, label: "Rules" }]} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-caption text-ink-2">Status
          <Select value={view} onChange={(e) => setParam("view", e.target.value)} className="min-w-40">
            <option value="active">Active (firing, acknowledged)</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-caption text-ink-2">Severity
          <Select value={severity} onChange={(e) => setParam("severity", e.target.value)} className="min-w-32">
            <option value="">Any</option>
            {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s[0]!.toUpperCase() + s.slice(1)}</option>)}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-caption text-ink-2">Target
          <Select value={targetId} onChange={(e) => setParam("target", e.target.value)} className="min-w-48">
            <option value="">Any</option>
            {(targets.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
        </label>
      </div>
      <Card className="overflow-hidden p-0 max-md:p-0">
        {fresh > 0 ? (
          <div className="flex justify-center border-b border-line py-2">
            <Button size="sm" variant="secondary" onClick={showAll}>
              Show {fresh} new {fresh === 1 ? "alert" : "alerts"}
            </Button>
          </div>
        ) : null}
        {q.isPending || shown === null ? (
          <div className="p-5"><LoadingRows /></div>
        ) : q.isError ? (
          <div className="p-5"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
        ) : shown.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={BellSlashIcon} title="No alerts.">This does not prove the service is healthy; it means no rule is currently breached.</EmptyState>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13.5px]">
              <thead className="chrome">
                <tr className="border-b border-line">
                  <th className="px-4 py-2.5 max-md:px-4">Severity</th>
                  <th className="px-4 py-2.5 max-md:px-4">Alert</th>
                  <th className="px-4 py-2.5 max-md:hidden">Observed</th>
                  <th className="px-4 py-2.5 max-md:hidden">Status</th>
                  <th className="px-4 py-2.5 max-md:px-4">Last seen</th>
                  <th className="px-4 py-2.5 max-lg:hidden"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((a) => (
                  <tr key={a.id} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2/60"
                    onClick={(e) => {
                      if (window.getSelection()?.toString() || (e.target as HTMLElement).closest("a,button")) return;
                      router.push(`/projects/${projectId}/alerts/${a.id}`);
                    }}>
                    <td className="px-4 py-2.5 max-md:px-4"><SeverityBadge severity={a.severity} emphasize={a.status === "firing"} /></td>
                    <td className="px-4 py-2.5 max-md:px-4">
                      <Link href={`/projects/${projectId}/alerts/${a.id}`} className="font-medium hover:underline">{a.rule_name}</Link>
                      <div className="text-caption text-ink-2">{a.target?.name ?? "Deleted target"}</div>
                    </td>
                    <td className="px-4 py-2.5 max-md:hidden">
                      {formatMetric(a.evidence.observed_value, METRIC_UNITS[a.evidence.query_name ?? ""] ?? "")}{" "}
                      <span className="text-ink-2">vs {formatMetric(a.evidence.threshold, METRIC_UNITS[a.evidence.query_name ?? ""] ?? "")}</span>
                    </td>
                    <td className="px-4 py-2.5 max-md:hidden">
                      <AlertStatusBadge status={a.status} />
                      {a.acknowledged_by && a.status === "acknowledged" ? (
                        <div className="text-caption text-ink-2">by {a.acknowledged_by.display_name}</div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 max-md:px-4"><TimeAgo iso={a.last_seen_at} /></td>
                    <td className="px-4 py-2.5 max-lg:hidden"><AlertActionButtons alert={a} projectId={projectId} archived={archived} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export default function AlertsPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <AlertsInner />
    </Suspense>
  );
}
