"use client";

import { MagnifyingGlassIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useRecents } from "@/lib/hooks";
import type { Severity } from "@/lib/types";

interface SearchResult {
  projects: { id: string; name: string }[];
  findings: { id: string; project_id: string; title: string; severity: Severity | null }[];
  alerts: { id: string; project_id: string; rule_name: string; severity: Severity; status: string }[];
}

interface Item {
  group: string;
  label: string;
  href: string;
  hint?: string;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** ⌘K / Ctrl K palette: recents, grouped results (≤ 5 per group), keyboard navigation. */
export function CommandPalette({ open, onClose, projectId }: { open: boolean; onClose: () => void; projectId?: string }) {
  const router = useRouter();
  const { can } = useAuth();
  const ref = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<"project" | "all">("project");
  const [active, setActive] = useState(0);
  const recents = useRecents("toolkit.palette.recents");
  const debounced = useDebounced(q.trim(), 150);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      setQ("");
      setActive(0);
    } else if (!open && el.open) el.close();
  }, [open]);

  const search = useQuery({
    queryKey: ["search", debounced, scope === "project" ? projectId : null],
    queryFn: () =>
      api<SearchResult>("/search", { query: { q: debounced, project_id: scope === "project" ? projectId : undefined } }),
    enabled: open && debounced.length > 0,
    staleTime: 10_000,
  });

  const items = useMemo<Item[]>(() => {
    const nav: Item[] = [{ group: "Navigate", label: "All projects", href: "/projects" }];
    if (projectId) {
      const base = `/projects/${projectId}`;
      nav.push(
        { group: "Navigate", label: "Overview", href: base },
        { group: "Navigate", label: "Monitoring", href: `${base}/monitoring` },
        { group: "Navigate", label: "Alerts", href: `${base}/alerts` },
        { group: "Navigate", label: "Alert rules", href: `${base}/alerts/rules` },
        { group: "Navigate", label: "Findings", href: `${base}/code-health` },
        { group: "Navigate", label: "Scans", href: `${base}/code-health/scans` },
        { group: "Navigate", label: "Fix proposals", href: `${base}/code-health/fix-proposals` },
        { group: "Navigate", label: "Project settings", href: `${base}/settings` },
      );
    }
    if (can("maintainer")) nav.push({ group: "Navigate", label: "New project", href: "/projects/new" });
    if (can("admin")) nav.push({ group: "Navigate", label: "Admin", href: "/admin" });
    const term = q.trim().toLowerCase();
    if (!term) {
      return recents.items.map((r) => {
        const [label, href] = r.split("\u0000");
        return { group: "Recent", label: label ?? r, href: href ?? "/projects" };
      });
    }
    const navMatches = nav.filter((n) => n.label.toLowerCase().includes(term)).slice(0, 5);
    const data = search.data;
    const results: Item[] = [
      ...navMatches,
      ...(data?.projects ?? []).slice(0, 5).map((p) => ({ group: "Projects", label: p.name, href: `/projects/${p.id}` })),
      ...(data?.findings ?? []).slice(0, 5).map((f) => ({
        group: "Findings", label: f.title, hint: f.severity ?? "unrated",
        href: `/projects/${f.project_id}/code-health/findings/${f.id}`,
      })),
      ...(data?.alerts ?? []).slice(0, 5).map((a) => ({
        group: "Alerts", label: a.rule_name, hint: a.status, href: `/projects/${a.project_id}/alerts/${a.id}`,
      })),
    ];
    return results;
  }, [q, search.data, projectId, can, recents.items]);

  function go(item: Item, newTab = false) {
    recents.push(`${item.label}\u0000${item.href}`);
    if (newTab) window.open(item.href, "_blank", "noopener");
    else router.push(item.href);
    onClose();
  }

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="pop-in mx-auto mt-[12vh] w-[min(620px,calc(100vw-32px))] overflow-hidden rounded-hero border border-line-strong bg-surface p-0 text-ink shadow-pop backdrop:bg-black/50"
      aria-label="Command palette"
    >
      {open ? (
        <div>
          <div className="flex items-center gap-2 border-b border-line px-4">
            <MagnifyingGlassIcon className="size-5 text-ink-3" aria-hidden="true" />
            <input
              autoFocus
              role="combobox"
              aria-expanded="true"
              aria-controls="palette-results"
              aria-activedescendant={items[active] ? `palette-${active}` : undefined}
              placeholder="Search projects, findings, alerts, pages…"
              className="h-13 min-h-13 flex-1 bg-transparent text-[15px] outline-none placeholder:text-ink-3"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((a) => Math.min(items.length - 1, a + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((a) => Math.max(0, a - 1));
                } else if (e.key === "Enter" && items[active]) {
                  e.preventDefault();
                  go(items[active]!, e.metaKey || e.ctrlKey);
                }
              }}
            />
            {projectId ? (
              <button
                type="button"
                onClick={() => setScope(scope === "project" ? "all" : "project")}
                className={cn("chrome hit h-7 rounded-control border px-2.5 text-[12px] font-medium",
                  scope === "all" ? "border-accent/[var(--tint-border)] bg-accent/[var(--tint)] text-accent" : "border-line-strong text-ink-2 hover:text-ink")}
              >
                {scope === "all" ? "All projects" : "This project"}
              </button>
            ) : null}
          </div>
          <ul id="palette-results" role="listbox" className="scroll-thin max-h-[50vh] overflow-auto p-1.5">
            {!q.trim() && recents.items.length ? (
              <li className="flex items-center justify-between px-3 pb-1 pt-2 text-caption text-ink-2">
                Recent
                <button type="button" className="chrome hit h-7 rounded-control px-2 hover:text-ink" onClick={recents.clear}>Clear</button>
              </li>
            ) : null}
            {q.trim() && search.isFetching && !search.data
              ? [0, 1, 2].map((i) => <li key={i} className="skeleton mx-3 my-2 h-8 rounded-control" aria-hidden="true" />)
              : null}
            {items.map((item, i) => {
              const header = item.group !== "Recent" && (i === 0 || items[i - 1]!.group !== item.group) ? item.group : null;
              return (
                <li key={`${item.group}-${item.href}-${i}`} className="list-none">
                  {header ? <div className="px-3 pb-1 pt-3 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{header}</div> : null}
                  <div
                    id={`palette-${i}`}
                    role="option"
                    aria-selected={i === active}
                    tabIndex={-1}
                    onMouseEnter={() => setActive(i)}
                    onClick={(e) => go(item, e.metaKey || e.ctrlKey)}
                    className={cn("chrome flex h-9 cursor-pointer items-center justify-between gap-3 rounded-control px-3 text-[13.5px]",
                      i === active ? "bg-surface-3 text-ink" : "text-ink-2")}
                  >
                    <span className="truncate">{item.label}</span>
                    {item.hint ? <span className="shrink-0 text-caption text-ink-2">{item.hint}</span> : null}
                  </div>
                </li>
              );
            })}
            {q.trim() && !items.length && !search.isFetching ? (
              <li className="px-3 py-6 text-center text-ink-2">
                {search.isError ? "Search is unavailable; page shortcuts still work." : "No matches."}
              </li>
            ) : null}
          </ul>
          <div id="palette-footer" className="flex items-center gap-4 border-t border-line bg-surface-2/50 px-4 py-2 text-[11.5px] text-ink-3">
            <span><kbd className="mono">↑</kbd> <kbd className="mono">↓</kbd> to move</span>
            <span><kbd className="mono">Enter</kbd> to open</span>
            <span><kbd className="mono">Esc</kbd> to close</span>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
