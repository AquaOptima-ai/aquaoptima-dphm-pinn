"""Per-node GRU temporal encoder.

Consumes a sequence of node features and returns one hidden vector per
node — the GRU's final hidden state. Each node shares the same GRU
weights; we reshape so the batch dimension of :class:`nn.GRU` is the
node axis (or ``batch * node`` axis in the batched case).

Two input layouts are supported:

* ``[T, N, F]`` (unbatched, legacy) → ``[N, hidden]``
* ``[B, T, N, F]`` (batched, Sprint 6) → ``[B, N, hidden]``

The batched path is mathematically equivalent to running ``B``
independent unbatched windows with the same weights — it just folds
the batch into the nn.GRU batch axis so the GRU sees ``B * N``
parallel sequences.
"""

from __future__ import annotations

import torch
from torch import nn


class GRUTemporalEncoder(nn.Module):
    """Per-node GRU encoder that shares weights across all nodes."""

    def __init__(self, input_dim: int, hidden_dim: int, num_layers: int = 1) -> None:
        super().__init__()
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.gru = nn.GRU(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=False,
        )

    def forward(self, x_seq: torch.Tensor) -> torch.Tensor:
        if x_seq.dim() == 3:
            T, N, F = x_seq.shape
            if F != self.input_dim:
                raise ValueError(
                    f"x_seq feature dim {F} != configured input_dim {self.input_dim}"
                )
            _, h_n = self.gru(x_seq)
            return h_n[-1]  # [N, hidden]

        if x_seq.dim() == 4:
            B, T, N, F = x_seq.shape
            if F != self.input_dim:
                raise ValueError(
                    f"x_seq feature dim {F} != configured input_dim {self.input_dim}"
                )
            # nn.GRU expects [T, batch, F]; fold (B, N) -> B*N parallel sequences.
            # Permute to [T, B, N, F] then flatten the batch axis.
            x = x_seq.permute(1, 0, 2, 3).reshape(T, B * N, F)
            _, h_n = self.gru(x)
            return h_n[-1].view(B, N, self.hidden_dim)

        raise ValueError(
            f"x_seq must be [T, N, F] or [B, T, N, F], got shape {tuple(x_seq.shape)}"
        )
