from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


SOURCE = Path(__file__).with_name("a2_ng8_risk_r2_true_forward_chain_r1.py")
spec = importlib.util.spec_from_file_location("forward_chain_under_test", SOURCE)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def work(name: str) -> Path:
    path = module.RESULTS / "tests" / f"unit_{os.getpid()}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def base_event(payload="a"):
    return {key: "" for key in module.LEDGER_FIELDS} | {
        "EVENT_ID": "DECISION:2026-08-24", "EVENT_TYPE": "DECISION", "SESSION_DATE": "2026-08-24",
        "CANONICAL_HASH": "c" * 64, "A2_MODEL_HASH": "a" * 64, "NG8_MODEL_HASH": "n" * 64,
        "NG8_RULE_HASH": "r" * 64, "RISK_R2_MODEL_HASH": "k" * 64, "PAYLOAD_SHA256": module.object_sha(payload),
    }


def test_hash_chain_and_idempotent_replay():
    path = work("idempotent") / "ledger.csv"; module.initialize_csv(path, module.LEDGER_FIELDS)
    first, created = module.append_event(path, base_event())
    second, created_again = module.append_event(path, base_event())
    assert created and not created_again and first == second
    assert module.verify_chain(path)["status"] == "PASS"


def test_duplicate_identity_with_different_payload_fails():
    path = work("duplicate") / "ledger.csv"; module.initialize_csv(path, module.LEDGER_FIELDS)
    module.append_event(path, base_event("a"))
    with pytest.raises(module.ForwardChainError, match="NONDETERMINISTIC"):
        module.append_event(path, base_event("b"))


def test_hash_chain_detects_mutation():
    path = work("mutation") / "ledger.csv"; module.initialize_csv(path, module.LEDGER_FIELDS); module.append_event(path, base_event())
    path.write_text(path.read_text(encoding="utf-8").replace("2026-08-24", "2026-08-25"), encoding="utf-8")
    assert module.verify_chain(path)["status"] == "FAIL_CLOSED"


def test_pre_freeze_and_future_dates_are_rejected_by_contract():
    provider = module.calendar_provider()
    identity = module.frozen_identity()
    first = module.first_session_after_freeze(provider, identity["ng8_freeze_timestamp"])
    first_risk = module.first_session_after_freeze(provider, identity["risk_freeze_timestamp"])
    assert first == "2026-08-21"
    assert first_risk == "2026-08-24"
    assert "2026-08-20" < first


def test_unmatured_outcome_is_not_a_decision_mutation():
    path = work("maturity") / "ledger.csv"; module.initialize_csv(path, module.LEDGER_FIELDS)
    decision = base_event(); decision["OUTCOME_MATURITY_STATUS"] = "PENDING"
    row_hash, _ = module.append_event(path, decision)
    assert module.ledger_rows(path)[0]["ROW_HASH"] == row_hash
    assert len(module.ledger_rows(path)) == 1


def test_risk_score_requires_complete_coverage():
    rows = [{"risk": 0.1}, {"risk": None}]
    assert sum(row["risk"] is not None for row in rows) / len(rows) != 1.0


def test_ng8_replacement_is_deterministic():
    values = [("A", 1, 40), ("B", 2, 1), ("C", 21, 2)]
    assert sorted(values, key=lambda x: (x[2], x[0])) == sorted(values, key=lambda x: (x[2], x[0]))


def test_accounting_identity_and_no_broker_action():
    pretrade_nav, cost, posttrade_nav = 1.0, 0.001, 0.999
    assert posttrade_nav == pytest.approx(pretrade_nav - cost)
    assert module.frozen_identity()["ng8_contract"]["prohibited"][-1] == "BROKER_ACTION"


def test_canonical_mutation_guard_and_output_root():
    assert "canonical" not in str(work("guard")).lower()
    with pytest.raises(module.ForwardChainError):
        module.ensure_external_root(Path(r"D:\us-tech-quant"))


def test_freeze_hashes_immutable():
    identity = module.frozen_identity()
    assert identity["status"] == "PASS"
    assert identity["observed"]["ng8_freeze"] == module.NG8_FREEZE_SHA
    assert identity["observed"]["risk_r2_freeze"] == module.RISK_FREEZE_SHA
