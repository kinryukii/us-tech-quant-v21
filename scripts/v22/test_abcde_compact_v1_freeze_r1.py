from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py"
MANIFEST_PATH = REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json"
GUARD_PATH = REPO_ROOT / "scripts/v22/abcde_compact_v1_freeze_r1_guard.py"
EVIDENCE = Path(r"D:\us-tech-quant-results\ABCDE_COMPACT_V1_REDUNDANCY_AUDIT_R1\abcde_redundancy_summary.json")

spec = importlib.util.spec_from_file_location("abcde_freeze_guard_r1", GUARD_PATH)
guard = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(guard)


def manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def source_contract() -> dict[str, object]:
    return guard.extract_contract(SOURCE)


def test_current_production_contract_matches_frozen_manifest():
    frozen = manifest()
    actual = source_contract()
    assert guard.contract_sha256(actual) == frozen["abcde_contract_sha256"]
    assert actual["strategy_weights"] == frozen["strategy_weights"]
    assert actual["factor_names"] == frozen["factor_names"]
    assert actual["semantic_invariants"] == frozen["semantic_invariants"]


def test_weight_mutation_fails_guard_in_memory():
    frozen = manifest()
    altered = SOURCE.read_text(encoding="utf-8").replace('"momentum": 0.35', '"momentum": 0.36', 1)
    assert guard.contract_sha256(guard.extract_contract_from_text(altered)) != frozen["abcde_contract_sha256"]


def test_volatility_direction_mutation_fails_guard_in_memory():
    frozen = manifest()
    altered = SOURCE.read_text(encoding="utf-8").replace('"volatility_raw"] for k,v in feats.items()}, reverse=True', '"volatility_raw"] for k,v in feats.items()}, reverse=False', 1)
    contract = guard.extract_contract_from_text(altered)
    assert contract["semantic_invariants"]["volatility_reverse"] is False
    assert guard.contract_sha256(contract) != frozen["abcde_contract_sha256"]


def test_strategy_identity_and_scoring_logic_mutations_fail_guard_in_memory():
    frozen = manifest()
    source_text = SOURCE.read_text(encoding="utf-8")
    renamed = source_text.replace('"A1_CONTROL"', '"A1_CONTROL_MUTATED"', 1)
    changed_operator = source_text.replace('weights["momentum"]*mom[t]', 'weights["momentum"]+mom[t]', 1)
    assert guard.contract_sha256(guard.extract_contract_from_text(renamed)) != frozen["abcde_contract_sha256"]
    assert guard.contract_sha256(guard.extract_contract_from_text(changed_operator)) != frozen["abcde_contract_sha256"]


def test_comment_and_format_only_changes_do_not_change_contract_hash():
    source_text = SOURCE.read_text(encoding="utf-8")
    formatting_only = "# freeze guard must ignore comments\n\n" + source_text.replace("    rows=[]", "\n\n    rows=[]", 1)
    assert guard.contract_sha256(guard.extract_contract_from_text(formatting_only)) == guard.contract_sha256(source_contract())


def test_daily_results_are_not_frozen_in_manifest():
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    for forbidden in ("latest_date", "daily_ticker_ranking", "top20_tickers", "daily_raw_score", "2026-08-13"):
        assert forbidden not in text


def test_redundancy_evidence_identity_and_accepted_status():
    frozen = manifest()
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert guard.file_sha256(EVIDENCE) == frozen["redundancy_audit_sha256"]
    assert evidence["status"] == frozen["redundancy_status"] == "PASS"
    assert evidence["ABCDE_REDUNDANCY_CLASSIFICATION"] == frozen["redundancy_classification"] == "B_PARTIALLY_REDUNDANT_MULTIPLE_DISTINCT_VIEWS"
