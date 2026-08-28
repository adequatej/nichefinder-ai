import { formatPercent } from "@/lib/format";

// Same sequential blue ramp as the dashboard's opportunity scatter --
// probability is a magnitude, not a state, so it gets the sequential
// treatment rather than the reserved good/warning/critical status colors.
const BLUE_RAMP = [
  "#cde2fb",
  "#9ec5f4",
  "#6da7ec",
  "#3987e5",
  "#256abf",
  "#184f95",
  "#0d366b",
];

function colorFor(probability: number): string {
  const idx = Math.min(BLUE_RAMP.length - 1, Math.floor(probability * BLUE_RAMP.length));
  return BLUE_RAMP[idx];
}

// Steps 0-2 (light blue) are too pale for white text; darker steps get white.
function textColorFor(probability: number): string {
  const idx = Math.min(BLUE_RAMP.length - 1, Math.floor(probability * BLUE_RAMP.length));
  return idx <= 1 ? "#0b0b0b" : "#ffffff";
}

export function BreakoutBadge({ probability }: { probability: number }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums"
      style={{ background: colorFor(probability), color: textColorFor(probability) }}
    >
      {formatPercent(probability, 0)}
    </span>
  );
}
