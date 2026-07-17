from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_045_daily_research_archive_and_pdf_report_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_045", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def pass_v22_040(**overrides) -> dict:
    payload = {
        "final_status": "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE",
        "final_decision": "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY",
        "canonical_latest_date": "2026-07-08",
        "abcde_latest_date": "2026-07-08",
        "dram_latest_price_date": "2026-07-08",
        "same_date_comparable_all_strategies": True,
        "data_gap_days": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
        "child_summary_paths": {
            "V21.232": str(Path("outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN/v21_232_summary.json")),
        },
    }
    payload.update(overrides)
    return payload


def pass_v22_044(repo: Path, **overrides) -> dict:
    payload = {
        "final_status": "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN",
        "final_decision": "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT",
        "child_v22_040_command": r".\scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1 -Execute",
        "v22_040_summary_path": str(repo / module.DEFAULT_V22_040_SUMMARY_REL),
    }
    payload.update(overrides)
    return payload


def pointer_payload(**overrides) -> dict:
    payload = {
        "accepted_current_entrypoint_name": "V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1",
        "accepted_current_entrypoint_wrapper": "scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1",
    }
    payload.update(overrides)
    return payload


def seed_repo(
    tmp_path: Path,
    *,
    pointer: bool = True,
    pointer_name: str = "V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1",
    v22_044: dict | None = None,
    v22_040: dict | None = None,
    abcde_required: bool = True,
    dram_files: bool = True,
    forward_files: bool = True,
    option_files: bool = True,
) -> Path:
    repo = tmp_path / "repo"
    if pointer:
        write_json(repo / module.POINTER_JSON_REL, pointer_payload(accepted_current_entrypoint_name=pointer_name))
        (repo / module.POINTER_MD_REL).parent.mkdir(parents=True, exist_ok=True)
        (repo / module.POINTER_MD_REL).write_text("# Current Daily Research Entrypoint\n", encoding="utf-8")
    if v22_040 is not None:
        write_json(repo / module.DEFAULT_V22_040_SUMMARY_REL, v22_040)
    if v22_044 is not None:
        write_json(repo / module.V22_044_SUMMARY_REL, v22_044)
    abcde = repo / module.ABCDE_DIR_REL
    abcde.mkdir(parents=True, exist_ok=True)
    names = module.ABCDE_HARD_REQUIRED if abcde_required else []
    names += ["abcde_strategy_overlap_matrix.csv", "abcde_canonical_snapshot_audit.csv", "abcde_coverage_audit.csv"]
    for name in names:
        (abcde / name).write_text(f"{name},value\nA,1\n", encoding="utf-8")
    if dram_files:
        dram = repo / "outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
        write_json(dram / "v21_232_summary.json", {"final_status": "PASS_V21_232"})
        (dram / "dram_daily_plan.csv").write_text("symbol,plan\nQQQ,hold\n", encoding="utf-8")
    if forward_files:
        fwd = repo / "outputs/v22/V22.043_DIRECTION_GATE_FORWARD_OUTCOME_TRACKER_R1"
        write_json(fwd / "v22_043_summary.json", {"final_status": "WARN_NOT_MATURE"})
    if option_files:
        opt = repo / "outputs/v22/V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
        (opt).mkdir(parents=True, exist_ok=True)
        (opt / "option_iv_greeks_audit.csv").write_text("symbol,iv\nSPY,0.2\n", encoding="utf-8")
    return repo


def valid_repo(tmp_path: Path, **kwargs) -> Path:
    repo = tmp_path / "repo"
    v040 = pass_v22_040()
    v044 = pass_v22_044(repo)
    kwargs.setdefault("v22_040", v040)
    kwargs.setdefault("v22_044", v044)
    return seed_repo(tmp_path, **kwargs)


def read_summary(repo: Path) -> dict:
    return json.loads((repo / module.OUT_REL / "v22_045_summary.json").read_text(encoding="utf-8"))


def test_pass_with_valid_fake_inputs(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=True)
    assert result["final_status"] == "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_CREATED"
    assert result["final_decision"] == "DAILY_RESEARCH_ARCHIVE_CREATED_RESEARCH_ONLY"
    assert result["archive_accepted"] is True
    assert Path(result["archive_zip_path"]).exists()


def test_fail_when_pointer_json_is_missing(tmp_path):
    repo = valid_repo(tmp_path, pointer=False)
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_045_ENTRYPOINT_POINTER_MISSING"
    assert "entrypoint_pointer_json_exists" in result["failed_gate_names"]


def test_fail_when_pointer_json_does_not_identify_v22_044(tmp_path):
    repo = valid_repo(tmp_path, pointer_name="V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1")
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_045_ENTRYPOINT_POINTER_MISSING"
    assert "entrypoint_pointer_identifies_v22_044" in result["failed_gate_names"]


def test_fail_when_v22_044_summary_is_missing(tmp_path):
    repo = seed_repo(tmp_path, v22_040=pass_v22_040())
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_045_V22_044_SUMMARY_MISSING"


def test_fail_when_v22_044_status_is_not_pass(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(), v22_044=pass_v22_044(repo, final_status="FAIL"))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_V22_044_NOT_ACCEPTED"
    assert "v22_044_final_status" in result["failed_gate_names"]


