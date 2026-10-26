"use client";

import { BellAlertIcon, PlusIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { SegmentedNav, Switch } from "@/components/ui/misc";
import { SeverityBadge } from "@/components/ui/status-badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDuration, formatMetric, METRIC_LABELS, METRIC_UNITS } from "@/lib/format";
import { describeSeconds, parseDuration, parseLatency, parseRatio } from "@/lib/parse";
import { useProject, useProjectParam } from "@/lib/project";
import type { AlertRule, RuleMetric, RuleType, Severity, Target } from "@/lib/types";

function ruleSummary(r: AlertRule): string {
  if (r.type === "absence") return `No samples for ${formatDuration(r.duration_seconds)}`;
  if (r.type === "anomaly") return `|z| > ${r.params.z_threshold} for ${r.params.consecutive} evaluations`;
  return `${METRIC_LABELS[r.metric]} ${r.comparator === "gt" ? ">" : "<"} ${formatMetric(r.threshold, METRIC_UNITS[r.metric] ?? "")} over ${r.window}, for ${formatDuration(r.duration_seconds)}`;
}

function RuleForm({ projectId, targets, editing, onClose }: { projectId: string; targets: Target[]; editing: AlertRule | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [type, setType] = useState<RuleType>(editing?.type ?? "threshold");
  const [metric, setMetric] = useState<RuleMetric>(editing?.metric ?? "error_ratio");
  const [name, setName] = useState(editing?.name ?? "");
  const [target, setTarget] = useState(editing?.target_id ?? targets[0]?.id ?? "");
  const [comparator, setComparator] = useState<"gt" | "lt">(editing?.comparator ?? "gt");
  const [thresholdText, setThresholdText] = useState(editing?.threshold != null ? String(editing.threshold) : "5%");
  const [window, setWindow] = useState(editing?.window ?? "5m");
  const [durationText, setDurationText] = useState(editing ? `${editing.duration_seconds}s` : "2m");
  const [severity, setSeverity] = useState<Severity>(editing?.severity ?? "high");
  const [guidance, setGuidance] = useState(editing?.guidance ?? "");
  const [z, setZ] = useState(String(editing?.params.z_threshold ?? 3));
  const [consecutive, setConsecutive] = useState(String(editing?.params.consecutive ?? 3));
  const [baseline, setBaseline] = useState(String(editing?.params.baseline_points ?? 60));
  const effectiveMetric: RuleMetric = type === "absence" ? "data_absent" : metric;
  const duration = parseDuration(durationText);
  const ratio = effectiveMetric === "error_ratio" ? parseRatio(thresholdText) : null;
  const threshold = effectiveMetric === "error_ratio" ? (ratio && "value" in ratio ? ratio.value : null)
    : effectiveMetric === "latency_p95" ? parseLatency(thresholdText) : Number.isFinite(Number(thresholdText)) ? Number(thresholdText) : null;

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name, severity, guidance, duration_seconds: duration ?? undefined,
        ...(type === "threshold" ? { comparator, threshold, window } : {}),
        ...(type === "anomaly" ? { window, params: { z_threshold: Number(z), consecutive: Number(consecutive), baseline_points: Number(baseline) } } : {}),
      };
      if (editing) return api<AlertRule>(`/alert-rules/${editing.id}`, { method: "PATCH", body });
      return api<AlertRule>(`/projects/${projectId}/alert-rules`, { method: "POST", body: { ...body, target_id: target, type, metric: effectiveMetric } });
    },
    onSuccess: () => {
      toast.show(editing ? "Rule updated. Its evaluation counters were reset." : `Rule “${name}” created.`, { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["rules", projectId] });
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field label="Name" htmlFor="r-name"><Input id="r-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} /></Field>
      {!editing ? (
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Target" htmlFor="r-target">
            <Select id="r-target" value={target} onChange={(e) => setTarget(e.target.value)}>
              {targets.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          </Field>
          <Field label="Type" htmlFor="r-type">
            <Select id="r-type" value={type} onChange={(e) => setType(e.target.value as RuleType)}>
              <option value="threshold">Threshold</option>
              <option value="absence">Absence (no data)</option>
              <option value="anomaly">Anomaly (z-score)</option>
            </Select>
          </Field>
        </div>
      ) : null}
      {type !== "absence" && !editing ? (
        <Field label="Metric" htmlFor="r-metric">
          <Select id="r-metric" value={metric} onChange={(e) => setMetric(e.target.value as RuleMetric)}>
            {type === "threshold" ? <option value="error_ratio">Error ratio</option> : null}
            <option value="latency_p95">Latency p95</option>
            <option value="request_rate">Request rate</option>
          </Select>
        </Field>
      ) : null}
      {type === "threshold" ? (
        <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
          <Field label="Comparator" htmlFor="r-cmp">
            <Select id="r-cmp" value={comparator} onChange={(e) => setComparator(e.target.value as "gt" | "lt")}>
              <option value="gt">Above (&gt;)</option><option value="lt">Below (&lt;)</option>
            </Select>
          </Field>
          <Field label="Threshold" htmlFor="r-thr"
            hint={threshold !== null ? `= ${formatMetric(threshold, METRIC_UNITS[effectiveMetric] ?? "")}` : undefined}
            error={ratio && "ambiguous" in ratio ? undefined : threshold === null && thresholdText ? "Not a valid threshold." : undefined}>
            <Input id="r-thr" value={thresholdText} onChange={(e) => setThresholdText(e.target.value)}
              placeholder={effectiveMetric === "error_ratio" ? "5% or 0.05" : effectiveMetric === "latency_p95" ? "2s or 250ms" : "req/s"} />
          </Field>
          <Field label="Window" htmlFor="r-win">
            <Select id="r-win" value={window} onChange={(e) => setWindow(e.target.value as "1m" | "5m" | "15m")}>
              <option value="1m">1m</option><option value="5m">5m</option><option value="15m">15m</option>
            </Select>
          </Field>
        </div>
      ) : null}
      {ratio && "ambiguous" in ratio ? (
        <button type="button" className="chrome self-start rounded-full bg-accent/15 px-3 py-1 text-caption font-semibold text-accent"
          onClick={() => setThresholdText(`${ratio.ambiguous * 100}%`)}>
          Did you mean {ratio.ambiguous * 100}% ({ratio.ambiguous})?
        </button>
      ) : null}
      {type === "anomaly" ? (
        <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
          <Field label="z threshold" htmlFor="r-z"><Input id="r-z" value={z} onChange={(e) => setZ(e.target.value)} inputMode="decimal" /></Field>
          <Field label="Consecutive" htmlFor="r-c"><Input id="r-c" value={consecutive} onChange={(e) => setConsecutive(e.target.value)} inputMode="numeric" /></Field>
          <Field label="Baseline points" htmlFor="r-b"><Input id="r-b" value={baseline} onChange={(e) => setBaseline(e.target.value)} inputMode="numeric" /></Field>
        </div>
      ) : (
        <Field label={type === "absence" ? "No data for" : "Condition must hold for"} htmlFor="r-dur"
          hint={duration ? `= ${describeSeconds(duration)}` : "e.g. 5m, 300s, 1h30m"}
          error={durationText && !duration ? "Not a duration." : undefined}>
          <Input id="r-dur" value={durationText} onChange={(e) => setDurationText(e.target.value)} />
        </Field>
      )}
      <Field label="Severity" htmlFor="r-sev">
        <Select id="r-sev" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s[0]!.toUpperCase() + s.slice(1)}</option>)}
        </Select>
      </Field>
      <Field label="Guidance" htmlFor="r-guid" optional hint="Shown in the alert's evidence: what the on-call engineer should check first.">
        <Textarea id="r-guid" value={guidance} onChange={(e) => setGuidance(e.target.value)} maxLength={2000} />
      </Field>
      {save.isError ? <ErrorState error={save.error} title="The rule was not saved." /> : null}
      <div className="-mx-5 -mb-5 mt-2 flex justify-end gap-2 border-t border-line bg-surface-2/50 px-5 py-3 max-md:-mx-4 max-md:-mb-4">
        <Button variant="secondary" onClick={onClose} data-dialog-cancel>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!name || save.isPending || (type === "threshold" && threshold === null)}>
          {editing ? "Save changes" : "Create rule"}
        </Button>
      </div>
    </form>
  );
}

