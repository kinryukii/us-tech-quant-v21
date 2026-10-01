"""Synthetic write-once whole-batch seal; no real freeze marker is touched."""
import json
from pathlib import Path
import pytest

import freeze_batch as freezer


@pytest.fixture
def synthetic_root(tmp_path, monkeypatch):
    # Keep the production file inventory implementation. Only prerequisite
    # learning completion is substituted; every bound file below is synthetic.
    for name in freezer.CORE_CODE:
        (tmp_path / name).write_text(f"# synthetic {name}\n", encoding="utf-8")
    for name in ["EXPERIMENT_CONTRACT.md", "DESIGN_LOCK.json", "PREDECLARED_PATHS.csv",
                 "input_paths.json", "COMPATIBILITY_MATRIX.csv"]:
        (tmp_path / name).write_text("synthetic sealed input\n", encoding="utf-8")
    for name in ["data/pre_panel.parquet", "models/final/actor.joblib",
                 "predictions/raw_oof_2025.parquet", "predictions/mu_oof_2025.json",
                 "audits/INPUT_AUDIT.json"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic artifact:" + name).encode("utf-8"))
    monkeypatch.setattr(freezer, "ROOT", tmp_path)
    calls = []
    def completed_prerequisites():
        calls.append(True)
        return dict(physical_attempts=172, declared_paths=8194, fit_2026_rows=0,
                    synthetic_only=True)
    monkeypatch.setattr(freezer, "check_prerequisites", completed_prerequisites)
    return tmp_path, calls


def test_seal_binds_all_actual_inventory_hashes_and_preserves_exposure_flags(synthetic_root):
    root, calls = synthetic_root
    expected = {str(p.relative_to(root)): freezer.sha(p) for p in freezer.binding_files()}
    receipt = freezer.freeze()
    assert calls == [True]
    assert receipt["status"] == "ENTIRE_BATCH_FROZEN"
    assert receipt["bindings"] == expected
    assert freezer.verify_freeze() == receipt
    assert receipt["fit_2026_rows"] == 0
    assert receipt["new_numeric_2026_inference_started"] is False
    assert receipt["blind_test"] is False and receipt["prior_exposure_preserved"] is True
    assert receipt["candidate_search_closed"] is True
    assert receipt["no_post_test_tuning"] is True and receipt["all_failures_preserved"] is True
    assert "FROZEN_BEFORE_2026.json" not in receipt["bindings"]


def test_existing_seal_is_write_once_and_cannot_be_replaced_after_tamper(synthetic_root):
    root, calls = synthetic_root
    original = freezer.freeze()
    marker = root / "FROZEN_BEFORE_2026.json"
    before = marker.read_bytes()
    before_mtime = marker.stat().st_mtime_ns
    assert freezer.freeze() == original
    assert calls == [True]
    assert marker.read_bytes() == before and marker.stat().st_mtime_ns == before_mtime
    (root / "optimization.py").write_text("# tampered sealed code\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"FROZEN_BATCH_CHANGED:.*optimization\.py"):
        freezer.verify_freeze()
    with pytest.raises(RuntimeError, match=r"FROZEN_BATCH_CHANGED:.*optimization\.py"):
        freezer.freeze()
    assert calls == [True] and marker.read_bytes() == before


def test_deleted_bound_artifact_is_rejected(synthetic_root):
    root, _ = synthetic_root
    freezer.freeze()
    (root / "models/final/actor.joblib").unlink()
    with pytest.raises(RuntimeError, match=r"FROZEN_BATCH_CHANGED:.*actor\.joblib"):
        freezer.verify_freeze()


@pytest.mark.parametrize("folder", ["predictions/evaluation_2026", "results/evaluation_2026"])
def test_test_stage_cannot_start_before_a_complete_seal(synthetic_root, folder):
    root, calls = synthetic_root
    with pytest.raises(RuntimeError, match="ENTIRE_BATCH_FREEZE_REQUIRED"):
        freezer.verify_freeze()
    (root / folder).mkdir(parents=True)
    with pytest.raises(RuntimeError, match="TEST_ALREADY_STARTED_WITHOUT_SEAL"):
        freezer.freeze()
    assert not calls
    assert not (root / "FROZEN_BEFORE_2026.json").exists()


def test_seal_exclusive_creation_never_overwrites_an_existing_marker(synthetic_root, monkeypatch):
    root, _ = synthetic_root
    marker = root / "FROZEN_BEFORE_2026.json"
    real_inventory = freezer.binding_files
    winner = {"status": "synthetic concurrent writer", "bindings": {}}
    def racing_inventory():
        paths = real_inventory()
        marker.write_text(json.dumps(winner), encoding="utf-8")
        return paths
    monkeypatch.setattr(freezer, "binding_files", racing_inventory)
    with pytest.raises(FileExistsError):
        freezer.freeze()
    assert json.loads(marker.read_text(encoding="utf-8")) == winner
