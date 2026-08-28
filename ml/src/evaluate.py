"""Shared evaluation utilities for both the sklearn baselines and the
PyTorch model, so every model is judged the same way on the same
folds.

compute_metrics is the one entry point both train_baselines.py and
train_torch.py call per fold; summarize_folds turns a
{model_name: {fold_index: metrics}} dict (train_baselines.py trains
two models per fold, train_torch.py trains one, but the shape is the
same) into the mean +/- std comparison rows that ship in ml/README.md.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

DEFAULT_K = 50
DEFAULT_CALIBRATION_BUCKETS = 10


def precision_at_k(y_true, y_score, k: int = DEFAULT_K) -> dict:
    """Precision among the top-k predicted-probability videos.

    Uses however many eligible videos exist when there are fewer than
    k, and reports k_used so callers/readers know a fold's precision@50
    was really precision@(fewer than 50) — noted rather than crashing.
    """
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score)
    n = len(y_true)
    k_used = min(k, n)
    if k_used == 0:
        return {"precision": None, "k_used": 0}
    order = np.argsort(-y_score)[:k_used]
    hits = float(y_true[order].sum())
    return {"precision": hits / k_used, "k_used": k_used}


def pr_auc(y_true, y_score) -> float | None:
    """Average precision (PR-AUC). None when only one class is present
    in y_true — undefined in that case, not zero."""
    if len(set(np.asarray(y_true).tolist())) < 2:
        return None
    return float(average_precision_score(y_true, y_score))


def roc_auc(y_true, y_score) -> float | None:
    """None when only one class is present in y_true, same reasoning as pr_auc."""
    if len(set(np.asarray(y_true).tolist())) < 2:
        return None
    return float(roc_auc_score(y_true, y_score))


def calibration_summary(y_true, y_score, n_buckets: int = DEFAULT_CALIBRATION_BUCKETS) -> list[dict]:
    """Decile (or n_buckets-ile) calibration: sort by predicted score,
    split into equal-ish rank buckets, report each bucket's mean
    predicted probability vs. mean actual label. A well-calibrated
    model has mean_predicted roughly equal to mean_actual in every
    bucket. No plot — this is a plain data structure, matplotlib isn't
    a dependency here.
    """
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score)
    n = len(y_true)
    if n == 0:
        return []
    order = np.argsort(y_score)
    y_true_sorted = y_true[order]
    y_score_sorted = y_score[order]
    summary = []
    for bucket_index, indices in enumerate(np.array_split(np.arange(n), min(n_buckets, n))):
        if len(indices) == 0:
            continue
        summary.append(
            {
                "bucket": bucket_index,
                "n": int(len(indices)),
                "mean_predicted": float(y_score_sorted[indices].mean()),
                "mean_actual": float(y_true_sorted[indices].mean()),
            }
        )
    return summary


def compute_metrics(y_true, y_score, k: int = DEFAULT_K) -> dict:
    """The full metrics dict for one fold's predictions: PR-AUC, ROC-AUC,
    precision@k, plus n/n_positive for context when reading a table of
    these across folds."""
    y_true = np.asarray(y_true)
    p_at_k = precision_at_k(y_true, y_score, k)
    return {
        "pr_auc": pr_auc(y_true, y_score),
        "roc_auc": roc_auc(y_true, y_score),
        "precision_at_k": p_at_k["precision"],
        "precision_at_k_n": p_at_k["k_used"],
        "n": int(len(y_true)),
        "n_positive": int(y_true.sum()),
    }


def summarize_folds(results: dict[str, dict[int, dict]]) -> list[dict]:
    """{model_name: {fold_index: metrics}} -> mean +/- std comparison rows.

    Only numeric, non-None metric values contribute to a mean/std; a
    metric that was None in every fold (for example pr_auc on a fold
    with a single class) is simply absent from that model's row rather
    than reported as a fabricated 0.
    """
    rows = []
    for model_name, folds in results.items():
        metric_names: set[str] = set()
        for metrics in folds.values():
            metric_names.update(
                name
                for name, value in metrics.items()
                if isinstance(value, (int, float)) and value is not None
            )
        row: dict = {"model": model_name, "n_folds": len(folds)}
        for name in sorted(metric_names):
            values = [
                metrics[name]
                for metrics in folds.values()
                if metrics.get(name) is not None
            ]
            if values:
                row[f"{name}_mean"] = float(np.mean(values))
                row[f"{name}_std"] = float(np.std(values))
        rows.append(row)
    return rows
