"""Baseline breakout-prediction models: LogisticRegression and
HistGradientBoostingClassifier, both trained on the raw 384-dim
embedding concatenated with the (scaled) tabular features.

No PCA or other dimensionality reduction is applied to the embedding.
An earlier version of this plan reduced the embedding to 64 components
with PCA before handing it to the baselines, which handicapped them
relative to the embedding's actual information content — this version
deliberately does not repeat that mistake.

Evaluated with the fixed GroupKFold split from folds.py (grouped by
channel_id), so a channel's videos never span train and test within a
fold: the question each fold answers is "does this generalize to an
unseen channel," not "does it memorize a channel's typical view
counts." StandardScaler is fit on each fold's training tabular slice
only (dataset.scale_train_test) — no leakage from test into the fit.
"""

from __future__ import annotations

import inspect
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from src import dataset, evaluate, folds

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCALER_PATH = DATA_DIR / "scaler.pkl"
FOLDS_PATH = DATA_DIR / "folds.json"


def hgb_kwargs() -> dict:
    """class_weight support on HistGradientBoostingClassifier varies by
    scikit-learn version (added later than the estimator itself); check
    the installed version's signature rather than assuming an API that
    may not exist."""
    params = inspect.signature(HistGradientBoostingClassifier).parameters
    if "class_weight" in params:
        return {"class_weight": "balanced", "random_state": 42}
    return {"random_state": 42}


def train_and_evaluate_fold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    save_scaler_path: str | Path | None = None,
) -> dict | None:
    """Fit both baselines on one fold's train split, score the held-out
    channels, and return {model_name: metrics}.

    Returns None when the training split has only one label class:
    scikit-learn's classifiers require at least 2 classes to fit and
    raise otherwise. On a thin or heavily-imbalanced corpus (the fake
    sample corpus, whose breakout labels are meaningless by
    construction — see labels.py — is expected to produce very few or
    zero positives), a single fold coming up single-class is a real,
    expected outcome, not a bug; the caller skips that fold rather than
    letting the ValueError propagate.

    `save_scaler_path`, when given, pickles the fitted scaler — the
    caller passes this only for the last fold trained (see run()): a
    v1 simplification so downstream serving code has *something* to
    load, documented here rather than presented as a production
    artifact. It was fit on one fold's data, not the full corpus.
    """
    if len(set(np.asarray(y_train).tolist())) < 2:
        return None

    X_train_scaled, X_test_scaled, scaler = dataset.scale_train_test(X_train, X_test)

    if save_scaler_path is not None:
        Path(save_scaler_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_scaler_path, "wb") as f:
            pickle.dump(scaler, f)

    logreg = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
    logreg.fit(X_train_scaled, y_train)
    logreg_scores = logreg.predict_proba(X_test_scaled)[:, 1]

    hgb = HistGradientBoostingClassifier(**hgb_kwargs())
    hgb.fit(X_train_scaled, y_train)
    hgb_scores = hgb.predict_proba(X_test_scaled)[:, 1]

    return {
        "logistic_regression": evaluate.compute_metrics(y_test, logreg_scores),
        "hist_gradient_boosting": evaluate.compute_metrics(y_test, hgb_scores),
    }


def run_over_folds(
    X: np.ndarray,
    y: np.ndarray,
    fold_by_video: dict[str, int],
    video_ids: list[str],
    scaler_path: str | Path | None = SCALER_PATH,
) -> dict[str, dict[int, dict]]:
    """Iterate every fold, train both baselines, collect per-fold metrics.

    Kept separate from run() so the fold-iteration logic is a plain
    function over arrays/dicts you could call in a test even though no
    test actually trains a model here (too slow/heavy for pytest).
    """
    fold_indices = np.array([fold_by_video[video_id] for video_id in video_ids])
    n_folds = len(set(fold_by_video.values()))

    results: dict[str, dict[int, dict]] = {
        "logistic_regression": {},
        "hist_gradient_boosting": {},
    }
    for fold_index in range(n_folds):
        test_mask = fold_indices == fold_index
        train_mask = ~test_mask
        if test_mask.sum() == 0 or train_mask.sum() == 0:
            continue
        save_path = scaler_path if (fold_index == n_folds - 1 and scaler_path) else None
        metrics = train_and_evaluate_fold(
            X[train_mask], y[train_mask], X[test_mask], y[test_mask], save_scaler_path=save_path
        )
        if metrics is None:
            print(
                f"Fold {fold_index}: training split has only one label class; "
                "skipping (expected on a thin or heavily-imbalanced corpus)."
            )
            continue
        for model_name, model_metrics in metrics.items():
            results[model_name][fold_index] = model_metrics
    return results


def run(dataset_path: str | Path | None = None, folds_path: str | Path = FOLDS_PATH) -> dict:
    df = dataset.load_export(dataset_path) if dataset_path else dataset.load_export()
    assembled = dataset.assemble_dataset(df)
    if assembled is None:
        raise SystemExit(
            "No video cleared both the labeling window and the channel-baseline "
            "gate (see labels.py) - nothing to train on."
        )

    fold_by_video = folds.make_folds(assembled["video_ids"], assembled["groups"])
    folds.save_folds(fold_by_video, folds_path)

    results = run_over_folds(
        assembled["X"], assembled["y"], fold_by_video, assembled["video_ids"]
    )
    table = evaluate.summarize_folds(results)
    return {"results": results, "table": table, "n_labeled": len(assembled["video_ids"])}


if __name__ == "__main__":
    outcome = run()
    print(f"{outcome['n_labeled']} labeled videos.")
    for row in outcome["table"]:
        print(row)
