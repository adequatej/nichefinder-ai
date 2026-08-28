import { getHealth } from "@/lib/api";

function Dot({ ok }: { ok: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`} />;
}

// Small footer/corner status indicator. This used to be the whole homepage
// (P0); the dashboard is now the main event, so it shrinks down to a
// corner-of-the-eye health check shared across every page.
export async function HealthIndicator() {
  const health = await getHealth();
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="flex items-center gap-1">
        <Dot ok={health !== null} />
        API
      </span>
      <span className="flex items-center gap-1">
        <Dot ok={health?.db ?? false} />
        DB
      </span>
      <span className="flex items-center gap-1">
        <Dot ok={health?.redis ?? false} />
        Redis
      </span>
    </div>
  );
}
