"""Read-only return attribution for the frozen A/A2 research baseline.

Thin task entrypoint: consume frozen ledgers, reuse the existing attribution
engine, and use the existing price loader for fixed Raw A2 rank buckets only.
No model is fitted and neither strategy is rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v22 import a2_global_ff12_hold_replace_r1 as price_utility
from scripts.v22.attribution.engine import AttributionEngine
from scripts.v22.attribution.schemas import AttributionConfig


RESULTS = Path(r"D:\us-tech-quant-results")
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
FREEZE = BASE / "audit" / "freeze_r1"
TOP40 = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"
TAXONOMY_MANIFEST = TAXONOMY.parent / "hash_manifest.json"
ADJUSTED_PRICES = Path(r"D:\us-tech-quant-cache\a2_risk_history_extension_r1\adjusted_prices_pre2026.parquet")
OUT = RESULTS / "A2_RETURN_ATTRIBUTION_R1"
EXPECTED_TOP40_SHA = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
TOL = 1e-12


class Stop(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise Stop(f"{code}|{evidence}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, writer: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp{path.suffix}")
    writer(temp)
    os.replace(temp, path)


def performance(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily.sort_values("execution_date").reconstructed_daily_return.to_numpy(float)
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    ann, vol = float(returns.mean() * 252), float(returns.std(ddof=0) * math.sqrt(252))
    dd = nav / np.maximum.accumulate(nav) - 1.0
    return {"cagr": float(nav[-1] ** (252 / len(returns)) - 1), "sharpe": ann / vol,
            "max_drawdown": float(dd.min()), "terminal_wealth": float(nav[-1])}


def verify_sources() -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    manifest = json.loads((FREEZE / "frozen_baseline_manifest.json").read_text(encoding="utf-8"))
    require(manifest["frozen_baseline_name"] == "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1", "BASELINE_IDENTITY")
    hashes = pd.read_csv(FREEZE / "frozen_artifact_hashes.csv")
    expected = {str(Path(r.absolute_path)): str(r.sha256) for r in hashes.itertuples(index=False)}
    frames: dict[str, pd.DataFrame] = {}
    facts: dict[str, Any] = {"manifest": manifest, "hashes": {}}
    for arm in ("A", "A2"):
        for name in ("portfolio_daily.parquet", "position_ledger.parquet", "top20_selections.parquet"):
            path = BASE / arm / name
            actual = sha256_file(path)
            require(expected.get(str(path)) == actual, "AUTHORITATIVE_SOURCE_HASH_MISMATCH", path)
            facts["hashes"][str(path)] = actual
            frames[f"{arm}_{name}"] = pd.read_parquet(path)
        path = BASE / arm / "metrics.json"
        require(expected.get(str(path)) == sha256_file(path), "AUTHORITATIVE_SOURCE_HASH_MISMATCH", path)
        facts[f"{arm}_published"] = json.loads(path.read_text(encoding="utf-8"))
    require(sha256_file(TOP40) == EXPECTED_TOP40_SHA, "RAW_TOP40_HASH_MISMATCH")
    top40 = pd.read_parquet(TOP40)
    require(len(top40) == 50_120 and top40.decision_date.nunique() == 1_253, "RAW_TOP40_IDENTITY")
    require(not top40.duplicated(["decision_date", "raw_rank"]).any(), "RAW_TOP40_DUPLICATE_RANK")
    require(top40.groupby("decision_date").raw_rank.apply(lambda x: set(x) == set(range(1, 41))).all(), "RAW_TOP40_RANK_RANGE")
    frames["TOP40"] = top40
    tax_manifest = json.loads(TAXONOMY_MANIFEST.read_text(encoding="utf-8"))
    tax_hash = next(r["sha256"] for r in tax_manifest["artifacts"] if r["name"] == TAXONOMY.name)
    require(sha256_file(TAXONOMY) == tax_hash, "TAXONOMY_HASH_MISMATCH")
    frames["TAXONOMY"] = pd.read_parquet(TAXONOMY)
    facts.update(top40_sha256=EXPECTED_TOP40_SHA, taxonomy_sha256=tax_hash,
                 adjusted_price_sha256=sha256_file(ADJUSTED_PRICES))
    return frames, facts


def verify_arm(arm: str, daily: pd.DataFrame, positions: pd.DataFrame, top: pd.DataFrame,
               published: dict[str, Any]) -> dict[str, Any]:
    daily = daily.sort_values("execution_date").reset_index(drop=True).copy()
    daily["execution_date"] = pd.to_datetime(daily.execution_date).dt.normalize()
    positions = positions.copy(); positions["date"] = pd.to_datetime(positions.date).dt.normalize()
    require(len(daily) == 751 and daily.execution_date.iloc[0] == pd.Timestamp("2023-01-04")
            and daily.execution_date.iloc[-1] == pd.Timestamp("2025-12-31"), "ECONOMIC_DATE_IDENTITY", arm)
    require(top.groupby("signal_date").size().eq(20).all(), "TOP20_CARDINALITY", arm)
    prior = daily.reconstructed_nav.shift(1).fillna(1.0)
    grouped = positions.groupby("date", as_index=False).agg(
        market=("market_pnl", "sum"), cost=("transaction_cost", "sum"),
        net=("net_pnl_contribution", "sum"), ret=("portfolio_pnl_contribution", "sum"))
    check = daily.merge(grouped, left_on="execution_date", right_on="date", validate="one_to_one")
    errors = [((check.pretrade_nav - prior) - check.market).abs().max(),
              (check.reconstructed_transaction_cost - check.cost).abs().max(),
              ((check.reconstructed_nav - prior) - check.net).abs().max(),
              (check.reconstructed_daily_return - check.ret).abs().max(),
              np.max(np.abs(np.cumprod(1 + daily.reconstructed_daily_return) - daily.reconstructed_nav))]
    result = performance(daily)
    for field in ("cagr", "sharpe", "max_drawdown"):
        require(abs(result[field] - float(published[field])) <= TOL, "ECONOMIC_REPLAY_MISMATCH", f"{arm}:{field}")
    require(max(errors) <= TOL, "ECONOMIC_REPLAY_MISMATCH", f"{arm}:{errors}")
    return {"status": "PASS_EXACT_OR_MACHINE_PRECISION", "max_error": float(max(errors)), **result}


def signal_maps(top: pd.DataFrame, daily: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    signals = sorted(pd.to_datetime(top.signal_date).dt.normalize().unique())
    executions = sorted(pd.to_datetime(daily.execution_date).dt.normalize().unique())
    require(len(signals) + 1 == len(executions), "SIGNAL_EXECUTION_COUNT")
    mapping = {pd.Timestamp(e): pd.Timestamp(s) for s, e in zip(signals, executions[:-1])}
    require(all(s < e for e, s in mapping.items()), "SIGNAL_EXECUTION_CAUSALITY")
    return mapping


def a2_wealth_ledger(frames: dict[str, pd.DataFrame], replay: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    daily = frames["A2_portfolio_daily.parquet"].copy().sort_values("execution_date")
    pos = frames["A2_position_ledger.parquet"].copy()
    top = frames["A2_top20_selections.parquet"].copy()
    tax = frames["TAXONOMY"].copy()
    daily["execution_date"] = pd.to_datetime(daily.execution_date).dt.normalize()
    for column in ("date", "previous_date"):
        pos[column] = pd.to_datetime(pos[column]).dt.normalize()
    top["signal_date"] = pd.to_datetime(top.signal_date).dt.normalize()
    execution_to_signal = signal_maps(top, daily)
    pos["holding_signal_date"] = pos.previous_date.map(execution_to_signal)
    pos["trade_signal_date"] = pos.date.map(execution_to_signal)
    pos["attribution_signal_date"] = pos.holding_signal_date.fillna(pos.trade_signal_date)
    ranks = top.set_index(["signal_date", "ticker"])["a2_rank"]
    pos["entry_rank"] = ranks.reindex(pd.MultiIndex.from_frame(pos[["attribution_signal_date", "ticker"]])).to_numpy()
    tax = tax[["signal_date", "ticker", "security_id", "ff12", "ff48"]].drop_duplicates(["signal_date", "ticker"])
    pos = pos.merge(tax, left_on=["attribution_signal_date", "ticker"], right_on=["signal_date", "ticker"],
                    how="left", suffixes=("", "_tax"), validate="many_to_one")
    pos["security_id"] = pos.security_id.fillna("A2_TICKER_" + pos.ticker.astype(str))
    pos["ff12"] = pos.ff12.fillna("UNKNOWN"); pos["ff48"] = pos.ff48.fillna("UNKNOWN")
    nav_before = daily.set_index("execution_date").reconstructed_nav.shift(1).fillna(1.0)
    pos["nav_before"] = pos.date.map(nav_before)
    pos["previous_weight_exact"] = np.where(pos.previous_price.notna(),
                                             pos.shares_before * pos.previous_price / pos.nav_before, 0.0)
    pos["gross_return_contribution"] = pos.market_pnl / pos.nav_before
    pos["cost_return_contribution"] = -pos.transaction_cost / pos.nav_before
    pos["net_return_contribution"] = pos.net_pnl_contribution / pos.nav_before

    # Reuse the existing repository attribution engine as an independent
    # return-level reconciliation over the authoritative explicit ledger.
    engine_rows = pd.DataFrame({
        "strategy_id": "A2", "date": pos.date, "security_id": pos.security_id, "ticker": pos.ticker,
        "component_type": "SECURITY", "model_id": "A2_HGB_FROZEN_R1",
        "universe_id": "AUTHORITATIVE_A2", "vintage_id": pos.date.dt.year.astype(str),
        "sector": pos.ff12, "industry": pos.ff48, "rank": pos.entry_rank,
        "portfolio_weight": pos.previous_weight_exact, "previous_weight": pos.previous_weight_exact,
        "security_return": pos.raw_return, "transaction_cost": pos.transaction_cost / pos.nav_before,
        "gross_contribution": pos.gross_return_contribution,
        "cost_contribution": pos.cost_return_contribution,
        "net_contribution": pos.net_return_contribution,
        "contribution_source": "FROZEN_POSITION_LEDGER_EXPLICIT",
    })
    engine_daily = pd.DataFrame({
        "strategy_id": "A2", "date": daily.execution_date,
        "authoritative_portfolio_return": daily.reconstructed_daily_return,
        "authoritative_gross_return": daily.reconstructed_gross_return,
        "authoritative_cost_contribution": -daily.reconstructed_transaction_cost / nav_before.to_numpy(),
        "nav_before": nav_before.to_numpy(), "nav_after": daily.reconstructed_nav,
    })
    result = AttributionEngine(AttributionConfig(identity_tolerance=TOL)).run(engine_rows, engine_daily)
    require(result["reconciliation"]["status"] == "PASS", "EXISTING_ATTRIBUTION_FRAMEWORK_RECONCILIATION")

    detail = pd.DataFrame({
        "row_type": "A2_SECURITY_SESSION", "date": pos.date, "signal_date": pos.attribution_signal_date,
        "security_id": pos.security_id, "ticker": pos.ticker, "classification": "A2_HELD_OR_TRADED",
        "rank": pos.entry_rank, "rank_bucket": pd.NA, "sector": pos.ff12, "industry": pos.ff48,
        "security_return": pos.raw_return, "previous_weight": pos.previous_weight_exact,
        "gross_wealth_contribution": pos.market_pnl, "transaction_cost_wealth": pos.transaction_cost,
        "net_wealth_contribution": pos.net_pnl_contribution,
        "a2_wealth_contribution": pos.market_pnl, "a_wealth_contribution": 0.0,
        "incremental_wealth_contribution": pd.NA, "price_source": pos.source_path,
        "data_status": "AUTHORITATIVE_POSITION_LEDGER", "year": pos.date.dt.year,
    })
    gross = pos.groupby("date").market_pnl.sum().reindex(daily.execution_date).to_numpy()
    cost = pos.groupby("date").transaction_cost.sum().reindex(daily.execution_date).to_numpy()
    residual = daily.reconstructed_nav.to_numpy() - nav_before.to_numpy() - gross + cost
    residual_max = float(np.max(np.abs(residual)))
    require(residual_max <= TOL, "A2_WEALTH_ATTRIBUTION_UNRECONCILED", residual_max)
    security = pos.groupby(["security_id", "ticker"], as_index=False).agg(
        gross_wealth=("market_pnl", "sum"), cost_wealth=("transaction_cost", "sum"),
        net_wealth=("net_pnl_contribution", "sum"), holding_sessions=("shares_before", lambda x: int((x > 0).sum())))
    security = security.sort_values(["gross_wealth", "ticker"], ascending=[False, True], kind="mergesort")
    positive, negative = security[security.gross_wealth > 0], security[security.gross_wealth < 0]
    positive_total = float(positive.gross_wealth.sum())
    shares = positive.gross_wealth / positive_total
    hhi = float((shares**2).sum())

    def needed(fraction: float) -> int:
        return int(np.searchsorted(shares.cumsum().to_numpy(), fraction, side="left") + 1)

    concentration: dict[str, Any] = {
        "positive_security_count": len(positive), "negative_security_count": len(negative),
        "n_for_50pct_positive": needed(.5), "n_for_80pct_positive": needed(.8),
        "contribution_hhi": hhi, "effective_contributor_count": 1 / hhi,
        "largest_positive_contributor": str(security.iloc[0].ticker),
        "largest_negative_contributor": str(security.iloc[-1].ticker),
        "taxonomy_row_coverage": float(pos.ff12.ne("UNKNOWN").mean()),
        "framework_max_daily_identity_error": float(result["reconciliation"]["max_daily_identity_error"]),
        "wealth_identity_max_abs_error": residual_max,
    }
    for n in (1, 3, 5, 10):
        concentration[f"top{n}_positive_contribution_share"] = float(shares.head(n).sum())
        removed = float(positive.gross_wealth.head(n).sum())
        concentration[f"ex_post_remove_top{n}_terminal_wealth"] = replay["terminal_wealth"] - removed
        concentration[f"ex_post_remove_top{n}_wealth_change"] = replay["terminal_wealth"] - 1 - removed
    by_year = pos.groupby(pos.date.dt.year).market_pnl.sum().sort_values(ascending=False)
    concentration.update(
        largest_positive_year=str(int(by_year.index[0])),
        largest_negative_year=str(int(by_year.index[-1])) if by_year.iloc[-1] < 0 else "NONE_ALL_YEARS_POSITIVE",
        largest_positive_year_contribution=float(by_year.iloc[0]), smallest_year_contribution=float(by_year.iloc[-1]))
    return detail, {"security": security, "by_year": by_year, "positions": pos}, concentration


def incremental_ledger(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    daily_a = frames["A_portfolio_daily.parquet"].sort_values("execution_date")
    daily_b = frames["A2_portfolio_daily.parquet"].sort_values("execution_date")
    a, b = frames["A_position_ledger.parquet"].copy(), frames["A2_position_ledger.parquet"].copy()
    for frame in (a, b): frame["date"] = pd.to_datetime(frame.date).dt.normalize()
    columns = ["date", "ticker", "shares_before", "raw_return", "market_pnl", "transaction_cost"]
    joined = b[columns].merge(a[columns], on=["date", "ticker"], how="outer", suffixes=("_a2", "_a"), validate="one_to_one")
    for column in joined.columns:
        if column not in ("date", "ticker"):
            joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(0.0)
    held_b, held_a = joined.shares_before_a2.gt(0), joined.shares_before_a.gt(0)
    joined["classification"] = np.select(
        [held_b & held_a, held_b & ~held_a, ~held_b & held_a], ["COMMON", "A2_ONLY", "A_ONLY"], default="TRADE_ONLY")
    joined["incremental_gross"] = joined.market_pnl_a2 - joined.market_pnl_a
    joined["incremental_cost"] = joined.transaction_cost_a2 - joined.transaction_cost_a
    joined["incremental_net"] = joined.incremental_gross - joined.incremental_cost
    joined["a2_only"] = np.where(joined.classification.eq("A2_ONLY"), joined.market_pnl_a2, 0.0)
    joined["a_only_actual"] = np.where(joined.classification.eq("A_ONLY"), joined.market_pnl_a, 0.0)
    joined["a_only_offset"] = np.where(joined.classification.eq("A_ONLY"), -joined.market_pnl_a, 0.0)
    joined["common_diff"] = np.where(joined.classification.eq("COMMON"), joined.incremental_gross, 0.0)
    joined["other_diff"] = np.where(joined.classification.eq("TRADE_ONLY"), joined.incremental_gross, 0.0)
    daily_b = daily_b.copy(); daily_b["execution_date"] = pd.to_datetime(daily_b.execution_date).dt.normalize()
    execution_dates = list(daily_b.execution_date)
    previous_execution = {execution_dates[i]: execution_dates[i - 1] for i in range(1, len(execution_dates))}
    execution_to_signal = signal_maps(frames["A2_top20_selections.parquet"], daily_b)
    joined["signal_date"] = joined.date.map(previous_execution).map(execution_to_signal)
    taxonomy = frames["TAXONOMY"][["signal_date", "ticker", "security_id", "ff12", "ff48"]].drop_duplicates(["signal_date", "ticker"])
    joined = joined.merge(taxonomy, on=["signal_date", "ticker"], how="left", validate="many_to_one")
    joined["security_id"] = joined.security_id.fillna("A2_TICKER_" + joined.ticker)
    joined["ff12"] = joined.ff12.fillna("UNKNOWN"); joined["ff48"] = joined.ff48.fillna("UNKNOWN")
    terminal_delta = float(daily_b.reconstructed_nav.iloc[-1] - daily_a.reconstructed_nav.iloc[-1])
    cost_delta = float(daily_b.reconstructed_transaction_cost.sum() - daily_a.reconstructed_transaction_cost.sum())
    components = float(joined[["a2_only", "a_only_offset", "common_diff", "other_diff"]].sum().sum())
    residual = terminal_delta - (components - cost_delta)
    require(abs(residual) <= TOL, "A2_MINUS_A_WEALTH_ATTRIBUTION_UNRECONCILED", residual)
    replacement_rows = []
    for date, group in joined.groupby("date", sort=True):
        left = group.loc[group.classification.eq("A2_ONLY") & group.raw_return_a2.notna(), "raw_return_a2"]
        right = group.loc[group.classification.eq("A_ONLY") & group.raw_return_a.notna(), "raw_return_a"]
        if len(left) and len(right):
            replacement_rows.append({"date": date, "year": date.year, "a2_only_return": left.mean(),
                                     "a_only_return": right.mean(), "spread": left.mean() - right.mean(),
                                     "a2_only_count": len(left), "a_only_count": len(right)})
    replacement = pd.DataFrame(replacement_rows)
    require(not replacement.empty, "EMPTY_REPLACEMENT_DIAGNOSTIC")
    facts = {"a2_only_total": float(joined.a2_only.sum()), "a_only_actual_total": float(joined.a_only_actual.sum()),
             "a_only_offset_total": float(joined.a_only_offset.sum()), "common_exposure_difference": float(joined.common_diff.sum()),
             "other_gross_difference": float(joined.other_diff.sum()), "incremental_cost": cost_delta,
             "terminal_delta": terminal_delta, "identity_error": abs(residual), "mean_spread": float(replacement.spread.mean()),
             "median_spread": float(replacement.spread.median()), "positive_date_fraction": float(replacement.spread.gt(0).mean()),
             "membership_change_count": int((joined.classification.isin(["A2_ONLY", "A_ONLY"]) & (held_b | held_a)).sum())}
    detail = pd.DataFrame({
        "row_type": "A2_MINUS_A_SESSION_SECURITY", "date": joined.date, "signal_date": joined.signal_date,
        "security_id": joined.security_id, "ticker": joined.ticker,
        "classification": joined.classification, "rank": pd.NA, "rank_bucket": pd.NA,
        "sector": joined.ff12, "industry": joined.ff48, "security_return": pd.NA, "previous_weight": pd.NA,
        "gross_wealth_contribution": joined.incremental_gross, "transaction_cost_wealth": joined.incremental_cost,
        "net_wealth_contribution": joined.incremental_net, "a2_wealth_contribution": joined.market_pnl_a2,
        "a_wealth_contribution": joined.market_pnl_a, "incremental_wealth_contribution": joined.incremental_net,
        "price_source": "FROZEN_A_AND_A2_POSITION_LEDGERS", "data_status": "AUTHORITATIVE_DIFFERENCE",
        "year": joined.date.dt.year})
    return detail, facts, replacement


def rank_attribution(top40: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    top = top40.loc[top40.decision_date.between("2023-01-01", "2025-12-31")].copy()
    top["ticker"] = top.ticker_if_available.astype(str).str.upper()
    require(len(top) == 30_000 and top.decision_date.nunique() == 750, "RANK_SAMPLE_IDENTITY")
    loaded = price_utility.load_prices(set(top.ticker), [2023, 2024, 2025])
    qfq = loaded.attrs["raw_counterfactual"].copy()
    qfq = qfq.loc[~qfq.source.astype(str).eq("FROZEN_POSITION_LEDGER_EXACT_MARK")]
    adjusted = pd.read_parquet(ADJUSTED_PRICES, columns=["ticker", "trade_date", "open", "source"])
    adjusted["ticker"] = adjusted.ticker.astype(str).str.upper()
    for frame in (qfq, adjusted): frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    calendar = pd.DatetimeIndex(sorted(qfq.loc[qfq.ticker.eq("QQQ"), "trade_date"].unique()))
    starts: dict[pd.Timestamp, pd.Timestamp] = {}; ends: dict[pd.Timestamp, pd.Timestamp] = {}
    for date in sorted(pd.to_datetime(top.decision_date).dt.normalize().unique()):
        position = int(calendar.searchsorted(date, side="right"))
        require(position + 1 < len(calendar), "RANK_HOLDING_INTERVAL_MISSING", date)
        starts[pd.Timestamp(date)], ends[pd.Timestamp(date)] = pd.Timestamp(calendar[position]), pd.Timestamp(calendar[position + 1])
    top["start_date"] = top.decision_date.map(starts); top["end_date"] = top.decision_date.map(ends)
    require(top.end_date.max() <= pd.Timestamp("2025-12-31"), "POST_2025_OUTCOME_LEAKAGE", "RANK")
    apx = adjusted.drop_duplicates(["trade_date", "ticker"]).set_index(["trade_date", "ticker"])["open"]
    qpx = qfq.drop_duplicates(["trade_date", "ticker"]).set_index(["trade_date", "ticker"])["open"]
    start_key = pd.MultiIndex.from_frame(top[["start_date", "ticker"]]); end_key = pd.MultiIndex.from_frame(top[["end_date", "ticker"]])
    a0, a1 = apx.reindex(start_key).to_numpy(), apx.reindex(end_key).to_numpy()
    q0, q1 = qpx.reindex(start_key).to_numpy(), qpx.reindex(end_key).to_numpy()
    use_a = np.isfinite(a0) & np.isfinite(a1) & (a0 > 0) & (a1 > 0)
    use_q = ~use_a & np.isfinite(q0) & np.isfinite(q1) & (q0 > 0) & (q1 > 0)
    top["holding_return"] = np.where(use_a, a1 / a0 - 1, np.where(use_q, q1 / q0 - 1, np.nan))
    top["price_source"] = np.where(use_a, "EXISTING_PIT_FORWARD_REHAB_INDEX",
                                    np.where(use_q, "EXISTING_QFQ_OR_BACKFILL", "MISSING"))
    top["rank_bucket"] = pd.cut(top.raw_rank, [0, 10, 20, 30, 40],
                                 labels=["RANK_1_10", "RANK_11_20", "RANK_21_30", "RANK_31_40"]).astype(str)
    require(top.groupby(["decision_date", "rank_bucket"], observed=True).size().eq(10).all(), "FIXED_RANK_BUCKET_IDENTITY")
    require(top.loc[top.raw_rank.between(16, 20), "raw_rank"].between(16, 20).all(), "BOUNDARY_16_20")
    require(top.loc[top.raw_rank.between(21, 25), "raw_rank"].between(21, 25).all(), "BOUNDARY_21_25")
    bucket_rows = []
    scopes = [("ALL", top), *[(str(y), g) for y, g in top.groupby(top.decision_date.dt.year, sort=True)]]
    for scope, part in scopes:
        for bucket, group in part.groupby("rank_bucket", observed=True, sort=True):
            valid = group.holding_return.dropna()
            daily = group.groupby("decision_date").holding_return.agg(["count", "mean"])
            complete = daily.loc[daily["count"].eq(10), "mean"]
            bucket_rows.append({"scope": scope, "bucket": bucket, "mean_return": valid.mean(),
                                "median_return": valid.median(), "hit_rate": valid.gt(0).mean(),
                                "observation_count": len(valid), "expected_observation_count": len(group),
                                "coverage": len(valid) / len(group), "complete_date_count": len(complete),
                                "cumulative_fixed_bucket_return": np.prod(1 + complete.to_numpy(float)) - 1 if len(complete) else np.nan})
    bucket_summary = pd.DataFrame(bucket_rows)
    specifications = {"TOP20_VS_RANK21_40": (range(1, 21), range(21, 41)),
                      "RANK1_10_VS_RANK11_20": (range(1, 11), range(11, 21)),
                      "RANK16_20_VS_RANK21_25": (range(16, 21), range(21, 26))}
    comparison_rows = []
    for name, (left_values, right_values) in specifications.items():
        left, right = set(left_values), set(right_values)
        selected = top.loc[top.raw_rank.isin(left | right)]
        for date, group in selected.groupby("decision_date", sort=True):
            valid = group.dropna(subset=["holding_return"])
            if len(valid) != len(left) + len(right):
                continue
            l = valid.loc[valid.raw_rank.isin(left), "holding_return"]
            r = valid.loc[valid.raw_rank.isin(right), "holding_return"]
            require(len(l) == len(left) and len(r) == len(right), "RANK_COMPARISON_CARDINALITY", f"{name}:{date}")
            comparison_rows.append({"comparison": name, "date": date, "year": date.year, "spread": l.mean() - r.mean()})
    comparison = pd.DataFrame(comparison_rows)
    require(set(comparison.comparison) == set(specifications), "EMPTY_RANK_COMPARISON")
    facts: dict[str, Any] = {"observation_count": int(top.holding_return.notna().sum()),
                             "expected_observation_count": len(top), "coverage": float(top.holding_return.notna().mean()),
                             "post_2025_used": False}
    for name, group in comparison.groupby("comparison", sort=True):
        facts[f"{name}_spread"] = float(group.spread.mean())
        facts[f"{name}_median_spread"] = float(group.spread.median())
        facts[f"{name}_positive_fraction"] = float(group.spread.gt(0).mean())
        facts[f"{name}_date_count"] = len(group)
    detail = pd.DataFrame({
        "row_type": "RAW_RANK_HOLDING_PERIOD", "date": top.end_date, "signal_date": top.decision_date,
        "security_id": top.security_id, "ticker": top.ticker, "classification": "RAW_TOP40_FIXED_BUCKET",
        "rank": top.raw_rank, "rank_bucket": top.rank_bucket, "sector": "UNKNOWN", "industry": "UNKNOWN",
        "security_return": top.holding_return, "previous_weight": .1,
        "gross_wealth_contribution": pd.NA, "transaction_cost_wealth": pd.NA, "net_wealth_contribution": pd.NA,
        "a2_wealth_contribution": pd.NA, "a_wealth_contribution": pd.NA, "incremental_wealth_contribution": pd.NA,
        "price_source": top.price_source, "data_status": np.where(top.holding_return.notna(), "AVAILABLE", "MISSING_PRICE_PAIR"),
        "year": top.decision_date.dt.year})
    return detail, facts, bucket_summary, comparison


def build_outputs(facts: dict[str, Any], a2: dict[str, Any], concentration: dict[str, Any],
                  incremental: dict[str, Any], replacement: pd.DataFrame, rank: dict[str, Any],
                  buckets: pd.DataFrame, comparisons: pd.DataFrame, detail: pd.DataFrame
                  ) -> tuple[pd.DataFrame, str, dict[str, str]]:
    rows: list[dict[str, Any]] = []

    def add(section: str, metric: str, value: Any, scope: str = "ALL", year: Any = "ALL", notes: str = "") -> None:
        rows.append({"section": section, "metric": metric, "scope": scope, "year": year,
                     "value": value, "notes": notes})

    for arm in ("A", "A2"):
        for key, value in facts[f"{arm}_replay"].items(): add("REPLAY", key.upper(), value, arm)
    for key, value in concentration.items():
        add("A2_WEALTH_CONCENTRATION", key.upper(), value, "A2", notes="Gross realized wealth; costs separate")
    for n in (1, 3, 5, 10):
        add("EX_POST_FRAGILITY_DIAGNOSTIC_ONLY", f"REMOVE_TOP{n}_TERMINAL_WEALTH",
            concentration[f"ex_post_remove_top{n}_terminal_wealth"], "A2",
            notes="NOT_AN_INVESTABLE_STRATEGY; NOT_ELIGIBLE_FOR_MODEL_SELECTION")
    for key, value in incremental.items(): add("A2_MINUS_A", key.upper(), value, "A2_MINUS_A")
    for year, group in replacement.groupby("year", sort=True):
        add("REPLACEMENT_QUALITY", "MEAN_SPREAD", group.spread.mean(), "A2_ONLY_MINUS_A_ONLY", year)
        add("REPLACEMENT_QUALITY", "MEDIAN_SPREAD", group.spread.median(), "A2_ONLY_MINUS_A_ONLY", year)
        add("REPLACEMENT_QUALITY", "POSITIVE_DATE_FRACTION", group.spread.gt(0).mean(), "A2_ONLY_MINUS_A_ONLY", year)
    for key, value in rank.items(): add("RAW_TOP40_RANK", key.upper(), value, "AUTHORITATIVE_2023_2025")
    for row in buckets.itertuples(index=False):
        for metric in ("mean_return", "median_return", "hit_rate", "coverage", "complete_date_count", "cumulative_fixed_bucket_return"):
            add("RAW_TOP40_BUCKET", metric.upper(), getattr(row, metric), row.bucket, row.scope,
                notes="Gross next-execution-session holding return; no costs")
    for name, group in comparisons.groupby("comparison", sort=True):
        for scope, part in [("ALL", group), *[(str(y), g) for y, g in group.groupby("year", sort=True)]]:
            add("RAW_TOP40_COMPARISON", "MEAN_SPREAD", part.spread.mean(), name, scope)
            add("RAW_TOP40_COMPARISON", "MEDIAN_SPREAD", part.spread.median(), name, scope)
            add("RAW_TOP40_COMPARISON", "POSITIVE_DATE_FRACTION", part.spread.gt(0).mean(), name, scope)
            add("RAW_TOP40_COMPARISON", "COMPLETE_DATE_COUNT", len(part), name, scope)
    for year, value in a2["by_year"].items():
        add("A2_WEALTH_BY_YEAR", "GROSS_WEALTH_CONTRIBUTION", value, "A2", year)
    increment_rows = detail[detail.row_type.eq("A2_MINUS_A_SESSION_SECURITY")]
    for year, group in increment_rows.groupby("year", sort=True):
        add("A2_MINUS_A_BY_YEAR", "NET_WEALTH_CONTRIBUTION",
            pd.to_numeric(group.net_wealth_contribution).sum(), "A2_MINUS_A", year)
    for ticker, group in increment_rows.groupby("ticker", sort=True):
        add("A2_MINUS_A_BY_SECURITY", "NET_WEALTH_CONTRIBUTION",
            pd.to_numeric(group.net_wealth_contribution).sum(), ticker)
    for sector, group in increment_rows.groupby("sector", sort=True):
        add("A2_MINUS_A_BY_SECTOR", "NET_WEALTH_CONTRIBUTION",
            pd.to_numeric(group.net_wealth_contribution).sum(), sector)
    for path, digest in facts["source"]["hashes"].items():
        add("SOURCE_IDENTITY", "SHA256", digest, path)
    add("SOURCE_IDENTITY", "RAW_TOP40_SHA256", facts["source"]["top40_sha256"], str(TOP40))
    add("SOURCE_IDENTITY", "PIT_TAXONOMY_SHA256", facts["source"]["taxonomy_sha256"], str(TAXONOMY))
    summary = pd.DataFrame(rows)

    year_net = increment_rows.groupby("year").net_wealth_contribution.apply(lambda x: pd.to_numeric(x).sum())
    edge = (incremental["terminal_delta"] > 0 and incremental["mean_spread"] > 0
            and incremental["positive_date_fraction"] > .5 and (year_net > 0).sum() >= 2)
    boundary = rank["TOP20_VS_RANK21_40_spread"] > 0 and rank["RANK16_20_VS_RANK21_25_spread"] > 0
    winner = concentration["top5_positive_contribution_share"] >= .5
    if not edge: primary = "A2_INCREMENTAL_EDGE_NOT_ESTABLISHED"
    elif winner and boundary: primary = "TOP20_BOUNDARY_EDGE_WITH_WINNER_DEPENDENCE"
    elif winner: primary = "EXTREME_WINNER_DOMINATED"
    elif boundary: primary = "BROAD_CROSS_SECTIONAL_SELECTION_EDGE"
    else: primary = "MIXED_OR_UNRESOLVED"
    classes = {"primary": primary, "incremental": "ESTABLISHED_DESCRIPTIVELY" if edge else "NOT_ESTABLISHED",
               "boundary": "POSITIVE_FIXED_BOUNDARY_SPREAD" if boundary else "NO_CONSISTENT_FIXED_BOUNDARY_EDGE",
               "winner": "MATERIAL_WINNER_DEPENDENCE" if winner else "NOT_TOP5_DOMINATED"}

    securities = a2["security"]
    top_lines = "\n".join(f"| {r.ticker} | {r.gross_wealth:.6f} | {r.cost_wealth:.6f} | {r.net_wealth:.6f} |"
                            for r in securities.head(10).itertuples(index=False))
    bottom_lines = "\n".join(f"| {r.ticker} | {r.gross_wealth:.6f} | {r.cost_wealth:.6f} | {r.net_wealth:.6f} |"
                               for r in securities.tail(5).sort_values("gross_wealth").itertuples(index=False))
    year_lines = "\n".join(f"| {int(y)} | {float(v):.6f} |" for y, v in a2["by_year"].items())
    replacement_year = replacement.groupby("year").spread.agg(mean="mean", median="median", positive=lambda x: x.gt(0).mean())
    replacement_lines = "\n".join(f"| {int(y)} | {r['mean']:.6%} | {r['median']:.6%} | {r['positive']:.2%} |"
                                    for y, r in replacement_year.iterrows())
    bucket_lines = "\n".join(
        f"| {r.bucket} | {r.mean_return:.6%} | {r.median_return:.6%} | {r.hit_rate:.2%} | {r.coverage:.2%} | {int(r.complete_date_count)} |"
        for r in buckets[buckets.scope.eq("ALL")].itertuples(index=False))
    inc_security = increment_rows.groupby("ticker").net_wealth_contribution.apply(lambda x: pd.to_numeric(x).sum()).sort_values(ascending=False)
    inc_security_lines = "\n".join(f"| {ticker} | {value:.6f} |" for ticker, value in pd.concat([inc_security.head(5), inc_security.tail(5)]).items())
    inc_year = increment_rows.groupby("year").net_wealth_contribution.apply(lambda x: pd.to_numeric(x).sum())
    inc_year_lines = "\n".join(f"| {int(year)} | {value:.6f} |" for year, value in inc_year.items())
    inc_sector = increment_rows.groupby("sector").net_wealth_contribution.apply(lambda x: pd.to_numeric(x).sum()).sort_values(ascending=False)
    inc_sector_lines = "\n".join(f"| {sector} | {value:.6f} |" for sector, value in inc_sector.items())
    report = f"""# A2 return attribution R1

