"use client";

import { ArrowPathIcon, CodeBracketIcon, PlusIcon, SignalIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { OnboardingSnippet } from "@/components/project/onboarding-snippet";
import { RepositoryForm } from "@/components/project/repository-form";
import { TargetForm } from "@/components/project/target-form";
import { Button } from "@/components/ui/button";
import { MetaList, PageHeader } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/field";
import { TimeAgo } from "@/components/ui/misc";
import { StatusBadge, TargetStatusBadge } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useProject, useProjectParam } from "@/lib/project";
import type { Project, Repository, Target } from "@/lib/types";

/** Settings section: title and explanation on the left, controls on the right (stacked on mobile). */
function Section({ title, description, children, action, danger }: {
  title: string;
  description: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  danger?: boolean;
}) {
  return (
    <section className={cn("grid grid-cols-[minmax(0,280px)_minmax(0,1fr)] gap-x-10 gap-y-4 border-t border-line py-8 first:border-t-0 first:pt-0 max-lg:grid-cols-1")}>
      <div>
        <h2 className={cn("text-[13.5px] font-semibold", danger && "text-crit")}>{title}</h2>
        <p className="mt-1 text-[13px] text-ink-2">{description}</p>
        {action ? <div className="mt-4">{action}</div> : null}
      </div>
      <div className={cn("min-w-0 rounded-panel border bg-surface p-5 shadow-card max-md:p-4", danger ? "border-crit/[var(--tint-border)]" : "border-line")}>
        {children}
      </div>
    </section>
  );
}

