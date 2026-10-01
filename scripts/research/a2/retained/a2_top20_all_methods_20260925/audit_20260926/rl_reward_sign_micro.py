"""Isolated PyTorch score-function sign check; no market data or training."""
import json
from pathlib import Path

import torch


def derivative(reward):
    mean = torch.nn.Parameter(torch.tensor(0.0))
    raw_action = torch.tensor(1.0)
    dist = torch.distributions.Normal(mean, 0.45)
    loss = -dist.log_prob(raw_action) * reward
    loss.backward()
    return float(mean.grad), float(mean - 0.001 * mean.grad)


positive = derivative(+1.0)
negative = derivative(-1.0)
assert positive[0] < 0 < negative[0]
assert positive[1] > 0 > negative[1]
result = {"positive_reward_gradient": positive[0], "negative_reward_gradient": negative[0],
          "positive_reward_next_mean": positive[1], "negative_reward_next_mean": negative[1],
          "scope": "isolated score-function algebra only; not evidence of historical alpha"}
(Path(__file__).parent / "rl_reward_sign_micro.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
