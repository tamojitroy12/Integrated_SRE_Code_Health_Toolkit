"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input } from "@/components/ui/field";
import { ErrorState } from "@/components/ui/states";
import { api } from "@/lib/api";
import { sanitize } from "@/lib/parse";
import type { Target } from "@/lib/types";

const SERVICE_RE = /^[A-Za-z0-9_.:-]{1,100}$/;
const ENV_RE = /^[a-z0-9-]{1,50}$/;

export function TargetForm({ projectId, onDone, submitLabel = "Register target" }: {
  projectId: string;
  onDone?: (t: Target) => void;
  submitLabel?: string;
}) {
  const qc = useQueryClient();
  const [service, setService] = useState("");
  const [env, setEnv] = useState("production");
  const [name, setName] = useState("");
  const [defaults, setDefaults] = useState(true);
  const mutation = useMutation({
    mutationFn: () =>
      api<Target>(`/projects/${projectId}/monitoring-targets`, {
        method: "POST",
        body: { name: name || `${service} (${env})`, service_name: service, environment: env, create_default_rules: defaults },
      }),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ["targets", projectId] });
      void qc.invalidateQueries({ queryKey: ["overview", projectId] });
      onDone?.(t);
    },
  });
  const valid = SERVICE_RE.test(service) && ENV_RE.test(env);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (valid) mutation.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        <Field label="Service name" htmlFor="svc" hint="Must equal OTEL_SERVICE_NAME in the app."
          error={service && !SERVICE_RE.test(service) ? "Letters, digits and _ . : - only (max 100)." : undefined}>
          <Input id="svc" value={service} onChange={(e) => setService(e.target.value)} onBlur={() => setService(sanitize(service))}
            placeholder="checkout-api" spellCheck={false} />
        </Field>
        <Field label="Environment" htmlFor="env" error={env && !ENV_RE.test(env) ? "Lowercase letters, digits and - only." : undefined}>
          <Input id="env" value={env} onChange={(e) => setEnv(e.target.value)} onBlur={() => setEnv(sanitize(env))} />
        </Field>
      </div>
      <Field label="Display name" htmlFor="tname" optional>
        <Input id="tname" value={name} onChange={(e) => setName(e.target.value)} placeholder={service ? `${service} (${env})` : ""} />
      </Field>
      <Checkbox checked={defaults} onChange={setDefaults} label="Create default alert rules"
        description="Error ratio above 5 %, p95 latency above 2 s, and telemetry stale for 5 minutes." />
      {mutation.isError ? <ErrorState error={mutation.error} title="The target could not be registered." /> : null}
      <div>
        <Button type="submit" variant="secondary" disabled={!valid || mutation.isPending}>
          {mutation.isPending ? "Registering…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
