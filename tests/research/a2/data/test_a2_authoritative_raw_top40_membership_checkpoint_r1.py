from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

import a2_authoritative_raw_top40_membership_checkpoint_r1 as runner


def test_frozen_replay_contract_is_narrow() -> None:
    assert runner.EXPECTED_AUTHORITATIVE_REPLAY_FIT_COUNT == 3
    assert runner.NEXT_STEP == "A2_SEC_FUNDAMENTAL_TARGETED_COVERAGE_RECOVERY_R2"
    assert "security_id" in runner.CHECKPOINT_COLUMNS
    assert "raw_rank" in runner.CHECKPOINT_COLUMNS


def test_rank_projection_is_deterministic_and_lexically_tied() -> None:
    frame = pd.DataFrame({
        "signal_date": pd.to_datetime(["2021-01-04"] * 3),
        "ticker": ["B", "A", "C"],
    })
    first = runner.rank_projection(frame, [1.0, 1.0, 0.5], "TEST")
    second = runner.rank_projection(frame, [1.0, 1.0, 0.5], "TEST")
    assert first.ticker.tolist() == ["A", "B", "C"]
    assert first.a2_rank.tolist() == [1, 2, 3]
    assert first.equals(second)


def test_materialized_artifacts_when_present() -> None:
    out = runner.OUT
    manifest_path = out / "hash_manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    assert manifest["artifact_count_including_manifest"] == 6
    for item in manifest["artifacts"]:
        payload = (out / item["name"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
    checkpoint = pd.read_parquet(out / "raw_a2_top40_membership_checkpoint.parquet")
    assert checkpoint.columns.tolist() == runner.CHECKPOINT_COLUMNS
    assert checkpoint.decision_date.nunique() == 1253
    assert len(checkpoint) == 50120
    assert checkpoint.groupby("decision_date").size().eq(40).all()
    assert checkpoint.groupby("decision_date").is_raw_top20.sum().eq(20).all()
    assert checkpoint.groupby("decision_date").raw_rank.apply(lambda x: sorted(x.tolist()) == list(range(1, 41))).all()
    assert checkpoint.duplicated(["decision_date", "security_id"]).sum() == 0
    assert checkpoint.security_id.isna().sum() == 0
    metrics = json.loads((out / "reconciliation_metrics.json").read_text(encoding="utf-8"))
    assert metrics["research_model_fit_count"] == 0
    assert metrics["hyperparameter_search_count"] == 0
    assert metrics["authoritative_replay_fit_count"] == 3
    assert metrics["top40_replay_hash_match"] is True
    assert metrics["top20_identity_mismatch_date_count"] == 0
    assert metrics["top20_rank_identity_mismatch_count"] == 0
    assert metrics["missing_decision_date_count"] == 0
    assert metrics["2026_outcome_used"] is False
