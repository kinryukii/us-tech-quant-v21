"""FAST3 R28.3A frozen economic attribution and matched-placebo audit.

This module only reads the R28.3 immutable prediction and payoff ledgers.  It
does not import or invoke model fitting/scoring code, and it never reads the
prospective Phase 3 interval.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday,
                                    USLaborDay, USMartinLutherKingJr, USMemorialDay,
                                    USPresidentsDay, USThanksgivingDay, nearest_workday)

REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
P2 = RESULTS / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
LEDGERS = RESULTS / "scratch" / "fast3" / "r28_phase2_20260808T125629Z" / "ledgers"
PAYOFF = RESULTS / "scratch" / "fast3" / "r27_2_independent_heads_20260806T235700000Z" / "r27_2_regenerated_r26a2_payoff_ledger.parquet"
COMPLETION = RESULTS / "frozen" / "fast3" / "cleanroom_r2_execution_contract_completion_20260808" / "execution_contract_completion.json"
OUT = RESULTS / "frozen" / "fast3" / "r28_3a_frozen_economic_attribution_20260809_r2"
EXPECTED_IDENTITY = {
    "lineage_sha256": "eb012006137745cc870840afac9b9fc9b59a46c9268f860d12ffd9c715e8b4df",
    "payoff_sha256": "f042b3e056474d242b8452e44807819b9f57772abf8b005741edb9d2a2fbaf92",
    "execution_contract_sha256": "31caf642a929bad214677fd988954b893647b77909311e586916d424d86bb267",
    "execution_completion_sha256": "17bf95775457e76c1f0e9f6d2c7fde41c5c7e117cac3f133a6da0f2cd639b55e",
}
BASELINE = {
    "trade_count": 1198, "win_rate": 0.48831385642737896,
    "mean_net20": 0.006491550349221664, "reverse": 0.005315601347389026,
    "minus1": 0.0016510410610386112, "plus1": -0.004189244624744792,
    "plus2": 0.007376067784829085,
}
SEED, RUNS = 28301, 1000
LEVELS = [
    ["underlying_symbol", "head", "year_month", "weekday", "session"],
    ["underlying_symbol", "head", "year_month", "session"],
    ["underlying_symbol", "head", "weekday", "session"],
    ["underlying_symbol", "head", "session"],
    ["underlying_symbol", "head"],
]
MATCHED_RULE = {
    "strong_pass": "real_net20_percentile >= 0.95 AND net20_p <= 0.05",
    "very_strong_pass": "real_net20_percentile >= 0.99 AND net20_p <= 0.01",
    "fail": "real_net20_percentile < 0.90 OR net20_p > 0.10",
}


class AuditStop(RuntimeError):
    """A fail-closed frozen-artifact audit stop."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def q(values, percentile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), percentile))


def empirical_p(random_values, real_value: float) -> float:
    values = np.asarray(random_values, dtype=float)
    return float((1 + (values >= real_value).sum()) / (len(values) + 1))


def sessions(timestamp: pd.Series) -> pd.Series:
    local = pd.to_datetime(timestamp, utc=True).dt.tz_convert("America/New_York")
    minute = local.dt.hour * 60 + local.dt.minute
    return pd.Series(np.select([minute.lt(240) | minute.ge(1200), minute.lt(570), minute.lt(960)],
                               ["NIGHT", "PREMARKET", "RTH"], default="AFTERHOURS"), index=timestamp.index)


def add_calendar_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    local = out.timestamp.dt.tz_convert("America/New_York")
    out["session"] = sessions(out.timestamp)
    out["year_month"] = local.dt.strftime("%Y-%m")
    out["calendar_month"] = out["year_month"]
    out["weekday"] = local.dt.day_name()
    return out


