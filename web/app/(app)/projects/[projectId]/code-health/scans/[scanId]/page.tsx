"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/layout/shell";
import { JobProgress } from "@/components/project/job-progress";
import { Card, CardHeader, MetaList, PageHeader } from "@/components/ui/card";
import { Sha, TimeAgo } from "@/components/ui/misc";
import { JobStatusBadge, StatusBadge } from "@/components/ui/status-badge";
import { Banner, ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { formatDuration, formatTime, sentence, providerName, providerStatus } from "@/lib/format";
import { useProject } from "@/lib/project";
import type { Scan } from "@/lib/types";

export default function ScanDetailPage() {
  const { projectId, scanId } = useParams<{ projectId: string; scanId: string }>();
  const project = useProject(projectId);
  const q = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => api<Scan>(`/scans/${scanId}`),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 3000 : false),
  });
  const s = q.data;
  const failed = s?.providers.filter((p) => p.status === "failed") ?? [];
  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: project.data?.name ?? "Project", href: `/projects/${projectId}` },
        { label: "Scans", href: `/projects/${projectId}/code-health/scans` }, { label: s ? formatTime(s.created_at) : "Scan" }]} />
      {q.isPending ? <LoadingRows /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : s ? (
        <>
          <PageHeader title={<>Scan of <span className="mono text-[0.9em]">{s.ref}</span></>} meta={<div className="flex flex-wrap items-center gap-3"><JobStatusBadge status={s.status} /><span className="text-ink-2">Started <TimeAgo iso={s.created_at} /></span></div>} />
          {s.job && !["succeeded", "partial", "failed", "cancelled"].includes(s.status) ? <div className="mb-6"><JobProgress jobId={s.job.id} label="Scan" /></div> : null}
          {s.status === "partial" ? <div className="mb-6"><Banner>Results may be incomplete: {failed.map((p) => providerName(p.name)).join(", ")} failed. Findings from those providers were not marked resolved.</Banner></div> : null}
          {s.error ? <div className="mb-6"><ErrorState error={new Error(s.error.message)} hint={<span className="mono">{s.error.code}</span>} /></div> : null}
          <div className="grid grid-cols-[2fr_1fr] gap-5 max-xl:grid-cols-1">
            <Card>
              <CardHeader title="Receipt" />
              <MetaList items={[
                { label: "Ref", value: <span className="mono">{s.ref}</span> },
                { label: "Commit", value: <Sha sha={s.commit_sha} /> },
                { label: "Trigger", value: s.trigger },
                { label: "Finished", value: s.finished_at ? formatTime(s.finished_at) : "—" },
              ]} />
              <div className="mt-5 grid grid-cols-4 gap-3 max-md:grid-cols-2">
                {[["Dependencies", s.summary.dependencies], ["New", s.summary.new], ["Unchanged", s.summary.unchanged], ["Resolved", s.summary.resolved]].map(([label, v]) => (
                  <div key={String(label)} className="rounded-control border border-line bg-surface-2/40 px-4 py-3">
                    <div className="text-caption text-ink-2">{label}</div>
                    <div className="text-title font-semibold">{v ?? 0}</div>
                  </div>
                ))}
              </div>
              {s.summary.by_type_severity ? (
                <table className="mt-6 w-full text-left text-[13.5px]">
                  <thead className="text-caption text-ink-2"><tr><th className="py-2 font-medium">Type</th>{["critical", "high", "medium", "low", "info", "unrated"].map((k) => <th key={k} className="py-2 font-medium">{sentence(k)}</th>)}</tr></thead>
                  <tbody>
                    {Object.entries(s.summary.by_type_severity).map(([type, counts]) => (
                      <tr key={type} className="border-t border-line">
                        <td className="py-2"><Link href={`/projects/${projectId}/code-health?type=${type}&status=all&scan_id=${s.id}`} className="hover:underline">{sentence(type)}</Link></td>
                        {["critical", "high", "medium", "low", "info", "unrated"].map((k) => <td key={k} className="py-2">{counts[k] ?? 0}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              {s.summary.warnings?.length ? (
                <ul className="mt-6 list-disc pl-5 text-caption text-ink-2">{s.summary.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              ) : null}
            </Card>
            <Card>
              <CardHeader title="Providers" as="h3" />
              <ul className="flex flex-col gap-3">
                {s.providers.map((p) => (
                  <li key={p.name} className="rounded-control border border-line bg-surface-2/40 px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{providerName(p.name)}</span>
                      <StatusBadge tone={p.status === "ok" ? "healthy" : p.status === "failed" ? "critical" : "neutral"}>{providerStatus(p.status)}</StatusBadge>
                    </div>
                    <div className="mt-1 text-caption text-ink-2">{formatDuration(p.duration_ms / 1000)}{p.tool_version ? `, version ${p.tool_version}` : ""}</div>
                    {p.db_info?.updated_at ? <div className="text-caption text-ink-2">Vulnerability DB updated {formatTime(p.db_info.updated_at)}</div> : null}
                    {p.error ? <div className="mt-1 text-caption text-crit">{p.error}</div> : null}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      ) : null}
    </>
  );
}
