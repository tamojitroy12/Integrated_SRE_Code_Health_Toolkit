"use client";

import {
  ArrowLeftStartOnRectangleIcon,
  BellAlertIcon,
  ChartBarIcon,
  ChevronLeftIcon,
  ChevronUpDownIcon,
  Cog6ToothIcon,
  ComputerDesktopIcon,
  FolderIcon,
  MagnifyingGlassIcon,
  MoonIcon,
  ShieldCheckIcon,
  Squares2X2Icon,
  SunIcon,
  UsersIcon,
} from "@heroicons/react/16/solid";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore, type ComponentType, type SVGProps } from "react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useNow, useProjectSummary } from "@/lib/hooks";
import { useProject } from "@/lib/project";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const noopSubscribe = () => () => {};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function useProjectId(): string | undefined {
  const path = usePathname();
  const parts = path.split("/");
  return parts[1] === "projects" && parts[2] && UUID.test(parts[2]) ? parts[2] : undefined;
}

function projectNav(pid: string): { href: string; label: string; icon: Icon; match: (p: string) => boolean }[] {
  const base = `/projects/${pid}`;
  return [
    { href: base, label: "Overview", icon: Squares2X2Icon, match: (p) => p === base },
    { href: `${base}/monitoring`, label: "Monitoring", icon: ChartBarIcon, match: (p) => p.startsWith(`${base}/monitoring`) },
    { href: `${base}/alerts`, label: "Alerts", icon: BellAlertIcon, match: (p) => p.startsWith(`${base}/alerts`) },
    { href: `${base}/code-health`, label: "Code health", icon: ShieldCheckIcon, match: (p) => p.startsWith(`${base}/code-health`) },
    { href: `${base}/settings`, label: "Settings", icon: Cog6ToothIcon, match: (p) => p.startsWith(`${base}/settings`) },
  ];
}

export const navItemClass = (active: boolean) =>
  cn(
    "chrome hit group flex h-8 items-center gap-2.5 rounded-control px-2.5 text-[13.5px] font-medium transition-colors duration-150",
    active ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
  );

function NavLink({ href, label, icon: IconCmp, active, children }: {
  href: string;
  label: string;
  icon: Icon;
  active: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Link href={href} aria-current={active ? "page" : undefined} className={navItemClass(active)}>
      <IconCmp className={cn("size-4 shrink-0", active ? "text-ink" : "text-ink-3 group-hover:text-ink-2")} aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {children}
    </Link>
  );
}

