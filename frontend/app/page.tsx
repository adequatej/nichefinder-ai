import Link from "next/link";

import { NicheTable } from "@/components/niche-table";
import { OpportunityScatter } from "@/components/opportunity-scatter";
import { StatTile } from "@/components/stat-tile";
import { getNiches } from "@/lib/api";
import { formatNumber, formatScore } from "@/lib/format";

// The niches list endpoint caps at 100 per page (MAX_LIMIT in
// backend/app/api/niches.py). The sample dataset has well under that, so one
// page covers everything for now; a later phase would paginate here instead.
const NICHES_PAGE_SIZE = 100;

export default async function Dashboard() {
  const { items: niches } = await getNiches({ limit: NICHES_PAGE_SIZE });

  const rankedNiches = niches.filter((n) => n.opportunity_score !== null);
  const totalVideos = niches.reduce((sum, n) => sum + n.video_count, 0);
  const topNiche = rankedNiches[0] ?? null;

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-8 p-8">
      <div>
        <h1 className="text-2xl font-bold">Niche opportunities</h1>
        <p className="text-sm text-muted-foreground">
          Demand and supply, scored across the tracked YouTube corpus.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile label="Niches tracked" value={formatNumber(niches.length)} />
        <StatTile
          label="Ranked niches"
          value={`${formatNumber(rankedNiches.length)} / ${formatNumber(niches.length)}`}
          hint="cleared the eligibility floor"
        />
        <StatTile label="Videos analyzed" value={formatNumber(totalVideos)} />
        {topNiche ? (
          <Link href={`/niches/${topNiche.id}`}>
            <StatTile
              label="Top opportunity"
              value={formatScore(topNiche.opportunity_score, 0)}
              hint={topNiche.label}
            />
          </Link>
        ) : (
          <StatTile label="Top opportunity" value="--" hint="no ranked niches yet" />
        )}
      </div>

      <OpportunityScatter niches={niches} />

      <div>
        <h2 className="mb-3 text-lg font-semibold">All niches</h2>
        <NicheTable niches={niches} />
      </div>
    </main>
  );
}
