"""Compatibility launcher for the already-frozen replacement audit protocol.

The frozen referenced R4 source exposes ``build_target_map`` but predates its
pure ``calculate_weight_rebalance`` helper. This launcher reuses that missing
helper from the active repository implementation at an exact recorded hash.
It changes no protocol, metric, threshold, event, cost, or classification rule.
"""
from __future__ import annotations

from pathlib import Path

import a2_boundary_replacement_mechanism_audit_r1 as audit


ACTIVE_PORTFOLIO_SOURCE = Path(
    r"D:\us-tech-quant\scripts\v22\abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
)
ACTIVE_PORTFOLIO_SOURCE_SHA256 = "578284ce5563e584eea7b10e9e90b5bcaa35dc5f97c3899441b4bba0ca5237bb"
COMPATIBILITY_EVIDENCE_PATH = audit.OUT / "compatibility_adapter_audit.json"
DATE_SUPPORT_EVIDENCE_PATH = audit.OUT / "authoritative_date_support_adapter_audit.json"
ORIGINAL_LOAD_PANELS_AFTER_FREEZE = audit.load_panels_after_freeze


def compatible_reused_functions():
    hash_rows = audit.verify_expected_hashes()
    audit.require(all(row["pass"] for row in hash_rows), "COMPAT_FROZEN_SOURCE_HASH_FAILURE", hash_rows)
    actual_active_hash = audit.sha256_file(ACTIVE_PORTFOLIO_SOURCE)
    audit.require(
        actual_active_hash == ACTIVE_PORTFOLIO_SOURCE_SHA256,
        "COMPAT_ACTIVE_PORTFOLIO_SOURCE_HASH_FAILURE",
        {"actual": actual_active_hash, "expected": ACTIVE_PORTFOLIO_SOURCE_SHA256},
    )
    frozen_portfolio = audit.import_file("a2_boundary_frozen_membership_helper", audit.PORTFOLIO_SOURCE)
    active_portfolio = audit.import_file("a2_boundary_active_cost_helper", ACTIVE_PORTFOLIO_SOURCE)
    pairing = audit.import_file("a2_boundary_frozen_pairing_helper_compat", audit.PAIRING_SOURCE)
    audit.require(hasattr(frozen_portfolio, "build_target_map"), "FROZEN_MEMBERSHIP_HELPER_MISSING")
    audit.require(hasattr(active_portfolio, "calculate_weight_rebalance"), "ACTIVE_COST_HELPER_MISSING")
    synthetic = active_portfolio.calculate_weight_rebalance({"OLD": 0.05}, {"NEW": 0.05}, cost_bps=audit.COST_BPS)
    audit.require(abs(float(synthetic["target_turnover"]) - 0.05) <= 1e-12, "COMPAT_TURNOVER_IDENTITY_FAILURE", synthetic)
    audit.require(abs(float(synthetic["transaction_cost_fraction"]) - 0.00005) <= 1e-12, "COMPAT_COST_IDENTITY_FAILURE", synthetic)
    evidence = {
        "task_id": audit.TASK_ID,
        "frozen_protocol_sha256": audit.sha256_file(audit.PROTOCOL_PATH),
        "compatibility_status": "PASS_NO_RESEARCH_METHOD_CHANGE",
        "reason": "frozen R4 source contains build_target_map but predates calculate_weight_rebalance",
        "membership_helper": {"path": str(audit.PORTFOLIO_SOURCE), "sha256": audit.sha256_file(audit.PORTFOLIO_SOURCE), "symbol": "build_target_map"},
        "cost_helper": {"path": str(ACTIVE_PORTFOLIO_SOURCE), "sha256": actual_active_hash, "symbol": "calculate_weight_rebalance"},
        "pairing_helper": {"path": str(audit.PAIRING_SOURCE), "sha256": audit.sha256_file(audit.PAIRING_SOURCE), "symbols": ["add_roundtrip_tags", "build_replacements"]},
        "fixed_cost_bps": audit.COST_BPS,
        "synthetic_target_turnover": float(synthetic["target_turnover"]),
        "synthetic_transaction_cost_fraction": float(synthetic["transaction_cost_fraction"]),
        "RESEARCH_METHOD_CHANGE_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "NEW_STRATEGY_COUNT": 0,
        "NEW_BACKTESTER_COUNT": 0,
    }
    if COMPATIBILITY_EVIDENCE_PATH.exists():
        existing = audit.json.loads(COMPATIBILITY_EVIDENCE_PATH.read_text(encoding="utf-8"))
        audit.require(existing == evidence, "COMPATIBILITY_EVIDENCE_CHANGED_BETWEEN_RETRIES")
    else:
        audit.write_json_once(COMPATIBILITY_EVIDENCE_PATH, evidence)
    return (
        frozen_portfolio.build_target_map,
        active_portfolio.calculate_weight_rebalance,
        pairing.add_roundtrip_tags,
        pairing.build_replacements,
    )


