"""Original REINFORCE policy and target mapping, whitelisted source extract."""
from __future__ import annotations
import numpy as np
import pandas as pd
import torch
from torch import nn
FEATURES = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d", "ret_20d",
            "realized_vol_20d", "downside_vol_20d", "max_drawdown_20d",
            "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d"]
MAX_WEIGHT = .10
MAX_EXPOSURE = .95
MAX_NAMES = 30
ZERO_GATE = .30
NOISE_STD = .45
class Policy(nn.Module):
    def __init__(self, inputs: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(inputs, 24), nn.Tanh(), nn.Linear(24, 1))
        nn.init.constant_(self.net[-1].bias, -.7)

    def forward(self, x):
        return self.net(x).flatten()

def build_days(panel: pd.DataFrame, mean: np.ndarray, scale: np.ndarray):
    days = {}
    for date, group in panel.groupby("signal_date", sort=True):
        g = group.sort_values(["raw_rank", "ticker"])
        values = np.nan_to_num((g[FEATURES].to_numpy(float) - mean) / scale,
                               nan=0., posinf=0., neginf=0.).clip(-8, 8)
        days[pd.Timestamp(date)] = (g.ticker.astype(str).tolist(),
                                    g.raw_rank.to_numpy(int), values)
    return days

def policy_target(policy, day, shares, pre_values, nav, training, log_probs=None, records=None):
    names, ranks, features = day
    lookup = {t: i for i, t in enumerate(names)}
    selected = [t for t, r in zip(names, ranks) if r <= 20]
    selected += sorted(set(shares) - set(selected))
    cash_weight = max(0., 1. - sum(pre_values.values()) / nav)
    rows = []
    for ticker in selected:
        i = lookup.get(ticker)
        base = features[i] if i is not None else np.zeros(len(FEATURES))
        old_w = pre_values.get(ticker, 0.) / nav
        rows.append(np.r_[base, old_w, cash_weight, float(ticker in shares), float(i is not None and ranks[i] <= 20)])
    obs = torch.tensor(np.asarray(rows, dtype=np.float32))
    mean_logit = policy(obs)
    if training:
        dist = torch.distributions.Normal(mean_logit, NOISE_STD)
        raw = dist.sample()
        assert log_probs is not None
        log_probs.append(dist.log_prob(raw).sum())
    else:
        raw = mean_logit
    tentative = torch.where(torch.sigmoid(raw) >= ZERO_GATE,
                            MAX_WEIGHT * torch.sigmoid(raw), torch.zeros_like(raw))
    if len(selected) > MAX_NAMES:
        keep = torch.topk(tentative, MAX_NAMES).indices
        mask = torch.zeros_like(tentative)
        mask[keep] = 1.
        tentative = tentative * mask
    gross = float(tentative.detach().sum())
    target = tentative * min(1., MAX_EXPOSURE / gross) if gross > 0 else tentative
    weights = target.detach().numpy()
    answer = {t: float(w) for t, w in zip(selected, weights) if w > 0}
    if records is not None:
        for t, r, w in zip(selected, raw.detach().numpy(), weights):
            records.append({"ticker": t, "raw_action_logit": float(r),
                            "pretrade_weight": float(pre_values.get(t, 0.) / nav),
                            "target_weight": float(w), "eligible_new": t in names[:20],
                            "held_before": t in shares, "cash_weight_before": cash_weight})
    assert sum(answer.values()) <= MAX_EXPOSURE + 1e-6
    assert len(answer) <= MAX_NAMES
    assert all(0 < w <= MAX_WEIGHT + 1e-6 for w in answer.values())
    return answer
