"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { api } from "./api";
import type { Job, Summary } from "./types";

export const TERMINAL = new Set(["succeeded", "partial", "failed", "cancelled"]);

/** Poll GET /jobs/{id}: every 2 s for 30 s, then every 5 s; stop on a terminal state (API_SPEC §4). */
export function useJob(jobId: string | null | undefined, onTerminal?: (job: Job) => void) {
  const qc = useQueryClient();
  const [started] = useState(() => Date.now());
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (status && TERMINAL.has(status)) return false;
      return Date.now() - started < 30_000 ? 2000 : 5000;
    },
  });
  const status = query.data?.status;
  useEffect(() => {
    if (query.data && status && TERMINAL.has(status)) {
      onTerminal?.(query.data);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "job" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  return query;
}

function subscribeVisibility(cb: () => void): () => void {
  document.addEventListener("visibilitychange", cb);
  return () => document.removeEventListener("visibilitychange", cb);
}

export function usePageVisible(): boolean {
  return useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState === "visible",
    () => true,
  );
}

/** One per-project summary poll (15 s while visible, backoff on errors) shared by the sidebar and overview. */
export function useProjectSummary(projectId: string | undefined) {
  const visible = usePageVisible();
  const query = useQuery({
    queryKey: ["summary", projectId],
    queryFn: () => api<Summary>(`/projects/${projectId}/summary`),
    enabled: !!projectId,
    refetchOnWindowFocus: true,
    refetchInterval: (q) => {
      if (!visible) return false;
      const failures = q.state.fetchFailureCount;
      return failures ? Math.min(120_000, 15_000 * 2 ** failures) : 15_000;
    },
    retry: false,
  });
  const now = useNow();
  const stale = !!query.dataUpdatedAt && now !== null && now - query.dataUpdatedAt > 60_000;
  return { ...query, stale };
}

const PREF_EVENT = "toolkit-preference";

function storageFor(kind: "local" | "session"): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function subscribePrefs(cb: () => void): () => void {
  window.addEventListener("storage", cb);
  window.addEventListener(PREF_EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(PREF_EVENT, cb);
  };
}

/** Small per-device preference (never used for secrets or tokens); falls back when storage is unavailable. */
export function usePreference<T>(key: string, fallback: T, storage: "local" | "session" = "local") {
  const raw = useSyncExternalStore(
    subscribePrefs,
    () => {
      try {
        return storageFor(storage)?.getItem(key) ?? null;
      } catch {
        return null;
      }
    },
    () => null,
  );
  const value = useMemo<T>(() => {
    if (raw === null) return fallback;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return fallback;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw]);
  const update = useCallback(
    (next: T) => {
      try {
        storageFor(storage)?.setItem(key, JSON.stringify(next));
      } catch {
        /* storage unavailable (private mode): the preference simply is not remembered */
      }
      window.dispatchEvent(new Event(PREF_EVENT));
    },
    [key, storage],
  );
  return [value, update] as const;
}

// Shared clock for relative times: one interval for the whole app, null during server rendering.
let nowValue = Date.now();
const nowListeners = new Set<() => void>();
let nowTimer: ReturnType<typeof setInterval> | null = null;

function subscribeNow(cb: () => void): () => void {
  nowListeners.add(cb);
  if (!nowTimer) {
    nowValue = Date.now();
    nowTimer = setInterval(() => {
      nowValue = Date.now();
      nowListeners.forEach((l) => l());
    }, 1000);
  }
  return () => {
    nowListeners.delete(cb);
    if (!nowListeners.size && nowTimer) {
      clearInterval(nowTimer);
      nowTimer = null;
    }
  };
}

/** Current time in ms (ticks every second), or null on the server. Pure to read during render. */
export function useNow(): number | null {
  return useSyncExternalStore(subscribeNow, () => nowValue, () => null);
}

export function useRecents(key: string, max = 5) {
  const [items, setItems] = usePreference<string[]>(key, []);
  const push = useCallback(
    (item: string) => setItems([item, ...items.filter((i) => i !== item)].slice(0, max)),
    [items, max, setItems],
  );
  const clear = useCallback(() => setItems([]), [setItems]);
  return { items, push, clear };
}
