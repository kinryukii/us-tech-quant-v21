from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_002_v21_active_deprecated_output_manifest.py")
SPEC = importlib.util.spec_from_file_location("v22_002", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v21_output_classification_manifest.csv",
    "v21_active_output_manifest.csv",
    "v21_deprecated_output_manifest.csv",
    "v21_output_manifest_summary.json",
    "v21_output_manifest_risk_gate.json",
    "V22.002_v21_active_deprecated_output_manifest_report.txt",
]

EXPECTED_COLUMNS = [
    "output_name",
    "output_path",
    "exists",
    "classification",
    "v22_role",
    "active_allowed",
    "read_allowed",
    "write_allowed",
    "delete_allowed",
    "mutation_allowed",
    "reason",
    "detected_by",
    "last_modified_utc",
    "file_count_shallow",
    "total_size_bytes_shallow",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_v21_outputs(repo: Path) -> None:
    output_root = repo / "outputs" / "v21"
    for name in [
        "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1",
        "V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1",
        "V21.201_DRAM_MOOMOO_R4_PLAN",
        "V21.999_EXPERIMENTAL_UNKNOWN_OUTPUT",
        "V21.998_TEST_DIAGNOSTIC_OUTPUT",
    ]:
        (output_root / name).mkdir(parents=True, exist_ok=True)


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_v21_outputs(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    out = repo / module.OUT_REL
    for filename in REQUIRED_FILES:
        assert (out / filename).exists()


def test_final_decision_and_no_action_gates(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v21_output_manifest_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "V21_OUTPUTS_CLASSIFIED_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "market_data_fetch_allowed",
        "option_chain_fetch_allowed",
        "daily_chain_execution_allowed",
    ]:
        assert summary[key] is False
    for key in [
        "historical_outputs_mutation_allowed",
        "cache_mutation_allowed",
        "delete_allowed",
        "move_allowed",
        "rename_allowed",
        "clean_allowed",
    ]:
        assert summary[key] is False
    assert summary["protected_outputs_modified"] is False


def test_classification_manifest_columns(tmp_path):
    repo, _ = run_stage(tmp_path)
    manifest = repo / module.OUT_REL / "v21_output_classification_manifest.csv"
    with manifest.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == EXPECTED_COLUMNS


def test_active_manifest_contains_only_active_rows(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v21_active_output_manifest.csv")
    assert rows
    for row in rows:
        assert row["active_allowed"] == "True"
        assert row["classification"].startswith("ACTIVE_")


def test_deprecated_manifest_contains_only_review_missing_or_deprecated_rows(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v21_deprecated_output_manifest.csv")
    assert rows
    allowed = {"DEPRECATED_DO_NOT_USE", "UNKNOWN_REVIEW_REQUIRED", "MISSING_REFERENCE"}
    for row in rows:
        assert row["classification"] in allowed


def test_known_references_represented_in_full_manifest(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v21_output_classification_manifest.csv")
    by_name = {row["output_name"]: row for row in rows}
    for known_name in module.KNOWN_REFERENCES:
        assert known_name in by_name
        assert by_name[known_name]["exists"] == "True" or by_name[known_name]["classification"] == "MISSING_REFERENCE"


def test_module_has_no_broker_network_process_or_mutation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {
        "moomoo",
        "futu",
        "yfinance",
        "requests",
        "urllib",
        "http",
        "socket",
        "subprocess",
        "shutil",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_002_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST"
    for path in repo.rglob("*"):
        if path.is_file():
            assert expected in path.resolve().parents


def test_no_delete_move_rename_clean_functions_are_used():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_attrs = {"unlink", "rmdir", "remove", "removedirs", "replace", "rename", "renames"}
    banned_names = {"delete", "move", "rename", "clean"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_attrs
        elif isinstance(node, ast.Name):
            assert node.id not in banned_names


def test_warn_status_when_output_root_missing(tmp_path):
    repo = tmp_path / "repo"
    payload = module.run(repo)
    assert payload["final_status"] == "WARN_V22_002_V21_OUTPUT_MANIFEST_READY_WITH_MISSING_OUTPUT_ROOT"
    assert payload["final_decision"] == "V21_OUTPUTS_CLASSIFIED_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"
