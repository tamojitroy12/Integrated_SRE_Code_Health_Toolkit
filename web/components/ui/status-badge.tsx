import {
  CheckCircleIcon,
  ClockIcon,
  ExclamationTriangleIcon,
  MinusCircleIcon,
  NoSymbolIcon,
  QuestionMarkCircleIcon,
  ShieldExclamationIcon,
  XCircleIcon,
} from "@heroicons/react/20/solid";
import type { ComponentType, ReactNode, SVGProps } from "react";

import { cn } from "@/lib/cn";
import { sentence } from "@/lib/format";
import type { AlertStatus, JobStatus, Severity, TargetStatus, ValidationResult, ValidationStatus } from "@/lib/types";

export type Tone = "critical" | "warning" | "healthy" | "neutral" | "info";
type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const toneClass: Record<Tone, string> = {
  critical: "text-crit bg-crit/[var(--tint)] border-crit/[var(--tint-border)]",
  warning: "text-warn bg-warn/[var(--tint)] border-warn/[var(--tint-border)]",
  healthy: "text-ok bg-ok/[var(--tint)] border-ok/[var(--tint-border)]",
  info: "text-accent bg-accent/[var(--tint)] border-accent/[var(--tint-border)]",
  neutral: "text-ink-2 bg-surface-2 border-line-strong",
};

/** Icon + word + tinted surface; never colour alone, never a solid fill. */
export function StatusBadge({ tone, icon: IconCmp, children, title, className }: {
  tone: Tone;
  icon?: Icon;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "chrome inline-flex h-5 items-center gap-1 rounded-[5px] border px-1.5 text-[11.5px] font-medium leading-none whitespace-nowrap",
        toneClass[tone],
        className,
      )}
    >
      {IconCmp ? <IconCmp className="size-3 shrink-0" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

const SEVERITY_ICON: Record<Severity, Icon> = {
  critical: ShieldExclamationIcon,
  high: ExclamationTriangleIcon,
  medium: ExclamationTriangleIcon,
  low: MinusCircleIcon,
  info: MinusCircleIcon,
};

/** Critical is red, high amber; lower severities are neutral chips with distinct icons. */
export function SeverityBadge({ severity, emphasize = false }: { severity: Severity | null; emphasize?: boolean }) {
  if (!severity) {
    return (
      <StatusBadge tone="neutral" icon={QuestionMarkCircleIcon} title="The source provided no severity.">
        Unrated
      </StatusBadge>
    );
  }
  const tone: Tone = severity === "critical" || (emphasize && severity === "high") ? "critical"
    : severity === "high" ? "warning" : "neutral";
  return (
    <StatusBadge tone={tone} icon={SEVERITY_ICON[severity]}>
      {sentence(severity)}
    </StatusBadge>
  );
}

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  if (status === "firing") return <StatusBadge tone="critical" icon={ExclamationTriangleIcon}>Firing</StatusBadge>;
  if (status === "acknowledged") return <StatusBadge tone="warning" icon={ClockIcon}>Acknowledged</StatusBadge>;
  return <StatusBadge tone="neutral" icon={CheckCircleIcon}>Resolved</StatusBadge>;
}

export function TargetStatusBadge({ status }: { status: TargetStatus }) {
  if (status === "receiving") return <StatusBadge tone="healthy" icon={CheckCircleIcon}>Receiving</StatusBadge>;
  if (status === "stale") return <StatusBadge tone="warning" icon={ExclamationTriangleIcon}>Stale</StatusBadge>;
  return <StatusBadge tone="neutral" icon={ClockIcon}>Waiting for data</StatusBadge>;
}

export function JobStatusBadge({ status }: { status: JobStatus | null | undefined }) {
  switch (status) {
    case "succeeded":
      return <StatusBadge tone="healthy" icon={CheckCircleIcon}>Succeeded</StatusBadge>;
    case "partial":
      return <StatusBadge tone="warning" icon={ExclamationTriangleIcon}>Partial</StatusBadge>;
    case "failed":
      return <StatusBadge tone="critical" icon={XCircleIcon}>Failed</StatusBadge>;
    case "cancelled":
      return <StatusBadge tone="neutral" icon={NoSymbolIcon}>Cancelled</StatusBadge>;
    case "running":
      return <StatusBadge tone="info" icon={ClockIcon}>Running</StatusBadge>;
    case "queued":
      return <StatusBadge tone="neutral" icon={ClockIcon}>Queued</StatusBadge>;
    default:
      return <StatusBadge tone="neutral" icon={MinusCircleIcon}>Never scanned</StatusBadge>;
  }
}

export function ValidationBadge({ status }: { status: ValidationStatus | null }) {
  if (status === "validated") return <StatusBadge tone="healthy" icon={CheckCircleIcon}>Validated</StatusBadge>;
  if (status === "partially_validated")
    return <StatusBadge tone="warning" icon={ExclamationTriangleIcon}>Partially validated</StatusBadge>;
  if (status === "rejected") return <StatusBadge tone="critical" icon={XCircleIcon}>Rejected</StatusBadge>;
  return <StatusBadge tone="neutral" icon={ClockIcon}>Pending</StatusBadge>;
}

export function ResultBadge({ result }: { result: ValidationResult | string | null | undefined }) {
  if (result === "passed") return <StatusBadge tone="healthy" icon={CheckCircleIcon}>Passed</StatusBadge>;
  if (result === "failed") return <StatusBadge tone="critical" icon={XCircleIcon}>Failed</StatusBadge>;
  if (result === "unverified")
    return <StatusBadge tone="warning" icon={ExclamationTriangleIcon}>Unverified</StatusBadge>;
  if (result === "skipped") return <StatusBadge tone="neutral" icon={MinusCircleIcon}>Skipped</StatusBadge>;
  if (result === "error") return <StatusBadge tone="critical" icon={XCircleIcon}>Error</StatusBadge>;
  return <StatusBadge tone="neutral" icon={ClockIcon}>Not run</StatusBadge>;
}

export function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("chrome inline-flex h-5 items-center rounded-[5px] border border-line-strong bg-surface-2 px-1.5 " +
      "text-[11.5px] font-medium leading-none text-ink-2", className)}>
      {children}
    </span>
  );
}
