// Liberal input parsing with canonical output (Postel's law, UI_UX_SPEC §9).

/** Trim whitespace and strip line breaks / zero-width characters (never used on passwords). */
export function sanitize(value: string): string {
  return value.replace(/[​-‍﻿]/g, "").replace(/[\r\n]+/g, "").trim();
}

/** Accepts org/repo, github.com/org/repo, https URLs (with .git, slashes, /tree/...), and SSH. */
export function normalizeRepo(input: string): { owner: string; name: string; url: string } | null {
  let s = sanitize(input);
  if (!s) return null;
  const ssh = s.match(/^git@github\.com:([^/]+)\/(.+?)(?:\.git)?$/i);
  if (ssh) s = `${ssh[1]}/${ssh[2]}`;
  s = s.replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  if (/^github\.com\//i.test(s)) s = s.slice("github.com/".length);
  else if (s.includes(".") && s.split("/")[0]!.includes(".")) return null; // another host
  const parts = s.split(/[/?#]/).filter(Boolean);
  if (parts.length < 2) return null;
  const owner = parts[0]!;
  const name = parts[1]!.replace(/\.git$/i, "");
  const ok = /^[A-Za-z0-9_.-]+$/;
  if (!ok.test(owner) || !ok.test(name)) return null;
  return { owner, name, url: `https://github.com/${owner}/${name}` };
}

/** "5m", "300s", "1h30m", "90" (seconds) → integer seconds. */
export function parseDuration(input: string): number | null {
  const s = sanitize(input).toLowerCase().replace(/\s+/g, "");
  if (!s) return null;
  if (/^\d+$/.test(s)) return Number(s);
  const re = /(\d+(?:\.\d+)?)(h|m|s)/g;
  let total = 0;
  let consumed = 0;
  for (const m of s.matchAll(re)) {
    const n = Number(m[1]);
    total += m[2] === "h" ? n * 3600 : m[2] === "m" ? n * 60 : n;
    consumed += m[0].length;
  }
  if (consumed !== s.length || total <= 0) return null;
  return Math.round(total);
}

export function describeSeconds(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} ${seconds === 3600 ? "hour" : "hours"} (${seconds} s)`;
  if (seconds % 60 === 0) return `${seconds / 60} ${seconds === 60 ? "minute" : "minutes"} (${seconds} s)`;
  return `${seconds} seconds`;
}

export type RatioParse = { value: number } | { ambiguous: number } | null;

/** "5%" → 0.05; "0.05" → 0.05; bare integers > 1 are ambiguous ("Did you mean 5%?"). */
export function parseRatio(input: string): RatioParse {
  const s = sanitize(input).replace(/\s+/g, "");
  if (!s) return null;
  if (s.endsWith("%")) {
    const n = Number(s.slice(0, -1));
    return Number.isFinite(n) && n >= 0 && n <= 100 ? { value: n / 100 } : null;
  }
  const n = Number(s);
  if (!Number.isFinite(n) || n < 0) return null;
  if (n > 1) return n <= 100 ? { ambiguous: n / 100 } : null;
  return { value: n };
}

/** Latency thresholds: "250ms", "2s", "1.5" (seconds) → seconds. */
export function parseLatency(input: string): number | null {
  const s = sanitize(input).toLowerCase().replace(/\s+/g, "");
  const ms = s.match(/^(\d+(?:\.\d+)?)ms$/);
  if (ms) return Number(ms[1]) / 1000;
  const sec = s.match(/^(\d+(?:\.\d+)?)s?$/);
  if (sec) return Number(sec[1]);
  return null;
}
