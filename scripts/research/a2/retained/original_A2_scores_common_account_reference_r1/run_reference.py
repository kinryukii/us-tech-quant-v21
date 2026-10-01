"""One fixed 2025H2 research replay, followed by reuse of three frozen accounts."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys
import time

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
from reference_policy import OriginalA2ScorePolicy, ENGINE_ROOT
from engine_v2 import run_replay

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
ATTRIBUTION = WORK / "a2_ensemble_attribution_20260928_r1"
COMMON = ENGINE_ROOT / "ensemble_2025_H2" / "cost_10"
OOF = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet")
PANEL = WORK / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
PRICES = WORK / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
LEDGERS = ["daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals",
           "raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]
NAMES = ["ensemble_equal", "ensemble_consensus_risk", "ensemble_stacked"]
NAME = ROOT.name


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def validate_account(daily, trades, positions, targets, calendar):
    assert pd.DatetimeIndex(daily.date).equals(calendar)
    assert len(daily) == 128 and daily.cash.ge(-1e-7).all() and daily.actual_name_count.le(20).all()
    assert daily.certified_nav.notna().all(), "NEW_ACCOUNT_UNCERTIFIED_DATE_RETAINED"
    flows = trades.assign(signed_notional=np.where(trades.side.eq("SELL"), trades.notional, -trades.notional))
    delta = flows.groupby("execution_date").signed_notional.sum().reindex(calendar, fill_value=0)
    fees = trades.groupby("execution_date").transaction_cost.sum().reindex(calendar, fill_value=0)
    cash = 1e6 + (delta - fees).cumsum()
    cash_error = float(np.max(np.abs(cash.to_numpy() - daily.cash.to_numpy())))
    assert cash_error < 1e-5
    assert np.allclose(trades.transaction_cost, trades.notional * .001, rtol=0, atol=1e-7)
    assert np.allclose(trades.index_units * trades.price, trades.notional, rtol=0, atol=1e-6)
    assert trades.execution_date.gt(trades.signal_date).all()
    next_session = dict(zip(calendar[:-1], calendar[1:]))
    assert (trades.signal_date.map(next_session) == trades.execution_date).all()
    buy = trades[trades.side.eq("BUY")].merge(
        targets[["order_id", "signal_day_adv"]], on="order_id", validate="one_to_one")
    assert (buy.notional <= .01 * buy.signal_day_adv + 1e-6).all()
    market = positions.groupby("date").market_value.sum().reindex(calendar, fill_value=0)
    assert np.allclose(daily.nav, daily.cash + market.to_numpy(), rtol=0, atol=1e-5)
    signed_units = trades.assign(signed_units=np.where(trades.side.eq("BUY"), trades.index_units, -trades.index_units))
    changes = signed_units.pivot_table(index="execution_date", columns="ticker", values="signed_units", aggfunc="sum", fill_value=0)
    expected = changes.reindex(calendar, fill_value=0).cumsum()
    actual = positions.pivot(index="date", columns="ticker", values="index_units").reindex(index=calendar, columns=expected.columns).fillna(0)
    assert np.allclose(expected.to_numpy(), actual.to_numpy(), rtol=0, atol=1e-7)
    return {"status": "PASS", "dates": 128, "uncertified_dates": 0,
            "cash_identity_max_absolute_usd_error": cash_error,
            "next_session_clock_checked": True, "fees_and_units_checked": True,
            "buy_adv_cap_checked": True, "positions_reconciled_from_all_trades": True}


def metrics(name, daily, trades, targets, execution):
    nav = np.r_[1e6, daily.nav.to_numpy(float)]
    fee = float(trades.transaction_cost.sum())
    net = float(nav[-1] - 1e6)
    rejected = execution.status.eq("REJECTED")
    return {
        "policy": name, "days": len(daily), "end_nav": float(nav[-1]),
        "net_bookkeeping_pnl_usd": net, "net_bookkeeping_return": net / 1e6,
        "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
        "mean_actual_cash_weight": float(daily.cash_weight.mean()),
        "last_actual_cash_weight": float(daily.cash_weight.iloc[-1]),
        "fees_usd": fee, "pnl_plus_fees_usd": net + fee,
        "traded_notional_usd": float(trades.notional.sum()),
        "cumulative_half_turnover": float(daily.turnover.sum()),
        "actual_position_count_max": int(daily.actual_name_count.max()),
        "actual_position_count_mean": float(daily.actual_name_count.mean()),
        "trades": len(trades), "buys": int(trades.side.eq("BUY").sum()),
        "sells": int(trades.side.eq("SELL").sum()),
        "active_exit_decisions": int(targets.decision_semantic.eq("MODEL_ACTIVE_EXIT").sum()),
        "no_decision_held_events": int((targets.decision_semantic.eq("MODEL_NO_DECISION") & targets.current_units.gt(0)).sum()),
        "rejected_order_events": int(rejected.sum()),
        "uncertified_days": int(daily.certified_nav.isna().sum()),
        "shareholder_total_return_certified": False, "blind_test": False,
        "source": "single_new_replay" if name == NAME else "existing_account_reused",
    }


def main():
    if (ROOT / "COMPLETE.json").exists() or (ROOT / "REPLAY_STARTED.json").exists():
        raise RuntimeError("SINGLE_RESEARCH_REPLAY_ALREADY_STARTED_OR_COMPLETE_PRESERVED")
    admission = read(ROOT / "ADMISSION_H2.json")
    assert admission["status"] == "PASS_FOR_FIXED_2025H2_COMMON_ACCOUNT_RESEARCH_REPLAY", admission.get("blockers")
    assert not admission.get("blockers") and all(admission["checks"].values())
    source_sha = dict(admission["source_sha256"])
    for filename, digest in admission["evidence_outputs"].items():
        assert sha(ROOT / filename) == digest, f"ADMISSION_EVIDENCE_DRIFT:{filename}"
        source_sha[str(ROOT / filename)] = digest
    test = read(ROOT / "TEST_RECEIPT.json")
    assert test["exit_code"] == 0 and "Ran 6 tests" in test["stderr"]
    assert sha(ROOT / "reference_policy.py") == test["adapter_sha256"]
    assert sha(ROOT / "test_reference_policy.py") == test["test_file_sha256"]
    for path, digest in source_sha.items():
        assert sha(path) == digest, f"ADMISSION_DEPENDENCY_DRIFT:{path}"
    previous_binding = read(COMMON / "FROZEN_BEFORE_REPLAY.json")
    for path in [PANEL, PRICES, ENGINE_ROOT / "engine_v2.py"]:
        expected = previous_binding["sources"][str(path)]
        assert sha(path) == expected, f"EXISTING_COMMON_INPUT_DRIFT:{path}"
        source_sha[str(path)] = expected
    identity = read(ATTRIBUTION / "qualification_original_a2_oof_admissibility.json")
    assert sha(OOF) == identity["frozen_expected_sha256"]
    source_sha[str(OOF)] = sha(OOF)
    for path in [ROOT / "reference_policy.py", ROOT / "run_reference.py", ROOT / "REFERENCE_CONTRACT.md",
                 ROOT / "ADMISSION_H2.json", ROOT / "TEST_RECEIPT.json", ROOT / "test_reference_policy.py",
                 ROOT / "admission_h2.py", ATTRIBUTION / "CONTROL_PLAN.md"]:
        source_sha[str(path)] = sha(path)

    existing, existing_meta = {}, {}
    for name in NAMES:
        folder = COMMON / name
        receipt = read(folder / "PATH_COMPLETE.json")
        for ledger, digest in receipt["ledger_sha256"].items():
            path = folder / f"{ledger}.parquet"
            assert sha(path) == digest, f"EXISTING_ACCOUNT_DRIFT:{path}"
            source_sha[str(path)] = digest
        for filename in ["metadata.json", "PATH_COMPLETE.json"]:
            source_sha[str(folder / filename)] = sha(folder / filename)
        existing_meta[name] = read(folder / "metadata.json")
        existing[name] = {key: pd.read_parquet(folder / f"{key}.parquet")
                          for key in ["daily", "trades", "target_decisions", "execution_results", "signal_contexts"]}

    panel = pd.read_parquet(PANEL)
    panel = panel.loc[panel.signal_date.between("2025-07-01", "2025-12-29"),
                      ["signal_date", "ticker", "new_buy_eligible", "avg_dollar_volume_20d"]].copy()
    prices = pd.read_parquet(PRICES)
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") &
        prices.trade_date.between("2025-07-01", "2025-12-31"), "trade_date"].unique()))
    assert len(calendar) == 128 and panel.signal_date.nunique() == 126 and len(panel) == 57819
    assert panel.new_buy_eligible.all() and np.isfinite(panel.avg_dollar_volume_20d).all()
    scores = pd.read_parquet(OOF)
    scores = scores.loc[scores.signal_date.between("2025-07-01", "2025-12-29") & scores.split.eq("FINAL")].copy()
    assert len(scores) == 57819
    joined = panel[["signal_date", "ticker"]].merge(scores[["signal_date", "ticker", "a2_prediction"]],
        on=["signal_date", "ticker"], how="outer", validate="one_to_one", indicator=True)
    assert joined._merge.eq("both").all() and np.isfinite(joined.a2_prediction).all()
    early = {"2025-07-03", "2025-11-28", "2025-12-24"}
    asofs = {day: (day + pd.Timedelta(hours=13 if str(day.date()) in early else 16))
             .tz_localize("America/New_York").tz_convert("UTC") for day in calendar}
    for name, account in existing.items():
        assert pd.DatetimeIndex(account["daily"].date).equals(calendar)
        contexts = account["signal_contexts"]
        assert len(contexts) == 126
        assert contexts.signal_asof.tolist() == contexts.signal_date.map(asofs).tolist(), f"CLOCK_DIFF:{name}"

    scores[["signal_date", "ticker", "a2_prediction", "a2_rank", "split"]].to_parquet(ROOT / "CONSUMED_OOF_H2.parquet", index=False)
    clock = pd.DataFrame({"date": calendar, "signal_asof": [asofs[day] for day in calendar],
                          "next_session": list(calendar[1:]) + [pd.NaT],
                          "is_signal": calendar <= pd.Timestamp("2025-12-29")})
    clock.to_csv(ROOT / "COMMON_CLOCK.csv", index=False)
    write(ROOT / "FROZEN_BEFORE_REPLAY.json", {
        "reference": NAME, "scope": "one fixed H2 reference, three existing accounts reused",
        "source_sha256": source_sha, "score_threshold": None, "single_name_mapping": .0475,
        "max_names": 20, "initial_cash": 1e6, "initial_positions": {},
        "cost_bps_one_way": 10, "capacity_fraction": .01, "capacity_on_sells": False,
        "calendar_start": "2025-07-01", "calendar_end": "2025-12-31", "calendar_days": 128,
        "signal_end": "2025-12-29", "signal_days": 126, "new_fits": 0, "new_predictions": 0,
        "existing_accounts_replayed": 0, "blind_test": False,
    })
    actor = OriginalA2ScorePolicy(scores)
    output = ROOT / "account"
    assert not output.exists(), "PARTIAL_ACCOUNT_MUST_BE_INSPECTED"
    output.mkdir()
    write(ROOT / "REPLAY_STARTED.json", {"started_utc": datetime.now(timezone.utc).isoformat(), "new_research_replays": 1})
    print("ADMISSION_PASS; starting the single fixed 2025H2 reference replay", flush=True)
    started = time.monotonic()
    result = run_replay(prices, calendar, panel, actor, candidate=NAME, initial_cash=1e6, initial_positions={},
        cost_bps=10, max_weight=.10, max_positions=20, max_invested=.95, capacity_fraction=.01,
        signal_start="2025-07-01", signal_end="2025-12-29", capacity_on_sells=False,
        signal_asof=asofs, operational_exits_by_signal={})
    for key in LEDGERS:
        getattr(result, key).to_parquet(output / f"{key}.parquet", index=False)
    write(output / "metadata.json", result.metadata)
    for name, metadata in existing_meta.items():
        assert result.metadata == metadata, f"COMMON_ACCOUNT_METADATA_DIFF:{name}"
    new_audit = validate_account(result.daily, result.trades, result.positions, result.target_decisions, calendar)
    assert actor.calls == 126
    contexts = result.signal_contexts
    assert pd.DatetimeIndex(contexts.signal_date).equals(calendar[:126])
    assert contexts.signal_asof.tolist() == contexts.signal_date.map(asofs).tolist()
    assert result.target_decisions.raw_model_weight.dropna().le(.0475 + 1e-12).all()
    audit = {**new_audit, "saved_score_policy_calls": actor.calls,
             "score_rows_consumed_after_engine_reservations": actor.score_rows_consumed,
             "metadata_identical_to_all_three_existing_accounts": True}
    row = metrics(NAME, result.daily, result.trades, result.target_decisions, result.execution_results)
    write(output / "PATH_COMPLETE.json", {"audit": audit, "metrics": row,
        "ledger_sha256": {key: sha(output / f"{key}.parquet") for key in LEDGERS}})

    rows = [row]
    daily_all = [result.daily.assign(policy=NAME)]
    differences = []
    for name in NAMES:
        saved = existing[name]
        other = metrics(name, saved["daily"], saved["trades"], saved["target_decisions"], saved["execution_results"])
        rows.append(other)
        daily_all.append(saved["daily"].assign(policy=name))
        difference = {"policy_minus_reference": name,
                      "net_pnl_difference_usd": other["net_bookkeeping_pnl_usd"] - row["net_bookkeeping_pnl_usd"],
                      "return_difference_percentage_points": 100 * (other["net_bookkeeping_return"] - row["net_bookkeeping_return"]),
                      "max_drawdown_difference_percentage_points": 100 * (other["max_drawdown"] - row["max_drawdown"]),
                      "mean_cash_difference_percentage_points": 100 * (other["mean_actual_cash_weight"] - row["mean_actual_cash_weight"]),
                      "fees_saved_usd": row["fees_usd"] - other["fees_usd"],
                      "pnl_plus_fees_difference_usd": other["pnl_plus_fees_usd"] - row["pnl_plus_fees_usd"],
                      "half_turnover_difference": other["cumulative_half_turnover"] - row["cumulative_half_turnover"],
                      "interpretation": "whole_policy_difference; fee term is accounting, not causal complementarity"}
        assert abs(difference["net_pnl_difference_usd"] - difference["fees_saved_usd"] - difference["pnl_plus_fees_difference_usd"]) < 1e-6
        differences.append(difference)
    pd.DataFrame(rows).to_csv(ROOT / "COMPARISON.csv", index=False)
    pd.DataFrame(differences).to_csv(ROOT / "POLICY_DIFFERENCES.csv", index=False)
    daily_union = pd.concat(daily_all, ignore_index=True)
    daily_union.to_parquet(ROOT / "ALL_FOUR_ACCOUNT_DAYS.parquet", index=False)
    selected = daily_union[["policy", "date", "nav", "cash", "cash_weight", "transaction_cost_amount", "turnover", "actual_name_count", "certified_nav"]]
    selected.to_csv(ROOT / "ALL_FOUR_ACCOUNT_DAYS.csv", index=False)
    daily_diff = []
    for name in NAMES:
        pair = existing[name]["daily"].merge(result.daily, on="date", suffixes=("_policy", "_reference"), validate="one_to_one")
        daily_diff.append(pd.DataFrame({"policy": name, "date": pair.date,
            "nav_difference_usd": pair.nav_policy - pair.nav_reference,
            "cash_weight_difference": pair.cash_weight_policy - pair.cash_weight_reference,
            "fee_difference_usd": pair.transaction_cost_amount_policy - pair.transaction_cost_amount_reference,
            "actual_name_count_difference": pair.actual_name_count_policy - pair.actual_name_count_reference}))
    pd.concat(daily_diff, ignore_index=True).to_csv(ROOT / "DAILY_POLICY_DIFFERENCES.csv", index=False)
    for path, digest in source_sha.items():
        assert sha(path) == digest, f"SOURCE_CHANGED_DURING_SINGLE_REPLAY:{path}"
    write(ROOT / "COMPLETE.json", {
        "status": "PASS_SINGLE_2025H2_COMMON_ACCOUNT_REFERENCE", "completed_utc": datetime.now(timezone.utc).isoformat(),
        "new_research_replays": 1, "existing_accounts_replayed": 0, "existing_accounts_reused": 3,
        "new_fits": 0, "new_model_predictions": 0, "new_weight_or_cash_searches": 0,
        "year_2026_replays": 0, "source_dependencies_unchanged": True,
        "full_128_day_windows_preserved": 4, "common_metadata_and_clock_verified": True,
        "shareholder_total_return_certified": False, "blind_test": False,
        "seconds": time.monotonic() - started, "reference_metrics": row, "audit": audit,
        "output_sha256": {str(path.relative_to(ROOT)): sha(path) for path in ROOT.rglob("*")
                          if path.is_file() and path.name != "COMPLETE.json" and "__pycache__" not in path.parts},
    })
    print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
