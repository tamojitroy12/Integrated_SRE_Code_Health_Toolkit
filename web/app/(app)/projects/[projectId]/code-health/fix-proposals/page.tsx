"use client";

import { WrenchScrewdriverIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { CodeHealthNav } from "@/components/project/code-health-nav";
import { Card, PageHeader } from "@/components/ui/card";
import { TimeAgo } from "@/components/ui/misc";
import { ResultBadge, StatusBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { sentence } from "@/lib/format";
import { useProjectParam } from "@/lib/project";
import type { FixProposal } from "@/lib/types";

export default function FixProposalsPage() {
  const projectId = useProjectParam();
  const q = useQuery({
    queryKey: ["fix-proposals", projectId],
    queryFn: () => api<{ items: FixProposal[]; remediation_enabled: boolean }>(`/projects/${projectId}/fix-proposals`),
    refetchInterval: (query) => (query.state.data?.items.some((p) => ["pending", "validating", "approved"].includes(p.status)) ? 3000 : 30_000),
  });
  return (
    <>
      <PageHeader title="Code health" subtitle="Dependency fixes are planned deterministically, validated in an isolated sandbox, and delivered as draft PRs after approval." />
      <CodeHealthNav projectId={projectId} />
      {q.data && !q.data.remediation_enabled ? (
        <div className="mb-6"><Banner tone="info">Automated fixes are turned off in this deployment, so new proposals cannot be created. An administrator can enable them with <span className="mono">REMEDIATION_ENABLED</span>. Existing proposals stay readable.</Banner></div>
      ) : null}
      <Card className="overflow-hidden p-0 max-md:p-0">
        {q.isPending ? <div className="p-5"><LoadingRows /></div> : q.isError ? <div className="p-5"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div> :
          q.data.items.length === 0 ? (
            <div className="p-5"><EmptyState icon={WrenchScrewdriverIcon} title="No fix proposals.">Select dependency findings in the explorer and choose Create fix proposal.</EmptyState></div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-[13.5px]">
                <thead className="chrome">
                  <tr className="border-b border-line">
                    <th className="sticky left-0 bg-surface px-4 py-2.5">Packages</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Validation</th>
                    <th className="px-4 py-2.5">Pull request</th>
                    <th className="px-4 py-2.5">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((p) => (
                    <tr key={p.id} className="border-b border-line last:border-0">
                      <td className="sticky left-0 bg-surface px-4 py-2.5">
                        <Link href={`/projects/${projectId}/code-health/fix-proposals/${p.id}`} className="font-medium hover:underline">
                          {p.changes.length ? p.changes.map((c) => `${c.package} ${c.from_version} → ${c.to_version}`).join(", ") : "Planning…"}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5"><StatusBadge tone={p.status === "failed" ? "critical" : p.status === "pr_opened" ? "healthy" : "neutral"}>{sentence(p.status)}</StatusBadge></td>
                      <td className="px-4 py-2.5"><ResultBadge result={p.validation.result} /></td>
                      <td className="px-4 py-2.5">{p.pull_request ? <a href={p.pull_request.url} target="_blank" rel="noopener noreferrer" className="text-accent">#{p.pull_request.number}</a> : <span className="text-ink-2">—</span>}</td>
                      <td className="px-4 py-2.5 text-ink-2"><TimeAgo iso={p.created_at} /></td>
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
