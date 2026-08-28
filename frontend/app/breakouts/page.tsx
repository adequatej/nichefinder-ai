import { BreakoutBadge } from "@/components/breakout-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getBreakouts } from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/format";

export default async function BreakoutsPage() {
  const { items } = await getBreakouts(50);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-bold">Breakout predictions</h1>
        <p className="text-sm text-muted-foreground">
          Videos the model flags as likely to break out, ranked by predicted probability.
        </p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-lg border p-8 text-center">
          <p className="font-medium">No breakout predictions yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            The model needs real bootstrap data to train on before it can make predictions --
            this is expected on a fresh install, not an error. See ml/README.md for what&apos;s
            needed to train it.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Channel</TableHead>
                <TableHead className="text-right">Views</TableHead>
                <TableHead className="text-right">Published</TableHead>
                <TableHead className="text-right">Probability</TableHead>
                <TableHead>Model</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.video_id}>
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
                  <TableCell className="text-right">
                    <BreakoutBadge probability={item.breakout_probability} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{item.model_version}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  );
}
