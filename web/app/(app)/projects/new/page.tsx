"use client";

import { CheckIcon, CheckCircleIcon, ClockIcon, MinusCircleIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent, type ReactNode } from "react";

import { Breadcrumbs } from "@/components/layout/shell";
import { OnboardingSnippet } from "@/components/project/onboarding-snippet";
import { RepositoryForm } from "@/components/project/repository-form";
import { TargetForm } from "@/components/project/target-form";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/field";
import { TargetStatusBadge } from "@/components/ui/status-badge";
import { ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Project, Repository, Target } from "@/lib/types";

const STEPS = [
  { label: "Details", hint: "Name the project" },
  { label: "Repository", hint: "Optional" },
  { label: "Monitoring", hint: "Optional" },
  { label: "Instrument", hint: "Send metrics" },
  { label: "Done", hint: "Review" },
] as const;

function Stepper({ step }: { step: number }) {
  return (
    <ol className="chrome mb-6 grid grid-cols-5 gap-2 max-md:hidden" aria-label="Progress">
      {STEPS.map((s, i) => {
        const done = i < step;
        const current = i === step;
        return (
          <li key={s.label} aria-current={current ? "step" : undefined} className="flex flex-col gap-2">
            <span className={cn("h-1 rounded-full", done || current ? "bg-primary" : "bg-surface-3")} />
            <span className="flex items-center gap-2">
              <span className={cn("grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold",
                done ? "bg-primary text-on-primary" : current ? "border border-primary text-accent" : "border border-line-strong text-ink-3")}>
                {done ? <CheckIcon className="size-3" aria-hidden="true" /> : i + 1}
              </span>
              <span className="min-w-0">
                <span className={cn("block truncate text-[13px] font-medium", current || done ? "text-ink" : "text-ink-2")}>{s.label}</span>
                <span className="block truncate text-[11.5px] text-ink-3">{s.hint}</span>
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StepHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-5">
      <h2 className="text-[16px] font-semibold">{title}</h2>
      {children ? <p className="mt-1 text-[13px] text-ink-2">{children}</p> : null}
    </div>
  );
}

function StepFooter({ children }: { children: ReactNode }) {
  return <div className="-mx-5 -mb-5 mt-6 flex flex-wrap items-center justify-between gap-3 rounded-b-panel border-t border-line bg-surface-2/40 px-5 py-3 max-md:-mx-4 max-md:-mb-4 max-md:px-4">{children}</div>;
}

function SummaryRow({ ok, pending, children }: { ok: boolean; pending?: boolean; children: ReactNode }) {
  const Icon = ok ? CheckCircleIcon : pending ? ClockIcon : MinusCircleIcon;
  return (
    <li className="flex items-start gap-2.5 py-2.5">
      <Icon className={cn("mt-0.5 size-4 shrink-0", ok ? "text-ok" : pending ? "text-warn" : "text-ink-3")} aria-hidden="true" />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** Resumable wizard; state lives in the URL so a reload continues where it stopped. */
function Wizard() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const qc = useQueryClient();
  const step = Math.min(4, Math.max(0, Number(params.get("step") ?? 0)));
  const projectId = params.get("project");
  const targetId = params.get("target");
  const go = (next: Record<string, string | number | null>) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(next)) {
      if (v === null) sp.delete(k);
      else sp.set(k, String(v));
    }
    router.replace(`/projects/new?${sp.toString()}`);
  };

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => api<Project>("/projects", { method: "POST", body: { name: name.trim(), description: description.trim() || null } }),
    onSuccess: (p) => {
      toast.show(<>Project <strong>{p.name}</strong> created.</>, { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["projects"] });
      go({ project: p.id, step: 1 });
    },
  });

  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`), enabled: !!projectId });
  const repo = useQuery({
    queryKey: ["repository", projectId],
    queryFn: () => api<Repository>(`/projects/${projectId}/repository`).catch(() => null),
    enabled: !!projectId && step >= 1,
  });
  const target = useQuery({
    queryKey: ["target", targetId],
    queryFn: () => api<Target>(`/monitoring-targets/${targetId}`),
    enabled: !!targetId && step >= 3,
    refetchInterval: (q) => (q.state.data?.status === "receiving" ? false : 5000),
  });

  function submitDetails(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) create.mutate();
  }

  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: "New project" }]} />
      <PageHeader title="New project"
        subtitle={project.data ? <>Setting up <strong className="font-medium text-ink">{project.data.name}</strong>. Everything after the name is optional and can be added later in Settings.</>
          : "Only the name is required. Repository and monitoring can be connected now or later."} />
      <div className="max-w-3xl">
        <Stepper step={step} />
        <p className="mb-3 text-caption text-ink-2 md:hidden">Step {step + 1} of {STEPS.length}: {STEPS[step]?.label}</p>
        <Card>
          {step === 0 ? (
            <form onSubmit={submitDetails}>
              <StepHeader title="Project details">A project groups one GitHub repository and the services it runs.</StepHeader>
              <div className="flex flex-col gap-4">
                <Field label="Project name" htmlFor="pname" hint="1–100 characters, unique among active projects.">
                  <Input id="pname" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Checkout service" />
                </Field>
                <Field label="Description" htmlFor="pdesc" optional>
                  <Textarea id="pdesc" value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)}
                    placeholder="What does this service do, and who owns it?" />
                </Field>
                {create.isError ? <ErrorState error={create.error} title="The project could not be created." /> : null}
              </div>
              <StepFooter>
                <ButtonLink href="/projects" variant="ghost">Cancel</ButtonLink>
                <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
                  {create.isPending ? "Creating…" : "Create project"}
                </Button>
              </StepFooter>
            </form>
          ) : null}
          {step === 1 && projectId ? (
            <>
              <StepHeader title="Connect a GitHub repository">
                Scans clone this repository to find vulnerable or outdated dependencies and risky code. A token is only needed for private repositories or fix PRs.
              </StepHeader>
              <RepositoryForm projectId={projectId} onDone={() => { toast.show("Repository connected.", { tone: "success" }); go({ step: 2 }); }} />
              <StepFooter>
                <span className="text-caption text-ink-2">You can connect a repository later in Settings.</span>
                <Button variant="ghost" onClick={() => go({ step: 2 })}>Skip for now</Button>
              </StepFooter>
            </>
          ) : null}
          {step === 2 && projectId ? (
            <>
              <StepHeader title="Register a monitoring target">
                A target is one running service in one environment. The toolkit charts its request rate, error ratio and latency, and evaluates alert rules against them.
              </StepHeader>
              <TargetForm projectId={projectId} onDone={(t) => { toast.show(`Monitoring target “${t.name}” registered.`, { tone: "success" }); go({ step: 3, target: t.id }); }} />
              <StepFooter>
                <span className="text-caption text-ink-2">You can add targets later in Settings.</span>
                <Button variant="ghost" onClick={() => go({ step: 4 })}>Skip for now</Button>
              </StepFooter>
            </>
          ) : null}
          {step === 3 && targetId ? (
            <>
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[16px] font-semibold">Send metrics from your service</h2>
                  <p className="mt-1 max-w-[60ch] text-[13px] text-ink-2">
                    Set these environment variables on the service you registered and restart it. Its OpenTelemetry SDK will then push
                    metrics to this toolkit. This page updates automatically when the first sample arrives.
                  </p>
                </div>
                {target.data ? <TargetStatusBadge status={target.data.status} /> : null}
              </div>
              <OnboardingSnippet targetId={targetId} />
              <StepFooter>
                <Button variant="ghost" onClick={() => go({ step: 4 })}>Finish without waiting</Button>
                <Button variant="primary" onClick={() => go({ step: 4 })} disabled={target.data?.status !== "receiving"}>
                  Continue
                </Button>
              </StepFooter>
            </>
          ) : null}
          {step === 4 && projectId ? (
            <>
              <StepHeader title="Project ready">Here is what was set up. Anything skipped can be added from the project’s Settings page.</StepHeader>
              <ul className="flex flex-col divide-y divide-line rounded-panel border border-line px-4">
                <SummaryRow ok={!!repo.data}>
                  {repo.data ? (
                    <>Repository <span className="mono">github.com/{repo.data.owner}/{repo.data.name}</span> verified
                      <span className="block text-caption text-ink-2">Ecosystems: {repo.data.ecosystems.join(", ") || "none detected"}</span></>
                  ) : "No repository connected"}
                </SummaryRow>
                <SummaryRow ok={target.data?.status === "receiving"} pending={!!targetId && target.data?.status !== "receiving"}>
                  {targetId ? (target.data?.status === "receiving" ? "Monitoring is receiving metrics" : "Monitoring target registered, waiting for the first sample")
                    : "No monitoring target registered"}
                </SummaryRow>
              </ul>
              <StepFooter>
                <span />
                <ButtonLink href={`/projects/${projectId}`} variant="primary">Open project overview</ButtonLink>
              </StepFooter>
            </>
          ) : null}
        </Card>
      </div>
    </>
  );
}

export default function NewProjectPage() {
  return (
    <Suspense fallback={null}>
      <Wizard />
    </Suspense>
  );
}
