"""Tests for the pure clustering math: tokenize, c-TF-IDF, centroids,
noise assignment, and channel-mode-niche. No UMAP/HDBSCAN/database.
"""

from __future__ import annotations

import numpy as np

from app.services.clustering import (
    assign_noise_points,
    channel_mode_niche,
    compute_c_tfidf,
    compute_centroids,
    tokenize,
)


def test_tokenize_lowercases_splits_and_drops_stopwords():
    tokens = tokenize("Seiwa Gakuen vs Aomori Yamada - Highlights!")
    assert "vs" not in tokens
    assert "gakuen" in tokens
    assert "seiwa" in tokens
    assert all(token == token.lower() for token in tokens)


def test_tokenize_drops_short_tokens_and_handles_empty():
    assert tokenize("a an ok") == []
    assert tokenize("") == []
    assert tokenize(None) == []


def test_c_tfidf_distinguishes_obviously_different_clusters():
    cluster_tokens = {
        0: tokenize("Seiwa Gakuen vs Aomori Yamada Soccer Highlights") * 5,
        1: tokenize("Koshien Baseball Highlights Full Recap") * 5,
    }
    top_terms = compute_c_tfidf(cluster_tokens, top_n=3)
    # "highlights" is common to both clusters, so it should not crowd
    # out the terms that are actually distinctive to each one.
    assert "soccer" in top_terms[0] or "seiwa" in top_terms[0]
    assert "baseball" in top_terms[1] or "koshien" in top_terms[1]
    assert top_terms[0] != top_terms[1]


def test_c_tfidf_downweights_terms_common_to_every_cluster():
    cluster_tokens = {
        0: ["highlights"] * 10 + ["soccer"] * 2,
        1: ["highlights"] * 10 + ["baseball"] * 2,
    }
    top_terms = compute_c_tfidf(cluster_tokens, top_n=1)
    # Despite "highlights" being far more frequent, the distinctive
    # term wins each cluster's top spot because it never appears
    # elsewhere.
    assert top_terms[0] == ["soccer"]
    assert top_terms[1] == ["baseball"]


def test_compute_centroids_excludes_noise():
    embeddings = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [5.0, 5.0]]
    )
    labels = np.array([0, 0, 1, 1, -1])
    centroids = compute_centroids(embeddings, labels)
    assert set(centroids.keys()) == {0, 1}
    assert np.allclose(centroids[0], [1.0, 0.0])
    assert np.allclose(centroids[1], [0.0, 1.0])


def test_assign_noise_points_joins_similar_cluster():
    embeddings = np.array(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
            [0.99, 0.05],  # near cluster 0
            [-1.0, 0.0],  # opposite of everything
        ]
    )
    labels = np.array([0, 0, 1, 1, -1, -1])
    centroids = compute_centroids(embeddings, labels)
    new_labels = assign_noise_points(embeddings, labels, centroids, threshold=0.5)
    assert new_labels[4] == 0
    # Cosine similarity to both centroids is 0 or negative, so this
    # point stays unassigned rather than being forced in.
    assert new_labels[5] == -1


def test_assign_noise_points_respects_threshold():
    embeddings = np.array([[1.0, 0.0], [1.0, 0.0], [0.6, 0.6]])
    labels = np.array([0, 0, -1])
    centroids = compute_centroids(embeddings, labels)
    # cosine(0.6,0.6 vs 1,0) ~ 0.707, clears a low bar...
    lenient = assign_noise_points(embeddings, labels, centroids, threshold=0.5)
    assert lenient[2] == 0
    # ...but not a high one.
    strict = assign_noise_points(embeddings, labels, centroids, threshold=0.95)
    assert strict[2] == -1


def test_channel_mode_niche_picks_most_common_and_ignores_unassigned():
    pairs = [
        ("UC1", 1),
        ("UC1", 1),
        ("UC1", 2),
        ("UC1", None),
        ("UC2", 3),
        ("UC2", None),
    ]
    result = channel_mode_niche(pairs)
    assert result == {"UC1": 1, "UC2": 3}


def test_channel_mode_niche_breaks_ties_deterministically():
    pairs = [("UC1", 5), ("UC1", 2)]
    assert channel_mode_niche(pairs) == {"UC1": 2}
