"""Stage-isolated, append-only A2 inputs for Predict-then-Optimize.

The pre stage never opens a 2026 feature, price, qualification, or result file.
The test stage requires a batch freeze receipt, retains every original candidate
key, and never turns an unknown input into an eligible security merely because
its numerical features exist. No fit, calibration, prediction, or replay here.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
OUT = ROOT / "data"
LATEST = WS / "a2_latest_effective_joint_20260927"
QUALIFIED = WS / "a2_qualification_holdings_v1_20260927"
STRICT = WS / "a2_strict_method_retrain_20260926"
STAGE = STRICT / "test2026_stage"
Q2 = WS / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1"
ORIGINAL = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1")
V17ROOT = Path("D:/us-tech-quant-results/13f_pit_v1")
KEY = ["signal_date", "ticker"]
FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120",
    "realized_vol_5d", "realized_vol_10d", "realized_vol_20d", "realized_vol_60d",
    "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d", "distance_from_high_60d",
    "distance_from_low_20d", "distance_from_low_60d", "max_drawdown_20d", "max_drawdown_60d",
    "avg_volume_20d", "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d",
    "avg_dollar_volume_20d",
]
SOURCES: dict[str, str] = {}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bind(path):
    path = Path(path).resolve()
    digest = sha(path)
    if str(path) in SOURCES and SOURCES[str(path)] != digest:
        raise RuntimeError(f"SOURCE_CHANGED_DURING_PREPARATION: {path}")
    SOURCES[str(path)] = digest
    return path


def read_json(path):
    return json.loads(bind(path).read_text(encoding="utf-8-sig"))


def read_parquet(path, **kwargs):
    return pd.read_parquet(bind(path), **kwargs)


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str,
                                    allow_nan=False) + "\n", encoding="utf-8")


def require(condition, reason):
    if not bool(condition):
        raise RuntimeError(reason)


def validate_keys(frame, name):
    require(not frame.duplicated(KEY).any(), f"{name}_DUPLICATE_KEYS")
    require(frame.signal_date.notna().all() and frame.ticker.notna().all(), f"{name}_NULL_KEYS")


def feature_registry():
    registry = read_json(LATEST / "data/JOINT_DATA_AUDIT.json")
    require(registry["features"] == FEATURES, "FEATURE_ORDER_CHANGED")
    return registry


def prepare_pre():
    """Materialize only physical pre-2026 inputs; zero 2026 row reads."""
    receipt_path = OUT / "PRE_DATA_RECEIPT.json"
    require(not receipt_path.exists(), "PRE_DATA_ALREADY_PREPARED_PRESERVE_OLD_OUTPUTS")
    feature_registry()
    pre = read_parquet(LATEST / "data/pre2026_joint_context.parquet")
    px = read_parquet(STRICT / "results/pre2026_original_price_coordinate.parquet")
    validate_keys(pre, "PRE")
    require(len(pre) == 313668 and pre.signal_date.nunique() == 752, "PRE_CONTEXT_SHAPE_CHANGED")
    require(pre.signal_date.lt("2026-01-01").all(), "PRE_FEATURE_DATE_LEAKAGE")
    require(px.trade_date.lt("2026-01-01").all(), "PRE_PRICE_DATE_LEAKAGE")
    require(np.isfinite(pre[FEATURES].to_numpy(float)).all(), "PRE_NONFINITE_FEATURES")
    require(pre.new_buy_eligible.all(), "LATEST_EFFECTIVE_PRE_ELIGIBILITY_CHANGED")
    require(pre.quarter_effective_date.le(pre.signal_date).all(), "FUTURE_QUARTER_USED")
    require(pre.latest_filing_date.lt(pre.signal_date).all(), "FUTURE_FILING_USED")
    require((pre.next_quarter_effective_date.isna()
             | pre.signal_date.lt(pre.next_quarter_effective_date)).all(), "SUPERSEDED_QUARTER_USED")
    mature = pre.loc[pre.label_available]
    require(mature.label_end_date.lt("2026-01-01").all(), "PRE_LABEL_DATE_LEAKAGE")
    require(mature.execution_date.gt(mature.signal_date).all()
            and mature.label_end_date.gt(mature.execution_date).all(), "PRE_LABEL_CLOCK_VIOLATION")
    require(np.allclose(mature.y_next_open.to_numpy(float),
                        mature.following_open.to_numpy(float) / mature.next_open.to_numpy(float) - 1,
                        atol=1e-12, rtol=0), "PRE_LABEL_VALUE_MISMATCH")
    require(not px.duplicated(["trade_date", "ticker"]).any(), "PRE_PRICE_DUPLICATE_KEYS")
    calendar = pd.DataFrame({"trade_date": sorted(px.loc[px.ticker.eq("QQQ"), "trade_date"].unique())})
    calendar["is_signal"] = calendar.trade_date.isin(pre.signal_date.unique())
    require(pre.signal_date.isin(calendar.trade_date).all(), "PRE_CALENDAR_MISSING_SIGNALS")
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [OUT / "pre.parquet", OUT / "pre_prices.parquet", OUT / "pre_calendar.parquet"]
    require(not any(p.exists() for p in paths), "PARTIAL_PRE_OUTPUT_REQUIRES_INSPECTION")
    for path, frame in zip(paths, [pre, px, calendar]):
        frame.to_parquet(path, index=False)
    receipt = {
        "status": "PASS_PHYSICAL_PRE2026_ONLY", "created_utc": datetime.now(timezone.utc).isoformat(),
        "producer_sha256": sha(Path(__file__)), "feature_order": FEATURES,
        "context_rows": len(pre), "signal_days": int(pre.signal_date.nunique()),
        "tickers": int(pre.ticker.nunique()), "signal_first": str(pre.signal_date.min().date()),
        "signal_last": str(pre.signal_date.max().date()),
        "rows_by_year": {str(k): int(v) for k, v in pre.groupby(pre.signal_date.dt.year).size().items()},
        "mature_label_rows": len(mature), "missing_label_rows_retained": int((~pre.label_available).sum()),
        "label_end_max": str(mature.label_end_date.max().date()),
        "label_contract": "Signal close features; next QQQ session open execution; following QQQ session open end. y_next_open is one-session gross affine price-index return. Costs enter common optimizer/account utility.",
        "old_multihorizon_target_not_used_as_feature_or_shared_pto_label": True,
        "latest_effective_rule": "Most recent published 13F quarter whose original fifth-next-session activation is reached; retain preceding quarter until then.",
        "full_13f_pool_formal_certification": False,
        "inherited_pre_limits": ["Static historical identity", "Missing-price and 121-session selection in the original daily eligible universe", "Actual historical supplier arrival/version timestamps unproven", "Affine research price index is not shareholder total return"],
        "prices": {"rows": len(px), "tickers": int(px.ticker.nunique()),
                   "first": str(px.trade_date.min().date()), "last": str(px.trade_date.max().date())},
        "calendar_days": len(calendar), "training_2026_rows_read": 0,
        "new_fit_calls": 0, "new_predictions": 0, "new_replays": 0,
        "input_sha256": SOURCES.copy(), "output_sha256": {p.name: sha(p) for p in paths},
    }
    require(all(sha(p) == h for p, h in SOURCES.items()), "PRE_SOURCE_MUTATION")
    save_json(receipt_path, receipt)
    print(json.dumps({k: receipt[k] for k in ["status", "context_rows", "signal_days", "mature_label_rows", "training_2026_rows_read"]}, ensure_ascii=False))


def frozen_v17b_rules():
    """Reuse exactly the three pure original universe-rule functions.

    Loading their AST avoids importing original scripts, mutable global paths,
    network validators, or writing __pycache__ into an old frozen directory.
    """
    path = bind(V17ROOT / "scripts/v17b/integrity_rebuild_v17b.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {"aggregate_eligible_for_ranking", "select_top100", "build_universe"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes} == names, "ORIGINAL_UNIVERSE_RULE_FUNCTIONS_MISSING")
    scope = {"pd": pd, "np": np, "TOP_N": 100, "PROTECTED_TOP_N": 20, "HARD_CAP": 900,
             "require": lambda c, code, detail: require(c, f"{code}: {detail}")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    return scope


def rebuild_restated_q2():
    """Recompute Top100 union from source rows, replacing Citadel on 09-10."""
    receipt = read_json(STAGE / "fixed_window_binding/Q2_SOURCE_BINDING.json")
    intake = read_json(Q2 / "Q2_INTAKE_AUDIT.json")
    rows = read_parquet(Q2 / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet")
    initial = read_parquet(Q2 / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
    require(sha(Q2 / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet") == receipt["q2_versioned_rows_sha256"], "Q2_VERSIONED_SOURCE_HASH_MISMATCH")
    accession = intake["citadel_restatement_accession"]
    base = rows.loc[~rows.accession.eq(accession)].copy()
    chosen = pd.concat([base.loc[~base.manager_id.eq("citadel")], rows.loc[rows.accession.eq(accession)]], ignore_index=True)
    require(chosen.groupby("manager_id").accession.nunique().eq(1).all()
            and chosen.manager_id.nunique() == 24, "Q2_VERSION_REPLACEMENT_FAILED")
    rules = frozen_v17b_rules()
    timing = pd.DataFrame([{"quarter": "2026Q2", "report_date": pd.Timestamp("2026-06-30"),
                            "effective_date": pd.Timestamp(receipt["citadel_restatement_effective_date"]),
                            "expiry_date": pd.Timestamp("2026-12-31")}])
    universe = rules["build_universe"](rules["select_top100"](rules["aggregate_eligible_for_ranking"](chosen)), timing)
    identity = read_parquet(V17ROOT / "data/universe/security_identity_v17c_transport.parquet")
    require(sha(V17ROOT / "data/universe/security_identity_v17c_transport.parquet") == receipt["security_identity_v17c_sha256"], "Q2_IDENTITY_SOURCE_HASH_MISMATCH")
    identity["cusip"] = identity.cusip.astype(str).str.upper().str.strip()
    resolved = identity.loc[identity.mapping_status.eq("RESOLVED")
                            & identity.transport_static_validated.fillna(False).astype(bool)
                            & identity.ticker.fillna("").astype(str).str.strip().ne("")
                            & identity.moomoo_transport_code.fillna("").astype(str).str.strip().ne(""),
                            ["cusip", "ticker", "moomoo_transport_code", "mapping_source", "mapping_confidence"]].drop_duplicates("cusip")
    members = universe.merge(resolved, on="cusip", how="inner", validate="many_to_one")
    for c in ["ticker", "moomoo_transport_code"]:
        members[c] = members[c].astype(str).str.upper().str.strip()
    members = members.sort_values(["universe_rank", "cusip"], kind="mergesort").drop_duplicates("ticker", keep="first").drop_duplicates("moomoo_transport_code", keep="first").head(900)
    # Independent reproduction of initial membership establishes exact rule reuse.
    initial_timing = timing.assign(effective_date=pd.Timestamp(receipt["initial_effective_date"]))
    original_union = rules["build_universe"](rules["select_top100"](rules["aggregate_eligible_for_ranking"](base)), initial_timing)
    original_members = original_union.merge(resolved, on="cusip", how="inner", validate="many_to_one")
    original_members = original_members.sort_values(["universe_rank", "cusip"], kind="mergesort").drop_duplicates("ticker").drop_duplicates("moomoo_transport_code").head(900)
    require(set(zip(original_members.ticker, original_members.cusip)) == set(zip(initial.ticker, initial.cusip)), "INITIAL_Q2_UNIVERSE_REPRODUCTION_FAILED")
    removed = sorted(set(initial.ticker) - set(members.ticker))
    added = sorted(set(members.ticker) - set(initial.ticker))
    return initial, members, receipt, {"initial_count": len(initial), "restated_count": len(members),
        "removed_tickers": removed, "added_tickers": added,
        "initial_effective_date": receipt["initial_effective_date"],
        "restatement_effective_date": receipt["citadel_restatement_effective_date"],
        "restatement_filed_date": intake["citadel_restatement_filed_date"],
        "restatement_accepted_at": intake["citadel_restatement_accepted_at"],
        "restatement_accession": accession, "old_original_candidate_keys_preserved": True,
        "rule": "Original v17b eligible equity; per manager Top100; protected Top20; conviction-ranked union capped at 900; same resolved identity projection"}


def prepare_test(freeze_receipt):
    """Build frozen inference inputs; do not create any economic performance."""
    require(freeze_receipt is not None, "TEST_REQUIRES_EXPLICIT_BATCH_FREEZE_RECEIPT")
    freeze_path = Path(freeze_receipt).resolve()
    require(freeze_path.is_relative_to(ROOT), "FREEZE_RECEIPT_MUST_BELONG_TO_THIS_NEW_BATCH")
    freeze = read_json(freeze_path)
    require(isinstance(freeze, dict) and freeze.get("status") == "FROZEN_ALL_LEARNING_PRE2026", "INVALID_BATCH_FREEZE_RECEIPT")
    frozen_artifacts = freeze.get("artifact_sha256")
    require(isinstance(frozen_artifacts, dict) and len(frozen_artifacts) > 0, "FREEZE_MISSING_ARTIFACT_HASHES")
    for artifact, expected_sha in frozen_artifacts.items():
        artifact_path = Path(artifact)
        if not artifact_path.is_absolute():
            artifact_path = ROOT / artifact_path
        require(sha(bind(artifact_path)) == expected_sha, f"FROZEN_ARTIFACT_CHANGED: {artifact}")
    receipt_path = OUT / "TEST_DATA_RECEIPT.json"
    require(not receipt_path.exists(), "TEST_DATA_ALREADY_PREPARED_PRESERVE_OLD_OUTPUTS")
    feature_registry()
    full = read_parquet(WS / "a2_ensemble_attribution_20260928_r1/qualification_all_candidates.parquet")
    material = read_parquet(STAGE / "identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet")
    old_context = read_parquet(QUALIFIED / "data/test_features_context.parquet")
    prices = read_parquet(QUALIFIED / "data/test_prices.parquet")
    calendar = read_parquet(LATEST / "data/calendar.parquet")
    calendar = calendar.loc[calendar.is_test].copy().reset_index(drop=True)
    validate_keys(full, "FULL_ORIGINAL_CANDIDATE")
    validate_keys(material, "MATERIALIZED_FEATURE")
    validate_keys(old_context, "OLD_QUALIFIED_CONTEXT")
    require(len(full) == 111868, "ORIGINAL_FULL_KEY_COUNT_CHANGED")
    require(full.current_frozen_unknown.sum() == 47271, "ORIGINAL_UNKNOWN_COUNT_CHANGED")
    initial, restated, q2_receipt, restated_audit = rebuild_restated_q2()
    quarters = pd.read_csv(bind(LATEST / "data/quarter_timing.csv"), parse_dates=["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"])
    quarter_members = read_parquet(ORIGINAL / "universe/quarterly_universe_members.parquet")
    member_cols = ["quarter", "ticker", "cusip", "title_of_class", "moomoo_transport_code"]
    member_by_quarter = {q: g[member_cols] for q, g in quarter_members.groupby("quarter")}
    member_by_quarter["2026Q2"] = initial[member_cols]
    active_days = pd.DataFrame({"signal_date": sorted(full.signal_date.unique())})
    assigned = pd.merge_asof(active_days, quarters.rename(columns={"quarter": "asof_quarter"}).sort_values("quarter_effective_date"), left_on="signal_date", right_on="quarter_effective_date", direction="backward")
    grids = []
    for day in assigned.itertuples(index=False):
        is_restated = day.asof_quarter == "2026Q2" and day.signal_date >= pd.Timestamp(q2_receipt["citadel_restatement_effective_date"])
        members = restated[member_cols] if is_restated else member_by_quarter[day.asof_quarter]
        g = members.copy()
        g["signal_date"] = day.signal_date
        g["asof_quarter"] = day.asof_quarter
        for c in ["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"]:
            g[c] = getattr(day, c)
        g["pool_version_state"] = "CITADEL_RESTATED" if is_restated else "INITIAL_24" if day.asof_quarter == "2026Q2" else "ORIGINAL_EFFECTIVE_QUARTER"
        g["pool_version_effective_date"] = pd.Timestamp(q2_receipt["citadel_restatement_effective_date"]) if is_restated else day.quarter_effective_date
        g["pool_version_latest_filing_date"] = pd.Timestamp(restated_audit["restatement_filed_date"]) if is_restated else day.latest_filing_date
        grids.append(g)
    active = pd.concat(grids, ignore_index=True)
    validate_keys(active, "NEW_LATEST_EFFECTIVE_CANDIDATE")
    require(active.pool_version_effective_date.le(active.signal_date).all()
            and active.pool_version_latest_filing_date.lt(active.signal_date).all(), "TEST_VERSION_CLOCK_VIOLATION")
    source = full.copy()
    source["original_frozen_candidate_key"] = True
    joined = source.merge(active.rename(columns={c: "active_pool_" + c for c in ["quarter", "cusip", "title_of_class", "moomoo_transport_code"]}), on=KEY, how="outer", validate="one_to_one", indicator="membership_join")
    joined["original_frozen_candidate_key"] = joined.original_frozen_candidate_key.fillna(False).astype(bool)
    joined["membership_active"] = joined.membership_join.ne("left_only")
    for c in ["quarter", "cusip", "title_of_class", "moomoo_transport_code"]:
        joined[c] = joined[c].fillna(joined["active_pool_" + c])
    joined["original_qualification_status"] = joined.current_frozen_status.fillna("NO_ORIGINAL_QUALIFICATION_EVIDENCE")
    joined["qualification_status"] = joined.original_qualification_status
    new_keys = ~joined.original_frozen_candidate_key
    joined.loc[new_keys, "qualification_status"] = "UNKNOWN_NEW_RESTATED_POOL_KEY"
    identity_changed = joined.membership_active & joined.original_frozen_candidate_key & joined.cusip.ne(joined.active_pool_cusip)
    joined.loc[identity_changed, "qualification_status"] = "UNKNOWN_ACTIVE_POOL_IDENTITY_MISMATCH"
    glw = joined.ticker.eq("GLW") & joined.signal_date.eq(pd.Timestamp("2026-02-26"))
    joined.loc[glw, "qualification_status"] = "UNKNOWN_GLW_EVENT_DATE_CONFLICT"
    joined["numeric_feature_row_present"] = False
    joined = joined.merge(material[KEY + FEATURES].assign(numeric_feature_row_present=True), on=KEY, how="left", validate="one_to_one", suffixes=("_before", ""))
    joined = joined.drop(columns="numeric_feature_row_present_before")
    joined["numeric_feature_row_present"] = joined.numeric_feature_row_present.fillna(False).astype(bool)
    joined["numeric_32_finite"] = np.isfinite(joined[FEATURES].to_numpy(float)).all(axis=1)
    joined["new_buy_eligible"] = joined.membership_active & joined.qualification_status.eq("QUALIFIED") & joined.numeric_32_finite
    joined["context_only_if_held"] = ~joined.membership_active & joined.qualification_status.eq("QUALIFIED") & joined.numeric_32_finite
    joined["formal_full_pool_selection_allowed"] = False
    joined["universe_rule"] = "LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER_WITH_EFFECTIVE_RESTATEMENT"
    validate_keys(joined, "FULL_PRESERVED_WITH_NEW_ACTIVE_GRID")
    preserved = joined.loc[joined.original_frozen_candidate_key, KEY + ["original_qualification_status"]].sort_values(KEY).reset_index(drop=True)
    expected = full[KEY + ["current_frozen_status"]].rename(columns={"current_frozen_status": "original_qualification_status"}).sort_values(KEY).reset_index(drop=True)
    pd.testing.assert_frame_equal(preserved, expected, check_dtype=False)
    # Qualified removed members remain possible holding context. Unknown numerical
    # rows remain solely in the full candidate audit and cannot enter an account.
    context = joined.loc[joined.new_buy_eligible | joined.context_only_if_held].copy()
    context_cols = KEY + FEATURES + ["quarter", "cusip", "new_buy_eligible", "context_only_if_held", "qualification_status", "original_qualification_status", "membership_active", "pool_version_state", "pool_version_effective_date", "pool_version_latest_filing_date", "asof_quarter", "report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date", "universe_rule"]
    context = context[context_cols]
    held = old_context.loc[old_context.context_only_if_held].copy()
    held = held.loc[~pd.MultiIndex.from_frame(held[KEY]).isin(pd.MultiIndex.from_frame(context[KEY]))]
    held["qualification_status"] = "QUALIFIED_HOLDING_CONTEXT_ONLY"
    held["original_qualification_status"] = "QUALIFIED_HOLDING_CONTEXT_ONLY"
    held["membership_active"] = False
    held["new_buy_eligible"] = False
    context = pd.concat([context, held], ignore_index=True).sort_values(KEY).reset_index(drop=True)
    validate_keys(context, "SAFE_TEST_CONTEXT")
    require(np.isfinite(context[FEATURES].to_numpy(float)).all(), "SAFE_TEST_CONTEXT_NONFINITE")
    prices["original_price_quality_warning"] = prices.price_quality_warning
    price_conflict = prices.ticker.eq("GLW") & prices.trade_date.isin(pd.to_datetime(["2026-02-26", "2026-02-27"]))
    prices.loc[price_conflict, "price_quality_warning"] = True
    prices["new_batch_glw_conflict_mask"] = price_conflict
    coverage = joined.loc[joined.membership_active].groupby(["signal_date", "asof_quarter", "pool_version_state"], dropna=False).agg(
        active_candidate_rows=("ticker", "size"), qualified_new_buy_rows=("new_buy_eligible", "sum"),
        finite32_rows=("numeric_32_finite", "sum"), numerical_missing_rows=("numeric_32_finite", lambda s: int((~s).sum())),
        unknown_rows=("qualification_status", lambda s: int(s.astype(str).str.startswith("UNKNOWN").sum())),
        proven_ineligible_rows=("qualification_status", lambda s: int(s.eq("PROVEN_INELIGIBLE").sum()))).reset_index()
    coverage["full_pool_input_qualified"] = coverage.unknown_rows.eq(0)
    require(len(coverage) == 181 and not coverage.full_pool_input_qualified.any(), "UNEXPECTED_FULL_POOL_COVERAGE_REQUIRES_REVIEW")
    OUT.mkdir(parents=True, exist_ok=True)
    outputs = [OUT / "test.parquet", OUT / "test_full_candidates.parquet", OUT / "test_prices.parquet", OUT / "test_calendar.parquet", OUT / "FULL_POOL_COVERAGE.csv", OUT / "Q2_RESTATEMENT_MEMBERS.parquet", OUT / "test_operational_exit_evidence.csv"]
    require(not any(p.exists() for p in outputs), "PARTIAL_TEST_OUTPUT_REQUIRES_INSPECTION")
    for path, frame in zip(outputs[:4], [context, joined.sort_values(KEY).reset_index(drop=True), prices, calendar]):
        frame.to_parquet(path, index=False)
    coverage.to_csv(outputs[4], index=False, encoding="utf-8-sig")
    restated.to_parquet(outputs[5], index=False)
    op_source = bind(QUALIFIED / "data/operational_exit_evidence.csv")
    shutil.copyfile(op_source, outputs[6])
    require(all(sha(p) == h for p, h in SOURCES.items()), "TEST_SOURCE_MUTATION")
    receipt = {
        "status": "READY_QUALIFIED_CONTEXT_DIAGNOSTIC_FORMAL_FULL_POOL_BLOCKED",
        "created_utc": datetime.now(timezone.utc).isoformat(), "producer_sha256": sha(Path(__file__)),
        "freeze_receipt_path": str(freeze_path), "freeze_receipt_sha256": sha(freeze_path),
        "feature_order": FEATURES, "signal_first": str(full.signal_date.min().date()),
        "signal_last": str(full.signal_date.max().date()), "signal_days": len(coverage),
        "calendar_days": len(calendar), "valuation_last": str(calendar.trade_date.max().date()),
        "original_candidate_keys_preserved": int(joined.original_frozen_candidate_key.sum()),
        "original_unknown_rows_preserved": int(joined.original_qualification_status.eq("UNKNOWN").sum()),
        "all_saved_rows": len(joined), "active_candidate_rows": int(joined.membership_active.sum()),
        "qualified_context_rows": len(context), "qualified_new_buy_rows": int(context.new_buy_eligible.sum()),
        "holding_only_context_rows": int(context.context_only_if_held.sum()),
        "original_unknown_with_numeric32": int((joined.original_qualification_status.eq("UNKNOWN") & joined.numeric_32_finite).sum()),
        "formal_full_pool_qualified_days": int(coverage.full_pool_input_qualified.sum()),
        "full_pool_formal_performance_allowed": False, "unknown_promoted_due_to_numeric_features": 0,
        "qualification_repair": {"q2_restatement": restated_audit, "glw_conflict_signal_rows_masked": int(glw.sum()), "glw_conflict_price_rows_masked": int(price_conflict.sum())},
        "evaluation_scope": "Full candidate keys retained. Account runs using test.parquet are explicitly qualified-context diagnostic results; they cannot be labeled full-pool TOP20 performance.",
        "new_fit_calls": 0, "new_predictions": 0, "new_replays": 0,
        "input_sha256": SOURCES.copy(), "output_sha256": {p.name: sha(p) for p in outputs},
        "inherited_limits": ["47,271 original unknown security-days plus any new restated members", "Static identity projection remains retrospective", "Historical vendor arrival/version not proved", "Price-index quantity is not raw physical shares or shareholder total return", "EXAS cash entitlement/settlement remains unknown; operational evidence is not cash credit"],
    }
    save_json(receipt_path, receipt)
    save_json(OUT / "Q2_RESTATEMENT_AUDIT.json", restated_audit)
    print(json.dumps({k: receipt[k] for k in ["status", "all_saved_rows", "active_candidate_rows", "qualified_context_rows", "formal_full_pool_qualified_days"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["pre", "test"], required=True)
    parser.add_argument("--freeze-receipt", type=Path)
    args = parser.parse_args()
    if args.stage == "pre":
        require(args.freeze_receipt is None, "PRE_STAGE_MUST_NOT_BIND_A_TEST_FREEZE_RECEIPT")
        prepare_pre()
    else:
        prepare_test(args.freeze_receipt)


if __name__ == "__main__":
    main()
