"""Read-only paired HGB/RL evaluation through the holding-aware frozen engine.

Only outputs below this experiment directory are written. Model and input sources
are hashed and verified before and after each evaluation year. No fitting occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
CURRENT = WS / "a2_qualification_holdings_v1_20260927"
OLD = WS / "a2_latest_effective_joint_20260927"
STRICT = WS / "a2_strict_method_retrain_20260926"
COVERAGE = OLD / "joint_linear_tree_coverage_v2" / "out"
HGB_NEW = ROOT / "hgb_capacity_artifacts"
RL_NEW = ROOT / "rl_capacity_artifacts"
RL_OLD = CURRENT / "neural_artifacts"
OUT = ROOT / "paired_evaluation"
SEEDS = (20260927, 20260928)
EXPECTED_ENGINE_SHA = "848754cdc305a7d2398e86be6151da84ea07dc8c35ddfcf5713a53c7450654ff"
EXPECTED_ADAPTER_SHA = "eb0c92ee4c3a04bd77e84fd94b0297467d1a2df71bf10e0c24499bf9e9c16251"
LEDGERS = ("daily", "trades", "positions", "target_decisions", "diagnostics",
           "valuation_intervals", "raw_model_outputs", "signal_contexts",
           "operational_actions", "execution_results")

sys.path.insert(0, str(CURRENT))
import run_v2 as v2  # noqa: E402
from adapters_v2 import PolicyV2  # noqa: E402
from engine_v2 import run_replay  # noqa: E402
from joint_neural_v2 import JointPolicy, FEATURES  # noqa: E402
import joint_linear_tree as values  # noqa: E402
from models.predict import registry, load_model  # noqa: E402
from run_suite import forbid_fitting  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    return value


def write_json(path: Path, value):
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def receipt_artifact(receipt: dict, stage: str, name: str, seed: int | None = None) -> dict:
    entries = receipt.get("fits", receipt.get("artifacts", []))
    matches = [x for x in entries if x.get("stage") == stage and x.get("name", x.get("method")) == name
               and (seed is None or x.get("seed") == seed)]
    if len(matches) != 1:
        raise RuntimeError(f"receipt artifact not unique: {stage}, {name}, {seed}, {len(matches)}")
    return matches[0]


def artifact_path(stage: str, arm: str, seed: int | None = None) -> Path:
    if arm == "hgb_original":
        return COVERAGE / f"{stage}_hgb.joblib"
    if arm == "hgb_capacity":
        return HGB_NEW / f"{stage}_hgb.joblib"
    if arm == "rl_original":
        return RL_OLD / f"{stage}_rl_{seed}.pt"
    if arm == "rl_capacity":
        return RL_NEW / f"{stage}_rl_{seed}.pt"
    if arm == "rl_zero_reference":
        return RL_OLD / f"{stage}_rl_{seed}_zero.pt"
    raise ValueError(arm)


def preflight(stage: str) -> dict:
    """Bind the actual execution functions and every selected model byte."""
    engine_file = Path(inspect.getsourcefile(run_replay)).resolve()
    adapter_file = Path(inspect.getsourcefile(PolicyV2)).resolve()
    if engine_file != (CURRENT / "engine_v2.py").resolve() or sha(engine_file) != EXPECTED_ENGINE_SHA:
        raise RuntimeError("actual run_replay source is not the frozen holding-aware engine")
    if adapter_file != (CURRENT / "adapters_v2.py").resolve() or sha(adapter_file) != EXPECTED_ADAPTER_SHA:
        raise RuntimeError("actual PolicyV2 source drift")
    if tuple(FEATURES) != tuple(values.FEATURES) or tuple(FEATURES) != tuple(registry()["feature_order"]):
        raise RuntimeError("32 feature order differs between HGB, RL and frozen score registry")
    coverage_receipt = read_json(COVERAGE / "FIT_RECEIPT.json")
    hgb_receipt = read_json(HGB_NEW / "FIT_RECEIPT.json")
    rl_original_receipt = read_json(RL_OLD / "TRAIN_RECEIPT.json")
    rl_capacity_receipt = read_json(RL_NEW / "TRAIN_RECEIPT.json")
    if coverage_receipt.get("status") != "PASS" or hgb_receipt.get("status") != "PASS":
        raise RuntimeError("HGB receipt not completed")
    if rl_capacity_receipt.get("status") != "PAIRED_RL_CAPACITY_TRAINING_COMPLETE":
        raise RuntimeError("RL capacity receipt not completed")
    if rl_original_receipt.get("status") != "JOINT_TRAINING_COMPLETE":
        raise RuntimeError("RL original receipt not completed")
    if hgb_receipt.get("test2026_rows_read") != 0 or rl_capacity_receipt.get("fit_2026_rows") != 0:
        raise RuntimeError("training time boundary violated")
    if hgb_receipt.get("fit_calls_completed") != 2 or rl_capacity_receipt.get("actual_parameter_updates") != 320:
        raise RuntimeError("new fit budget differs from contract")
    selected = {}
    for arm, receipt, name in (("hgb_original", coverage_receipt, "hgb"),
                               ("hgb_capacity", hgb_receipt, "hgb")):
        path = artifact_path(stage, arm)
        record = receipt_artifact(receipt, stage, name)
        if sha(path) != record["artifact_sha256"]:
            raise RuntimeError(f"artifact drift: {path}")
        selected[arm] = {"path": str(path), "sha256": sha(path)}
    for arm, receipt in (("rl_original", rl_original_receipt), ("rl_capacity", rl_capacity_receipt)):
        selected[arm] = []
        for seed in SEEDS:
            path = artifact_path(stage, arm, seed)
            record = receipt_artifact(receipt, stage, "rl", seed)
            if sha(path) != record["sha256"]:
                raise RuntimeError(f"artifact drift: {path}")
            selected[arm].append({"seed": seed, "path": str(path), "sha256": sha(path)})
    selected["rl_zero_reference"] = []
    for seed in SEEDS:
        path = artifact_path(stage, "rl_zero_reference", seed)
        if not path.exists():
            raise FileNotFoundError(path)
        selected["rl_zero_reference"].append({"seed": seed, "path": str(path), "sha256": sha(path)})
    old_hgb_receipt = OLD / "joint_linear_tree_artifacts/FIT_RECEIPT.json"
    old_hgb_loaded = OLD / "joint_linear_tree_artifacts" / f"{stage}_hgb.joblib"
    if not old_hgb_loaded.exists():
        raise FileNotFoundError(old_hgb_loaded)
    score_hgb = Path(registry()["models"]["hgb"]["path"])
    if sha(score_hgb) != registry()["models"]["hgb"]["sha256"]:
        raise RuntimeError("frozen baseline score HGB drift")
    sources = [ROOT / "EXPERIMENT_CONTRACT.md", ROOT / "DATA_DEPENDENCY.md", Path(__file__),
               engine_file, adapter_file, CURRENT / "run_v2.py", CURRENT / "joint_neural_v2.py",
               OLD / "joint_linear_tree.py", OLD / "models/model_registry.json", OLD / "models/predict.py",
               score_hgb, old_hgb_receipt, old_hgb_loaded,
               COVERAGE / "FIT_RECEIPT.json", COVERAGE / "PRE_FIT_CONTRACT.json",
               COVERAGE / f"sample_keys_{stage}.parquet",
               HGB_NEW / "FIT_RECEIPT.json", HGB_NEW / "PRE_FIT_CONTRACT.json",
               RL_OLD / "TRAIN_RECEIPT.json", RL_NEW / "TRAIN_RECEIPT.json",
               RL_OLD / f"{stage}_normalization.npz"]
    source_hashes = {str(path.resolve()): sha(path) for path in sources}
    for spec in selected.values():
        for item in (spec if isinstance(spec, list) else [spec]):
            source_hashes[item["path"]] = item["sha256"]
    return {"stage": stage, "selected_models": selected, "source_sha256": source_hashes,
            "actual_run_replay_source": str(engine_file), "actual_PolicyV2_source": str(adapter_file)}


def verify_unchanged(binding: dict):
    for raw_path, expected in binding["source_sha256"].items():
        if sha(Path(raw_path)) != expected:
            raise RuntimeError(f"read-only input changed during evaluation: {raw_path}")


def load_rl_models(stage: str, arm: str, seeds=SEEDS):
    models = []
    for seed in seeds:
        model = JointPolicy()
        model.load_state_dict(torch.load(artifact_path(stage, arm, seed), weights_only=True, map_location="cpu"))
        model.eval()
        models.append(model)
    return models


def actor_for(label: str, stage: str) -> PolicyV2:
    if label in {"hgb_original", "hgb_capacity"}:
        actor = PolicyV2("joint_hgb", stage)
        actor.value.models["hgb"] = joblib.load(artifact_path(stage, label))
        return actor
    if label.startswith("rl_original") or label.startswith("rl_capacity"):
        arm = "rl_original" if label.startswith("rl_original") else "rl_capacity"
        actor = PolicyV2("joint_rl_ensemble", stage)
        seeds = SEEDS
        if label.endswith(str(SEEDS[0])):
            seeds = (SEEDS[0],)
        elif label.endswith(str(SEEDS[1])):
            seeds = (SEEDS[1],)
        actor.neural.models = load_rl_models(stage, arm, seeds)
        return actor
    if label == "rl_zero_reference":
        return PolicyV2("joint_rl_zero_control", stage)
    if label == "hgb_return_reference":
        return PolicyV2("hgb_return_baseline", stage)
    raise ValueError(label)


def interface_check() -> dict:
    """No account replay; ensure identical feature/architecture and artifact loading."""
    out = {"status": "PASS", "fit_attempts": 0, "stages": {}}
    for stage in ("validation", "final"):
        binding = preflight(stage)
        x = values.mapped_features(np.zeros((1, len(FEATURES))), np.zeros(1), np.ones(1), np.zeros(1), np.zeros(1))
        if x.shape != (1, 106):
            raise RuntimeError(f"HGB input dimension changed: {x.shape}")
        for arm in ("hgb_original", "hgb_capacity"):
            actor = actor_for(arm, stage)
            score = values.predict_values(actor.value.models["hgb"], "hgb", x)
            if score.shape != (1,) or not np.isfinite(score).all():
                raise RuntimeError(f"HGB injection failed: {arm}, {stage}")
        for arm in ("rl_original", "rl_capacity"):
            actor = actor_for(arm, stage)
            with torch.no_grad():
                scores = [m(torch.zeros((1, len(FEATURES) + 3), dtype=torch.float32)).numpy()
                          for m in actor.neural.models]
            if len(scores) != 2 or any(x.shape != (1,) or not np.isfinite(x).all() for x in scores):
                raise RuntimeError(f"RL injection failed: {arm}, {stage}")
        verify_unchanged(binding)
        out["stages"][stage] = {"model_sha256": binding["selected_models"],
                                "hgb_input_width": 106, "rl_input_width": len(FEATURES) + 3}
    write_json(ROOT / "INTERFACE_CHECK.json", out)
    return out


def load_inputs(year: int):
    if year == 2026:
        panel_path = CURRENT / "data/test_features_context.parquet"
        price_path = CURRENT / "data/test_prices.parquet"
        calendar_path = OLD / "data/calendar.parquet"
        panel = pd.read_parquet(panel_path)
        prices = pd.read_parquet(price_path)
        calendar = pd.DatetimeIndex(pd.read_parquet(calendar_path).query("is_test").trade_date)
        # Exact HGB column of run_v2.predict_panel, without loading its eight
        # unused frozen models into this long-running paired evaluation process.
        baseline_values = panel[list(FEATURES)].to_numpy(float)
        if not np.isfinite(baseline_values).all():
            raise RuntimeError("nonfinite frozen baseline scoring features")
        score = panel[["signal_date", "ticker"]].copy()
        score["baseline_hgb"] = load_model("hgb").predict(baseline_values)
        if not np.isfinite(score.baseline_hgb.to_numpy(float)).all():
            raise RuntimeError("nonfinite frozen baseline HGB score")
        last, stage, extra = "2026-09-22", "final", [calendar_path]
    else:
        panel_path = OLD / "data/pre2026_joint_context.parquet"
        price_path = STRICT / "results/pre2026_original_price_coordinate.parquet"
        score_path = STRICT / "results/hgb/pre2026_oof.parquet"
        panel = pd.read_parquet(panel_path).query('signal_date >= "2025-01-01"').copy()
        prices = pd.read_parquet(price_path)
        calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") &
                                                    prices.trade_date.ge("2025-01-01"), "trade_date"].unique()))
        score = pd.read_parquet(score_path)
        score = score.loc[score.signal_date.dt.year.eq(2025),
                          ["signal_date", "ticker", "prediction"]].rename(columns={"prediction": "baseline_hgb"})
        last, stage, extra = "2025-12-29", "validation", [score_path]
    panel = panel.loc[panel.signal_date.le(last)].copy()
    panel = panel.merge(score, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if panel.baseline_hgb.isna().any() or panel.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("incomplete or duplicate evaluation panel")
    panel = panel[["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + list(FEATURES)]
    asofs = v2.clocks(calendar)
    ops = v2.operational_schedule(calendar, asofs) if year == 2026 else {}
    paths = [panel_path, price_path, *extra]
    if year == 2026:
        paths.append(CURRENT / "data/DATA_RECEIPT.json")
        paths.append(CURRENT / "data/operational_exit_evidence.csv")
    return panel, prices, calendar, asofs, ops, last, stage, {str(p.resolve()): sha(p) for p in paths}


def roster(year: int):
    names = ["hgb_original", "hgb_capacity", "rl_original", "rl_capacity",
             "rl_zero_reference", "hgb_return_reference"]
    if year == 2025:
        for arm in ("rl_original", "rl_capacity"):
            names += [f"{arm}_seed_{seed}" for seed in SEEDS]
    return names


def reference_folder(year: int, label: str) -> Path | None:
    policy = {"rl_zero_reference": "joint_rl_zero_control",
              "hgb_return_reference": "hgb_return_baseline"}.get(label)
    return CURRENT / f"evaluation_{year}" / "cost_10" / policy if policy else None


def bind_references(year: int) -> dict:
    complete = CURRENT / f"evaluation_{year}" / "cost_10" / "COMPLETE.json"
    receipt = read_json(complete)
    if receipt.get("status") != "VERSIONED_DIAGNOSTIC_REPLAY_COMPLETE" or receipt.get("cost_bps") != 10 or receipt.get("year") != year or receipt.get("fit_attempts") != 0:
        raise RuntimeError("saved reference batch contract differs")
    result = {}
    for label in ("rl_zero_reference", "hgb_return_reference"):
        folder = reference_folder(year, label)
        meta = read_json(folder / "metadata.json")
        if meta.get("capacity_fraction") != .01 or meta.get("cost_bps_one_way") != 10 or meta.get("signal_end") != ("2025-12-29" if year == 2025 else "2026-09-22"):
            raise RuntimeError(f"saved reference account contract differs: {label}")
        result[label] = {"path": str(folder), "metadata": meta,
                         "sha256": {key: sha(folder / f"{key}.parquet") for key in LEDGERS},
                         "metadata_sha256": sha(folder / "metadata.json")}
    result["batch_complete_sha256"] = sha(complete)
    return result


def capacity_metrics(trades: pd.DataFrame, targets: pd.DataFrame) -> dict:
    buys = trades.loc[trades.side.eq("BUY")].copy()
    if buys.empty:
        return dict(limited_buy_fills=0, limited_execution_dates=0, requested_dollars=0.,
                    cap_dollars=0., actual_dollars=0., pre_cash_capacity_gap_dollars=0.,
                    after_cap_cash_gap_dollars=0.)
    keyed = targets[["order_id", "target_weight", "signal_day_adv"]]
    buys = buys.merge(keyed, on="order_id", validate="one_to_one")
    buys["requested"] = (buys.target_weight * buys.pretrade_nav - buys.index_units_before * buys.price).clip(lower=0)
    buys["cap"] = .01 * buys.signal_day_adv
    limited = buys.loc[buys.requested > buys.cap + 1e-7]
    return dict(limited_buy_fills=len(limited), limited_execution_dates=limited.execution_date.nunique(),
                requested_dollars=limited.requested.sum(), cap_dollars=limited.cap.sum(),
                actual_dollars=limited.notional.sum(),
                pre_cash_capacity_gap_dollars=(limited.requested - limited.cap).sum(),
                after_cap_cash_gap_dollars=np.maximum(0, np.minimum(limited.requested, limited.cap) - limited.notional).sum())


def path_metrics(folder: Path, year: int, label: str) -> dict:
    daily = pd.read_parquet(folder / "daily.parquet")
    trades = pd.read_parquet(folder / "trades.parquet")
    target = pd.read_parquet(folder / "target_decisions.parquet")
    execution = pd.read_parquet(folder / "execution_results.parquet")
    nav = daily.nav.astype(float)
    all_certified = year == 2025 and daily.certified_nav.notna().all()
    # Never splice an uncertified 2026 NAV gap into apparent daily zero returns.
    # GLW's disputed candidate feature also prevents formal 2026 risk metrics.
    if all_certified:
        certified = daily.certified_nav.astype(float)
        step = pd.concat([pd.Series([1_000_000.]), certified], ignore_index=True).pct_change(fill_method=None).iloc[1:]
        sd = step.std(ddof=1)
        vol = float(sd * np.sqrt(252)) if len(step) > 1 and np.isfinite(sd) else None
        sharpe = float(step.mean() / sd * np.sqrt(252)) if np.isfinite(sd) and sd > 0 else None
        growth = certified / 1_000_000
        running_max = pd.concat([pd.Series([1.]), growth], ignore_index=True).cummax().iloc[1:].to_numpy()
        dd = growth.to_numpy() / running_max - 1
        max_dd = float(np.min(dd))
    else:
        vol = sharpe = max_dd = None
    cap = capacity_metrics(trades, target)
    return dict(path=label, year=year, cost_bps=10, account_unit="frozen adjusted price index, not shareholder total return",
                evaluation_status="CERTIFIED_RETROSPECTIVE_2025" if all_certified
                else "INDICATIVE_CONFLICT_SENSITIVE_2026",
                risk_metric_qualification="CERTIFIED_RETROSPECTIVE_2025" if all_certified
                else "NOT_CALCULATED_2026_UNCERTIFIED_GAPS_AND_GLW_CONFLICT",
                certified_retrospective_return=float(nav.iloc[-1] / 1_000_000 - 1) if all_certified else None,
                indicative_return=float(nav.iloc[-1] / 1_000_000 - 1) if np.isfinite(nav.iloc[-1]) else None,
                max_drawdown=max_dd,
                annualized_volatility=vol, sharpe_zero_rf=sharpe,
                mean_gross_exposure=float(daily.gross_exposure.mean()), mean_cash_weight=float(daily.cash_weight.mean()),
                total_turnover=float(daily.turnover.sum()), total_cost_dollars=float(daily.transaction_cost_amount.sum()),
                cost_fraction_of_initial=float(daily.transaction_cost_amount.sum() / 1_000_000),
                uncertified_valuation_days=int(daily.certified_nav.isna().sum()),
                execution_rejections=int(execution.status.eq("REJECTED").sum()),
                traded_orders=len(trades), **cap)


def paired_metrics(metrics: dict, year: int) -> list[dict]:
    pairs = [("HGB", "hgb_original", "hgb_capacity"), ("RL_TWO_SEED_ENSEMBLE", "rl_original", "rl_capacity")]
    if year == 2025:
        pairs += [(f"RL_SEED_{seed}", f"rl_original_seed_{seed}", f"rl_capacity_seed_{seed}") for seed in SEEDS]
    rows = []
    for label, old, new in pairs:
        a, b = metrics[old], metrics[new]
        fields = ["indicative_return", "mean_gross_exposure", "mean_cash_weight", "total_turnover",
                  "total_cost_dollars", "cost_fraction_of_initial", "limited_buy_fills",
                  "pre_cash_capacity_gap_dollars", "max_drawdown", "annualized_volatility", "sharpe_zero_rf"]
        row = {"pair": label, "year": year, "original_path": old, "capacity_path": new,
               "certified_retrospective_comparison": year == 2025 and a["certified_retrospective_return"] is not None and b["certified_retrospective_return"] is not None,
               "certified_retrospective_net_return_delta": b["certified_retrospective_return"] - a["certified_retrospective_return"] if year == 2025 and a["certified_retrospective_return"] is not None and b["certified_retrospective_return"] is not None else None,
               "indicative_net_return_delta": b["indicative_return"] - a["indicative_return"] if a["indicative_return"] is not None and b["indicative_return"] is not None else None,
               "note": "2025已观察，非独立盲测" if year == 2025 else "INDICATIVE_CONFLICT_SENSITIVE; 2026回撤/波动/Sharpe亦非正式可比指标；GLW候选特征冲突、未认证估值及非完整原池"}
        row.update({f"delta_{f}": b[f] - a[f] if a[f] is not None and b[f] is not None else None for f in fields})
        rows.append(row)
    return rows


def monthly_metrics(folder: Path, label: str) -> pd.DataFrame:
    daily = pd.read_parquet(folder / "daily.parquet", columns=["date", "nav", "certified_nav"])
    daily["month"] = pd.to_datetime(daily.date).dt.to_period("M").astype(str)
    month = daily.groupby("month", sort=True).tail(1).copy()
    previous = month.nav.shift(1).fillna(1_000_000.)
    month["monthly_indicative_return"] = month.nav / previous - 1
    month["path"] = label
    month["month_all_days_certified"] = daily.groupby("month").certified_nav.apply(lambda x: x.notna().all()).reindex(month.month).to_numpy()
    return month[["path", "month", "monthly_indicative_return", "month_all_days_certified"]]


def evaluate(year: int):
    stage = "validation" if year == 2025 else "final"
    year_out = OUT / f"{year}_10bps"
    if year_out.exists():
        raise RuntimeError(f"evaluation output already exists; preserve it: {year_out}")
    binding = preflight(stage)
    panel, prices, calendar, asofs, ops, last, loaded_stage, input_hashes = load_inputs(year)
    if stage != loaded_stage:
        raise AssertionError("stage mismatch")
    binding["input_sha256"] = input_hashes
    binding["saved_references"] = bind_references(year)
    binding.update({"year": year, "cost_bps": 10, "capacity_fraction": .01,
                    "signal_start": f"{year}-01-01", "signal_end": last,
                    "initial_cash": 1_000_000, "roster": roster(year),
                    "full_pool_complete": False if year == 2026 else None,
                    "historical_status": "retrospective_2025" if year == 2025 else "INDICATIVE_CONFLICT_SENSITIVE_2026",
                    "glw_20260226_candidate_conflict": year == 2026,
                    "glw_conflict_propagation": "2026-02-26 GLW was an actual model candidate input even when its old target was zero; alternate event timing may change scores, orders, holdings and later account state" if year == 2026 else None,
                    "unknown_2026_candidate_rows": 47271 if year == 2026 else None})
    year_out.mkdir(parents=True)
    write_json(year_out / "SOURCE_BINDING.json", binding)
    guard = forbid_fitting()
    for label in roster(year):
        if reference_folder(year, label) is not None:
            print(json.dumps({"year": year, "path": label, "source": "saved_same_version_reference"}), flush=True)
            continue
        folder = year_out / label
        folder.mkdir()
        actor = actor_for(label, stage)
        with threadpool_limits(limits=2):
            result = run_replay(prices, calendar, panel, actor, candidate=label, cost_bps=10,
                                capacity_fraction=.01, signal_start=f"{year}-01-01", signal_end=last,
                                signal_asof=asofs, operational_exits_by_signal=ops)
        for key in LEDGERS:
            getattr(result, key).to_parquet(folder / f"{key}.parquet", index=False)
        write_json(folder / "metadata.json", result.metadata)
        write_json(folder / "PATH_COMPLETE.json", {"status": "LEDGERS_SAVED_BEFORE_METRICS", "path": label,
                    "year": year, "fit_attempts": guard["attempts"],
                    "ledger_sha256": {key: sha(folder / f"{key}.parquet") for key in LEDGERS},
                    "metadata_sha256": sha(folder / "metadata.json")})
        print(json.dumps({"year": year, "path": label, "rows": len(result.daily),
                          "uncertified_days": int(result.daily.certified_nav.isna().sum())}), flush=True)
    if guard["attempts"] != 0:
        raise RuntimeError("fitting attempted during evaluation")
    verify_unchanged(binding)
    for p, expected in input_hashes.items():
        if sha(Path(p)) != expected:
            raise RuntimeError(f"input drift: {p}")
    for label in ("rl_zero_reference", "hgb_return_reference"):
        ref = binding["saved_references"][label]
        folder = Path(ref["path"])
        if sha(folder / "metadata.json") != ref["metadata_sha256"] or any(sha(folder / f"{key}.parquet") != digest for key, digest in ref["sha256"].items()):
            raise RuntimeError(f"saved reference changed: {label}")
    folders = {label: reference_folder(year, label) or year_out / label for label in roster(year)}
    metrics = {label: path_metrics(folders[label], year, label) for label in roster(year)}
    pd.DataFrame([metrics[label] for label in roster(year)]).to_csv(year_out / "PATH_METRICS.csv", index=False)
    pd.DataFrame(paired_metrics(metrics, year)).to_csv(year_out / "PAIRED_METRICS.csv", index=False)
    pd.concat([monthly_metrics(folders[label], label) for label in roster(year)], ignore_index=True).to_csv(
        year_out / "MONTHLY_RETURNS.csv", index=False)
    write_json(year_out / "COMPLETE.json", {"status": "PAIRED_EVALUATION_COMPLETE", "year": year,
        "paths": len(roster(year)), "new_replays": len(roster(year)) - 2, "saved_reference_paths": 2,
        "fit_attempts": guard["attempts"], "read_only_sources_unchanged": True,
        "full_pool_complete": False if year == 2026 else None,
        "return_qualification": "CERTIFIED_RETROSPECTIVE_2025" if year == 2025 else "INDICATIVE_CONFLICT_SENSITIVE_2026",
        "glw_20260226_candidate_conflict": year == 2026,
        "glw_conflict_propagation": "possible later score/order/holding/NAV changes from 2026-02-26 candidate feature" if year == 2026 else None,
        "unknown_2026_candidate_rows": 47271 if year == 2026 else None,
        "metric_sha256": {name: sha(year_out / name) for name in ("PATH_METRICS.csv", "PAIRED_METRICS.csv", "MONTHLY_RETURNS.csv")}})
    print(json.dumps({"status": "PAIRED_EVALUATION_COMPLETE", "year": year,
                      "paths": len(roster(year)), "fit_attempts": guard["attempts"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-interface", action="store_true")
    parser.add_argument("--year", type=int, choices=(2025, 2026))
    args = parser.parse_args()
    if args.check_interface:
        print(json.dumps(interface_check(), ensure_ascii=False))
    elif args.year:
        evaluate(args.year)
    else:
        parser.error("select --check-interface or --year")


if __name__ == "__main__":
    main()
