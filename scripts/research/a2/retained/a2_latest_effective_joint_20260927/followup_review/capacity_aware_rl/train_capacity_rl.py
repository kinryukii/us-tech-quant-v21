"""Bounded pre-2026 capacity-aware RL amendment of the joint batch.

The original joint model/ledger files are read-only inputs.  This module only
trains the two original REINFORCE seeds, with actual partial fills in its state
transition and a reward which matures before the next decision.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

import joint_neural as original

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PRICE = original.PRICE
SOURCE = ROOT / "data/pre2026_joint_context.parquet"
FEATURES = original.FEATURES
SEEDS = original.SEEDS
EPOCHS = original.RL_EPOCHS
COST = original.COST
CAPACITY_FRACTION = .01
INITIAL_CASH = 1_000_000.
TOL = 1e-10
EXPECTED_SOURCE_SHA = "5895dbca36064a7ea7a9ab66fbe47c5b1dfc2ab5e6cef61d53cd23e447b09b0e"
EXPECTED_PRICE_SHA = "a8fd449887076633a816fd1ebf4ad17f27dbf5ae0948bb805e9cc6b978cb8cda"
EXPECTED_ORIGINAL_SHA = "8cb41c9adf50c90aea79feca0df0121415508939c6fe9590fcaebae2b9d3beb6"
torch.set_num_threads(2)


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


class CapacityPolicy(nn.Module):
    """Original 32→16→1 topology; one additional contemporaneous cap/NAV input."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(len(FEATURES) + 4, 32), nn.Tanh(),
            nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1),
        )
        nn.init.constant_(self.net[-1].bias, -.7)

    def forward(self, x):
        return self.net(x).flatten()


def capacity_ratio(adv: np.ndarray, nav: float) -> np.ndarray:
    if not np.isfinite(nav) or nav <= 0:
        raise RuntimeError("UNKNOWN_SIGNAL_NAV")
    adv = np.asarray(adv, dtype=np.float64)
    return np.clip(np.where(np.isfinite(adv) & (adv > 0), CAPACITY_FRACTION * adv / nav, 0.), 0., 1.)


