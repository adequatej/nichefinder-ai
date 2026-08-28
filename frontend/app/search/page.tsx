import { SearchResults } from "@/components/search-results";
import { search } from "@/lib/api";

// A GET form with a `q` query param keeps this a server component -- no
// client-side state needed, the URL itself is the search state.
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = q?.trim() ?? "";
  let results: Awaited<ReturnType<typeof search>> | null = null;
  let error = false;
  if (query) {
    try {
      results = await search(query, 20);
    } catch {
      error = true;
    }
  }

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-bold">Search videos</h1>
        <p className="text-sm text-muted-foreground">
          Free-text search over video embeddings -- nearest neighbors by meaning, not keyword
          match.
        </p>
      </div>

      <form className="flex gap-2" action="/search">
        <input
          type="text"
          name="q"
          defaultValue={query}
          placeholder="e.g. arsenal highlights"
          className="w-full max-w-md rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Search
        </button>
      </form>

      {error ? (
        <p className="text-sm text-destructive">
          Search failed -- the API may be unreachable. Try again in a moment.
        </p>
      ) : results ? (
        results.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No matches for &quot;{query}&quot;.</p>
        ) : (
          <div>
            <p className="mb-3 text-sm text-muted-foreground">
              {results.items.length} results for &quot;{query}&quot;, closest match first
              (cosine distance -- lower is more similar).
            </p>
            <SearchResults items={results.items} />
          </div>
        )
      ) : (
        <p className="text-sm text-muted-foreground">Enter a query to search.</p>
      )}
    </main>
  );
}
