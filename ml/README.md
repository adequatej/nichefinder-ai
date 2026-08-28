# ml/ — breakout prediction model

Predicts which recently-published videos are "breaking out": growing
much faster than is typical for their own channel, once the fact that
young videos naturally show inflated views-per-day is corrected for.

This package is separate from `backend/` on purpose: it has its own
`pyproject.toml` and venv (torch, scikit-learn, pandas — none of which
the FastAPI service needs at runtime), and it runs on the **host**,
not inside a container, connecting to Postgres over the port
docker-compose already exposes (`localhost:5432`).

```bash
cd ml
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

## Pipeline

```
python -m src.export_dataset      # Postgres -> ml/data/dataset.parquet
python -m src.train_baselines     # LogisticRegression + HistGradientBoostingClassifier
python -m src.train_torch         # two-branch PyTorch MLP
```

Each stage reads/writes only `ml/data/` (gitignored — see `.gitignore`
at the repo root: `ml/data/` and `*.parquet`). `train_baselines.py`
writes `ml/data/folds.json` (the fixed GroupKFold split, reused by
`train_torch.py` if present) and `ml/data/scaler.pkl` (see "Scaler" below).

`export_dataset.py` connects with `ML_DATABASE_URL` (default
`postgresql://nichefinder:nichefinder@localhost:5432/nichefinder`),
**not** the `postgresql+asyncpg://...` URL the api/worker containers
use — this is a synchronous, host-side script, not an asyncio one.

## File layout

```
ml/
  pyproject.toml
  README.md
  src/
    __init__.py
    export_dataset.py   # Postgres -> parquet
    labels.py            # pure: V(t) curve, channel baseline, breakout threshold
    features.py          # pure: feature functions + the fixed feature_names() order
    dataset.py            # pandas/DB-shaped glue: sanitizing, assemble_dataset, scaling
    model.py              # BreakoutNet (PyTorch), architecture only
    evaluate.py           # PR-AUC, ROC-AUC, precision@50, calibration, fold comparison table
    folds.py              # GroupKFold by channel_id, with a small-corpus fallback
    train_baselines.py    # LogisticRegression + HistGradientBoostingClassifier over folds
    train_torch.py        # BreakoutNet training loop over folds
  tests/
    test_labels.py
    test_features.py
    test_evaluate.py
    test_folds.py
    test_model.py
    test_dataset.py
  data/                   # gitignored: dataset.parquet, folds.json, scaler.pkl
```

`ml/models/` does not exist yet. It's intentionally not created (not
even empty) — the only model that has ever been "trained" so far in
this repo is trained on the fake sample corpus's i.i.d.-random view
counts (see below), and committing that as if it were a real artifact
would misrepresent it. It gets created once a real training run
against real bootstrap data produces something worth keeping.

## Label construction

A video is a labeled "breakout" (1) when its **channel-baseline-relative,
age-corrected view velocity** clears `BREAKOUT_MULTIPLIER = 3.0`. Two
corrections, both in `labels.py`:

1. **Age-curve correction.** Raw views-per-day (`view_count / age_days`)
   is inflated for young videos purely because most of a video's
   lifetime views land in its first weeks — comparing a 10-day-old
   video's views/day directly to a 170-day-old video's is comparing
   apples to a much slower-ripening orange. `fit_view_curve` builds an
   empirical V(t): videos are bucketed into 7-day age buckets, and the
   **median** views/day within each bucket stands in for "what's
   typical at that age." Dividing a video's raw velocity by V(its age)
   gives a normalized velocity centered near 1.0 regardless of age.
   This is a median-of-currently-observed-videos curve, not a fitted
   parametric growth model, and it is *not* a "fraction of eventual
   lifetime views" curve in the literal sense (no true final view count
   exists to fit against yet) — it's honest as "what's typical right
   now for a video this old," which is exactly what channel-relative
   comparison needs.