def stats(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {key: (0 if key == "trade_count" else float("nan")) for key in
                ("trade_count", "win_rate", "mean_gross", "mean_net10", "mean_net20", "median_net20", "total_net20_contribution")}
    return {"trade_count": int(len(frame)), "win_rate": float((frame.net20 > 0).mean()),
            "mean_gross": float(frame.gross.mean()), "mean_net10": float(frame.net10.mean()),
            "mean_net20": float(frame.net20.mean()), "median_net20": float(frame.net20.median()),
            "total_net20_contribution": float(frame.net20.sum())}


def assert_identity(identity: dict) -> None:
    if identity != EXPECTED_IDENTITY:
        raise AuditStop("FAST3_R28_3A_STATUS=STOPPED_IDENTITY_MISMATCH")


def assert_no_prospective(timestamps: pd.Series) -> None:
    if pd.to_datetime(timestamps, utc=True).max() > pd.Timestamp("2025-02-01T05:00:00Z"):
        raise AuditStop("STOP_PHASE3_INTERVAL_FORBIDDEN")


def validate_frozen_scores(ledger: pd.DataFrame, head: str) -> None:
    required = {"probability", "selected", "target_first", "head", "underlying_symbol", "decision_timestamp_utc"}
    if not required.issubset(ledger) or ledger.probability.isna().any():
        raise AuditStop("SCORE_MONOTONICITY_STATUS=STOP_FROZEN_SCORE_MISSING")
    if not (ledger["head"].eq(head).all() and (ledger.selected == (ledger.probability >= ledger.frozen_threshold)).all()):
        raise AuditStop("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")


def read_frozen() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    lineage = json.loads((P2 / "R28_PHASE2_LINEAGE.json").read_text(encoding="utf-8"))
    frozen = []
    for head in ("UP", "DOWN"):
        path = LEDGERS / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
        if sha256(path) != lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head]:
            raise AuditStop("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")
        ledger = pd.read_parquet(path)
        validate_frozen_scores(ledger, head)
        frozen.append(ledger)
    signals = pd.concat(frozen, ignore_index=True)
    signals["timestamp"] = pd.to_datetime(signals.decision_timestamp_utc, utc=True)
    assert_no_prospective(signals.timestamp)
    payoff = pd.read_parquet(PAYOFF)
    payoff["outcome_key"] = payoff.candidate_instrument.astype(str) + "|" + pd.to_datetime(payoff.decision_timestamp_et, utc=True).astype(str)
    if payoff.outcome_key.duplicated().any() or payoff.execution_contract_hash.nunique() != 1:
        raise AuditStop("STOP_FROZEN_PAYOFF_CONTRACT_AMBIGUOUS")
    signals["outcome_key"] = signals.underlying_symbol.astype(str) + "|" + signals.timestamp.astype(str)
    all_rows = signals.merge(payoff, on="outcome_key", how="left", suffixes=("_signal", "_payoff"), validate="many_to_one")
    all_rows.rename(columns={"candidate_id_signal": "candidate_id"}, inplace=True)
    if all_rows.payoff_row_hash.isna().any():
        raise AuditStop("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")
    identity = {"lineage_sha256": sha256(P2 / "R28_PHASE2_LINEAGE.json"), "payoff_sha256": sha256(PAYOFF),
                "execution_contract_sha256": str(payoff.execution_contract_hash.iloc[0]), "execution_completion_sha256": sha256(COMPLETION)}
    assert_identity(identity)
    return add_calendar_columns(all_rows), payoff, identity


def add_economics(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    up = out["head"].eq("UP")
    for target, suffix in (("valid", "payoff_valid"), ("gross", "action_gross_return"),
                           ("net10", "action_net_return_10bps"), ("net20", "action_net_return_20bps"),
                           ("exit", "actual_exit_timestamp_et"), ("outcome_path", "path_hash")):
        out[target] = np.where(up, out[f"up_{suffix}"], out[f"down_{suffix}"])
    out["valid"] = out.valid.astype(bool)
    out["exit"] = pd.to_datetime(out.exit, utc=True)
    return out


def execute(raw: pd.DataFrame) -> pd.DataFrame:
    """The frozen simultaneous-tie and one-global-position contract."""
    x = add_economics(raw)
    both = x.groupby(["underlying_symbol", "timestamp"])["head"].transform("nunique").gt(1)
    x = x.loc[~both].copy()
    tied = x.groupby("timestamp").size().reindex(x.timestamp).to_numpy() > 1
    x = x.loc[~tied].sort_values("timestamp", kind="mergesort")
    kept, until = [], None
    for index, row in x.iterrows():
        if not row.valid or pd.isna(row.exit) or (until is not None and row.timestamp < until):
            continue
        kept.append(index)
        until = row.exit
    return x.loc[kept].reset_index(drop=True)


def frozen_nyse_holidays() -> set[date]:
    """The R26A2 frozen full-closure calendar, including its one special date."""
    class Calendar(AbstractHolidayCalendar):
        rules = [Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday), USMartinLutherKingJr,
                 USPresidentsDay, GoodFriday, USMemorialDay,
                 Holiday("Juneteenth", month=6, day=19, observance=nearest_workday, start_date="2022-01-01"),
                 Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday), USLaborDay,
                 USThanksgivingDay, Holiday("Christmas", month=12, day=25, observance=nearest_workday)]
    return {item.date() for item in Calendar().holidays(start="2019-12-01", end="2025-02-02")}.union({date(2018, 12, 5)})


