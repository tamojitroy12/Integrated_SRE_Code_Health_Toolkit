"use client";

import { SparklesIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { JobProgress } from "@/components/project/job-progress";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/field";
import { CodeBlock, Disclosure } from "@/components/ui/misc";
import { Chip, StatusBadge, ValidationBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatTime, sentence } from "@/lib/format";
import { usePreference } from "@/lib/hooks";
import type { FindingDetail, Job, Recommendation, RecommendationKind } from "@/lib/types";

const KINDS: Record<string, RecommendationKind[]> = {
  dependency_vulnerability: ["upgrade_guidance", "library_alternative"],
  dependency_outdated: ["upgrade_guidance", "library_alternative"],
  dependency_incompatibility: ["upgrade_guidance", "library_alternative"],
  code_issue: ["code_improvement"],
};

function EvidenceChips({ refs, rec }: { refs: string[]; rec: Recommendation }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {refs.map((r) => {
        const ev = rec.evidence.find((e) => e.id === r);
        const label = ev ? `${r} ${ev.source}` : r;
        return ev?.url ? (
          <a key={r} href={ev.url} target="_blank" rel="noopener noreferrer"
            title={`${ev.kind}, retrieved ${ev.retrieved_at ? formatTime(ev.retrieved_at) : "n/a"}`}
            className="chrome rounded-full border border-line bg-surface-2 px-2 text-caption font-medium text-accent hover:bg-accent/10">
            {label}
          </a>
        ) : (
          <Chip key={r}>{label}</Chip>
        );
      })}
    </span>
  );
}