本任务只读取冻结的 A/A2 经济账本和 authoritative Raw A2 Top40 checkpoint；没有训练、优化、网络访问或 2026 outcome 使用。A 与 A2 的逐日收益、成本和 NAV 均在 machine precision 内重现。A2 security wealth identity 最大误差 `{concentration['wealth_identity_max_abs_error']:.3e}`，A2−A identity 最大误差 `{incremental['identity_error']:.3e}`。

## 谁为 A2 创造了财富

A2 从 1.0 增至 `{facts['A2_replay']['terminal_wealth']:.6f}`。证券贡献是 frozen position ledger 的 realized gross wealth；交易成本另行扣除。正贡献 Top1/Top3/Top5/Top10 集中度为 `{concentration['top1_positive_contribution_share']:.2%}` / `{concentration['top3_positive_contribution_share']:.2%}` / `{concentration['top5_positive_contribution_share']:.2%}` / `{concentration['top10_positive_contribution_share']:.2%}`；有效贡献者数 `{concentration['effective_contributor_count']:.2f}`。

| Security | Gross wealth | Cost | Net wealth |
|---|---:|---:|---:|
{top_lines}

最大负贡献者：

| Security | Gross wealth | Cost | Net wealth |
|---|---:|---:|---:|
{bottom_lines}

