from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_041_r1a_etf_option_moomoo_readonly_quote_and_log_permission_repair.py")
SPEC = importlib.util.spec_from_file_location("v22_041_r1a", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "moomoo_log_permission_diagnostic.csv",
    "moomoo_readonly_quote_smoke_test.csv",
    "v22_041_r1a_summary.json",
    "V22.041_R1A_moomoo_readonly_quote_and_log_permission_repair_report.txt",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_safe_log_dir_selection_is_repo_output_scoped(tmp_path):
    repo = tmp_path / "repo"
    out = repo / module.OUT_REL
    selected = module.select_safe_log_dir(repo.resolve(), out.resolve())
    assert selected == (out / "provider_logs").resolve()
    assert out.resolve() in selected.parents


def test_access_denied_detection_extracts_exact_log_path():
    text = r"PermissionError: [WinError 5] Access is denied: 'C:\Users\Lenovo\AppData\Roaming\com.moomoo.OpenD\Log\py_2026_07_06.log'"
    assert module.is_access_denied_text(text) is True
    paths = module.extract_log_paths(text)
    assert r"C:\Users\Lenovo\AppData\Roaming\com.moomoo.OpenD\Log\py_2026_07_06.log" in paths


def test_writable_safe_log_dir_validation(tmp_path):
    safe_dir = tmp_path / "repo" / "outputs" / "v22" / "stage" / "provider_logs"
    writable, error = module.validate_writable_dir(safe_dir)
    assert writable is True
    assert error == ""
    assert safe_dir.exists()
    assert not (safe_dir / "v22_041_r1a_write_probe.tmp").exists()


def test_fallback_is_explicit_and_never_mislabeled_as_live_quote_success(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, execute=False)
    assert summary["final_status"] == module.WARN_STATUS
    assert summary["final_decision"] == module.BLOCKED_DECISION
    assert summary["quote_access_status"] == "EXECUTE_NOT_REQUESTED"
    assert summary["fallback_rows_used"] is True
    assert summary["real_readonly_quote_verified"] is False


def test_execute_import_failure_records_fallback_not_live_success(tmp_path):
    def missing_import(name: str):
        raise ModuleNotFoundError("No module named 'moomoo'")

    summary = module.run(tmp_path / "repo", execute=True, import_func=missing_import)
    assert summary["moomoo_import_available"] is False
    assert summary["moomoo_quote_context_attempted"] is False
    assert summary["quote_access_status"] == "MOOMOO_IMPORT_UNAVAILABLE"
    assert summary["fallback_rows_used"] is True
    assert summary["real_readonly_quote_verified"] is False
    assert summary["final_status"] == module.WARN_STATUS


class FakeFrame:
    def to_dict(self, orient: str):
        assert orient == "records"
        return [{"code": "US.QQQ260717C500000"}]


class FakeQuoteContext:
    closed = False

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def get_option_chain(self, code: str):
        assert code == "US.QQQ"
        return 0, FakeFrame()

    def close(self):
        FakeQuoteContext.closed = True


class FakeMoomoo:
    OpenQuoteContext = FakeQuoteContext


def test_successful_readonly_quote_smoke_sets_expected_pass_status(tmp_path):
    FakeQuoteContext.closed = False
    summary = module.run(tmp_path / "repo", execute=True, import_func=lambda name: FakeMoomoo)
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["final_decision"] == module.READY_DECISION
    assert summary["moomoo_import_available"] is True
    assert summary["moomoo_quote_context_attempted"] is True
    assert summary["moomoo_quote_context_connected"] is True
    assert summary["moomoo_quote_context_disconnected_cleanly"] is True
    assert summary["real_readonly_quote_verified"] is True
    assert summary["fallback_rows_used"] is False


def test_broker_and_official_adoption_gates_remain_false(tmp_path):
    summary = module.run(tmp_path / "repo", execute=False)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["research_only"] is True


def test_trade_context_unlock_and_place_order_flags_remain_false(tmp_path):
    summary = module.run(tmp_path / "repo", execute=False)
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, execute=False)
    payload = json.loads((repo / module.OUT_REL / "v22_041_r1a_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_output_csv_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    module.run(repo, execute=False)
    expected = {
        "moomoo_log_permission_diagnostic.csv": module.LOG_DIAGNOSTIC_FIELDS,
        "moomoo_readonly_quote_smoke_test.csv": module.SMOKE_FIELDS,
    }
    for filename, fields in expected.items():
        with (repo / module.OUT_REL / filename).open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == fields


def test_deterministic_final_status_and_decision_with_fake_success(tmp_path):
    first = module.run(tmp_path / "a", execute=True, import_func=lambda name: FakeMoomoo)
    second = module.run(tmp_path / "b", execute=True, import_func=lambda name: FakeMoomoo)
    assert first["final_status"] == second["final_status"] == module.PASS_STATUS
    assert first["final_decision"] == second["final_decision"] == module.READY_DECISION


def test_no_trade_context_or_order_behavior_exists():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_names = {"OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_names
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_names
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in text
