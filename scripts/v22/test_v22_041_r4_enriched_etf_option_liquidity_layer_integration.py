from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


R4_PATH = Path(__file__).with_name("v22_041_r4_enriched_etf_option_liquidity_layer_integration.py")
V22_PATH = Path(__file__).with_name("v22_041_option_intraday_etf_only_research_layer_r1.py")
SPEC_R4 = importlib.util.spec_from_file_location("v22_041_r4", R4_PATH)
r4 = importlib.util.module_from_spec(SPEC_R4)
assert SPEC_R4.loader is not None
SPEC_R4.loader.exec_module(r4)
SPEC_V22 = importlib.util.spec_from_file_location("v22_041_main", V22_PATH)
v22 = importlib.util.module_from_spec(SPEC_V22)
assert SPEC_V22.loader is not None
SPEC_V22.loader.exec_module(v22)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class FakeR3:
    OUT_REL = Path("outputs") / "v22" / "V22.041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_FROM_CHAIN_CODES"

    @staticmethod
    def run(repo_root: Path, **kwargs):
        out = repo_root / FakeR3.OUT_REL
        out.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "option_code": "US.QQQ_GOOD",
                "underlying": "QQQ",
                "expiration": "2026-07-17",
                "dte": 9,
                "strike": 500,
                "call_put": "CALL",
                "bid": 1.0,
                "ask": 1.1,
                "mid": 1.05,
                "spread": 0.1,
                "spread_pct": 0.095,
                "volume": 10,
                "open_interest": 100,
                "implied_volatility": 0.2,
                "delta": "",
                "gamma": "",
                "theta": "",
                "vega": "",
                "last_price": 1.05,
                "quote_time": "2026-07-08T14:00:00Z",
            }
        ]
        with (out / "live_option_quote_enriched_rows.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        summary = {
            "final_status": "PASS_V22_041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_READY",
            "opend_port_reachable": True,
            "moomoo_quote_context_connected": True,
            "moomoo_quote_context_disconnected_cleanly": True,
            "total_raw_contract_count": 1,
            "total_dte_eligible_count": 1,
            "enrichment_target_count": 1,
            "enrichment_success_count": 1,
            "bid_field_mapped": True,
            "ask_field_mapped": True,
            "volume_field_mapped": True,
            "valid_bid_ask_count": 1,
            "finite_spread_pct_count": 1,
            "spread_pass_count": 1,
            "volume_positive_count": 1,
            "liquidity_candidate_count": 1,
        }
        (out / "v22_041_r3_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary


def make_patch_file(repo: Path):
    path = repo / "scripts" / "v22" / "v22_041_option_intraday_etf_only_research_layer_r1.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "v22_041_r3_live_option_quote_enrichment_from_chain_codes.py\n"
        "read_only_enriched_option_rows\n"
        "allow_fallback_rows: bool = False\n"
        "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES\n",
        encoding="utf-8",
    )


def test_v22_041_uses_enriched_rows_in_execute_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(v22, "load_r3_module", lambda: FakeR3)
    summary = v22.run(tmp_path / "repo", execute=True)
    assert summary["quote_access_status"] == "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES"
    assert summary["fallback_rows_used"] is False
    assert summary["real_readonly_quote_verified"] is True
    assert summary["liquidity_candidate_count"] == 1


def test_fallback_rows_disabled_by_default(tmp_path, monkeypatch):
    class EmptyR3(FakeR3):
        @staticmethod
        def run(repo_root: Path, **kwargs):
            out = repo_root / EmptyR3.OUT_REL
            out.mkdir(parents=True, exist_ok=True)
            (out / "live_option_quote_enriched_rows.csv").write_text("option_code\n", encoding="utf-8")
            return {"final_status": "WARN", "enrichment_success_count": 0}

    monkeypatch.setattr(v22, "load_r3_module", lambda: EmptyR3)
    summary = v22.run(tmp_path / "repo", execute=True)
    assert summary["fallback_rows_used"] is False
    assert summary["final_status"] == v22.WARN_LIVE_UNAVAILABLE_STATUS
    assert summary["contract_attempted_count"] == 0


def test_fallback_rows_cannot_produce_clean_live_enrichment_pass(tmp_path):
    repo = tmp_path / "repo"
    make_patch_file(repo)
    summary = r4.run(repo, execute=True, v22_run_func=lambda *args, **kwargs: {
        "final_status": v22.PASS_STATUS,
        "final_decision": v22.READY_DECISION,
        "quote_access_status": "FALLBACK_LOCAL_RESEARCH_ROWS_USED",
        "fallback_rows_used": True,
        "liquidity_candidate_count": 3,
        "real_readonly_quote_verified": False,
    })
    assert summary["final_status"] == r4.WARN_FALLBACK_STATUS
    assert summary["fallback_rows_used"] is True


