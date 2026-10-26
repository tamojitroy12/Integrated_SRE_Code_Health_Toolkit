"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { JobStatusBadge } from "@/components/ui/status-badge";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDuration, sentence } from "@/lib/format";
import { TERMINAL, useJob } from "@/lib/hooks";

/** Inline progress row shown immediately after a 202; stage name + elapsed time, never a fake %. */
export function JobProgress({ jobId, label, onDone }: { jobId: string; label: string; onDone?: () => void }) {
  const { can } = useAuth();
  const job = useJob(jobId);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const confirm = useConfirm();
  const toast = useToast();
  const cancel = useMutation({
    mutationFn: () => api(`/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => toast.show(`${label} cancellation requested.`),
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const data = job.data;
  const terminal = !!data && TERMINAL.has(data.status);
  const started = data?.started_at ?? data?.created_at;
  const elapsed = started ? ((data?.finished_at ? new Date(data.finished_at).getTime() : now) - new Date(started).getTime()) / 1000 : 0;
  return (
    <div role="status" className="relative flex flex-wrap items-center justify-between gap-3 overflow-hidden rounded-panel border border-line bg-surface px-4 py-3 shadow-card">
      {!terminal ? <span aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-primary" /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{label}</span>
        <JobStatusBadge status={data?.status ?? "queued"} />
        {!terminal ? (
          <span className="text-ink-2">
            {data?.stage ? sentence(data.stage) : "Waiting for a worker"} · {formatDuration(Math.max(0, elapsed))}
          </span>
        ) : data?.error ? (
          <span className="text-ink-2"><span className="mono">{data.error.code}</span> {data.error.message}</span>
        ) : (
          <span className="text-ink-2">Finished in {formatDuration(Math.max(0, elapsed))}</span>
        )}
      </div>
      <div className="flex gap-2">
        {!terminal && can("maintainer") ? (
          <Button size="sm" variant="ghost" onClick={async () => {
            if (await confirm({ title: `Cancel this ${label.toLowerCase()}?`, confirmLabel: `Cancel ${label.toLowerCase()}`, cancelLabel: "Keep running", destructive: true,
              body: <p>Work already done is discarded. You can start it again later.</p> })) cancel.mutate();
          }} disabled={cancel.isPending || data?.cancel_requested}>
            {data?.cancel_requested ? "Cancelling…" : "Cancel"}
          </Button>
        ) : null}
        {terminal && onDone ? <Button size="sm" variant="ghost" onClick={onDone}>Dismiss</Button> : null}
      </div>
    </div>
  );
}
