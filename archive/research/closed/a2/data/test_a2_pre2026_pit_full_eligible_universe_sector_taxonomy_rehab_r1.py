from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import a2_pre2026_pit_full_eligible_universe_sector_taxonomy_rehab_r1 as rehab


TASK_ROOT = Path(r"D:\us-tech-quant-results\A2_PRE2026_PIT_FULL_ELIGIBLE_UNIVERSE_SECTOR_TAXONOMY_REHAB_R1")
PRIOR_RV_CONTRACT = Path(r"D:\us-tech-quant-results\A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1\rv_contract.json")


def _synthetic_inputs(*, post_2025: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(["2026-01-02", "2026-01-03"] if post_2025 else ["2025-01-02", "2025-01-03"])
    rows = [(date, ticker, rank) for date in dates for ticker, rank in (("A", 1), ("B", 2), ("C", 21))]
    oof = pd.DataFrame(rows, columns=["signal_date", "ticker", "a2_rank"])
    oof["universe_size"] = 3
    oof["split"] = "synthetic"
    eligible = oof[["signal_date", "ticker"]].copy()
    eligible["moomoo_transport_code"] = "US." + eligible["ticker"]
    eligible["cusip"] = eligible["ticker"].map({"A": "CUSIP_A", "B": "CUSIP_B", "C": "CUSIP_C"})
    eligible["U_t_fingerprint"] = "synthetic-universe"
    taxonomy_rows = [(date, ticker) for date in dates for ticker in ("A", "B")]
    taxonomy = pd.DataFrame(taxonomy_rows, columns=["signal_date", "ticker"])
    taxonomy["execution_date"] = taxonomy["signal_date"]
    taxonomy["security_id"] = taxonomy["ticker"].map({"A": "CUSIP_A", "B": "CUSIP_B"})
    taxonomy["cik"] = taxonomy["ticker"].map({"A": 1, "B": 2})
    taxonomy["information_cutoff_utc"] = pd.to_datetime(
        [f"{date.date()} 21:00:00+00:00" for date in taxonomy["signal_date"]], utc=True
    )
    taxonomy["sic_accepted_timestamp_utc"] = pd.to_datetime(
        ["2024-01-01 00:00:00+00:00"] * len(taxonomy), utc=True
    )
    taxonomy["pit_sic"] = 3571
    taxonomy["ff12"] = "BusEq"
    taxonomy["ff48"] = "Computers"
    taxonomy["taxonomy_status"] = "PIT_SEC_SIC_MAPPED"
    return oof, eligible, taxonomy


def test_registry_anti_duplication_query_and_preflight() -> None:
    evidence = json.loads((TASK_ROOT / "registry_preflight.json").read_text(encoding="utf-8"))
    assert evidence["current"]["status"] == "PASS"
    assert evidence["validate"]["status"] == "PASS"
    assert evidence["proposal"]["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"
    assert evidence["canonical_capability_findings"]["broad_full_eligible_universe_pit_sector_taxonomy_entity_exists"] is False


def test_no_parallel_security_master_or_persistent_surface_created() -> None:
    preflight = json.loads((TASK_ROOT / "anti_duplication_preflight.json").read_text(encoding="utf-8"))
    assert preflight["decision"] == "NO_AUTHORITATIVE_PIT_SOURCE_AVAILABLE"
    assert preflight["anti_bloat_disposition"]["new_security_master_framework"] is False
    assert preflight["anti_bloat_disposition"]["new_persistent_data_surface_count"] == 0
    assert not (TASK_ROOT / "pit_full_eligible_universe_sector_surface.parquet").exists()


def test_source_temporal_certification_and_no_static_current_backfill() -> None:
    contract = json.loads((TASK_ROOT / "taxonomy_selection_contract.json").read_text(encoding="utf-8"))
    assert contract["strict_pit_requirements"][4] == "current static sector is never backfilled into history"
    assert contract["selected_full_universe_authoritative_taxonomy_source"] is None
    assert contract["synthetic_mapping_allowed"] is False


def test_unknown_or_mixed_source_is_never_open_then_filtered() -> None:
    text = (TASK_ROOT / "source_temporal_classification.csv").read_text(encoding="utf-8")
    assert "BROAD_MASTER_LEDGER,UNKNOWN_TEMPORAL_CONTENT,FALSE,FALSE" in text
    assert "RISK_REGISTRY,MIXED_POST2025,FALSE,FALSE" in text
    assert rehab.classify_candidate_source(whole_file_certified=False, registry_authoritative=False) == "UNKNOWN_TEMPORAL_CONTENT_DO_NOT_OPEN"


def test_unapproved_physical_path_is_rejected_before_hash_or_open(monkeypatch: pytest.MonkeyPatch) -> None:
    content_access_calls: list[Path] = []
    monkeypatch.setattr(rehab, "sha256_file", lambda path: content_access_calls.append(path) or "not-called")
    with pytest.raises(RuntimeError, match="UNAPPROVED_PHYSICAL_SOURCE_PATH:oof"):
        rehab.build_audit(
            oof_path=Path(r"D:\unsafe-or-unknown\oof.parquet"),
            eligible_path=rehab.EXPECTED_INPUT_PATHS["eligible"],
            taxonomy_path=rehab.EXPECTED_INPUT_PATHS["taxonomy"],
            prior_rv_contract_path=rehab.EXPECTED_INPUT_PATHS["rv_contract"],
            output_root=TASK_ROOT,
        )
    assert content_access_calls == []


def test_eligible_key_coverage_and_rank_gt20_failure() -> None:
    oof, eligible, taxonomy = _synthetic_inputs()
    legal_dates, eligible_legal, merged = rehab.reconcile_structural_keysets(oof, eligible, taxonomy)
    assert len(legal_dates) == 2
    assert len(eligible_legal) == len(merged) == 6
    assert int(merged["mapped_day_level_pit"].sum()) == 4
    assert int((merged["rank_gt_20"] & merged["mapped_day_level_pit"]).sum()) == 0
    assert int(merged["mapped_strict_pit"].sum()) == 0


def test_mapping_independent_of_top20_is_not_falsely_claimed() -> None:
    oof, eligible, taxonomy = _synthetic_inputs()
    _, _, merged = rehab.reconcile_structural_keysets(oof, eligible, taxonomy)
    taxonomy_keys = set(taxonomy[["signal_date", "ticker"]].itertuples(index=False, name=None))
    rank_le_20_keys = set(merged.loc[merged["rank_le_20"], ["signal_date", "ticker"]].itertuples(index=False, name=None))
    assert taxonomy_keys.issubset(rank_le_20_keys)
    assert taxonomy_keys == set(
        merged.loc[
            merged["rank_le_20"] & merged["signal_date"].isin(set(taxonomy["signal_date"])),
            ["signal_date", "ticker"],
        ].itertuples(index=False, name=None)
    )
    assert not (merged["rank_gt_20"] & merged["mapped_day_level_pit"]).any()


def test_unique_date_security_key_fails_closed() -> None:
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2025-01-01", "2025-01-01"]), "ticker": ["A", "A"]})
    with pytest.raises(RuntimeError, match="DUPLICATE_KEY"):
        rehab.assert_unique(frame, ["signal_date", "ticker"], "synthetic")


def test_missing_or_duplicate_stable_identity_fails_closed() -> None:
    oof, eligible, taxonomy = _synthetic_inputs()
    missing = eligible.copy()
    missing.loc[0, "cusip"] = None
    with pytest.raises(RuntimeError, match="MISSING_STABLE_IDENTITY"):
        rehab.reconcile_structural_keysets(oof, missing, taxonomy)

    duplicated = eligible.copy()
    duplicated.loc[duplicated.index[1], "cusip"] = duplicated.loc[duplicated.index[0], "cusip"]
    with pytest.raises(RuntimeError, match="DUPLICATE_KEY:ELIGIBLE_UNIVERSE_STABLE_IDENTITY"):
        rehab.reconcile_structural_keysets(oof, duplicated, taxonomy)


def test_ticker_reuse_is_distinguished_by_stable_identity() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2025-01-01", "2025-02-01"]),
            "ticker": ["A", "A"],
            "cusip": ["CUSIP_OLD", "CUSIP_NEW"],
        }
    )
    with_cusip = rehab.keyset_hash(frame, ["signal_date", "ticker", "cusip"])
    without_cusip = rehab.keyset_hash(frame, ["signal_date", "ticker"])
    assert with_cusip != without_cusip


