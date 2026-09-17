from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_no_prospective_outcome_or_broker_api_access() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src/fast4").glob("*.py"))
    lowered = source.lower()
    assert "runtime/fast3/r34" not in lowered
    assert "r36_tail_risk_guard" not in lowered
    assert "opensectradecontext" not in lowered
    assert "unlock_trade" not in lowered
    assert "place_order" not in lowered
    assert "broker_action_allowed\": true" not in lowered
    assert "stop_fast4_invalid_resume_root" in lowered


def test_compact_repo_layout_and_external_artifact_contract() -> None:
    files = [path for path in ROOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts]
    assert len(files) <= 20
    assert not any(path.suffix in {".parquet", ".joblib", ".db"} for path in files)