export default function SettingsPage() {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  const { can } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const qc = useQueryClient();
  const router = useRouter();
  const writable = can("maintainer") && !project.data?.archived_at;
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [snippetFor, setSnippetFor] = useState<Target | null>(null);
  const [addTarget, setAddTarget] = useState(false);
  const [editRepo, setEditRepo] = useState(false);
  const onError = (e: unknown) => toast.show((e as Error).message, { tone: "error" });

  const repo = useQuery({
    queryKey: ["repository", projectId],
    queryFn: () => api<Repository>(`/projects/${projectId}/repository`).catch((e) => (e.status === 404 ? null : Promise.reject(e))),
  });
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<Target[]>(`/projects/${projectId}/monitoring-targets`) });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["project", projectId] });
    void qc.invalidateQueries({ queryKey: ["overview", projectId] });
    void qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const save = useMutation({
    mutationFn: () => api<Project>(`/projects/${projectId}`, { method: "PATCH", body: {
      ...(name !== null ? { name: name.trim() } : {}), ...(description !== null ? { description: description.trim() || null } : {}) } }),
    onSuccess: () => { toast.show("Project details saved.", { tone: "success" }); setName(null); setDescription(null); invalidate(); },
    onError,
  });
  const verify = useMutation({
    mutationFn: () => api<Repository>(`/projects/${projectId}/repository/verify`, { method: "POST" }),
    onSuccess: () => { toast.show("Repository access re-verified.", { tone: "success" }); void qc.invalidateQueries({ queryKey: ["repository", projectId] }); },
    onError,
  });
  const disconnect = useMutation({
    mutationFn: () => api(`/projects/${projectId}/repository`, { method: "DELETE" }),
    onSuccess: () => { toast.show("Repository disconnected and its stored token deleted.", { tone: "success" }); void qc.invalidateQueries({ queryKey: ["repository", projectId] }); invalidate(); },
    onError,
  });
  const removeTarget = useMutation({
    mutationFn: (t: Target) => api(`/monitoring-targets/${t.id}`, { method: "DELETE" }),
    onSuccess: (_r, t) => { toast.show(`Target “${t.name}” deleted with its alert rules.`, { tone: "success" }); void qc.invalidateQueries({ queryKey: ["targets", projectId] }); invalidate(); },
    onError,
  });
  const archive = useMutation({
    mutationFn: () => api(`/projects/${projectId}`, { method: "DELETE" }),
    onSuccess: () => { toast.show("Project archived. It is now read-only.", { tone: "success" }); void qc.invalidateQueries({ queryKey: ["projects"] }); router.push("/projects"); },
    onError,
  });

  function submitGeneral(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  const p = project.data;
  const dirty = (name !== null && name !== p?.name) || (description !== null && description !== (p?.description ?? ""));
  return (
    <>
      <PageHeader title="Settings" subtitle="Project details, the connected repository and monitored services." />
      <div className="max-w-5xl">
        <Section title="General" description="The name appears across the dashboard and in alert notifications.">
          {!p ? <LoadingRows rows={2} /> : (
            <form onSubmit={submitGeneral} className="flex flex-col gap-4">
              <Field label="Name" htmlFor="s-name"><Input id="s-name" value={name ?? p.name} onChange={(e) => setName(e.target.value)} disabled={!writable} maxLength={100} /></Field>
              <Field label="Description" htmlFor="s-desc" optional><Textarea id="s-desc" value={description ?? p.description ?? ""} onChange={(e) => setDescription(e.target.value)} disabled={!writable} maxLength={1000} /></Field>
              {writable ? (
                <div className="flex items-center justify-end gap-2">
                  {dirty ? <Button variant="ghost" onClick={() => { setName(null); setDescription(null); }}>Discard</Button> : null}
                  <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>{save.isPending ? "Saving…" : "Save changes"}</Button>
                </div>
              ) : null}
            </form>
          )}
        </Section>

        <Section title="Repository" description="The GitHub repository that scans clone. A token is needed for private repositories and for opening fix pull requests.">
          {repo.isPending ? <LoadingRows rows={2} /> : repo.isError ? <ErrorState error={repo.error} onRetry={() => repo.refetch()} /> : repo.data && !editRepo ? (
            <div className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <a href={repo.data.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 font-medium hover:underline">
                  <CodeBracketIcon className="size-4 text-ink-2" aria-hidden="true" />
                  <span className="mono">{repo.data.owner}/{repo.data.name}</span>
                </a>
                {repo.data.verified_at ? <StatusBadge tone="healthy">Verified</StatusBadge> : null}
              </div>
              <MetaList items={[
                { label: "Default branch", value: <span className="mono">{repo.data.default_branch}</span> },
                { label: "Ecosystems", value: repo.data.ecosystems.join(", ") || "None detected" },
                { label: "Access token", value: repo.data.has_token ? "Stored (encrypted)" : "None, public access" },
                { label: "Can open PRs", value: repo.data.can_open_prs ? "Yes" : "No" },
                { label: "Test command", value: <span className="mono">{repo.data.test_command ?? "None"}</span> },
                { label: "Last verified", value: <TimeAgo iso={repo.data.verified_at} /> },
              ]} />
              {writable ? (
                <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                  <Button onClick={() => verify.mutate()} disabled={verify.isPending} icon={<ArrowPathIcon />}>{verify.isPending ? "Verifying…" : "Re-verify access"}</Button>
                  <Button variant="ghost" onClick={() => setEditRepo(true)}>Edit token or settings</Button>
                  <Button variant="ghost" className="ml-auto text-crit hover:text-crit" onClick={async () => {
                    if (await confirm({
                      title: `Disconnect ${repo.data?.owner}/${repo.data?.name}?`, destructive: true, confirmLabel: "Disconnect repository",
                      body: <p>The stored access token is deleted and new scans become unavailable. Existing scans and findings stay available.</p>,
                    })) disconnect.mutate();
                  }}>Disconnect</Button>
                </div>
              ) : null}
            </div>
          ) : writable ? (
            <div className="flex flex-col gap-3">
              <RepositoryForm projectId={projectId} existing={repo.data} onDone={() => { setEditRepo(false); toast.show("Repository verified and connected.", { tone: "success" }); invalidate(); }} />
              {editRepo ? <div><Button variant="ghost" onClick={() => setEditRepo(false)}>Cancel</Button></div> : null}
            </div>
          ) : <EmptyState icon={CodeBracketIcon} title="No repository connected." />}
        </Section>

        <Section title="Monitoring targets" description="Each target is one service in one environment that sends OpenTelemetry metrics to this toolkit."
          action={writable && !addTarget ? <Button onClick={() => setAddTarget(true)} icon={<PlusIcon />}>Add target</Button> : undefined}>
          {addTarget ? (
            <div className="mb-5 rounded-control border border-line bg-surface-2/40 p-4">
              <TargetForm projectId={projectId} onDone={(t) => {
                setAddTarget(false);
                setSnippetFor(t);
                toast.show(`Target “${t.name}” registered. Configure the service to start sending metrics.`, { tone: "success" });
                void qc.invalidateQueries({ queryKey: ["targets", projectId] });
                invalidate();
              }} />
              <Button className="mt-2" variant="ghost" onClick={() => setAddTarget(false)}>Cancel</Button>
            </div>
          ) : null}
          {targets.isPending ? <LoadingRows rows={2} /> : targets.isError ? <ErrorState error={targets.error} onRetry={() => targets.refetch()} /> :
            targets.data.length === 0 ? (!addTarget ? <EmptyState icon={SignalIcon} title="No monitoring target yet.">Add a target to chart a service’s traffic and alert on it.</EmptyState> : null) : (
              <ul className="-my-3 flex flex-col divide-y divide-line">
                {targets.data.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2"><span className="font-medium">{t.name}</span><TargetStatusBadge status={t.status} /></div>
                      <div className="mono mt-0.5 text-caption text-ink-2">{t.service_name} · {t.environment}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                      {can("maintainer") ? <Button size="sm" variant="ghost" onClick={() => setSnippetFor(t)}>Setup instructions</Button> : null}
                      {writable ? (
                        <Button size="sm" variant="ghost" className="text-crit hover:text-crit" onClick={async () => {
                          if (await confirm({
                            title: `Delete target “${t.name}”?`, destructive: true, confirmLabel: "Delete target",
                            body: <p>Its alert rules are deleted and open alerts are resolved. Alert history is kept. Metrics already stored in Prometheus are not removed.</p>,
                          })) removeTarget.mutate(t);
                        }}>Delete</Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
        </Section>

        {writable ? (
          <Section danger title="Archive project" description="Archiving makes the project read-only and disables its alert rules. Data is kept until an admin permanently deletes it.">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-[13px] text-ink-2">Archived projects are hidden from the project list unless “Include archived” is selected.</p>
              <Button variant="destructive" onClick={async () => {
                if (!p) return;
                if (await confirm({
                  title: `Archive “${p.name}”?`, destructive: true, confirmLabel: "Archive project", typeToConfirm: p.name,
                  body: <p>The project becomes read-only and its alert rules stop evaluating. Scans, findings and alert history are kept.</p>,
                })) archive.mutate();
              }}>Archive project</Button>
            </div>
          </Section>
        ) : null}
      </div>
      <Dialog open={!!snippetFor} onClose={() => setSnippetFor(null)} title={`Send metrics from ${snippetFor?.name ?? ""}`} className="w-[min(720px,calc(100vw-32px))]"
        footer={<Button variant="secondary" data-dialog-cancel onClick={() => setSnippetFor(null)}>Done</Button>}>
        {snippetFor ? <div className="text-ink"><OnboardingSnippet targetId={snippetFor.id} /></div> : null}
      </Dialog>
    </>
  );
}
