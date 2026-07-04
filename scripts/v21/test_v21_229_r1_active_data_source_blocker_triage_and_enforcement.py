from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_229_r1_active_data_source_blocker_triage_and_enforcement.py")
GUARD_PATH = Path(__file__).with_name("v21_data_source_policy_guard.py")
spec = importlib.util.spec_from_file_location("v21_229_r1", MODULE_PATH)
v229r1 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v229r1)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_v229(root: Path, *, active: bool = True, legacy: bool = True, output_ref: bool = True) -> Path:
    out = root / "outputs/v21/V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE"
    summary = {
        "active_yfinance_blocker_count": 1 if active else 0,
        "active_yahoo_blocker_count": 0,
        "external_fallback_blocker_count": 0,
    }
    write(out / "v21_229_summary.json", json.dumps(summary))
    write(out / "data_source_policy.json", "{}")
    refs = []
    if active:
        refs.append({"path": str(root / "scripts/v21/v21_data_source_policy_guard.py"), "matched_term": "yfinance", "source_inventory": "forbidden_source_usage_inventory", "active_candidate": "True"})
    if legacy:
        refs.append({"path": str(root / "scripts/v20/old_refresh.py"), "matched_term": "yfinance", "source_inventory": "forbidden_source_usage_inventory", "active_candidate": "True"})
    if output_ref:
        out_file = root / "outputs/v21/OLD/summary.json"
        write(out_file, '{"provider":"yfinance"}')
        refs.append({"path": str(out_file), "matched_term": "yfinance", "source_inventory": "forbidden_source_usage_inventory", "active_candidate": "False"})
    write_csv(out / "forbidden_source_usage_inventory.csv", refs, ["path", "matched_term", "source_inventory", "active_candidate"])
    write_csv(out / "external_fallback_inventory.csv", [], ["path", "matched_term", "source_inventory", "active_candidate"])
    for name in [
        "repository_data_source_scan.csv", "yfinance_usage_inventory.csv", "yahoo_string_inventory.csv",
        "active_chain_policy_audit.csv", "script_import_policy_audit.csv", "wrapper_env_policy_audit.csv",
        "config_policy_audit.csv", "canonical_source_policy_audit.csv", "dram_policy_readiness_audit.csv",
        "abcde_policy_readiness_audit.csv", "policy_violation_blockers.csv",
        "diagnostic_only_allowlist_plan.csv", "moomoo_only_enforcement_plan.csv",
    ]:
        write(out / name, "x\n")
    return out


def test_fails_if_required_v21_229_inputs_missing(tmp_path):
    summary = v229r1.run(repo_root=tmp_path / "repo", output_dir=tmp_path / "out", v21_229_output_dir=tmp_path / "missing")
    assert summary["final_status"] == v229r1.FAIL_INPUT_STATUS


def test_classifies_active_yfinance_as_true_active_blocker(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=True, legacy=False, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    rows = read_csv(out / "true_active_blockers.csv")
    assert rows and rows[0]["blocker_type"] in {"TRUE_ACTIVE_CORE_BLOCKER", "TRUE_ACTIVE_SUPPORT_BLOCKER"}


def test_classifies_old_v20_as_legacy_deprecated(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=True, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    rows = read_csv(out / "legacy_deprecated_references.csv")
    assert rows and "scripts/v20" in rows[0]["path"].replace("\\", "/")


def test_classifies_output_metadata_historical(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=True)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    assert read_csv(out / "historical_metadata_references.csv")


def test_guard_file_exists():
    assert GUARD_PATH.exists()


def test_guard_has_no_banned_imports():
    text = GUARD_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_guard_returns_forbidden_defaults():
    spec_guard = importlib.util.spec_from_file_location("guard", GUARD_PATH)
    guard = importlib.util.module_from_spec(spec_guard)
    assert spec_guard.loader is not None
    spec_guard.loader.exec_module(guard)
    flags = guard.policy_flags_for_summary()
    assert flags["yfinance_allowed_by_default"] is False


def test_writes_policy_config(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    v229r1.run(root, tmp_path / "out", v229)
    assert (root / "config/v21/data_source_policy.json").exists()


def test_writes_active_manifest(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    v229r1.run(root, tmp_path / "out", v229)
    assert (root / "config/v21/active_chain_manifest.json").exists()


def test_writes_allowlists(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root)
    v229r1.run(root, tmp_path / "out", v229)
    assert (root / "config/v21/diagnostic_only_data_source_allowlist.json").exists()
    assert (root / "config/v21/legacy_deprecated_source_allowlist.json").exists()


def test_writes_blocker_triage_master(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    assert read_csv(out / "blocker_triage_master.csv")


def test_writes_true_active_blockers(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=True, legacy=False, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    assert read_csv(out / "true_active_blockers.csv")


def test_enforcement_patch_manifest_has_hashes(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229)
    rows = read_csv(out / "enforcement_patch_manifest.csv")
    assert any(r["after_hash"] for r in rows)


def test_writes_guard_coverage_audit(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229, dry_run_patches=True)
    assert read_csv(out / "guard_coverage_audit.csv")


def test_canonical_dram_abcde_blocked_if_active(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    # Add explicit active manifest-ish DRAM reference.
    with (v229 / "forbidden_source_usage_inventory.csv").open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([root / "scripts/v21/v21_data_source_policy_guard.py", "Yahoo", "forbidden_source_usage_inventory", "True"])
    out = tmp_path / "out"
    summary = v229r1.run(root, out, v229, dry_run_patches=True)
    assert summary["true_active_blocker_count_after"] >= 1


def test_does_not_mutate_historical_outputs(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=True)
    historical = root / "outputs/v21/OLD/summary.json"
    before = historical.read_text(encoding="utf-8")
    v229r1.run(root, tmp_path / "out", v229)
    assert historical.read_text(encoding="utf-8") == before


def test_dry_run_patches_do_not_write_config(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    v229r1.run(root, tmp_path / "out", v229, dry_run_patches=True)
    assert not (root / "config/v21/data_source_policy.json").exists()


def test_ready_with_only_legacy_references(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=True, output_ref=True)
    summary = v229r1.run(root, tmp_path / "out", v229)
    assert summary["final_status"] == v229r1.WARN_LEGACY_STATUS
    assert summary["v21_230_ready"] is True


def test_warn_if_true_active_blockers_remain(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=True, legacy=False, output_ref=False)
    summary = v229r1.run(root, tmp_path / "out", v229, dry_run_patches=True)
    assert summary["final_status"] == v229r1.WARN_BLOCKED_STATUS


def test_no_banned_imports_in_r1_script():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_source_mutation_audit_written(tmp_path):
    root = tmp_path / "repo"
    v229 = make_v229(root, active=False, legacy=False, output_ref=False)
    out = tmp_path / "out"
    v229r1.run(root, out, v229)
    assert read_csv(out / "source_mutation_audit.csv")
