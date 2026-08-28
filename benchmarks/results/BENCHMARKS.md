# Benchmarks

Two scripts back two different kinds of claim, and they are not the
same kind of number:

- `benchmarks/bench_quota.py` measures an **architectural** fact: call
  counts against the YouTube Data API's fixed per-endpoint unit costs
  (`app/services/quota.py`'s `UNIT_COSTS`). This does not depend on
  what's in the sample corpus, whether Redis is warm, or how fast the
  machine running it is — it depends only on which endpoints get
  called how many times for a given amount of monitoring work, which
  is fixed by code, not by data. There is no "meaningless because the
  corpus is fake" caveat here the way there is for `ml/README.md`'s
  breakout-model table: this benchmark never touches the sample
  corpus's fabricated view counts at all.
- `benchmarks/bench_latency.py` measures **absolute wall-clock
  latency** against the live stack as it is running right now — real
  Postgres, real Redis, real (small) sample corpus. These numbers are
  real and reproducible on this machine, but they are latency *at
  sample-corpus scale* (a few hundred videos, ~14 niches). A real
  bootstrap with 10k+ videos would change the absolute numbers,
  particularly for `/api/niches`' database query. What should hold at
  any scale is the *shape* of the result — cache hit beats cache miss,
  and the embedding cache accounts for most of `/api/search`'s win —
  because that gap comes from skipping work entirely, not from how
  fast the work happens to run.

Both scripts are runnable with no YouTube API key: `bench_quota.py`
mocks every YouTube HTTP call with `respx`, and `bench_latency.py`
only talks to this repo's own FastAPI service.

## Quota benchmark

### What it measures

For the same fixed amount of "daily monitoring work" — 20 tracked
channels, 5 new videos discovered per channel per day (100 new videos
total) — how many YouTube Data API quota units does each strategy
spend:

- **naive**: one `search.list` call per tracked topic (100 units
  each) to look for new uploads, then one `videos.list` call per video
  fetched one at a time (1 unit each, no batching). This is
  benchmark-only code (`run_naive_strategy` in `bench_quota.py`) —
  it is never imported by `app.ingest` or the scheduler.
- **optimized**: the real, already-shipped
  `app.ingest.snapshot.run_daily_refresh` — not a re-implementation —
  run against 20 synthetic tracked channels: one batched
  `channels.list` call, one `playlistItems.list` page per channel to
  diff for new uploads, and batched `videos.list` calls (50 ids per
  call) for whatever's new.

Every YouTube HTTP call on both sides is intercepted by `respx`, the
same technique `backend/tests/test_bootstrap.py` uses to prove the
bootstrap costs exactly 103 units — the mocked response content
doesn't need to be realistic, only its shape, so the client's real
batching and pagination code actually runs. `bench_quota.py`'s module
docstring has the full scenario and design rationale (why 20 channels
rather than the ~100 in `docs/quota-math.md`'s own example, why the
embedding/clustering hooks get monkeypatched out for the optimized
run, how cleanup works).

### How it was run

```
docker compose exec api python -m benchmarks.bench_quota
```

Postgres was reachable, so this wrote real rows to `api_quota_log`
(run_label `benchmark-quota-2026-08-28-6086f69b`) and read them back
with the same `(day, strategy_label)` grouping `/api/stats/quota` uses
(`app.services.quota_stats.aggregate_quota_rows`). Confirmed by
querying the table directly afterward, and confirmed that the 20
synthetic `UCbench*` channels and any temporarily-untracked real
channels were fully cleaned up / restored (verified against the 11
channels tracked by the sample-data bootstrap, unaffected before and
after).

### Result (copied from actual script output)

```
Quota benchmark (real Postgres, api_quota_log), run_label=benchmark-quota-2026-08-28-6086f69b
Scenario: 20 tracked channels, 5 new videos each (100 new videos total)
strategy      units_spent  calls_uncached
naive                2100             120
optimized              23              23

Optimized costs 23 units vs 2100 naive -- 98.9 percent fewer units for the same monitoring work.
Scaled 5x (to the ~100-channel scale docs/quota-math.md illustrates): naive 10500, optimized 115 units/day.
```

Rerun twice more back to back (each run uses a fresh, unique
`run_label` so repeats never double-count against a stale row from an
earlier run the same day) and confirmed bit-identical: 2100 vs 23
every time, as expected from a purely call-count-driven arithmetic
result with no randomness in the scenario.

The `--memory-only` flag (in-memory `ListQuotaRecorder` on both sides,
no database at all) was also run and produced the identical 2100 /
23 split, confirming the DB-backed and in-memory code paths agree.
Both measured totals are also checked in-script against
`naive_units_for` / `optimized_expected_units` (the same
hand-computable formulas `benchmarks/tests/test_bench_quota.py`
asserts against); a mismatch prints a loud warning instead of silently
reporting a wrong-but-plausible number. Neither run triggered it.

### Cross-check against docs/quota-math.md

`docs/quota-math.md` estimates the production daily refresh (~100
tracked channels) at **about 110-125 units**, and the naive
alternative at "several thousand." Scaling this benchmark's 20-channel
result up 5x (units scale linearly with channel count in both
strategies) gives **115 units** for the optimized side — landing
inside the middle of that estimated range — and **10,500** for naive,
consistent with "several thousand." The estimate holds up; this
benchmark replaces "should cost around" with a real, reproducible
measured number.

## Latency benchmark

### What it measures

Absolute p50/p95 latency in milliseconds, cold vs. warm, for the two
endpoints with Layer 2 (computed-response) caching:
`app/services/api_cache.py`.

- **`/api/niches`**: one response cache keyed on `(limit, offset)`.
- **`/api/search`**: two caches — the query embedding (keyed on `q`
  alone) and the full response (keyed on `q` + `limit`) —
  `api_cache.py` calls the embedding cache "the dominant win" since
  embedding a query costs far more than the pgvector scan after it.

"Cold" means a guaranteed cache miss: niches uses a never-before-seen
`offset` per sample (a random per-run salt), search uses distinct,
realistic-looking queries salted the same way, so neither is an
artifact of the OS/HTTP layer replaying one repeated string. "Warm"
means one untimed warmup call followed by repeated identical requests.
A third search case holds the query fixed but varies `limit` on every
call, so the response cache always misses while the embedding cache
always hits — isolating how much of the win is "skip the embedding
model" versus "skip the whole request." The very first `/api/search`
call in a freshly started process pays a one-time cost to load the
sentence-transformers model into memory; that's a process-lifetime
cost unrelated to caching, so the cold-search benchmark burns it off
with one throwaway warmup query before timing anything (see the
script's docstring).

### How it was run

Stack already up via `docker compose up -d --build db redis api`,
schema migrated (`make migrate`), sample data loaded
(`make bootstrap-sample`), embeddings/clustering run (`make cluster`).
Then, from inside the api container (so `http://localhost:8000`
resolves to the api container's own server):

```
docker compose exec api python -m benchmarks.bench_latency
```

20 cold samples and 30 warm samples per case, per the script's
`COLD_SAMPLES` / `WARM_SAMPLES` constants.

### Result (copied from actual script output)

```
Latency benchmark against http://localhost:8000
Measured on the corpus currently loaded -- see this script's docstring for what that does and doesn't prove.

niches: cold (unique offset, cache miss)        20  p50=     2.4ms  p95=     3.2ms  (min=2.1, max=3.7)
niches: warm (repeated, cache hit)              30  p50=     1.4ms  p95=     1.7ms  (min=1.3, max=2.1)
search: cold (unique query, both caches miss)   20  p50=     8.2ms  p95=    13.9ms  (min=7.5, max=15.2)
search: warm embedding only (response cache still misses)   30  p50=     2.5ms  p95=     2.8ms  (min=1.3, max=2.9)
search: warm full response (cache hit)          30  p50=     1.3ms  p95=     1.5ms  (min=1.2, max=1.5)
```

Sample corpus at the time of this run: 12 channels, 300 videos (273
English-detected). `make cluster` embedded all 300 videos and
clustered the 273 considered (English-detected) into 14 niches, all
273 assigned. Loaded via `make bootstrap-sample` + `make cluster` —
see `ml/README.md` for why this fixture's *content* (i.i.d.-random
view counts) is not meaningful, though that limitation is irrelevant
here since this benchmark only measures response time, never accuracy
or ranking.

### Reading the numbers

- **`/api/niches`** barely benefits from caching at this corpus size:
  1.4ms warm vs 2.4ms cold p50. The uncached query is already cheap
  (14 niches, one indexed `ORDER BY`), so there is little for a cache
  to save. This could look different against a real, larger corpus if
  the niches table or its ordering ever gets more expensive to compute
  — the point of Layer 2 here (per `niches.py`'s own docstring) is
  protecting a cheap-but-repeated query under load, not fixing a slow
  one.
- **`/api/search`** benefits a lot: 8.2ms cold p50 down to 1.3ms warm
  full-response p50, a ~6.3x drop. Comparing the three rows shows
  where that drop comes from: cold-to-warm-embedding-only already
  drops p50 from 8.2ms to 2.5ms (5.7ms of the 6.9ms total gap, about
  83 percent), and warm-embedding-only to warm-full only saves another
  1.2ms. That is a real, measured confirmation of `api_cache.py`'s
  claim that the embedding cache is "the dominant win" — most of the
  savings come from skipping the sentence-transformers forward pass,
  not from skipping the database round trip after it.
- Do not average these into one "caching saves N percent" number
  across both endpoints — one endpoint saves almost nothing in
  absolute terms at this scale and the other saves the majority of its
  cost, and blending them would misrepresent both.

## Reproducing

```
make up            # or: docker compose up -d --build db redis api
make migrate
make bootstrap-sample
make cluster
make bench-quota
make bench-latency
```

`make bench-quota` runs `bench_quota.py` against whatever Postgres the
api container sees (real ledger rows) or falls back to an in-memory
ledger if none is reachable — see that script's own module docstring.
`make bench-latency` expects the api/db/redis stack to already be up
and loaded (per the steps above); it does not start or seed anything
itself.
