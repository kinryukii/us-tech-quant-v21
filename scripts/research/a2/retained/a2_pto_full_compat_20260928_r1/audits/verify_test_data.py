"""Read-only independent verification of frozen test input construction.

Writes only its new verification receipt. No training, model loading, prediction,
account replay, or performance-result reads occur here.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT.parent
DATA = ROOT / "data"
KEY = ["signal_date", "ticker"]
CHECKS = {}
HASHES = {}


def sha(path):
    path = Path(path).resolve()
    if str(path) not in HASHES:
        with path.open("rb") as stream:
            HASHES[str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    return HASHES[str(path)]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    CHECKS[name] = True


def keyed(frame):
    return frame.sort_values(KEY).reset_index(drop=True)


def verify():
    freeze = read_json(ROOT / "FREEZE.json")
    receipt = read_json(DATA / "TEST_DATA_RECEIPT.json")
    registry = read_json(ROOT / "REGISTRY.json")
    check("all_learning_frozen_pre2026_with_explicit_complete_state", freeze["status"] == "FROZEN_ALL_LEARNING_PRE2026"
          and freeze["all_learning_completed"] is True and freeze["fit_2026_rows"] == 0
          and freeze["test_2026_inference_before_freeze"] == 0
          and freeze["test_2026_account_replays_before_freeze"] == 0
          and freeze["future_learning_or_candidate_search_authorized"] is False)
    expected_coverage = dict(base_members=31, member_stages=93, actual_supervised_estimators=129,
                             prediction_streams=75, adapter_stages=62, fusion_stages=88,
                             risk_specification_stages=24, rl_policy_stages=8, pto_strategies=11088)
    check("complete_frozen_learning_and_strategy_registry_coverage", freeze["coverage"] == expected_coverage
          and len(registry["streams"]) == 75 and len(registry["strategies"]) == 11088
          and len(freeze["artifact_sha256"]) == 663)
    check("freeze_binds_input_producer_and_registry", all(name in freeze["artifact_sha256"]
          for name in ["prepare_data.py", "common.py", "REGISTRY.json", "COMPATIBILITY_MATRIX.csv"]))
    for name, expected in freeze["artifact_sha256"].items():
        path = Path(name)
        if not path.is_absolute():
            path = ROOT / path
        check("frozen_artifact_hash:" + name, sha(path) == expected)
    check("test_built_after_full_batch_freeze", pd.Timestamp(receipt["created_utc"]) >= pd.Timestamp(freeze["created_utc"]))
    check("test_receipt_binds_exact_freeze_and_unchanged_producer", receipt["freeze_receipt_sha256"] == sha(ROOT / "FREEZE.json")
          and receipt["producer_sha256"] == sha(ROOT / "prepare_data.py")
          and receipt["producer_sha256"] == freeze["artifact_sha256"]["prepare_data.py"])
    for path, expected in receipt["input_sha256"].items():
        check("input_source_hash:" + path, sha(path) == expected)
    for name, expected in receipt["output_sha256"].items():
        check("test_output_hash:" + name, sha(DATA / name) == expected)
    pre_receipt = read_json(DATA / "PRE_DATA_RECEIPT.json")
    check("pre_outputs_preserved_after_test_construction", all(sha(DATA / name) == expected
          for name, expected in pre_receipt["output_sha256"].items()))
    features = receipt["feature_order"]
    check("fixed_32_features_match_pre_contract", len(features) == 32 and features == pre_receipt["feature_order"])

    full = pd.read_parquet(DATA / "test_full_candidates.parquet")
    context = pd.read_parquet(DATA / "test.parquet")
    prices = pd.read_parquet(DATA / "test_prices.parquet")
    calendar = pd.read_parquet(DATA / "test_calendar.parquet")
    coverage = pd.read_csv(DATA / "FULL_POOL_COVERAGE.csv", parse_dates=["signal_date"])
    original = pd.read_parquet(WS / "a2_ensemble_attribution_20260928_r1/qualification_all_candidates.parquet")
    old_context = pd.read_parquet(WS / "a2_qualification_holdings_v1_20260927/data/test_features_context.parquet")
    old_prices = pd.read_parquet(WS / "a2_qualification_holdings_v1_20260927/data/test_prices.parquet")
    material = pd.read_parquet(WS / "a2_strict_method_retrain_20260926/test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet",
                               columns=KEY + features)
    check("full_and_safe_context_keys_are_unique_nonnull", all(not f.duplicated(KEY).any()
          and f[KEY].notna().all().all() for f in [full, context]))
    check("all_111868_original_candidate_keys_remain_active_and_preserved", len(full) == len(original) == 111868
          and full.original_frozen_candidate_key.all() and full.membership_active.all()
          and set(map(tuple, full[KEY].to_numpy())) == set(map(tuple, original[KEY].to_numpy())))
    pd.testing.assert_frame_equal(keyed(full[original.columns]), keyed(original), check_dtype=False)
    check("all_original_candidate_evidence_fields_unchanged", True)
    unknown = full.original_qualification_status.eq("UNKNOWN")
    check("all_47271_original_unknown_rows_remain_unknown_and_cannot_buy", int(unknown.sum()) == 47271
          and full.loc[unknown, "qualification_status"].astype(str).str.startswith("UNKNOWN").all()
          and not full.loc[unknown, "new_buy_eligible"].any())
    joined_material = full[KEY].merge(material, on=KEY, how="left", validate="one_to_one", indicator=True)
    pd.testing.assert_frame_equal(keyed(full[KEY + features]), keyed(joined_material[KEY + features]), check_dtype=False)
    check("complete_candidate_numeric_features_are_exact_left_join", True)
    finite = np.isfinite(full[features].to_numpy(float)).all(axis=1)
    check("numeric_presence_and_finiteness_flags_match_actual_rows", np.array_equal(full.numeric_32_finite.to_numpy(), finite)
          and np.array_equal(full.numeric_feature_row_present.to_numpy(), joined_material._merge.eq("both").to_numpy()))
    check("unknown_numeric_values_do_not_upgrade_qualification", int((unknown & full.numeric_32_finite).sum()) == 43863
          and not full.loc[unknown & full.numeric_32_finite, "new_buy_eligible"].any())
    expected_buy = full.membership_active & full.qualification_status.eq("QUALIFIED") & full.numeric_32_finite
    check("buy_eligibility_requires_membership_qualified_status_and_all_32_finite", expected_buy.equals(full.new_buy_eligible))
    glw = full.ticker.eq("GLW") & full.signal_date.eq(pd.Timestamp("2026-02-26"))
    check("sole_new_qualification_change_is_explicit_glw_conflict_mask", int(glw.sum()) == 1
          and full.loc[glw, "qualification_status"].eq("UNKNOWN_GLW_EVENT_DATE_CONFLICT").all()
          and full.loc[~glw, "qualification_status"].equals(full.loc[~glw, "original_qualification_status"]))
    check("safe_context_has_62392_buy_rows_and_83_holding_only_rows", len(context) == 62475
          and int(context.new_buy_eligible.sum()) == 62392 and int(context.context_only_if_held.sum()) == 83
          and (context.new_buy_eligible ^ context.context_only_if_held).all()
          and np.isfinite(context[features].to_numpy(float)).all())
    pd.testing.assert_frame_equal(keyed(context.loc[context.new_buy_eligible, KEY + features]),
                                  keyed(full.loc[expected_buy, KEY + features]), check_dtype=False)
    pd.testing.assert_frame_equal(keyed(context.loc[context.context_only_if_held, KEY + features]),
                                  keyed(old_context.loc[old_context.context_only_if_held, KEY + features]), check_dtype=False)
    check("safe_buy_and_holding_feature_rows_match_independent_source_keys", True)
    check("holding_only_rows_have_no_new_buy_permission", not context.loc[context.context_only_if_held, "new_buy_eligible"].any()
          and not context.loc[context.context_only_if_held, "membership_active"].any())
    check("inference_context_contains_no_forward_label_or_target_columns", not set(context.columns).intersection(
          {"y_next_open", "target", "next_open", "following_open", "execution_date", "label_end_date", "label_available"}))

    timing = pd.read_csv(WS / "a2_latest_effective_joint_20260927/data/quarter_timing.csv",
                         parse_dates=["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"])
    quarter_members = pd.read_parquet(Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe/quarterly_universe_members.parquet"))
    q2 = WS / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1"
    initial = pd.read_parquet(q2 / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
    restated = pd.read_parquet(DATA / "Q2_RESTATEMENT_MEMBERS.parquet")
    q2_audit = read_json(DATA / "Q2_RESTATEMENT_AUDIT.json")
    source_q2 = pd.read_parquet(q2 / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet")
    intake = read_json(q2 / "Q2_INTAKE_AUDIT.json")
    accession = intake["citadel_restatement_accession"]
    chosen = pd.concat([source_q2.loc[~source_q2.accession.eq(accession) & ~source_q2.manager_id.eq("citadel")],
                        source_q2.loc[source_q2.accession.eq(accession)]], ignore_index=True)
    check("citadel_restatement_is_one_version_replacement_with_original_24_managers", chosen.manager_id.nunique() == 24
          and chosen.groupby("manager_id").accession.nunique().eq(1).all())
    original_rule_path = Path("D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/integrity_rebuild_v17b.py")
    tree = ast.parse(original_rule_path.read_text(encoding="utf-8"))
    names = {"aggregate_eligible_for_ranking", "select_top100", "build_universe"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = dict(pd=pd, np=np, TOP_N=100, PROTECTED_TOP_N=20, HARD_CAP=900,
                 require=lambda ok, code, detail: check("original_rule:" + code + str(detail), ok))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(original_rule_path), "exec"), scope)
    universe_timing = pd.DataFrame([dict(quarter="2026Q2", report_date=pd.Timestamp("2026-06-30"),
                                       effective_date=pd.Timestamp("2026-09-10"), expiry_date=pd.Timestamp("2026-12-31"))])
    rebuilt = scope["build_universe"](scope["select_top100"](scope["aggregate_eligible_for_ranking"](chosen)), universe_timing)
    identity = pd.read_parquet(Path("D:/us-tech-quant-results/13f_pit_v1/data/universe/security_identity_v17c_transport.parquet"))
    identity["cusip"] = identity.cusip.astype(str).str.upper().str.strip()
    identity = identity.loc[identity.mapping_status.eq("RESOLVED") & identity.transport_static_validated.fillna(False).astype(bool)
                            & identity.ticker.fillna("").astype(str).str.strip().ne("")
                            & identity.moomoo_transport_code.fillna("").astype(str).str.strip().ne(""),
                            ["cusip", "ticker", "moomoo_transport_code", "mapping_source", "mapping_confidence"]].drop_duplicates("cusip")
    rebuilt = rebuilt.merge(identity, on="cusip", how="inner", validate="many_to_one")
    for column in ["ticker", "moomoo_transport_code"]:
        rebuilt[column] = rebuilt[column].astype(str).str.upper().str.strip()
    rebuilt = rebuilt.sort_values(["universe_rank", "cusip"], kind="mergesort").drop_duplicates("ticker").drop_duplicates("moomoo_transport_code").head(900)
    pd.testing.assert_frame_equal(rebuilt[restated.columns].reset_index(drop=True), restated.reset_index(drop=True), check_dtype=False)
    check("restated_members_reproduced_from_original_rules_and_source_rows", True)
    check("initial_and_restatement_share_same_575_ticker_cusip_members", len(initial) == len(restated) == 575
          and set(zip(initial.ticker, initial.cusip)) == set(zip(restated.ticker, restated.cusip)))
    actual_clock = []
    for day, group in full.groupby("signal_date", sort=True):
        eligible = timing.loc[timing.quarter_effective_date.le(day) & timing.latest_filing_date.lt(day)].sort_values("quarter_effective_date")
        check("published_effective_pool_exists:" + str(day.date()), len(eligible) > 0)
        clock = eligible.iloc[-1]
        restatement_active = clock.quarter == "2026Q2" and day >= pd.Timestamp("2026-09-10")
        state = "CITADEL_RESTATED" if restatement_active else "INITIAL_24" if clock.quarter == "2026Q2" else "ORIGINAL_EFFECTIVE_QUARTER"
        members = restated if restatement_active else initial if clock.quarter == "2026Q2" else quarter_members.loc[quarter_members.quarter.eq(clock.quarter)]
        effective = pd.Timestamp("2026-09-10") if restatement_active else clock.quarter_effective_date
        filed = pd.Timestamp("2026-09-02") if restatement_active else clock.latest_filing_date
        check("independent_pool_and_version_clock:" + str(day.date()), group.asof_quarter.eq(clock.quarter).all()
              and group.pool_version_state.eq(state).all() and group.pool_version_effective_date.eq(effective).all()
              and group.pool_version_latest_filing_date.eq(filed).all()
              and set(zip(group.ticker, group.active_pool_cusip)) == set(zip(members.ticker, members.cusip)))
        actual_clock.append(dict(signal_date=str(day.date()), quarter=clock.quarter, pool_version_state=state,
                                 version_effective_date=str(effective.date()), candidates=len(group)))
    check("all_pool_version_sources_are_public_and_effective_by_signal", full.pool_version_latest_filing_date.lt(full.signal_date).all()
          and full.pool_version_effective_date.le(full.signal_date).all()
          and full.report_date.lt(full.latest_filing_date).all())
    for filed, effective in [("2026-08-14", "2026-08-21"), ("2026-09-02", "2026-09-10")]:
        future_sessions = calendar.loc[calendar.trade_date.gt(pd.Timestamp(filed)), "trade_date"]
        check("fifth_subsequent_qqq_session:" + filed, future_sessions.iloc[4] == pd.Timestamp(effective))
    boundary_cases = [("2026-01-02", "2025Q3", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-02-18", "2025Q3", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-02-24", "2025Q3", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-02-25", "2025Q4", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-05-15", "2025Q4", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-05-21", "2025Q4", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-05-22", "2026Q1", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-08-14", "2026Q1", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-08-20", "2026Q1", "ORIGINAL_EFFECTIVE_QUARTER"),
                      ("2026-08-21", "2026Q2", "INITIAL_24"),
                      ("2026-09-02", "2026Q2", "INITIAL_24"),
                      ("2026-09-09", "2026Q2", "INITIAL_24"),
                      ("2026-09-10", "2026Q2", "CITADEL_RESTATED")]
    for day, quarter, state in boundary_cases:
        g = full.loc[full.signal_date.eq(pd.Timestamp(day))]
        check("carry_and_exact_effective_boundary:" + day, len(g) > 0 and g.asof_quarter.eq(quarter).all() and g.pool_version_state.eq(state).all())

    check("price_keys_unique_nonnull_and_history_retained", not prices.duplicated(["ticker", "trade_date"]).any()
          and prices[["ticker", "trade_date"]].notna().all().all() and len(prices) == len(old_prices) == 211482
          and prices.trade_date.min() == pd.Timestamp("2025-06-02") and prices.trade_date.max() == pd.Timestamp("2026-09-24"))
    unchanged_columns = [c for c in old_prices.columns if c != "price_quality_warning"]
    pd.testing.assert_frame_equal(prices[unchanged_columns], old_prices[unchanged_columns], check_dtype=False)
    check("all_source_prices_and_coordinates_unchanged", True)
    mask = prices.ticker.eq("GLW") & prices.trade_date.isin(pd.to_datetime(["2026-02-26", "2026-02-27"]))
    check("only_glw_conflict_prices_gain_conservative_warning", int(mask.sum()) == 2
          and prices.new_batch_glw_conflict_mask.equals(mask)
          and prices.original_price_quality_warning.equals(old_prices.price_quality_warning)
          and prices.price_quality_warning.equals(old_prices.price_quality_warning | mask))
    old_calendar = pd.read_parquet(WS / "a2_latest_effective_joint_20260927/data/calendar.parquet")
    pd.testing.assert_frame_equal(calendar, old_calendar.loc[old_calendar.is_test].reset_index(drop=True))
    check("calendar_is_exact_source_test_sessions_unique_sorted", len(calendar) == 183
          and calendar.trade_date.is_unique and calendar.trade_date.is_monotonic_increasing
          and calendar.trade_date.min() == pd.Timestamp("2026-01-02") and calendar.trade_date.max() == pd.Timestamp("2026-09-24")
          and calendar.is_test.all())
    check("all_181_signal_days_have_next_and_following_calendar_sessions", full.signal_date.nunique() == 181
          and set(full.signal_date.unique()).issubset(set(calendar.loc[calendar.is_signal, "trade_date"].unique()))
          and all((calendar.trade_date > day).sum() >= 2 for day in full.signal_date.unique()))
    check("all_safe_context_names_have_source_price_history", set(context.ticker).issubset(set(prices.ticker)))
    active = full.loc[full.membership_active]
    recomputed_coverage = active.groupby(["signal_date", "asof_quarter", "pool_version_state"], dropna=False).agg(
        active_candidate_rows=("ticker", "size"), qualified_new_buy_rows=("new_buy_eligible", "sum"),
        finite32_rows=("numeric_32_finite", "sum"), numerical_missing_rows=("numeric_32_finite", lambda s: int((~s).sum())),
        unknown_rows=("qualification_status", lambda s: int(s.astype(str).str.startswith("UNKNOWN").sum())),
        proven_ineligible_rows=("qualification_status", lambda s: int(s.eq("PROVEN_INELIGIBLE").sum()))).reset_index()
    recomputed_coverage["full_pool_input_qualified"] = False
    pd.testing.assert_frame_equal(coverage, recomputed_coverage, check_dtype=False)
    check("coverage_table_counts_independently_recomputed", True)
    check("formal_full_pool_remains_blocked_on_all_181_signal_days", len(coverage) == 181 and (coverage.unknown_rows > 0).all()
          and not coverage.full_pool_input_qualified.any() and not full.formal_full_pool_selection_allowed.any()
          and receipt["full_pool_formal_performance_allowed"] is False and freeze["formal_full_pool_status"] == "BLOCKED_DATA")
    operation_path = DATA / "test_operational_exit_evidence.csv"
    check("operational_exit_evidence_exact_source_copy", sha(operation_path) == sha(WS / "a2_qualification_holdings_v1_20260927/data/operational_exit_evidence.csv"))
    operations = pd.read_csv(operation_path)
    check("dated_exas_unsettled_right_has_no_cash_credit_permission", len(operations) == 1
          and operations.ticker.iloc[0] == "EXAS" and "NO_CASH_CREDIT" in operations.reason.iloc[0]
          and pd.Timestamp(operations.known_at.iloc[0]) == pd.Timestamp("2026-03-23T13:00:16+00:00")
          and pd.Timestamp(operations.effective_date.iloc[0]) == pd.Timestamp("2026-03-23"))
    check("data_preparation_declares_no_learning_prediction_or_replay", all(receipt[key] == 0 for key in ["new_fit_calls", "new_predictions", "new_replays"]))
    check("receipt_counts_match_independent_outputs", receipt["all_saved_rows"] == len(full)
          and receipt["qualified_context_rows"] == len(context) and receipt["qualified_new_buy_rows"] == int(context.new_buy_eligible.sum())
          and receipt["holding_only_context_rows"] == int(context.context_only_if_held.sum())
          and receipt["original_unknown_rows_preserved"] == int(unknown.sum())
          and receipt["formal_full_pool_qualified_days"] == 0 and receipt["calendar_days"] == len(calendar))
    return {
        "status": "PASS_FROZEN_TEST_INPUTS_FORMAL_FULL_POOL_BLOCKED_DATA",
        "created_utc": datetime.now(timezone.utc).isoformat(), "checks_passed": len(CHECKS), "checks": CHECKS,
        "freeze_sha256": sha(ROOT / "FREEZE.json"), "test_data_receipt_sha256": sha(DATA / "TEST_DATA_RECEIPT.json"),
        "producer_sha256_unchanged": sha(ROOT / "prepare_data.py"), "frozen_artifacts_verified": len(freeze["artifact_sha256"]),
        "full_candidate_rows": len(full), "original_unknown_rows": int(unknown.sum()),
        "original_unknown_finite32_rows": int((unknown & full.numeric_32_finite).sum()),
        "qualified_context_rows": len(context), "qualified_new_buy_rows": int(context.new_buy_eligible.sum()),
        "holding_only_rows": int(context.context_only_if_held.sum()), "signal_days": full.signal_date.nunique(),
        "calendar_days": len(calendar), "price_rows": len(prices), "glw_signal_rows_masked": int(glw.sum()),
        "glw_price_rows_masked": int(mask.sum()), "formal_full_pool_status": "BLOCKED_DATA",
        "formal_full_pool_qualified_days": 0, "ready_for_qualified_context_inference": True,
        "full_pool_formal_performance_allowed": False, "quarter_version_clock_by_signal": actual_clock,
        "new_fit_calls": 0, "new_predictions": 0, "new_account_replays": 0, "economic_results_read": 0,
        "verified_sha256": HASHES, "verification_source_sha256": sha(Path(__file__)),
        "scope": "Qualified-context diagnostic inference only. Original UNKNOWN evidence and formal full-pool blockage remain preserved.",
        "inherited_limits": receipt["inherited_limits"],
    }


if __name__ == "__main__":
    output = DATA / "TEST_DATA_VERIFICATION.json"
    if output.exists():
        raise RuntimeError("REFUSE_OVERWRITE_EXISTING_TEST_DATA_VERIFICATION")
    try:
        result = verify()
    except Exception as error:
        failed = dict(status="FAILED_FROZEN_TEST_INPUT_VERIFICATION", failure_type=type(error).__name__,
                      failure_reason=str(error), traceback=traceback.format_exc(), completed_checks=CHECKS)
        (DATA / "TEST_DATA_VERIFICATION_FAILED.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        raise
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ["status", "checks_passed", "full_candidate_rows", "qualified_context_rows", "formal_full_pool_qualified_days"]}, ensure_ascii=False))
