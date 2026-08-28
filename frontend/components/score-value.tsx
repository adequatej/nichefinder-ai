import { Badge } from "@/components/ui/badge";
import { formatScore } from "@/lib/format";

// A null score means the niche hasn't cleared the eligibility floor (see
// scoring.py) -- it's unranked, not a confident zero. Render that state as
// an explicit badge rather than a blank cell, which would read as a loading
// bug rather than a real state.
export function ScoreValue({ value, digits = 1 }: { value: number | null; digits?: number }) {
  if (value === null) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        Unranked
      </Badge>
    );
  }
  return <span className="tabular-nums">{formatScore(value, digits)}</span>;
}
