"""Apply saved security verdicts and run the frozen A2 feature builders, read only.

This produces an exact candidate-day ledger.  It never invokes a fit method,
subscribes to data, or runs the original rebuild entry point.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "identity_feature_application_r1"
OLD = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
ORIGINAL = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
R0F1 = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
RUN_CACHE = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1")
REHAB_DIRS = [RUN_CACHE] + [OLD / n for n in (
    "REHAB_NEW_OCCUPIED_ONLY", "REHAB_SUBSCRIPTION_ONLY",
    "REHAB_AUTHORITY_ALIASES_ONLY", "REHAB_OFFICIAL_COMMON_ALIASES_ONLY")]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def main() -> None:
    OUT.mkdir(exist_ok=True)
    contract = json.loads((BASE / "test2026/test2026_contract.json").read_text(encoding="utf-8"))
    assert contract["test_asof_utc"] == "2026-09-25T18:10:21.6494935Z"
    assert contract["last_fully_accountable_signal"] == "2026-09-22"
    assert contract["terminal_valuation_open"] == "2026-09-24"
    grid_path = STAGE / "fixed_window_binding/full_window_candidate_raw_status.parquet"
    grid = pd.read_parquet(grid_path)
    assert len(grid) == 111868
    key = ["cusip", "title_of_class", "quarter", "signal_date"]
    assert not grid.duplicated(key).any()
    resolution_path = OLD / "REMAINING75_RESOLUTION.csv"
    resolution = pd.read_csv(resolution_path, dtype={"original_cusip": str})
    resolution = resolution.set_index("original_code", verify_integrity=True)
    source_path = STAGE / "fixed_window_binding/raw_source_binding.csv"
    sources = pd.read_csv(source_path).set_index("code", verify_integrity=True)
    assert set(grid.moomoo_transport_code.unique()) == set(sources.index)

    rebuild = module("a2_rebuild_feature_consumption", ORIGINAL)
    r1 = module("a2_r1_feature_consumption", R1)
    r0f1 = module("a2_r0f1_feature_consumption", R0F1)
    rebuild.END_EXCLUSIVE = pd.Timestamp("2026-09-25")
    wolf = next(x for x in r0f1.frozen_evidence_records() if x["ticker"] == "WOLF")
    assert len(r1.FEATURE_COLUMNS) == 32
    reuse_generated_features = os.environ.get("A2_REUSE_COMPLETED_FEATURES") == "1"
    cached_features_path = OUT / "ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"
    if reuse_generated_features:
        assert cached_features_path.exists(), "NO_COMPLETED_FEATURE_CHECKPOINT"
    qqq = []
    qfq = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
    for year in (2024, 2025, 2026):
        qqq.append(pd.read_parquet(qfq / f"year={year}/prices.parquet", columns=["ticker", "trade_date"])
                   .loc[lambda d: d.ticker.eq("QQQ"), ["trade_date"]])
    qqq.append(pd.read_parquet(STAGE / "qqq_2026_0715_0924_moomoo_qfq.parquet", columns=["trade_date"]))
    calendar = pd.DatetimeIndex(pd.concat(qqq).trade_date).unique().sort_values()
    position = pd.Series(np.arange(len(calendar)), index=calendar)

    # A PASS is required for the actual transport.  These five disjoint saved
    # snapshots contain the original factors and the prior subscription work.
    status_rows, factor_parts, rehab_sources = [], [], []
    for folder in REHAB_DIRS:
        status_file, factor_file = folder / "rehab_status.csv", folder / "rehab_factors.parquet"
        status = pd.read_csv(status_file, keep_default_na=False)
        factors = pd.read_parquet(factor_file)
        status_rows.append(status.loc[status.status.eq("PASS"), ["code", "status"]])
        factor_parts.append(factors)
        rehab_sources.append({"status_path": str(status_file), "status_sha256": sha(status_file),
                              "factors_path": str(factor_file), "factors_sha256": sha(factor_file),
                              "pass_codes": int(status.status.eq("PASS").sum())})
    pass_codes = pd.concat(status_rows).code.astype(str)
    assert not pass_codes.duplicated().any(), "REHAB_PASS_CODE_COLLISION"
    rehab = pd.concat(factor_parts, ignore_index=True)
    assert not rehab.duplicated(["code", "ex_div_date"]).any(), "REHAB_EVENT_COLLISION"
    rehab_by_code = {code: part for code, part in rehab.groupby("code", sort=False)}
    pass_set = set(pass_codes)
    prior_adjusted_path = BASE / "pre2026_original_price_coordinate.parquet"
    prior_adjusted = pd.read_parquet(prior_adjusted_path)
    prior_adjusted.trade_date = pd.to_datetime(prior_adjusted.trade_date)
    prior_by_ticker = {ticker: part.set_index("trade_date") for ticker, part in prior_adjusted.groupby("ticker", sort=False)}
    prior_alias_paths = [OLD / "AUTHORITY_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet",
                         OLD / "OFFICIAL_COMMON_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet"]
    prior_alias = pd.concat([pd.read_parquet(path) for path in prior_alias_paths], ignore_index=True)
    prior_alias.trade_date = pd.to_datetime(prior_alias.trade_date)
    prior_alias = prior_alias.drop_duplicates(["ticker", "trade_date"], keep="first")
    alias_by_ticker = {ticker: part.set_index("trade_date") for ticker, part in prior_alias.groupby("ticker", sort=False)}

    active_codes = grid[["moomoo_transport_code", "ticker", "cusip"]].drop_duplicates(
        ["moomoo_transport_code", "ticker"])
    assert active_codes.groupby("moomoo_transport_code").ticker.nunique().max() == 1
    multi_cusip_codes = set(grid.groupby("moomoo_transport_code").cusip.nunique().loc[lambda x: x.gt(1)].index)
    code_result, feature_parts, event_rows, source_audit = [], [], [], []
    for number, row in enumerate(active_codes.itertuples(index=False), 1):
        old_code, ticker = row.moomoo_transport_code, row.ticker
        verdict = resolution.loc[old_code] if old_code in resolution.index else None
        transport = str(verdict.correct_transport) if verdict is not None and pd.notna(verdict.correct_transport) else old_code
        if transport != old_code:
            assert str(row.cusip) == str(verdict.original_cusip), (old_code, row.cusip)
            r31_identity = bool(verdict.cusip_match) and str(verdict.share_class_check) == "PASS"
            targeted_official = (old_code in {"US.DTP", "US.GE.WI", "US.LILAB"}
                and str(verdict.transport_evidence_level) == "OFFICIAL_CUSIP_CLASS_ALIAS"
                and str(verdict.case_kind).startswith("TARGETED_OFFICIAL_")
                and "https://" in str(verdict.evidence_refs))
            assert r31_identity or targeted_official, old_code
            if str(verdict.resolution_status).startswith("UNKNOWN"):
                # AZNCF has an identified listing, but the original identity
                # interval and full 121 sessions are not yet proven.
                code_result.append({"moomoo_transport_code": old_code, "transport_used": None,
                                    "feature_error": "ALIAS_IDENTITY_PREWARM_UNRESOLVED", "rehab_pass": False,
                                    "coordinate_match": False, "coordinate_overlap_rows": 0})
                continue
        paths = []
        if transport == old_code:
            for item in json.loads(sources.loc[old_code, "sources"]):
                path = Path(item["path"])
                assert path.exists() and sha(path) == item["sha256"], path
                paths.append(path)
        else:
            path = OLD / f"SUBSCRIPTION_{transport.replace('.', '_')}_RAW_DAY_K_INPUT_ONLY.parquet"
            if path.exists():
                paths.append(path)
        if not paths or transport not in pass_set:
            code_result.append({"moomoo_transport_code": old_code, "transport_used": transport,
                                "feature_error": "NO_SAVED_RAW" if not paths else "NO_PASS_REHAB_SNAPSHOT",
                                "rehab_pass": transport in pass_set, "coordinate_match": False,
                                "coordinate_overlap_rows": 0})
            continue
        try:
            raw = rebuild.load_raw_code(transport, paths)
            raw = raw.loc[raw.trade_date.lt(rebuild.END_EXCLUSIVE)]
            assert len(raw), "EMPTY_SAVED_RAW"
            adjusted, events = rebuild.adjusted_price_frame(
                transport, ticker, raw, rehab_by_code.get(transport, rehab.iloc[:0]), wolf)
            # The original full-history coordinate is retained.  Only the
            # feature computation can discard dates too old to affect 2026.
            reference = alias_by_ticker.get(ticker) if transport != old_code else prior_by_ticker.get(ticker)
            overlap = 0
            coordinate_match = False
            if reference is not None:
                check = adjusted.set_index("trade_date")[["open", "close"]].join(
                    reference[["open", "close"]], how="inner", lsuffix="_now", rsuffix="_prior")
                overlap = len(check)
                if overlap:
                    vals = check[["open_now", "close_now"]].to_numpy(float)
                    old_vals = check[["open_prior", "close_prior"]].to_numpy(float)
                    coordinate_match = bool(np.allclose(vals, old_vals, rtol=0, atol=1e-8))
            # LLYVK was spun off in Dec 2025.  Earlier provider history must
            # never count toward the original CUSIP's 121 sessions.
            feature_start = pd.Timestamp("2025-12-16") if old_code == "US.LLYVB" else pd.Timestamp("2025-06-01")
            if not reuse_generated_features:
                price_for_features = adjusted.loc[adjusted.trade_date.ge(feature_start),
                                                  ["ticker", "trade_date", "close", "volume"]]
                stock = r1.build_stock_state_features(price_for_features)
                stock["signal_date"] = stock.trade_date
                stock["calendar_position"] = stock.signal_date.map(position)
                stock["position_120_prior"] = stock.calendar_position.shift(120)
                stock["required_observations"] = np.arange(1, len(stock) + 1)
                stock["lookback_121_eligible"] = (stock.required_observations.ge(121)
                    & stock.calendar_position.notna() & stock.position_120_prior.notna()
                    & stock.calendar_position.sub(stock.position_120_prior).eq(120))
                stock["all_features_available"] = np.isfinite(stock[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
                feature_parts.append(stock.loc[stock.signal_date.ge("2026-01-02") & stock.signal_date.le("2026-09-22")].copy())
            for event in events:
                event_rows.append({"original_code": old_code, **event})
            source_audit.append({"original_code": old_code, "transport": transport,
                                 "paths": [str(p) for p in paths], "raw_rows": len(raw),
                                 "raw_first": str(raw.trade_date.min().date()), "raw_last": str(raw.trade_date.max().date()),
                                 "rehab_event_rows": len(rehab_by_code.get(transport, []))})
            code_result.append({"moomoo_transport_code": old_code, "transport_used": transport,
                                "feature_error": "", "rehab_pass": True,
                                "coordinate_match": coordinate_match, "coordinate_overlap_rows": overlap})
        except Exception as exc:
            code_result.append({"moomoo_transport_code": old_code, "transport_used": transport,
                                "feature_error": f"{type(exc).__name__}:{str(exc)[:200]}",
                                "rehab_pass": True, "coordinate_match": False,
                                "coordinate_overlap_rows": 0})
        if number % 100 == 0:
            print(f"processed {number}/{len(active_codes)} codes", flush=True)

    code_result = pd.DataFrame(code_result)
    assert len(code_result) == len(active_codes)
    all_features = (pd.read_parquet(cached_features_path) if reuse_generated_features else
                    pd.concat(feature_parts, ignore_index=True) if feature_parts else pd.DataFrame())
    if len(all_features):
        assert not all_features.duplicated(["ticker", "signal_date"]).any()
        if not reuse_generated_features:
            all_features.to_parquet(cached_features_path, index=False)

    ledger = grid.merge(code_result, on="moomoo_transport_code", how="left", validate="many_to_one")
    cols = ["ticker", "signal_date", "lookback_121_eligible", "all_features_available"]
    ledger = ledger.merge(all_features[cols], on=["ticker", "signal_date"], how="left", validate="one_to_one")
    prewarm = pd.read_parquet(OUT / "PREWARM_983_EXACT_KEY_RECONCILIATION.parquet")
    ledger = ledger.merge(prewarm[key + ["prior_verdict"]], on=key, how="left", validate="one_to_one")
    lifecycle = resolution[["original_cusip", "lifecycle_end_exclusive"]].dropna(subset=["lifecycle_end_exclusive"])
    end_dates = lifecycle.lifecycle_end_exclusive.to_dict()
    ledger["lifecycle_end_exclusive"] = ledger.moomoo_transport_code.map(end_dates)
    ledger["proven_lifecycle_ineligible"] = pd.to_datetime(ledger.lifecycle_end_exclusive).notna() & (
        ledger.signal_date.ge(pd.to_datetime(ledger.lifecycle_end_exclusive)))
    ledger["proven_121_ineligible"] = ledger.prior_verdict.eq("PROVEN_ORIGINAL_121_INELIGIBLE")
    llyvb = ledger.moomoo_transport_code.eq("US.LLYVB") & ledger.signal_date.lt(pd.Timestamp("2026-06-10"))
    ledger.loc[llyvb, "proven_121_ineligible"] = True
    ledger["has_32_finite"] = ledger.all_features_available.fillna(False)
    ledger["version_checked"] = ledger.coordinate_match & ledger.coordinate_overlap_rows.gt(0)
    ledger["multi_cusip_transport_interval_pending"] = ledger.moomoo_transport_code.isin(multi_cusip_codes)
    ledger["candidate_status"] = np.select([
        ledger.proven_lifecycle_ineligible,
        ledger.proven_121_ineligible,
        ledger.multi_cusip_transport_interval_pending,
        ledger.feature_error.fillna("").ne(""),
        ~ledger.lookback_121_eligible.fillna(False).to_numpy(dtype=bool),
        ~ledger.has_32_finite.to_numpy(dtype=bool),
        ~ledger.version_checked.to_numpy(dtype=bool),
    ], ["PROVEN_LIFECYCLE_INELIGIBLE", "PROVEN_ORIGINAL_121_INELIGIBLE",
        "UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL",
        "UNKNOWN_RAW_OR_REHAB_OR_IDENTITY", "UNKNOWN_121_OR_HISTORY",
        "UNKNOWN_32_FEATURES", "UNKNOWN_PRICE_VERSION"], default="FEATURE_READY_VERSION_OVERLAP_CHECKED")
    assert len(ledger) == 111868 and not ledger.duplicated(key).any()
    ledger.to_parquet(OUT / "CANDIDATE_111868_IDENTITY_32_FEATURE_VERSION_LEDGER.parquet", index=False)
    pd.DataFrame(event_rows).to_parquet(OUT / "CONSUMED_REHAB_EVENT_AUDIT.parquet", index=False)
    pd.DataFrame(source_audit).to_json(OUT / "CONSUMED_RAW_SOURCE_AUDIT.json", orient="records", indent=2)
    code_result.to_csv(OUT / "CODE_FEATURE_CONSUMPTION_AUDIT.csv", index=False)
    gaps = ledger.loc[ledger.candidate_status.str.startswith("UNKNOWN")].groupby(
        ["quarter", "ticker", "cusip", "title_of_class", "moomoo_transport_code", "candidate_status"],
        as_index=False).agg(days=("signal_date", "size"), first=("signal_date", "min"), last=("signal_date", "max"))
    gaps.to_csv(OUT / "REMAINING_EXACT_CANDIDATE_GAPS.csv", index=False)
    report = {"status": "FEATURES_CONSUMED_FORMAL_TEST_GATE_PENDING", "candidate_days": len(ledger),
              "candidate_status_counts": ledger.candidate_status.value_counts().to_dict(),
              "feature_rows_generated": len(all_features), "feature_columns": list(r1.FEATURE_COLUMNS),
              "completed_feature_checkpoint_reused_after_aggregation_type_error": reuse_generated_features,
              "completed_feature_checkpoint_sha256": sha(cached_features_path),
              "codes_processed": len(code_result), "codes_with_feature_error": int(code_result.feature_error.ne("").sum()),
              "codes_coordinate_overlap_matched": int(code_result.coordinate_match.sum()),
              "consumed_rehab_events": len(event_rows), "rehab_sources": rehab_sources,
              "original_builder_sha256": sha(ORIGINAL), "original_feature_source_sha256": sha(R1),
              "old_grid_sha256": sha(grid_path), "resolution_sha256": sha(resolution_path),
              "original_price_coordinate_sha256": sha(prior_adjusted_path),
              "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
              "formal_predictions_started": False, "formal_accounting_started": False}
    (OUT / "FEATURE_CONSUMPTION_REPORT.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("candidate_status_counts", "feature_rows_generated", "codes_with_feature_error", "codes_coordinate_overlap_matched")}, default=str))


if __name__ == "__main__":
    main()