def shifted(selected: pd.DataFrame, payoff: pd.DataFrame, offset: int) -> pd.DataFrame:
    lookup = set(payoff.outcome_key)
    holidays = frozen_nyse_holidays()
    local = selected.timestamp.dt.tz_convert("America/New_York")
    day_map, step = {}, 1 if offset > 0 else -1
    for original in pd.unique(local.dt.date):
        day = original
        for _ in range(abs(offset)):
            day += timedelta(days=step)
            while day.weekday() >= 5 or day in holidays:
                day += timedelta(days=step)
        day_map[original] = day
    shifted_local = pd.to_datetime([f"{day_map[day]} {time}" for day, time in zip(local.dt.date, local.dt.time)]).tz_localize("America/New_York")
    keys = selected.underlying_symbol.astype(str) + "|" + shifted_local.tz_convert("UTC").astype(str)
    mapped = keys.isin(lookup).to_numpy()
    output = selected.loc[mapped].copy().reset_index(drop=True)
    output = output.drop(columns=[c for c in payoff.columns if c in output and c != "outcome_key"], errors="ignore")
    output = output.drop(columns="outcome_key", errors="ignore")
    output["outcome_key"] = keys.loc[mapped].to_numpy()
    output = output.merge(payoff, on="outcome_key", how="left", validate="many_to_one")
    output["timestamp"] = pd.to_datetime(output.decision_timestamp_et, utc=True)
    return add_calendar_columns(output)


def validate_baseline(real: pd.DataFrame, reverse: pd.DataFrame, shifts: dict) -> None:
    observed = {"trade_count": len(real), "win_rate": stats(real)["win_rate"], "mean_net20": stats(real)["mean_net20"],
                "reverse": stats(reverse)["mean_net20"], **{name: stats(value)["mean_net20"] for name, value in shifts.items()}}
    if any(not np.isclose(observed[key], expected, rtol=0, atol=1e-15) for key, expected in BASELINE.items()):
        raise AuditStop("FAST3_R28_3A_STATUS=STOPPED_BASELINE_REPRODUCTION_FAILURE")


