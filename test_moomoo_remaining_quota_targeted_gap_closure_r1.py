from pathlib import Path

import pandas as pd

import moomoo_remaining_quota_targeted_gap_closure_r1 as task


def test_frozen_maintenance_contract() -> None:
    assert task.MIN_FINAL_RESERVE == 20
    assert task.ZERO_COUNTERS["history_request_count"] == 0
    assert task.ZERO_COUNTERS["post_2025_realized_label_metric_read_count"] == 0
    assert task.ZERO_COUNTERS["mixed_source_content_open_count"] == 0
    assert task.EXPECTED_PRIOR_HASHES["moomoo_fetch_ledger.parquet"] == "c9acd0d5f36f1919df9f2485082b07fceb541cc4bf484090dfa33e232aad5a0f"


def test_published_sources_remain_hash_pinned() -> None:
    evidence = task.verify_prior_artifacts()
    assert evidence["status"] == "PASS"
    assert evidence["risk_registry_status"] == "DENYLISTED_NOT_OPENED"
    assert evidence["taxonomy_surface_sha256"] == "591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646"


def test_empty_fetch_schema_cannot_hide_a_request() -> None:
    plan = pd.DataFrame(columns=task.FETCH_PLAN_COLUMNS)
    results = pd.DataFrame(columns=task.FETCH_RESULT_COLUMNS)
    assert plan.empty and results.empty
    assert "moomoo_code" in plan and "quota_after" in results


def test_completed_build_is_zero_fetch_and_fail_closed() -> None:
    output = task.OUT
    if not (output / "build_summary.json").is_file():
        return
    summary = pd.read_json(output / "build_summary.json", typ="series")
    gaps = pd.read_csv(output / "remaining_moomoo_addressable_gaps.csv")
    plan = pd.read_csv(output / "fetch_plan.csv")
    results = pd.read_csv(output / "fetch_results.csv")
    assert summary["useful_fetchable_gaps"] == 0
    assert summary["unique_securities_fetched"] == 0
    assert plan.empty and results.empty
    security = gaps[gaps["gap_scope"].eq("SECURITY_PRICE_DERIVED_FACTOR_GAP")]
    assert len(security) == 47
    assert int(security["gap_observations"].sum()) == 2704
    assert not security["fetch_selected"].astype(bool).any()
    ea = security[security["moomoo_code"].eq("US.EA")]
    assert len(ea) == 1
    assert ea.iloc[0]["fetchable_status"] == "MOOMOO_PROVIDER_UNAVAILABLE"
    assert "TERMINAL" in ea.iloc[0]["no_retry_reason"]
    assert (security[security["moomoo_code"].ne("US.EA")]["fetchable_status"] == "LEGITIMATE_INSUFFICIENT_HISTORY").all()


def test_no_new_surface_or_registry_patch_materialized() -> None:
    output = task.OUT
    forbidden = [
        "security_factor_risk_surface.parquet",
        "capacity_e1_surface.parquet",
        "pit_sec_sic_ff12_ff48_eligible_surface.parquet",
        "registry_patch.jsonl",
        "moomoo_fetch_ledger.parquet",
    ]
    assert all(not (output / name).exists() for name in forbidden)


def test_final_artifact_hash_readback() -> None:
    path = task.OUT / "final_manifest.json"
    if not path.is_file():
        return
    import json

    manifest = json.loads(path.read_text(encoding="utf-8"))
    for name, evidence in manifest["files"].items():
        artifact = task.OUT / name
        assert artifact.is_file()
        assert task.sha256_file(artifact) == evidence["sha256"]
