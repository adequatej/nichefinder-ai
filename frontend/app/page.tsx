import { apiGet } from "@/lib/api";

type Health = {
  status: string;
  db: boolean;
  redis: boolean;
};

async function getHealth(): Promise<Health | null> {
  try {
    return await apiGet<Health>("/api/health");
  } catch {
    return null;
  }
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
    />
  );
}

export default async function Home() {
  const health = await getHealth();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-bold">NicheFinder AI</h1>
      <p className="text-sm opacity-70">
        Find low-competition YouTube niches before everyone else does.
      </p>
      <div className="flex flex-col gap-3 rounded-lg border p-6">
        <div className="flex items-center gap-3">
          <StatusDot ok={health !== null} />
          <span>API: {health ? "connected" : "unreachable"}</span>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot ok={health?.db ?? false} />
          <span>Postgres: {health?.db ? "connected" : "unreachable"}</span>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot ok={health?.redis ?? false} />
          <span>Redis: {health?.redis ? "connected" : "unreachable"}</span>
        </div>
      </div>
    </main>
  );
}
