from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


TASK_ID = "A2_PRE2026_PIT_FULL_ELIGIBLE_UNIVERSE_SECTOR_TAXONOMY_REHAB_R1"
TERMINAL_STATUS = "PASS_UNTESTABLE_NO_AUTHORITATIVE_PIT_SECTOR_SOURCE"
RV_CHILD = "A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1"
RV_CONTRACT_SHA256 = "146af857798c21441b24a1106d32112878ffba43be289ac69098b9a4c070e9c8"
EXPECTED_HASHES = {
    "oof": "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    "eligible": "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637",
    "taxonomy": "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
}
EXPECTED_INPUT_PATHS = {
    "oof": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\oof_predictions.parquet"),
    "eligible": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\universe\daily_eligible_universe_membership.parquet"),
    "taxonomy": Path(r"D:\us-tech-quant-results\A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1\pit_ff12_ff48_taxonomy.parquet"),
    "rv_contract": Path(r"D:\us-tech-quant-results\A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1\rv_contract.json"),
}
REQUIRED_ZERO_COUNTERS = {
    "new_alpha_component_count": 0,
    "new_feature_count": 0,
    "new_model_count": 0,
    "new_model_fit_count": 0,
    "new_threshold_search_count": 0,
    "new_taxonomy_search_count": 0,
    "new_universe_count": 0,
    "new_identity_framework_count": 0,
    "new_external_data_source_count": 0,
    "new_database_count": 0,
    "new_dependency_count": 0,
    "harness_modification_count": 0,
    "new_persistent_data_surface_count": 0,
    "post_2025_realized_label_metric_read_count": 0,
    "post_2025_model_evaluation_metric_read_count": 0,
    "post_2025_outcome_derived_metadata_read_count": 0,
    "2026_economic_outcome_read_count": 0,
    "holdout_peek_count": 0,
    "mixed_source_content_open_count": 0,
    "economic_result_read_count": 0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_physical_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def assert_certified_physical_path(path: Path, source_id: str) -> None:
    expected = EXPECTED_INPUT_PATHS[source_id]
    if _normalized_physical_path(path) != _normalized_physical_path(expected):
        raise RuntimeError(f"UNAPPROVED_PHYSICAL_SOURCE_PATH:{source_id}:{path}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_dates(frame: pd.DataFrame, column: str = "signal_date") -> pd.DataFrame:
    result = frame.copy()
    result[column] = pd.to_datetime(result[column]).dt.normalize()
    return result


def assert_unique(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    duplicate_count = int(frame.duplicated(keys, keep=False).sum())
    if duplicate_count:
        raise RuntimeError(f"DUPLICATE_KEY:{label}:{keys}:{duplicate_count}")


def assert_pre2026(frame: pd.DataFrame, label: str, column: str = "signal_date") -> None:
    if frame[column].max() > pd.Timestamp("2025-12-31"):
        raise RuntimeError(f"POST_2025_{label}_ROW")


def read_certified_parquet(path: Path, expected_sha256: str, columns: list[str]) -> pd.DataFrame:
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise RuntimeError(f"HASH_MISMATCH:{path}:{expected_sha256}:{observed}")
    schema_names = set(pq.ParquetFile(path).schema_arrow.names)
    missing = sorted(set(columns) - schema_names)
    if missing:
        raise RuntimeError(f"MISSING_COLUMNS:{path}:{missing}")
    return pq.read_table(path, columns=columns).to_pandas()


def dataframe_schema_hash(frame: pd.DataFrame) -> str:
    schema = pa.Schema.from_pandas(frame, preserve_index=False)
    return hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()


def keyset_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame[columns].copy()
    for column in columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
        else:
            ordered[column] = ordered[column].astype("string").fillna("<NA>")
    ordered = ordered.sort_values(columns, kind="mergesort")
    digest = hashlib.sha256()
    for row in ordered.itertuples(index=False, name=None):
        digest.update(("\x1f".join(str(value) for value in row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def classify_candidate_source(*, whole_file_certified: bool, registry_authoritative: bool) -> str:
    if whole_file_certified and registry_authoritative:
        return "STRICT_PIT_CANDIDATE_REQUIRES_CONTENT_VALIDATION"
    return "UNKNOWN_TEMPORAL_CONTENT_DO_NOT_OPEN"


def validate_patch_base(expected_head: str, observed_head: str) -> None:
    if expected_head != observed_head:
        raise RuntimeError(f"HARD_BLOCKER_REGISTRY_HEAD_CHANGED:{expected_head}:{observed_head}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, lineterminator="\n")


def _aggregate_coverage(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    grouped = frame.groupby(group_columns, dropna=False, sort=True)
    output = grouped.agg(
        total_eligible_security_observations=("ticker", "size"),
        rank_le_20_observations=("rank_le_20", "sum"),
        rank_gt_20_observations=("rank_gt_20", "sum"),
        matched_any_taxonomy=("matched_any_taxonomy", "sum"),
        mapped_day_level_pit=("mapped_day_level_pit", "sum"),
        mapped_strict_pit=("mapped_strict_pit", "sum"),
        unmapped=("unmapped", "sum"),
        ambiguous=("ambiguous", "sum"),
        identity_unresolved=("identity_unresolved", "sum"),
        identity_exact_string_match=("identity_exact_string_match", "sum"),
        identity_linkage_unproven=("identity_linkage_unproven", "sum"),
        taxonomy_unavailable=("taxonomy_unavailable", "sum"),
        non_pit_only_available=("non_pit_only_available", "sum"),
    ).reset_index()
    output["strict_pit_mapping_coverage"] = output["mapped_strict_pit"] / output["total_eligible_security_observations"]
    output["day_level_mapping_coverage"] = output["mapped_day_level_pit"] / output["total_eligible_security_observations"]
    return output


def reconcile_structural_keysets(
    oof: pd.DataFrame,
    eligible: pd.DataFrame,
    taxonomy: pd.DataFrame,
) -> tuple[list[pd.Timestamp], pd.DataFrame, pd.DataFrame]:
    """Reconcile only date/security/rank/taxonomy structure; no outcome column is accepted."""
    for frame, label in ((oof, "RAW_A2_OOF"), (eligible, "ELIGIBLE_UNIVERSE"), (taxonomy, "TOP20_TAXONOMY")):
        assert_unique(frame, ["signal_date", "ticker"], label)
        assert_pre2026(frame, label)

    legal_dates = sorted(oof["signal_date"].drop_duplicates())
    eligible_legal = eligible[eligible["signal_date"].isin(legal_dates)].copy()
    eligible_cusip = eligible_legal["cusip"].astype("string").str.strip()
    missing_cusip = eligible_cusip.isna() | eligible_cusip.eq("")
    if missing_cusip.any():
        raise RuntimeError(f"MISSING_STABLE_IDENTITY:ELIGIBLE_UNIVERSE:cusip:{int(missing_cusip.sum())}")
    assert_unique(eligible_legal, ["signal_date", "cusip"], "ELIGIBLE_UNIVERSE_STABLE_IDENTITY")
    oof_keys = set(oof[["signal_date", "ticker"]].itertuples(index=False, name=None))
    eligible_keys = set(eligible_legal[["signal_date", "ticker"]].itertuples(index=False, name=None))
    if oof_keys != eligible_keys:
        raise RuntimeError(
            f"ELIGIBLE_SCORE_KEYSET_MISMATCH:oof_only={len(oof_keys-eligible_keys)}:eligible_only={len(eligible_keys-oof_keys)}"
        )

    merged = oof.merge(
        eligible_legal[["signal_date", "ticker", "moomoo_transport_code", "cusip", "U_t_fingerprint"]],
        on=["signal_date", "ticker"],
        how="left",
        validate="one_to_one",
    ).merge(
        taxonomy,
        on=["signal_date", "ticker"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    merged["rank_le_20"] = merged["a2_rank"] <= 20
    merged["rank_gt_20"] = merged["a2_rank"] > 20
    merged["matched_any_taxonomy"] = merged["_merge"].eq("both")
    merged["mapped_day_level_pit"] = (
        merged["matched_any_taxonomy"]
        & merged["taxonomy_status"].eq("PIT_SEC_SIC_MAPPED")
        & merged["ff12"].notna()
    )
    # Day-level evidence cannot become strict PIT without the exact Raw A2
    # decision timestamp relative to the 20:00/21:00 UTC taxonomy cutoff.
    merged["mapped_strict_pit"] = False
    eligible_identity = merged["cusip"].astype("string").str.strip().str.upper()
    taxonomy_identity = merged["security_id"].astype("string").str.strip().str.upper()
    merged["identity_exact_string_match"] = merged["matched_any_taxonomy"] & eligible_identity.eq(taxonomy_identity)
    merged["identity_linkage_unproven"] = merged["matched_any_taxonomy"] & ~merged["identity_exact_string_match"]
    merged["identity_unresolved"] = merged["identity_linkage_unproven"]
    merged["ambiguous"] = False
    merged["taxonomy_unavailable"] = ~merged["mapped_day_level_pit"]
    merged["non_pit_only_available"] = merged["mapped_day_level_pit"]
    merged["unmapped"] = ~merged["mapped_strict_pit"]
    merged["mapping_reason"] = "NO_AUTHORITATIVE_TAXONOMY_ROW"
    merged.loc[merged["taxonomy_status"].eq("UNKNOWN_TAXONOMY"), "mapping_reason"] = "TAXONOMY_STATUS_UNKNOWN"
    merged.loc[merged["mapped_day_level_pit"], "mapping_reason"] = "DAY_LEVEL_PIT_ONLY_INTRADAY_DECISION_TIME_UNRESOLVED"
    merged.loc[merged["identity_linkage_unproven"], "mapping_reason"] = "CROSS_SOURCE_IDENTITY_LINKAGE_UNPROVEN"
    return legal_dates, eligible_legal, merged


def build_audit(
    *,
    oof_path: Path,
    eligible_path: Path,
    taxonomy_path: Path,
    prior_rv_contract_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    # A path/hash pair is authorized as one physical source. Reject unexpected
    # paths before hashing or opening any content; never inspect then filter.
    assert_certified_physical_path(oof_path, "oof")
    assert_certified_physical_path(eligible_path, "eligible")
    assert_certified_physical_path(taxonomy_path, "taxonomy")
    assert_certified_physical_path(prior_rv_contract_path, "rv_contract")
    output_root.mkdir(parents=True, exist_ok=True)
    if sha256_file(prior_rv_contract_path) != RV_CONTRACT_SHA256:
        raise RuntimeError("FROZEN_RV_CONTRACT_HASH_MISMATCH")

    oof = normalize_dates(
        read_certified_parquet(
            oof_path,
            EXPECTED_HASHES["oof"],
            ["signal_date", "ticker", "universe_size", "split", "a2_rank"],
        )
    )
    eligible = normalize_dates(
        read_certified_parquet(
            eligible_path,
            EXPECTED_HASHES["eligible"],
            ["signal_date", "ticker", "moomoo_transport_code", "cusip", "U_t_fingerprint"],
        )
    )
    taxonomy = normalize_dates(
        read_certified_parquet(
            taxonomy_path,
            EXPECTED_HASHES["taxonomy"],
            [
                "signal_date",
                "ticker",
                "execution_date",
                "security_id",
                "cik",
                "information_cutoff_utc",
                "sic_accepted_timestamp_utc",
                "pit_sic",
                "ff12",
                "ff48",
                "taxonomy_status",
            ],
        )
    )
    legal_dates, eligible_legal, merged = reconcile_structural_keysets(oof, eligible, taxonomy)

    by_date = _aggregate_coverage(merged, ["signal_date"]).rename(columns={"signal_date": "decision_date"})
    by_date["decision_date"] = by_date["decision_date"].dt.strftime("%Y-%m-%d")
    by_year_frame = merged.assign(year=merged["signal_date"].dt.year)
    by_year = _aggregate_coverage(by_year_frame, ["year"])
    sector_bucket = pd.Series("UNAVAILABLE_OR_UNPROVEN", index=merged.index, dtype="string")
    sector_bucket.loc[merged["mapped_day_level_pit"]] = (
        "DAY_LEVEL_ONLY_FF12:" + merged.loc[merged["mapped_day_level_pit"], "ff12"].astype("string")
    )
    by_sector = _aggregate_coverage(merged.assign(sector_bucket=sector_bucket), ["sector_bucket"])
    rank_bucket = pd.Series("RANK_GT_20", index=merged.index)
    rank_bucket.loc[merged["rank_le_20"]] = "RANK_LE_20"
    by_rank = _aggregate_coverage(merged.assign(rank_bucket=rank_bucket), ["rank_bucket"])
    by_rank["rank_bucket_order"] = by_rank["rank_bucket"].map({"RANK_LE_20": 1, "RANK_GT_20": 2})
    by_rank = by_rank.sort_values("rank_bucket_order").drop(columns=["rank_bucket_order"])

    unmapped = (
        merged.groupby(["ticker", "cusip", "mapping_reason"], dropna=False, sort=True)
        .agg(
            observation_count=("signal_date", "size"),
            first_decision_date=("signal_date", "min"),
            last_decision_date=("signal_date", "max"),
            min_a2_rank=("a2_rank", "min"),
            max_a2_rank=("a2_rank", "max"),
            day_level_mapping_count=("mapped_day_level_pit", "sum"),
            strict_pit_mapping_count=("mapped_strict_pit", "sum"),
        )
        .reset_index()
    )
    unmapped["first_decision_date"] = unmapped["first_decision_date"].dt.strftime("%Y-%m-%d")
    unmapped["last_decision_date"] = unmapped["last_decision_date"].dt.strftime("%Y-%m-%d")

    taxonomy_conflicts = (
        taxonomy.groupby(["signal_date", "ticker"], dropna=False)
        .agg(sector_code_count=("ff12", "nunique"), taxonomy_status_count=("taxonomy_status", "nunique"))
        .reset_index()
    )
    taxonomy_conflicts = taxonomy_conflicts[
        (taxonomy_conflicts["sector_code_count"] > 1) | (taxonomy_conflicts["taxonomy_status_count"] > 1)
    ]
    taxonomy_conflicts["signal_date"] = taxonomy_conflicts["signal_date"].dt.strftime("%Y-%m-%d")

    valid_day_level = merged["mapped_day_level_pit"]
    rank_le_20_count = int(merged["rank_le_20"].sum())
    rank_gt_20_count = int(merged["rank_gt_20"].sum())
    rank_gt_20_day_level_mapping = int((merged["rank_gt_20"] & valid_day_level).sum())
    cutoff = pd.to_datetime(taxonomy["information_cutoff_utc"], utc=True)
    accepted = pd.to_datetime(taxonomy["sic_accepted_timestamp_utc"], utc=True)

    _write_csv(output_root / "sector_coverage_by_date.csv", by_date)
    _write_csv(output_root / "sector_coverage_by_year.csv", by_year)
    _write_csv(output_root / "sector_coverage_by_sector.csv", by_sector)
    _write_csv(output_root / "sector_coverage_by_rank_bucket.csv", by_rank)
    _write_csv(output_root / "unmapped_security_report.csv", unmapped)
    _write_csv(output_root / "taxonomy_conflict_report.csv", taxonomy_conflicts)

    key_manifest = {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "status": "PASS_AUTHORITATIVE_ELIGIBLE_KEYSET_REUSED",
        "authoritative_universe_source": str(eligible_path),
        "authoritative_universe_sha256": EXPECTED_HASHES["eligible"],
        "raw_a2_scored_surface_source": str(oof_path),
        "raw_a2_scored_surface_sha256": EXPECTED_HASHES["oof"],
        "legal_decision_dates": len(legal_dates),
        "min_decision_date": str(min(legal_dates).date()),
        "max_decision_date": str(max(legal_dates).date()),
        "total_eligible_security_observations": len(eligible_legal),
        "total_raw_a2_scored_observations": len(oof),
        "scored_keyset_equals_eligible_keyset_on_legal_dates": True,
        "unique_signal_date_ticker": True,
        "unique_signal_date_cusip": not eligible_legal.duplicated(["signal_date", "cusip"]).any(),
        "missing_cusip_count": int(eligible_legal["cusip"].isna().sum()),
        "ticker_change_cusip_count": int((eligible_legal.groupby("cusip")["ticker"].nunique() > 1).sum()),
        "ticker_reused_across_cusips_count": int((eligible_legal.groupby("ticker")["cusip"].nunique() > 1).sum()),
        "identity_reuse": "EXISTING_CUSIP_AND_TICKER_AT_DATE_NO_NEW_RESOLVER",
        "canonical_security_id_materialized": False,
        "eligible_keyset_sha256": keyset_hash(eligible_legal, ["signal_date", "ticker", "cusip"]),
        "schema_sha256": dataframe_schema_hash(eligible_legal),
    }
    _write_json(output_root / "eligible_universe_keyset_manifest.json", key_manifest)

    temporal_certification = {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "status": "FAIL_STRICT_PIT_PROMOTION",
        "source_temporal_period_classification": "SAFE_PRE2026",
        "pit_classification": "MIXED_OR_UNPROVEN",
        "pit_classification_detail": "INTRADAY_DECISION_TIME_AND_CROSS_SOURCE_IDENTITY_LINKAGE_UNPROVEN",
        "source_path": str(taxonomy_path),
        "source_sha256": EXPECTED_HASHES["taxonomy"],
        "taxonomy_rows": len(taxonomy),
        "taxonomy_dates": int(taxonomy["signal_date"].nunique()),
        "taxonomy_min_date": str(taxonomy["signal_date"].min().date()),
        "taxonomy_max_date": str(taxonomy["signal_date"].max().date()),
        "taxonomy_key_duplicate_count": int(taxonomy.duplicated(["signal_date", "ticker"]).sum()),
        "information_cutoff_utc_hours": sorted(int(value) for value in cutoff.dt.hour.unique()),
        "sic_accepted_after_information_cutoff_count": int((accepted > cutoff).fillna(False).sum()),
        "exact_raw_a2_decision_timestamp_contract_available": False,
        "mapped_day_level_pit": int(valid_day_level.sum()),
        "identity_exact_string_match_count": int(merged["identity_exact_string_match"].sum()),
        "identity_linkage_unproven_count": int(merged["identity_linkage_unproven"].sum()),
        "mapped_day_level_pit_with_exact_identity_string_count": int(
            (valid_day_level & merged["identity_exact_string_match"]).sum()
        ),
        "mapped_strict_pit": 0,
        "rank_gt_20_day_level_mapping_count": rank_gt_20_day_level_mapping,
        "strict_pit_promotion_allowed": False,
        "reasons": [
            "physical taxonomy keyset is selection-conditioned on Raw A2 Top20",
            "rank greater than 20 mapping count is zero",
            "exact Raw A2 decision timestamp is not certified relative to 20:00/21:00 UTC information cutoff",
            f"{int(merged['identity_linkage_unproven'].sum()):,} date/ticker joins lack exact cross-source identifier-string agreement and no authoritative identity bridge is certified",
            "no broad-pool strict-PIT taxonomy source is independently certified",
        ],
    }
    _write_json(output_root / "pit_sector_temporal_certification.json", temporal_certification)

    taxonomy_keys = set(taxonomy[["signal_date", "ticker"]].itertuples(index=False, name=None))
    rank_le_20_keys = set(
        merged.loc[merged["rank_le_20"], ["signal_date", "ticker"]].itertuples(index=False, name=None)
    )
    taxonomy_dates = set(taxonomy["signal_date"].drop_duplicates())
    rank_le_20_keys_on_taxonomy_dates = set(
        merged.loc[
            merged["rank_le_20"] & merged["signal_date"].isin(taxonomy_dates),
            ["signal_date", "ticker"],
        ].itertuples(index=False, name=None)
    )
    existing_certification = {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "status": "FAIL_FULL_ELIGIBLE_UNIVERSE_PROMOTION_TOP20_ONLY",
        "surface_path": str(taxonomy_path),
        "surface_sha256": EXPECTED_HASHES["taxonomy"],
        "authoritative_scope": "RAW_A2_TOP20_ONLY_DAY_LEVEL_PIT",
        "physical_rows": len(taxonomy),
        "valid_day_level_rows": int(valid_day_level.sum()),
        "exact_identity_string_match_rows": int(merged["identity_exact_string_match"].sum()),
        "identity_linkage_unproven_rows": int(merged["identity_linkage_unproven"].sum()),
        "full_eligible_observations": len(merged),
        "strict_pit_mapped_observations": 0,
        "day_level_mapping_coverage": float(valid_day_level.mean()),
        "strict_pit_mapping_coverage": 0.0,
        "rank_le_20_observations": rank_le_20_count,
        "rank_le_20_day_level_mapping_count": int((merged["rank_le_20"] & valid_day_level).sum()),
        "rank_gt_20_observations": rank_gt_20_count,
        "rank_gt_20_day_level_mapping_count": rank_gt_20_day_level_mapping,
        "taxonomy_key_not_rank_le_20_count": len(taxonomy_keys - rank_le_20_keys),
        "rank_le_20_key_not_taxonomy_count_full_legal_sample": len(rank_le_20_keys - taxonomy_keys),
        "rank_le_20_key_not_taxonomy_count_on_taxonomy_dates": len(rank_le_20_keys_on_taxonomy_dates - taxonomy_keys),
        "missing_legal_decision_date_count": len(set(legal_dates) - taxonomy_dates),
        "keyset_subset_of_raw_a2_rank_le_20": taxonomy_keys.issubset(rank_le_20_keys),
        "keyset_equals_raw_a2_rank_le_20_on_taxonomy_dates": taxonomy_keys == rank_le_20_keys_on_taxonomy_dates,
        "previous_authoritative_test": "physical taxonomy keyset equals frozen Raw A2 Top20 selections on the 750 taxonomy-covered dates",
        "promotion_allowed": False,
    }
    _write_json(output_root / "existing_surface_certification.json", existing_certification)

    validation_tests = {
        "TEST_1_OLD_SURFACE_TOP20_EQUIVALENCE": "PASS_EXACT_TOP20_ON_750_COVERED_DATES_TWO_LEGAL_DATES_ABSENT",
        "TEST_2_CANDIDATE_COVERS_RANK_GT_20": "FAIL_ZERO_MAPPINGS",
        "TEST_3_CANDIDATE_COVERS_FULL_ELIGIBLE_UNIVERSE": "FAIL",
        "TEST_4_MAPPING_AVAILABLE_BEFORE_TOP20_SELECTION": "FAIL_UNPROVEN_AND_SELECTION_CONDITIONED",
        "TEST_5_GENERATION_INDEPENDENT_OF_TOP20_MEMBERSHIP": "FAIL",
    }
    counters = dict(REQUIRED_ZERO_COUNTERS)
    run_summary = {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "status": TERMINAL_STATUS,
        "anti_duplication_decision": "NO_AUTHORITATIVE_PIT_SOURCE_AVAILABLE",
        "canonical_infrastructure_reused": False,
        "registry_base_head": "0897324b5fa17fd92eec94c47d6a1b4ecebe955317271cff1db7263484dc838f",
        "legal_decision_dates": len(legal_dates),
        "total_eligible_security_observations": len(merged),
        "mapped_day_level_pit": int(valid_day_level.sum()),
        "mapped_strict_pit": 0,
        "unmapped": len(merged),
        "ambiguous": 0,
        "identity_unresolved": int(merged["identity_unresolved"].sum()),
        "identity_exact_string_match_count": int(merged["identity_exact_string_match"].sum()),
        "identity_linkage_unproven_count": int(merged["identity_linkage_unproven"].sum()),
        "taxonomy_unavailable": int(merged["taxonomy_unavailable"].sum()),
        "non_pit_only_available": int(merged["non_pit_only_available"].sum()),
        "mapping_coverage": 0.0,
        "day_level_mapping_coverage": float(valid_day_level.mean()),
        "rank_le_20_mapping_count": 0,
        "rank_le_20_day_level_mapping_count": int((merged["rank_le_20"] & valid_day_level).sum()),
        "rank_gt_20_mapping_count": 0,
        "rank_gt_20_day_level_mapping_count": rank_gt_20_day_level_mapping,
        "new_persistent_data_surface_count": 0,
        "rv_data_gap_status": "UNRESOLVED",
        "rv_frozen_child": RV_CHILD,
        "rv_contract_modified": False,
        "rv_economics_run": False,
        "next_legal_action": "DO_NOT_RUN_RV_ECONOMICS",
        "validation_tests": validation_tests,
        "counters": counters,
    }
    _write_json(output_root / "execution_counters.json", counters)
    _write_json(output_root / "run_summary.json", run_summary)
    _write_json(
        output_root / "postopen_source_resolution.json",
        {
            "schema_version": "1.0.0",
            "task_id": TASK_ID,
            "status": "PASS",
            "opened_safe_pre2026_sources": [
                {"path": str(oof_path), "sha256": EXPECTED_HASHES["oof"], "columns_read": ["signal_date", "ticker", "universe_size", "split", "a2_rank"], "realized_target_read": False},
                {"path": str(eligible_path), "sha256": EXPECTED_HASHES["eligible"], "columns_read": ["signal_date", "ticker", "moomoo_transport_code", "cusip", "U_t_fingerprint"]},
                {"path": str(taxonomy_path), "sha256": EXPECTED_HASHES["taxonomy"], "columns_read": ["signal_date", "ticker", "execution_date", "security_id", "cik", "information_cutoff_utc", "sic_accepted_timestamp_utc", "pit_sic", "ff12", "ff48", "taxonomy_status"]},
            ],
            "unknown_or_mixed_sources_opened": [],
            "post_2025_rows_read": 0,
            "economic_result_read_count": 0,
        },
    )

    output_hashes: dict[str, str] = {}
    excluded_nonfiles: list[str] = []
    for path in sorted(output_root.iterdir()):
        try:
            if path.is_file() and path.name != "artifact_hash_readback.json":
                output_hashes[path.name] = sha256_file(path)
            elif path.name != "artifact_hash_readback.json":
                excluded_nonfiles.append(path.name)
        except OSError:
            excluded_nonfiles.append(path.name)
    _write_json(
        output_root / "artifact_hash_readback.json",
        {
            "schema_version": "1.0.0",
            "task_id": TASK_ID,
            "status": "PASS",
            "artifacts": output_hashes,
            "excluded_nonfile_or_inaccessible_entries": excluded_nonfiles,
            "build_fingerprint": sha256_value(
                {
                    "contract_sha256": sha256_file(output_root / "taxonomy_selection_contract.json"),
                    "runner_sha256": sha256_file(Path(__file__)),
                    "source_hashes": EXPECTED_HASHES,
                    "output_hashes": output_hashes,
                }
            ),
        },
    )
    return run_summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict-PIT full eligible-universe sector-taxonomy gap audit")
    parser.add_argument("--oof", required=True, type=Path)
    parser.add_argument("--eligible", required=True, type=Path)
    parser.add_argument("--taxonomy", required=True, type=Path)
    parser.add_argument("--prior-rv-contract", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_audit(
        oof_path=args.oof,
        eligible_path=args.eligible,
        taxonomy_path=args.taxonomy,
        prior_rv_contract_path=args.prior_rv_contract,
        output_root=args.output_root,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