def test_fail_when_v22_040_summary_is_missing(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_V22_040_SUMMARY_MISSING"


def test_fail_when_v22_040_status_is_not_pass(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(final_status="WARN"), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_V22_040_NOT_PASS"
    assert "v22_040_final_status" in result["failed_gate_names"]


def test_fail_when_dates_are_unequal(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(dram_latest_price_date="2026-07-07"), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_DATE_ALIGNMENT_FAILED"
    assert "dates_equal" in result["failed_gate_names"]


def test_fail_when_same_date_comparable_is_false(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(same_date_comparable_all_strategies=False), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert "same_date_comparable_all_strategies" in result["failed_gate_names"]


def test_fail_when_data_gap_days_is_not_zero(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(data_gap_days=1), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert "data_gap_days_zero" in result["failed_gate_names"]


def test_fail_when_broker_action_allowed_is_true(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(broker_action_allowed=True), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_official_adoption_allowed_is_true(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(tmp_path, v22_040=pass_v22_040(official_adoption_allowed=True), v22_044=pass_v22_044(repo))
    result = module.run(seeded, execute=True)
    assert result["final_status"] == "FAIL_V22_045_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_required_abcde_files_are_missing(tmp_path):
    repo = valid_repo(tmp_path, abcde_required=False)
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_045_REQUIRED_ABCDE_FILES_MISSING"
    assert not Path(result["archive_zip_path"] or repo / "missing.zip").exists()


def test_pass_with_warning_when_optional_forward_files_are_missing(tmp_path):
    repo = valid_repo(tmp_path, forward_files=False)
    result = module.run(repo, execute=True)
    assert result["final_status"].startswith("PASS_")
    assert any("forward outcome files are missing" in warning for warning in result["warnings"])


def test_pass_with_warning_when_optional_option_files_are_missing(tmp_path):
    repo = valid_repo(tmp_path, option_files=False)
    result = module.run(repo, execute=True)
    assert result["final_status"].startswith("PASS_")
    assert any("option quote" in warning for warning in result["warnings"])


def test_pass_with_warning_when_raw_dram_files_are_not_discoverable(tmp_path):
    repo = tmp_path / "repo"
    seeded = seed_repo(
        tmp_path,
        v22_040=pass_v22_040(child_summary_paths={}),
        v22_044=pass_v22_044(repo),
        dram_files=False,
    )
    result = module.run(seeded, execute=True)
    assert result["final_status"].startswith("PASS_")
    assert any("Raw DRAM files are not discoverable" in warning for warning in result["warnings"])


def test_source_files_are_copied_not_mutated(tmp_path):
    repo = valid_repo(tmp_path)
    source = repo / module.ABCDE_DIR_REL / "abcde_strategy_ranking_master.csv"
    before = source.read_bytes()
    result = module.run(repo, execute=True)
    assert source.read_bytes() == before
    copied = [row for row in result["source_inventory"] if row["source_path"] == str(source)]
    assert copied and Path(copied[0]["archived_path"]).read_bytes() == before
    assert result["source_files_mutated"] is False


def test_sha256_hash_values_in_manifest_match_copied_files(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=True)
    manifest = json.loads(Path(result["archive_manifest_json_path"]).read_text(encoding="utf-8"))
    for row in manifest["files"]:
        digest = hashlib.sha256(Path(row["archived_path"]).read_bytes()).hexdigest()
        assert row["sha256"] == digest


def test_markdown_report_is_written(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=True)
    text = Path(result["markdown_report_path"]).read_text(encoding="utf-8")
    assert "Daily Research Archive Audit Report" in text
    assert "Safety Statement" in text


def test_pdf_report_is_written_and_non_empty(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=True)
    pdf = Path(result["pdf_report_path"])
    assert pdf.exists()
    assert pdf.stat().st_size > 100
    assert pdf.read_bytes().startswith(b"%PDF")


def test_zip_archive_contains_report_manifest_and_raw_files(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=True)
    with zipfile.ZipFile(result["archive_zip_path"]) as zf:
        names = set(zf.namelist())
    assert "daily_research_audit_report.md" in names
    assert "daily_research_audit_report.pdf" in names
    assert "archive_manifest.csv" in names
    assert any(name.startswith("raw/abcde/abcde_strategy_ranking_master") for name in names)


def test_v22_045_does_not_execute_wrappers_or_import_market_modules():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_imports = {"subprocess", "moomoo", "futu", "requests", "urllib", "socket", "http"}
    imported: set[str] = set()
    calls: set[str] = set()
    constants: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.append(node.value.lower())
    assert imported.isdisjoint(banned_imports)
    assert "popen" not in calls and "system" not in calls and "spawn" not in calls
    forbidden_wrappers = [
        "run_v21",
        "run_v22_020",
        "run_v22_032",
        "run_v22_043",
        "abcde_rerun.ps1",
        "dram_daily",
        "forward_outcome_data_fetch",
    ]
    assert all(token not in " ".join(constants) for token in forbidden_wrappers)


def test_dry_run_validates_inputs_but_does_not_create_accepted_zip(tmp_path):
    repo = valid_repo(tmp_path)
    result = module.run(repo, execute=False)
    assert result["final_status"] == "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_DRY_RUN_VALIDATED"
    assert result["hard_gate_passed"] is True
    assert result["archive_accepted"] is False
    assert result["copied_file_count"] == 0
    assert not Path(result["archive_zip_path"]).exists()


def test_failed_hard_gate_writes_summary_but_no_accepted_zip(tmp_path):
    repo = valid_repo(tmp_path, abcde_required=False)
    result = module.run(repo, execute=True)
    persisted = read_summary(repo)
    assert persisted["final_status"].startswith("FAIL_")
    assert result["archive_accepted"] is False
    assert not result["archive_zip_path"]
