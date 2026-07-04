import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UTILS = ROOT / "scripts/v21/v21_194_broad_date_gate_utils.py"
SCRIPT = ROOT / "scripts/v21/v21_194_integrate_broad_date_gate_into_daily_chain.py"
RUNNER = ROOT / "scripts/v21/run_v21_194_integrate_broad_date_gate_into_daily_chain.ps1"
OUT = ROOT / "outputs/v21/V21.194_INTEGRATE_BROAD_DATE_GATE_INTO_DAILY_CHAIN"
SUMMARY = OUT / "v21_194_summary.json"


def load_utils():
    spec = importlib.util.spec_from_file_location("v21_194_broad_date_gate_utils", UTILS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_gate_fixture(tmp_path: Path) -> Path:
    gate_path = tmp_path / "latest_broad_date_gate.json"
    gate_path.write_text(
        json.dumps(
            {
                "raw_canonical_max_date": "2026-06-29",
                "broad_price_latest_date": "2026-06-29",
                "abcd_honest_latest_date": "2026-06-26",
                "blocked_newer_dates": ["2026-06-27", "2026-06-28", "2026-06-29"],
                "broad_date_gate_passed": True,
            }
        ),
        encoding="utf-8",
    )
    return gate_path


def test_helper_loads_gate_and_classifies_dates(tmp_path):
    utils = load_utils()
    gate = utils.load_latest_broad_date_gate(write_gate_fixture(tmp_path))
    assert gate["raw_canonical_max_date"] == "2026-06-29"
    assert gate["abcd_honest_latest_date"] == "2026-06-26"
    blocked = utils.classify_requested_date("2026-06-29", gate)
    allowed = utils.classify_requested_date("2026-06-26", gate)
    assert blocked["classification"] == "NARROW_TAIL_BLOCKED"
    assert blocked["allowed"] is False
    assert allowed["classification"] == "ALLOWED_HONEST_LATEST_DATE"
    assert allowed["allowed"] is True


def test_missing_gate_fails_safely(tmp_path):
    utils = load_utils()
    missing = tmp_path / "latest_broad_date_gate.json"
    try:
        utils.load_latest_broad_date_gate(missing)
    except Exception as exc:
        assert exc.__class__.__name__ == "BroadDateGateError"
    else:
        raise AssertionError("missing gate did not fail")


def test_helper_does_not_mutate_canonical(tmp_path):
    utils = load_utils()
    canonical = tmp_path / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
    canonical.write_text("date,symbol,close\n2026-06-26,DRAM,1.0\n", encoding="utf-8")
    before = canonical.read_text(encoding="utf-8")
    gate = utils.load_latest_broad_date_gate(write_gate_fixture(tmp_path))
    utils.emit_broad_date_gate_snapshot(tmp_path / "snapshot.json", gate)
    assert canonical.read_text(encoding="utf-8") == before


def test_static_contract_files():
    assert UTILS.is_file()
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = UTILS.read_text(encoding="utf-8")
    for name in [
        "load_latest_broad_date_gate",
        "resolve_honest_latest_date",
        "assert_target_date_is_broad_eligible",
        "classify_requested_date",
        "build_blocked_newer_dates_audit",
        "emit_broad_date_gate_snapshot",
    ]:
        assert f"def {name}" in text


def test_summary_and_contract_if_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["gate_loaded"] is True
    assert summary["abcd_honest_latest_date"] == "2026-06-26"
    contract = OUT / "broad_date_gate_contract.json"
    assert contract.is_file()
    payload = json.loads(contract.read_text(encoding="utf-8"))
    assert payload["blocked_if_requested_date_newer_than_abcd_honest_latest_date"] is True
    assert payload["example_20260629"]["allowed"] is False
    assert payload["example_20260626"]["allowed"] is True
