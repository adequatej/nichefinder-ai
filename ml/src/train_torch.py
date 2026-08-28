"""PyTorch training loop for the two-branch breakout model (model.py).

Same fixed GroupKFold split as train_baselines.py (ml/data/folds.json
— reused if it already exists, generated and saved if not, so both
scripts are guaranteed to evaluate on identical folds regardless of
which one runs first). Same tabular-only StandardScaler approach as
the baselines (dataset.scale_train_test): the embedding stays raw,
only the tabular slice is fit-and-scaled per fold.

BCEWithLogitsLoss with pos_weight computed from each fold's own
training label balance (not the whole corpus, to avoid leaking test
fold information into the loss weighting). AdamW optimizer. Early
stopping tracks the best validation PR-AUC per fold and stops after
PATIENCE epochs without improvement, restoring the best-seen weights
before scoring — this is a small dataset, so MAX_EPOCHS is a
generous cap that will rarely be reached.

Reproducibility: random/numpy/torch seeds are all fixed (see
set_seed). Two runs of run() on the same input should therefore
produce the same metrics; exact floating-point reproducibility across
different torch versions or hardware (CPU vs. GPU, different BLAS
backends) is not guaranteed by PyTorch itself, so "seeded reruns
reproduce" is verified on one machine/torch version, not promised
across all of them.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from src import dataset, evaluate, folds
from src.model import BreakoutNet, EMBEDDING_DIM

SEED = 42
MAX_EPOCHS = 100
PATIENCE = 10
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FOLDS_PATH = DATA_DIR / "folds.json"


def set_seed(seed: int = SEED) -> None:
    """Seed every source of randomness this module touches.

    torch.set_num_threads(1) matters as much as the seed itself here:
    PyTorch's default multi-threaded CPU matmul sums partial results in
    a thread-scheduling-dependent order, so floating point results can
    differ slightly between runs *even with identical seeds* unless
    it's pinned to one thread. This is a small dataset, so the speed
    cost of single-threading is negligible.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)


def _pos_weight(y_train: np.ndarray) -> torch.Tensor:
    n_pos = float(y_train.sum())
    n_neg = float(len(y_train) - n_pos)
    if n_pos == 0:
        # No positives in this fold's training split: nothing to
        # up-weight against; pos_weight=1 leaves BCE unweighted rather
        # than dividing by zero.
        return torch.tensor([1.0])
    return torch.tensor([n_neg / n_pos])


def train_one_fold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    tabular_dim: int,
    seed: int = SEED,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
) -> dict:
    set_seed(seed)

    model = BreakoutNet(tabular_dim=tabular_dim)

    emb_train = torch.tensor(X_train[:, :EMBEDDING_DIM], dtype=torch.float32)
    tab_train = torch.tensor(X_train[:, EMBEDDING_DIM:], dtype=torch.float32)
    y_train_t = torch.tensor(y_train, dtype=torch.float32)
    emb_test = torch.tensor(X_test[:, :EMBEDDING_DIM], dtype=torch.float32)
    tab_test = torch.tensor(X_test[:, EMBEDDING_DIM:], dtype=torch.float32)

    criterion = nn.BCEWithLogitsLoss(pos_weight=_pos_weight(y_train))
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    train_loader = DataLoader(
        TensorDataset(emb_train, tab_train, y_train_t),
        batch_size=min(BATCH_SIZE, len(y_train)),
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )

    best_pr_auc = -1.0
    best_state = None
    epochs_without_improvement = 0

    for _epoch in range(max_epochs):
        model.train()
        for emb_batch, tab_batch, y_batch in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(emb_batch, tab_batch), y_batch)
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_probs = torch.sigmoid(model(emb_test, tab_test)).numpy()
        val_pr_auc = evaluate.pr_auc(y_test, val_probs)
        val_pr_auc = val_pr_auc if val_pr_auc is not None else -1.0

        if val_pr_auc > best_pr_auc:
            best_pr_auc = val_pr_auc
            best_state = {key: value.clone() for key, value in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        final_probs = torch.sigmoid(model(emb_test, tab_test)).numpy()

    return evaluate.compute_metrics(y_test, final_probs)


def run_over_folds(
    X: np.ndarray,
    y: np.ndarray,
    fold_by_video: dict[str, int],
    video_ids: list[str],
    tabular_dim: int,
) -> dict[int, dict]:
    """Iterate every fold, train the model, collect per-fold metrics.

    Kept separate from run() so fold iteration is a plain function over
    arrays/dicts, even though no test actually trains a model here.
    """
    fold_indices = np.array([fold_by_video[video_id] for video_id in video_ids])
    n_folds = len(set(fold_by_video.values()))

    results: dict[int, dict] = {}
    for fold_index in range(n_folds):
        test_mask = fold_indices == fold_index
        train_mask = ~test_mask
        if test_mask.sum() == 0 or train_mask.sum() == 0:
            continue
        if len(set(y[train_mask].tolist())) < 2:
            # Unlike the sklearn baselines, BCEWithLogitsLoss doesn't
            # require both classes to be present to fit (pos_weight
            # falls back to 1.0 - see _pos_weight), so this fold is
            # still trained, just noted: a single-class training split
            # is a real, expected outcome on a thin or imbalanced
            # corpus (the fake sample corpus's labels are meaningless
            # by construction - see labels.py), not a bug.
            print(
                f"Fold {fold_index}: training split has only one label class; "
                "training anyway (pos_weight falls back to 1.0)."
            )
        X_train_scaled, X_test_scaled, _scaler = dataset.scale_train_test(
            X[train_mask], X[test_mask]
        )
        results[fold_index] = train_one_fold(
            X_train_scaled, y[train_mask], X_test_scaled, y[test_mask], tabular_dim
        )
    return results


def run(dataset_path: str | Path | None = None, folds_path: str | Path = FOLDS_PATH) -> dict:
    df = dataset.load_export(dataset_path) if dataset_path else dataset.load_export()
    assembled = dataset.assemble_dataset(df)
    if assembled is None:
        raise SystemExit(
            "No video cleared both the labeling window and the channel-baseline "
            "gate (see labels.py) - nothing to train on."
        )

    X, y, video_ids, groups = (
        assembled["X"],
        assembled["y"],
        assembled["video_ids"],
        assembled["groups"],
    )
    tabular_dim = X.shape[1] - EMBEDDING_DIM

    folds_path = Path(folds_path)
    if folds_path.exists():
        fold_by_video = folds.load_folds(folds_path)
    else:
        fold_by_video = folds.make_folds(video_ids, groups)
        folds.save_folds(fold_by_video, folds_path)

    results = run_over_folds(X, y, fold_by_video, video_ids, tabular_dim)
    table = evaluate.summarize_folds({"pytorch_mlp": results})
    return {"results": {"pytorch_mlp": results}, "table": table, "n_labeled": len(video_ids)}


if __name__ == "__main__":
    outcome = run()
    print(f"{outcome['n_labeled']} labeled videos.")
    for row in outcome["table"]:
        print(row)
