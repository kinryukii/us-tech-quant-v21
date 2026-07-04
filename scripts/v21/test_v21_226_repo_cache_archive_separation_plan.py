from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_226_repo_cache_archive_separation_plan.py")
spec = importlib.util.spec_from_file_location("v21_226", MODULE_PATH)
v226 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v226)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    v225 = root / "outputs/v21/V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT"
    v224 = root / "outputs/v21/V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE"
    fields = v226.MASTER_FIELDS
    inv_fields = ["path","relative_path","path_type","size_bytes","mtime_utc","extension","inferred_module","inferred_version","inferred_artifact_type","primary_status","secondary_status","reason","recommended_action","safe_to_delete_now","requires_user_review","should_archive","should_cache","should_keep_in_repo","yfinance_related","moomoo_related","dram_related","abcde_related","v20_related","v21_related","protected_by_v21_224","notes"]
    rows = [
        [root/"scripts/v21/a.py","scripts/v21/a.py","file","10","",".py","a","","python_code","ACTIVE_SUPPORT","","","","False","False","False","False","True","False","False","False","False","False","True","False",""],
        [root/"docs/readme.md","docs/readme.md","file","10","",".md","docs","","report_or_doc","ACTIVE_SUPPORT","","","","False","False","False","False","True","False","False","False","False","False","False","False",""],
        [root/"outputs/v21/MOOMOO_RAW/raw.csv","outputs/v21/MOOMOO_RAW/raw.csv","file","9999999","",".csv","MOOMOO_RAW","","manifest_or_data","ACTIVE_CORE","","","","False","False","False","True","False","False","True","False","False","False","True","False",""],
        [root/"outputs/v21/V21.197_FINAL/x.csv","outputs/v21/V21.197_FINAL/x.csv","file","9999999","",".csv","V21.197_FINAL","V21.197","manifest_or_data","PROTECTED_EVIDENCE","","","","False","False","True","False","False","False","False","False","True","False","True","True",""],
        [root/"outputs/v21/E_R1_DEFENSIVE/x.csv","outputs/v21/E_R1_DEFENSIVE/x.csv","file","50","",".csv","E_R1_DEFENSIVE","","manifest_or_data","PAUSED_REVIEW_REQUIRED","","","","False","True","True","False","False","False","False","False","False","False","True","False",""],
        [root/"__pycache__/x.pyc","__pycache__/x.pyc","file","5",".",".pyc","__pycache__","","file","DELETE_CANDIDATE_REVIEW_ONLY","","","","False","True","False","False","False","False","False","False","False","False","False","False",""],
        [root/"outputs/yfinance_cache.csv","outputs/yfinance_cache.csv","file","5",".",".csv","yfinance_cache","","manifest_or_data","DEPRECATED","","","","False","False","False","False","False","True","False","False","False","False","False","False",""],
        [root/"outputs/v21/MYSTERY/file.bin","outputs/v21/MYSTERY/file.bin","file","5",".",".bin","MYSTERY","","file","QUARANTINE_CANDIDATE","","","","False","True","False","False","False","False","False","False","False","False","True","False",""],
    ]
    write(v225 / "system_file_inventory.csv", ",".join(inv_fields) + "\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n")
    write(v225 / "module_status_registry.csv", "module_name,latest_version,primary_status,latest_final_status,latest_final_decision,reason,recommended_action,user_review_required,active_chain_dependency,storage_bytes,file_count,protected_by_v21_224,continue_value_score,fit_with_dram_only_focus,maintenance_cost,risk_level\nE_R1_DEFENSIVE,,PAUSED_REVIEW_REQUIRED,,,,,True,False,50,1,False,45,REVIEW,LOW,MEDIUM\n")
    for name in ["large_file_inventory.csv","yfinance_artifact_inventory.csv","moomoo_only_readiness_audit.csv","paused_project_review_list.csv","delete_candidates_review_only.csv","v21_224_protected_archive_crosscheck.csv"]:
        write(v225 / name, "x\n")
    write(v225 / "dram_outcome_pattern_crosscheck.csv", "path,matched_pattern,size_bytes,mtime_utc,crosscheck_status,notes\nx,V21.183,0,,PATTERN_MISS_ONLY,ok\n")
    write(v225 / "cleanup_policy.json", "{}\n")
    write(v224 / "archive_pointer_manifest.json", "{}\n")
    write(v224 / "v21_224_summary.json", "{}\n")
    return root, v225, v224


