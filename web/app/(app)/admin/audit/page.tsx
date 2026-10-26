"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api";
import { bothZones, formatTime, sentence } from "@/lib/format";
import type { AuditEntry, Page } from "@/lib/types";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const q = useInfiniteQuery({
    queryKey: ["audit", action],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api<Page<AuditEntry>>("/audit-log", { query: { action: action || undefined, limit: 50, cursor: pageParam ?? undefined } }),
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Card>
      <CardHeader title="Audit log" subtitle="Append-only record of security-relevant actions." />
      <div className="mb-4 max-w-xs">
        <Input aria-label="Filter by action prefix" placeholder="Action prefix, e.g. auth. or fix." value={action} onChange={(e) => setAction(e.target.value.trim())} />
      </div>
      {q.isPending ? <LoadingRows /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : items.length === 0 ? <EmptyState title={action ? "No entries match this prefix." : "No entries."} /> : (
        <div className="scroll-thin -mx-5 overflow-x-auto border-t border-line max-md:-mx-4">
          <table className="w-full min-w-[720px] text-left text-[13.5px]">
            <thead className="chrome"><tr className="border-b border-line">
              <th className="px-4 py-2.5">Time</th><th className="px-4 py-2.5">Action</th>
              <th className="px-4 py-2.5">Actor</th><th className="px-4 py-2.5">Resource</th><th className="px-4 py-2.5">Details</th></tr></thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-line align-top last:border-0">
                  <td className="whitespace-nowrap px-4 py-2.5" title={bothZones(e.created_at)}>{formatTime(e.created_at, "local", true)}</td>
                  <td className="mono px-4 py-2.5">{e.action}</td>
                  <td className="px-4 py-2.5">{e.actor?.display_name ?? <span className="text-ink-2">system</span>}</td>
                  <td className="px-4 py-2.5 text-caption" title={e.resource_id ?? undefined}>{e.resource_type ? <>{sentence(e.resource_type)}{typeof e.metadata.name === "string" ? <span className="text-ink-2"> · {e.metadata.name}</span> : null}</> : <span className="text-ink-3">—</span>}</td>
                  <td className="mono max-w-md truncate px-4 py-2.5 text-caption text-ink-2" title={JSON.stringify(e.metadata)}>{Object.keys(e.metadata).length ? JSON.stringify(e.metadata) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.hasNextPage ? <div className="mt-4 flex justify-center"><Button variant="ghost" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>Load more</Button></div> : null}
    </Card>
  );
}
