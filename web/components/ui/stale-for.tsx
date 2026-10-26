"use client";

import { useNow } from "@/lib/hooks";

/** "No samples received for N minutes." computed from the shared clock (pure during render). */
export function StaleFor({ since }: { since: string | null }) {
  const now = useNow();
  if (!since || now === null) return <>No samples received recently.</>;
  const minutes = Math.max(1, Math.round((now - new Date(since).getTime()) / 60000));
  return <>No samples received for {minutes} minutes.</>;
}