class CapacityMarket(original.Market):
    """Reuse original legal dates/features; amend only cap and close-to-close fills."""

    def __init__(self, panel, first, last, mean, scale):
        super().__init__(panel, first, last, mean, scale)
        px = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "close"])
        px["trade_date"] = pd.to_datetime(px.trade_date)
        assert px.trade_date.max() < pd.Timestamp("2026-01-01")
        cal = pd.DatetimeIndex(sorted(px.loc[px.ticker.eq("QQQ"), "trade_date"].unique()))
        # Reward maturity requires a fresh next-session close. A forward-filled
        # mark may be useful for indicative valuation, never for a fit reward.
        raw_close = px.pivot(index="trade_date", columns="ticker", values="close").reindex(
            index=cal, columns=self.tickers)
        next_close = raw_close.shift(-1)
        groups = {pd.Timestamp(d): g for d, g in panel.groupby("signal_date", sort=True)}
        empty = panel.iloc[:0]
        for d in self.days:
            date = pd.Timestamp(d["date"])
            g = groups.get(date, empty)
            x = np.clip((g[FEATURES].to_numpy(float) - mean) / scale, -8, 8)
            g = g.iloc[np.flatnonzero(np.isfinite(x).all(axis=1))]
            ids = np.asarray([self.lookup[t] for t in g.ticker], dtype=int)
            if not np.array_equal(ids, d["ids"].numpy()):
                raise RuntimeError("CAPACITY_FEATURE_KEY_ORDER_MISMATCH")
            adv = pd.to_numeric(g.avg_dollar_volume_20d, errors="coerce").to_numpy(float)
            d["adv"] = adv
            d["ending"] = next_close.loc[date].fillna(0.).to_numpy(float)
            d["execution_date"] = str(cal[cal.get_loc(date) + 1].date())
            if pd.Timestamp(d["execution_date"]) > pd.Timestamp(last):
                raise RuntimeError("REWARD_END_CROSSES_FOLD")

    def episode(self, model, optimizer=None, noise_seed=0, trace=False):
        rng = torch.Generator().manual_seed(noise_seed)
        units = np.zeros(len(self.tickers), dtype=np.float64)
        cash = INITIAL_CASH
        last_known_vol = np.full(len(self.tickers), np.nan, dtype=np.float64)
        rewards, records, log_probs, pg_rewards = [], [], [], []
        updates = 0
        for d in self.days:
            close = d["close"].numpy()
            opening = d["opening"].numpy()
            ending = d["ending"]
            fill = d["fill"].numpy()
            held = units > TOL
            if np.any(held & ((close <= 0) | (opening <= 0))):
                raise RuntimeError("UNKNOWN_HELD_TRAINING_PRICE")
            close_values = units * close
            close_nav = cash + close_values.sum()
            if not np.isfinite(close_nav) or close_nav <= 0:
                raise RuntimeError("INVALID_SIGNAL_NAV")
            current = close_values / close_nav
            day_ids = d["ids"].numpy()
            eligible = d["eligible"].numpy()
            last_known_vol[day_ids] = d["vol"].numpy()
            observable = eligible | (units[day_ids] > TOL)
            ids = day_ids[observable]
            n = len(ids)
            upper = torch.tensor(np.where(eligible[observable], .1, np.minimum(current[ids], .1)), dtype=torch.float32)
            target = np.zeros(len(self.tickers), dtype=np.float64)
            lp = None
            if n:
                # At signal close, this is the actual nominal NAV and same-day ADV.
                cap_state = capacity_ratio(d["adv"][observable], close_nav)
                obs = torch.cat((
                    d["x"][observable],
                    torch.tensor(current[ids, None], dtype=torch.float32),
                    torch.full((n, 1), float(cash / close_nav)),
                    torch.tensor((units[ids, None] > TOL).astype(float), dtype=torch.float32),
                    torch.tensor(cap_state[:, None], dtype=torch.float32),
                ), dim=1)
                logits = model(obs)
                if optimizer is not None:
                    noise = torch.randn(logits.shape, generator=rng) * .35
                    dist = torch.distributions.Normal(logits, .35)
                    raw = logits.detach() + noise
                    lp = dist.log_prob(raw).mean()
                    action = original.project(raw, False, upper)
                else:
                    action = original.project(logits, False, upper)
                # Match engine._validate_targets: float32 0.1 is slightly above
                # decimal 0.1 and is clamped before account execution.
                target[ids] = np.minimum(action.detach().double().numpy(), .1)
                if target.sum() > .95:
                    target *= .95 / target.sum()

            # The following open is only used after the target is fixed.
            pre_values = units * opening
            pre_nav = cash + pre_values.sum()
            if not np.isfinite(pre_nav) or pre_nav <= 0:
                raise RuntimeError("INVALID_EXECUTION_NAV")
            desired = target * pre_nav
            fees = buy_notional = sell_notional = 0.
            cap_limited = 0
            for j in np.flatnonzero(units > TOL):  # self.tickers are sorted
                requested = max(0., pre_values[j] - desired[j])
                if requested <= TOL or not fill[j]:
                    continue
                notional = min(requested, units[j] * opening[j])
                units[j] = max(0., units[j] - notional / opening[j])
                fee = notional * COST
                cash += notional - fee
                fees += fee
                sell_notional += notional
            buy_eligible = np.zeros(len(self.tickers), dtype=bool)
            buy_eligible[day_ids] = eligible
            cap = np.zeros(len(self.tickers), dtype=np.float64)
            cap[day_ids] = np.where(np.isfinite(d["adv"]) & (d["adv"] > 0), d["adv"] * CAPACITY_FRACTION, 0.)
            requests = {}
            reserved = set(np.flatnonzero(units > TOL))
            for j in sorted(np.flatnonzero(target > 0), key=lambda k: (-target[k], self.tickers[k])):
                requested = max(0., desired[j] - units[j] * opening[j])
                if requested <= TOL or not buy_eligible[j] or not fill[j]:
                    continue
                if j not in reserved and len(reserved) >= 20:
                    continue
                allowed = min(requested, cap[j])
                if requested > allowed + TOL:
                    cap_limited += 1
                if allowed > TOL:
                    requests[j] = allowed
                    reserved.add(j)
            total_request = sum(requests.values())
            buy_scale = min(1., max(0., cash) / (total_request * (1 + COST))) if total_request > 0 else 1.
            for j, requested in requests.items():
                notional = requested * buy_scale
                if notional <= TOL:
                    continue
                units[j] += notional / opening[j]
                fee = notional * COST
                cash -= notional + fee
                fees += fee
                buy_notional += notional
            if cash < -1e-6 or len(np.flatnonzero(units > TOL)) > 20:
                raise RuntimeError("TRAIN_SELF_FINANCE_OR_POSITION_LIMIT")
            cash = max(0., cash)
            if np.any((units > TOL) & (ending <= 0)):
                raise RuntimeError("UNKNOWN_END_TRAINING_PRICE")
            end_nav = cash + np.dot(units, ending)
            if not np.isfinite(end_nav) or end_nav <= 0:
                raise RuntimeError("INVALID_END_NAV")
            # This d+1 close reward matures before the next d+1 close decision.
            reward = float(np.log(end_nav / close_nav))
            vol = d["vol"].numpy()[observable]
            target_risk_proxy = float(np.dot(target[ids] ** 2, vol ** 2)) if n else 0.
            posttrade_value = units * opening
            posttrade_nav = cash + posttrade_value.sum()
            if not np.isfinite(posttrade_nav) or posttrade_nav <= 0:
                raise RuntimeError("INVALID_POSTTRADE_NAV")
            if np.any((units > TOL) & ~np.isfinite(last_known_vol)):
                raise RuntimeError("UNKNOWN_HELD_RISK_INPUT")
            actual_weights = posttrade_value / posttrade_nav
            risk = float(np.nansum((actual_weights * last_known_vol) ** 2))
            utility = reward - 5 * risk
            if optimizer is not None and n:
                log_probs.append(lp)
                pg_rewards.append(utility)
                if len(log_probs) >= 32:
                    original.Market._reinforce(log_probs, pg_rewards, optimizer, model)
                    updates += 1
                    log_probs, pg_rewards = [], []
            rewards.append(reward)
            row = dict(
                signal_date=d["date"], execution_date=d["execution_date"],
                signal_close_nav=close_nav, pretrade_nav=pre_nav, end_close_nav=end_nav,
                reward=reward, risk_penalty=5 * risk,
                target_risk_proxy_penalty=5 * target_risk_proxy,
                risk_penalty_basis="actual_posttrade_weights_at_next_open",
                fees=fees, buy_notional=buy_notional, sell_notional=sell_notional,
                cash=cash, cash_weight=cash / end_nav,
                target_exposure=float(target.sum()), target_names=int((target > 0).sum()),
                live_names=int((units > TOL).sum()), capacity_limited=cap_limited,
                buy_cash_scale=buy_scale,
            )
            if trace:
                row["position_units"] = {self.tickers[j]: float(units[j]) for j in np.flatnonzero(units > TOL)}
            records.append(row)
        if optimizer is not None and log_probs:
            original.Market._reinforce(log_probs, pg_rewards, optimizer, model)
            updates += 1
        return dict(log_reward_sum=float(sum(rewards)), reward_nav_proxy=float(np.exp(sum(rewards))),
                    updates=updates, days=len(records), max_reward_signal=records[-1]["signal_date"] if records else None,
                    max_reward_end=records[-1]["execution_date"] if records else None,
                    capacity_limited=sum(r["capacity_limited"] for r in records),
                    fees=sum(r["fees"] for r in records)), records


