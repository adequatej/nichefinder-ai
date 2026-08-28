import { notFound } from "next/navigation";

import { ScoreComponentsPanel } from "@/components/score-components-panel";
import { ScoreValue } from "@/components/score-value";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { VideoList } from "@/components/video-list";
import { getNiche, getNicheVideos } from "@/lib/api";
import { formatNumber } from "@/lib/format";

// There's no dedicated "channels in this niche" endpoint (see
// GET /api/niches/{id}/videos in the API), so channels are derived here by
// aggregating channel_id across the video sample below. This undercounts if
// a niche has more videos than VIDEO_SAMPLE_SIZE and the missing ones belong
// to channels not otherwise represented in the sample -- an acceptable v1
// approximation given the endpoints available, not a full channel roster.
const VIDEO_SAMPLE_SIZE = 100;

function aggregateChannels(videos: { channel_id: string }[]) {
  const counts = new Map<string, number>();
  for (const video of videos) {
    counts.set(video.channel_id, (counts.get(video.channel_id) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([channelId, videoCount]) => ({ channelId, videoCount }))
    .sort((a, b) => b.videoCount - a.videoCount);
}

export default async function NicheDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const nicheId = Number(id);
  if (!Number.isFinite(nicheId)) notFound();

  const niche = await getNiche(nicheId);
  if (!niche) notFound();

  const { items: videos } = await getNicheVideos(nicheId, { limit: VIDEO_SAMPLE_SIZE });
  const channels = aggregateChannels(videos);

  // "Top" videos: view_count desc, straightforward from the data. "Rising"
  // has no dedicated signal on this endpoint -- no velocity or snapshot
  // history is exposed per-video, only a single current view_count. Sorting
  // by published_at desc (what the API already returns by default) is used
  // here as an honest "recent uploads" proxy, not a claim of a real rising
  // ranking -- see backend/app/services/scoring.py for the same caveat
  // applied to niche-level velocity.
  const topVideos = [...videos].sort((a, b) => b.view_count - a.view_count).slice(0, 10);
  const recentVideos = videos.slice(0, 10);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-8 p-8">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold">{niche.label}</h1>
          {niche.opportunity_score === null ? (
            <Badge variant="outline" className="text-muted-foreground">
              Unranked
            </Badge>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {niche.top_terms.map((term) => (
            <Badge key={term} variant="secondary">
              {term}
            </Badge>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">Demand</div>
          <div className="text-2xl font-semibold">
            <ScoreValue value={niche.demand_score} />
          </div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">Supply</div>
          <div className="text-2xl font-semibold">
            <ScoreValue value={niche.supply_score} />
          </div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">Opportunity</div>
          <div className="text-2xl font-semibold">
            <ScoreValue value={niche.opportunity_score} digits={0} />
          </div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">Videos</div>
          <div className="text-2xl font-semibold tabular-nums">{formatNumber(niche.video_count)}</div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">Channels</div>
          <div className="text-2xl font-semibold tabular-nums">{formatNumber(niche.channel_count)}</div>
        </div>
      </div>

      <ScoreComponentsPanel niche={niche} />

      <div>
        <h2 className="mb-3 text-lg font-semibold">Channels in this niche</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Derived from the {formatNumber(videos.length)} videos below, since the API has no
          direct channel roster per niche.
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Channel ID</TableHead>
                <TableHead className="text-right">Videos in sample</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channels.map((channel) => (
                <TableRow key={channel.channelId}>
                  <TableCell className="font-mono text-xs">{channel.channelId}</TableCell>
                  <TableCell className="text-right tabular-nums">{channel.videoCount}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Top videos</h2>
        <VideoList videos={topVideos} />
      </div>

      <div>
        <h2 className="mb-1 text-lg font-semibold">Recent uploads</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Sorted by publish date, not a rising/velocity signal -- the API doesn&apos;t expose
          per-video view history yet.
        </p>
        <VideoList videos={recentVideos} />
      </div>
    </main>
  );
}
