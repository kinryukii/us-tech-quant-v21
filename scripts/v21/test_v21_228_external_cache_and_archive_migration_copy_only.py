from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_228_external_cache_and_archive_migration_copy_only.py")
spec = importlib.util.spec_from_file_location("v21_228", MODULE_PATH)
v228 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v228)

V227_MASTER_FIELDS = ["source_path","relative_path","planned_action_from_v21_226","dry_run_future_action","source_exists","source_size_bytes","proposed_target_path","target_root_type","target_path_valid","target_under_allowed_root","duplicate_target_path","protected_blocker","user_review_blocker","delete_blocker","yfinance_active_chain_blocker","pointer_required","sha256_required","sha256_status","sha256","dry_run_pass","reason","notes"]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_dict_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_v227(tmp_path: Path, *, same_hash_target: bool = False, different_hash_target: bool = False) -> tuple[Path, Path, Path, Path, Path]:
    root = tmp_path / "repo"
    v227 = root / "outputs/v21/V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN"
    cache = tmp_path / "cache"
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    sources = {
        "cache": root / "outputs/cache_src.csv",
        "archive": root / "outputs/archive_src.csv",
        "quarantine": root / "outputs/quarantine_src.csv",
        "keep": root / "scripts/keep.py",
        "review": root / "outputs/E_R1.csv",
        "delete": root / "tmp/delete.tmp",
        "protected": root / "outputs/protected.json",
    }
    for name, path in sources.items():
        write(path, f"{name}\n")
    targets = {
        "cache": cache / "data/cache_src.csv",
        "archive": archive / "v21/archive_src.csv",
        "quarantine": quarantine / "v21/quarantine_src.csv",
    }
    if same_hash_target:
        write(targets["cache"], sources["cache"].read_text(encoding="utf-8"))
    if different_hash_target:
        write(targets["cache"], "different\n")
    def row(key: str, action: str, target: Path | str = "", root_type: str = "", review: bool = False, protected: bool = False, delete_blocker: bool = False, reason: str = "") -> dict[str, object]:
        source = sources[key]
        return {
            "source_path": str(source),
            "relative_path": str(source.relative_to(root)).replace("\\", "/"),
            "planned_action_from_v21_226": action.replace("COPY_TO_", "MOVE_TO_").replace("_FUTURE", "_PLAN") if action.startswith("COPY_TO_") else action,
            "dry_run_future_action": action,
            "source_exists": True,
            "source_size_bytes": source.stat().st_size,
            "proposed_target_path": str(target),
            "target_root_type": root_type,
            "target_path_valid": True,
            "target_under_allowed_root": True,
            "duplicate_target_path": False,
            "protected_blocker": protected,
            "user_review_blocker": review,
            "delete_blocker": delete_blocker,
            "yfinance_active_chain_blocker": False,
            "pointer_required": bool(target),
            "sha256_required": bool(target) or action == "DELETE_AFTER_VERIFICATION_FUTURE",
            "sha256_status": "",
            "sha256": "",
            "dry_run_pass": True,
            "reason": reason or key,
            "notes": "test",
        }
    rows = [
        row("cache", "COPY_TO_CACHE_FUTURE", targets["cache"], "cache", reason="cache"),
        row("archive", "COPY_TO_ARCHIVE_FUTURE", targets["archive"], "archive", reason="archive"),
        row("quarantine", "COPY_TO_QUARANTINE_FUTURE", targets["quarantine"], "quarantine", review=True, reason="quarantine"),
        row("keep", "KEEP_IN_REPO", reason="keep"),
        row("review", "USER_REVIEW_REQUIRED_BEFORE_ACTION", review=True, reason="review"),
        row("delete", "DELETE_AFTER_VERIFICATION_FUTURE", delete_blocker=False, reason="delete"),
        row("protected", "PROTECTED_NO_ACTION", protected=True, reason="protected"),
    ]
    write_dict_csv(v227 / "dry_run_master_plan.csv", rows, V227_MASTER_FIELDS)
    write(v227 / "dry_run_cache_actions.csv", "source_path,proposed_cache_path,cache_category,source_exists,active_runtime_needed,target_path_valid,sha256_status,dry_run_pass,reason\n")
    write(v227 / "dry_run_archive_actions.csv", "source_path,proposed_archive_path,archive_category,protected_evidence,user_review_required,target_path_valid,sha256_status,dry_run_pass,reason\n")
    write(v227 / "dry_run_quarantine_actions.csv", "source_path,proposed_quarantine_path,reason,target_path_valid,user_review_required,dry_run_pass\n")
    write(v227 / "dry_run_delete_after_verification_actions.csv", f"source_path,size_bytes,reason,source_exists,required_pre_delete_checks,protected_blocker,user_review_blocker,archive_or_cache_copy_required,immediate_delete_allowed,dry_run_delete_allowed_now,dry_run_pass\n{sources['delete']},5,delete,True,checks,False,False,True,False,False,True\n")
    write(v227 / "dry_run_repo_keep_actions.csv", f"source_path,reason,lightweight_policy,source_size_bytes,pointer_required,keep_pass,notes\n{sources['keep']},keep,policy,5,False,True,keep\n")
    write(v227 / "dry_run_user_review_blockers.csv", f"source_path,project_name,reason,recommended_review_action,blocks_delete,blocks_migration,notes\n{sources['review']},E_R1,review,review,True,True,review\n")
    write(v227 / "dry_run_protected_no_action.csv", f"source_path,reason,protected_by,no_action_until,dry_run_pass\n{sources['protected']},protected,V21.224,later,True\n")
    pointer_lines = ["source_path,future_repo_pointer_path,target_external_path,pointer_type,required_fields,pointer_path_valid,target_path_valid,dry_run_pass"]
    for key in ["cache", "archive", "quarantine"]:
        pointer_lines.append(f"{sources[key]},{root / ('outputs/_pointers/' + key + '.json')},{targets[key]},{key}_pointer,a,True,True,True")
    write(v227 / "dry_run_pointer_manifest_actions.csv", "\n".join(pointer_lines) + "\n")
    for name in ["dry_run_path_collision_audit.csv","dry_run_missing_source_audit.csv","dry_run_hash_feasibility_audit.csv","dry_run_external_root_readiness.csv","dry_run_storage_projection.csv","dry_run_execution_order.csv","v21_226_plan_consistency_audit.csv"]:
        write(v227 / name, "x\n")
    write(v227 / "dry_run_policy_gate.json", "{}\n")
    write(v227 / "v21_227_summary.json", json.dumps({"dry_run_fail_count": 0, "missing_source_count": 0}))
    return root, v227, cache, archive, quarantine


