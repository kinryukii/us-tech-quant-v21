import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pandas as pd
import pytest

import artifact_lifecycle as lifecycle
from generation3r3_research import DIRECTION_MARGINS, OPPORTUNITY_THRESHOLDS, _funnel_row, _promotion_gate, _reasoned_actions, artifact_lifecycle_closeout, calibrated_probability, coverage_surface, finalize_phase, fixed_contract, overlap_selector, repair_metrics, separated_execution


def _metadata(**updates):
    value = {
        "metadata_complete": True,
        "status": "PASS_COMPLETE",
        "run_role": "EXPLORATORY",
        "promotion_status": "REJECTED_NOT_SELECTED",
    }
    value.update(updates)
    return value


def _evidence(**updates):
    value = {
        "final_metrics_persisted": True,
        "config_identity_persisted": True,
        "final_status_persisted": True,
        "required_ledger_persisted": True,
        "manifest_finalized": True,
    }
    value.update(updates)
    return value


def _closeout(root: Path, candidates, **updates):
    options = {
        "run_root": root,
        "candidates": candidates,
        "metadata": _metadata(),
        "evidence": _evidence(),
        "approved_roots": (root,),
    }
    options.update(updates)
    return lifecycle.closeout_artifacts(**options)


@pytest.fixture
def lifecycle_tmp():
    parent = Path(os.environ.get("ARTIFACT_LIFECYCLE_TEST_ROOT", tempfile.gettempdir())).resolve()
    parent.mkdir(parents=True, exist_ok=True, mode=0o777)
    path = parent / ("case_" + uuid.uuid4().hex)
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def test_3r3_contract_preserves_frozen_split_and_confirmation_isolation():
    dates = pd.date_range("2023-03-01", "2026-07-28", freq="B", tz="America/New_York")
    contract = fixed_contract(dates, pd.Timestamp("2026-07-28 11:16", tz="America/New_York"))
    assert str(contract["development_start"]).startswith("2023-03-01")
    assert contract["confirmation_read_count"] == 0
    assert contract["research_id"].endswith("ITERATION")


def test_reason_codes_are_exclusive_and_cover_all_scored_rows():
    rows = pd.DataFrame({"decision_timestamp": pd.date_range("2025-01-02", periods=4, freq="5min", tz="America/New_York"), "calendar_date": pd.date_range("2025-01-02", periods=4, freq="5min", tz="America/New_York").normalize(), "soxl_gross_60m_delay0": [.01, .01, None, .01], "soxs_gross_60m_delay0": [.01, .01, .01, .01]})
    result = _reasoned_actions(rows, [0.2, .6, .8, .9], [.5, .51, .9, .1])
    assert len(result.reason) == 4
    assert set(result.reason).issubset({"NO_OPPORTUNITY", "LOW_DIRECTION_CONFIDENCE", "EXPECTED_NET_BELOW_BUFFER", "ETF_MAPPING_FAILURE", "TRADE"})


def test_probability_quantile_column_is_data_not_dataframe_method():
    quantiles = pd.DataFrame({"quantile": [0.5], "p_opp": [0.6]})
    assert float(quantiles.iloc[0]["quantile"]) == 0.5