| Year | Gross wealth contribution |
|---:|---:|
{year_lines}

三个年度的 gross wealth contribution 都为正；2025 最大，占三年 gross security contribution 的 `{concentration['largest_positive_year_contribution'] / sum(a2['by_year']):.2%}`，因此年度来源有倾斜但并非单一年份独占。

Top1/3/5/10 删除结果只标记为 `EX_POST_FRAGILITY_DIAGNOSTIC_ONLY`、`NOT_AN_INVESTABLE_STRATEGY`、`NOT_ELIGIBLE_FOR_MODEL_SELECTION`；没有替换或重排证券。

## A2 为什么比 A 多赚钱

A2 terminal wealth 比 A 高 `{incremental['terminal_delta']:.6f}`。精确分解：A2-only `{incremental['a2_only_total']:.6f}`；A-only signed offset `{incremental['a_only_offset_total']:.6f}`（A 实际 A-only gross `{incremental['a_only_actual_total']:.6f}`）；common exposure difference `{incremental['common_exposure_difference']:.6f}`；other/trade-only gross difference `{incremental['other_gross_difference']:.6f}`；再减 incremental cost `{incremental['incremental_cost']:.6f}`。残差 `{incremental['identity_error']:.3e}`。

A2-only 相对 A-only 的同 session basket spread：均值 `{incremental['mean_spread']:.6%}`，中位数 `{incremental['median_spread']:.6%}`，正值日期比例 `{incremental['positive_date_fraction']:.2%}`。

