from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_229_moomoo_only_data_source_policy_gate.py")
spec = importlib.util.spec_from_file_location("v21_229", MODULE_PATH)
v229 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v229)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_v228(root: Path) -> Path:
    out = root / "outputs/v21/V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY"
    write(out / "v21_228_summary.json", json.dumps({"failed_copy_count": 0}))
    write(out / "copy_only_policy_gate.json", json.dumps({"next_allowed_stage": v229.STAGE}))
    return out


def test_detects_import_yfinance_active_blocker(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/bad.py", "import yfinance as yf\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["active_yfinance_blocker_count"] >= 1


def test_detects_yf_download_active_blocker(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/bad.py", "prices = yf.download('SPY')\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["active_yfinance_blocker_count"] >= 1


def test_detects_yahoo_string_references(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/bad.py", "url='https://query1.finance.yahoo.com'\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["yahoo_usage_count"] >= 1


def test_distinguishes_historical_output_metadata(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/OLD/summary.json", '{"yfinance_used": true, "provider": "Yahoo"}')
    summary = v229.run(root, tmp_path / "out")
    assert summary["final_status"] == v229.PASS_STATUS
    rows = read_csv(tmp_path / "out" / "yfinance_usage_inventory.csv")
    assert rows[0]["is_historical_metadata"] == "True"


def test_yfinance_artifacts_forbidden_for_future_active_chain(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/OLD/report.txt", "yfinance historical metadata")
    v229.run(root, tmp_path / "out")
    rows = read_csv(tmp_path / "out" / "repository_data_source_scan.csv")
    assert next(r for r in rows if "report.txt" in r["path"])["future_active_chain_allowed"] == "False"


def test_moomoo_opend_local_cache_allowed(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/good.py", "MOOMOO_ONLY local Moomoo cache OpenD\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["moomoo_allowed_usage_count"] >= 1


def test_external_fallback_diagnostic_only(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/diag/report.txt", "external_fallback stooq")
    summary = v229.run(root, tmp_path / "out")
    assert summary["diagnostic_only_allowlist_count"] >= 1


def test_policy_json_disallows_yfinance_by_default(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    summary = v229.run(root, tmp_path / "out")
    policy = json.loads((tmp_path / "out" / "data_source_policy.json").read_text())
    assert policy["yfinance_allowed_by_default"] is False


def test_creates_required_audit_csvs(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/DRAM/report.txt", "DRAM MOOMOO_ONLY")
    write(root / "outputs/v21/ABCDE/report.txt", "ABCDE MOOMOO_ONLY")
    out = tmp_path / "out"
    v229.run(root, out)
    for name in ["active_chain_policy_audit.csv", "canonical_source_policy_audit.csv", "dram_policy_readiness_audit.csv", "abcde_policy_readiness_audit.csv", "diagnostic_only_allowlist_plan.csv", "moomoo_only_enforcement_plan.csv"]:
        assert (out / name).exists()


def test_consumes_v21_228_context(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    summary = v229.run(root, tmp_path / "out")
    assert summary["v21_228_crosscheck_status"] == "FOUND"


def test_no_banned_imports():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_warning_status_when_active_blockers_found(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/bad.py", "import yfinance as yf\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["final_status"] == v229.WARN_STATUS


def test_pass_status_when_only_historical_references(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/OLD/report.txt", "Yahoo yfinance old report")
    summary = v229.run(root, tmp_path / "out")
    assert summary["final_status"] == v229.PASS_STATUS


def test_fail_on_active_blockers_returns_nonzero(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "scripts/v21/bad.py", "import yfinance as yf\n")
    code = v229.main(["--repo-root", str(root), "--output-dir", str(tmp_path / "out"), "--fail-on-active-blockers"])
    assert code != 0


def test_creates_all_named_outputs(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    out = tmp_path / "out"
    v229.run(root, out)
    required = [
        "v21_229_summary.json", "data_source_policy.json", "repository_data_source_scan.csv",
        "forbidden_source_usage_inventory.csv", "yfinance_usage_inventory.csv", "yahoo_string_inventory.csv",
        "moomoo_allowed_usage_inventory.csv", "external_fallback_inventory.csv", "script_import_policy_audit.csv",
        "wrapper_env_policy_audit.csv", "config_policy_audit.csv", "output_manifest_policy_audit.csv",
        "policy_violation_blockers.csv", "v21_228_copy_policy_crosscheck.csv",
        "V21.229_moomoo_only_data_source_policy_gate_report.txt",
    ]
    assert all((out / name).exists() for name in required)


def test_config_policy_blocks_forbidden_defaults(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "config/data.yaml", "YFINANCE_ENABLED: true\n")
    summary = v229.run(root, tmp_path / "out")
    assert summary["active_yfinance_blocker_count"] >= 1


def test_wrapper_env_policy_detects_toggle(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "run_test.ps1", "$env:ALLOW_YFINANCE='1'\n")
    v229.run(root, tmp_path / "out")
    rows = read_csv(tmp_path / "out" / "wrapper_env_policy_audit.csv")
    assert rows and rows[0]["yfinance_env_toggle_found"] == "True"


def test_canonical_rebuild_required_for_legacy_source(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/CANONICAL/summary.json", '{"provider":"yfinance"}')
    summary = v229.run(root, tmp_path / "out")
    assert summary["canonical_rebuild_required"] is True


def test_dram_and_abcde_rebuild_flags(tmp_path):
    root = tmp_path / "repo"; make_v228(root)
    write(root / "outputs/v21/DRAM/report.txt", "Yahoo")
    write(root / "outputs/v21/ABCDE/report.txt", "external_fallback")
    summary = v229.run(root, tmp_path / "out")
    assert summary["dram_rebuild_required"] is True
    assert summary["abcde_rebuild_required"] is True
