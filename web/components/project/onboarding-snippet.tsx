"use client";

import { EyeIcon, EyeSlashIcon, KeyIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { CodeBlock, CopyButton, Disclosure } from "@/components/ui/misc";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Onboarding } from "@/lib/types";

const SECRET = /^(Authorization=Bearer%20)(.{8,})$/;

/** OpenTelemetry environment for a target. The ingest token is masked on screen; copy copies the real value. */
export function OnboardingSnippet({ targetId }: { targetId: string }) {
  const [reveal, setReveal] = useState(false);
  const q = useQuery({ queryKey: ["onboarding", targetId], queryFn: () => api<Onboarding>(`/monitoring-targets/${targetId}/onboarding`) });
  if (q.isPending) return <LoadingBlock height="h-48" label="Loading instructions" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const entries = Object.entries(q.data.env);
  const text = entries.map(([k, v]) => `${k}=${v}`).join("\n");
  const hasSecret = entries.some(([, v]) => SECRET.test(v) && !v.includes("<"));
  const shown = entries
    .map(([k, v]) => `${k}=${reveal ? v : v.replace(SECRET, (_m, prefix: string, token: string) => `${prefix}${"•".repeat(Math.min(24, token.length))}`)}`)
    .join("\n");
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-hidden rounded-panel border border-line">
        <div className="flex items-center justify-between gap-2 border-b border-line bg-surface-2/60 py-1 pl-3.5 pr-1">
          <span className="text-caption font-medium text-ink-2">Environment variables</span>
          <span className="flex items-center gap-0.5">
            {hasSecret ? (
              <button type="button" onClick={() => setReveal(!reveal)} aria-pressed={reveal}
                className="chrome hit inline-flex h-7 items-center gap-1.5 rounded-control px-2 text-[12px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink">
                {reveal ? <EyeSlashIcon className="size-3.5" aria-hidden="true" /> : <EyeIcon className="size-3.5" aria-hidden="true" />}
                {reveal ? "Hide token" : "Show token"}
              </button>
            ) : null}
            <CopyButton text={text} label="Copy environment variables" />
          </span>
        </div>
        <CodeBlock label="Environment variables" className="rounded-none border-0">{shown}</CodeBlock>
      </div>
      <p className="text-[13px] text-ink-2">
        The service must emit the <span className="mono text-ink">{q.data.required_metric}</span> metric; most HTTP
        instrumentations do this automatically.
      </p>
      {hasSecret ? (
        <div className="flex gap-2.5 rounded-panel border border-warn/[var(--tint-border)] bg-warn/[var(--tint)] px-3.5 py-2.5 text-[13px]">
          <KeyIcon className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
          <span>{q.data.token_note} Store it in your secret manager, not in source control.</span>
        </div>
      ) : (
        <p className="text-caption text-ink-2">{q.data.token_note}</p>
      )}
      <Disclosure summary="Troubleshooting" count={q.data.notes.length + 4}>
        <ul className="flex list-disc flex-col gap-1 pl-5 text-[13px] text-ink-2">
          {q.data.notes.map((n) => <li key={n}>{n}</li>)}
          <li>The service reads these variables at start-up, so restart it after changing them.</li>
          <li><span className="mono">OTEL_SERVICE_NAME</span> must exactly match the service name registered here.</li>
          <li>The service must be able to reach the OTLP endpoint (port 4318) from where it runs.</li>
          <li>The Authorization header uses the current ingest token, with <span className="mono">%20</span> between Bearer and the token.</li>
        </ul>
      </Disclosure>
    </div>
  );
}