def _verify_inputs():
    checks = {SOURCE: EXPECTED_SOURCE_SHA, PRICE: EXPECTED_PRICE_SHA,
              ROOT / "joint_neural.py": EXPECTED_ORIGINAL_SHA}
    actual = {str(k): sha(k) for k in checks}
    if any(actual[str(k)] != v for k, v in checks.items()):
        raise RuntimeError("SOURCE_HASH_MISMATCH")
    return actual


def train():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("PRESERVE_EXISTING_CAPACITY_RL_OUTPUT")
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = _verify_inputs()
    panel = pd.read_parquet(SOURCE)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    label_end = pd.to_datetime(panel.label_end_date.dropna())
    if panel.signal_date.max() >= pd.Timestamp("2026-01-01") or label_end.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("PRE2026_BOUNDARY")
    spec = dict(
        batch="a2_latest_effective_joint_20260927", source_sha256=source_hashes,
        seeds=list(SEEDS), rl_epochs=EPOCHS, train_periods={"validation": "2023-01-01..2024-12-31",
            "final": "2023-01-01..2025-12-31"}, validation_period="2025-01-01..2025-12-31",
        architecture=[len(FEATURES) + 4, 32, 16, 1], parameters=sum(p.numel() for p in CapacityPolicy().parameters()),
        capacity_feature="min(1, 0.01*signal_day_raw_dollar_ADV/signal_close_NAV)",
        capacity_fraction=.01, initial_cash=INITIAL_CASH, cost_bps_per_side=10,
        max_positions=20, max_weight=.1, max_exposure=.95, zero_threshold=.02,
        learning_rate=.0005, weight_decay=.001, rl_gamma=.97, rl_block_steps=32,
        reward="log(next_close_NAV/signal_close_NAV)-5*sum(actual_posttrade_weight^2*last_known_signal_vol20^2)",
        choice_rule="fixed two seeds, four epochs; no 2025 metric-driven continuation or seed choice",
        no_2026_input=True,
    )
    (OUT / "PRE_FIT_CONTRACT.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    logs, artifacts = [], []
    for stage, last in (("validation", "2024-12-31"), ("final", "2025-12-31")):
        fitrows = panel[panel.signal_date.le(last)]
        fitrows = fitrows[np.isfinite(fitrows[FEATURES].to_numpy(float)).all(axis=1)]
        x = fitrows[FEATURES].to_numpy(float)
        mean = x.mean(axis=0)
        scale = x.std(axis=0)
        scale[scale < 1e-12] = 1.
        np.savez(OUT / f"{stage}_normalization.npz", mean=mean, scale=scale)
        market = CapacityMarket(panel, "2023-01-01", last, mean, scale)
        validation = CapacityMarket(panel, "2025-01-01", "2025-12-31", mean, scale) if stage == "validation" else None
        for seed in SEEDS:
            torch.manual_seed(seed)
            model = CapacityPolicy()
            initial_path = OUT / f"{stage}_rl_{seed}_zero.pt"
            torch.save(model.state_dict(), initial_path)
            optimizer = torch.optim.Adam(model.parameters(), lr=.0005, weight_decay=.001)
            for epoch in range(EPOCHS):
                start = time.monotonic()
                info, _ = market.episode(model, optimizer, seed + epoch)
                row = dict(stage=stage, method="rl", seed=seed, epoch=epoch + 1,
                           seconds=time.monotonic() - start, **info)
                logs.append(row)
                with (OUT / "training.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)
            model_path = OUT / f"{stage}_rl_{seed}.pt"
            torch.save(model.state_dict(), model_path)
            artifacts.append(dict(stage=stage, seed=seed, path=str(model_path),
                                  sha256=sha(model_path), parameters=spec["parameters"]))
            if validation is not None:
                with torch.no_grad():
                    info, records = validation.episode(model)
                pd.DataFrame(records).to_parquet(OUT / f"validation_rl_{seed}_2025.parquet", index=False)
                logs.append(dict(stage="2025_validation", method="rl", seed=seed, **info))
    receipt = dict(specification=spec, artifacts=artifacts, logs=logs,
                   actual_parameter_updates=sum(v["updates"] for v in logs if v["stage"] != "2025_validation"),
                   fit_2026_rows=0, reward_end_max=max(v["max_reward_end"] for v in logs if v["stage"] != "2025_validation"),
                   status="PRE2026_CAPACITY_AWARE_RL_TRAINED")
    (OUT / "TRAIN_RECEIPT.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


class CapacityRLAdapter:
    """Two-seed target-weight ensemble, with NAV provided by the ledger at signal close."""

    def __init__(self, stage="validation", zero=False):
        stats = np.load(OUT / f"{stage}_normalization.npz")
        self.mean, self.scale = stats["mean"], stats["scale"]
        self.models = []
        for seed in SEEDS:
            model = CapacityPolicy()
            suffix = "_zero" if zero else ""
            model.load_state_dict(torch.load(OUT / f"{stage}_rl_{seed}{suffix}.pt", weights_only=True, map_location="cpu"))
            model.eval()
            self.models.append(model)

    def __call__(self, day: pd.DataFrame, weights: dict[str, float], cash: float):
        if day.empty:
            return {}
        nav = day.attrs.get("signal_close_nav")
        if nav is None or not np.isfinite(float(nav)) or float(nav) <= 0:
            raise RuntimeError("CAPACITY_RL_REQUIRES_SIGNAL_CLOSE_NAV")
        day = day[np.isfinite(day[FEATURES].to_numpy(float)).all(axis=1)]
        if day.empty:
            return {}
        day = day[day.new_buy_eligible.astype(bool) | day.ticker.map(weights).fillna(0).gt(0)]
        if day.empty:
            return {}
        day = day.sort_values("ticker", kind="stable")
        x = np.clip((day[FEATURES].to_numpy(float) - self.mean) / self.scale, -8, 8)
        old = np.asarray([weights.get(t, 0.) for t in day.ticker])
        cap = capacity_ratio(pd.to_numeric(day.avg_dollar_volume_20d, errors="coerce").to_numpy(float), float(nav))
        obs = torch.tensor(np.column_stack((x, old, np.repeat(cash, len(day)), old > 0, cap)), dtype=torch.float32)
        upper = torch.tensor(np.where(day.new_buy_eligible.to_numpy(bool), .1, np.minimum(old, .1)), dtype=torch.float32)
        with torch.no_grad():
            w = torch.stack([original.project(m(obs), upper=upper) for m in self.models]).mean(dim=0).numpy()
        keep = np.argsort(-w, kind="stable")[:20]
        mask = np.zeros(len(w))
        mask[keep] = 1
        w *= mask
        if w.sum() > .95:
            w *= .95 / w.sum()
        return {str(t): float(v) for t, v in zip(day.ticker, w) if v > 1e-8}


if __name__ == "__main__":
    train()
