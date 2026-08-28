import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { SimilarVideo } from "@/lib/api";
import { formatDate, formatNumber, formatScore } from "@/lib/format";

export function SearchResults({ items }: { items: SimilarVideo[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead className="text-right">Views</TableHead>
            <TableHead className="text-right">Published</TableHead>
            <TableHead className="text-right">Distance</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell className="max-w-md truncate">{item.title}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {item.channel_id}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(item.view_count)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {formatDate(item.published_at)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {formatScore(item.distance, 3)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
