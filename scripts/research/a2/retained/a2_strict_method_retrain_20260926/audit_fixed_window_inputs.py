"""Read-only full-window candidate Raw availability and source binding audit.

This is an input audit only. It never labels missing data as ineligible, never
fits a model, and never creates a strategy return from a partial pool.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "fixed_window_binding"
RAW_OUT = STAGE / "fixed_window_raw"
OTHER = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
ORIGINAL = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
QFQ = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    contract = json.loads((BASE / "test2026/test2026_contract.json").read_text(encoding="utf-8"))
    assert contract["test_asof_utc"] == "2026-09-25T18:10:21.6494935Z"
    assert contract["last_fully_accountable_signal"] == "2026-09-22"
    assert contract["last_fully_accountable_execution"] == "2026-09-23"
    assert contract["terminal_valuation_open"] == "2026-09-24"
    qfq_parts = []
    for year in (2024, 2025, 2026):
        path = QFQ / f"year={year}/prices.parquet"
        qfq_parts.append(pd.read_parquet(path, columns=["ticker", "trade_date"]).loc[lambda x: x.ticker.eq("QQQ")])
    qfq_parts.append(pd.read_parquet(STAGE / "qqq_2026_0715_0924_moomoo_qfq.parquet", columns=["trade_date"])
                     .assign(ticker="QQQ"))
    calendar = pd.DatetimeIndex(pd.concat(qfq_parts).trade_date).unique().sort_values()
    test = calendar[(calendar >= "2026-01-02") & (calendar <= "2026-09-24")]
    signals = test[test <= "2026-09-22"]
    assert signals.min() == pd.Timestamp("2026-01-02")
    assert test.max() == pd.Timestamp("2026-09-24")
    assert len(signals) >= 170

    manifest = pd.read_parquet(ORIGINAL / "universe/quarterly_universe_manifest.parquet")
    members = pd.read_parquet(ORIGINAL / "universe/quarterly_universe_members.parquet")
    members = members.loc[members.quarter.isin(["2025Q3", "2025Q4", "2026Q1"])]
    q2 = pd.read_parquet(OTHER / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
    agg = pd.read_parquet(OTHER / "Q2_ORIGINAL24_CANDIDATE_AGG_VH.parquet")
    assert set(agg.loc[agg.version_state.eq("INITIAL_24"), "ticker"]) == set(q2.ticker)
    assert set(agg.loc[agg.version_state.eq("CITADEL_RESTATED"), "ticker"]) == set(q2.ticker)
    assert len(q2) == 575 and q2.ticker.is_unique and q2.cusip.is_unique and q2.moomoo_transport_code.is_unique
    members = pd.concat([members, q2], ignore_index=True)
    assert members.groupby("moomoo_transport_code").ticker.nunique().max() == 1
    assert members.groupby("quarter").size().to_dict() == {"2025Q3": 643, "2025Q4": 624, "2026Q1": 613, "2026Q2": 575}
    effective = manifest.loc[manifest.quarter.isin(["2025Q3", "2025Q4", "2026Q1"]), ["quarter", "effective_date"]]
    effective = pd.concat([effective, pd.DataFrame([{"quarter": "2026Q2", "effective_date": pd.Timestamp("2026-08-21")}])])
    effective = effective.sort_values("effective_date")
    active = pd.DataFrame({"signal_date": signals})
    active["quarter"] = effective.iloc[np.searchsorted(effective.effective_date.to_numpy(), signals.to_numpy(), side="right") - 1].quarter.to_numpy()
    grid = active.merge(members[["quarter", "ticker", "cusip", "title_of_class", "moomoo_transport_code"]],
                        on="quarter", validate="many_to_many")
    assert not grid.duplicated(["signal_date", "ticker"]).any()

    inventory = pd.read_csv(OTHER / "QUARTER_POOL_PRICE_INVENTORY.csv")
    original_paths = inventory.drop_duplicates("moomoo_transport_code").set_index("moomoo_transport_code").raw_paths.to_dict()
    reused = pd.read_csv(OTHER / "SUBSCRIPTION_RAW_FILES_MANIFEST.csv")
    assert reused.code.is_unique
    reused = reused.set_index("code")
    receipt_path = RAW_OUT / "FIXED_WINDOW_RAW_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {"records": []}
    current = {x["code"]: x for x in receipt["records"] if x.get("status") == "RAW_SAVED_INPUT_ONLY"}
    raw_dates = {}
    valid_opens = {}
    collisions = []
    source_rows = []
    for code in sorted(grid.moomoo_transport_code.unique()):
        parts = []
        sources = []
        original = original_paths.get(code)
        if isinstance(original, str) and original:
            path = Path(original)
            if path.exists():
                parts.append(("ORIGINAL_RAW", path))
        if code in reused.index:
            row = reused.loc[code]
            path = OTHER / str(row["file"])
            if path.exists() and sha(path) == str(row["sha256"]):
                parts.append(("PRIOR_SUBSCRIPTION_RAW", path))
            else:
                collisions.append({"code": code, "kind": "PRIOR_RAW_MISSING_OR_HASH_MISMATCH", "path": str(path)})
        if code in current:
            path = RAW_OUT / current[code]["file"]
            if path.exists() and sha(path) == current[code]["sha256"]:
                parts.append(("CURRENT_FIXED_WINDOW_RAW", path))
            else:
                collisions.append({"code": code, "kind": "CURRENT_RAW_MISSING_OR_HASH_MISMATCH", "path": str(path)})
        frames = []
        for label, path in parts:
            d = pd.read_parquet(path)
            if "code" in d:
                d = d.loc[d.code.astype(str).eq(code)]
            d = d[["time_key", "open", "high", "low", "close", "volume"]].copy()
            d["trade_date"] = pd.to_datetime(d.time_key).dt.normalize()
            d["source_label"] = label
            frames.append(d)
            sources.append({"source": label, "path": str(path), "sha256": sha(path), "rows": len(d),
                            "first": str(d.trade_date.min().date()) if len(d) else None,
                            "last": str(d.trade_date.max().date()) if len(d) else None})
        if frames:
            d = pd.concat(frames, ignore_index=True)
            duplicate = d.loc[d.trade_date.duplicated(keep=False)].copy()
            if len(duplicate):
                fields = ["open", "high", "low", "close", "volume"]
                duplicate[fields] = duplicate[fields].apply(pd.to_numeric, errors="coerce")
                grouped = duplicate.groupby("trade_date")[fields]
                spread = grouped.max() - grouped.min()
                for day in spread.index[spread.gt(1e-9).any(axis=1)]:
                    collisions.append({"code": code, "kind": "RAW_OVERLAP_PRICE_CONFLICT", "trade_date": str(day.date())})
            d = d.sort_values(["trade_date", "source_label"]).drop_duplicates("trade_date", keep="last")
            raw_dates[code] = set(d.trade_date)
            opens = pd.to_numeric(d.open, errors="coerce")
            valid_opens[code] = set(d.loc[np.isfinite(opens) & opens.gt(0), "trade_date"])
        else:
            raw_dates[code] = set()
            valid_opens[code] = set()
        source_rows.append({"code": code, "source_file_count": len(parts), "sources": json.dumps(sources),
                            "has_current_fetch": code in current, "current_fetch_status": next((x.get("status") for x in receipt["records"] if x["code"] == code), "NOT_ATTEMPTED")})

    # A preliminary Raw coverage measure. Full eligibility still requires the
    # original adjustment events, UID, feature builder, and PIT version checks.
    dates_by_code = {c: set(v) for c, v in raw_dates.items()}
    grid["raw_on_signal"] = [d in dates_by_code[c] for d, c in zip(grid.signal_date, grid.moomoo_transport_code)]
    position = {d: i for i, d in enumerate(calendar)}
    lookback = {}
    for code, dates in dates_by_code.items():
        ordered = sorted(d for d in dates if d in position)
        good = set()
        for i in range(120, len(ordered)):
            if position[ordered[i]] - position[ordered[i - 120]] == 120:
                good.add(ordered[i])
        lookback[code] = good
    grid["raw_121_calendar_ready"] = [d in lookback[c] for d, c in zip(grid.signal_date, grid.moomoo_transport_code)]
    grid["input_status"] = np.select(
        [~grid.raw_on_signal, grid.raw_on_signal & ~grid.raw_121_calendar_ready],
        ["UNKNOWN_NO_QUALIFIED_RAW_ON_SIGNAL", "UNKNOWN_RAW_121_OR_PREWARM_INCOMPLETE"],
        default="RAW_121_READY_FEATURE_UID_REHAB_PENDING")
    grid.to_parquet(OUT / "full_window_candidate_raw_status.parquet", index=False)
    daily = grid.groupby(["signal_date", "quarter", "input_status"]).size().unstack(fill_value=0).reset_index()
    daily.to_csv(OUT / "full_window_daily_raw_coverage.csv", index=False)
    execution_by_signal = {calendar[i]: calendar[i + 1] for i in range(len(calendar) - 1)}
    valuation_by_signal = {calendar[i]: calendar[i + 2] for i in range(len(calendar) - 2)}
    settlement = grid[["signal_date", "quarter", "ticker", "moomoo_transport_code", "cusip"]].copy()
    settlement["execution_date"] = settlement.signal_date.map(execution_by_signal)
    settlement["subsequent_valuation_date"] = settlement.signal_date.map(valuation_by_signal)
    settlement["execution_open_input_present"] = [d in valid_opens[c] for d, c in zip(settlement.execution_date, settlement.moomoo_transport_code)]
    settlement["valuation_open_input_present"] = [d in valid_opens[c] for d, c in zip(settlement.subsequent_valuation_date, settlement.moomoo_transport_code)]
    settlement["execution_input_status"] = np.where(settlement.execution_open_input_present,
        "RAW_OPEN_PRESENT_ADJUSTMENT_AND_UID_PENDING", "UNKNOWN_NO_VALID_EXECUTION_OPEN_OR_LIFECYCLE")
    settlement["valuation_input_status"] = np.where(settlement.valuation_open_input_present,
        "RAW_OPEN_PRESENT_ADJUSTMENT_AND_POSITION_PENDING", "UNKNOWN_HELD_MARK_OR_EXIT_SETTLEMENT")
    settlement.to_parquet(OUT / "full_window_execution_valuation_input_status.parquet", index=False)
    gap_rows = grid.loc[grid.input_status.ne("RAW_121_READY_FEATURE_UID_REHAB_PENDING")].groupby(
        ["quarter", "ticker", "cusip", "title_of_class", "moomoo_transport_code", "input_status"],
        as_index=False).agg(candidate_days=("signal_date", "size"), first_signal=("signal_date", "min"),
                             last_signal=("signal_date", "max"))
    prior75 = pd.read_csv(OTHER / "REMAINING75_RESOLUTION.csv", usecols=["original_code", "resolution_status", "case_kind"])
    gap_rows = gap_rows.merge(prior75, left_on="moomoo_transport_code", right_on="original_code", how="left")
    gap_rows = gap_rows.drop(columns=["original_code"])
    gap_rows.to_csv(OUT / "remaining_candidate_input_gaps.csv", index=False)
    settlement_gaps = settlement.loc[~settlement.execution_open_input_present | ~settlement.valuation_open_input_present]
    settlement_gaps.groupby(["quarter", "ticker", "cusip", "moomoo_transport_code"], as_index=False).agg(
        possible_execution_gap_days=("execution_open_input_present", lambda s: int((~s).sum())),
        possible_valuation_gap_days=("valuation_open_input_present", lambda s: int((~s).sum())),
        first_signal=("signal_date", "min"), last_signal=("signal_date", "max")
    ).to_csv(OUT / "remaining_execution_valuation_input_gaps.csv", index=False)
    pd.DataFrame(source_rows).to_csv(OUT / "raw_source_binding.csv", index=False)
    pd.DataFrame(collisions).to_csv(OUT / "raw_collisions.csv", index=False)
    source = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
    evaluate = HERE / "evaluate.py"
    source_text = source.read_text(encoding="utf-8")
    evaluate_text = evaluate.read_text(encoding="utf-8")
    assert "def reconstruct_path(" in source_text
    assert 'R0F = Path(r"D:\\us-tech-quant\\scripts\\v22\\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")' in evaluate_text
    assert 'r0f = import_file("original_r0f_for_execution", R0F)' in evaluate_text
    assert "r0f.reconstruct_path(model=method" in evaluate_text
    spec = importlib.util.spec_from_file_location("a2_bound_execution_source", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    actual_function_source = Path(inspect.getsourcefile(module.reconstruct_path)).resolve()
    assert actual_function_source == source.resolve()
    report = {
        "status": "FULL_FIXED_WINDOW_RAW_AUDIT_FEATURE_AND_ACCOUNTING_QUALIFICATION_PENDING",
        "test_asof_utc": contract["test_asof_utc"], "last_signal": str(signals.max().date()),
        "last_execution": contract["last_fully_accountable_execution"],
        "terminal_valuation": contract["terminal_valuation_open"],
        "signal_sessions": len(signals), "candidate_rows": len(grid),
        "candidate_input_status_counts": grid.input_status.value_counts().to_dict(),
        "quarter_candidate_counts": members.groupby("quarter").size().to_dict(),
        "q2_initial_and_restatement_candidate_ticker_sets_identical": True,
        "raw_price_collision_count": len(collisions),
        "remaining_candidate_gap_rows": len(gap_rows),
        "remaining75_prior_diagnostic_matched_gap_codes": int(gap_rows.loc[gap_rows.moomoo_transport_code.isin(prior75.original_code), "moomoo_transport_code"].nunique()),
        "candidate_execution_input_status_counts": settlement.execution_input_status.value_counts().to_dict(),
        "candidate_valuation_input_status_counts": settlement.valuation_input_status.value_counts().to_dict(),
        "last_signal_execution_open_present": int(settlement.loc[settlement.signal_date.eq("2026-09-22"), "execution_open_input_present"].sum()),
        "last_signal_valuation_open_present": int(settlement.loc[settlement.signal_date.eq("2026-09-22"), "valuation_open_input_present"].sum()),
        "last_signal_candidate_count": int(settlement.signal_date.eq("2026-09-22").sum()),
        "actual_reconstruct_path_source": str(source), "actual_reconstruct_path_sha256": sha(source),
        "actual_reconstruct_path_function_first_line": inspect.getsourcelines(module.reconstruct_path)[1],
        "actual_reconstruct_call_site": str(evaluate), "call_site_sha256": sha(evaluate),
        "original_13f_manifest_sha256": sha(ORIGINAL / "universe/quarterly_universe_manifest.parquet"),
        "original_13f_members_sha256": sha(ORIGINAL / "universe/quarterly_universe_members.parquet"),
        "q2_source_map_sha256": sha(OTHER / "Q2_ORIGINAL24_SOURCE_MAP.csv"),
        "q2_initial_candidates_sha256": sha(OTHER / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet"),
        "q2_version_agg_sha256": sha(OTHER / "Q2_ORIGINAL24_CANDIDATE_AGG_VH.parquet"),
        "raw_fetch_receipt_sha256": sha(receipt_path) if receipt_path.exists() else None,
        "raw_status_file_sha256": sha(OUT / "full_window_candidate_raw_status.parquet"),
        "execution_valuation_status_file_sha256": sha(OUT / "full_window_execution_valuation_input_status.parquet"),
        "remaining_candidate_gaps_sha256": sha(OUT / "remaining_candidate_input_gaps.csv"),
        "remaining_execution_valuation_gaps_sha256": sha(OUT / "remaining_execution_valuation_input_gaps.csv"),
        "separate_execution_and_valuation_qualification": "PENDING; raw signal status cannot certify fills or held-price valuation",
        "formal_nav_reported": False, "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
        "fit_count_basis": "audit imports no model, estimator, scaler or fit entry point",
    }
    (OUT / "FULL_WINDOW_INPUT_BINDING_AUDIT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("signal_sessions", "candidate_rows", "candidate_input_status_counts", "raw_price_collision_count")}), flush=True)


if __name__ == "__main__":
    main()
