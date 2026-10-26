"use client";

import { MegaphoneIcon, PlusIcon } from "@heroicons/react/20/solid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/field";
import { Switch } from "@/components/ui/misc";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { sanitize } from "@/lib/parse";
import type { Channel } from "@/lib/types";

interface TestResult {
  status: "delivered" | "failed";
  http_status: number | null;
  error: string | null;
  latency_ms: number;
  attempted_at: string;
}

export default function ChannelsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [createOpen, setCreateOpen] = useState(false);
  const [replace, setReplace] = useState<Channel | null>(null);
  const [remove, setRemove] = useState<Channel | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [results, setResults] = useState<Record<string, TestResult | "pending">>({});
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/notification-channels") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["channels"] });
  const create = useMutation({
    mutationFn: () => api<Channel>("/notification-channels", { method: "POST", body: { type: "webhook", name, config: { url: sanitize(url) } } }),
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
    onSuccess: () => { setCreateOpen(false); setName(""); setUrl(""); toast.show("Channel created. The URL is stored encrypted and is never shown again.", { tone: "success" }); void refresh(); },
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api<Channel>(`/notification-channels/${id}`, { method: "PATCH", body }),
    onSuccess: (c, v) => {
      toast.show("config" in v.body ? `Webhook URL for “${c.name}” replaced.` : `“${c.name}” ${c.enabled ? "enabled" : "disabled"}.`, { tone: "success" });
      setReplace(null);
      setUrl("");
      void refresh();
    },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  const del = useMutation({
    mutationFn: (c: Channel) => api(`/notification-channels/${c.id}`, { method: "DELETE" }),
    onSuccess: (_r, c) => { setRemove(null); toast.show(`Channel “${c.name}” deleted.`, { tone: "success" }); void refresh(); },
    onError: (e) => toast.show((e as Error).message, { tone: "error" }),
  });
  // Non-optimistic: show the real delivery receipt from the server.
  const test = useMutation({
    mutationFn: (c: Channel) => api<TestResult>(`/notification-channels/${c.id}/test`, { method: "POST" }),
    onMutate: (c) => setResults((r) => ({ ...r, [c.id]: "pending" })),
    onSuccess: (res, c) => setResults((r) => ({ ...r, [c.id]: res })),
    onError: (e, c) => {
      setResults((r) => { const n = { ...r }; delete n[c.id]; return n; });
      toast.show((e as Error).message, { tone: "error" });
    },
  });
  return (
    <Card>
      <CardHeader title="Notification channels" subtitle="Webhooks receive a JSON payload when alerts fire or resolve."
        action={<Button variant="primary" icon={<PlusIcon />} onClick={() => setCreateOpen(true)}>Add channel</Button>} />
      {channels.isPending ? <LoadingRows /> : channels.isError ? <ErrorState error={channels.error} onRetry={() => channels.refetch()} /> :
        channels.data.length === 0 ? <EmptyState icon={MegaphoneIcon} title="No channels.">Alerts are still shown in the dashboard; add a webhook to be notified.</EmptyState> : (
          <ul className="-my-3 flex flex-col divide-y divide-line">
            {channels.data.map((c) => {
              const r = results[c.id];
              return (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                  <div>
                    <div className="font-medium">{c.name}</div>
                    <div className="mono text-caption text-ink-2">{c.type} to {c.config.host}{c.config.port ? `:${c.config.port}` : ""}</div>
                    {r === "pending" ? <div className="mt-1 text-caption text-ink-2">Sending test…</div> : r ? (
                      <div className={`mt-1 text-caption ${r.status === "delivered" ? "text-ok" : "text-crit"}`}>
                        {r.status === "delivered" ? `Delivered at ${formatTime(r.attempted_at, "utc", true)} UTC (${r.latency_ms} ms)` : `Failed: ${r.error ?? "unknown"}`}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mr-2 flex items-center gap-2">
                      <Switch checked={c.enabled} label={`Channel ${c.name} enabled`} disabled={patch.isPending}
                        onChange={() => patch.mutate({ id: c.id, body: { enabled: !c.enabled } })} />
                      <span className="text-caption text-ink-2">{c.enabled ? "Enabled" : "Disabled"}</span>
                    </span>
                    <Button size="sm" variant="secondary" onClick={() => test.mutate(c)} disabled={r === "pending"}>Send test</Button>
                    <Button size="sm" variant="ghost" onClick={() => setReplace(c)}>Replace URL</Button>
                    <Button size="sm" variant="ghost" className="text-crit hover:text-crit" onClick={() => setRemove(c)}>Delete</Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Add webhook channel" initialFocus="first"
        footer={<>
          <Button variant="secondary" data-dialog-cancel onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => create.mutate()} disabled={!name || !url || create.isPending}>Create channel</Button>
        </>}>
        <div className="flex flex-col gap-4">
          <Field label="Name" htmlFor="c-name"><Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} /></Field>
          <Field label="Webhook URL" htmlFor="c-url" hint="HTTPS only; private, loopback and credential-bearing URLs are rejected.">
            <Input id="c-url" type="password" autoComplete="off" value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => setUrl(sanitize(url))} />
          </Field>
          {create.isError ? <ErrorState error={create.error} title="The channel was not created." /> : null}
        </div>
      </Dialog>
      <Dialog open={!!replace} onClose={() => setReplace(null)} title={`Replace URL for ${replace?.name ?? ""}`}
        footer={<>
          <Button variant="secondary" data-dialog-cancel onClick={() => setReplace(null)}>Cancel</Button>
          <Button variant="primary" onClick={() => replace && patch.mutate({ id: replace.id, body: { config: { url: sanitize(url) } } })} disabled={!url || patch.isPending}>Replace</Button>
        </>}>
        <Field label="New webhook URL" htmlFor="c-new"><Input id="c-new" type="password" autoComplete="off" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
      </Dialog>
      <Dialog open={!!remove} onClose={() => setRemove(null)} title={`Delete channel "${remove?.name ?? ""}"?`}
        footer={<>
          <Button variant="secondary" data-dialog-cancel onClick={() => setRemove(null)}>Cancel</Button>
          <Button variant="destructive" onClick={() => remove && del.mutate(remove)} disabled={del.isPending}>Delete channel</Button>
        </>}>
        <p>Deleting the channel also removes its delivery history.</p>
      </Dialog>
    </Card>
  );
}
