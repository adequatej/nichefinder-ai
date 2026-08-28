"""Tests for evaluate.py's metrics on small synthetic prediction arrays
with hand-computed expected values."""

from __future__ import annotations

import pytest

from src.evaluate import (
    calibration_summary,
    compute_metrics,
    pr_auc,
    precision_at_k,
    roc_auc,
    summarize_folds,
)


def test_precision_at_k_basic():
    # Top 3 by score are indices 4,3,2 with true labels 1,0,1 -> 2/3.
    y_true = [0, 0, 1, 0, 1]
    y_score = [0.1, 0.2, 0.6, 0.5, 0.9]
    result = precision_at_k(y_true, y_score, k=3)
    assert result["k_used"] == 3
    assert result["precision"] == pytest.approx(2 / 3)


def test_precision_at_k_uses_fewer_than_k_when_not_enough_rows():
    y_true = [1, 0]
    y_score = [0.9, 0.1]
    result = precision_at_k(y_true, y_score, k=50)
    assert result["k_used"] == 2
    assert result["precision"] == pytest.approx(0.5)


def test_precision_at_k_empty_input():
    result = precision_at_k([], [], k=50)
    assert result["k_used"] == 0
    assert result["precision"] is None


def test_pr_auc_and_roc_auc_none_with_single_class():
    assert pr_auc([0, 0, 0], [0.1, 0.2, 0.3]) is None
    assert roc_auc([1, 1, 1], [0.1, 0.2, 0.3]) is None


def test_pr_auc_and_roc_auc_perfect_separation():
    y_true = [0, 0, 1, 1]
    y_score = [0.1, 0.2, 0.8, 0.9]
    assert pr_auc(y_true, y_score) == pytest.approx(1.0)
    assert roc_auc(y_true, y_score) == pytest.approx(1.0)


def test_calibration_summary_bucket_count_and_means():
    y_true = [0, 0, 1, 1]
    y_score = [0.1, 0.2, 0.8, 0.9]
    summary = calibration_summary(y_true, y_score, n_buckets=2)
    assert len(summary) == 2
    assert summary[0]["mean_predicted"] == pytest.approx(0.15)
    assert summary[0]["mean_actual"] == pytest.approx(0.0)
    assert summary[1]["mean_predicted"] == pytest.approx(0.85)
    assert summary[1]["mean_actual"] == pytest.approx(1.0)


def test_calibration_summary_empty_input():
    assert calibration_summary([], []) == []


def test_compute_metrics_shape():
    y_true = [0, 1, 1, 0]
    y_score = [0.2, 0.9, 0.6, 0.4]
    metrics = compute_metrics(y_true, y_score, k=2)
    assert metrics["n"] == 4
    assert metrics["n_positive"] == 2
    assert metrics["precision_at_k_n"] == 2
    assert metrics["pr_auc"] is not None
    assert metrics["roc_auc"] is not None


def test_summarize_folds_mean_and_std():
    results = {
        "model_a": {
            0: {"pr_auc": 0.5, "roc_auc": 0.6},
            1: {"pr_auc": 0.7, "roc_auc": 0.8},
        }
    }
    table = summarize_folds(results)
    assert len(table) == 1
    row = table[0]
    assert row["model"] == "model_a"
    assert row["n_folds"] == 2
    assert row["pr_auc_mean"] == pytest.approx(0.6)
    assert row["roc_auc_mean"] == pytest.approx(0.7)


def test_summarize_folds_skips_none_values():
    results = {
        "model_a": {
            0: {"pr_auc": None, "roc_auc": 0.6},
            1: {"pr_auc": 0.7, "roc_auc": 0.8},
        }
    }
    table = summarize_folds(results)
    row = table[0]
    # Only one fold had a non-None pr_auc, so the mean equals it exactly.
    assert row["pr_auc_mean"] == pytest.approx(0.7)