def test_ticker_change_preserves_stable_identity() -> None:
    frame = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2025-01-01", "2025-02-01"]),
            "ticker": ["OLD", "NEW"],
            "cusip": ["CUSIP_STABLE", "CUSIP_STABLE"],
        }
    )
    assert int((frame.groupby("cusip")["ticker"].nunique() > 1).sum()) == 1
    rehab.assert_unique(frame, ["signal_date", "cusip"], "TICKER_CHANGE_STABLE_IDENTITY")


def test_no_post2025_rows_are_accepted() -> None:
    oof, eligible, taxonomy = _synthetic_inputs(post_2025=True)
    with pytest.raises(RuntimeError, match="POST_2025_.*OOF_ROW"):
        rehab.reconcile_structural_keysets(oof, eligible, taxonomy)


def test_deterministic_structural_reconciliation_and_hashing() -> None:
    oof, eligible, taxonomy = _synthetic_inputs()
    outputs = []
    for _ in range(2):
        _, eligible_legal, merged = rehab.reconcile_structural_keysets(oof, eligible, taxonomy)
        coverage = rehab._aggregate_coverage(merged.assign(year=merged["signal_date"].dt.year), ["year"])
        outputs.append(
            (
                rehab.keyset_hash(eligible_legal, ["signal_date", "ticker", "cusip"]),
                rehab.sha256_value(coverage.to_dict(orient="records")),
            )
        )
    assert outputs[0] == outputs[1]


def test_registry_patch_base_head_protection() -> None:
    rehab.validate_patch_base("same", "same")
    with pytest.raises(RuntimeError, match="HARD_BLOCKER_REGISTRY_HEAD_CHANGED"):
        rehab.validate_patch_base("expected", "changed")


def test_existing_frozen_rv_contract_is_unchanged() -> None:
    assert rehab.sha256_file(PRIOR_RV_CONTRACT) == rehab.RV_CONTRACT_SHA256


def test_all_temporal_and_anti_bloat_counters_are_zero() -> None:
    assert rehab.REQUIRED_ZERO_COUNTERS
    assert all(value == 0 for value in rehab.REQUIRED_ZERO_COUNTERS.values())
    assert rehab.REQUIRED_ZERO_COUNTERS["economic_result_read_count"] == 0
    assert rehab.REQUIRED_ZERO_COUNTERS["new_identity_framework_count"] == 0


def test_realized_target_column_is_not_in_permitted_projection() -> None:
    contract = json.loads((TASK_ROOT / "taxonomy_selection_contract.json").read_text(encoding="utf-8"))
    projection = contract["existing_certified_inputs"]["raw_a2_oof_structural_projection"]
    assert projection["realized_target_column_permitted"] is False
    assert "target" not in projection["permitted_columns"]
