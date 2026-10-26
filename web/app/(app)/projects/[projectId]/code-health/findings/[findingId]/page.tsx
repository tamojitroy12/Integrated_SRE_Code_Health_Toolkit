"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { RecommendationPanel } from "@/components/findings/recommendation-panel";
import { Breadcrumbs } from "@/components/layout/shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, MetaList, PageHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/field";
import { CodeBlock, Disclosure, Sha, TimeAgo } from "@/components/ui/misc";
import { Chip, ResultBadge, SeverityBadge, StatusBadge } from "@/components/ui/status-badge";
import { Banner, EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatTime, sentence } from "@/lib/format";
import { useProject } from "@/lib/project";
import type { EvidenceItem, FindingDetail, Job } from "@/lib/types";

function EvidenceView({ ev }: { ev: EvidenceItem }) {
  const c = ev.content as Record<string, unknown>;
  if (ev.kind === "code_snippet") {
    return (
      <div>
        <p className="mb-2 text-caption text-ink-2"><span className="mono">{String(c.path)}</span> lines {String(c.line_start)}–{String(c.line_end)}{c.redactions ? `, ${String(c.redactions)} secret(s) redacted` : ""}</p>
        <CodeBlock label="Code snippet">{String(c.snippet ?? "")}</CodeBlock>
      </div>
    );
  }
  if (ev.kind === "advisory_record") {
    return (
      <div className="flex flex-col gap-2 text-[13.5px]">
        <p className="font-semibold"><span className="mono">{String(c.id)}</span> {c.summary ? `— ${String(c.summary)}` : ""}</p>
        {Array.isArray(c.aliases) && c.aliases.length ? <p className="text-ink-2">Aliases: <span className="mono">{(c.aliases as string[]).join(", ")}</span></p> : null}
        {Array.isArray(c.fixed_versions) ? <p>Fixed in: <span className="mono">{(c.fixed_versions as string[]).join(", ") || "no fixed version published"}</span></p> : null}
        {c.details ? <Disclosure summary="Advisory details"><p className="whitespace-pre-wrap text-ink-2">{String(c.details)}</p></Disclosure> : null}
      </div>
    );
  }
  return <CodeBlock label={ev.kind}>{JSON.stringify(c, null, 2)}</CodeBlock>;
}

