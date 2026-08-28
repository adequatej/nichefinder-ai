// Server components run inside Docker and reach the API through the compose
// network hostname. The browser reaches it through localhost. Pick the right
// base URL depending on where the code is running.
export function apiBase(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL_INTERNAL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}
