"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Breadcrumbs } from "@/components/layout/shell";
import { JobProgress } from "@/components/project/job-progress";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, MetaList, PageHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Textarea } from "@/components/ui/field";
import { CodeBlock, CopyButton, DiffViewer, Sha } from "@/components/ui/misc";
import { ResultBadge, StatusBadge } from "@/components/ui/status-badge";
import { Banner, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { approvalGate, type CheckKey } from "@/lib/approval";
import { useAuth } from "@/lib/auth";
import { formatDuration, sentence } from "@/lib/format";
import { useProject } from "@/lib/project";
import type { FixProposal, Job, ValidationRun } from "@/lib/types";

function useWide(): boolean {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return wide;
}

function RunBlock({ title, run }: { title: string; run: ValidationRun | null | undefined }) {
  return (
    <div className="rounded-control border border-line bg-surface-2/40 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{title}</span>
        <ResultBadge result={run?.status ?? null} />
      </div>
      {run ? (
        <>
          <p className="mt-1 text-caption text-ink-2">Exit code {run.exit_code ?? "n/a"}, {formatDuration(run.duration_s)}</p>
          {run.output_tail ? <CodeBlock className="mt-2 max-h-48" label={`${title} output`}>{run.output_tail}</CodeBlock> : null}
        </>
      ) : <p className="mt-1 text-caption text-ink-2">Not run.</p>}
    </div>
  );
}

export default function ProposalReviewPage() {
  const { projectId, proposalId } = useParams<{ projectId: string; proposalId: string }>();
  const project = useProject(projectId);
  const { user, can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const wide = useWide();
  const [checked, setChecked] = useState<Record<CheckKey, boolean>>({ reviewed: false, unverified: false, breaking: false });
  const [comment, setComment] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["fix-proposal", proposalId],
    queryFn: () => api<FixProposal>(`/fix-proposals/${proposalId}`),
    refetchInterval: (query) => (["pending", "validating", "approved"].includes(query.state.data?.status ?? "") && !query.state.data?.pr_error ? 3000 : false),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["fix-proposal", proposalId] });
    void qc.invalidateQueries({ queryKey: ["fix-proposals", projectId] });
  };
  // Approval is never optimistic: the UI waits for the server (UI_UX_SPEC §5).
  const approve = useMutation({
    mutationFn: () => api<{ job: Job }>(`/fix-proposals/${proposalId}/approve`, {
      method: "POST",
      body: { acknowledge_reviewed: checked.reviewed, acknowledge_unverified: checked.unverified,
        acknowledge_breaking_change: checked.breaking, comment: comment || null },
    }),
    onSuccess: (r) => { setJobId(r.job.id); toast.show("Approved. Creating the draft pull request.", { tone: "success" }); refresh(); },
  });
  const reject = useMutation({
    mutationFn: () => api(`/fix-proposals/${proposalId}/reject`, { method: "POST", body: { reason: rejectReason || null } }),
    onSuccess: () => { setRejectOpen(false); toast.show("Proposal rejected. No branch or pull request was created.", { tone: "success" }); refresh(); },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const retry = useMutation({
    mutationFn: () => api<{ job: Job }>(`/fix-proposals/${proposalId}/retry-pr`, { method: "POST" }),
    onSuccess: (r) => { setJobId(r.job.id); toast.show("Retrying pull request creation."); refresh(); },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const cleanup = useMutation({
    mutationFn: () => api<{ job: Job }>(`/fix-proposals/${proposalId}/cleanup`, { method: "POST" }),
    onSuccess: (r) => { setCleanupOpen(false); setJobId(r.job.id); toast.show("Closing the pull request and deleting its branch.", { tone: "success" }); refresh(); },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });

  const p = q.data;
  const gate = p && user ? approvalGate(p, user.role, checked, wide, comment) : null;
  const delta = p?.validation.delta_scan;
  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: project.data?.name ?? "Project", href: `/projects/${projectId}` },
        { label: "Fix proposals", href: `/projects/${projectId}/code-health/fix-proposals` }, { label: "Review" }]} />
      {q.isPending ? <LoadingRows rows={6} /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : p ? (
        <>
          <PageHeader title="Fix proposal"
            meta={
              <MetaList items={[
                { label: "Packages", value: p.changes.length },
                { label: "Base commit", value: <Sha sha={p.base_commit_sha} /> },
                { label: "Status", value: <StatusBadge tone={p.status === "failed" ? "critical" : p.status === "pr_opened" ? "healthy" : "neutral"}>{sentence(p.status)}</StatusBadge> },
                { label: "Validation", value: <ResultBadge result={p.validation.result} /> },
              ]} />
            } />
          <div className="mb-5 flex flex-col gap-3 empty:hidden">
            {p.job && ["pending", "validating"].includes(p.status) ? <JobProgress jobId={p.job.id} label="Sandbox validation" /> : null}
            {jobId ? <JobProgress jobId={jobId} label="Pull request" onDone={() => setJobId(null)} /> : null}
            {p.error ? <ErrorState error={new Error(p.error.message ?? "Validation failed.")} title="Validation could not complete." hint={<span className="mono">{p.error.code}</span>} /> : null}
            {p.validation.result === "unverified" ? <Banner>Unverified: baseline tests were missing or failing before the change, so passing tests after it prove little.</Banner> : null}
            {p.validation.result === "failed" ? <Banner tone="critical" role="alert">Failed: tests failed after the change or the delta scan found a problem. Only an admin can override.</Banner> : null}
            {p.pr_error ? (
              <Banner tone="critical" role="alert">
                Pull request creation failed: {p.pr_error}.{" "}
                {can("maintainer") ? <Button size="sm" variant="secondary" onClick={() => retry.mutate()} disabled={retry.isPending}>Retry</Button> : null}
              </Banner>
            ) : null}
          </div>
          <div className="flex flex-col gap-5">
            <Card>
              <CardHeader title="Changes" />
              <div className="scroll-thin -mx-5 overflow-x-auto border-t border-line max-md:-mx-4">
                <table className="w-full min-w-[640px] text-left text-[13.5px]">
                  <thead><tr className="border-b border-line">
                    <th className="px-5 py-2.5">Package</th><th className="px-5 py-2.5">Version</th>
                    <th className="px-5 py-2.5">Bump</th><th className="px-5 py-2.5">Files</th></tr></thead>
                  <tbody>
                    {p.changes.map((c) => (
                      <tr key={`${c.ecosystem}-${c.package}-${c.lockfile_path}`} className="border-b border-line last:border-0">
                        <td className="mono px-5 py-2.5">{c.package} <span className="text-ink-2">({c.ecosystem}, {c.scope ?? "?"})</span></td>
                        <td className="mono px-5 py-2.5">{c.from_version} → {c.to_version}</td>
                        <td className="px-5 py-2.5">{c.bump === "major" ? <StatusBadge tone="warning">Major</StatusBadge> : sentence(c.bump)}</td>
                        <td className="mono px-5 py-2.5 text-caption">{c.manifest_path}{c.lockfile_path !== c.manifest_path ? `, ${c.lockfile_path}` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card>
              <CardHeader title="Diff" subtitle="Limited to manifests and lockfiles; any other change aborts the proposal." />
              {p.diff ? <DiffViewer diff={p.diff} /> : <p className="text-ink-2">No diff yet.</p>}
            </Card>
            <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
              <Card>
                <CardHeader title="Test report" subtitle="Tests run with networking disabled; install scripts disabled." />
                <div className="flex flex-col gap-3">
                  <RunBlock title="Baseline (before)" run={p.validation.baseline} />
                  <RunBlock title="After change" run={p.validation.post_change} />
                </div>
              </Card>
              <Card>
                <CardHeader title="Delta scan" />
                {delta ? (
                  <ul className="flex flex-col gap-2 text-[13.5px]">
                    <li>{delta.resolved_finding_ids?.length ?? 0} targeted finding(s) resolved</li>
                    <li>{delta.new_findings?.length ?? 0} advisory match(es) on changed packages</li>
                    {delta.unresolved?.length ? <li className="text-crit">{delta.unresolved.length} targeted version(s) still present</li> : null}
                    {delta.status && delta.status !== "ok" ? <li className="text-warn">Delta scan could not complete.</li> : null}
                    {(delta.new_findings ?? []).map((n) => <li key={`${n.package}${n.advisory}`} className="mono text-caption">{n.package}@{n.version}: {n.advisory} ({n.severity ?? "unrated"})</li>)}
                  </ul>
                ) : <p className="text-ink-2">Not run yet.</p>}
              </Card>
            </div>
            <Card>
              <CardHeader title="Risk notes" />
              {p.risk_notes?.length ? <ul className="list-disc pl-5">{p.risk_notes.map((n) => <li key={n}>{n}</li>)}</ul> : <p className="text-ink-2">None recorded.</p>}
            </Card>
            {p.status === "pr_opened" && p.pull_request ? (
              <Card>
                <CardHeader title="Draft pull request created" />
                <p>Draft pull request created. Review and merge it on GitHub; the Toolkit does not merge.</p>
                <div className="mt-4 flex flex-wrap items-center gap-4 text-[13.5px]">
                  <a href={p.pull_request.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline">Pull request #{p.pull_request.number}</a>
                  <span className="flex items-center gap-1"><span className="mono">{p.pull_request.branch}</span><CopyButton text={p.pull_request.branch} label="Copy branch name" /></span>
                  <span className="flex items-center gap-2"><span className="text-ink-2">Base</span><Sha sha={p.base_commit_sha} /></span>
                </div>
                {can("maintainer") && !p.pull_request.closed_at ? (
                  <div className="mt-4"><Button variant="ghost" onClick={() => setCleanupOpen(true)}>Close PR and delete branch</Button></div>
                ) : p.pull_request.closed_at ? <p className="mt-3 text-ink-2">The pull request was closed and its branch deleted.</p> : null}
              </Card>
            ) : null}
            {p.approval ? (
              <p className="text-ink-2">Approved by {p.approval.by?.display_name ?? "a user"}{p.approval.admin_override ? " (admin override)" : ""}.{p.approval.comment ? ` “${p.approval.comment}”` : ""}</p>
            ) : null}
            {gate && p.status === "ready" && can("maintainer") ? (
              <Card>
                <CardHeader title="Approval" subtitle="Approving creates a branch toolkit/fix/… and a draft pull request. Nothing is merged." />
                <div className="flex flex-col gap-1">
                  <Checkbox checked={checked.reviewed} onChange={(v) => setChecked({ ...checked, reviewed: v })} label="I reviewed the diff and test report" />
                  {gate.applicable.includes("unverified") ? (
                    <Checkbox checked={checked.unverified} onChange={(v) => setChecked({ ...checked, unverified: v })} label="I understand tests were missing or failing at base" />
                  ) : null}
                  {gate.applicable.includes("breaking") ? (
                    <Checkbox checked={checked.breaking} onChange={(v) => setChecked({ ...checked, breaking: v })} label="I understand this major upgrade may break compatibility" />
                  ) : null}
                </div>
                {gate.adminOverride && can("admin") ? (
                  <div className="mt-4">
                    <Field label="Override justification" htmlFor="override" hint="Recorded in the audit log.">
                      <Textarea id="override" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
                    </Field>
                  </div>
                ) : (
                  <div className="mt-4">
                    <Field label="Comment" htmlFor="approve-comment" optional>
                      <Textarea id="approve-comment" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
                    </Field>
                  </div>
                )}
                <p className="mt-4 text-[13.5px] text-ink-2" aria-live="polite">
                  {gate.blocked ?? (gate.remaining ? `Tick ${gate.remaining} more item${gate.remaining === 1 ? "" : "s"} above to enable approval.` : "Ready to approve.")}
                </p>
                {approve.isError ? <div className="mt-3"><ErrorState error={approve.error} title="Approval was not recorded." /></div> : null}
                <div className="mt-4 flex justify-between gap-4 max-sm:flex-col-reverse">
                  <Button variant="secondary" onClick={() => setRejectOpen(true)}>Reject</Button>
                  <Button variant="primary" softDisabled={!gate.canApprove || approve.isPending} onClick={() => approve.mutate()}>
                    {approve.isPending ? "Recording approval…" : gate.adminOverride ? "Approve (admin override)" : "Approve and open draft PR"}
                  </Button>
                </div>
              </Card>
            ) : null}
          </div>
          <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject this fix proposal?"
            footer={<>
              <Button variant="secondary" data-dialog-cancel onClick={() => setRejectOpen(false)}>Cancel</Button>
              <Button variant="destructive" onClick={() => reject.mutate()} disabled={reject.isPending}>Reject proposal</Button>
            </>}>
            <Field label="Reason" htmlFor="reject-reason" optional>
              <Textarea id="reject-reason" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} maxLength={1000} />
            </Field>
          </Dialog>
          <Dialog open={cleanupOpen} onClose={() => setCleanupOpen(false)} title={`Close pull request #${p.pull_request?.number ?? ""}?`}
            footer={<>
              <Button variant="secondary" data-dialog-cancel onClick={() => setCleanupOpen(false)}>Cancel</Button>
              <Button variant="destructive" onClick={() => cleanup.mutate()} disabled={cleanup.isPending}>Close PR and delete branch</Button>
            </>}>
            <p>The Toolkit closes the pull request and deletes <span className="mono">{p.pull_request?.branch}</span>. It never touches other branches.</p>
          </Dialog>
        </>
      ) : null}
    </>
  );
}
