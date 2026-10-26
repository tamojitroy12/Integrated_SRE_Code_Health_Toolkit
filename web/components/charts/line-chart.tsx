"use client";

import { useId, useMemo, useRef, useState } from "react";

import { bothZones, formatMetric, formatTime, type Zone, zoneLabel } from "@/lib/format";

export interface ChartSeries {
  label: string;
  points: { t: string; v: number | null }[];
  color?: string;
  dash?: string;
}

const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)"];
const DASHES = ["none", "7 4", "2 4", "9 3 2 3", "1 5"];
const W = 820;
const H = 220;
const PAD = { l: 72, r: 76, t: 16, b: 28 };

/**
 * SVG line chart: gaps for missing samples (never interpolated), quiet axes labelled with the active
 * time zone, direct end labels and distinct dash patterns so colour is never the only signal.
 */
export function LineChart({ series, unit, zone, height = H, title }: {
  series: ChartSeries[];
  unit: string;
  zone: Zone;
  height?: number;
  title: string;
}) {
  const id = useId();
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const { xs, yMax, paths, areas, times } = useMemo(() => {
    const times = series[0]?.points.map((p) => new Date(p.t).getTime()) ?? [];
    const all = series.flatMap((s) => s.points.map((p) => p.v).filter((v): v is number => v !== null));
    const max = all.length ? Math.max(...all) : 1;
    const yMax = max <= 0 ? 1 : unit === "ratio" ? Math.max(0.01, Math.min(1, max * 1.2)) : max * 1.2;
    const t0 = times[0] ?? 0;
    const t1 = times[times.length - 1] ?? 1;
    const span = Math.max(1, t1 - t0);
    const xs = times.map((t) => PAD.l + ((t - t0) / span) * (W - PAD.l - PAD.r));
    const base = (height - PAD.b).toFixed(1);
    const areas: string[] = [];
    const paths = series.map((s, si) => {
      let d = "";
      let area = "";
      let segment: string[] = [];
      const flush = () => {
        if (segment.length > 1) area += `M${segment[0]!.split(",")[0]},${base}L${segment.join("L")}L${segment[segment.length - 1]!.split(",")[0]},${base}Z`;
        segment = [];
      };
      let pen = false;
      s.points.forEach((p, i) => {
        if (p.v === null) {
          pen = false;
          flush();
          return;
        }
        const x = xs[i] ?? PAD.l;
        const y = PAD.t + (1 - p.v / yMax) * (height - PAD.t - PAD.b);
        d += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
        segment.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        pen = true;
      });
      flush();
      if (si === 0) areas.push(area);
      return d;
    });
    return { xs, yMax, paths, areas, times };
  }, [series, unit, height]);

  const yTicks = [0, 0.5, 1].map((f) => ({ v: yMax * f, y: PAD.t + (1 - f) * (height - PAD.t - PAD.b) }));
  const xTickIdx = times.length ? [0, Math.floor((times.length - 1) / 2), times.length - 1] : [];

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const svg = ref.current;
    if (!svg || !xs.length) return;
    const rect = svg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    xs.forEach((px, i) => {
      if (Math.abs(px - x) < Math.abs((xs[best] ?? 0) - x)) best = i;
    });
    setHover(best);
  }

  const hoverIso = hover !== null && times[hover] ? new Date(times[hover]!).toISOString() : null;
  return (
    <figure className="relative min-w-0">
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${height}`}
        className="chrome block h-auto w-full touch-none"
        role="img"
        aria-labelledby={`${id}-t`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <title id={`${id}-t`}>{title}</title>
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={series[0]?.color ?? COLORS[0]} stopOpacity="0.22" />
            <stop offset="100%" stopColor={series[0]?.color ?? COLORS[0]} stopOpacity="0" />
          </linearGradient>
        </defs>
        {yTicks.map((t) => (
          <g key={t.y}>
            <line x1={PAD.l} x2={W - PAD.r} y1={t.y} y2={t.y} stroke="var(--grid)" />
            <text x={PAD.l - 8} y={t.y + 4} textAnchor="end" fontSize="11" fill="var(--ink-2)">
              {formatMetric(t.v, unit)}
            </text>
          </g>
        ))}
        {xTickIdx.map((i, k) => (
          <text key={k} x={xs[i]} y={height - 6} textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"} fontSize="11" fill="var(--ink-2)">
            {times[i] ? formatTime(new Date(times[i]!).toISOString(), zone).split(", ").pop() : ""}
          </text>
        ))}
        <text x={W - PAD.r} y={PAD.t - 2} textAnchor="end" fontSize="10" fill="var(--ink-2)">{zoneLabel(zone)}</text>
        {series.length === 1 && areas[0] ? <path d={areas[0]} fill={`url(#${id}-fill)`} stroke="none" /> : null}
        {paths.map((d, i) => (
          <path
            key={i}
            d={d}
            fill="none"
            stroke={series[i]?.color ?? (i === 0 ? COLORS[0] : series.length >= 3 ? COLORS[i % 5] : "var(--ctx1)")}
            strokeWidth={i === 0 ? 2 : 1.5}
            strokeDasharray={series[i]?.dash ?? DASHES[i % 5]}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {endLabels(series, xs, yMax, height).map((l) => (
          <text key={l.key} x={l.x + 6} y={l.y + 4} fontSize="11" fill="var(--ink-2)">
            {series.length > 1 ? l.label : formatMetric(l.v, unit)}
          </text>
        ))}
        {hover !== null && xs[hover] !== undefined ? (
          <g>
            <line x1={xs[hover]} x2={xs[hover]} y1={PAD.t} y2={height - PAD.b} stroke="var(--line-strong)" />
            {series.map((s, i) => {
              const v = s.points[hover]?.v;
              if (v === null || v === undefined) return null;
              const y = PAD.t + (1 - v / yMax) * (height - PAD.t - PAD.b);
              return <circle key={s.label} cx={xs[hover]} cy={y} r="3.5" fill="var(--surface)" strokeWidth="2"
                stroke={s.color ?? (i === 0 ? COLORS[0] : series.length >= 3 ? COLORS[i % 5] : "var(--ctx1)")} />;
            })}
          </g>
        ) : null}
      </svg>
      {hover !== null && hoverIso ? (
        <figcaption className="pointer-events-none absolute right-2 top-2 min-w-40 rounded-control border border-line-strong bg-surface px-3 py-2 text-caption shadow-pop">
          <div className="text-ink-2">{bothZones(hoverIso)}</div>
          {series.map((s) => (
            <div key={s.label} className="flex justify-between gap-4">
              <span>{s.label}</span>
              <span className="font-medium tabular-nums">{formatMetric(s.points[hover]?.v ?? null, unit)}</span>
            </div>
          ))}
        </figcaption>
      ) : null}
    </figure>
  );
}

/** Direct end-of-line labels, nudged apart vertically so close series never overlap. */
function endLabels(series: ChartSeries[], xs: number[], yMax: number, height: number) {
  const labels = series.flatMap((s) => {
    const lastIdx = s.points.map((p) => p.v).findLastIndex((v) => v !== null);
    if (lastIdx < 0) return [];
    const v = s.points[lastIdx]!.v!;
    return [{ key: s.label, label: s.label, v, x: xs[lastIdx] ?? 0, y: PAD.t + (1 - v / yMax) * (height - PAD.t - PAD.b) }];
  }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) {
    if (labels[i]!.y - labels[i - 1]!.y < 13) labels[i]!.y = labels[i - 1]!.y + 13;
  }
  return labels;
}

export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const nums = values.filter((v): v is number => v !== null);
  const max = nums.length ? Math.max(...nums, 0.0001) : 1;
  const d = values
    .map((v, i) => (v === null ? null : `${i === 0 ? "M" : "L"}${(i / Math.max(1, values.length - 1)) * 100},${28 - (v / max) * 24}`))
    .filter(Boolean)
    .join("");
  return (
    <svg viewBox="0 0 100 30" className="chrome h-8 w-24" role="img" aria-label={label}>
      <path d={d} fill="none" stroke="var(--c1)" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