def test_fails_if_required_v21_225_inputs_missing(tmp_path):
    summary = v226.run(repo_root=tmp_path/"repo", output_dir=tmp_path/"out", v21_225_output_dir=tmp_path/"missing")
    assert summary["final_status"] == v226.FAIL_STATUS


def test_reads_inventory_and_generates_master(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"
    v226.run(root, out, v225, v224)
    assert read_csv(out / "separation_plan_master.csv")


def test_maps_scripts_tests_config_docs_to_keep(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    rows = read_csv(out / "separation_plan_master.csv")
    assert all(next(r for r in rows if p in r["relative_path"])["target_action"] == "KEEP_IN_REPO" for p in ["scripts/v21/a.py","docs/readme.md"])


def test_maps_moomoo_data_to_cache(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"separation_plan_master.csv") if "MOOMOO_RAW" in r["relative_path"])
    assert row["target_action"] == "MOVE_TO_CACHE_PLAN"


def test_maps_protected_to_archive_or_no_action(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"separation_plan_master.csv") if "V21.197" in r["relative_path"])
    assert row["target_action"] in {"MOVE_TO_ARCHIVE_PLAN","PROTECTED_NO_ACTION"}


def test_paused_projects_user_review_not_delete(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"separation_plan_master.csv") if "E_R1" in r["relative_path"])
    assert row["target_action"] == "USER_REVIEW_REQUIRED"
    assert row["immediate_delete_allowed"] == "False"


def test_pycache_tmp_debug_delete_after_verification_only(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"separation_plan_master.csv") if "__pycache__" in r["relative_path"])
    assert row["target_action"] == "DELETE_AFTER_VERIFICATION_PLAN"
    assert row["immediate_delete_allowed"] == "False"


def test_yfinance_not_active_chain(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"separation_plan_master.csv") if "yfinance" in r["relative_path"])
    assert row["target_action"] in {"QUARANTINE_PLAN","DELETE_AFTER_VERIFICATION_PLAN","MOVE_TO_ARCHIVE_PLAN"}


def test_creates_pointer_manifest_plan(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    assert read_csv(out/"pointer_manifest_plan.csv")


def test_creates_directory_layout_plan(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    assert json.loads((out/"directory_layout_plan.json").read_text())["cache"]["env_override"] == "US_TECH_QUANT_CACHE_ROOT"


def test_migration_order_correct(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    rows = read_csv(out/"migration_order_plan.csv")
    assert rows[0]["phase_name"] == "V21.226 plan-only"
    assert rows[-1]["phase_name"] == "V21.236 paused project review package"


def test_creates_storage_projection(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    assert read_csv(out/"storage_impact_projection.csv")


def test_dram_outcome_pattern_miss_only_preserved(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    row = next(r for r in read_csv(out/"v21_224_225_dependency_crosscheck.csv") if r["artifact"] == "DRAM_OUTCOME_WARNING")
    assert row["status"] == "PATTERN_MISS_ONLY"


def test_immediate_flags_never_true(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    for row in read_csv(out/"separation_plan_master.csv"):
        assert row["immediate_delete_allowed"] == row["immediate_move_allowed"] == row["immediate_copy_allowed"] == "False"


def test_no_banned_imports():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text


def test_policy_disallows_broker_and_official(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    out = tmp_path / "out"; v226.run(root, out, v225, v224)
    policy = json.loads((out/"repo_lightweight_output_policy.json").read_text())
    assert policy["broker_action_allowed"] is False
    assert policy["official_adoption_allowed"] is False


def test_warning_status_when_user_review_remains(tmp_path):
    root, v225, v224 = make_inputs(tmp_path)
    summary = v226.run(root, tmp_path/"out", v225, v224)
    assert summary["final_status"] == v226.WARN_STATUS