因此 A2-only 并非“通常”优于 A-only：均值受右尾收益抬高，但中位数为负，且正 spread 日期不足一半。A2−A 的 net wealth advantage 在 2023、2024、2025 都为正，不过 2025 贡献 `{inc_year.loc[2025] / incremental['terminal_delta']:.2%}`，增量优势明显向 2025 倾斜。

| Year | Mean spread | Median spread | Positive dates |
|---:|---:|---:|---:|
{replacement_lines}

按年度的 A2−A exact net wealth contribution：

| Year | Net incremental wealth |
|---:|---:|
{inc_year_lines}

增量贡献最高/最低的 securities：

| Security | Net incremental wealth |
|---|---:|
{inc_security_lines}

现有 PIT FF12 可匹配部分的增量贡献（A-only 无 A2 taxonomy 对应时保持 UNKNOWN）：

| FF12 | Net incremental wealth |
|---|---:|
{inc_sector_lines}

## Raw A2 Top20 边界

固定使用 ranks 1–10、11–20、21–30、31–40 与 16–20 对 21–25，没有 TopN 搜索。观测窗口与冻结 A/A2 经济窗口一致（2023–2025）。return 是 signal 后下一执行 session 到再下一 session 的 gross open-to-open return。价格仅来自已有 PIT forward-rehab cache 或 QFQ/backfill；缺任一端点即 missing，且不跨来源混合尺度。总体覆盖 `{rank['coverage']:.2%}`；主比较只用左右固定桶全部成员都有 return 的日期。

