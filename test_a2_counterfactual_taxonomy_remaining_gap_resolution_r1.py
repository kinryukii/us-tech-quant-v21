from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pandas as pd

import a2_counterfactual_taxonomy_remaining_gap_resolution_r1 as task


OUT = task.OUT


def read_json(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_authoritative_denominator_and_left_complete_keyset() -> None:
    base = pd.read_parquet(task.BASE_SURFACE, columns=["decision_date", "canonical_security_id", "ff48_code"])
    after = pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet", columns=["decision_date", "canonical_security_id", "ff48_code"])
    assert len(base) == len(after) == task.TOTAL
    assert int(base.ff48_code.notna().sum()) == task.BASE_MAPPED
    assert not after.duplicated(["decision_date", "canonical_security_id"]).any()
    assert set(map(tuple, base[["decision_date", "canonical_security_id"]].to_numpy())) == set(map(tuple, after[["decision_date", "canonical_security_id"]].to_numpy()))


def test_no_moomoo_or_outcome_reads_and_no_current_backfill() -> None:
    readiness = read_json("counterfactual_readiness.json")
    counters = readiness["zero_read_counters"]
    assert counters["new_moomoo_fetch_count"] == 0
    assert counters["moomoo_history_request_count"] == 0
    assert counters["post_2025_realized_label_metric_read_count"] == 0
    assert counters["post_2025_model_evaluation_metric_read_count"] == 0
    assert counters["post_2025_outcome_derived_metadata_read_count"] == 0
    assert counters["2026_economic_outcome_read_count"] == 0
    assert counters["holdout_peek_count"] == 0
    assert counters["mixed_source_content_open_count"] == 0
    contract = read_json("targeted_recovery_contract.json")
    assert "CURRENT_SIC_BACKFILL" in contract["forbidden"]
    assert "CURRENT_MOOMOO_INDUSTRY" in contract["forbidden"]
    assert "TOP20_DEPENDENT_TAXONOMY" in contract["forbidden"]


def test_temporal_contract_reused_and_no_future_filing_backfill() -> None:
    baseline = read_json("authoritative_baseline_manifest.json")
    assert task.sha256_file(task.BASE_SIC_CONTRACT) == task.EXPECTED[task.BASE_SIC_CONTRACT]
    assert baseline["recovery_contract_sha256"] == task.sha256_file(OUT / "targeted_recovery_contract.json")
    evidence = pd.read_parquet(OUT / "new_classification_evidence.parquet")
    assert (pd.to_datetime(evidence.sic_available_at, utc=True) == pd.to_datetime(evidence.acceptance_datetime, utc=True) + pd.Timedelta(minutes=5)).all()
    surface = pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet", columns=["decision_date", "sic_available_at"])
    available = pd.to_datetime(surface.sic_available_at, utc=True)
    assert available[available.notna()].dt.tz_convert(None).le(pd.to_datetime(surface.loc[available.notna(), "decision_date"])).all()


def test_official_ff_mapping_and_sic_3990_remain_immutable() -> None:
    assert task.sha256_file(task.FF48_ZIP) == task.EXPECTED[task.FF48_ZIP]
    mapping, _ = task.parse_ff_definition(task.FF48_ZIP, "FF48")
    assert 3990 not in set(mapping.sic4)
    after = pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet", columns=["sic4", "ff48_code"])
    assert after.loc[after.sic4.eq(3990), "ff48_code"].isna().all()


def test_targeted_sec_batch_is_frozen_and_only_previously_unmapped_rows_change() -> None:
    baseline = read_json("authoritative_baseline_manifest.json")
    assert baseline["targeted_plan_sha256"] == task.sha256_file(OUT / "targeted_sec_recovery_plan.csv")
    plan = pd.read_csv(OUT / "targeted_sec_recovery_plan.csv")
    assert plan.canonical_security_id.nunique() == 84
    assert plan.action.isin(["NO_REQUEST_FAIL_CLOSED", "REUSE_VALIDATED_HEADER_CACHE", "TARGETED_SEC_HEADER_REQUEST"]).all()
    base_for_plan, bridge_for_plan, _, sec_sub_for_plan = task.load_authoritative_inputs()
    rebuilt_plan, _, _ = task.choose_recovery_plan(base_for_plan, bridge_for_plan, sec_sub_for_plan)
    identity_columns = ["canonical_security_id", "action", "plan_reason", "candidate_ciks", "target_accession"]
    assert rebuilt_plan.plan_row_sha256.astype(str).reset_index(drop=True).equals(plan.plan_row_sha256.astype(str).reset_index(drop=True))
    assert rebuilt_plan[identity_columns].fillna("").astype(str).reset_index(drop=True).equals(plan[identity_columns].fillna("").astype(str).reset_index(drop=True))
    base = pd.read_parquet(task.BASE_SURFACE)
    after = pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet")
    changed = base.row_sha256.ne(after.row_sha256)
    assert base.loc[changed, "ff48_code"].isna().all()
    assert base.loc[~changed].reset_index(drop=True).equals(after.loc[~changed].reset_index(drop=True))
    hash_columns = [column for column in after.columns if column != "row_sha256"]
    assert task.foundation_row_sha256(after, hash_columns).equals(after.row_sha256.astype(str))


def test_identity_reused_not_rebuilt_and_new_links_have_historical_ticker() -> None:
    manifest = read_json("taxonomy_surface_manifest.json")
    assert manifest["entity_id"] == task.TAXONOMY_ENTITY
    assert manifest["new_persistent_data_surface_count"] == 1
    results = pd.read_csv(OUT / "targeted_sec_recovery_results.csv")
    promoted_new = results.loc[results.status.eq("PASS") & results.instance_required.eq(True)]
    assert not promoted_new.empty
    for row in promoted_new.itertuples(index=False):
        symbols = {task.normalized_ticker(value) for value in str(row.trading_symbols).split("|")}
        assert task.normalized_ticker(row.ticker_at_date) in symbols


def test_coverage_deterministic_rank_and_year_gates() -> None:
    surface = pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet")
    readiness = read_json("counterfactual_readiness.json")
    assert int(surface.ff48_code.notna().sum()) == readiness["strict_ff48_mapped_after"]
    assert float(surface.ff48_code.notna().mean()) == readiness["strict_ff48_coverage_after"]
    rank_le = float(surface.loc[surface.a2_rank.le(20), "ff48_code"].notna().mean())
    rank_gt = float(surface.loc[surface.a2_rank.gt(20), "ff48_code"].notna().mean())
    assert rank_le == readiness["rank_le20_ff48_coverage_after"]
    assert rank_gt == readiness["rank_gt20_ff48_coverage_after"]
    years = surface.assign(year=pd.to_datetime(surface.decision_date).dt.year).groupby("year").ff48_code.apply(lambda values: float(values.notna().mean()))
    assert float(years.min()) == readiness["minimum_year_ff48_coverage_after"]
    assert readiness["gates"] == {
        "overall_90_gate": True,
        "each_year_85_gate": True,
        "rank_gt20_85_gate": True,
        "rank_coverage_gap_10pp_gate": True,
    }
    closure = pd.read_csv(OUT / "minimal_structural_gap_closure_set.csv")
    selected = closure.loc[closure.minimum_gate_set_member]
    required = int(math.ceil(0.90 * task.TOTAL) - task.BASE_MAPPED)
    assert selected.observations.sum() >= required
    assert selected.iloc[:-1].observations.sum() < required
    bias = pd.read_csv(OUT / "taxonomy_missingness_bias_report.csv")
    listing_age = bias.loc[bias.dimension.eq("LISTING_AGE_BUCKET")]
    assert listing_age.bucket.tolist() == ["UNAVAILABLE_NO_AUTHORITATIVE_LISTING_DATE"]
    ledger = pd.read_parquet(OUT / "remaining_ff48_gap_ledger.parquet")
    assert ledger.first_known_listing_date.isna().all()
    assert ledger.identity_interval_start.notna().all()


def test_registry_head_guard_and_no_parallel_taxonomy_entity() -> None:
    spec = importlib.util.spec_from_file_location("registry_for_tail_gap_test", task.REGISTRY_MODULE)
    assert spec and spec.loader
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    root = task.registry_root(registry)
    current = registry.current_state(root)
    baseline = read_json("authoritative_baseline_manifest.json")
    assert current["status"] == "PASS"
    assert current["head_sha256"] == baseline["registry_base_head"]
    assert registry.query_registry(root, entity_id=task.TAXONOMY_ENTITY)["count"] == 1
    assert registry.query_registry(root, entity_id=task.TASK_ID)["count"] == 0


def test_frozen_rv_v1_unchanged_and_not_run() -> None:
    rv = read_json("rv_data_dependency_report.json")
    assert task.sha256_file(task.RV_CONTRACT) == task.EXPECTED[task.RV_CONTRACT]
    assert rv["rv_contract_modified"] is False
    assert rv["rv_economics_run"] is False
    assert rv["rv_data_dependency_available"] is False


def test_no_repo_local_pytest_staging() -> None:
    forbidden = []
    for pattern in ("pytest-cache-files-*", "nested-probe-*", "_fix*_validation_tmp"):
        forbidden.extend(path for path in task.REPO.glob(pattern) if path.is_dir())
    assert forbidden == []
