"""Append the preserved V2 run to the binding receipt without altering R1."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
V2 = HERE / "repair_v2_all_affected_27"


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    old_binding = HERE / "RUN_REPLAY_BINDING_RECEIPT.json"
    old_latest = HERE / "LATEST_27_RECEIPT.json"
    binding = json.loads(old_binding.read_text(encoding="utf-8"))
    latest = json.loads(old_latest.read_text(encoding="utf-8"))
    complete_path = V2 / "COMPLETE.json"
    source_path = V2 / "SOURCE_HASHES.json"
    diff_path = V2 / "PRICE_FIELD_DIFF.csv"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if complete["fit_guard_attempts"] != 0 or complete["source_hashes_checked_before_and_after"] != 76:
        raise AssertionError("V2 fit/source verification failed")
    if source["frozen_source_hashes"]["engine.py"] != binding["actual_source_sha256"]:
        raise AssertionError("V2 frozen engine differs")
    if len(complete["paths"]) != 27:
        raise AssertionError("V2 should contain all originally affected paths")
    first_cp = json.loads((V2 / complete["paths"][0]["run_id"] / "CHECKPOINT.json").read_text(encoding="utf-8"))
    approval = first_cp["input_approval_ledger"]
    if sha(Path(approval["path"])) != approval["sha256"]:
        raise AssertionError("V2 approval ledger hash differs")
    for item in complete["paths"]:
        run_id = item["run_id"]
        cp = json.loads((V2 / run_id / "CHECKPOINT.json").read_text(encoding="utf-8"))
        if cp["input_approval_ledger"] != approval:
            raise AssertionError(f"V2 path approval mismatch: {run_id}")
        if cp["source_manifest"]["sha256"] != sha(source_path):
            raise AssertionError(f"V2 path source manifest mismatch: {run_id}")
        if cp["new_predictor_fit_attempts"] or cp["new_preprocessor_fit_attempts"]:
            raise AssertionError(f"V2 fit count mismatch: {run_id}")
    binding["versions"]["V2"] = {
        "complete_path": str(complete_path), "complete_sha256": sha(complete_path),
        "source_manifest_sha256": sha(source_path), "input_approval_ledger": approval,
        "price_field_diff_path": str(diff_path), "input_field_diff_sha256": sha(diff_path),
        "actual_binding_captured_at_runtime": False, "fit_guard_attempts": 0,
        "role": "first complete 27-path V2 repair output, preserved; superseded by selected V3/V4/V6 paths",
    }
    binding["versions"] = {key: binding["versions"][key] for key in ("V2", "V3", "V4", "V6")}
    new_binding = HERE / "RUN_REPLAY_BINDING_RECEIPT_R2.json"
    new_latest = HERE / "LATEST_27_RECEIPT_R2.json"
    if new_binding.exists() or new_latest.exists():
        raise RuntimeError("R2 correction exists; preserve prior receipts")
    binding["amendment"] = {"from": str(old_binding), "original_sha256": sha(old_binding),
                            "change": "add preserved V2 source/approval/diff receipts; no account ledger edits"}
    new_binding.write_text(json.dumps(binding, ensure_ascii=False, indent=2), encoding="utf-8")
    latest["runtime_binding_receipt_sha256"] = sha(new_binding)
    latest["runtime_binding_receipt_path"] = str(new_binding)
    latest["amendment"] = {"from": str(old_latest), "original_sha256": sha(old_latest),
                           "change": "bind version history to appended V2 receipt"}
    new_latest.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"new_binding": str(new_binding), "sha256": sha(new_binding),
                      "new_latest": str(new_latest), "sha256_latest": sha(new_latest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