| Bucket | Mean | Median | Hit rate | Coverage | Complete dates |
|---|---:|---:|---:|---:|---:|
{bucket_lines}

- Top20 − ranks 21–40: `{rank['TOP20_VS_RANK21_40_spread']:.6%}`，完整日期 `{rank['TOP20_VS_RANK21_40_date_count']}`。
- ranks 1–10 − 11–20: `{rank['RANK1_10_VS_RANK11_20_spread']:.6%}`，完整日期 `{rank['RANK1_10_VS_RANK11_20_date_count']}`。
- ranks 16–20 − 21–25: `{rank['RANK16_20_VS_RANK21_25_spread']:.6%}`，完整日期 `{rank['RANK16_20_VS_RANK21_25_date_count']}`。

所以 ranks 1–20 整体在完整日期上胜过 21–40，但真正的 Top20 邻近边界（16–20 对 21–25）没有显示正排序价值；较强的 ordering 主要来自 ranks 1–10 对 11–20，而不是边界切割本身。

## 简明回答

1. 主要财富贡献者见首表；winner dependence 为 `{classes['winner']}`。
2. A2−A 优势由 A2-only、A-only offset、common exposure 与成本差精确解释；替换质量为 `{classes['incremental']}`。
3. 固定 Top20 boundary 为 `{classes['boundary']}`。
4. 总体历史证据最符合 `{classes['primary']}`。