def test_funnel_reports_legacy_joint_probability_gate_separately():
    samples = pd.DataFrame({"opportunity_60m": [0, 1]})
    scored = samples.copy()
    actions = pd.DataFrame({"reason": ["NO_OPPORTUNITY", "TRADE"], "p_opp": [.2, .8], "direction_confidence": [0, .1], "action": ["LONG", "LONG"], "expected_net": [0, .01], "mapped": [True, True], "decision_timestamp": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York")})
    legacy = pd.DataFrame({"probability_long": [.1, .6], "probability_short": [.1, .1], "action": ["FLAT", "LONG"], "net_10bps_delay0": [None, .01], "decision_timestamp": actions.decision_timestamp})
    row = _funnel_row("C3", 3, 2, samples, scored, actions, legacy)
    assert row["legacy_joint_probability_pass_count"] == 1


def test_coverage_surface_is_coordinate_only_and_uses_frozen_grid():
    rows = coverage_surface([.3, .5, .7], [.5, .6, .4], "C3")
    assert len(rows) == len(OPPORTUNITY_THRESHOLDS) + len(DIRECTION_MARGINS)
    assert all(row["uses_economic_returns"] is False for row in rows)
    assert {row["stage"] for row in rows} == {"OPPORTUNITY_COVERAGE_ONLY", "DIRECTION_COVERAGE_ONLY"}


def test_separated_execution_does_not_use_joint_probability_gate():
    rows = pd.DataFrame({"decision_timestamp": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York"), "calendar_date": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York").normalize(), **{f"{s}_gross_60m_delay{d}": [.01, .01] for s in ("soxl", "soxs") for d in (0, 1, 3, 5)}})
    output = separated_execution(rows, [.8, .8], [.54, .46])
    assert output.action.tolist() == ["LONG", "SHORT"]


def test_empty_repair_metrics_fails_promotion():
    metrics = repair_metrics(pd.DataFrame({"decision_timestamp": pd.Series([], dtype="datetime64[ns, America/New_York]"), "action": [], "net_10bps_delay0": []}))
    assert _promotion_gate(metrics)[0] is False


def test_calibrator_is_fit_only_on_training_subperiod():
    train = pd.DataFrame({"feature": list(range(20)), "label": [0, 1] * 10})
    test = pd.DataFrame({"feature": [20, 21]})
    result = calibrated_probability(train, test, ["feature"], "label", "sigmoid")
    assert len(result) == 2 and ((result >= 0) & (result <= 1)).all()


def test_overlap_policy_per_direction_allows_opposing_signal():
    frame = pd.DataFrame({"decision_timestamp": pd.to_datetime(["2025-01-02 10:00", "2025-01-02 10:05"]).tz_localize("America/New_York"), "action": ["LONG", "SHORT"], "net_10bps_delay0": [.01, .01]})
    assert len(overlap_selector("one_active_position_per_direction")(frame)) == 2
    assert len(overlap_selector("one_active_position_globally")(frame)) == 1


def test_lifecycle_protected_full_attempts_nothing(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "scratch.bin"; target.write_bytes(b"x")
    result = _closeout(root, [target], metadata=_metadata(frozen=True))
    assert result["lifecycle_class"] == "PROTECTED_FULL"
    assert result["deleted_target_count"] == 0 and target.exists()


def test_lifecycle_selected_full_retains_bulky_artifacts(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "matrix.parquet"; target.write_bytes(b"bulky")
    result = _closeout(root, [target], metadata=_metadata(selected=True))
    assert result["lifecycle_class"] == "SELECTED_FULL"
    assert result["deleted_target_count"] == 0 and target.exists()


def test_lifecycle_rejected_exploratory_removes_ephemeral_runtime(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "temporary_predictions.parquet"; target.write_bytes(b"12345")
    result = _closeout(root, [target])
    assert result["cleanup_status"] == "CLEANUP_COMPLETE"
    assert result["bytes_reclaimed"] == 5 and not target.exists()


def test_lifecycle_failed_run_keeps_evidence_and_removes_scratch(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir()
    evidence_file = root / "failure_summary.json"; evidence_file.write_text("{}", encoding="utf-8")
    scratch = root / "scratch"; scratch.mkdir(); (scratch / "partial.bin").write_bytes(b"123")
    result = _closeout(root, [scratch], metadata=_metadata(status="FAILED_RUNTIME", run_role="RESEARCH_CANDIDATE"))
    assert result["lifecycle_class"] == "FAILED" and result["bytes_reclaimed"] == 3
    assert evidence_file.exists() and not scratch.exists()


def test_lifecycle_missing_final_metrics_blocks_cleanup(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "temp.bin"; target.write_bytes(b"x")
    result = _closeout(root, [target], evidence=_evidence(final_metrics_persisted=False))
    assert result["cleanup_status"] == "CLEANUP_NOT_RUN_EVIDENCE_INCOMPLETE" and target.exists()


def test_lifecycle_incomplete_metadata_is_unknown_and_kept(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "temp.bin"; target.write_bytes(b"x")
    result = _closeout(root, [target], metadata={"status": "PASS"})
    assert result["lifecycle_class"] == "UNKNOWN" and result["cleanup_status"] == "KEEP_UNKNOWN"
    assert target.exists()


def test_lifecycle_rejects_target_outside_approved_root(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); outside = lifecycle_tmp / "outside.bin"; outside.write_bytes(b"x")
    result = _closeout(root, [outside])
    assert result["skip_reasons"] == {"OUTSIDE_APPROVED_ROOT": 1} and outside.exists()


def test_lifecycle_hard_rejects_canonical_and_frozen_paths(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir()
    canonical = root / "canonical"; canonical.mkdir(); (canonical / "temp.bin").write_bytes(b"x")
    frozen = root / "frozen_bundle"; frozen.mkdir(); (frozen / "temp.bin").write_bytes(b"y")
    result = _closeout(root, [canonical, frozen])
    assert result["skip_reasons"] == {"PROTECTED_PATH_REJECTED": 2}
    assert canonical.exists() and frozen.exists()


def test_lifecycle_nested_targets_do_not_double_count(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); parent = root / "scratch"; parent.mkdir()
    child = parent / "matrix.bin"; child.write_bytes(b"1234567")
    result = _closeout(root, [parent, child])
    assert result["deleted_target_count"] == 1 and result["bytes_reclaimed"] == 7
    assert result["skip_reasons"] == {"COVERED_BY_PARENT_TARGET": 1}


def test_lifecycle_permission_failure_continues_and_preserves_research_status(lifecycle_tmp, monkeypatch):
    root = lifecycle_tmp / "run"; root.mkdir()
    blocked = root / "blocked.bin"; blocked.write_bytes(b"12")
    removable = root / "removable.bin"; removable.write_bytes(b"345")
    original = lifecycle._delete_path

    def selective_delete(path):
        if path == blocked:
            raise PermissionError("synthetic")
        original(path)

    monkeypatch.setattr(lifecycle, "_delete_path", selective_delete)
    result = _closeout(root, [blocked, removable])
    assert result["cleanup_status"] == "CLEANUP_PARTIAL_PERMISSION_OR_IO"
    assert blocked.exists() and not removable.exists() and result["bytes_reclaimed"] == 3


def test_lifecycle_dry_run_has_zero_filesystem_mutation(lifecycle_tmp):
    root = lifecycle_tmp / "run"; root.mkdir(); target = root / "temp.bin"; target.write_bytes(b"1234")
    result = _closeout(root, [target], dry_run=True)
    assert result["cleanup_status"] == "DRY_RUN" and result["would_reclaim_bytes"] == 4
    assert result["bytes_reclaimed"] == 0 and target.read_bytes() == b"1234"


def test_runner_cleanup_dry_run_changes_no_files(lifecycle_tmp):
    output = lifecycle_tmp / "run"; output.mkdir()
    required = {
        "generation3r3_split_contract.json": b"{}",
        "generation3r3_final_summary.json": b"{}",
        "generation3r3_final_checkpoint.json": b"{}",
        "generation3r3_candidate_registry.csv": b"candidate_id\nC1\n",
        "generation3r3_development_walkforward_metrics.csv": b"candidate_id\nC1\n",
        "generation3r3_probability_distributions.csv": b"12345",
        "generation3r3_threshold_coverage_surface.csv": b"6789",
    }
    for name, payload in required.items():
        (output / name).write_bytes(payload)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    result = artifact_lifecycle_closeout(output, "PASS_COMPLETE", dry_run=True)
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert result["cleanup_status"] == "DRY_RUN" and result["would_reclaim_bytes"] == 9
    assert before == after


def test_future_runner_finalize_embeds_compact_lifecycle_summary(lifecycle_tmp):
    output = lifecycle_tmp / "run"; output.mkdir()
    (output / "generation3r3_split_contract.json").write_text(
        json.dumps({"confirmation_read_count": 0, "contract_sha256": "synthetic"}), encoding="utf-8"
    )
    pd.DataFrame([{"candidate_id": "C1", "decision": "REJECT"}]).to_csv(
        output / "generation3r3_candidate_registry.csv", index=False
    )
    pd.DataFrame([{"candidate_id": "C1", "metric": 0.0}]).to_csv(
        output / "generation3r3_development_walkforward_metrics.csv", index=False
    )
    disposable = {
        "generation3r3_probability_distributions.csv": b"12345",
        "generation3r3_threshold_coverage_surface.csv": b"6789",
    }
    for name, payload in disposable.items():
        (output / name).write_bytes(payload)
    finalize_phase(output)
    summary = json.loads((output / "generation3r3_final_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_GENERATION3R3_FUNNEL_DIAGNOSIS_COMPLETE"
    assert summary["artifact_lifecycle"]["cleanup_status"] == "CLEANUP_COMPLETE"
    assert summary["artifact_lifecycle"]["bytes_reclaimed"] == 9
    assert not any((output / name).exists() for name in disposable)
