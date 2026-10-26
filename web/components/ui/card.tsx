import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

/** Bordered surface for a self-contained region. */
export function Card({ className, children, ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn("min-w-0 rounded-panel border border-line bg-surface p-5 shadow-card max-md:p-4", className)} {...rest}>
      {children}
    </section>
  );
}

export function CardHeader({ title, status, action, subtitle, as: Tag = "h2" }: {
  title: ReactNode;
  status?: ReactNode;
  action?: ReactNode;
  subtitle?: ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <header className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Tag className="text-title font-semibold">{title}</Tag>
          {status}
        </div>
        {subtitle ? <p className="mt-0.5 text-caption text-ink-2">{subtitle}</p> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </header>
  );
}

/** Small "View all →" style link used in card headers. */
export function CardLink({ children }: { children: ReactNode }) {
  return <span className="text-[13px] font-medium text-ink-2 transition-colors hover:text-ink">{children}</span>;
}

export function PageHeader({ title, subtitle, actions, meta, eyebrow }: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1 text-caption font-medium text-ink-2">{eyebrow}</div> : null}
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.02em] max-md:text-[20px]">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-[72ch] text-ink-2">{subtitle}</p> : null}
        {meta ? <div className="mt-3">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** Hairline-divided metadata list for runs of 4+ items. */
export function MetaList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-x-6 gap-y-3">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-caption text-ink-2">{item.label}</dt>
          <dd className="mt-0.5 truncate font-medium">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Compact numeric tile: label, value, optional context line. */
export function Stat({ label, value, hint, tone }: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "critical" | "warning" | "healthy";
}) {
  const toneClass = tone === "critical" ? "text-crit" : tone === "warning" ? "text-warn" : tone === "healthy" ? "text-ok" : "";
  return (
    <div className="min-w-0 rounded-control border border-line bg-surface-2/50 px-3.5 py-3">
      <div className="truncate text-caption text-ink-2">{label}</div>
      <div className={cn("tabular mt-1 text-[20px] font-semibold leading-none tracking-[-0.02em]", toneClass)}>{value}</div>
      {hint ? <div className="mt-1.5 truncate text-caption text-ink-2">{hint}</div> : null}
    </div>
  );
}
