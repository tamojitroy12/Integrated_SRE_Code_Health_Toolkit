"use client";

import { AdjustmentsHorizontalIcon, MagnifyingGlassIcon, ShieldCheckIcon, XMarkIcon } from "@heroicons/react/20/solid";
import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { CodeHealthNav } from "@/components/project/code-health-nav";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/field";
import { TimeAgo } from "@/components/ui/misc";
import { Chip, SeverityBadge, StatusBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { formatTime, sentence, shortSha, providerName } from "@/lib/format";
import { useRecents } from "@/lib/hooks";
import { useProject, useProjectParam } from "@/lib/project";
import type { FindingSummary, Job, Overview, Page, Scan } from "@/lib/types";

const TYPES = ["dependency_vulnerability", "dependency_outdated", "dependency_incompatibility", "code_issue"];
const SECONDARY = ["type", "change", "package", "path"] as const;
const FIXABLE = new Set(["dependency_vulnerability", "dependency_outdated", "dependency_incompatibility"]);

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Explorer() {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  const { can } = useAuth();
  const toast = useToast();
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const [qText, setQText] = useState(get("q"));
  const debouncedQ = useDebounced(qText, 250);
  const [moreOpen, setMoreOpen] = useState(SECONDARY.some((k) => params.get(k)));
  const [searchFocus, setSearchFocus] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const recents = useRecents(`toolkit.findings.search.${projectId}`);

  const setParams = (next: Record<string, string>) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(next)) {
      if (v) sp.set(k, v);
      else sp.delete(k);
    }
    router.replace(`${path}?${sp.toString()}`);
  };
  useEffect(() => {
    if (debouncedQ !== get("q")) setParams({ q: debouncedQ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const filters = {
    q: get("q"), severity: get("severity"), status: get("status") || "open", type: get("type"),
    change: get("change"), package: get("package"), path: get("path"), scan_id: get("scan_id"),
    sort: get("sort") || "-severity",
  };
  const query = useInfiniteQuery({
    queryKey: ["findings", projectId, filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page<FindingSummary>>(`/projects/${projectId}/findings`, {
        query: {
          ...Object.fromEntries(Object.entries(filters).filter(([k]) => k !== "status")),
          status: filters.status === "all" ? undefined : filters.status,
          limit: 50,
          cursor: pageParam ?? undefined,
        },
      }),
    getNextPageParam: (last) => last.next_cursor,
  });
  const overview = useQuery({ queryKey: ["overview", projectId], queryFn: () => api<Overview>(`/projects/${projectId}/overview`) });
  const suggestions = useQuery({
    queryKey: ["suggest", projectId, debouncedQ],
    queryFn: () => api<{ packages: string[]; files: string[]; advisories: string[] }>(`/projects/${projectId}/findings/suggestions`, { query: { q: debouncedQ } }),
    enabled: searchFocus && debouncedQ.length > 0,
  });
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const total = query.data?.pages[0]?.total;
  const remediation = useQuery({
    queryKey: ["fix-proposals-flag", projectId],
    queryFn: () => api<{ remediation_enabled: boolean }>(`/projects/${projectId}/fix-proposals`, { query: { limit: 1 } }),
  });
  const propose = useMutation({
    mutationFn: () => api<{ proposal: { id: string }; job: Job }>(`/projects/${projectId}/fix-proposals`, { method: "POST", body: { finding_ids: [...selected] } }),
    onSuccess: (r) => router.push(`/projects/${projectId}/code-health/fix-proposals/${r.proposal.id}`),
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });

  const scanFilter = useQuery({
    queryKey: ["scan", filters.scan_id],
    queryFn: () => api<Scan>(`/scans/${filters.scan_id}`),
    enabled: !!filters.scan_id,
  });
  const chipLabel = (k: string, v: string): string => {
    if (k === "scan_id") {
      const s = scanFilter.data;
      return s ? `Scan: ${formatTime(s.created_at)}${s.commit_sha ? ` (${shortSha(s.commit_sha)})` : ""}` : "Scan: selected scan";
    }
    return `${sentence(k === "q" ? "search" : k)}: ${k === "type" ? sentence(v) : v}`;
  };
  const activeChips = Object.entries({ scan_id: filters.scan_id, severity: filters.severity, type: filters.type, change: filters.change, package: filters.package, path: filters.path, q: filters.q })
    .filter(([, v]) => v);
  const secondaryCount = SECONDARY.filter((k) => params.get(k)).length;
  const scanState = overview.data?.latest_scan;
  const canPropose = can("maintainer") && remediation.data?.remediation_enabled && !project.data?.archived_at;

  return (
    <>
      <PageHeader title="Code health" subtitle="Dependency and static-analysis findings from repository scans." />
      <CodeHealthNav projectId={projectId} />
      {scanState?.scan_status === "partial" ? (
        <div className="mb-4">
          <Banner>Results may be incomplete: {(scanState.providers ?? []).filter((p) => p.status === "failed").map((p) => providerName(p.name)).join(", ")} failed.</Banner>
        </div>
      ) : null}
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="relative w-full max-w-md">
          <label htmlFor="f-search" className="mb-1 block text-caption text-ink-2">Search</label>
          <MagnifyingGlassIcon className="pointer-events-none absolute bottom-2 left-2.5 size-4 text-ink-3" aria-hidden="true" />
          <Input id="f-search" value={qText} placeholder="Package, file path or advisory ID" autoComplete="off" className="pl-8"
            onChange={(e) => setQText(e.target.value)} onFocus={() => setSearchFocus(true)}
            onBlur={() => { setTimeout(() => setSearchFocus(false), 150); if (qText) recents.push(qText); }} />
          {searchFocus && (recents.items.length || suggestions.data) ? (
            <div className="pop-in absolute z-30 mt-1 w-full rounded-panel border border-line-strong bg-surface p-1 shadow-pop">
              {!qText && recents.items.length ? (
                <div className="flex items-center justify-between px-2 text-caption text-ink-2">Recent searches
                  <button type="button" className="chrome hit min-h-8 px-2 hover:text-ink" onMouseDown={(e) => { e.preventDefault(); recents.clear(); }}>Clear</button></div>
              ) : null}
              {(qText ? [...(suggestions.data?.packages ?? []), ...(suggestions.data?.files ?? []), ...(suggestions.data?.advisories ?? [])] : recents.items)
                .slice(0, 10).map((s) => (
                  <button key={s} type="button" className="chrome hit block w-full min-h-9 truncate rounded-control px-2 text-left text-[13.5px] hover:bg-surface-2"
                    onMouseDown={(e) => { e.preventDefault(); setQText(s); setParams({ q: s }); }}>
                    <span className="mono">{s}</span>
                  </button>
                ))}
            </div>
          ) : null}
        </div>
        <label className="flex flex-col gap-1 text-caption text-ink-2">Severity
          <Select value={filters.severity} onChange={(e) => setParams({ severity: e.target.value })} className="min-w-32">
            <option value="">Any</option>
            {["critical", "high", "medium", "low", "info", "unrated"].map((s) => <option key={s} value={s}>{sentence(s)}</option>)}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-caption text-ink-2">Status
          <Select value={filters.status} onChange={(e) => setParams({ status: e.target.value })} className="min-w-32">
            <option value="open">Open</option><option value="dismissed">Dismissed</option><option value="resolved">Resolved</option><option value="all">All</option>
          </Select>
        </label>
        <Button variant="secondary" icon={<AdjustmentsHorizontalIcon />} onClick={() => setMoreOpen(!moreOpen)} aria-expanded={moreOpen}>
          More filters{secondaryCount ? ` (${secondaryCount})` : ""}
        </Button>
      </div>
      {moreOpen ? (
        <div className="mb-3 flex flex-wrap items-end gap-3 rounded-panel border border-line bg-surface p-4 shadow-card">
          <label className="flex flex-col gap-1 text-caption text-ink-2">Type
            <Select value={filters.type} onChange={(e) => setParams({ type: e.target.value })}>
              <option value="">Any</option>
              {TYPES.map((t) => <option key={t} value={t}>{sentence(t)}</option>)}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-caption text-ink-2">Change
            <Select value={filters.change} onChange={(e) => setParams({ change: e.target.value })}>
              <option value="">Any</option><option value="new">New</option><option value="unchanged">Unchanged</option><option value="resolved">Resolved</option>
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-caption text-ink-2">Package (exact)
            <Input defaultValue={filters.package} onBlur={(e) => setParams({ package: e.target.value.trim() })} />
          </label>
          <label className="flex flex-col gap-1 text-caption text-ink-2">File path starts with
            <Input defaultValue={filters.path} onBlur={(e) => setParams({ path: e.target.value.trim() })} />
          </label>
        </div>
      ) : null}
      {activeChips.length ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {activeChips.map(([k, v]) => (
            <button key={k} type="button" onClick={() => { if (k === "q") setQText(""); setParams({ [k]: "" }); }}
              className="chrome hit inline-flex h-7 items-center gap-1.5 rounded-control border border-accent/[var(--tint-border)] bg-accent/[var(--tint)] pl-2.5 pr-1.5 text-[12.5px] font-medium text-accent hover:bg-accent/20">
              {chipLabel(k, v)}
              <XMarkIcon className="size-3.5" aria-label="Remove filter" />
            </button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => { setQText(""); router.replace(path); }}>Clear all</Button>
        </div>
      ) : null}
      {selected.size ? (
        <div className="pop-in sticky top-16 z-20 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-panel border border-primary/40 bg-surface px-4 py-2.5 shadow-pop lg:top-3">
          <span>{selected.size} finding{selected.size === 1 ? "" : "s"} selected for a fix proposal (max 20).</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setSelected(new Set())}>Clear selection</Button>
            <Button variant="primary" onClick={() => propose.mutate()} disabled={propose.isPending || selected.size > 20}>
              {propose.isPending ? "Creating…" : "Create fix proposal"}
            </Button>
          </div>
        </div>
      ) : null}
      <Card className="overflow-hidden p-0 max-md:p-0">
        {query.isPending ? <div className="p-5"><LoadingRows rows={6} /></div> : query.isError ? (
          <div className="p-5"><ErrorState error={query.error} onRetry={() => query.refetch()} /></div>
        ) : items.length === 0 ? (
          <div className="p-5">
            {activeChips.length ? (
              <EmptyState title="No findings match these filters." action={<Button variant="secondary" onClick={() => { setQText(""); router.replace(path); }}>Clear all filters</Button>} />
            ) : scanState?.status === "empty" ? (
              <EmptyState icon={ShieldCheckIcon} title="Run a scan to see findings." />
            ) : (
              <EmptyState icon={ShieldCheckIcon} title="No findings here.">Only {filters.status} findings are shown. Change the Status filter to see others.</EmptyState>
            )}
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-line px-4 py-2 text-caption text-ink-2">
              <span><span className="font-medium text-ink">{total ?? items.length}</span> findings</span>
              <label className="flex items-center gap-2">Sort
                <Select value={filters.sort} onChange={(e) => setParams({ sort: e.target.value })} className="h-7 w-auto text-[12.5px]">
                  <option value="-severity">Severity (highest first)</option>
                  <option value="-last_seen_at">Last seen (newest)</option>
                  <option value="-first_seen_at">First seen (newest)</option>
                  <option value="first_seen_at">First seen (oldest)</option>
                </Select>
              </label>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-[13.5px]">
                <thead className="chrome">
                  <tr className="border-b border-line">
                    {canPropose ? <th className="w-10 px-4 py-2.5"><span className="sr-only">Select</span></th> : null}
                    <th className="sticky left-0 bg-surface px-4 py-2.5">Finding</th>
                    <th className="px-4 py-2.5">Severity</th>
                    <th className="px-4 py-2.5">Type</th>
                    <th className="px-4 py-2.5">Sources</th>
                    <th className="px-4 py-2.5">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((f) => (
                    <tr key={f.id} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2/60"
                      onClick={(e) => {
                        if (window.getSelection()?.toString() || (e.target as HTMLElement).closest("a,button,input,label")) return;
                        router.push(`/projects/${projectId}/code-health/findings/${f.id}`);
                      }}>
                      {canPropose ? (
                        <td className="px-4 py-2.5">
                          {FIXABLE.has(f.type) && f.status === "open" ? (
                            <input type="checkbox" aria-label={`Select ${f.title}`} className="size-4 accent-[var(--primary)]"
                              checked={selected.has(f.id)} onChange={(e) => {
                                const next = new Set(selected);
                                if (e.target.checked) next.add(f.id);
                                else next.delete(f.id);
                                setSelected(next);
                              }} />
                          ) : null}
                        </td>
                      ) : null}
                      <td className="sticky left-0 max-w-[560px] bg-surface px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <Link href={`/projects/${projectId}/code-health/findings/${f.id}`} className="truncate font-medium hover:underline">{f.title}</Link>
                          {f.change === "new" ? <Chip>New</Chip> : null}
                          {f.status === "dismissed" ? <Chip>Dismissed</Chip> : null}
                          {f.status === "resolved" ? <StatusBadge tone="neutral">Resolved</StatusBadge> : null}
                        </div>
                        <div className="mono truncate text-caption text-ink-2">
                          {f.type === "code_issue" ? `${f.subject.file_path}:${f.subject.line_start}` : `${f.subject.ecosystem} ${f.subject.name}@${f.subject.version}`}
                        </div>
                      </td>
                      <td className="px-4 py-2.5"><SeverityBadge severity={f.severity} /></td>
                      <td className="px-4 py-2.5 text-ink-2">{sentence(f.type.replace("dependency_", ""))}</td>
                      <td className="px-4 py-2.5 text-ink-2">{f.sources.join(", ")}</td>
                      <td className="px-4 py-2.5 text-ink-2"><TimeAgo iso={f.last_seen_at} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {query.hasNextPage ? (
              <div className="flex justify-center p-4">
                <Button variant="ghost" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
                  {query.isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </Card>
    </>
  );
}

export default function FindingsPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <Explorer />
    </Suspense>
  );
}