function RecommendationView({ rec, canDebug }: { rec: Recommendation; canDebug: boolean }) {
  const qc = useQueryClient();
  const feedback = useMutation({
    mutationFn: (rating: "helpful" | "not_helpful") => api(`/recommendations/${rec.id}/feedback`, { method: "POST", body: { rating } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recommendations", rec.finding_id] }),
  });
  if (rec.status === "pending") return rec.job ? <JobProgress jobId={rec.job.id} label="AI recommendation" /> : <LoadingRows rows={3} />;
  if (rec.status === "failed") {
    return <ErrorState error={new Error(rec.error?.message ?? "The AI job failed.")} title="AI unavailable" hint={<span className="mono">{rec.error?.code}</span>} />;
  }
  const supported = rec.claims.filter((c) => c.validation !== "unsupported");
  const unsupported = rec.claims.filter((c) => c.validation === "unsupported");
  if (rec.validation_status === "rejected") {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2"><ValidationBadge status="rejected" /><Chip>{rec.label}</Chip></div>
        <p>AI output could not be validated, so it is not shown as advice.</p>
        <Disclosure summary="Rejected output" count={rec.claims.length}>
          <ul className="flex flex-col gap-2 text-[13.5px]">
            {rec.claims.map((c) => <li key={c.claim_id}><span className="text-ink-2">{c.validation_note}</span> {c.text}</li>)}
          </ul>
          {canDebug && rec.raw_output ? <CodeBlock className="mt-3" label="Raw model output">{rec.raw_output}</CodeBlock> : null}
        </Disclosure>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <ValidationBadge status={rec.validation_status} />
        <Chip>{rec.label}</Chip>
        <span className="text-caption text-ink-2" title="Qualitative statement from the model, capped by validation. Not a probability.">
          Confidence: {rec.confidence ?? "not shown"} (not a probability)
        </span>
      </div>
      {rec.summary ? <p className="max-w-[72ch]">{rec.summary}</p> : null}
      <ul className="flex flex-col gap-3">
        {supported.map((c) => (
          <li key={c.claim_id} className="rounded-control border border-line bg-surface-2/40 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={c.validation === "supported" ? "healthy" : "neutral"}>{c.kind === "judgment" ? "Judgment" : "Verified"}</StatusBadge>
              <span>{c.text}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-caption text-ink-2">
              <EvidenceChips refs={c.evidence_refs} rec={rec} />
              <span>{c.validation_note}</span>
            </div>
          </li>
        ))}
      </ul>
      {unsupported.length ? (
        <Disclosure summary="Show unsupported claims" count={unsupported.length}>
          <ul className="flex flex-col gap-2 text-[13.5px] text-ink-2">
            {unsupported.map((c) => <li key={c.claim_id}>{c.text} <span className="text-crit">({c.validation_note})</span></li>)}
          </ul>
        </Disclosure>
      ) : null}
      {rec.alternatives.length ? (
        <div>
          <h4 className="mb-2 text-[13.5px] font-semibold">Alternatives (registry-verified facts)</h4>
          <ul className="flex flex-col gap-2">
            {rec.alternatives.map((a) => (
              <li key={a.name} className="rounded-control border border-line px-4 py-3 text-[13.5px]">
                <div className="font-semibold"><span className="mono">{a.name}</span> <span className="text-ink-2">({a.ecosystem})</span></div>
                <p className="mt-1">{a.rationale}</p>
                <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-2">
                  {(["latest_version", "latest_released_at", "first_released_at", "license", "deprecated"] as const).map((k) => (
                    <div key={k}><dt className="inline">{sentence(k)}: </dt><dd className="inline text-ink">{String(a.criteria[k] ?? "unknown")}</dd></div>
                  ))}
                </dl>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {rec.suggested_steps.length ? (
        <div>
          <h4 className="mb-2 text-[13.5px] font-semibold">Suggested steps</h4>
          <ol className="list-decimal pl-5">{rec.suggested_steps.map((s) => <li key={s}>{s}</li>)}</ol>
        </div>
      ) : null}
      {rec.proposed_patch ? (
        <Disclosure summary="Proposed patch (display only; applies cleanly to the scanned commit)">
          <CodeBlock label="Proposed patch">{rec.proposed_patch}</CodeBlock>
        </Disclosure>
      ) : null}
      <div>
        <h4 className="mb-2 text-[13.5px] font-semibold">Limitations</h4>
        <ul className="list-disc pl-5 text-ink-2">{rec.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-caption text-ink-2">
        Model <span className="mono">{rec.model}</span>
        {rec.feedback ? <span>Rated {rec.feedback.rating.replace("_", " ")}.</span> : (
          <>
            <Button size="sm" variant="ghost" onClick={() => feedback.mutate("helpful")}>Helpful</Button>
            <Button size="sm" variant="ghost" onClick={() => feedback.mutate("not_helpful")}>Not helpful</Button>
          </>
        )}
      </div>
    </div>
  );
}

export function RecommendationPanel({ finding, archived }: { finding: FindingDetail; archived: boolean }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const kinds = KINDS[finding.type] ?? [];
  const [kind, setKind] = useState<RecommendationKind>(kinds[0] ?? "upgrade_guidance");
  const [noticeSeen, setNoticeSeen] = usePreference("toolkit.ai.notice", false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => api<{ enabled: boolean; notice: string }>("/ai/status"), staleTime: 60_000 });
  const recs = useQuery({
    queryKey: ["recommendations", finding.id],
    queryFn: () => api<{ items: Recommendation[] }>(`/findings/${finding.id}/recommendations`),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "pending") ? 3000 : false),
  });
  const request = useMutation({
    mutationFn: () => api<{ job: Job }>(`/findings/${finding.id}/recommendations`, { method: "POST", body: { kind } }),
    onSuccess: () => {
      toast.show("Recommendation requested. It appears here once it has been generated and checked.", { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["recommendations", finding.id] });
    },
  });
  const start = () => {
    if (!noticeSeen) setNoticeOpen(true);
    else request.mutate();
  };
  const latest = recs.data?.items[0];
  return (
    <Card>
      <CardHeader title="AI recommendation" subtitle="Advice grounded in this finding's stored evidence; every claim is checked before it is shown."
        action={can("maintainer") && !archived && status.data?.enabled ? (
          <div className="flex flex-wrap items-center gap-2">
            {kinds.length > 1 ? (
              <Select aria-label="Recommendation kind" value={kind} onChange={(e) => setKind(e.target.value as RecommendationKind)} className="w-auto">
                {kinds.map((k) => <option key={k} value={k}>{sentence(k)}</option>)}
              </Select>
            ) : null}
            <Button variant="primary" icon={<SparklesIcon />} onClick={start} disabled={request.isPending || latest?.status === "pending"}>Request</Button>
          </div>
        ) : null} />
      {request.isError ? <ErrorState error={request.error} title="AI unavailable" /> : null}
      {recs.isPending ? <LoadingRows rows={3} /> : recs.isError ? <ErrorState error={recs.error} onRetry={() => recs.refetch()} /> :
        latest ? <RecommendationView rec={latest} canDebug={can("maintainer")} />
          : status.data && !status.data.enabled ? (
            <Banner tone="info">AI recommendations are turned off in this deployment. An administrator can enable them by setting <span className="mono">AI_ENABLED</span> and an Anthropic API key.</Banner>
          ) : (
            <EmptyState icon={SparklesIcon} title="No recommendation yet.">
              {can("maintainer") && !archived ? "Choose Request to get evidence-grounded upgrade or fix guidance." : "A maintainer can request one."}
            </EmptyState>
          )}
      <Dialog open={noticeOpen} onClose={() => setNoticeOpen(false)} title="Before you send evidence to the AI"
        footer={<>
          <Button variant="secondary" data-dialog-cancel onClick={() => setNoticeOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => { setNoticeSeen(true); setNoticeOpen(false); request.mutate(); }}>Send and request</Button>
        </>}>
        <p>{status.data?.notice ?? "The finding's evidence, including a short code snippet where relevant, is sent to Anthropic's API."}</p>
        <p className="mt-2 text-ink-2">Secrets are redacted first; snippets are omitted when redaction is uncertain.</p>
      </Dialog>
    </Card>
  );
}
