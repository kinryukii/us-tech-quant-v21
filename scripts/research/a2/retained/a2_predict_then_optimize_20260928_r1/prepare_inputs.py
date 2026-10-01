"""Build frozen, physically separate data snapshots without fitting or replay."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from data_contract import (
    ROOT, INPUT, FEATURES, KEY, SEED, MAX_TRAIN_KEYS, TRAIN_CLIP, STAGE_CUTOFFS,
    maturity_mask, sample_training_keys, sha256_file, validate_panel,
    validate_latest_effective, require_schema,
)

WS = ROOT.parent
OLD = WS / "a2_latest_effective_joint_20260927/data"
STRICT = WS / "a2_strict_method_retrain_20260926"
QUAL = WS / "a2_qualification_holdings_v1_20260927/data"
SOURCE = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1")
GATE = STRICT / "test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet"
TEST_FEATURES = STRICT / "test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"
PRICE_SOURCE = STRICT / "results/pre2026_original_price_coordinate.parquet"
SOURCES = {}
OUTPUTS = {}


def bind(path: Path) -> Path:
    SOURCES[str(path)] = sha256_file(path)
    return path


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen input artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")
    OUTPUTS[str(path.relative_to(ROOT))] = sha256_file(path)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen input artifact: {path}")
    frame.to_parquet(path, index=False)
    OUTPUTS[str(path.relative_to(ROOT))] = sha256_file(path)


def copy_snapshot(source: Path, destination: Path) -> None:
    bind(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite frozen input snapshot: {destination}")
    shutil.copyfile(source, destination)
    if sha256_file(destination) != SOURCES[str(source)]:
        raise AssertionError("snapshot copy hash differs from source")
    OUTPUTS[str(destination.relative_to(ROOT))] = sha256_file(destination)


def operations_snapshot(year: int, directory: Path) -> None:
    path = directory / "operational_exits.csv"
    if year == 2026:
        source = bind(QUAL / "operational_exit_evidence.csv")
        operations = pd.read_csv(source, dtype=str)
    else:
        operations = pd.DataFrame(columns=["ticker", "known_at", "effective_date", "reason", "source_id"])
    require_schema(operations, ["ticker", "known_at", "effective_date", "reason", "source_id"], name="operational exits")
    if path.exists():
        raise RuntimeError("operational-exit snapshot already exists")
    operations.to_csv(path, index=False)
    OUTPUTS[str(path.relative_to(ROOT))] = sha256_file(path)


def prepare() -> dict:
    if (ROOT / "INPUT_AUDIT.json").exists():
        return verify_existing()
    pre_source = bind(OLD / "pre2026_joint_context.parquet")
    pre = pd.read_parquet(pre_source)
    feature_audit = json.loads(bind(OLD / "JOINT_DATA_AUDIT.json").read_text(encoding="utf-8"))
    if tuple(feature_audit["features"]) != FEATURES:
        raise ValueError("upstream feature order differs from frozen 32-feature contract")
    validate_panel(pre, name="pre-2026 full available panel")
    require_schema(pre, ["active_13f_quarter", "latest_filing_date", "quarter_effective_date", "execution_date", "label_end_date", "label_available", "y_next_open"], name="pre-2026 panel")
    if not pre.signal_date.lt("2026-01-01").all() or not pre.new_buy_eligible.all():
        raise ValueError("pre-2026 training snapshot violates signal or pool boundary")
    timing = pd.read_csv(bind(OLD / "quarter_timing.csv"), parse_dates=["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"])
    validate_latest_effective(pre, timing, quarter_column="active_13f_quarter")
    membership = pd.read_parquet(bind(SOURCE / "universe/daily_eligible_universe_membership.parquet"), columns=KEY)
    membership = membership.loc[membership.signal_date.dt.year.isin([2023, 2024, 2025])].sort_values(KEY).reset_index(drop=True)
    if not pre[KEY].sort_values(KEY).reset_index(drop=True).equals(membership):
        raise ValueError("pre-2026 panel differs from entire upstream available daily pool")
    copy_snapshot(pre_source, INPUT / "pre2026.parquet")
    copy_snapshot(PRICE_SOURCE, INPUT / "pre2026_prices.parquet")
    pre_prices = pd.read_parquet(PRICE_SOURCE)
    require_schema(pre_prices, ["ticker", "trade_date", "open", "close"], name="pre-2026 price coordinate")
    if not pre_prices.trade_date.lt("2026-01-01").all() or pre_prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("pre-2026 risk prices violate chronology or key uniqueness")
    write_frame(INPUT / "quarter_timing.parquet", timing)
    stages = {}
    for stage, cutoff in STAGE_CUTOFFS.items():
        keys = sample_training_keys(pre, stage)
        write_frame(INPUT / f"stage_{stage}_keys.parquet", keys)
        mature = pre.loc[maturity_mask(pre, cutoff)]
        date_totals = keys.groupby("signal_date").sample_weight.sum()
        selected = keys.merge(pre[KEY + ["y_next_open"]], on=KEY, validate="one_to_one")
        stages[stage] = {
            "cutoff_exclusive": cutoff, "mature_full_pool_rows": len(mature),
            "mature_signal_days": int(mature.signal_date.nunique()), "selected_keys": len(keys),
            "selected_signal_days": int(keys.signal_date.nunique()),
            "max_mature_signal": str(mature.signal_date.max().date()),
            "max_mature_label_end": str(mature.label_end_date.max().date()),
            "selected_date_weight_min": float(date_totals.min()), "selected_date_weight_max": float(date_totals.max()),
            "selected_training_labels_clipped": int(selected.y_next_open.abs().gt(TRAIN_CLIP).sum()),
            "normalization_fit_scope": "this stage's selected pre-cutoff keys only",
        }

    directory = INPUT / "eval_2025"
    panel_2025 = pre.loc[pre.signal_date.between("2025-01-01", "2025-12-29")].copy()
    # Evaluation panels carry signal-time data, never prospective label values.
    signal_columns = KEY + ["active_13f_quarter", "new_buy_eligible", "latest_filing_date", "quarter_effective_date", "cusip", "moomoo_transport_code", *FEATURES]
    panel_2025 = panel_2025[signal_columns].copy()
    panel_2025["context_only_if_held"] = False
    panel_2025["input_conflict_warning"] = False
    panel_2025["price_coordinate"] = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    calendar_2025 = pd.DataFrame({"trade_date": sorted(pre_prices.loc[pre_prices.ticker.eq("QQQ") & pre_prices.trade_date.dt.year.eq(2025), "trade_date"].unique())})
    calendar_2025["is_signal"] = calendar_2025.trade_date.le("2025-12-29")
    price_2025 = pre_prices.loc[pre_prices.trade_date.dt.year.eq(2025)].copy()
    price_2025["price_quality_warning"] = False
    price_2025["price_coordinate"] = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    price_2025["price_qualification_reason"] = "INHERITED_PRE2026_RESEARCH_COORDINATE_NOT_INDEPENDENT_RAW_ACCOUNT_CERTIFICATION"
    directory.mkdir(parents=True, exist_ok=True)
    write_frame(directory / "features.parquet", panel_2025)
    write_frame(directory / "prices.parquet", price_2025)
    write_frame(directory / "calendar.parquet", calendar_2025)
    operations_snapshot(2025, directory)
    metadata_2025 = {
        "year": 2025, "signal_start": "2025-01-01", "signal_end": "2025-12-29",
        "terminal_valuation": "2025-12-31", "stage": "validation",
        "candidate_rows": len(panel_2025), "signal_days": int(panel_2025.signal_date.nunique()),
        "available_upstream_pool_complete": True, "original_unfiltered_13f_holdings_pool_complete": False,
        "scope": "entire upstream available daily pool from the 24-manager eligible Top100 union",
        "blind_test": False, "all_features_as_signal_time_only": True,
        "risk_inputs_path": str(INPUT / "pre2026_prices.parquet"),
        "price_warning_assignment": "inherited pre2026 research coordinate; warning=False does not certify raw shareholder-return accounting",
    }
    write_json(directory / "METADATA.json", metadata_2025)

    directory = INPUT / "eval_2026"
    panel_2026 = pd.read_parquet(bind(QUAL / "test_features_context.parquet"))
    validate_panel(panel_2026, name="2026 qualification subset")
    validate_latest_effective(panel_2026.loc[panel_2026.new_buy_eligible], timing, quarter_column="quarter")
    if not panel_2026.signal_date.dt.year.eq(2026).all():
        raise ValueError("2026 feature snapshot contains another signal year")
    if (panel_2026.context_only_if_held & panel_2026.new_buy_eligible).any():
        raise ValueError("held-only context cannot be newly bought")
    conflict = panel_2026.ticker.eq("GLW") & panel_2026.signal_date.eq("2026-02-26")
    panel_2026["input_conflict_warning"] = conflict
    panel_2026["input_conflict_reason"] = np.where(conflict, "UNRESOLVED_GLW_EXDATE_2026_02_26_VS_02_27_ADJUSTED_FEATURE_CONFLICT", "")
    write_frame(directory / "features.parquet", panel_2026)
    # Only source snapshots are read: no existing 2026 policy, trade, NAV or metric file.
    copy_snapshot(QUAL / "test_prices.parquet", directory / "prices.parquet")
    calendar_source = pd.read_parquet(bind(OLD / "calendar.parquet"))
    calendar_2026 = calendar_source.loc[calendar_source.is_test].copy()
    write_frame(directory / "calendar.parquet", calendar_2026)
    operations_snapshot(2026, directory)
    gate = pd.read_parquet(bind(GATE))
    material = pd.read_parquet(bind(TEST_FEATURES), columns=KEY + list(FEATURES))
    if gate.duplicated(KEY).any() or material.duplicated(KEY).any():
        raise ValueError("duplicate original-candidate or materialized-feature key")
    left = gate.merge(material, on=KEY, how="left", validate="one_to_one", indicator=True)
    summary = gate.copy()
    summary["materialized_feature_row_present"] = left._merge.eq("both").to_numpy()
    summary["materialized_32_finite"] = np.isfinite(left[list(FEATURES)].to_numpy(float)).all(axis=1)
    available = panel_2026[KEY + ["new_buy_eligible", "context_only_if_held"]].rename(columns={"new_buy_eligible": "qualified_new_buy_available", "context_only_if_held": "qualified_held_only_available"})
    summary = summary.merge(available, on=KEY, how="left", validate="one_to_one", indicator=True)
    summary["qualified_source_context_present"] = summary._merge.eq("both")
    summary = summary.drop(columns="_merge")
    for column in ["qualified_new_buy_available", "qualified_held_only_available"]:
        summary[column] = summary[column].fillna(False).astype(bool)
    summary["proven_ineligible"] = summary.final_input_gate.str.startswith("PROVEN")
    if (summary.qualified_new_buy_available & summary.proven_ineligible).any():
        raise ValueError("qualified source contains a proven-ineligible candidate")
    summary["qualification_status"] = np.select(
        [summary.qualified_new_buy_available, summary.proven_ineligible],
        ["QUALIFIED_INPUT_SUBSET", "PROVEN_INELIGIBLE"], default="UNKNOWN_INPUT_QUALIFICATION",
    )
    write_frame(directory / "full_candidate_input_gate.parquet", summary)
    summary[KEY + ["quarter", "cusip", "final_input_gate", "qualification_status", "materialized_feature_row_present", "materialized_32_finite", "qualified_source_context_present", "qualified_new_buy_available"]].to_csv(directory / "full_candidate_input_coverage.csv", index=False, encoding="utf-8-sig")
    OUTPUTS[str((directory / "full_candidate_input_coverage.csv").relative_to(ROOT))] = sha256_file(directory / "full_candidate_input_coverage.csv")
    daily = summary.groupby(["signal_date", "quarter"], sort=True).agg(
        original_candidates=("ticker", "size"), qualified_current_pool=("qualified_new_buy_available", "sum"),
        proven_ineligible=("proven_ineligible", "sum"), materialized_32_finite=("materialized_32_finite", "sum"),
    ).reset_index()
    daily["unknown_candidates"] = daily.original_candidates - daily.qualified_current_pool - daily.proven_ineligible
    if not daily.unknown_candidates.ge(0).all():
        raise ValueError("invalid full-candidate coverage partition")
    write_frame(directory / "daily_full_pool_coverage.parquet", daily)
    qual_coverage = pd.read_csv(bind(QUAL / "coverage.csv"))
    if int(daily.unknown_candidates.sum()) != int(qual_coverage.unknown_candidates.sum()):
        raise ValueError("left-joined original-candidate partition differs from upstream qualification receipt")
    metadata_2026 = {
        "year": 2026, "signal_start": "2026-01-01", "signal_end": "2026-09-22",
        "terminal_valuation": "2026-09-24", "stage": "final",
        "candidate_rows": len(panel_2026), "new_buy_rows": int(panel_2026.new_buy_eligible.sum()),
        "held_only_rows": int(panel_2026.context_only_if_held.sum()),
        "original_candidate_rows": len(summary), "unknown_candidate_rows": int(daily.unknown_candidates.sum()),
        "proven_ineligible_rows": int(daily.proven_ineligible.sum()),
        "materialized_feature_row_present": int(summary.materialized_feature_row_present.sum()),
        "materialized_32_finite_rows": int(summary.materialized_32_finite.sum()),
        "missing_or_nonfinite_32_rows": int((~summary.materialized_32_finite).sum()),
        "complete_original_pool_signal_days": int(daily.unknown_candidates.eq(0).sum()),
        "full_original_pool_test_status": "BLOCKED_UNKNOWN_INPUTS",
        "formal_full_pool_test_allowed": False, "blind_test": False,
        "scope": "retrospectively qualified input subset of the existing 24-manager eligible Top100 union",
        "known_glw_conflict_rows": int(conflict.sum()),
        "known_glw_conflict_not_resolved_by_saved_price_warning": True,
        "frozen_subset_replay_is_diagnostic_only": True,
        "unknown_is_not_proven_ineligible": True,
        "original_gate_reason_counts": {str(k): int(v) for k, v in gate.final_input_gate.value_counts(dropna=False).items()},
    }
    write_json(directory / "METADATA.json", metadata_2026)

    # These are rule implementations and exposure evidence; no old outcome data are ingested.
    rule_sources = [
        SOURCE / "scripts/run_rebuild.py",
        Path("D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/integrity_rebuild_v17b.py"),
        Path("D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/eligibility_v17b.py"),
    ]
    for path in rule_sources:
        bind(path)
    exposure_path = WS / "a2_capacity_in_training_paired_20260927/DATA_DEPENDENCY.md"
    exposure = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "2026_is_previously_exposed_historical_evaluation": True,
        "pristine_holdout_restored": False,
        "prior_exposure_source": "upstream EXPERIMENT_CONTRACT.md and audit/INPUT_AUDIT.json explicitly acknowledge previously observed 2025/2026 windows",
        "current_input_audit_incident": {
            "path": str(exposure_path), "sha256": sha256_file(exposure_path),
            "reason_read": "trace referenced BYND/GLW input qualification and accounting dependency limits",
            "unintended_content": "referenced static input dependency document also contained old 2025/2026 strategy-return and capacity summaries",
            "strategy_outcome_files_opened": 0,
            "used_for_candidate_parameter_horizon_seed_weight_selection": False,
            "handling": "recorded exposure; no candidate, parameter, horizon, seed or weighting expansion from these values",
        },
        "this_preparation": {"model_fit_calls": 0, "strategy_replays": 0, "existing_2026_strategy_outcome_files_read": 0},
    }
    write_json(ROOT / "EXPOSURE_HISTORY.json", exposure)
    audit = {
        "status": "PREPARED_AVAILABLE_POOL_WITH_FORMAL_2026_FULL_POOL_BLOCKED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "model_fit_calls": 0,
        "strategy_replays": 0, "existing_2026_strategy_outcome_files_read": 0,
        "feature_order": list(FEATURES), "feature_count": len(FEATURES),
        "prediction_target": "uncosted affine-index return from signal t+1 session open to t+2 session open",
        "training_target_column": "y_train", "original_target_column": "y_next_open",
        "training_clip_abs": TRAIN_CLIP, "evaluation_return_clipping": False,
        "sampling": {"budget_per_stage": MAX_TRAIN_KEYS, "seed": SEED,
                     "rule": "equal quotas for every mature signal date; limited dates redistribute; SHA256(seed|ISO date|ticker) ascending within date",
                     "weights": "mean-one weights; each selected signal date has equal total training weight",
                     "depends_on_outcomes": False},
        "stages": stages,
        "oof": {"validation_fusion_years": [2024], "final_fusion_years": [2024, 2025],
                "base_fit_for_2024": "development; signal/label_end strictly before 2024-01-01",
                "base_fit_for_2025": "validation; signal/label_end strictly before 2025-01-01",
                "meta_label_end_before_year_following_oof": True},
        "pre2026": {"full_available_rows": len(pre), "signal_days": int(pre.signal_date.nunique()),
                    "min_signal": str(pre.signal_date.min().date()), "max_signal": str(pre.signal_date.max().date()),
                    "missing_or_immature_labels_retained_for_inference": int((~pre.label_available).sum()),
                    "upstream_entire_available_pool_key_equality": True,
                    "signal_rows_filtered_by_future_label_availability": False},
        "pool_rule": {
            "precise_original_membership": "24 managers excluding situational_awareness; per-manager per-quarter eligible operating-company-equity holdings ranked by disclosed USD value descending, CUSIP ascending; Top100 then CUSIP union",
            "not_top40": True, "not_entire_manager_stock_holdings_union": True,
            "Top20_protected_core": "upstream union ordering protection only; no upstream Top20 candidate truncation",
            "historical_900_cap": "present in code; upstream asserts no members removed by this cap",
            "eligibility": "no put/call; SH type; reject warrants/units/rights/preferred/debt/convertible/option and fund products; allow ordinary/common/ADR/ADS/GDR/REIT classes",
            "asof_clock": "latest publicly filed quarter effective on the fifth subsequent QQQ session; previous effective quarter persists until next activation",
            "current_available_training_pool": "legacy resolved/static-validated identity and 121 consecutive QQQ sessions plus 32 finite signal features",
            "unresolved_original_identity": "legacy source inner-joined away unresolved/static-unvalidated identities; this does not prove economic ineligibility or eliminate survivorship bias",
            "same_old_A2_TOP20": False,
        },
        "evaluation_2025": metadata_2025, "evaluation_2026": metadata_2026,
        "physical_isolation": {"training_data": "input/pre2026.parquet and input/stage_*_keys.parquet",
                               "risk_training_prices": "input/pre2026_prices.parquet strictly before 2026",
                               "evaluation_2026": "input/eval_2026; stage_frame never opens this directory"},
        "limitations": [
            "Available upstream input pool is not the complete unfiltered 24-manager stock-holdings union.",
            "Original 2026 candidate input qualification remains incomplete; unknown rows are recorded, not recoded as ineligible.",
            "2026 subset qualification is retrospective; raw arrival times and survivorship-free full-universe certification are not established.",
            "Prices use affine research-index units; not raw tradable shares or certified shareholder total return.",
            "GLW 2026-02-26 adjusted-feature event-date conflict remains recorded; saved warning=False does not resolve it.",
            "2025/2026 were previously exposed; new freezing cannot restore an untouched holdout.",
        ],
        "source_sha256": SOURCES, "output_sha256": OUTPUTS.copy(),
    }
    write_json(ROOT / "INPUT_AUDIT.json", audit)
    return audit


def verify_existing() -> dict:
    audit = json.loads((ROOT / "INPUT_AUDIT.json").read_text(encoding="utf-8"))
    for path, expected in audit["source_sha256"].items():
        if sha256_file(path) != expected:
            raise ValueError(f"frozen source bytes changed: {path}")
    for relative, expected in audit["output_sha256"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen prepared input bytes changed: {relative}")
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    audit = verify_existing() if args.verify else prepare()
    print(json.dumps({"status": audit["status"], "stages": audit["stages"],
                      "evaluation_2026": audit["evaluation_2026"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