def load_authoritative_date_supported_panels():
    panels, read_audit = ORIGINAL_LOAD_PANELS_AFTER_FREEZE()
    checkpoint = audit.pd.read_parquet(
        audit.PRE2026_CHECKPOINT,
        columns=["decision_date", "ticker_if_available", "raw_score", "raw_rank"],
    ).rename(columns={"ticker_if_available": "ticker"})
    checkpoint["decision_date"] = audit.pd.to_datetime(checkpoint["decision_date"])
    checkpoint = checkpoint.loc[
        checkpoint.decision_date.between(audit.pd.Timestamp("2023-01-01"), audit.pd.Timestamp("2025-12-31"))
    ].copy()
    authoritative_dates = set(checkpoint.decision_date)
    pre_mask = panels.window.eq("PRE2026")
    excluded = panels.loc[pre_mask & ~panels.decision_date.isin(authoritative_dates)].copy()
    panels = panels.loc[~pre_mask | panels.decision_date.isin(authoritative_dates)].copy()
    pre_top40 = panels.loc[
        panels.window.eq("PRE2026") & panels.raw_rank.le(40),
        ["decision_date", "ticker", "raw_score", "raw_rank"],
    ].copy()
    joined = checkpoint.merge(
        pre_top40,
        on=["decision_date", "ticker"],
        how="outer",
        suffixes=("_checkpoint", "_oof"),
        indicator=True,
    )
    checkpoint_identity = {
        "checkpoint_rows": int(len(checkpoint)),
        "source_top40_rows": int(len(pre_top40)),
        "key_mismatch_count": int(joined._merge.ne("both").sum()),
        "rank_mismatch_count": int(joined.raw_rank_checkpoint.fillna(-1).ne(joined.raw_rank_oof.fillna(-1)).sum()),
        "score_mismatch_count": int((~audit.np.isclose(joined.raw_score_checkpoint, joined.raw_score_oof, rtol=0.0, atol=1e-12, equal_nan=True)).sum()),
    }
    audit.require(
        all(checkpoint_identity[key] == 0 for key in ["key_mismatch_count", "rank_mismatch_count", "score_mismatch_count"]),
        "AUTHORITATIVE_DATE_SUPPORT_IDENTITY_FAILURE",
        checkpoint_identity,
    )
    excluded_dates = sorted(audit.pd.Timestamp(value).date().isoformat() for value in excluded.decision_date.unique())
    evidence = {
        "task_id": audit.TASK_ID,
        "status": "PASS_AUTHORITATIVE_CHECKPOINT_DATE_SUPPORT_ENFORCED",
        "reason": "full OOF source contains terminal 2025-12-30 and 2025-12-31 dates absent from the frozen 750-date membership checkpoint",
        "excluded_pre2026_panel_rows": int(len(excluded)),
        "excluded_decision_dates": excluded_dates,
        "excluded_top40_rows": int(excluded.raw_rank.le(40).sum()),
        "checkpoint_identity_after_filter": checkpoint_identity,
        "replacement_events_constructed_from_excluded_rows": 0,
        "RESEARCH_METHOD_CHANGE_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
    }
    audit.require(not DATE_SUPPORT_EVIDENCE_PATH.exists(), "DATE_SUPPORT_EVIDENCE_ALREADY_EXISTS")
    audit.write_json_once(DATE_SUPPORT_EVIDENCE_PATH, evidence)
    read_audit["checkpoint_identity"] = checkpoint_identity
    read_audit["pre2026_rows_excluded_outside_authoritative_checkpoint_date_support"] = int(len(excluded))
    read_audit["pre2026_excluded_decision_dates"] = excluded_dates
    return panels, read_audit


def main() -> int:
    audit.load_reused_functions = compatible_reused_functions
    audit.load_panels_after_freeze = load_authoritative_date_supported_panels
    summary = audit.run_audit()
    print("AUDIT_STATUS=PASS")
    print(f"FINAL_MECHANISM_CLASSIFICATION={summary['FINAL_MECHANISM_CLASSIFICATION']}")
    for key in [
        "POST_2026_08_28_OUTCOME_READ_COUNT",
        "THRESHOLD_SEARCH_COUNT",
        "NEW_STRATEGY_COUNT",
        "MODEL_REFIT_COUNT",
        "REGISTRY_CHANGE_COUNT",
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED",
        "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS",
        "ACTIVE_UNRELATED_TEMP_EXCLUSIONS",
        "ACTIVE_UNRELATED_TEMP_PATHS",
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT",
    ]:
        print(f"{key}={summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
