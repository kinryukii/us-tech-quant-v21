"""Unit coverage for the fixed, external-storage R4 study primitives."""
from __future__ import annotations

import json
import os
import runpy
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fast3.models.two_stage_direction_hard_r22 import (
    DOWN, EVENT_LABELS, INTERACTIONS, R4ContractError, UP, block_rows, deterministic_schedule,
    prepare_cohort, run_checkpoint, score_architecture, stable_hash, training_weights)


CACHE_ROOT = Path(os.environ["FAST3_CACHE_ROOT"])
FEATURES = ["nine_5m_signed__level", "realized_vol_60m__level", "vix_level__level", "vwap_distance__level"] + [f"f{i}" for i in range(16)]


def cohort(rows: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    timestamp = pd.date_range("2020-01-01", periods=rows, freq="D", tz="UTC")
    frame = pd.DataFrame({"decision_timestamp_et": timestamp, "horizon_timestamp_et": timestamp + pd.Timedelta(hours=24),
                          "feature_available_at_et": timestamp, "underlying": np.where(np.arange(rows) % 2, "QQQ", "SOXX"),
                          "label": np.where(np.arange(rows) % 3 == 0, UP, np.where(np.arange(rows) % 3 == 1, DOWN, "NO_EVENT")),
                          "era": np.where(np.arange(rows) < rows // 2, "old", "new"), "uniqueness_weight": .5 + rng.random(rows),
                          "event_id": [f"e{i}" for i in range(rows)]})
    for index, name in enumerate(FEATURES): frame[name] = rng.normal(size=rows) + index / 100
    return frame


def test_prepare_cohort_excludes_ambiguous_and_rejects_future_feature_timestamp():
    raw = cohort(); raw.loc[0, "label"] = "AMBIGUOUS"
    prepared = prepare_cohort(raw, FEATURES)
    assert "AMBIGUOUS" not in set(prepared.label)
    assert len(prepared) == len(raw) - 1
    raw.loc[1, "feature_available_at_et"] = raw.loc[1, "decision_timestamp_et"] + pd.Timedelta(seconds=1)
    with pytest.raises(R4ContractError, match="FEATURE_NOT_AVAILABLE"):
        prepare_cohort(raw, FEATURES)


def test_schedule_is_deterministic_and_tamper_evident():
    prepared = prepare_cohort(cohort(800), FEATURES)
    first, second = deterministic_schedule(prepared), deterministic_schedule(prepared)
    assert first == second and len(first["blocks"]) == 8
    assert [block["phase"] for block in first["blocks"]] == ["development"] * 4 + ["internal_holdout"] * 4
    assert deterministic_schedule(prepared, existing=first) == first
    broken = dict(first); broken["schedule_hash"] = "not-a-hash"
    with pytest.raises(R4ContractError, match="SCHEDULE_HASH"):
        deterministic_schedule(prepared, existing=broken)


def test_fold_is_expanding_with_24h_purge_and_embargo_and_train_only_preprocessing():
    prepared = prepare_cohort(cohort(800), FEATURES)
    block = deterministic_schedule(prepared)["blocks"][0]
    train, test = block_rows(prepared, block)
    assert train.label_end_timestamp_et.max() < pd.Timestamp(block["start"]) - pd.Timedelta(hours=24)
    direct, _ = score_architecture(train, test, FEATURES, 104729, "direct")
    two, _ = score_architecture(train, test, FEATURES, 104729, "two_stage")
    assert direct.p_event.between(0, 1).all()
    assert two.p_event.between(0, 1).all()
    assert np.allclose(two.p_event, two.p_up + two.p_down)
    assert set(two.predicted_label).issubset(set(EVENT_LABELS))


def test_fold_weights_use_only_training_class_and_era_distribution():
    frame = prepare_cohort(cohort(12), FEATURES)
    target = frame.label.copy()
    weights = training_weights(frame, target)
    assert np.isfinite(weights).all() and (weights > 0).all()
    # A rare class/era has a greater fixed fold-only multiplier than a common one.
    rare = frame.index[(target == UP) & (frame.era == "old")][0]
    common = frame.index[(target == "NO_EVENT") & (frame.era == "new")][0]
    assert weights[rare] != weights[common]


def test_checkpoint_contains_fixed_nulls_and_resumes_only_on_matching_fingerprint():
    prepared = prepare_cohort(cohort(800), FEATURES); schedule = deterministic_schedule(prepared)
    block = schedule["blocks"][0]; train, test = block_rows(prepared, block)
    scratch = CACHE_ROOT / f"r4_checkpoint_test_{uuid.uuid4().hex}"
    source = {"features": FEATURES, "interactions": list(INTERACTIONS), "r3_summary_hash": "a", "r3_model_freeze_hash": "b", "r3_audit_hash": "c"}
    first = run_checkpoint(train, test, FEATURES, "development", block["block_id"], 104729, source, schedule, scratch)
    second = run_checkpoint(train, test, FEATURES, "development", block["block_id"], 104729, source, schedule, scratch)
    assert first == second
    assert set(first["nulls"]) == {"ALWAYS_UP", "ALWAYS_DOWN", "TRAIN_PRIOR_RANDOM_DIRECTION", "FIFTY_FIFTY_RANDOM_DIRECTION", "SHUFFLED_SCORE_FULL_CANDIDATES"}
    assert first["fingerprint"] == stable_hash({"source_freeze": source, "schedule_hash": schedule["schedule_hash"], "phase": "development",
        "block_id": block["block_id"], "seed": 104729, "model_parameters": {"max_iter": 100, "learning_rate": .08, "max_leaf_nodes": 7, "l2_regularization": 1.0}, "threshold": .60, "top_fraction": .05})


def test_runner_writes_all_frozen_not_run_artifacts_to_external_root_only(monkeypatch):
    root = CACHE_ROOT / f"r4_runner_test_{uuid.uuid4().hex}"
    frozen = root / "frozen"; scratch = root / "scratch"; runtime = root / "runtime"; data = root / "data"
    limits = root / "limits.json"; root.mkdir(parents=True)
    limits.write_text(json.dumps({"agent_repo_write_allowlist": ["fast3/scripts/run/fast3_r4_two_stage_direction_hard_r22.py"],
        "storage_contract": {"name": "FAST3_STORAGE_CONTRACT_R1"}, "source_freeze": {}}), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "run" / "fast3_r4_two_stage_direction_hard_r22.py"
    argv = [str(script), "--repo-root", str(Path(__file__).resolve().parents[3]), "--data-root", str(data), "--runtime-root", str(runtime),
            "--scratch-root", str(scratch), "--frozen-root", str(frozen), "--cache-root", str(root), "--source-r3-root", str(root / "missing_r3"),
            "--source-r3-audit-root", str(root / "missing_audit"), "--limits", str(limits), "--run-id", "unit"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_code: runpy.run_path(str(script), run_name="__main__")
    assert exit_code.value.code == 0
    required = json.loads((Path(os.environ["FAST3_AGENT_LIMITS_PATH"])).read_text(encoding="utf-8"))["required_frozen_artifacts"]
    assert all((frozen / filename).is_file() for filename in required)
    manifest = json.loads((frozen / "FAST3_R4_ARTIFACT_HASH_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["manifest_created_last"] is True
