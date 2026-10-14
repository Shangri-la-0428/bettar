"""Pinned BetaZero inference architecture (MIT, Evan McCormick 2026).

Adapted from commit 6f0acb414a5f1ab070aa62d02ac98f2602011821:
climb-backend/app/services/utils/ddpm_model.py.
Only the inference architecture/schedules are retained; CPU is explicit and
weight loading is handled with weights_only=True by learned_generator.
See assets/learned/BETAZERO-LICENSE.txt for the upstream license.
"""
import math
from pathlib import Path
import torch
from torch import Tensor, nn

class SinusoidalPositionEmbeddings(nn.Module):
    def __init__(self, dim: int = 128):
        super().__init__()
        self.dim = dim

    def forward(self, time):
        device = time.device
        half_dim = self.dim // 2
        embeddings = math.log(10000) / (half_dim - 1)
        embeddings = torch.exp(torch.arange(half_dim, device=device) * -embeddings)
        embeddings = time[:, 0].unsqueeze(1) * embeddings.unsqueeze(0)
        return torch.cat((embeddings.sin(), embeddings.cos()), dim=-1)


class ResidualBlock1D(nn.Module):
    def __init__(self, in_channels, out_channels, cond_dim, padding=1):
        super().__init__()
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size=3, padding=padding)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size=3, padding=padding)
        self.norm1 = nn.GroupNorm(8, out_channels)
        self.norm2 = nn.GroupNorm(8, out_channels)
        self.act = nn.SiLU()
        self.cond_proj = nn.Linear(cond_dim, out_channels * 2)
        self.shortcut = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else nn.Identity()

    def forward(self, x, cond):
        h = self.conv1(x)
        h = self.norm1(h)
        gamma, beta = self.cond_proj(cond).unsqueeze(-1).chunk(2, dim=1)
        h = h * (1 + gamma) + beta
        h = self.act(h)
        h = self.conv2(h)
        h = self.norm2(h)
        h = self.act(h)
        return h + self.shortcut(x)


class Noiser(nn.Module):
    """U-Net denoiser with learnable null embeddings and zero-COM input projection."""
    def __init__(self, hidden_dim=256, layers=3, in_feature_dim=12, out_feature_dim=12, cond_dim=4, sinusoidal=True):
        super().__init__()
        self.device = torch.device("cpu")

        self.time_mlp = nn.Sequential(
            (SinusoidalPositionEmbeddings(hidden_dim) if sinusoidal else nn.Linear(1, hidden_dim)),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.cond_mlp = nn.Sequential(
            nn.Linear(cond_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.null_cond_emb = nn.Parameter(torch.randn(1, hidden_dim, device=self.device))
        self.combine_t_mlp = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.init_conv = ResidualBlock1D(in_feature_dim, hidden_dim, hidden_dim)
        self.down_blocks = nn.ModuleList(
            [ResidualBlock1D(hidden_dim * (i + 1), hidden_dim * (i + 2), hidden_dim) for i in range(layers)]
        )
        self.up_blocks = nn.ModuleList(
            [ResidualBlock1D(hidden_dim * (i + 1), hidden_dim * i, hidden_dim) for i in range(layers, 0, -1)]
        )
        self.head = nn.Conv1d(hidden_dim, out_feature_dim, 1)

    def forward(self, climbs: Tensor, cond: Tensor | None, t: Tensor) -> Tensor:
        (B, S, H) = climbs.shape
        emb_t = self.time_mlp(t)
        emb_c = self.cond_mlp(cond) if cond is not None else self.null_cond_emb.repeat(B, 1)
        emb_c = self.combine_t_mlp(torch.cat([emb_t, emb_c], dim=1))
        emb_h = self.init_conv(climbs.transpose(1, 2), emb_c)

        skip_conns = []
        for layer in self.down_blocks:
            skip_conns.append(emb_h)
            emb_h = layer(emb_h, emb_c)
        for layer in self.up_blocks:
            emb_h = skip_conns.pop() + layer(emb_h, emb_c)

        return self.head(emb_h).transpose(1, 2)


# ---------------------------------------------------------------------------
# DDPM wrapper
# ---------------------------------------------------------------------------

class ClimbDDPM(nn.Module):
    def __init__(self, model: nn.Module, weights_path: Path | str | None = None):
        super().__init__()
        self.device = torch.device("cpu")
        self.model = model
        if weights_path:
            raise ValueError("Load verified weights through learned_generator only")

    def _cos_alpha_bar(self, t: Tensor) -> Tensor:
        t = t.view(-1, 1, 1)
        epsilon = 0.0004
        return torch.cos((t + epsilon) / (1 + 2 * epsilon) * torch.pi / 2) ** 2

    def _composite_alpha_bar(self, t: Tensor, n_features: int) -> Tensor:
        """Composite schedule that preserves the is_null flag until t=0.8."""
        a_features = self._cos_alpha_bar(t)
        a_null = self._cos_alpha_bar(torch.clamp((t - 0.8) / 0.2, 0.0, 1.0))
        a_full = a_features.expand(-1, -1, n_features - 1)
        return torch.cat([a_full, a_null], dim=2)

    def predict_clean(self, noisy, cond, t, epsilon=0.0004):
        (B, S, H) = noisy.shape
        a = self._composite_alpha_bar(t, H)
        prediction = self.model(noisy, cond, t)
        return (noisy - torch.sqrt(1 - a) * prediction) / (torch.sqrt(a) + epsilon)

    def predict_cfg(self, noisy, cond, t, guidance_value=1.0, epsilon=0.0004):
        (B, S, H) = noisy.shape
        a = self._composite_alpha_bar(t, H)
        cf_pred = self.model(noisy, None, t)
        pred = self.model(noisy, cond, t)
        cfg = cf_pred + (pred - cf_pred) * guidance_value
        return (noisy - torch.sqrt(1 - a) * cfg) / (torch.sqrt(a) + epsilon)

    def forward_diffusion(self, clean: Tensor, t: Tensor, noise: Tensor) -> Tensor:
        (B, S, H) = clean.shape
        a = self._composite_alpha_bar(t, H)
        return torch.sqrt(a) * clean + torch.sqrt(1 - a) * noise

    def forward(self, noisy, cond, t):
        return self.predict_clean(noisy, cond, t)