def by_symbol(experiments: dict, selected: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for name, frame in experiments.items():
        total = len(frame)
        for symbol, part in frame.groupby("underlying_symbol", sort=True):
            row = {"experiment": name, "symbol": symbol, **stats(part), "trade_share": float(len(part) / total)}
            rows.append(row)
    table = pd.DataFrame(rows)
    top_symbol = selected.underlying_symbol.value_counts(normalize=True).index[0]
    real = table.loc[(table.experiment == "REAL") & (table.symbol == top_symbol)].iloc[0]
    return table, {"top_symbol": str(top_symbol), "top_symbol_share": float((selected.underlying_symbol == top_symbol).mean()),
                   "top_symbol_real_net20": float(real.mean_net20),
                   "top_symbol_reverse_net20": float(table.loc[(table.experiment == "REVERSE") & (table.symbol == top_symbol), "mean_net20"].iloc[0]),
                   "top_symbol_plus2_net20": float(table.loc[(table.experiment == "SHIFT_PLUS2") & (table.symbol == top_symbol), "mean_net20"].iloc[0])}


def leave_one_out(real: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    overall = stats(real)
    rows = []
    for symbol in sorted(real.underlying_symbol.unique()):
        remaining = real.loc[real.underlying_symbol.ne(symbol)]
        rows.append({"removed_symbol": symbol, "real_net20_all": overall["mean_net20"], **stats(remaining)})
    table = pd.DataFrame(rows)
    return table, overall


def score_monotonicity(all_rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, summaries = [], {}
    for head in ("UP", "DOWN"):
        x = add_economics(all_rows.loc[all_rows["head"].eq(head)]).copy()
        x["bucket_rank"] = pd.qcut(x.probability.rank(method="first", pct=True), 10, labels=False) + 1
        base = float(x.target_first.mean())
        means = []
        for rank, part in x.groupby("bucket_rank", sort=False):
            event = float(part.target_first.mean())
            row = {"head": head, "bucket_definition": "frozen_score_decile; 10=highest", "bucket_rank": int(rank),
                   "bucket": f"DECILE_{int(rank)}", "candidate_count": int(len(part)), "selected_trade_count": int(part.selected.sum()),
                   "event_rate": event, "lift": event / base, **stats(part.loc[part.valid])}
            rows.append(row); means.append(row)
        b = pd.DataFrame(means).sort_values("bucket_rank")
        raw = x.loc[x.valid, ["probability", "net20"]].corr(method="spearman").iloc[0, 1]
        summaries[head] = {"bucket_definition": "frozen_score_decile; 10=highest", "spearman_bucket_rank_event_rate": float(b[["bucket_rank", "event_rate"]].corr(method="spearman").iloc[0, 1]),
                           "spearman_bucket_rank_mean_net20": float(b[["bucket_rank", "mean_net20"]].corr(method="spearman").iloc[0, 1]),
                           "spearman_frozen_score_realized_net20": float(raw)}
    return pd.DataFrame(rows).sort_values(["head", "bucket_rank"], ascending=[True, False]), summaries


def plus2_attribution(real: pd.DataFrame, plus2: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for dimension in ("underlying_symbol", "head", "calendar_month", "weekday", "session"):
        for experiment, frame in (("REAL", real), ("SHIFT_PLUS2", plus2)):
            denominator = len(frame)
            for group, part in frame.groupby(dimension, dropna=False, sort=True):
                row = {"dimension": dimension, "group": str(group), "experiment": experiment, **stats(part)}
                row["mean_net20_contribution"] = row["total_net20_contribution"] / denominator
                rows.append(row)
    table = pd.DataFrame(rows)
    compare = table.pivot(index=["dimension", "group"], columns="experiment", values="mean_net20_contribution").fillna(0).reset_index()
    compare["plus2_minus_real_net20_contribution"] = compare["SHIFT_PLUS2"] - compare["REAL"]
    delta = stats(plus2)["mean_net20"] - stats(real)["mean_net20"]
    concentration = compare.assign(abs_contribution=lambda x: x.plus2_minus_real_net20_contribution.abs()).groupby("dimension").abs_contribution.max().div(abs(delta) if delta else 1).to_dict()
    top = max(concentration, key=concentration.get)
    concentrated = [name for name, value in concentration.items() if value >= .70]
    if abs(delta) < 1e-12: classification = "F_UNRESOLVED"
    elif len(concentrated) > 1: classification = "E_MIXED"
    elif concentration.get("underlying_symbol", 0) >= .70: classification = "B_SYMBOL_CONCENTRATED"
    elif concentration.get("calendar_month", 0) >= .70 or concentration.get("weekday", 0) >= .70: classification = "C_WEEKDAY_OR_CALENDAR_EFFECT"
    elif concentration.get("session", 0) >= .70: classification = "D_SESSION_EFFECT"
    else: classification = "A_BROAD_EFFECT"
    return table, {"plus2_minus_real_net20": float(delta), "dimension_max_abs_contribution_share": concentration,
                   "largest_dimension": top, "classification": classification,
                   "reconciliation": float(compare.plus2_minus_real_net20_contribution.sum() / 5)}


def match_plan(real: pd.DataFrame, eligible: pd.DataFrame) -> list[tuple[np.ndarray, int, int]]:
    source = real.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    remaining = source.copy()
    plan = []
    for level, fields in enumerate(LEVELS):
        pools = {key: group.index.to_numpy() for key, group in eligible.groupby(fields, sort=False)}
        deferred = []
        for key, group in remaining.groupby(fields, sort=False):
            pool = pools.get(key, np.array([], dtype=int))
            if len(pool) >= len(group):
                plan.append((pool, len(group), level))
            else:
                deferred.append(group)
        remaining = pd.concat(deferred, ignore_index=True) if deferred else remaining.iloc[0:0]
        if remaining.empty:
            break
    if len(remaining):
        return []
    return plan


def matched_once(real: pd.DataFrame, eligible: pd.DataFrame, rng: np.random.Generator,
                 plan: list[tuple[np.ndarray, int, int]] | None = None) -> tuple[pd.DataFrame, list[int]]:
    plan = match_plan(real, eligible) if plan is None else plan
    if not plan or sum(count for _, count, _ in plan) != len(real):
        return eligible.iloc[0:0].copy(), []
    selected, levels = [], []
    for pool, count, level in plan:
        selected.extend(rng.choice(pool, size=count, replace=False).tolist())
        levels.extend([level] * count)
    output = eligible.loc[selected].copy().reset_index(drop=True)
    output["match_level"] = levels
    return output, levels


def matched_placebo(real: pd.DataFrame, all_rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    eligible = add_economics(all_rows)
    eligible = eligible.loc[eligible.valid].reset_index(drop=True)
    rng, records, fixed_levels = np.random.default_rng(SEED), [], None
    plan = match_plan(real, eligible)
    for run in range(RUNS):
        sampled, levels = matched_once(real, eligible, rng, plan)
        if len(sampled) != len(real):
            raise AuditStop("STOP_MATCHED_PLACEBO_UNMATCHED")
        if fixed_levels is None: fixed_levels = levels
        paths = sampled.outcome_path.value_counts(dropna=False)
        records.append({"run": run + 1, "trade_count": int(len(sampled)), "signal_cardinality_conserved": bool(len(sampled) == len(real)),
                        "unique_placebo_signal_count": int(sampled.candidate_id.nunique()), "unique_outcome_path_count": int(paths.size),
                        "shared_outcome_path_count": int((paths > 1).sum()), "max_signals_per_outcome_path": int(paths.max()), **stats(sampled)})
    table = pd.DataFrame(records)
    actual = stats(real)
    net, win = table.mean_net20.to_numpy(), table.win_rate.to_numpy()
    level_counts = {f"match_level_{level}_count": int(sum(value == level for value in fixed_levels)) for level in range(5)}
    summary = {"random_seed": SEED, "random_run_count": RUNS, "judgment_rule": MATCHED_RULE, **level_counts,
               "unmatched_count": 0, "unmatched_rate": 0.0, "signal_cardinality_conserved": bool(table.signal_cardinality_conserved.all()),
               "win_rate_median": q(win, .5), "win_rate_p90": q(win, .9), "win_rate_p95": q(win, .95), "win_rate_p99": q(win, .99), "win_rate_max": float(win.max()),
               "net20_median": q(net, .5), "net20_p90": q(net, .9), "net20_p95": q(net, .95), "net20_p99": q(net, .99), "net20_max": float(net.max()),
               "real_win_rate_percentile": float((win <= actual["win_rate"]).mean()), "real_net20_percentile": float((net <= actual["mean_net20"]).mean()),
               "win_rate_p": empirical_p(win, actual["win_rate"]), "net20_p": empirical_p(net, actual["mean_net20"]),
               "shared_outcome_path_count": int(table.shared_outcome_path_count.max()), "max_signals_per_outcome_path": int(table.max_signals_per_outcome_path.max())}
    return table, summary


def final_classification(symbol: dict, leave: pd.DataFrame, overall: dict, score: dict, plus2: dict, matched: dict) -> tuple[str, str, str]:
    all_net = float(leave.real_net20_all.iloc[0])
    ex_top = float(leave.loc[leave.removed_symbol.eq(symbol["top_symbol"]), "mean_net20"].iloc[0])
    remaining_count = int(leave.loc[leave.removed_symbol.eq(symbol["top_symbol"]), "trade_count"].iloc[0])
    contribution_share = 1 - (ex_top * remaining_count) / (all_net * overall["trade_count"])
    high = ex_top <= 0 or ex_top <= .25 * all_net or contribution_share > .50
    predictive = all(value["spearman_bucket_rank_event_rate"] > 0 for value in score.values())
    if matched["real_net20_percentile"] >= .99 and matched["net20_p"] <= .01: economic = "MATCHED_PLACEBO_VERY_STRONG_PASS"
    elif matched["real_net20_percentile"] >= .95 and matched["net20_p"] <= .05: economic = "MATCHED_PLACEBO_STRONG_PASS"
    elif matched["real_net20_percentile"] < .90 or matched["net20_p"] > .10: economic = "MATCHED_PLACEBO_FAIL"
    else: economic = "WEAK_OR_MIXED"
    if economic.endswith("PASS"): classification = "B_ECONOMIC_EDGE_PRESENT_BUT_CONCENTRATED" if high else "A_STRONG_ECONOMIC_SELECTION_EDGE_CONFIRMED"
    elif predictive: classification = "C_PREDICTIVE_EDGE_CONFIRMED_ECONOMIC_SELECTION_EDGE_WEAK_OR_MIXED"
    else: classification = "D_ECONOMIC_EDGE_NOT_DISTINGUISHABLE_FROM_MATCHED_RANDOM"
    return classification, ("HIGH" if high else "LOW"), ("PREDICTIVE_EDGE_CONFIRMED" if predictive else "PREDICTIVE_EDGE_NOT_CONFIRMED"), economic


def run() -> dict:
    all_rows, payoff, identity = read_frozen()
    selected = all_rows.loc[all_rows.selected].copy()
    real = execute(selected)
    reverse = execute(selected.assign(head=selected["head"].map({"UP": "DOWN", "DOWN": "UP"})))
    shifts = {"SHIFT_MINUS1": execute(shifted(selected, payoff, -1)), "SHIFT_PLUS1": execute(shifted(selected, payoff, 1)), "SHIFT_PLUS2": execute(shifted(selected, payoff, 2))}
    validate_baseline(real, reverse, {"reverse": reverse, "minus1": shifts["SHIFT_MINUS1"], "plus1": shifts["SHIFT_PLUS1"], "plus2": shifts["SHIFT_PLUS2"]})
    experiments = {"REAL": real, "REVERSE": reverse, **shifts}
    symbol_table, symbol = by_symbol(experiments, selected)
    leave, overall = leave_one_out(real)
    score_table, score = score_monotonicity(all_rows)
    plus2_table, plus2 = plus2_attribution(real, shifts["SHIFT_PLUS2"])
    runs, matched = matched_placebo(real, all_rows)
    classification, dependence, predictive, economic = final_classification(symbol, leave, overall, score, plus2, matched)
    if OUT.exists():
        raise AuditStop("STOP_R28_3A_OUTPUT_PATH_EXISTS")
    OUT.mkdir(parents=True)
    symbol_table.to_csv(OUT / "R28_3A_SYMBOL_ATTRIBUTION.csv", index=False)
    score_table.to_csv(OUT / "R28_3A_SCORE_ECONOMIC_MONOTONICITY.csv", index=False)
    plus2_table.to_csv(OUT / "R28_3A_PLUS2_ATTRIBUTION.csv", index=False)
    runs.to_csv(OUT / "R28_3A_MATCHED_PLACEBO_RUNS.csv", index=False)
    payload = {"status": "PASS", "classification": classification, "identity": identity, "baseline_reproduction_pass": True,
               "constraints": {"model_retrain_count": 0, "model_refit": False, "feature_changes": False, "prospective_data_used": False, "post_freeze_rescoring_count": 0, "data_root_write_count": 0, "live_trading_allowed": False},
               "real": stats(real), "reverse": stats(reverse), "shifts": {name: stats(frame) for name, frame in shifts.items()},
               "symbol": {**symbol, "leave_one_out": leave.to_dict(orient="records"), "single_symbol_dependence": dependence}, "score": score,
               "plus2": plus2, "matched_placebo": matched, "predictive_edge_status": predictive, "economic_selection_edge_status": economic,
               "r29_allowed_to_resume": False, "live_trading_allowed": False}
    (OUT / "R28_3A_SYMBOL_ATTRIBUTION.json").write_text(json.dumps({"top_symbol": symbol, "leave_one_out": leave.to_dict(orient="records")}, indent=2), encoding="utf-8")
    (OUT / "R28_3A_SCORE_ECONOMIC_MONOTONICITY.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
    (OUT / "R28_3A_PLUS2_ATTRIBUTION.json").write_text(json.dumps(plus2, indent=2), encoding="utf-8")
    (OUT / "R28_3A_MATCHED_PLACEBO_SUMMARY.json").write_text(json.dumps(matched, indent=2), encoding="utf-8")
    (OUT / "R28_3A_SUMMARY.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "R28_3A_REPORT.md").write_text("# FAST3 R28.3A Frozen Economic Attribution\n\n" + json.dumps(payload, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2))
    except AuditStop as exc:
        print(str(exc))
        raise SystemExit(2)
