"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipContentProps } from "recharts";

import type { NicheSummary } from "@/lib/api";
import { formatNumber, formatScore } from "@/lib/format";

// Chart chrome tokens (light chart surface only -- the app doesn't ship a
// theme toggle yet, see report). Values match the dataviz skill's reference
// palette (references/palette.md).
const SURFACE = "#fcfcfb";
const INK_PRIMARY = "#0b0b0b";
const INK_MUTED = "#898781";
const GRID = "#e1e0d9";
const BASELINE = "#c3c2b7";

// Sequential single-hue (blue) ramp, light -> dark, used to encode
// opportunity_score as a third dimension on top of the x/y scatter position.
const BLUE_RAMP = [
  "#cde2fb",
  "#b7d3f6",
  "#9ec5f4",
  "#86b6ef",
  "#6da7ec",
  "#5598e7",
  "#3987e5",
  "#2a78d6",
  "#256abf",
  "#1c5cab",
  "#184f95",
  "#104281",
  "#0d366b",
];

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
}

// Discrete marks need a contrast floor the continuous 100->700 fill range
// doesn't: palette.md calls out step 250 as the lightest step that still
// clears 2:1 against the light surface. Without this floor, min-max
// normalizing opportunity_score maps the lowest-scoring ranked niche to
// step 100 (~1.2:1) and its dot disappears into the card background.
const MARK_FLOOR_INDEX = 3; // BLUE_RAMP[3] === step 250

function sequentialBlue(t: number): string {
  const clamped = Math.min(1, Math.max(0, t));
  const scaled = MARK_FLOOR_INDEX + clamped * (BLUE_RAMP.length - 1 - MARK_FLOOR_INDEX);
  const lo = Math.floor(scaled);
  const hi = Math.min(BLUE_RAMP.length - 1, lo + 1);
  const frac = scaled - lo;
  const a = hexToRgb(BLUE_RAMP[lo]);
  const b = hexToRgb(BLUE_RAMP[hi]);
  return rgbToHex([
    a[0] + (b[0] - a[0]) * frac,
    a[1] + (b[1] - a[1]) * frac,
    a[2] + (b[2] - a[2]) * frac,
  ]);
}

type ScatterPoint = {
  id: number;
  label: string;
  x: number;
  y: number;
  opportunity: number;
  videoCount: number;
  channelCount: number;
  fill: string;
};

function ScatterDot(props: { cx?: number; cy?: number; payload?: ScatterPoint }) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined || !payload) return null;
  return (
    <g>
      {/* Transparent hit area, well past the 8px minimum visible dot so the
          pointer only has to be close, not dead-center. */}
      <circle cx={cx} cy={cy} r={14} fill="transparent" />
      <circle cx={cx} cy={cy} r={6} fill={payload.fill} stroke={SURFACE} strokeWidth={2} />
    </g>
  );
}

function ScatterTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as ScatterPoint;
  return (
    <div
      className="rounded-md border px-3 py-2 text-sm shadow-md"
      style={{ background: SURFACE, borderColor: BASELINE, color: INK_PRIMARY }}
    >
      <div className="font-medium">{point.label}</div>
      <dl className="mt-1 grid grid-cols-[auto_auto] gap-x-3 text-xs" style={{ color: INK_PRIMARY }}>
        <dt style={{ color: INK_MUTED }}>Demand</dt>
        <dd className="text-right tabular-nums">{formatScore(point.y)}</dd>
        <dt style={{ color: INK_MUTED }}>Supply</dt>
        <dd className="text-right tabular-nums">{formatScore(point.x)}</dd>
        <dt style={{ color: INK_MUTED }}>Opportunity</dt>
        <dd className="text-right tabular-nums">{formatScore(point.opportunity)}</dd>
        <dt style={{ color: INK_MUTED }}>Videos</dt>
        <dd className="text-right tabular-nums">{formatNumber(point.videoCount)}</dd>
        <dt style={{ color: INK_MUTED }}>Channels</dt>
        <dd className="text-right tabular-nums">{formatNumber(point.channelCount)}</dd>
      </dl>
    </div>
  );
}

export function OpportunityScatter({ niches }: { niches: NicheSummary[] }) {
  const points = useMemo<ScatterPoint[]>(() => {
    const ranked = niches.filter(
      (n) => n.demand_score !== null && n.supply_score !== null && n.opportunity_score !== null,
    ) as (NicheSummary & { demand_score: number; supply_score: number; opportunity_score: number })[];

    if (ranked.length === 0) return [];

    const opportunities = ranked.map((n) => n.opportunity_score);
    const min = Math.min(...opportunities);
    const max = Math.max(...opportunities);
    const span = max - min || 1;

    return ranked.map((n) => ({
      id: n.id,
      label: n.label,
      x: n.supply_score,
      y: n.demand_score,
      opportunity: n.opportunity_score,
      videoCount: n.video_count,
      channelCount: n.channel_count,
      fill: sequentialBlue((n.opportunity_score - min) / span),
    }));
  }, [niches]);

  if (points.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border text-sm text-muted-foreground">
        No ranked niches yet -- scores appear once a niche clears the eligibility floor.
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4" style={{ background: SURFACE }}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium" style={{ color: INK_PRIMARY }}>
          Demand vs. supply
        </h3>
        <div className="flex items-center gap-2 text-xs" style={{ color: INK_MUTED }}>
          <span>Opportunity</span>
          <span
            className="h-2 w-16 rounded-full"
            style={{ background: `linear-gradient(to right, ${BLUE_RAMP[MARK_FLOOR_INDEX]}, ${BLUE_RAMP[BLUE_RAMP.length - 1]})` }}
          />
          <span>low - high</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={360}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
          <XAxis
            type="number"
            dataKey="x"
            name="Supply"
            domain={["dataMin - 0.3", "dataMax + 0.3"]}
            tick={{ fill: INK_MUTED, fontSize: 12 }}
            tickFormatter={(v: number) => v.toFixed(1)}
            stroke={BASELINE}
            label={{ value: "Supply (z-score)", position: "insideBottom", offset: -12, fill: INK_MUTED, fontSize: 12 }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="Demand"
            domain={["dataMin - 0.3", "dataMax + 0.3"]}
            tick={{ fill: INK_MUTED, fontSize: 12 }}
            tickFormatter={(v: number) => v.toFixed(1)}
            stroke={BASELINE}
            label={{ value: "Demand (z-score)", angle: -90, position: "insideLeft", fill: INK_MUTED, fontSize: 12 }}
          />
          <ReferenceLine x={0} stroke={BASELINE} strokeDasharray="3 3" />
          <ReferenceLine y={0} stroke={BASELINE} strokeDasharray="3 3" />
          <Tooltip content={ScatterTooltip} cursor={{ stroke: BASELINE, strokeDasharray: "3 3" }} />
          <Scatter data={points} shape={ScatterDot} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs" style={{ color: INK_MUTED }}>
        Top-left (high demand, low supply) is where opportunity concentrates. Unranked niches are
        excluded -- they have no scores to plot.
      </p>
    </div>
  );
}
