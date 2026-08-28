import { Badge } from "@/components/ui/badge";
import type { NicheDetail } from "@/lib/api";
import { formatNumber, formatPercent, formatScore } from "@/lib/format";

// Eligibility floor from backend/app/services/scoring.py -- kept in sync by
// hand since the frontend has no access to the backend's Python constants.
// If these ever drift, the eligibility explanation below will say the wrong
// thing, so update both together.
const MIN_ELIGIBLE_CHANNELS = 3;
const MIN_ELIGIBLE_VIDEOS = 25;

const ROWS: { key: keyof NonNullable<NicheDetail["score_components"]>; label: string; format: (v: number) => string }[] = [
  { key: "median_views", label: "Median views", format: (v) => formatNumber(v) },
  { key: "median_velocity", label: "Median velocity", format: (v) => `${formatNumber(v)} views/day` },
  { key: "median_engagement", label: "Median engagement", format: (v) => formatPercent(v) },
  { key: "uploads_per_week", label: "Uploads / week (niche-wide, last 90 days)", format: (v) => formatScore(v, 2) },
  { key: "active_channel_count", label: "Active channels", format: (v) => formatNumber(v) },
  { key: "video_count", label: "Videos", format: (v) => formatNumber(v) },
];

export function ScoreComponentsPanel({ niche }: { niche: NicheDetail }) {
  const isRanked = niche.opportunity_score !== null;
  const components = niche.score_components;

  return (
    <div className="rounded-lg border p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium">Score components</h3>
        {isRanked ? (
          <Badge variant="secondary">Ranked</Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            Unranked
          </Badge>
        )}
      </div>

      {!isRanked ? (
        <p className="mb-4 rounded-md bg-muted p-3 text-sm text-muted-foreground">
          This niche needs at least {MIN_ELIGIBLE_CHANNELS} channels and {MIN_ELIGIBLE_VIDEOS}{" "}
          videos to be ranked. It currently has {formatNumber(niche.channel_count)} channel
          {niche.channel_count === 1 ? "" : "s"} and {formatNumber(niche.video_count)} video
          {niche.video_count === 1 ? "" : "s"}, so demand, supply, and opportunity scores are
          withheld rather than published on too thin a sample.
        </p>
      ) : null}

      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {ROWS.map(({ key, label, format }) => {
          const value = components[key];
          return (
            <div key={key} className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="tabular-nums font-medium">{value === null || value === undefined ? "--" : format(value)}</dd>
            </div>
          );
        })}
        {components.shrinkage_weight !== undefined ? (
          <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
            <dt className="text-muted-foreground">Shrinkage weight</dt>
            <dd className="tabular-nums font-medium">{formatScore(components.shrinkage_weight, 2)}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}
