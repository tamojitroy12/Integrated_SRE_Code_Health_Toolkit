"use client";

import { FolderPlusIcon, MagnifyingGlassIcon, PlusIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ButtonLink } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/field";
import { SegmentedControl, TimeAgo } from "@/components/ui/misc";
import { Chip, JobStatusBadge, StatusBadge } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { plural } from "@/lib/format";
import type { Page, Project } from "@/lib/types";

function AlertsCell({ p }: { p: Project }) {
  const unack = p.health?.unacknowledged_alerts ?? 0;
  const open = p.health?.open_alerts ?? 0;
  if (unack > 0) return <StatusBadge tone="critical">{plural(unack, "firing alert")}</StatusBadge>;
  if (open > 0) return <StatusBadge tone="warning">{plural(open, "open alert")}</StatusBadge>;
  return <span className="text-ink-3">None</span>;
}

export default function ProjectsPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState<"active" | "all">("active");
  const query = useQuery({
    queryKey: ["projects", q, archived],
    queryFn: () => api<Page<Project>>("/projects", { query: { q, include_archived: archived === "all", limit: 100 } }),
  });
  const items = query.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Each project pairs a GitHub repository with the services it runs."
        actions={can("maintainer") ? (
          <ButtonLink href="/projects/new" variant="primary" icon={<PlusIcon />}>New project</ButtonLink>
        ) : null}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <MagnifyingGlassIcon className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden="true" />
          <Input aria-label="Filter projects" placeholder="Filter by name" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
        </div>
        <SegmentedControl label="Archived projects" value={archived} onChange={setArchived}
          options={[{ value: "active", label: "Active" }, { value: "all", label: "Include archived" }]} />
        {query.data ? <span className="ml-auto text-caption text-ink-2">{plural(query.data.total ?? items.length, "project")}</span> : null}
      </div>
      {query.isPending ? (
        <div className="overflow-hidden rounded-panel border border-line bg-surface" role="status" aria-label="Loading projects">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-line px-4 py-3.5 last:border-0">
              <Skeleton className="h-4 w-48" /><Skeleton className="h-4 flex-1" /><Skeleton className="h-4 w-24" />
            </div>
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={FolderPlusIcon}
          title={q ? "No projects match this filter." : "No projects yet"}
          action={can("maintainer") && !q ? <ButtonLink href="/projects/new" variant="primary" icon={<PlusIcon />}>Create the first project</ButtonLink> : null}
        >
          {q ? "Try a different name, or include archived projects." : "Create a project, then connect a repository and register a running service."}
        </EmptyState>
      ) : (
        <div className="overflow-hidden rounded-panel border border-line bg-surface shadow-card">
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b border-line">
                  <th className="px-4 py-2.5">Project</th>
                  <th className="px-4 py-2.5">Alerts</th>
                  <th className="px-4 py-2.5">Last scan</th>
                  <th className="px-4 py-2.5">Repository</th>
                  <th className="px-4 py-2.5">Targets</th>
                  <th className="px-4 py-2.5 text-right">Updated</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2/60"
                    onClick={(e) => {
                      if (window.getSelection()?.toString() || (e.target as HTMLElement).closest("a,button")) return;
                      router.push(`/projects/${p.id}`);
                    }}>
                    <td className="max-w-[360px] px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-control border border-line bg-surface-2 text-[12px] font-semibold text-ink-2">
                          {p.name.slice(0, 1).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Link href={`/projects/${p.id}`} className="truncate font-medium hover:underline">{p.name}</Link>
                            {p.archived_at ? <Chip>Archived</Chip> : null}
                          </div>
                          {p.description ? <div className="truncate text-caption text-ink-2">{p.description}</div> : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[13px]"><AlertsCell p={p} /></td>
                    <td className="px-4 py-3 text-[13px]">
                      <div className="flex items-center gap-2">
                        {p.health?.last_scan_status ? <JobStatusBadge status={p.health.last_scan_status} /> : <span className="text-ink-3">Never</span>}
                        {p.health?.last_scan_at ? <span className="text-ink-2"><TimeAgo iso={p.health.last_scan_at} /></span> : null}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[13px] text-ink-2">{p.health?.has_repository ? "Connected" : "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-ink-2">{p.health?.target_count ? plural(p.health.target_count, "target") : "—"}</td>
                    <td className="px-4 py-3 text-right text-[13px] text-ink-2"><TimeAgo iso={p.updated_at} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
