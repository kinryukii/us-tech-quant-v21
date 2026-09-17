from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest


SCRIPT = Path(__file__).with_name("a2_open_research_locked_2026_holdout.py")
REPO_ROOT = Path(r"D:\us-tech-quant")
APPROVED_TEST_ROOT = Path(r"D:\us-tech-quant-cache\a2_locked_holdout_unit_tests")
SPEC = importlib.util.spec_from_file_location("a2_locked_holdout_test_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


@pytest.fixture
def workdir() -> Any:
    parent = APPROVED_TEST_ROOT
    path = parent / uuid.uuid4().hex
    # Fail before writing if this fixture is ever redirected into the repository.
    assert path.is_relative_to(Path(r"D:\us-tech-quant-cache"))
    assert not path.is_relative_to(REPO_ROOT)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)
        parent.rmdir()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _frozen_fixture(tmp_path: Path, *, nonzero_counter: str | None = None) -> Path:
    root = tmp_path / "research"
    freeze_dir = root / "09_pre2026_freeze"
    model = tmp_path / "frozen_model.joblib"
    model.write_bytes(b"frozen-model-test-identity")
    counters = {key: 0 for key in SUBJECT.ZERO_COUNTERS}
    if nonzero_counter:
        counters[nonzero_counter] = 1
    champion = {
        "run_id": "TEST_RUN",
        "status": "RESEARCH_CHALLENGER_NOT_DEPLOYMENT_AUTHORIZATION",
        "champion_id": "RIDGE",
        "frozen_models": [{
            "family": "RIDGE", "seed": 7, "model_path": str(model),
            "model_sha256": SUBJECT.sha256_file(model),
            "features": [f"f{i:02d}" for i in range(32)],
            "training_rows": 100, "max_label_maturity": "2025-12-31",
        }],
        "thresholds": {"economic_top_k": 20, "holdout_top_k": 20},
        "ensemble": {"type": "NONE", "members": ["RIDGE"], "weights": [1.0]},
        "execution": {"mapping": "FROZEN_R4_CLOSE_TO_NEXT_OPEN_EQUAL_WEIGHT_LONG_ONLY", "cost_bps": 10},
        "temporal_counters": counters,
    }
    champion_path = freeze_dir / "pre2026_champion_manifest.json"
    _write_json(champion_path, champion)
    freeze = {
        "run_id": "TEST_RUN",
        "pre2026_research_complete": True,
        "pre2026_selection_complete": True,
        "pre2026_champion_frozen": True,
        "2026_outcome_read_count_at_freeze": 0,
        "artifact_hashes": {champion_path.name: SUBJECT.sha256_file(champion_path)},
        "model_hashes": {model.name: SUBJECT.sha256_file(model)},
        "model_code_sha256": SUBJECT.sha256_file(SUBJECT.ENGINE_SOURCE),
        "selected_candidate_ids": ["RIDGE"],
    }
    freeze["pre2026_freeze_sha256"] = SUBJECT.canonical_hash(freeze)
    _write_json(freeze_dir / "pre2026_freeze_manifest.json", freeze)
    return root


def test_missing_freeze_refuses_before_any_2026_evaluator_call(workdir: Path) -> None:
    called = False

    def forbidden_evaluator(_: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("2026 evaluator must remain sealed")

    with pytest.raises(SUBJECT.HoldoutGovernanceError, match="PRE2026_FREEZE_MISSING"):
        SUBJECT.run_locked_holdout(workdir / "missing", evaluator=forbidden_evaluator)
    assert called is False


def test_nonzero_temporal_counter_refuses_before_any_2026_read(workdir: Path) -> None:
    root = _frozen_fixture(workdir, nonzero_counter="2026_parameter_search_count")
    called = False

    def forbidden_evaluator(_: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("2026 evaluator must remain sealed")

    with pytest.raises(SUBJECT.HoldoutGovernanceError, match="HOLDOUT_GATE_COUNTER_NONZERO"):
        SUBJECT.run_locked_holdout(root, evaluator=forbidden_evaluator)
    assert called is False


def test_gate_verifies_freeze_champion_and_model_hashes(workdir: Path) -> None:
    root = _frozen_fixture(workdir)
    gate = SUBJECT.verify_freeze_gate(root)
    assert gate.freeze_manifest["pre2026_champion_frozen"] is True
    assert gate.champion_manifest["champion_id"] == "RIDGE"
    model = Path(gate.frozen_models[0]["model_path"])
    model.write_bytes(b"tampered")
    with pytest.raises(SUBJECT.HoldoutGovernanceError, match="CHAMPION_MODEL_HASH_MISMATCH"):
        SUBJECT.verify_freeze_gate(root)


def test_temporal_assertion_rejects_unmatured_or_unavailable_rows() -> None:
    cutoff = SUBJECT.pd.Timestamp("2026-08-20")
    valid = SUBJECT.pd.DataFrame({
        "feature_information_available_timestamp": ["2026-08-19"],
        "label_maturity_timestamp": ["2026-08-20"],
        "target": [0.1],
    })
    SUBJECT.assert_locked_temporal_rows(valid, cutoff)
    invalid = valid.copy()
    invalid.loc[0, "label_maturity_timestamp"] = "2026-08-21"
    with pytest.raises(SUBJECT.HoldoutGovernanceError, match="UNMATURED_2026_LABEL"):
        SUBJECT.assert_locked_temporal_rows(invalid, cutoff)


def test_adapter_contains_no_model_fit_or_search_call() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "fit" not in calls
    assert "fit_predict" not in calls
