from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("harness_preflight.py")
SPEC = importlib.util.spec_from_file_location("harness_preflight", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_training_boundary_is_strictly_pre2026() -> None:
    module.assert_training_before_cutoff(["2025-12-31", "2025-12-31T23:59:59"])
    with pytest.raises(module.ResearchBoundaryError, match="TRAINING_TIMESTAMP_NOT_PRE2026"):
        module.assert_training_before_cutoff(["2026-01-01"])


def test_pit_order_rejects_future_information() -> None:
    module.assert_pit_order([("2025-01-01T15:00:00", "2025-01-01T16:00:00")])
    with pytest.raises(module.ResearchBoundaryError, match="PIT_INFORMATION_AFTER_DECISION"):
        module.assert_pit_order([("2025-01-02", "2025-01-01")])


def test_changed_literal_scanner_blocks_train_end_but_allows_exclusive_cutoff() -> None:
    safe = module._boundary_literal_violations("safe.py", 'TRAINING_CUTOFF = "2026-01-01"\n')
    bad = module._boundary_literal_violations("bad.py", 'TRAIN_END_DATE = "2026-01-02"\n')
    assert not safe
    assert bad == ["bad.py:1:2026-01-02"]


def test_exposed_holdout_is_scoped_hard_blocker() -> None:
    row = module._holdout_status_finding(
        "FAIL_CLOSED_PRIOR_2026_OUTCOME_EXPOSURE_PRECEDES_CONTRACT"
    )
    assert row["level"] == "HARD_BLOCKER"
    assert row["blocks"] == ["2026-optimization"]


def test_registry_2026_training_flag_fails_closed() -> None:
    registry = {
        "governance": {"auto_promotion_forbidden": True, "requires_explicit_user_authorization": True},
        "models": [{
            "model_id": "BAD", "training_cutoff": "PRE2026", "uses_2026_training": True,
            "uses_2026_parameter_search": False, "uses_2026_model_selection": False,
        }],
    }
    rows = module._registry_semantic_findings(Path("alpha_registry.json"), registry)
    assert any(row["code"] == "RESEARCH_REGISTRY_2026_REUSE" for row in rows)


def test_default_scope_does_not_apply_2026_optimization_blocker(monkeypatch) -> None:
    monkeypatch.setattr(module, "_git_paths", lambda repo: ([], []))
    monkeypatch.setattr(module, "_contract_findings", lambda repo: [])
    monkeypatch.setattr(module, "_anti_bloat_findings", lambda repo: [])
    monkeypatch.setattr(module, "_changed_training_findings", lambda repo, paths: [])
    monkeypatch.setattr(module, "_holdout_findings", lambda repo: [
        module.finding("HARD_BLOCKER", "EXPOSED", "fixture", ("2026-optimization",))
    ])
    default = module.run_preflight(Path.cwd(), "independent-code")
    optimization = module.run_preflight(Path.cwd(), "2026-optimization")
    assert default["preflight_status"] == "PASS_WITH_SCOPED_HARD_BLOCKERS"
    assert default["applicable_hard_blocker_count"] == 0
    assert optimization["preflight_status"] == "HARD_BLOCKER"
    assert optimization["applicable_hard_blocker_count"] == 1
