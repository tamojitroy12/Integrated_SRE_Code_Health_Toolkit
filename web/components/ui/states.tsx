"use client";

import { ArrowPathIcon, ExclamationTriangleIcon, InformationCircleIcon, XCircleIcon } from "@heroicons/react/20/solid";
import type { ComponentType, ReactNode, SVGProps } from "react";

import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("skeleton rounded-control", className)} />;
}

/** Content-shaped loading placeholder; no spinners. */
export function LoadingRows({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20 max-sm:hidden" />
        </div>
      ))}
    </div>
  );
}

export function LoadingBlock({ height = "h-40", label = "Loading" }: { height?: string; label?: string }) {
  return (
    <div role="status" aria-label={label}>
      <Skeleton className={cn("w-full", height)} />
    </div>
  );
}

export function EmptyState({ title, children, action, className, icon: Icon }: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
}) {
  return (
    <div className={cn("flex flex-col items-center rounded-panel border border-dashed border-line-strong px-6 py-8 text-center", className)}>
      {Icon ? (
        <span className="mb-3 grid size-9 place-items-center rounded-control border border-line bg-surface-2 text-ink-2">
          <Icon className="size-5" aria-hidden="true" />
        </span>
      ) : null}
      <p className="text-[13.5px] font-medium">{title}</p>
      {children ? <div className="mt-1 max-w-[56ch] text-[13px] text-ink-2">{children}</div> : null}
      {action ? <div className="mt-4 flex justify-center gap-2">{action}</div> : null}
    </div>
  );
}

export function errorText(error: unknown): { message: string; requestId: string | null; code: string | null } {
  if (error instanceof ApiError) return { message: error.message, requestId: error.requestId, code: error.code };
  if (error instanceof Error) return { message: error.message, requestId: null, code: null };
  return { message: "Something went wrong.", requestId: null, code: null };
}

/** Every error ends with a next step and a selectable request ID. */
export function ErrorState({ error, title, onRetry, hint, className }: {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  hint?: ReactNode;
  className?: string;
}) {
  const { message, requestId, code } = errorText(error);
  return (
    <div role="alert" className={cn("flex gap-3 rounded-panel border border-crit/[var(--tint-border)] bg-crit/[var(--tint)] px-4 py-3", className)}>
      <XCircleIcon className="mt-0.5 size-4 shrink-0 text-crit" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{title ?? message}</p>
        {title ? <p className="mt-0.5 text-[13px] text-ink-2">{message}</p> : null}
        {hint ? <div className="mt-0.5 text-[13px] text-ink-2">{hint}</div> : null}
        {onRetry || code || requestId ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            {onRetry ? (
              <Button size="sm" onClick={onRetry} icon={<ArrowPathIcon />}>
                Retry
              </Button>
            ) : null}
            {code ? <span className="mono text-caption text-ink-2">{code}</span> : null}
            {requestId ? (
              <span className="text-caption text-ink-2">
                Request ID <span className="mono select-all text-ink">{requestId}</span>
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const BANNER = {
  warning: { cls: "border-warn/[var(--tint-border)] bg-warn/[var(--tint)]", icon: ExclamationTriangleIcon, iconCls: "text-warn" },
  critical: { cls: "border-crit/[var(--tint-border)] bg-crit/[var(--tint)]", icon: XCircleIcon, iconCls: "text-crit" },
  info: { cls: "border-line-strong bg-surface-2", icon: InformationCircleIcon, iconCls: "text-ink-2" },
};

/** Persistent, non-collapsible banner for partial/unverified/stale states. */
export function Banner({ tone = "warning", children, role = "status" }: {
  tone?: "warning" | "critical" | "info";
  children: ReactNode;
  role?: "status" | "alert";
}) {
  const b = BANNER[tone];
  const Icon = b.icon;
  return (
    <div role={role} className={cn("flex gap-2.5 rounded-panel border px-3.5 py-2.5 text-[13px]", b.cls)}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", b.iconCls)} aria-hidden="true" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
