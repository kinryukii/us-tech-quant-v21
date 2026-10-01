"""Independent REINFORCE/PPO controls with the common actual cash/unit ledger.

These decision learners are outside the PTO forecast/risk/optimizer grid.
Retrospective training rewards use only mature pre-cutoff open-to-open labels;
the actor observes its own actual, capacity-limited holdings and cash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.distributions import Normal

from common import ROOT, read, write, sha
from data_contract import FEATURES, INPUT, STAGE_CUTOFFS, stage_frame, maturity_mask, load_pre2026_prices
from engine_v2 import HoldingAwareDecision, run_replay

ARTIFACTS = ROOT / "rl_artifacts"
METHODS = ("reinforce", "ppo")
STAGES = ("validation", "final")
STD = .15
MAX_TRAIN_SECONDS = 40 * 60


class PolicyNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(34, 32), nn.Tanh(), nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1))

    def forward(self, inputs):
        return self.layers(inputs).squeeze(-1)


def state_digest(model):
    digest = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        digest.update(key.encode())
        digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def project_logits(logits, upper, *, slots, budget):
    logits, upper = np.asarray(logits, float), np.asarray(upper, float)
    if logits.shape != upper.shape or not np.isfinite(logits).all() or not np.isfinite(upper).all():
        raise ValueError("invalid projection arrays")
    weights = upper / (1.0 + np.exp(-np.clip(logits, -40., 40.)))
    order = np.argsort(-weights, kind="stable")
    weights[order[max(0, int(slots)):]] = 0.
    if weights.sum() > max(0., float(budget)):
        weights *= max(0., float(budget)) / weights.sum()
    return weights


def observations(day, context, mean, scale):
    names = day.ticker.astype(str).tolist()
    x = np.clip((day[list(FEATURES)].to_numpy(float) - mean) / scale, -8., 8.)
    own = np.array([context.current_weights.get(t, 0.) for t in names], dtype=float)
    cash = float(context.cash_weight)
    if not np.isfinite(x).all() or not np.isfinite(own).all() or not np.isfinite(cash):
        raise ValueError("non-finite actual account observation")
    eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(context.buy_restricted_tickers).to_numpy()
    upper = np.where(eligible, context.max_weight, np.minimum(np.maximum(own, 0.), context.max_weight))
    return torch.tensor(np.column_stack([x, own, np.full(len(day), cash)]), dtype=torch.float32), upper


def actor_decision(day, context, logits, upper):
    weights = project_logits(logits, upper, slots=context.available_slots, budget=context.available_weight)
    # All candidates were scored. Sparse explicit zeros are needed for owned names.
    decisions = {str(t): float(w) for t, w in zip(day.ticker, weights)
                 if w > 1e-12 or context.current_units.get(str(t), 0.) > 0}
    return HoldingAwareDecision(model_decisions=decisions,
        raw_model_outputs={str(t): {"logit": float(l), "projected_weight": float(w)}
                           for t, l, w in zip(day.ticker, logits, weights)})


class FrozenRL:
    def __init__(self, stage, method, zero=False):
        method = str(method).lower()
        if stage not in STAGES or method not in METHODS:
            raise ValueError("unknown frozen RL stage/method")
        suffix = "zero" if zero else "learned"
        directory = ARTIFACTS / f"{stage}_{method}"
        receipt = read(directory / "TRAIN_RECEIPT.json")
        if receipt["status"] != "COMPLETE_FIXED_BUDGET":
            raise ValueError("RL training is not complete")
        path = directory / f"{suffix}.pt"
        if sha(path) != receipt[f"{suffix}_artifact_sha256"]:
            raise ValueError("frozen RL artifact hash changed")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if tuple(payload["features"]) != FEATURES or payload["cutoff_exclusive"] != STAGE_CUTOFFS[stage]:
            raise ValueError("frozen RL input contract differs")
        self.model = PolicyNetwork()
        self.model.load_state_dict(payload["state"])
        self.model.eval()
        self.mean = np.asarray(payload["mean"], float)
        self.scale = np.asarray(payload["scale"], float)
        self.stage, self.method, self.zero = stage, method, bool(zero)

    def __call__(self, day, context):
        if day.empty or not np.isfinite(context.nav) or not np.isfinite(context.cash_weight):
            return HoldingAwareDecision(raw_model_outputs={"status": "NO_FINITE_ACCOUNT_OBSERVATION"})
        day = day.sort_values("ticker", kind="stable").reset_index(drop=True)
        obs, upper = observations(day, context, self.mean, self.scale)
        with torch.no_grad():
            logits = self.model(obs).numpy()
        return actor_decision(day, context, logits, upper)


def weighted_normalization(stage):
    sample = stage_frame(stage)
    values = sample[list(FEATURES)].to_numpy(float)
    weights = sample.sample_weight.to_numpy(float)
    mean = np.average(values, axis=0, weights=weights)
    scale = np.sqrt(np.average((values - mean) ** 2, axis=0, weights=weights))
    return mean, np.maximum(scale, 1e-8)


def filled_step_reward(record, actual_units, actual_cash, execution_date, price_map, next_date, cutoff, cost_bps):
    """Score actual post-fill units, including prior reserved holdings, and true fees."""
    execution_date = pd.Timestamp(execution_date)
    endpoint = next_date.get(execution_date)
    if execution_date != next_date.get(record["signal_date"]) or endpoint is None or endpoint >= pd.Timestamp(cutoff):
        return dict(valid=False, reason="IMMATURE_OR_NONADJACENT_REWARD_CLOCK")
    before, cash_before = record["before_units"], float(record["before_cash"])
    union = set(before) | set(actual_units)
    opens = {t: price_map.get((t, execution_date), np.nan) for t in union}
    ends = {t: price_map.get((t, endpoint), np.nan) for t in actual_units}
    if any(not np.isfinite(v) or v <= 0 for v in [*opens.values(), *ends.values()]):
        return dict(valid=False, reason="MISSING_HELD_MATURE_OPEN_LABEL")
    pre_nav = cash_before + sum(before[t] * opens[t] for t in before)
    if not np.isfinite(pre_nav) or pre_nav <= 0:
        return dict(valid=False, reason="INVALID_ACTUAL_PRETRADE_NAV")
    buys = sum(max(0., actual_units.get(t, 0.) - before.get(t, 0.)) * opens[t] for t in union)
    sells = sum(max(0., before.get(t, 0.) - actual_units.get(t, 0.)) * opens[t] for t in union)
    fees = (buys + sells) * cost_bps / 10000.
    cash_error = float(actual_cash) - (cash_before + sells - buys - fees)
    if abs(cash_error) > max(1e-6, pre_nav * 1e-10):
        raise AssertionError(f"training actual cash identity differs from common ledger: {cash_error}")
    asset_return = sum(actual_units[t] * opens[t] / pre_nav * np.clip(ends[t] / opens[t] - 1., -.20, .20)
                       for t in actual_units)
    return dict(valid=True, signal_date=record["signal_date"], execution_date=execution_date,
                label_end_date=endpoint, reward=float(asset_return - fees / pre_nav),
                gross_clipped_open_reward=float(asset_return), transaction_cost=fees,
                actual_cash_before=cash_before, actual_cash_after=float(actual_cash),
                actual_pretrade_nav=pre_nav, actual_name_count=len(actual_units),
                cash_identity_error=cash_error, reason="ACTUAL_FILLED_UNITS_CLIPPED_MATURE_OPEN_LABEL_MINUS_ACTUAL_FEES")


class TrainingActor:
    def __init__(self, model, mean, scale, method, optimizer, price_map, next_date, cutoff, config):
        self.model, self.mean, self.scale = model, mean, scale
        self.method, self.optimizer = method, optimizer
        self.price_map, self.next_date, self.cutoff = price_map, next_date, cutoff
        self.config = config
        self.pending = None
        self.records, self.reward_rows, self.update_rows = [], [], []
        self.reward_sum = 0.
        self.reward_count = 0

    def finish_pending(self, units, cash, date):
        if self.pending is None:
            return
        record = self.pending
        reward = filled_step_reward(record, units, cash, date, self.price_map, self.next_date,
                                    self.cutoff, self.config["cost_bps"])
        reward.setdefault("signal_date", record["signal_date"])
        self.reward_rows.append(reward)
        record["reward"] = reward
        if reward["valid"] and self.method == "reinforce":
            baseline = self.reward_sum / self.reward_count if self.reward_count else 0.
            advantage = 100. * (reward["reward"] - baseline)
            loss = -record["log_prob"] * advantage
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            grad = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0))
            if not np.isfinite(grad) or not torch.isfinite(loss):
                raise ValueError("non-finite REINFORCE update")
            self.optimizer.step()
            self.update_rows.append(dict(signal_date=record["signal_date"], loss=float(loss.detach()),
                reward=reward["reward"], advantage=advantage, gradient_norm_before_clip=grad,
                update_rule="on-policy score-function after actual capacity-limited fill; retrospective mature label"))
            self.reward_sum += reward["reward"]
            self.reward_count += 1
        record.pop("log_prob", None)
        self.pending = None

    def __call__(self, day, context):
        self.finish_pending(context.current_units, context.cash, context.signal_date)
        if day.empty or not np.isfinite(context.nav) or not np.isfinite(context.cash_weight):
            return HoldingAwareDecision(raw_model_outputs={"status": "NO_FINITE_ACCOUNT_OBSERVATION"})
        day = day.sort_values("ticker", kind="stable").reset_index(drop=True)
        obs, upper = observations(day, context, self.mean, self.scale)
        logits = self.model(obs)
        distribution = Normal(logits, STD)
        actions = distribution.sample().detach()
        log_prob = distribution.log_prob(actions).sum()
        record = dict(signal_date=context.signal_date, before_units=dict(context.current_units),
                      before_cash=float(context.cash), obs=obs.detach(), actions=actions,
                      old_log_prob=float(log_prob.detach()), log_prob=log_prob)
        self.records.append(record)
        self.pending = record
        return actor_decision(day, context, actions.numpy(), upper)

    def flush(self, result):
        if self.pending is not None:
            execution = self.next_date[self.pending["signal_date"]]
            units = result.positions.loc[result.positions.date.eq(execution)].set_index("ticker").index_units.to_dict()
            cash = result.daily.set_index("date").loc[execution, "cash"]
            self.finish_pending(units, cash, execution)
        if self.method == "ppo":
            valid = [r for r in self.records if r["reward"]["valid"]]
            baseline = np.mean([r["reward"]["reward"] for r in valid]) if valid else 0.
            for record in valid:
                advantage = 100. * (record["reward"]["reward"] - baseline)
                new_log_prob = Normal(self.model(record["obs"]), STD).log_prob(record["actions"]).sum()
                log_ratio = torch.clamp(new_log_prob - record["old_log_prob"], -20., 20.)
                ratio = torch.exp(log_ratio)
                clipped = ratio.clamp(1.-self.config["ppo_clip"], 1.+self.config["ppo_clip"])
                loss = -torch.minimum(ratio * advantage, clipped * advantage)
                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                grad = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0))
                if not np.isfinite(grad) or not torch.isfinite(loss):
                    raise ValueError("non-finite PPO update")
                self.optimizer.step()
                self.update_rows.append(dict(signal_date=record["signal_date"], loss=float(loss.detach()),
                    reward=record["reward"]["reward"], advantage=float(advantage),
                    likelihood_ratio=float(ratio.detach()), gradient_norm_before_clip=grad,
                    update_rule="old rollout joint Normal probability; clipped PPO surrogate, one update per signal"))


def training_episode(stage):
    cutoff = STAGE_CUTOFFS[stage]
    full = pd.read_parquet(INPUT / "pre2026.parquet")
    panel = full.loc[maturity_mask(full, cutoff), ["signal_date", "ticker", "new_buy_eligible", *FEATURES]].copy()
    # Labels are never actor observation columns. The account determines actual positions.
    prices = load_pre2026_prices()
    prices = prices.loc[prices.trade_date.lt(cutoff)].copy()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.ge(panel.signal_date.min()), "trade_date"].unique()))
    price_map = prices.set_index(["ticker", "trade_date"]).open.to_dict()
    next_date = dict(zip(calendar[:-1], calendar[1:]))
    return panel, prices, calendar, price_map, next_date


def artifact_payload(model, mean, scale, stage, method, initial_digest):
    return dict(state={k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                features=list(FEATURES), mean=mean.tolist(), scale=scale.tolist(),
                stage=stage, method=method, cutoff_exclusive=STAGE_CUTOFFS[stage],
                initial_state_sha256=initial_digest, input_dimension=34)


def train(stage, method, *, resume=False, seconds_remaining=MAX_TRAIN_SECONDS):
    if stage not in STAGES or method not in METHODS:
        raise ValueError("invalid RL fixed candidate")
    directory = ARTIFACTS / f"{stage}_{method}"
    receipt_path = directory / "TRAIN_RECEIPT.json"
    if receipt_path.exists():
        receipt = read(receipt_path)
        if not resume or receipt["status"] != "COMPLETE_FIXED_BUDGET":
            raise RuntimeError("existing RL result cannot be silently overwritten")
        for kind in ["learned", "zero"]:
            if sha(directory / f"{kind}.pt") != receipt[f"{kind}_artifact_sha256"]:
                raise ValueError("completed RL artifact changed")
        return receipt
    if directory.exists():
        raise RuntimeError("partial RL directory requires explicit audit; no automatic extra epochs")
    if (ROOT / "GLOBAL_FREEZE.json").exists():
        raise RuntimeError("fit prohibited after global freeze")
    contract = read(ROOT / "contract.json")
    config = dict(contract["rl"], cost_bps=contract["account"]["cost_bps"])
    if config["seed"] != 20260928 or config["epochs"] != 4 or config["updates_per_day"] != 1:
        raise ValueError("RL fixed budget differs")
    torch.set_num_threads(1)
    torch.manual_seed(config["seed"])
    mean, scale = weighted_normalization(stage)
    model = PolicyNetwork()
    initial_digest = state_digest(model)
    directory.mkdir(parents=True)
    torch.save(artifact_payload(model, mean, scale, stage, method, initial_digest), directory / "zero.pt")
    zero_hash = sha(directory / "zero.pt")
    source_hashes = {str(p): sha(p) for p in [ROOT / "contract.json", ROOT / "DESIGN_LOCK.json",
        ROOT / "engine_v2.py", ROOT / "data_contract.py", Path(__file__),
        INPUT / "pre2026.parquet", INPUT / "pre2026_prices.parquet", INPUT / f"stage_{stage}_keys.parquet"]}
    write(directory / "PRE_FIT.json", dict(stage=stage, method=method, config=config, source_sha256=source_hashes,
        initial_state_sha256=initial_digest, zero_artifact_sha256=zero_hash, fit_2026_rows=0,
        normalization_keys=30000, observation="32 features + own predecision actual weight + own cash",
        fixed_mechanism=dict(action_distribution="independent Normal logits", action_std=STD,
            projection="sigmoid * per-name legal upper; top20/reserved slots; scale to available 95% budget",
            gradient_clip=1., reward_scale=100., ppo_log_ratio_numerical_bounds=[-20., 20.],
            reward="actual post-fill units weighted clipped mature open-to-open returns minus real fees",
            REINFORCE="one update after realized fill, using retrospective mature historical endpoint; running past reward mean baseline",
            PPO="one actual-carry rollout per epoch; old joint log probabilities and clipped surrogate, one update per valid signal"),
        episode_pool="entire mature pre-cutoff available candidate panel; not only standardization sampling keys",
        max_total_rl_training_seconds=MAX_TRAIN_SECONDS, created_utc=datetime.now(timezone.utc).isoformat()))
    panel, prices, calendar, price_map, next_date = training_episode(stage)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
    start = time.monotonic()
    epoch_receipts = []
    try:
        for epoch in range(config["epochs"]):
            if time.monotonic() - start > seconds_remaining:
                raise TimeoutError("fixed total RL wall budget exhausted; no extra epochs permitted")
            actor = TrainingActor(model, mean, scale, method, optimizer, price_map, next_date, STAGE_CUTOFFS[stage], config)
            result = run_replay(prices, calendar, panel, actor, candidate=f"train_{stage}_{method}_{epoch+1}",
                initial_cash=contract["account"]["initial_cash"], cost_bps=config["cost_bps"],
                max_positions=20, max_weight=.10, max_invested=.95, capacity_fraction=.01,
                capacity_on_sells=False, signal_start=panel.signal_date.min(), signal_end=panel.signal_date.max())
            actor.flush(result)
            updates = pd.DataFrame(actor.update_rows)
            rewards = pd.DataFrame(actor.reward_rows)
            if updates.empty or updates.signal_date.duplicated().any():
                raise ValueError("RL did not perform legal unique per-day updates")
            epoch_dir = directory / f"epoch_{epoch+1}"
            epoch_dir.mkdir()
            updates.to_parquet(epoch_dir / "updates.parquet", index=False)
            rewards.to_parquet(epoch_dir / "mature_actual_rewards.parquet", index=False)
            for name in ["daily", "trades", "positions", "target_decisions", "execution_results"]:
                getattr(result, name).to_parquet(epoch_dir / f"{name}.parquet", index=False)
            if sha(directory / "zero.pt") != zero_hash:
                raise AssertionError("matched initial-state zero artifact was modified")
            row = dict(epoch=epoch+1, signal_steps=len(actor.records), parameter_update_steps=len(updates),
                valid_reward_steps=int(rewards.valid.sum()), invalid_reward_steps=int((~rewards.valid).sum()),
                max_label_end=str(rewards.loc[rewards.valid, "label_end_date"].max()),
                max_actual_names=int(result.daily.actual_name_count.max()),
                max_cash_identity_error=float(result.daily.cash_flow_identity_error.abs().max()),
                capacity_constrained_orders=int(result.execution_results.reason.astype(str).str.contains("CAPACITY").sum()),
                state_sha256=state_digest(model), zero_unchanged=True,
                elapsed_seconds=time.monotonic()-start)
            epoch_receipts.append(row)
            write(directory / "PROGRESS.json", dict(stage=stage, method=method, epochs=epoch_receipts,
                fixed_epochs=config["epochs"], source_sha256=source_hashes, fit_2026_rows=0))
            print(f"RL {stage} {method} epoch {epoch+1}/4 updates {len(updates)} elapsed {row['elapsed_seconds']:.1f}s", flush=True)
            del actor, result
        if state_digest(model) == initial_digest:
            raise ValueError("RL learned parameters equal the matched zero control")
        torch.save(artifact_payload(model, mean, scale, stage, method, initial_digest), directory / "learned.pt")
        receipt = dict(status="COMPLETE_FIXED_BUDGET", stage=stage, method=method, seed=config["seed"],
            epochs_completed=4, epoch_receipts=epoch_receipts,
            parameter_update_steps=sum(r["parameter_update_steps"] for r in epoch_receipts),
            initial_state_sha256=initial_digest, learned_state_sha256=state_digest(model),
            learned_artifact_sha256=sha(directory / "learned.pt"), zero_artifact_sha256=zero_hash,
            zero_parameter_updates=0, matched_initial_state_immutable=True, fit_2026_rows=0,
            source_sha256=source_hashes, elapsed_seconds=time.monotonic()-start,
            created_utc=datetime.now(timezone.utc).isoformat())
        write(receipt_path, receipt)
        return receipt
    except Exception as exc:
        write(directory / "FAILURE.json", dict(status="FAILED_WITH_RETAINED_FIXED_BUDGET_TRACE",
            stage=stage, method=method, error_type=type(exc).__name__, reason=str(exc),
            completed_epochs=epoch_receipts, elapsed_seconds=time.monotonic()-start,
            zero_artifact_sha256=zero_hash, fit_2026_rows=0))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    args = parser.parse_args()
    if not args.train:
        raise SystemExit("use --train only after fixed implementation tests")
    prior = sum(read(p)["elapsed_seconds"] for p in ARTIFACTS.glob("*/TRAIN_RECEIPT.json"))
    started = time.monotonic()
    receipts = []
    for stage in args.stages:
        for method in args.methods:
            remaining = MAX_TRAIN_SECONDS - prior - (time.monotonic() - started)
            receipts.append(train(stage, method, resume=args.resume, seconds_remaining=remaining))
    write(ARTIFACTS / "TRAINING_COMPLETE.json", dict(status="COMPLETE_FIXED_RL_CONTROLS",
        roster=[dict(stage=r["stage"], method=r["method"], receipt_sha256=sha(ARTIFACTS/f"{r['stage']}_{r['method']}"/"TRAIN_RECEIPT.json")) for r in receipts],
        controls=["REINFORCE", "REINFORCE_zero", "PPO", "PPO_zero"],
        cash_control="provided by shared batch replay", fit_2026_rows=0,
        parameter_update_steps=sum(r["parameter_update_steps"] for r in receipts)))


if __name__ == "__main__":
    main()