export default function RulesPage() {
  const projectId = useProjectParam();
  const project = useProject(projectId);
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<AlertRule | null | "new">(null);
  const confirm = useConfirm();
  const targets = useQuery({ queryKey: ["targets", projectId], queryFn: () => api<Target[]>(`/projects/${projectId}/monitoring-targets`) });
  const rules = useQuery({ queryKey: ["rules", projectId], queryFn: () => api<AlertRule[]>(`/projects/${projectId}/alert-rules`) });
  const toggle = useMutation({
    mutationFn: (r: AlertRule) => api<AlertRule>(`/alert-rules/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }),
    onSuccess: (r) => {
      toast.show(`Rule “${r.name}” ${r.enabled ? "enabled" : "disabled"}.`, { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["rules", projectId] });
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const remove = useMutation({
    mutationFn: (r: AlertRule) => api(`/alert-rules/${r.id}`, { method: "DELETE" }),
    onSuccess: (_r, rule) => {
      toast.show(`Rule “${rule.name}” deleted.`, { tone: "success" });
      void qc.invalidateQueries({ queryKey: ["rules", projectId] });
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const writable = can("maintainer") && !project.data?.archived_at;
  const targetName = (id: string) => targets.data?.find((t) => t.id === id)?.name ?? "Unknown target";

  return (
    <>
      <PageHeader title="Alerts" subtitle="Threshold, absence and anomaly rules per monitoring target."
        actions={writable && targets.data?.length ? <Button variant="primary" icon={<PlusIcon />} onClick={() => setEditing("new")}>New rule</Button> : null} />
      <SegmentedNav items={[{ href: `/projects/${projectId}/alerts`, label: "Active", exact: true },
        { href: `/projects/${projectId}/alerts/rules`, label: "Rules" }]} />
      <Card className="overflow-hidden p-0 max-md:p-0">
        {rules.isPending ? <div className="p-5"><LoadingRows /></div> : rules.isError ? <div className="p-5"><ErrorState error={rules.error} onRetry={() => rules.refetch()} /></div> :
          rules.data.length === 0 ? (
            <div className="p-5"><EmptyState icon={BellAlertIcon} title="No alert rules.">{targets.data?.length ? "Create a rule to be notified when a target misbehaves." : "Register a monitoring target first."}</EmptyState></div>
          ) : (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full text-left text-[13.5px]">
                <thead className="chrome">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2.5">Rule</th>
                    <th className="px-4 py-2.5">Condition</th>
                    <th className="px-4 py-2.5">Severity</th>
                    <th className="px-4 py-2.5">State</th>
                    <th className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rules.data.map((r) => (
                    <tr key={r.id} className="border-b border-line last:border-0">
                      <td className="px-4 py-2.5"><div className="font-medium">{r.name}</div><div className="text-caption text-ink-2">{targetName(r.target_id)}</div></td>
                      <td className="px-4 py-2.5 text-ink-2">{ruleSummary(r)}</td>
                      <td className="px-4 py-2.5"><SeverityBadge severity={r.severity} /></td>
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-2">
                          <Switch checked={r.enabled} onChange={() => toggle.mutate(r)} disabled={!writable || toggle.isPending} label={`Rule ${r.name} enabled`} />
                          <span className="text-caption text-ink-2">{r.enabled ? "Enabled" : "Disabled"}</span>
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        {writable ? (
                          <div className="flex justify-end gap-2">
                            <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit</Button>
                            <Button size="sm" variant="ghost" className="text-crit hover:text-crit" onClick={async () => {
                              if (await confirm({
                                title: `Delete rule “${r.name}”?`, destructive: true, confirmLabel: "Delete rule",
                                body: <p>Open alerts for this rule are resolved and the rule stops being evaluated. Alert history is kept.</p>,
                              })) remove.mutate(r);
                            }}>Delete</Button>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "New alert rule" : "Edit alert rule"} initialFocus="first">
        {editing !== null && targets.data ? (
          <RuleForm projectId={projectId} targets={targets.data} editing={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
        ) : null}
      </Dialog>
    </>
  );
}
