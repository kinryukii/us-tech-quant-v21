"""Fixed-budget neural estimators for the pre-registered A2 PTO batch.

These estimators learn returns, event probabilities, quantiles or a Normal
distribution. They do not reuse the earlier A2 policy-logit MLP weights.
"""
from __future__ import annotations

import numpy as np
import torch
from torch import nn

SEED = 20260928
HIDDEN = 32
EPOCHS = 8
BATCH_SIZE = 1024
torch.set_num_threads(2)


class ResidualBlock(nn.Module):
    def __init__(self, width=HIDDEN):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(width, width), nn.ReLU(),
                                 nn.Linear(width, width))

    def forward(self, value):
        return torch.relu(value + self.net(value))


class NeuralNet(nn.Module):
    def __init__(self, features, kind="mlp", outputs=1):
        super().__init__()
        self.kind = kind
        if kind == "ft_transformer":
            self.token_weight = nn.Parameter(torch.randn(features, HIDDEN) * .02)
            self.token_bias = nn.Parameter(torch.zeros(features, HIDDEN))
            self.cls = nn.Parameter(torch.zeros(1, 1, HIDDEN))
            layer = nn.TransformerEncoderLayer(HIDDEN, nhead=4,
                dim_feedforward=64, dropout=0., activation="gelu", batch_first=True)
            self.body = nn.TransformerEncoder(layer, num_layers=2,
                                              enable_nested_tensor=False)
            self.head = nn.Linear(HIDDEN, outputs)
        elif kind == "resnet":
            self.body = nn.Sequential(nn.Linear(features, HIDDEN), nn.ReLU(),
                                     ResidualBlock(), ResidualBlock())
            self.head = nn.Linear(HIDDEN, outputs)
        elif kind == "linear":
            self.body = nn.Identity()
            self.head = nn.Linear(features, outputs)
        elif kind == "mlp":
            self.body = nn.Sequential(nn.Linear(features, HIDDEN), nn.ReLU(),
                                     nn.Linear(HIDDEN, HIDDEN), nn.ReLU())
            self.head = nn.Linear(HIDDEN, outputs)
        else:
            raise ValueError(f"UNKNOWN_NETWORK:{kind}")

    def forward(self, value):
        if self.kind == "ft_transformer":
            tokens = value[:, :, None] * self.token_weight[None, :, :] + self.token_bias
            tokens = torch.cat([self.cls.expand(len(value), -1, -1), tokens], dim=1)
            hidden = self.body(tokens)[:, 0, :]
        else:
            hidden = self.body(value)
        return self.head(hidden)


class TorchEstimator:
    """Pickle-safe estimator with its own training-only normalization state."""
    def __init__(self, kind="mlp", task="regression", quantile=.5, seed=SEED,
                 epochs=EPOCHS, batch_size=BATCH_SIZE):
        self.kind, self.task, self.quantile = kind, task, float(quantile)
        self.seed, self.epochs, self.batch_size = int(seed), int(epochs), int(batch_size)

    def fit(self, x, y):
        x = np.asarray(x, np.float64)
        y = np.asarray(y, np.float32).reshape(-1)
        if x.ndim != 2 or len(x) != len(y) or not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("INVALID_NEURAL_TRAINING_INPUT")
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        self.mean_ = x.mean(axis=0)
        self.scale_ = x.std(axis=0)
        self.scale_[self.scale_ < 1e-12] = 1.
        tx = torch.tensor(np.clip((x-self.mean_)/self.scale_, -8., 8.), dtype=torch.float32)
        ty = torch.tensor(y)
        outputs = 2 if self.task == "normal" else 1
        model = NeuralNet(x.shape[1], self.kind, outputs)
        # Return targets have small financial units. A small initial output
        # prevents irrelevant large initial predictions from dominating 8 epochs.
        nn.init.normal_(model.head.weight, std=.005)
        nn.init.zeros_(model.head.bias)
        if self.task == "normal":
            with torch.no_grad():
                model.head.bias[1] = float(np.log(max(.005, float(np.std(y)))))
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        generator = torch.Generator().manual_seed(self.seed)
        self.loss_history_, self.optimizer_steps_ = [], 0
        model.train()
        for _ in range(self.epochs):
            permutation = torch.randperm(len(tx), generator=generator)
            total = 0.
            for begin in range(0, len(tx), self.batch_size):
                ids = permutation[begin:begin+self.batch_size]
                prediction = model(tx[ids])
                target = ty[ids]
                if self.task == "regression":
                    loss = torch.mean((prediction[:, 0]-target)**2)
                elif self.task == "classification":
                    loss = nn.functional.binary_cross_entropy_with_logits(prediction[:, 0], target)
                elif self.task == "quantile":
                    error = target-prediction[:, 0]
                    loss = torch.maximum(self.quantile*error, (self.quantile-1.)*error).mean()
                elif self.task == "normal":
                    log_scale = prediction[:, 1].clamp(-7., 0.)
                    loss = (log_scale + .5*((target-prediction[:, 0])*torch.exp(-log_scale))**2).mean()
                else:
                    raise ValueError(f"UNKNOWN_NEURAL_TASK:{self.task}")
                if not torch.isfinite(loss):
                    raise RuntimeError("NONFINITE_NEURAL_LOSS")
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 5.)
                optimizer.step()
                self.optimizer_steps_ += 1
                total += float(loss.detach())*len(ids)
            self.loss_history_.append(total/len(tx))
        model.eval()
        self.state_ = {name:value.detach().cpu().clone() for name,value in model.state_dict().items()}
        self.n_features_in_, self.outputs_ = x.shape[1], outputs
        return self

    def raw_predict(self, x):
        x = np.asarray(x, np.float64)
        if x.ndim != 2 or x.shape[1] != self.n_features_in_ or not np.isfinite(x).all():
            raise ValueError("INVALID_NEURAL_INFERENCE_INPUT")
        model = NeuralNet(self.n_features_in_, self.kind, self.outputs_)
        model.load_state_dict(self.state_)
        model.eval()
        values = torch.tensor(np.clip((x-self.mean_)/self.scale_, -8., 8.), dtype=torch.float32)
        parts = []
        with torch.no_grad():
            for begin in range(0, len(values), self.batch_size):
                parts.append(model(values[begin:begin+self.batch_size]).cpu().numpy())
        result = np.concatenate(parts) if parts else np.empty((0, self.outputs_))
        if not np.isfinite(result).all():
            raise RuntimeError("NONFINITE_NEURAL_INFERENCE")
        return result.astype(np.float64)

    def predict(self, x):
        result = self.raw_predict(x)
        if self.task == "classification":
            return 1./(1.+np.exp(-np.clip(result[:, 0], -40., 40.)))
        return result[:, 0]

    def predict_proba(self, x):
        p = self.predict(x)
        return np.column_stack([1.-p, p])

    def predict_normal(self, x):
        result = self.raw_predict(x)
        return result[:, 0], np.exp(np.clip(result[:, 1], -7., 0.))
