// Formatting helpers. Canonical units on the wire, human units on screen (UI_UX_SPEC §9).

export type Zone = "local" | "utc";

export function formatTime(iso: string | null | undefined, zone: Zone = "local", withSeconds = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    timeZone: zone === "utc" ? "UTC" : undefined,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

export function bothZones(iso: string | null | undefined): string {
  if (!iso) return "";
  return `${formatTime(iso, "utc", true)} UTC, ${formatTime(iso, "local", true)} local`;
}

export function zoneLabel(zone: Zone): string {
  if (zone === "utc") return "UTC";
  const offset = -new Date().getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "−";
  const abs = Math.abs(offset);
  return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 0) return "just now";
  if (s < 45) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${Number(seconds.toFixed(1))} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}

export function formatMetric(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "ratio":
      return `${(value * 100).toFixed(value < 0.1 ? 2 : 1)}%`;
    case "seconds":
      return value < 1 ? `${Math.round(value * 1000)} ms` : `${value.toFixed(2)} s`;
    case "requests_per_second":
      return `${value < 10 ? value.toFixed(2) : value.toFixed(1)} req/s`;
    default:
      return String(value);
  }
}

export const METRIC_UNITS: Record<string, string> = {
  request_rate: "requests_per_second",
  error_ratio: "ratio",
  latency_p50: "seconds",
  latency_p95: "seconds",
  latency_p99: "seconds",
  data_absent: "seconds",
};

export const METRIC_LABELS: Record<string, string> = {
  request_rate: "Request rate",
  error_ratio: "Error ratio",
  latency_p50: "Latency p50",
  latency_p95: "Latency p95",
  latency_p99: "Latency p99",
  data_absent: "No data",
};

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "—";
}

export function sentence(value: string | null | undefined): string {
  if (!value) return "";
  const s = value.replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function plural(n: number, word: string, pluralWord = `${word}s`): string {
  return `${n} ${n === 1 ? word : pluralWord}`;
}

const PROVIDERS: Record<string, string> = { osv: "OSV", registry: "Registry", semgrep: "Semgrep", trivy: "Trivy" };

/** Display name for a scan provider ("osv" → "OSV"). */
export function providerName(name: string): string {
  return PROVIDERS[name] ?? sentence(name);
}

/** Provider run status label ("ok" → "OK"). */
export function providerStatus(status: string): string {
  return status === "ok" ? "OK" : sentence(status);
}