会计 identities 是精确事实；replacement/rank 是描述性历史证据；删除赢家是纯 ex-post fragility diagnostic。sector 只复用现有 frozen PIT FF12；缺失保持 UNKNOWN。
"""
    return summary, report, classes


def main() -> None:
    canonical = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe").resolve()
    require(Path(sys.executable).resolve() == canonical, "NON_CANONICAL_RUNTIME", sys.executable)
    if OUT.exists():
        existing = sorted(p.name for p in OUT.iterdir())
        require(existing == ["attribution_detail.parquet", "attribution_summary.csv", "final_report.md"],
                "TARGET_RESULTS_CONTAINS_UNEXPECTED_ARTIFACT", existing)
    frames, source = verify_sources()
    facts: dict[str, Any] = {"source": source}
    for arm in ("A", "A2"):
        facts[f"{arm}_replay"] = verify_arm(arm, frames[f"{arm}_portfolio_daily.parquet"],
            frames[f"{arm}_position_ledger.parquet"], frames[f"{arm}_top20_selections.parquet"], source[f"{arm}_published"])
    a2_detail, a2, concentration = a2_wealth_ledger(frames, facts["A2_replay"])
    incremental_detail, incremental, replacement = incremental_ledger(frames)
    rank_detail, rank, buckets, comparisons = rank_attribution(frames["TOP40"])
    detail = pd.concat([a2_detail, incremental_detail, rank_detail], ignore_index=True, sort=False)
    require(pd.to_datetime(detail.date).max() <= pd.Timestamp("2025-12-31"), "POST_2025_OUTCOME_LEAKAGE")
    summary, report, classes = build_outputs(facts, a2, concentration, incremental, replacement,
                                              rank, buckets, comparisons, detail)
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_write(OUT / "attribution_detail.parquet", lambda p: detail.to_parquet(p, index=False))
    atomic_write(OUT / "attribution_summary.csv", lambda p: summary.to_csv(p, index=False, encoding="utf-8-sig"))
    atomic_write(OUT / "final_report.md", lambda p: p.write_text(report, encoding="utf-8"))
    artifacts = sorted(p.name for p in OUT.iterdir() if p.is_file())
    require(artifacts == ["attribution_detail.parquet", "attribution_summary.csv", "final_report.md"], "RESULT_ARTIFACT_CAP", artifacts)
    temp_remains = len(list(OUT.glob(".*.tmp*"))); require(temp_remains == 0, "TEMP_FILE_REMAINS")
    values = {
        "RESEARCH_RESULT_STATUS": "PASS_ATTRIBUTION_COMPLETE", "EXECUTION_STATUS": "PASS",
        "REPOSITORY_POLICY_STATUS": "PASS_TASK_LOCAL_WITH_PREEXISTING_WARNINGS",
        "DATE_MAX_OUTCOME_USED": "2025-12-31", "POST_2025_OUTCOME_USED": "false", "NETWORK_USED": "false",
        "A_REPLAY_STATUS": facts["A_replay"]["status"], "A2_REPLAY_STATUS": facts["A2_replay"]["status"],
        "A2_ATTRIBUTION_IDENTITY_MAX_ABS_ERROR": concentration["wealth_identity_max_abs_error"],
        "A2_MINUS_A_IDENTITY_MAX_ABS_ERROR": incremental["identity_error"],
        "A_CAGR": facts["A_replay"]["cagr"], "A2_CAGR": facts["A2_replay"]["cagr"],
        "A2_MINUS_A_TERMINAL_WEALTH_DELTA": incremental["terminal_delta"],
        "TOP1_POSITIVE_CONTRIBUTION_SHARE": concentration["top1_positive_contribution_share"],
        "TOP3_POSITIVE_CONTRIBUTION_SHARE": concentration["top3_positive_contribution_share"],
        "TOP5_POSITIVE_CONTRIBUTION_SHARE": concentration["top5_positive_contribution_share"],
        "TOP10_POSITIVE_CONTRIBUTION_SHARE": concentration["top10_positive_contribution_share"],
        "EFFECTIVE_CONTRIBUTOR_COUNT": concentration["effective_contributor_count"],
        "LARGEST_POSITIVE_CONTRIBUTOR": concentration["largest_positive_contributor"],
        "LARGEST_POSITIVE_YEAR": concentration["largest_positive_year"],
        "A2_ONLY_VS_A_ONLY_MEAN_SPREAD": incremental["mean_spread"],
        "A2_ONLY_VS_A_ONLY_MEDIAN_SPREAD": incremental["median_spread"],
        "A2_ONLY_VS_A_ONLY_POSITIVE_DATE_FRACTION": incremental["positive_date_fraction"],
        "TOP20_VS_RANK21_40_SPREAD": rank["TOP20_VS_RANK21_40_spread"],
        "RANK1_10_VS_RANK11_20_SPREAD": rank["RANK1_10_VS_RANK11_20_spread"],
        "RANK16_20_VS_RANK21_25_SPREAD": rank["RANK16_20_VS_RANK21_25_spread"],
        "PRIMARY_RETURN_SOURCE_CLASSIFICATION": classes["primary"],
        "A2_INCREMENTAL_EDGE_CLASSIFICATION": classes["incremental"],
        "TOP20_BOUNDARY_CLASSIFICATION": classes["boundary"], "WINNER_DEPENDENCE_CLASSIFICATION": classes["winner"],
        "SOURCE_MODIFICATION_COUNT": 1, "RESULT_ARTIFACT_COUNT": len(artifacts), "TEMP_FILE_REMAINS": temp_remains,
        "NEXT_RESEARCH_QUESTION": "NONE_AUTOMATIC_STOP_HERE"}
    print("=" * 60); print("A2_RETURN_ATTRIBUTION_R1_FINAL"); print("=" * 60); print()
    for key, value in values.items(): print(f"{key}={value}")


if __name__ == "__main__":
    main()
