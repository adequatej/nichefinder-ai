"""Batch clustering: group English-language videos into candidate niches.

Honesty framing, matching the rest of this repo: the corpus is built
from a fixed seed keyword list (see app/ingest/seeds.py), so the
clusters this module finds mostly echo those seed topics back. This is
"score and rank candidate niches drawn from a curated topic list," not
"discover niches from nothing." A cluster's label is only as good as
the titles that fed it.

Pipeline: UMAP compresses the 384-dim sentence embeddings to a lower
dimension (HDBSCAN needs that; density estimates fall apart in high
dimensions), then HDBSCAN finds density-based clusters. Noise points
(label -1) get a second chance: if they are similar enough to an
existing cluster's centroid they join it, otherwise they stay
unassigned rather than being forced into the nearest cluster regardless
of fit. A MiniBatchKMeans fallback (fixed k) is available behind the
`algorithm` parameter for corpora where HDBSCAN degenerates into one
giant cluster or all noise.

Every run deletes all existing Niche rows and rebuilds them from
scratch, the same "reset first" pattern bootstrap.py uses for tracked
channels: niche ids are not stable across runs (HDBSCAN's own cluster
numbering isn't stable either), only the recomputed state is
meaningful. video.niche_id and channel.niche_id are cleared
automatically by the ON DELETE SET NULL foreign keys.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable

import numpy as np

# HDBSCAN's minimum cluster size. Below this, a group of similar videos
# is treated as noise rather than its own niche.
MIN_CLUSTER_SIZE = 10

# Skip clustering entirely below this many embedded English videos;
# HDBSCAN with min_cluster_size=10 cannot produce anything meaningful
# on less.
MIN_ROWS_FOR_CLUSTERING = MIN_CLUSTER_SIZE * 2

UMAP_N_COMPONENTS = 15
UMAP_N_NEIGHBORS = 15

# MiniBatchKMeans fallback cluster count, used only when algorithm="kmeans".
KMEANS_K = 40

# A noise point joins the nearest cluster only if cosine similarity to
# that cluster's centroid clears this bar; otherwise it is left
# unassigned rather than forced into a poor-fit niche.
NOISE_SIMILARITY_THRESHOLD = 0.5

# How many c-TF-IDF terms to keep per niche, and how many of those make
# the human-readable label.
TOP_TERMS_COUNT = 6
LABEL_TERM_COUNT = 4

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
        "vs", "is", "this", "at", "by", "from", "as", "it", "its", "are",
        "was", "were", "be", "that", "these", "those", "you", "your", "all",
        "will", "not", "but", "so", "if", "than", "then",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric runs, drop stopwords and short tokens."""
    tokens = _TOKEN_RE.findall((text or "").lower())
    return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]


def compute_c_tfidf(
    cluster_tokens: dict[int, list[str]], top_n: int = TOP_TERMS_COUNT
) -> dict[int, list[str]]:
    """Top terms per cluster using c-TF-IDF (the BERTopic trick).

    Each cluster's combined token list is treated as one "document".
    A term's score is its frequency within the cluster (tf), weighted
    down the more clusters it also appears in (idf), so a term that is
    common everywhere (like "highlights" in a sports corpus) scores
    lower than one that is distinctive to this cluster, even if both
    are frequent within it.
    """
    cluster_counts = {cid: Counter(tokens) for cid, tokens in cluster_tokens.items()}
    doc_freq: Counter = Counter()
    for counts in cluster_counts.values():
        doc_freq.update(counts.keys())
    n_clusters = len(cluster_counts)

    top_terms: dict[int, list[str]] = {}
    for cluster_id, counts in cluster_counts.items():
        total_terms = sum(counts.values()) or 1
        scored = []
        for term, count in counts.items():
            tf = count / total_terms
            # A term in every cluster scores exactly zero (log(1) == 0):
            # being everywhere carries no information about this one.
            # With a single cluster total there is nothing to compare
            # against, so idf is skipped and raw frequency ranks terms.
            idf = 1.0 if n_clusters <= 1 else math.log(n_clusters / doc_freq[term])
            scored.append((tf * idf, term))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        top_terms[cluster_id] = [term for _, term in scored[:top_n]]
    return top_terms


def compute_centroids(
    embeddings: np.ndarray, labels: np.ndarray
) -> dict[int, np.ndarray]:
    """Mean embedding per cluster, excluding noise (-1)."""
    centroids: dict[int, np.ndarray] = {}
    for cluster_id in sorted(set(int(label) for label in labels)):
        if cluster_id == -1:
            continue
        mask = labels == cluster_id
        centroids[cluster_id] = embeddings[mask].mean(axis=0)
    return centroids


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def assign_noise_points(
    embeddings: np.ndarray,
    labels: np.ndarray,
    centroids: dict[int, np.ndarray],
    threshold: float = NOISE_SIMILARITY_THRESHOLD,
) -> np.ndarray:
    """Reassign noise points (-1) to the nearest centroid above `threshold`.

    Points that don't clear the bar for any centroid stay at -1: no
    niche is better than a bad-fit one.
    """
    new_labels = labels.copy()
    if not centroids:
        return new_labels
    for i, label in enumerate(labels):
        if label != -1:
            continue
        best_cluster_id = None
        best_similarity = -1.0
        for cluster_id, centroid in centroids.items():
            similarity = _cosine_similarity(embeddings[i], centroid)
            if similarity > best_similarity:
                best_similarity, best_cluster_id = similarity, cluster_id
        if best_cluster_id is not None and best_similarity > threshold:
            new_labels[i] = best_cluster_id
    return new_labels


