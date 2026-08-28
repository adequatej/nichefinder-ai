"""Sanity check of BreakoutNet's architecture: shapes only, no training.

A single forward pass on random tensors is fast (no optimizer, no
epochs) and catches shape-mismatch bugs (the embedding/tabular branch
sizes, the concat dimension) without the cost of an actual training
loop, which is deliberately left out of this suite (see
train_torch.py).
"""

from __future__ import annotations

import torch

from src.model import COMBINED_HIDDEN, EMBEDDING_DIM, EMBEDDING_HIDDEN, TABULAR_HIDDEN, BreakoutNet


def test_forward_pass_output_shape():
    tabular_dim = 40
    batch_size = 8
    model = BreakoutNet(tabular_dim=tabular_dim)

    embedding = torch.randn(batch_size, EMBEDDING_DIM)
    tabular = torch.randn(batch_size, tabular_dim)

    logits = model(embedding, tabular)

    assert logits.shape == (batch_size,)


def test_branch_and_combined_dims_are_consistent():
    tabular_dim = 17
    model = BreakoutNet(tabular_dim=tabular_dim)

    # embedding_branch: Linear(EMBEDDING_DIM, EMBEDDING_HIDDEN)
    first_linear = model.embedding_branch[0]
    assert first_linear.in_features == EMBEDDING_DIM
    assert first_linear.out_features == EMBEDDING_HIDDEN

    tab_linear = model.tabular_branch[0]
    assert tab_linear.in_features == tabular_dim
    assert tab_linear.out_features == TABULAR_HIDDEN

    head_linear = model.head[0]
    assert head_linear.in_features == EMBEDDING_HIDDEN + TABULAR_HIDDEN
    assert head_linear.out_features == COMBINED_HIDDEN

    final_linear = model.head[-1]
    assert final_linear.out_features == 1
