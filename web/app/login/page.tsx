"use client";

import { BellAlertIcon, ChartBarIcon, EyeIcon, EyeSlashIcon, ShieldCheckIcon, XCircleIcon } from "@heroicons/react/20/solid";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { errorText } from "@/components/ui/states";
import { useAuth } from "@/lib/auth";
import { sanitize } from "@/lib/parse";

function safeNext(next: string | null): string {
  // Only same-site relative paths, never protocol-relative or absolute URLs.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/projects";
}

function LoginForm() {
  const { login, status } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState<{ message: string; requestId: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const next = safeNext(params.get("next"));

  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, router, next]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(sanitize(email), password);
      router.replace(next);
    } catch (err) {
      const { message, requestId } = errorText(err);
      setError({ message, requestId });
    } finally {
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState?.("CapsLock") ?? false);

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <Field label="Email" htmlFor="email">
        <Input id="email" type="email" autoComplete="username" required value={email} autoFocus
          placeholder="you@company.com" className="h-9"
          onChange={(e) => setEmail(e.target.value)} onBlur={() => setEmail(sanitize(email))} />
      </Field>
      <Field label="Password" htmlFor="password" hint={capsLock ? "Caps Lock is on." : undefined}>
        <div className="relative">
          <Input id="password" type={reveal ? "text" : "password"} autoComplete="current-password" required value={password}
            className="h-9 pr-10" onKeyUp={onKey} onKeyDown={onKey}
            onChange={(e) => setPassword(e.target.value)} />
          <button type="button" onClick={() => setReveal(!reveal)} aria-pressed={reveal} title={reveal ? "Hide" : "Show"}
            className="chrome absolute inset-y-0 right-0 grid w-9 place-items-center rounded-r-control text-ink-3 hover:text-ink">
            {reveal ? <EyeSlashIcon className="size-4" aria-hidden="true" /> : <EyeIcon className="size-4" aria-hidden="true" />}
            <span className="sr-only">{reveal ? "Hide characters" : "Reveal characters"}</span>
          </button>
        </div>
      </Field>
      {error ? (
        <div role="alert" className="flex gap-2.5 rounded-control border border-crit/[var(--tint-border)] bg-crit/[var(--tint)] px-3 py-2.5 text-[13px]">
          <XCircleIcon className="mt-0.5 size-4 shrink-0 text-crit" aria-hidden="true" />
          <div>
            {error.message}
            {error.requestId ? <span className="mt-0.5 block text-caption text-ink-2">Request ID <span className="mono select-all">{error.requestId}</span></span> : null}
          </div>
        </div>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy || !email || !password} className="mt-1 h-9 w-full text-[13.5px]">
        {busy ? "Signing in…" : "Sign in"}
      </Button>
      <p className="text-center text-caption text-ink-2">
        Accounts are created by an administrator. Forgot your password? Ask your admin to reset it.
      </p>
    </form>
  );
}

const FEATURES = [
  { icon: ChartBarIcon, title: "Monitor", text: "Request rate, errors and latency from OpenTelemetry, with live charts." },
  { icon: BellAlertIcon, title: "Alert", text: "Threshold, absence and anomaly rules with evidence and webhook delivery." },
  { icon: ShieldCheckIcon, title: "Scan", text: "Vulnerable and outdated dependencies plus risky code, with reviewable fix PRs." },
];

function Logo() {
  return (
    <span aria-hidden="true" className="grid size-8 place-items-center rounded-[8px] bg-primary text-on-primary shadow-card">
      <svg viewBox="0 0 16 16" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1.5 9h2.5l1.75-4.5 2.5 8 1.75-5.5 1 2h3.5" />
      </svg>
    </span>
  );
}

export default function LoginPage() {
  return (
    <main id="main" className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section aria-label="About the toolkit"
        className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-70"
          style={{ background: "radial-gradient(60% 50% at 20% 10%, color-mix(in srgb, var(--primary) 22%, transparent), transparent 70%), radial-gradient(50% 40% at 90% 90%, color-mix(in srgb, var(--primary) 12%, transparent), transparent 70%)" }} />
        <div className="relative flex items-center gap-3">
          <Logo />
          <span className="text-[15px] font-semibold">SRE + Code Health</span>
        </div>
        <div className="relative max-w-md">
          <h2 className="text-[28px] font-semibold leading-tight tracking-[-0.025em]">
            Runtime health and code health, in one place.
          </h2>
          <p className="mt-3 text-ink-2">A self-hosted toolkit for small teams that run services and maintain the code behind them.</p>
          <ul className="mt-8 flex flex-col gap-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-3.5">
                <span className="grid size-8 shrink-0 place-items-center rounded-control border border-line-strong bg-surface-2 text-accent">
                  <f.icon className="size-4" aria-hidden="true" />
                </span>
                <span>
                  <span className="block text-[13.5px] font-medium">{f.title}</span>
                  <span className="block text-[13px] text-ink-2">{f.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-caption text-ink-3">AI suggestions are advisory and validated against evidence. The toolkit never merges code.</p>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-[360px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logo />
            <span className="text-[15px] font-semibold">SRE + Code Health</span>
          </div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Sign in</h1>
          <p className="mb-6 mt-1 text-ink-2">Welcome back. Enter your work email and password.</p>
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
