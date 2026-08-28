"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ScoreValue } from "@/components/score-value";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { NicheSummary } from "@/lib/api";
import { formatNumber } from "@/lib/format";

type SortKey =
  | "label"
  | "video_count"
  | "channel_count"
  | "demand_score"
  | "supply_score"
  | "opportunity_score";

type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "label", label: "Niche" },
  { key: "video_count", label: "Videos", align: "right" },
  { key: "channel_count", label: "Channels", align: "right" },
  { key: "demand_score", label: "Demand", align: "right" },
  { key: "supply_score", label: "Supply", align: "right" },
  { key: "opportunity_score", label: "Opportunity", align: "right" },
];

// Null scores (unranked niches) always sort after every ranked niche,
// regardless of sort direction -- a null is "no opinion yet," never the
// lowest or highest value on the scale. Matches the API's own ordering
// convention on GET /api/niches.
function compareNiches(a: NicheSummary, b: NicheSummary, key: SortKey, dir: SortDir): number {
  const sign = dir === "asc" ? 1 : -1;
  if (key === "label") {
    return sign * a.label.localeCompare(b.label);
  }
  const av = a[key];
  const bv = b[key];
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  return sign * (av - bv);
}

export function NicheTable({ niches }: { niches: NicheSummary[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("opportunity_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    return [...niches].sort((a, b) => compareNiches(a, b, sortKey, sortDir));
  }, [niches, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "label" ? "asc" : "desc");
    }
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            {COLUMNS.map((col) => (
              <TableHead
                key={col.key}
                className={col.align === "right" ? "text-right" : undefined}
              >
                <button
                  type="button"
                  onClick={() => handleSort(col.key)}
                  className="inline-flex items-center gap-1 font-medium hover:text-foreground"
                >
                  {col.label}
                  {sortKey === col.key ? (
                    <span aria-hidden className="text-muted-foreground">
                      {sortDir === "asc" ? "^" : "v"}
                    </span>
                  ) : null}
                </button>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((niche) => {
            const unranked = niche.opportunity_score === null;
            return (
              <TableRow key={niche.id} className={unranked ? "opacity-70" : undefined}>
                <TableCell>
                  <Link
                    href={`/niches/${niche.id}`}
                    className="font-medium hover:underline underline-offset-2"
                  >
                    {niche.label}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(niche.video_count)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(niche.channel_count)}
                </TableCell>
                <TableCell className="text-right">
                  <ScoreValue value={niche.demand_score} />
                </TableCell>
                <TableCell className="text-right">
                  <ScoreValue value={niche.supply_score} />
                </TableCell>
                <TableCell className="text-right">
                  <ScoreValue value={niche.opportunity_score} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
