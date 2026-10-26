"use client";

import { PlayIcon, ShieldCheckIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { CodeHealthNav } from "@/components/project/code-health-nav";
import { JobProgress } from "@/components/project/job-progress";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/field";
import { Sha, TimeAgo } from "@/components/ui/misc";
import { JobStatusBadge, StatusBadge } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { providerName } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useProject, useProjectParam } from "@/lib/project";
import type { Job, Page, Repository, Scan } from "@/lib/types";

export default function ScansPage() {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [ref, setRef] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const repo = useQuery({ queryKey: ["repository", projectId], queryFn: () => api<Repository>(`/projects/${projectId}/repository`).catch(() => null) });
  const scans = useQuery({
    queryKey: ["scans", projectId],
    queryFn: () => api<Page<Scan>>(`/projects/${projectId}/scans`, { query: { limit: 20 } }),
    refetchInterval: (q) => (q.state.data?.items.some((s) => s.status === "queued" || s.status === "running") ? 3000 : 30_000),
  });
  const start = useMutation({
    mutationFn: () => api<{ job: Job }>(`/projects/${projectId}/scans`, { method: "POST", body: ref.trim() ? { ref: ref.trim() } : {} }),
    onSuccess: (r) => {
      setJobId(r.job.id);
      toast.show("Scan started.", { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["scans", projectId] });
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const running = scans.data?.items.some((s) => s.status === "queued" || s.status === "running");
  const writable = can("maintainer") && !project.data?.archived_at && !!repo.data;
  return (
    <>
      <PageHeader title="Code health" subtitle="Each scan clones the repository at a ref, then runs Trivy, OSV, registry checks and Semgrep." />
      <CodeHealthNav projectId={projectId} />
      {writable ? (
        <Card className="mb-6">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex w-full max-w-xs flex-col gap-1.5 text-[13px] font-medium">Branch, tag or commit
              <Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder={repo.data?.default_branch ?? "main"} />
            </label>
            <Button variant="primary" icon={<PlayIcon />} onClick={() => start.mutate()} softDisabled={running || start.isPending}
              title={running ? "A scan is already running" : undefined}>Start scan</Button>
            {running ? <span className="text-caption text-ink-2">A scan is already running.</span> : null}
          </div>
          {jobId ? <div className="mt-4"><JobProgress jobId={jobId} label="Scan" onDone={() => setJobId(null)} /></div> : null}
        </Card>
      ) : null}
      <Card className="overflow-hidden p-0 max-md:p-0">
        {scans.isPending ? <div className="p-5"><LoadingRows /></div> : scans.isError ? <div className="p-5"><ErrorState error={scans.error} onRetry={() => scans.refetch()} /></div> :
          scans.data.items.length === 0 ? (
            <div className="p-5"><EmptyState icon={ShieldCheckIcon} title={repo.data ? "No scan yet." : "No repository connected."}>{repo.data ? "Run the first scan." : "Connect a repository in project settings."}</EmptyState></div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-[13.5px]">
                <thead className="chrome">
                  <tr className="border-b border-line">
                    <th className="sticky left-0 bg-surface px-4 py-2.5">Started</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Ref</th>
                    <th className="px-4 py-2.5">Commit</th>
                    <th className="px-4 py-2.5">Providers</th>
                    <th className="px-4 py-2.5">Changes</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.data.items.map((s) => (
                    <tr key={s.id} className="border-b border-line last:border-0">
                      <td className="sticky left-0 bg-surface px-4 py-2.5">
                        <Link href={`/projects/${projectId}/code-health/scans/${s.id}`} className="font-medium hover:underline"><TimeAgo iso={s.created_at} /></Link>
                        <div className="text-caption text-ink-2">{s.trigger}</div>
                      </td>
                      <td className="px-4 py-2.5"><JobStatusBadge status={s.status} />{s.job?.stage && s.status === "running" ? <div className="text-caption text-ink-2">{s.job.stage}</div> : null}</td>
                      <td className="mono px-4 py-2.5">{s.ref}</td>
                      <td className="px-4 py-2.5"><Sha sha={s.commit_sha} /></td>
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {s.providers.map((p) => <StatusBadge key={p.name} tone={p.status === "ok" ? "healthy" : p.status === "failed" ? "critical" : "neutral"}>{providerName(p.name)}</StatusBadge>)}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-ink-2">{s.summary.new ?? 0} new, {s.summary.resolved ?? 0} resolved</td>
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