def test_fails_if_required_v227_inputs_missing(tmp_path):
    summary = v228.run(repo_root=tmp_path/"repo", output_dir=tmp_path/"out", v21_227_output_dir=tmp_path/"missing")
    assert summary["final_status"] == v228.FAIL_INPUT


def test_copies_cache_archive_quarantine_to_external_roots(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert (cache / "data/cache_src.csv").exists()
    assert (archive / "v21/archive_src.csv").exists()
    assert (quarantine / "v21/quarantine_src.csv").exists()
    assert summary["planned_copy_item_count"] == 3


def test_does_not_copy_skipped_actions(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert not (cache / "keep.py").exists()
    assert not (archive / "E_R1.csv").exists()
    assert (root / "tmp/delete.tmp").exists()


def test_creates_external_roots_only_when_needed(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    assert not cache.exists() and not archive.exists() and not quarantine.exists()
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert cache.exists() and archive.exists() and quarantine.exists()
    assert summary["external_root_created_count"] == 3


def test_sources_not_deleted_moved_renamed_or_mutated(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    source = root / "outputs/cache_src.csv"
    before = source.read_text(encoding="utf-8")
    before_paths = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    after_paths = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "V21.228" not in str(p))
    assert source.exists()
    assert source.read_text(encoding="utf-8") == before
    assert before_paths == after_paths


def test_verifies_sha256_and_sizes(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    rows = read_csv(out / "copy_hash_verification.csv")
    assert rows
    assert all(r["hash_match"] == "True" and r["size_match"] == "True" and r["verified"] == "True" for r in rows)


def test_existing_same_hash_already_present_verified(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path, same_hash_target=True)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert summary["already_present_verified_count"] >= 1


def test_existing_different_hash_fails(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path, different_hash_target=True)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert summary["final_status"] == v228.FAIL_COLLISION


def test_writes_required_copy_manifests(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    for name in ["copy_execution_master.csv","cache_copy_manifest.csv","archive_copy_manifest.csv","quarantine_copy_manifest.csv"]:
        assert (out / name).exists()


def test_writes_skipped_manifests(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    assert read_csv(out / "skipped_user_review_manifest.csv")
    assert read_csv(out / "skipped_delete_after_verification_manifest.csv")


def test_writes_pointer_index_and_json(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    assert read_csv(out / "repo_pointer_manifest_index.csv")
    assert json.loads((out / "generated_pointer_manifests.json").read_text(encoding="utf-8"))


def test_source_integrity_no_mutation(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    assert all(r["mutation_detected"] == "False" for r in read_csv(out / "source_integrity_audit.csv"))


def test_policy_gate_disables_delete_move_source_mutation(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    out = tmp_path/"out"
    v228.run(root, out, v227dir, cache, archive, quarantine)
    policy = json.loads((out / "copy_only_policy_gate.json").read_text(encoding="utf-8"))
    assert policy["delete_allowed_now"] is False
    assert policy["move_allowed_now"] is False
    assert policy["source_mutation_allowed"] is False


def test_warning_when_user_review_remains_and_copy_passes(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert summary["final_status"] == v228.WARN_STATUS


def test_fail_status_on_hash_or_size_mismatch(monkeypatch, tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)

    def fake_copy_status(source, target, force):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("bad", encoding="utf-8")
        return True, False, False, "a", "b", "COPY_VERIFICATION_FAILED"

    monkeypatch.setattr(v228, "copy_status", fake_copy_status)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine)
    assert summary["final_status"] == v228.FAIL_VERIFY


def test_max_copy_items_limits_copy_scope(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path)
    summary = v228.run(root, tmp_path/"out", v227dir, cache, archive, quarantine, max_copy_items=1)
    assert summary["copied_file_count"] == 1
    assert summary["skipped_file_count"] >= 1


def test_main_returns_nonzero_on_different_hash_collision(tmp_path):
    root, v227dir, cache, archive, quarantine = make_v227(tmp_path, different_hash_target=True)
    code = v228.main([
        "--repo-root", str(root),
        "--output-dir", str(tmp_path / "out"),
        "--v21-227-output-dir", str(v227dir),
        "--cache-root", str(cache),
        "--archive-root", str(archive),
        "--quarantine-root", str(quarantine),
    ])
    assert code != 0


def test_no_banned_imports():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text
