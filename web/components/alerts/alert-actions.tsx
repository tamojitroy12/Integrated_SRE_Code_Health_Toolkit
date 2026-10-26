"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Alert } from "@/lib/types";

/** Acknowledge commits immediately, updates optimistically, and offers a 6 s compensating undo. */
export function useAlertActions(projectId: string) {
  const qc = useQueryClient();
  const toast = useToast();
  const patchCaches = (id: string, patch: Partial<Alert>) => {
    qc.setQueriesData<{ items: Alert[] }>({ queryKey: ["alerts", projectId] }, (old) =>
      old ? { ...old, items: old.items.map((a) => (a.id === id ? { ...a, ...patch } : a)) } : old);
    qc.setQueryData<Alert>(["alert", id], (old) => (old ? { ...old, ...patch } : old));
  };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["alerts", projectId] });
    void qc.invalidateQueries({ queryKey: ["summary", projectId] });
    void qc.invalidateQueries({ queryKey: ["overview", projectId] });
  };
  const unack = useMutation({
    mutationFn: (id: string) => api<Alert>(`/alerts/${id}/unacknowledge`, { method: "POST" }),
    onSettled: refresh,
  });
  const ack = useMutation({
    mutationFn: (id: string) => api<Alert>(`/alerts/${id}/acknowledge`, { method: "POST" }),
    onMutate: (id) => {
      const previous = qc.getQueryData<Alert>(["alert", id]);
      patchCaches(id, { status: "acknowledged" });
      return { previous };
    },
    onSuccess: (alert) => {
      qc.setQueryData(["alert", alert.id], alert);
      toast.show(<>Acknowledged <strong>{alert.rule_name}</strong>.</>, { tone: "success", undo: () => unack.mutate(alert.id) });
    },
    onError: (e, id) => {
      patchCaches(id, { status: "firing" });
      toast.show(`Could not acknowledge: ${(e as Error).message}`, { tone: "error" });
    },
    onSettled: refresh,
  });
  const resolve = useMutation({
    mutationFn: (id: string) => api<Alert>(`/alerts/${id}/resolve`, { method: "POST" }),
    onSuccess: (alert) => {
      qc.setQueryData(["alert", alert.id], alert);
      toast.show(<>Resolved <strong>{alert.rule_name}</strong>. If the condition still holds, the rule fires again.</>, { tone: "success" });
    },
    onError: (e) => toast.show(`Could not resolve: ${(e as Error).message}`, { tone: "error" }),
    onSettled: refresh,
  });
  return { ack, resolve };
}

export function AlertActionButtons({ alert, projectId, archived }: { alert: Alert; projectId: string; archived: boolean }) {
  const { can } = useAuth();
  const { ack, resolve } = useAlertActions(projectId);
  const confirm = useConfirm();
  if (!can("maintainer") || alert.status === "resolved") return null;
  return (
    <div className="flex gap-2">
      {alert.status === "firing" && !archived ? (
        <Button size="sm" variant="secondary" onClick={() => ack.mutate(alert.id)} disabled={ack.isPending}>Acknowledge</Button>
      ) : null}
      <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={async () => {
        if (await confirm({
          title: `Resolve “${alert.rule_name}”?`, confirmLabel: "Resolve alert",
          body: <p>Resolve manually only once the underlying problem is fixed. If the rule’s condition still holds at the next evaluation, a new alert fires.</p>,
        })) resolve.mutate(alert.id);
      }}>Resolve</Button>
    </div>
  );
}
