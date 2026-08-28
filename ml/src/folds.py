"""GroupKFold fold assignment, grouped by channel_id, saved to disk so
every model (both sklearn baselines and the PyTorch model) trains and
evaluates on the exact same split. A channel's videos never span train
and test within a fold, so the question each fold answers is "does
this generalize to an unseen channel," not "does it memorize a
channel's typical view counts."

Fallback: 5-fold GroupKFold needs at least 5 distinct groups
(sklearn's GroupKFold requires n_groups >= n_splits). The sample
corpus has only 12 channels total, and only a fraction of those will
have any labeled videos at all (see labels.py's channel-baseline
gate) — degenerate or outright failing 5-fold splits are the expected
case here, not an edge case to paper over. make_folds falls back to
as many folds as there are distinct channel groups among the labeled
videos, with a floor of MIN_SPLITS (2): below that, no fold could hold
out a whole group and the exercise wouldn't test generalization at
all, so it raises instead of producing something that looks like
cross-validation but isn't.
"""

from __future__ import annotations

import json
from pathlib import Path

from sklearn.model_selection import GroupKFold

DEFAULT_N_SPLITS = 5
MIN_SPLITS = 2


def make_folds(
    video_ids: list[str],
    groups: list[str],
    n_splits: int = DEFAULT_N_SPLITS,
    min_splits: int = MIN_SPLITS,
) -> dict[str, int]:
    """video_id -> fold index, via GroupKFold on `groups` (channel_id).

    Raises ValueError if fewer than `min_splits` distinct groups exist
    — see the module docstring for why that's a hard stop rather than
    a silent 1-fold "evaluation."
    """
    if len(video_ids) != len(groups):
        raise ValueError("video_ids and groups must be the same length")

    n_groups = len(set(groups))
    effective_splits = min(n_splits, n_groups)
    if effective_splits < min_splits:
        raise ValueError(
            f"Only {n_groups} distinct channel group(s) among labeled videos; "
            f"need at least {min_splits} for a meaningful GroupKFold split."
        )
    if effective_splits < n_splits:
        print(
            f"Only {n_groups} distinct channels among labeled videos; "
            f"using {effective_splits} folds instead of the default {n_splits}."
        )

    splitter = GroupKFold(n_splits=effective_splits)
    fold_by_video: dict[str, int] = {}
    dummy_X = list(range(len(video_ids)))
    for fold_index, (_, test_idx) in enumerate(splitter.split(dummy_X, groups=groups)):
        for i in test_idx:
            fold_by_video[video_ids[i]] = fold_index
    return fold_by_video


def save_folds(fold_by_video: dict[str, int], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fold_by_video, indent=2, sort_keys=True))


def load_folds(path: str | Path) -> dict[str, int]:
    return json.loads(Path(path).read_text())
