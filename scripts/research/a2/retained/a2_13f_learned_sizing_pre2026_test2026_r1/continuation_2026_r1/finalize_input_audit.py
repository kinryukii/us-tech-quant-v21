"""Freeze a read-only input qualification audit without reading policy outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
R1 = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
QFQ = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq\year=2026\prices.parquet")
SNAP = Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")
BULK = Path(r"D:\us-tech-quant-cache\13f_pit_v1\sec_bulk_reduced")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write(name: str, value: dict):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    final = R1 / "A2/final_full_pre2026_hgb.joblib"
    summary = json.loads((R1 / "audit/fail_closed_or_pass_summary.json").read_text(encoding="utf-8"))
    contract = json.loads((R1 / "audit/frozen_contracts_before_outcome_read.json").read_text(encoding="utf-8"))
    assert sha(final) == summary["A2_MODEL_FINGERPRINT"]
    assert summary["A2_TRAIN_ROWS_2026_PLUS"] == 0
    write("A2_IDENTITY_AUDIT.json", {
        "status": "QUALIFIED_FINAL_PRODUCER_IDENTITY_SOURCE_ONLY_NO_2026_SIGNAL_MATERIALIZED",
        "frozen_final_model_path": str(final), "frozen_final_model_sha256": sha(final),
        "producer_path": str(R1 / "scripts/run_rebuild.py"),
        "producer_sha256": sha(R1 / "scripts/run_rebuild.py"),
        "hgb_config": contract["HGB_CONFIG"], "a2_feature_source_sha256": contract["A2_SOURCE_FINGERPRINT"],
        "a2_prereg_source_sha256": contract["A2_PREREG_FINGERPRINT"],
        "a2_feature_columns_source": "r1.FEATURE_COLUMNS, exactly as saved in original producer",
        "training_max_signal_date": summary["A2_MAX_TRAIN_DATE"],
        "training_rows_2026_plus": summary["A2_TRAIN_ROWS_2026_PLUS"],
        "training_row_count": summary["A2_TRAIN_ROW_COUNT"],
        "quarterly_universe_path": str(R1 / "universe/quarterly_universe_members.parquet"),
        "quarterly_universe_sha256": sha(R1 / "universe/quarterly_universe_members.parquet"),
        "uid_mapping_source": r"D:\us-tech-quant-results\13f_pit_v1\data\universe\security_identity_v17c_transport.parquet",
        "quarter_clock": "latest actual filing date of fixed 24, fifth later QQQ session; single active quarter",
        "eligibility": "original quarter members, 121 consecutive QQQ sessions and all original stock features finite",
        "ranking": "descending HGB prediction, ticker ascending tie; original r1._prediction_rank",
        "execution": "signal close; next QQQ session open",
        "historical_oof_vintages": "2023, 2024, 2025 distinct; no binary-hash equality required",
        "r1a_latest_common_2026_archive": "NOT_USED_DIFFERENT_PRODUCER_VINTAGE",
        "version_selection": "single original final pre2026 model; no 2026 policy outcome consulted",
        "retrospective_inference_disclosure": "would be retrospective, not contemporaneous publication",
        "inference_calls_this_continuation": 0,
    })

    old = pd.read_parquet(QFQ, columns=["ticker", "trade_date", "open", "close"])
    q = old.loc[old.ticker.eq("QQQ")].sort_values("trade_date")
    qmax = pd.Timestamp(q.trade_date.max()).normalize()
    assert qmax == pd.Timestamp("2026-07-14")
    q2 = pd.read_csv(HERE / "Q2_FILINGS_METADATA_ONLY.csv", dtype=str)
    assert len(q2) == 24 and q2.cik.nunique() == 24 and q2.filing_date.max() == "2026-08-14"
    # Completed version-manifest snapshot supplies only the calendar here; its adjusted values are not spliced.
    later = pd.read_csv(SNAP / "canonical_moomoo_ohlcv_daily_qfq.csv", usecols=["ticker", "date"])
    calendar = pd.DatetimeIndex(pd.to_datetime(later.loc[later.ticker.eq("QQQ"), "date"]).sort_values().unique())
    after_q2 = calendar[calendar > pd.Timestamp(q2.filing_date.max())]
    assert len(after_q2) >= 5
    q2_effective = str(after_q2[4].date())
    assert q2_effective == "2026-08-21"
    inventory = pd.read_csv(HERE / "RAW_2026Q1_CANDIDATE_PRICE_COVERAGE.csv")
    counts = inventory.max_time_key.value_counts(dropna=False).to_dict()
    assert not any("2026_sep_nov" in p.name for p in BULK.glob("*.parquet"))
    gap = {
        "status": "BLOCKED_NO_FORMAL_2026_REVEAL",
        "fixed_test_asof": json.loads((BASE / "RUN_MANIFEST.json").read_text(encoding="utf-8"))["test_asof"],
        "required_scope": "all completed 2026 market intervals strictly before fixed TEST_ASOF, plus next-open liquidation under original contract",
        "old_qqq_path": str(QFQ), "old_qqq_sha256": sha(QFQ),
        "old_qqq_last_trade_date": str(qmax.date()), "first_missing_following_session": "2026-07-15",
        "newer_completed_snapshot_path": str(SNAP / "canonical_manifest.json"),
        "newer_completed_snapshot_sha256": sha(SNAP / "canonical_manifest.json"),
        "newer_snapshot_target_date": "2026-09-11",
        "newer_qfq_vintage": "DIFFERS_FROM_OLD_ON_2026-07-14; not spliced or proved transformable",
        "raw_2026q1_candidate_count": len(inventory),
        "raw_direct_file_count": int(inventory.file_exists.sum()),
        "raw_missing_direct_file_count": int((~inventory.file_exists).sum()),
        "raw_last_date_distribution": {str(k): int(v) for k,v in counts.items()},
        "raw_majority_last_date": "2026-08-14",
        "q2_submissions_local": len(q2), "q2_form_counts": q2.form.value_counts().to_dict(),
        "q2_latest_filing_date": q2.filing_date.max(), "q2_original_clock_effective_date": q2_effective,
        "q2_complete_info_table_package": "ABSENT_LOCAL_REDUCED_BULK_THROUGH_2026_MAR_MAY",
        "q2_missing_specific_state": "Pershing Square CIK 0001336528 filed 13F-NT accession 0001172661-26-003777; other-manager underlying public holdings unresolved",
        "price_boundary_sample": "PRICE_BOUNDARY_CHECK.json: AAPL, AMZN, MSFT exact frozen overlap and 2026 extension through July14",
        "certified_complete_2026_signal_days": 0,
        "formal_signal_range": None, "formal_execution_range": None,
        "formal_2026_common_fallback_days": None,
        "formal_2026_test_reveals": 0,
        "policy_outcomes_read": False,
    }
    write("INPUT_GAP_AUDIT.json", gap)
    print(json.dumps({k:gap[k] for k in ("status","old_qqq_last_trade_date","first_missing_following_session","q2_original_clock_effective_date","q2_form_counts","raw_last_date_distribution")},indent=2))


if __name__ == "__main__":
    main()