def test_bid_ask_volume_field_mapping_from_provider_snapshot_names(tmp_path, monkeypatch):
    monkeypatch.setattr(v22, "load_r3_module", lambda: FakeR3)
    summary = v22.run(tmp_path / "repo", execute=True)
    assert summary["bid_field_mapped"] is True
    assert summary["ask_field_mapped"] is True
    assert summary["volume_field_mapped"] is True


def test_liquidity_filter_applied_after_enrichment(tmp_path, monkeypatch):
    monkeypatch.setattr(v22, "load_r3_module", lambda: FakeR3)
    summary = v22.run(tmp_path / "repo", execute=True)
    candidates = read_rows(tmp_path / "repo" / v22.OUT_REL / "etf_option_liquidity_candidates.csv")
    assert len(candidates) == 1
    assert candidates[0]["liquidity_status"] == "R1_LIQUIDITY_FILTER_PASS"


def test_greeks_missing_are_warning_only(tmp_path, monkeypatch):
    monkeypatch.setattr(v22, "load_r3_module", lambda: FakeR3)
    summary = v22.run(tmp_path / "repo", execute=True)
    assert summary["liquidity_candidate_count"] == 1
    audit = read_rows(tmp_path / "repo" / v22.OUT_REL / "etf_option_quote_audit.csv")
    assert audit[0]["missing_greeks"] == "True"
    assert audit[0]["audit_status"] == "WARN_OPTIONAL_FIELDS_MISSING"


def test_maxcontracts_and_batchsize_are_forwarded(tmp_path, monkeypatch):
    seen = {}

    class SeenR3(FakeR3):
        @staticmethod
        def run(repo_root: Path, **kwargs):
            seen.update(kwargs)
            return FakeR3.run(repo_root, **kwargs)

    monkeypatch.setattr(v22, "load_r3_module", lambda: SeenR3)
    v22.run(tmp_path / "repo", execute=True, max_contracts=7, batch_size=3)
    assert seen["max_contracts"] == 7
    assert seen["batch_size"] == 3


def test_r4_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    make_patch_file(repo)
    summary = r4.run(repo, execute=True, v22_run_func=lambda *args, **kwargs: {
        "final_status": v22.PASS_STATUS,
        "final_decision": v22.READY_DECISION,
        "quote_access_status": "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES",
        "fallback_rows_used": False,
        "liquidity_candidate_count": 1,
        "real_readonly_quote_verified": True,
    })
    payload = json.loads((repo / r4.OUT_REL / "v22_041_r4_summary.json").read_text(encoding="utf-8"))
    for field in r4.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    assert (repo / r4.OUT_REL / "integration_patch_audit.csv").exists()
    assert (repo / r4.OUT_REL / "enriched_v22_041_rerun_audit.csv").exists()


def test_main_v22_041_output_schema_stability(tmp_path, monkeypatch):
    monkeypatch.setattr(v22, "load_r3_module", lambda: FakeR3)
    repo = tmp_path / "repo"
    v22.run(repo, execute=True)
    expected = {
        "etf_option_contract_universe.csv": v22.UNIVERSE_FIELDS,
        "etf_option_quote_audit.csv": v22.QUOTE_AUDIT_FIELDS,
        "etf_option_liquidity_candidates.csv": v22.CANDIDATE_FIELDS,
        "etf_option_rejected_contracts.csv": v22.REJECT_FIELDS,
    }
    for filename, fields in expected.items():
        with (repo / v22.OUT_REL / filename).open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == fields


def test_safety_flags_remain_false(tmp_path):
    repo = tmp_path / "repo"
    make_patch_file(repo)
    summary = r4.run(repo, execute=True, v22_run_func=lambda *args, **kwargs: {"fallback_rows_used": False, "liquidity_candidate_count": 1})
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["research_only"] is True


def test_deterministic_final_status_and_decision(tmp_path):
    def fake(*args, **kwargs):
        return {"fallback_rows_used": False, "liquidity_candidate_count": 1}

    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    make_patch_file(repo_a)
    make_patch_file(repo_b)
    first = r4.run(repo_a, execute=True, v22_run_func=fake)
    second = r4.run(repo_b, execute=True, v22_run_func=fake)
    assert first["final_status"] == second["final_status"] == r4.PASS_STATUS
    assert first["final_decision"] == second["final_decision"] == r4.PASS_DECISION


def test_no_trade_context_or_order_behavior_exists():
    for path in [R4_PATH, V22_PATH]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_names = {"OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    assert func.attr not in forbidden_names
                if isinstance(func, ast.Name):
                    assert func.id not in forbidden_names
        text = path.read_text(encoding="utf-8")
        assert "OpenSecTradeContext" not in text
