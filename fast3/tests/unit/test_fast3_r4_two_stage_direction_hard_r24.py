"""R2.4 unit tests; every generated path is rooted at FAST3_CACHE_ROOT."""
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

from fast3.models.two_stage_direction_hard_r24 import (
    DOWN, EVENT_LABELS, INTERACTIONS, R4ContractError, UP, block_rows, checkpoint_fingerprint,
    deterministic_schedule, prepare_cohort, run_checkpoint, score_architecture, stable_hash,
)

CACHE_ROOT = Path(os.environ["FAST3_CACHE_ROOT"])
FEATURES = ["nine_5m_signed__level", "realized_vol_60m__level", "vix_level__level", "vwap_distance__level"] + [f"f{i}" for i in range(16)]


def sample(rows: int = 800) -> pd.DataFrame:
    rng = np.random.default_rng(24)
    timestamp = pd.date_range("2018-01-01", periods=rows, freq="D", tz="UTC")
    frame = pd.DataFrame({"decision_timestamp_et": timestamp, "entry_timestamp_et": timestamp,
        "horizon_timestamp_et": timestamp + pd.Timedelta(hours=24),
        "feature_available_at_et": timestamp, "underlying": np.where(np.arange(rows) % 2, "QQQ", "SOXX"),
        "label": np.where(np.arange(rows) % 3 == 0, UP, np.where(np.arange(rows) % 3 == 1, DOWN, "NO_EVENT")),
        "era": np.where(np.arange(rows) < rows // 2, "older", "newer"), "uniqueness_weight": .5 + rng.random(rows),
        "event_id": [f"event-{i}" for i in range(rows)]})
    for index, name in enumerate(FEATURES):
        frame[name] = rng.normal(size=rows) + index
    return frame


def test_labels_and_point_in_time_guard():
    raw = sample(); raw.loc[0, "label"] = "AMBIGUOUS"
    result = prepare_cohort(raw, FEATURES)
    assert "AMBIGUOUS" not in set(result.label)
    raw.loc[2, "feature_available_at_et"] += pd.Timedelta(seconds=1)
    with pytest.raises(R4ContractError, match="FEATURE_NOT_AVAILABLE"):
        prepare_cohort(raw, FEATURES)
    raw = sample(); raw.loc[0, "label"] = "OTHER"
    with pytest.raises(R4ContractError, match="UNKNOWN_LABEL"):
        prepare_cohort(raw, FEATURES)


def test_schedule_is_frozen_eight_blocks_and_tamper_evident():
    cohort = prepare_cohort(sample(), FEATURES)
    schedule = deterministic_schedule(cohort)
    assert len(schedule["blocks"]) == 8
    assert [item["phase"] for item in schedule["blocks"]] == ["development"] * 4 + ["internal_holdout"] * 4
    assert deterministic_schedule(cohort, existing=schedule) == schedule
    altered = dict(schedule); altered["schedule_hash"] = "invalid"
    with pytest.raises(R4ContractError, match="SCHEDULE_HASH"):
        deterministic_schedule(cohort, existing=altered)


def test_direct_and_two_stage_are_fixed_and_checkpoint_resume_is_exact():
    cohort = prepare_cohort(sample(), FEATURES); schedule = deterministic_schedule(cohort); block = schedule["blocks"][0]
    train, test = block_rows(cohort, block)
    direct, _ = score_architecture(train, test, FEATURES, 104729, "direct")
    two, _ = score_architecture(train, test, FEATURES, 104729, "two_stage")
    assert direct.p_event.between(0, 1).all() and two.p_event.between(0, 1).all()
    assert np.allclose(two.p_event, two.p_up + two.p_down)
    assert set(two.predicted_label).issubset(EVENT_LABELS)
    source = {"features": FEATURES, "interactions": list(INTERACTIONS), "r3_summary_hash": "one", "r3_model_freeze_hash": "two",
              "r3_audit_hash": "three", "source_cohort_sha256": "four"}
    scratch = CACHE_ROOT / f"r24-checkpoint-{uuid.uuid4().hex}"
    first = run_checkpoint(train, test, FEATURES, "development", block["block_id"], 104729, source, schedule, scratch)
    assert run_checkpoint(train, test, FEATURES, "development", block["block_id"], 104729, source, schedule, scratch) == first
    changed = dict(source); changed["source_cohort_sha256"] = "changed"
    assert checkpoint_fingerprint(source, schedule, "development", block["block_id"], 104729) != checkpoint_fingerprint(changed, schedule, "development", block["block_id"], 104729)
    assert set(first["nulls"]) == {"ALWAYS_UP", "ALWAYS_DOWN", "TRAIN_PRIOR_RANDOM_DIRECTION", "FIFTY_FIFTY_RANDOM_DIRECTION", "SHUFFLED_SCORE_FULL_CANDIDATES"}


def test_launcher_is_external_root_only_and_populates_not_run_artifacts(monkeypatch):
    root = CACHE_ROOT / f"r24-launcher-{uuid.uuid4().hex}"; root.mkdir(parents=True)
    frozen = root / "frozen"
    limits = root / "limits.json"
    limits.write_text(json.dumps({"agent_repo_write_allowlist": ["fast3/scripts/run/fast3_r4_two_stage_direction_hard_r24.py"],
        "storage_contract": {"name": "FAST3_STORAGE_CONTRACT_R1"}, "source_freeze": {}}), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "run" / "fast3_r4_two_stage_direction_hard_r24.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--repo-root", str(Path(__file__).resolve().parents[3]), "--data-root", str(root / "data"),
        "--runtime-root", str(root / "runtime"), "--scratch-root", str(root / "scratch"), "--frozen-root", str(frozen),
        "--cache-root", str(root), "--source-r3-root", str(root / "missing"), "--source-r3-audit-root", str(root / "missing-audit"),
        "--limits", str(limits), "--run-id", "unit"])
    with pytest.raises(SystemExit) as code:
        runpy.run_path(str(script), run_name="__main__")
    assert code.value.code == 0
    assert (frozen / "FAST3_R4_ARTIFACT_HASH_MANIFEST.json").is_file()
    manifest = json.loads((frozen / "FAST3_R4_ARTIFACT_HASH_MANIFEST.json").read_text())
    assert manifest["manifest_created_last"] is True