def channel_mode_niche(
    pairs: Iterable[tuple[str, int | None]],
) -> dict[str, int]:
    """Each channel's niche is the mode among its own videos' niches.

    Videos with no niche don't count toward any channel's mode. Ties
    are broken by the smaller niche id, for determinism.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    for channel_id, niche_id in pairs:
        if niche_id is None:
            continue
        counts[channel_id][niche_id] += 1
    result: dict[str, int] = {}
    for channel_id, counter in counts.items():
        best_niche_id, _ = min(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        result[channel_id] = best_niche_id
    return result


def reduce_and_cluster(
    embeddings: np.ndarray,
    algorithm: str = "hdbscan",
    random_state: int = 42,
) -> np.ndarray:
    """Reduce dimensionality with UMAP, then cluster. Returns integer labels.

    algorithm="kmeans" swaps HDBSCAN for a fixed-k MiniBatchKMeans, for
    corpora where density-based clustering degenerates (everything is
    noise, or everything is one cluster).
    """
    import umap

    n_samples = len(embeddings)
    n_components = max(2, min(UMAP_N_COMPONENTS, n_samples - 2))
    n_neighbors = max(2, min(UMAP_N_NEIGHBORS, n_samples - 1))
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        random_state=random_state,
    )
    reduced = reducer.fit_transform(embeddings)

    if algorithm == "kmeans":
        from sklearn.cluster import MiniBatchKMeans

        k = min(KMEANS_K, n_samples)
        model = MiniBatchKMeans(n_clusters=k, random_state=random_state, n_init="auto")
        return model.fit_predict(reduced)

    from sklearn.cluster import HDBSCAN

    # copy=True pinned explicitly: scikit-learn's default flips in a
    # future release, and this call site should not change behavior
    # out from under it.
    model = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, copy=True)
    return model.fit_predict(reduced)


async def _fetch_clustering_rows(session_factory) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import Video, VideoEmbedding

    async with session_factory() as session:
        stmt = (
            select(Video.id, Video.channel_id, Video.title, VideoEmbedding.embedding)
            .join(VideoEmbedding, VideoEmbedding.video_id == Video.id)
            .where(Video.detected_language == "en")
        )
        result = await session.execute(stmt)
        return [dict(row._mapping) for row in result]


async def run_clustering(session_factory, algorithm: str = "hdbscan") -> dict:
    """Recompute every niche from the current embedded English corpus."""
    from sqlalchemy import delete, update

    from app.db.models import Channel, Niche, Video

    rows = await _fetch_clustering_rows(session_factory)
    if len(rows) < MIN_ROWS_FOR_CLUSTERING:
        print(
            f"Only {len(rows)} embedded English videos; skipping clustering "
            f"(need at least {MIN_ROWS_FOR_CLUSTERING})."
        )
        return {"videos_considered": len(rows), "clusters": 0, "assigned_videos": 0}

    embeddings = np.array(
        [np.asarray(row["embedding"], dtype=np.float32) for row in rows],
        dtype=np.float32,
    )
    raw_labels = reduce_and_cluster(embeddings, algorithm=algorithm)
    centroids = compute_centroids(embeddings, raw_labels)
    labels = assign_noise_points(embeddings, raw_labels, centroids)
    cluster_ids = sorted(centroids.keys())

    cluster_tokens: dict[int, list[str]] = defaultdict(list)
    for label, row in zip(labels, rows):
        if int(label) == -1:
            continue
        cluster_tokens[int(label)].extend(tokenize(row["title"]))
    top_terms_map = compute_c_tfidf(cluster_tokens)

    async with session_factory() as session:
        await session.execute(delete(Niche))
        await session.flush()

        niche_id_by_cluster: dict[int, int] = {}
        for cluster_id in cluster_ids:
            member_indices = [i for i, label in enumerate(labels) if int(label) == cluster_id]
            channels_in_cluster = {rows[i]["channel_id"] for i in member_indices}
            terms = top_terms_map.get(cluster_id, [])
            label_text = " / ".join(terms[:LABEL_TERM_COUNT]) or f"niche-{cluster_id}"
            niche = Niche(
                label=label_text,
                top_terms=terms or None,
                centroid=centroids[cluster_id].tolist(),
                video_count=len(member_indices),
                channel_count=len(channels_in_cluster),
            )
            session.add(niche)
            await session.flush()
            niche_id_by_cluster[cluster_id] = niche.id

        videos_by_niche: dict[int | None, list[str]] = defaultdict(list)
        pairs: list[tuple[str, int | None]] = []
        for i, row in enumerate(rows):
            cluster_id = int(labels[i])
            niche_id = niche_id_by_cluster.get(cluster_id) if cluster_id != -1 else None
            videos_by_niche[niche_id].append(row["id"])
            pairs.append((row["channel_id"], niche_id))
        for niche_id, video_ids in videos_by_niche.items():
            await session.execute(
                update(Video).where(Video.id.in_(video_ids)).values(niche_id=niche_id)
            )

        channel_niches = channel_mode_niche(pairs)
        channels_by_niche: dict[int, list[str]] = defaultdict(list)
        for channel_id, niche_id in channel_niches.items():
            channels_by_niche[niche_id].append(channel_id)
        for niche_id, channel_ids_for_niche in channels_by_niche.items():
            await session.execute(
                update(Channel)
                .where(Channel.id.in_(channel_ids_for_niche))
                .values(niche_id=niche_id)
            )

        await session.commit()

    assigned = int(sum(1 for label in labels if int(label) != -1))
    return {
        "videos_considered": len(rows),
        "clusters": len(cluster_ids),
        "assigned_videos": assigned,
        "unassigned_videos": len(rows) - assigned,
    }
