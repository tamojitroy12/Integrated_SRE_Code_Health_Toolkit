"use client";

import { CheckIcon, ClipboardDocumentIcon } from "@heroicons/react/20/solid";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { bothZones, shortSha, timeAgo } from "@/lib/format";
import { useNow } from "@/lib/hooks";

import { useToast } from "./toast";

/** In-page tabs between sibling views (Alerts: Active | Rules; Code health: ...). */
export function SegmentedNav({ items }: { items: { href: string; label: string; exact?: boolean }[] }) {
  const path = usePathname();
  return (
    <nav aria-label="Section" className="chrome mb-6 flex flex-wrap gap-5 border-b border-line">
      {items.map((item) => {
        const active = item.exact ? path === item.href : path === item.href || path.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "hit -mb-px inline-flex h-9 items-center border-b-2 text-[13.5px] font-medium transition-colors duration-150",
              active ? "border-ink text-ink" : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SegmentedControl<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="chrome inline-flex h-8 items-center rounded-control border border-line bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "hit h-full rounded-[5px] px-2.5 text-[12.5px] font-medium transition-colors duration-150",
            value === o.value ? "bg-surface text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  return (
    <button
      type="button"
      aria-label={label}
      className={cn("chrome hit inline-grid size-7 place-items-center rounded-control text-ink-2 hover:bg-surface-2 hover:text-ink", className)}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          toast.show("Copied to clipboard.");
          setTimeout(() => setCopied(false), 1500);
        } catch {
          toast.show("Copy failed: clipboard not available.", { tone: "error" });
        }
      }}
    >
      {copied ? <CheckIcon className="size-3.5 text-ok" aria-hidden="true" /> : <ClipboardDocumentIcon className="size-3.5" aria-hidden="true" />}
    </button>
  );
}

/** 7-character SHA display; the copy button copies all 40 characters (UI_UX_SPEC §9). */
export function Sha({ sha }: { sha: string | null | undefined }) {
  if (!sha) return <span className="text-ink-2">—</span>;
  return (
    <span className="inline-flex items-center gap-0.5">
      <span className="mono" title={sha}>{shortSha(sha)}</span>
      <CopyButton text={sha} label="Copy full commit SHA" />
    </span>
  );
}

export function TimeAgo({ iso }: { iso: string | null | undefined }) {
  const now = useNow();
  if (!iso) return <span className="text-ink-2">never</span>;
  return (
    <time dateTime={iso} title={bothZones(iso)}>
      {now === null ? "" : timeAgo(iso, now)}
    </time>
  );
}

export function CodeBlock({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <pre
      aria-label={label}
      className={cn("mono scroll-thin max-h-[480px] overflow-auto rounded-control border border-line bg-surface-2 p-3.5 text-[12.5px] leading-relaxed whitespace-pre", className)}
    >
      {children}
    </pre>
  );
}

/** Unified diff viewer: text is rendered as text (never HTML), lines coloured by prefix. */
export function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <div className="scroll-thin max-h-[640px] overflow-auto rounded-control border border-line bg-surface-2" role="region" aria-label="Unified diff">
      <pre className="mono min-w-max p-4 text-[12.5px] leading-[1.6]">
        {lines.map((line, i) => {
          const cls = line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff --git")
            ? "font-semibold text-ink"
            : line.startsWith("@@")
              ? "text-accent"
              : line.startsWith("+")
                ? "bg-ok/[var(--tint)] text-ok"
                : line.startsWith("-")
                  ? "bg-crit/[var(--tint)] text-crit"
                  : "text-ink-2";
          return (
            <div key={i} className={cls}>
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

export function Disclosure({ summary, count, children, defaultOpen = false }: {
  summary: string;
  count?: number;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  // Collapsed sections always show an explicit item count (UI_UX_SPEC §1, tier 2).
  return (
    <details open={defaultOpen} className="group rounded-panel border border-line bg-surface">
      <summary className="chrome hit flex h-10 cursor-pointer list-none items-center justify-between px-4 text-[13.5px] font-medium">
        <span>
          {summary}
          {count !== undefined ? ` (${count} ${count === 1 ? "item" : "items"})` : ""}
        </span>
        <span aria-hidden="true" className="text-ink-2 transition-transform duration-200 group-open:rotate-90">›</span>
      </summary>
      <div className="border-t border-line p-4">{children}</div>
    </details>
  );
}

/** Accessible on/off switch (role="switch"); the label is announced, the state is aria-checked. */
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("chrome hit relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-150 disabled:opacity-50",
        checked ? "border-primary bg-primary" : "border-line-strong bg-surface-3")}
    >
      <span aria-hidden="true" className={cn("size-3.5 rounded-full bg-white shadow-card transition-transform duration-150",
        checked ? "translate-x-[18px]" : "translate-x-[2px]")} />
    </button>
  );
}
