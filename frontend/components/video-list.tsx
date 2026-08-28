import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { VideoSummary } from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/format";

export function VideoList({ videos }: { videos: VideoSummary[] }) {
  if (videos.length === 0) {
    return <p className="text-sm text-muted-foreground">No videos to show.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead className="text-right">Views</TableHead>
            <TableHead className="text-right">Published</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {videos.map((video) => (
            <TableRow key={video.id}>
              <TableCell className="max-w-md">
                <div className="flex items-center gap-2">
                  <span className="truncate">{video.title}</span>
                  {video.is_short ? (
                    <Badge variant="outline" className="shrink-0">
                      Short
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {video.channel_id}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(video.view_count)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {formatDate(video.published_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