2. **Channel-baseline correction.** A video's normalized velocity is
   compared to the *median normalized velocity of that same channel's
   other videos*, aged 30-180 days as of `now` (not before the target
   video — before `now`, so a channel's baseline doesn't drift
   backwards in time as new candidate videos are labeled). A channel
   needs at least 5 such videos before any of its videos get a label
   at all — see "Small-corpus limitations" below.

`BREAKOUT_MULTIPLIER = 3.0` is the plan's stated default. **It has not
been tuned against this repo's sample data.** The sample corpus's view
counts are i.i.d. random per video (see
`backend/app/ingest/sample_data.py`'s module docstring), so any
resulting positive rate on it is meaningless by construction, and
tuning the multiplier to hit a target rate on it would just be
curve-fitting to noise. Calibrating it against a real ~10-20% positive
rate is deferred until real bootstrap data exists.

## Leakage and bias discussion

- **Proxy bias — lifetime-ish views standing in for true day-N
  velocity.** `views_per_day` uses each video's single most recent
  `view_count` read divided by its age — not a true day-7 (or day-N)
  delta. Most of the corpus has only ever had `view_count` read once;
  the `VideoSnapshot`/`ChannelSnapshot` tables exist and the daily
  scheduler populates them going forward, but there isn't yet ~2 years
  of backfilled daily history to compute a true early-velocity signal
  from. Once roughly 90 days of daily snapshots accumulate, this proxy
  should be replaced with a real measured day-N velocity, which is far
  less sensitive to a single stale read and doesn't conflate "young and
  fast-growing" with "read at a lucky moment."
- **Corpus provenance.** Like the niches produced by
  `backend/app/services/clustering.py`, this corpus comes from a fixed
  seed-keyword list (`backend/app/ingest/seeds.py`), not an open crawl.
  A model trained on it learns "what distinguishes a breakout among
  videos matching these seed topics," not "what distinguishes a
  breakout on YouTube in general." That's the same honest scope
  limitation the niche-scoring system already carries.
- **No leakage between features and labels.** `view_count`,
  `like_count`, and `comment_count` are never themselves model inputs
  — only their derived, age-normalized/baseline forms
  (`log_baseline_velocity`) are. `StandardScaler` is fit on each fold's
  training split only (`dataset.scale_train_test`); GroupKFold ensures
  a channel's videos never span train and test within a fold, so no
  fold can "cheat" by having seen that channel's typical scale already.

## Small-corpus limitations

The 12-channel sample fixture (`app/ingest/sample_data.py`) is far too
small and far too random to produce a meaningful trained model, on
purpose — see the module's own docstring: view counts are i.i.d.
random per video, so any resulting label or metric is noise, not
signal. Two real, expected (not buggy) consequences observed while
verifying this pipeline:

- **Most videos end up unlabeled.** The channel-baseline gate (≥5
  same-channel videos aged 30-180 days) means a channel needs real
  depth before any of its videos get scored at all. On a 12-channel,
  ~300-video corpus, a large fraction of videos are excluded from
  training entirely — this is the gate working as intended, not a bug.
- **GroupKFold may not get 5 folds.** `folds.make_folds` falls back to
  as many folds as there are distinct channel groups among the
  *labeled* videos (floor of 2; raises below that) — see `folds.py`'s
  docstring. On a corpus this small, expect fewer than 5 folds, or
  even too few channels to cross-validate meaningfully at all.
- **A training fold can end up single-class.** With very few
  positives, a given fold's train split can end up with zero breakout
  labels. scikit-learn's classifiers require both classes to fit;
  `train_baselines.py` detects this and skips that fold (with a
  printed note) rather than crashing. PyTorch's `BCEWithLogitsLoss`
  doesn't have that restriction, so `train_torch.py` trains through it
  (with `pos_weight` falling back to 1.0) but also prints a note.

## Honest outcome policy

This comparison table ships with whatever the real numbers are. If a
model trails another, or all three trail a trivial baseline, that gets
reported as-is — not hidden, not iterated away by re-tuning against
the same data until a better number appears. The deliverable here is
the **rigor of the comparison** (grouped-by-channel folds so no model
gets to memorize a channel, identical folds and identical feature set
across all three models, a scaler fit without leakage, calibration
reported alongside ranking metrics) — not a specific PR-AUC value.

## Verification run (sample-data proxy — proves the pipeline runs, nothing else)

This table is from the actual `app/ingest/sample_data.py` fixture
(`make bootstrap-sample` + `make cluster` to populate embeddings, then
`python -m src.export_dataset` against that live Postgres), not a
hand-fabricated harness — 273 English-detected videos exported, 50 of
those cleared both the labeling window and the channel-baseline gate.

| model | folds | PR-AUC | ROC-AUC | precision@k (k≈10) |
|---|---|---|---|---|
| logistic_regression | 5 | 0.284 ± 0.136 | 0.446 ± 0.301 | 0.133 ± 0.076 |
| hist_gradient_boosting | 5 | 0.308 ± 0.126 | 0.658 ± 0.173 | 0.133 ± 0.076 |
| pytorch_mlp | 5 | 0.459 ± 0.327 | 0.567 ± 0.363 | 0.133 ± 0.076 |

**This table means nothing predictively** — the sample corpus's view
counts are i.i.d. random per video (see
`app/ingest/sample_data.py`'s own docstring), n is tiny (10 candidates
per fold on average), and the large standard deviations reflect that
directly. It is proof the pipeline runs end to end against a real
Postgres — export → labels → features → folds → both baselines → the
PyTorch model — without a crash, that reruns are reproducible
(`train_torch.py`'s `set_seed` also pins `torch.set_num_threads(1)`;
without that, CPU matmul's thread-scheduling-dependent reduction order
made even seeded reruns differ — two reruns of this exact table
produced bit-identical PyTorch metrics), and that a well-formed
comparison table comes out the other end — not a claim about which
model is better.

**The real comparison table** — the one that means something — gets
generated the same way, just pointed at real bootstrap data once the
YouTube API key exists and the daily scheduler has accumulated enough
history for `views_per_day` to stop being a single-stale-read proxy
(see "Leakage and bias discussion" above).

## Judgment calls

- **V(t) approximation:** median views/day within 7-day age buckets
  over the whole exported corpus (not just the 7-180 day labeling
  window), so the curve has support at every age including the 30-180
  day baseline range. See "Label construction" above.
- **Export scope:** `export_dataset.py` exports *every* English-language
  video per channel, not just the 7-180 day labeling window, so
  channel-level aggregates (the baseline pool, `uploads_per_week`) can
  be computed in-process without a second round-trip to Postgres.
- **Category one-hot:** the 8 most frequent `category_id` values *in
  the exported dataset* (not a fixed global YouTube category list) each
  get a column; everything else, including a missing category, falls
  into one "other" column. Corpus-dependent by design — rebuilt fresh
  each export.
- **GroupKFold fallback:** falls back from 5 folds to as many folds as
  there are distinct channel groups among labeled videos, floor 2;
  raises below that. See `folds.py`.
- **scikit-learn API:** `HistGradientBoostingClassifier`'s
  `class_weight` support is checked via
  `inspect.signature(...).parameters` at runtime rather than assumed,
  since it varies by scikit-learn version (this repo's ml/.venv has
  1.9, where it exists).
- **Scaling:** per the plan, only the tabular feature slice is
  standardized (fit on the fold's train split); the 384-dim embedding
  is left raw in both baselines and the PyTorch model, so its own
  signal isn't dampened or distorted relative to what the plan
  explicitly wants tested un-handicapped.
- **Scaler artifact:** `train_baselines.py` pickles the *last* fold's
  scaler to `ml/data/scaler.pkl`, purely so downstream serving code has
  something to load. It is not fit on the full corpus and is not
  presented as a production artifact — a v1 simplification, and
  gitignored regardless.