export default function FindingDetailPage() {
  const { projectId, findingId } = useParams<{ projectId: string; findingId: string }>();
  const project = useProject(projectId);
  const router = useRouter();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [dismissOpen, setDismissOpen] = useState(false);
  const [reason, setReason] = useState("false_positive");
  const [note, setNote] = useState("");
  const q = useQuery({ queryKey: ["finding", findingId], queryFn: () => api<FindingDetail>(`/findings/${findingId}`) });
  const triage = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<FindingDetail>(`/findings/${findingId}`, { method: "PATCH", body }),
    onSuccess: (f, body) => {
      qc.setQueryData(["finding", findingId], f);
      void qc.invalidateQueries({ queryKey: ["findings", projectId] });
      if (body.status === "dismissed") {
        toast.show("Finding dismissed. It stays dismissed in future scans.", { tone: "success", undo: () => triage.mutate({ status: "open" }) });
      } else if (body.status === "open") {
        toast.show("Finding reopened.", { tone: "success" });
      }
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const propose = useMutation({
    mutationFn: () => api<{ proposal: { id: string }; job: Job }>(`/projects/${projectId}/fix-proposals`, { method: "POST", body: { finding_ids: [findingId] } }),
    onSuccess: (r) => {
      toast.show("Fix proposal created. Sandbox validation has started.", { tone: "success" });
      router.push(`/projects/${projectId}/code-health/fix-proposals/${r.proposal.id}`);
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const f = q.data;
  const archived = !!project.data?.archived_at;
  const writable = can("maintainer") && !archived;
  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: project.data?.name ?? "Project", href: `/projects/${projectId}` },
        { label: "Code health", href: `/projects/${projectId}/code-health` }, { label: f?.title ?? "Finding" }]} />
      {q.isPending ? <LoadingRows rows={6} /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : f ? (
        <>
          <PageHeader
            title={<span className="break-words text-[20px]">{f.title}</span>}
            meta={
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={f.severity} emphasize />
                <StatusBadge tone={f.status === "open" ? "info" : "neutral"}>{sentence(f.status)}</StatusBadge>
                {f.change === "new" ? <Chip>New</Chip> : null}
                <span className="text-caption text-ink-2">Sources: {f.sources.join(", ")}</span>
              </div>
            }
            actions={writable && f.status !== "resolved" ? (
              <div className="flex flex-wrap gap-2">
                {f.status === "dismissed" ? (
                  <Button variant="ghost" onClick={() => triage.mutate({ status: "open" })}>Reopen</Button>
                ) : (
                  <Button variant="ghost" onClick={() => setDismissOpen(true)}>Dismiss</Button>
                )}
                {f.fixable ? <Button variant="primary" onClick={() => propose.mutate()} disabled={propose.isPending}>Create fix proposal</Button> : null}
              </div>
            ) : null}
          />
          {f.dismissal ? (
            <div className="mb-5">
              <Banner tone="info">
                Dismissed as <strong>{sentence(f.dismissal.reason)}</strong> by {f.dismissal.by?.display_name ?? "a user"} <TimeAgo iso={f.dismissal.at} />
                {f.dismissal.note ? <> · “{f.dismissal.note}”</> : null}
              </Banner>
            </div>
          ) : null}
          <div className="grid grid-cols-[3fr_2fr] gap-5 max-xl:grid-cols-1">
            <div className="flex min-w-0 flex-col gap-5">
              <Card>
                <CardHeader title="Subject" />
                {f.type === "code_issue" ? (
                  <MetaList items={[
                    { label: "File", value: <span className="mono">{f.subject.file_path}</span> },
                    { label: "Lines", value: `${f.subject.line_start}–${f.subject.line_end}` },
                    { label: "Rule", value: <span className="mono">{f.subject.rule_id}</span> },
                  ]} />
                ) : (
                  <MetaList items={[
                    { label: "Package", value: <span className="mono">{f.subject.name}</span> },
                    { label: "Version", value: <span className="mono">{f.subject.version}</span> },
                    { label: "Ecosystem", value: f.subject.ecosystem },
                    { label: "Scope", value: f.subject.scope ?? "unknown" },
                    { label: "Manifest", value: <span className="mono">{f.subject.manifest_path}</span> },
                  ]} />
                )}
                {f.message ? <p className="mt-4 max-w-[72ch]">{f.message}</p> : null}
                {f.advisory ? (
                  <div className="mt-4 flex flex-col gap-1 text-[13.5px]">
                    <p>Advisories: <span className="mono">{(f.advisory.ids ?? []).join(", ")}</span></p>
                    <p>Fixed versions: <span className="mono">{(f.advisory.fixed_versions ?? []).join(", ") || "none published"}</span>
                      {f.advisory.recommended_fix ? <> (smallest applicable fix <span className="mono">{f.advisory.recommended_fix}</span>)</> : null}</p>
                  </div>
                ) : null}
                {f.detail && "heuristic" in f.detail ? (
                  <p className="mt-4 text-caption text-ink-2">Heuristic: <span className="mono">{String(f.detail.heuristic)}</span>. Potential, not proven.</p>
                ) : null}
              </Card>
              <Card>
                <CardHeader title="Evidence" subtitle={`${f.evidence.length} item(s), stored when found; evidence is immutable.`} />
                {f.evidence.length === 0 ? <EmptyState title="No stored evidence." /> : (
                  <ul className="flex flex-col gap-4">
                    {f.evidence.map((ev, i) => (
                      <li key={ev.id}>
                        <div className="mb-2 flex flex-wrap items-center gap-2 text-caption text-ink-2">
                          <Chip>{ev.id}</Chip><span>{sentence(ev.kind)} from {ev.source}</span>
                          <span>retrieved {formatTime(ev.retrieved_at)}</span>
                          {ev.url ? <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-accent">source</a> : null}
                        </div>
                        {i === 0 ? <EvidenceView ev={ev} /> : <Disclosure summary={`${sentence(ev.kind)} (${ev.source})`}><EvidenceView ev={ev} /></Disclosure>}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <RecommendationPanel finding={f} archived={archived} />
            </div>
            <div className="flex min-w-0 flex-col gap-5">
              <Card>
                <CardHeader title="Scan history" as="h3" />
                {f.history.length === 0 ? <p className="text-[13px] text-ink-2">Not seen in any retained scan.</p> : (
                  <ul className="flex flex-col gap-2 text-[13.5px]">
                    {f.history.map((h) => (
                      <li key={h.scan_id} className="flex flex-wrap items-center justify-between gap-2">
                        <Link href={`/projects/${projectId}/code-health/scans/${h.scan_id}`} className="hover:underline"><TimeAgo iso={h.created_at} /></Link>
                        <span className="flex items-center gap-2"><Sha sha={h.commit_sha} /><Chip>{h.change}</Chip></span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card>
                <CardHeader title="Fix proposals" as="h3" />
                {f.fix_proposals.length === 0 ? <p className="text-[13px] text-ink-2">No fix proposal yet.{f.fixable ? " Use Create fix proposal above." : ""}</p> : (
                  <ul className="flex flex-col gap-2 text-[13.5px]">
                    {f.fix_proposals.map((p) => (
                      <li key={p.id} className="flex flex-wrap items-center justify-between gap-2">
                        <Link href={`/projects/${projectId}/code-health/fix-proposals/${p.id}`} className="hover:underline">{sentence(p.status)}</Link>
                        <ResultBadge result={p.validation_result} />
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card>
                <CardHeader title="Recommendations" as="h3" />
                {f.recommendations.length === 0 ? <p className="text-[13px] text-ink-2">No recommendation requested.</p> : (
                  <ul className="flex flex-col gap-2 text-[13.5px]">
                    {f.recommendations.map((r) => (
                      <li key={r.id} className="flex justify-between gap-2"><span>{sentence(r.kind)}</span><span className="text-ink-2"><TimeAgo iso={r.created_at} /></span></li>
                    ))}
                  </ul>
                )}
              </Card>
              <p className="text-caption text-ink-2">
                Static and dependency findings do not prove a runtime failure, and runtime alerts do not identify which finding caused them.
              </p>
            </div>
          </div>
          <Dialog open={dismissOpen} onClose={() => setDismissOpen(false)} title="Dismiss finding"
            footer={<>
              <Button variant="secondary" data-dialog-cancel onClick={() => setDismissOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={() => { setDismissOpen(false); triage.mutate({ status: "dismissed", dismissal_reason: reason, note: note || null }); }}>Dismiss finding</Button>
            </>}>
            <div className="flex flex-col gap-4">
              <Field label="Reason" htmlFor="d-reason">
                <Select id="d-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
                  <option value="false_positive">False positive</option>
                  <option value="accepted_risk">Accepted risk</option>
                  <option value="wont_fix">Won&apos;t fix</option>
                </Select>
              </Field>
              <Field label="Note" htmlFor="d-note" optional>
                <Textarea id="d-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
              </Field>
              <p className="text-caption text-ink-2">The dismissal persists across scans while the finding&apos;s fingerprint is unchanged.</p>
            </div>
          </Dialog>
        </>
      ) : null}
    </>
  );
}
