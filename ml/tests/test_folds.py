"""Tests for the GroupKFold wrapper and its small-corpus fallback."""

from __future__ import annotations

import json

import pytest

from src.folds import load_folds, make_folds, save_folds


def _video_ids_and_groups(group_sizes: dict[str, int]) -> tuple[list[str], list[str]]:
    video_ids, groups = [], []
    for group, size in group_sizes.items():
        for i in range(size):
            video_ids.append(f"{group}-v{i}")
            groups.append(group)
    return video_ids, groups


def test_make_folds_uses_default_when_enough_groups():
    video_ids, groups = _video_ids_and_groups({f"c{i}": 4 for i in range(6)})
    fold_by_video = make_folds(video_ids, groups, n_splits=5)
    assert len(set(fold_by_video.values())) == 5
    # Every video got assigned.
    assert set(fold_by_video.keys()) == set(video_ids)


def test_make_folds_falls_back_to_fewer_splits(capsys):
    # Only 3 distinct channels: default 5-fold isn't possible.
    video_ids, groups = _video_ids_and_groups({"c1": 3, "c2": 3, "c3": 3})
    fold_by_video = make_folds(video_ids, groups, n_splits=5)
    assert len(set(fold_by_video.values())) == 3
    captured = capsys.readouterr()
    assert "using 3 folds instead of the default 5" in captured.out


def test_make_folds_a_channels_videos_never_split_across_folds():
    video_ids, groups = _video_ids_and_groups({"c1": 5, "c2": 5, "c3": 5})
    fold_by_video = make_folds(video_ids, groups, n_splits=3)
    for group in ("c1", "c2", "c3"):
        member_folds = {fold_by_video[vid] for vid in video_ids if vid.startswith(group)}
        assert len(member_folds) == 1


def test_make_folds_raises_below_min_splits():
    video_ids, groups = _video_ids_and_groups({"c1": 5})
    with pytest.raises(ValueError, match="need at least 2"):
        make_folds(video_ids, groups, n_splits=5, min_splits=2)


def test_make_folds_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        make_folds(["v1", "v2"], ["c1"])


def test_save_and_load_folds_round_trip(tmp_path):
    fold_by_video = {"v1": 0, "v2": 1}
    path = tmp_path / "folds.json"
    save_folds(fold_by_video, path)
    assert json.loads(path.read_text()) == fold_by_video
    assert load_folds(path) == fold_by_video
