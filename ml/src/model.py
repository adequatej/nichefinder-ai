"""The PyTorch breakout model: architecture only, no training loop.

Two-branch MLP: the 384-dim embedding gets its own branch (embedding
structure is different in kind from the tabular features, so a shared
first layer would force the network to learn a common representation
before it's had a chance to specialize), the tabular features get a
smaller branch, and the two branches' outputs are concatenated before
a small combined head. See train_torch.py for the training loop, loss,
and optimizer.
"""

from __future__ import annotations

import torch
from torch import nn

EMBEDDING_DIM = 384
EMBEDDING_HIDDEN = 128
TABULAR_HIDDEN = 32
COMBINED_HIDDEN = 64
DROPOUT = 0.3


class BreakoutNet(nn.Module):
    """embedding (384) -> 128; tabular (tabular_dim) -> 32; concat (160) ->
    64 -> 1 raw logit. No sigmoid: BCEWithLogitsLoss applies it, and
    doing it inside the loss is numerically more stable than a manual
    sigmoid + BCELoss.
    """

    def __init__(
        self,
        tabular_dim: int,
        embedding_dim: int = EMBEDDING_DIM,
        embedding_hidden: int = EMBEDDING_HIDDEN,
        tabular_hidden: int = TABULAR_HIDDEN,
        combined_hidden: int = COMBINED_HIDDEN,
        dropout: float = DROPOUT,
    ) -> None:
        super().__init__()
        self.embedding_branch = nn.Sequential(
            nn.Linear(embedding_dim, embedding_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.tabular_branch = nn.Sequential(
            nn.Linear(tabular_dim, tabular_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        # embedding_hidden + tabular_hidden, e.g. 128 + 32 = 160. If the
        # branch sizes above change, this stays correct automatically.
        combined_dim = embedding_hidden + tabular_hidden
        self.head = nn.Sequential(
            nn.Linear(combined_dim, combined_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(combined_hidden, 1),
        )

    def forward(self, embedding: torch.Tensor, tabular: torch.Tensor) -> torch.Tensor:
        embedded = self.embedding_branch(embedding)
        tab = self.tabular_branch(tabular)
        combined = torch.cat([embedded, tab], dim=1)
        return self.head(combined).squeeze(-1)
