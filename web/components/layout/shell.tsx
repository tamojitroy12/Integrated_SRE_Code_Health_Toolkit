"use client";

import { Bars3Icon, XMarkIcon } from "@heroicons/react/20/solid";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/states";
import { useAuth } from "@/lib/auth";

import { CommandPalette } from "./command-palette";
import { SidebarContent, useProjectId } from "./sidebar";

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  // Only at depth ≥ 2; the last item is plain text with aria-current.
  if (items.length < 2) return null;
  return (
    <nav aria-label="Breadcrumb" className="mb-3 text-[13px] text-ink-2">
      <ol className="flex flex-wrap items-center gap-1.5">
        {items.map((item, i) => (
          <li key={`${item.label}-${i}`} className="flex min-w-0 items-center gap-1.5">
            {i > 0 ? <span aria-hidden="true" className="text-ink-3">/</span> : null}
            {item.href && i < items.length - 1 ? (
              <Link href={item.href} className="max-w-[24ch] truncate transition-colors hover:text-ink">{item.label}</Link>
            ) : (
              <span aria-current={i === items.length - 1 ? "page" : undefined} className="max-w-[40ch] truncate text-ink">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Client-side auth guard plus chrome for every signed-in page: sidebar on desktop, drawer on mobile. */
export function AppShell({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const pid = useProjectId();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);
  // Close the drawer on navigation (derived during render, not in an effect).
  const [drawerPath, setDrawerPath] = useState(path);
  if (drawerPath !== path) {
    setDrawerPath(path);
    setDrawer(false);
  }
  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [status, router, path]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-dvh" role="status" aria-label="Loading">
        <div className="w-60 shrink-0 border-r border-line bg-surface max-lg:hidden" />
        <div className="flex-1 px-8 py-8 max-md:px-4">
          <Skeleton className="mb-6 h-7 w-48" />
          <Skeleton className="mb-3 h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }
  const openSearch = () => {
    setDrawer(false);
    setPaletteOpen(true);
  };
  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-30 w-60 border-r border-line bg-surface max-lg:hidden">
        <SidebarContent onSearch={openSearch} />
      </aside>
      {/* No backdrop-filter here: it would become the containing block of the fixed drawer below. */}
      <header className="sticky top-0 z-40 border-b border-line bg-surface lg:hidden">
        <div className="flex h-14 items-center gap-3 px-4">
          <button
            type="button"
            aria-expanded={drawer}
            aria-controls="mobile-nav"
            onClick={() => setDrawer(!drawer)}
            className="chrome hit inline-flex h-8 items-center gap-1.5 rounded-control border border-line-strong px-2.5 text-[13px] font-medium"
          >
            {drawer ? <XMarkIcon className="size-4" aria-hidden="true" /> : <Bars3Icon className="size-4" aria-hidden="true" />}
            Menu
          </button>
          <Link href="/projects" className="chrome truncate text-[13.5px] font-semibold">SRE + Code Health</Link>
        </div>
        {drawer ? (
          <>
            <div className="fixed inset-0 top-14 z-40 bg-black/40" aria-hidden="true" onClick={() => setDrawer(false)} />
            <div id="mobile-nav" className="pop-in fixed bottom-0 left-0 top-14 z-50 w-72 max-w-[85vw] border-r border-line bg-surface">
              <SidebarContent onSearch={openSearch} brand={false} />
            </div>
          </>
        ) : null}
      </header>
      <main id="main" className="lg:pl-60">
        <div className="page-enter mx-auto w-full max-w-[1320px] px-8 py-7 max-md:px-4 max-md:py-5">{children}</div>
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} projectId={pid} />
    </div>
  );
}