function AlertCount({ projectId }: { projectId: string }) {
  const { data, stale, dataUpdatedAt } = useProjectSummary(projectId);
  const now = useNow();
  if (!data) return null;
  if (stale && now !== null) {
    const mins = Math.max(1, Math.round((now - dataUpdatedAt) / 60000));
    return <span className="text-[11px] text-ink-3" title="Counts could not be refreshed">Stale · {mins}m</span>;
  }
  const n = data.unacknowledged_alerts_count;
  if (!n) return null;
  return (
    <span aria-label={`${n} unacknowledged alerts`} className="rounded-[5px] bg-crit/[var(--tint)] px-1.5 text-[11px] font-semibold leading-[18px] text-crit">
      {n > 99 ? "99+" : n}
    </span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="px-2.5 pb-1 pt-4 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{children}</div>;
}

function ProjectBlock({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const name = project.data?.name;
  return (
    <div className="mt-4">
      <Link href="/projects" className="chrome hit mb-1 inline-flex h-6 items-center gap-1 rounded-control px-1.5 text-[12px] text-ink-3 hover:text-ink">
        <ChevronLeftIcon className="size-3.5" aria-hidden="true" /> All projects
      </Link>
      <div className="flex items-center gap-2.5 rounded-control px-2.5 py-1.5">
        <span aria-hidden="true" className="grid size-6 shrink-0 place-items-center rounded-[5px] bg-primary/20 text-[11px] font-semibold text-accent">
          {(name ?? "·").slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-semibold" title={name}>{name ?? "Loading…"}</span>
          {project.data?.archived_at ? <span className="block text-[11px] text-ink-3">Archived</span> : null}
        </span>
      </div>
    </div>
  );
}

type ThemeChoice = "system" | "light" | "dark";

function setTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    if (choice === "system") localStorage.removeItem("toolkit.theme");
    else localStorage.setItem("toolkit.theme", choice);
  } catch {
    /* not persisted */
  }
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [theme, setThemeState] = useState<ThemeChoice>(() =>
    typeof document === "undefined" ? "system" : ((document.documentElement.dataset.theme as ThemeChoice | undefined) ?? "system"));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const initials = (user?.display_name ?? "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const themes: { value: ThemeChoice; label: string; icon: Icon }[] = [
    { value: "system", label: "System", icon: ComputerDesktopIcon },
    { value: "light", label: "Light", icon: SunIcon },
    { value: "dark", label: "Dark", icon: MoonIcon },
  ];
  return (
    <div ref={ref} className="relative">
      {open ? (
        <div className="pop-in absolute inset-x-0 bottom-full z-50 mb-2 rounded-panel border border-line-strong bg-surface p-1 shadow-pop">
          <div className="px-2.5 py-2">
            <p className="truncate text-[13px] font-medium">{user?.display_name}</p>
            <p className="truncate text-[12px] text-ink-2">{user?.email}</p>
          </div>
          <div className="my-1 border-t border-line" />
          <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-ink-3">Theme</div>
          <div role="radiogroup" aria-label="Theme" className="mx-1.5 mb-1.5 grid grid-cols-3 gap-0.5 rounded-control border border-line bg-surface-2 p-0.5">
            {themes.map((t) => (
              <button key={t.value} type="button" role="radio" aria-checked={theme === t.value}
                onClick={() => { setTheme(t.value); setThemeState(t.value); }}
                className={cn("chrome flex h-7 items-center justify-center gap-1 rounded-[5px] text-[12px] font-medium",
                  theme === t.value ? "bg-surface text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:text-ink")}>
                <t.icon className="size-3.5" aria-hidden="true" />{t.label}
              </button>
            ))}
          </div>
          <div className="my-1 border-t border-line" />
          <button
            type="button"
            className="chrome hit flex h-8 w-full items-center gap-2.5 rounded-control px-2.5 text-left text-[13px] text-ink-2 hover:bg-surface-2 hover:text-ink"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
          >
            <ArrowLeftStartOnRectangleIcon className="size-4" aria-hidden="true" /> Sign out
          </button>
        </div>
      ) : null}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="chrome hit flex h-11 w-full items-center gap-2.5 rounded-control px-2 text-left hover:bg-surface-2"
      >
        <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-semibold text-ink-2">
          {initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{user?.display_name}</span>
          <span className="block truncate text-[11.5px] capitalize text-ink-3">{user?.role}</span>
        </span>
        <span className="sr-only">, account menu</span>
        <ChevronUpDownIcon className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
      </button>
    </div>
  );
}

/** Navigation column shared by the desktop sidebar and the mobile drawer. */
export function SidebarContent({ onSearch, brand = true }: { onSearch: () => void; brand?: boolean }) {
  const path = usePathname();
  const pid = useProjectId();
  const { can } = useAuth();
  const mac = useSyncExternalStore(noopSubscribe, () => /Mac|iPhone|iPad/.test(navigator.platform), () => false);
  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-14 shrink-0 items-center gap-2.5 px-4", !brand && "hidden")}>
        <Link href="/projects" className="chrome flex items-center gap-2.5 rounded-control">
          <span aria-hidden="true" className="grid size-7 place-items-center rounded-[7px] bg-primary text-on-primary shadow-card">
            <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1.5 9h2.5l1.75-4.5 2.5 8 1.75-5.5 1 2h3.5" />
            </svg>
          </span>
          <span className="text-[13.5px] font-semibold tracking-[-0.01em]">SRE + Code Health</span>
        </Link>
      </div>
      <div className={cn("px-3", !brand && "pt-3")}>
        <button
          type="button"
          onClick={onSearch}
          className="chrome hit flex h-8 w-full items-center gap-2 rounded-control border border-line bg-surface-2/60 px-2.5 text-[13px] text-ink-3 transition-colors hover:border-line-strong hover:text-ink-2"
        >
          <MagnifyingGlassIcon className="size-4" aria-hidden="true" />
          <span className="flex-1 text-left">Search</span>
          <kbd className="mono rounded-[4px] border border-line bg-surface px-1.5 text-[10.5px] leading-[18px] text-ink-3">{mac ? "⌘K" : "Ctrl K"}</kbd>
        </button>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <nav aria-label="Workspace" className="mt-3 flex flex-col gap-0.5">
          <NavLink href="/projects" label="Projects" icon={FolderIcon} active={path === "/projects" || path === "/projects/new"} />
          {can("admin") ? <NavLink href="/admin" label="Admin" icon={UsersIcon} active={path.startsWith("/admin")} /> : null}
        </nav>
        {pid ? (
          <>
            <ProjectBlock projectId={pid} />
            <nav aria-label="Project" className="flex flex-col gap-0.5">
              {projectNav(pid).map((item) => (
                <NavLink key={item.href} href={item.href} label={item.label} icon={item.icon} active={item.match(path)}>
                  {item.label === "Alerts" ? <AlertCount projectId={pid} /> : null}
                </NavLink>
              ))}
            </nav>
          </>
        ) : null}
        {!pid ? <SectionLabel>Toolkit</SectionLabel> : null}
        {!pid ? (
          <p className="px-2.5 text-[12px] leading-relaxed text-ink-3">
            Self-hosted runtime and repository health. AI output is advisory; the toolkit never merges.
          </p>
        ) : null}
      </div>
      <div className="shrink-0 border-t border-line p-2">
        <AccountMenu />
      </div>
    </div>
  );
}
