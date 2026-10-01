"""Seal the latest version-selected 27 repaired R6 account prefixes."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VERSION_DIRS = {
    "V3": HERE / "repair_v3_four_first_blocks_12",
    "V4": HERE / "repair_v4_wdc_crbg_9",
    "V6": HERE / "repair_v6_slmt_pfe_crs_gpc_15",
}
LATEST = {
    "hgb_return_baseline": "V3",
    "joint_rl_zero_control": "V4", "joint_ridge": "V4", "joint_elastic_net": "V4",
    "joint_q90": "V6", "joint_q50": "V6", "joint_mlp": "V6",
    "joint_rl_ensemble": "V6", "joint_logistic": "V6",
}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from engine import run_replay

    actual = Path(run_replay.__code__.co_filename).resolve()
    actual_inspect = Path(inspect.getsourcefile(run_replay)).resolve()
    expected = (ROOT / "engine.py").resolve()
    if actual != expected or actual_inspect != expected:
        raise AssertionError("actual run_replay source binding does not point to frozen engine")
    source_sha = sha(expected)
    binding = {"actual_co_filename": str(actual), "actual_inspect_sourcefile": str(actual_inspect),
               "actual_source_sha256": source_sha,
               "adapter_current_path": str(HERE / "replay_account.py"),
               "adapter_current_sha256": sha(HERE / "replay_account.py"),
               "runtime_capture_scope": "V6 explicitly asserts and records bound co_filename; V2/V3/V4 imported from ROOT and checked frozen engine source hash, but did not persist a bound co_filename assertion or historical adapter SHA",
               "versions": {}}
    selected, changed, next_demands, consumed = [], [], [], []
    for version, folder in VERSION_DIRS.items():
        complete_path = folder / "COMPLETE.json"
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        if complete["fit_guard_attempts"] != 0 or complete["source_hashes_checked_before_and_after"] != 76:
            raise AssertionError(f"fit/source verification failed: {version}")
        source_path = folder / "SOURCE_HASHES.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if source["frozen_source_hashes"].get("engine.py") != source_sha:
            raise AssertionError(f"engine seal mismatch: {version}")
        if version == "V6":
            captured = source.get("actual_run_replay_source")
            if not captured or Path(captured["path"]).resolve() != expected or captured["sha256"] != source_sha:
                raise AssertionError("V6 did not capture actual engine binding")
        first_item = complete["paths"][0]
        first_checkpoint = json.loads((folder / first_item["run_id"] / "CHECKPOINT.json").read_text(encoding="utf-8"))
        binding["versions"][version] = {"complete_path": str(complete_path), "complete_sha256": sha(complete_path),
            "source_manifest_sha256": sha(source_path),
            "input_approval_ledger": first_checkpoint["input_approval_ledger"],
            "price_field_diff_path": str((folder / "PRICE_FIELD_DIFF.csv").resolve()),
            "input_field_diff_sha256": sha(folder / "PRICE_FIELD_DIFF.csv"),
            "actual_binding_captured_at_runtime": version == "V6",
            "fit_guard_attempts": 0}
        progress = pd.read_csv(folder / "PATH_PROGRESS.csv")
        first_trades = pd.read_csv(folder / "FIRST_BLOCK_ACTUAL_FILL.csv")
        requirements = pd.read_csv(folder / "NEXT_REQUIRED_INPUTS.csv")
        for item in complete["paths"]:
            run_id = item["run_id"]
            policy = run_id.rsplit("_", 1)[0]
            if LATEST.get(policy) != version:
                continue
            checkpoint_path = folder / run_id / "CHECKPOINT.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint["new_predictor_fit_attempts"] != 0 or checkpoint["new_preprocessor_fit_attempts"] != 0:
                raise AssertionError(f"nonzero fit count: {run_id}")
            d = pd.read_parquet(folder / run_id / "daily.parquet")
            if not d.valuation_status.eq("certified").all() or d.cash.min() < -1e-8 or d.actual_name_count.max() > 20:
                raise AssertionError(f"account certification/limits fail: {run_id}")
            for column in ("cash_flow_identity_error", "cost_identity_error", "nav_identity_error"):
                vals = d[column].to_numpy(float)
                if not np.isfinite(vals).all() or np.abs(vals).max() > 1e-7:
                    raise AssertionError(f"account identity fails: {run_id}: {column}")
            record = progress.loc[progress.run_id.eq(run_id)].iloc[0].to_dict()
            record.update(input_version=version, output_dir=str(folder / run_id),
                          checkpoint_sha256=sha(checkpoint_path),
                          daily_ledger_sha256=sha(folder / run_id / "daily.parquet"))
            selected.append(record)
            trade_rows = first_trades.loc[first_trades.run_id.eq(run_id)].copy()
            trade_rows["input_version"] = version
            changed.extend(trade_rows.to_dict("records"))
            next_rows = requirements.loc[requirements.run_id.eq(run_id)].copy()
            next_rows["input_version"] = version
            next_demands.extend(next_rows.to_dict("records"))
            consumed_path = folder / run_id / "CONSUMED_APPROVALS.csv"
            if consumed_path.exists():
                fields = pd.read_csv(consumed_path)
                fields["run_id"] = run_id
                fields["input_version"] = version
                consumed.extend(fields.to_dict("records"))
    if len(selected) != 27 or len({r["run_id"] for r in selected}) != 27:
        raise AssertionError("latest set must contain each of the 27 originally affected paths once")
    consumed_frame = pd.DataFrame(consumed)
    if not consumed_frame.empty:
        for key, group in consumed_frame.groupby(["ticker", "trade_date", "field"]):
            if group.value.nunique() != 1 or group.evidence_id.nunique() != 1:
                raise AssertionError(f"consumed field conflict: {key}")
        unique = consumed_frame.drop_duplicates(["ticker", "trade_date", "field"]).sort_values(
            ["ticker", "trade_date", "field"], kind="stable")
    else:
        unique = consumed_frame
    pd.DataFrame(selected).sort_values("run_id").to_csv(HERE / "LATEST_27_PATHS.csv", index=False)
    pd.DataFrame(changed).sort_values("run_id").to_csv(HERE / "LATEST_27_FIRST_BLOCK_TRADES.csv", index=False)
    pd.DataFrame(next_demands).sort_values(["run_id", "date", "ticker", "field"]).to_csv(
        HERE / "LATEST_27_NEXT_INPUTS.csv", index=False)
    unique.to_csv(HERE / "LATEST_27_UNIQUE_CONSUMED_FIELDS.csv", index=False)
    (HERE / "RUN_REPLAY_BINDING_RECEIPT.json").write_text(json.dumps(binding, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt = {"status": "VERSION_SELECTED_CERTIFIED_ACCOUNT_PREFIXES",
               "selected_paths": len(selected), "through_terminal": sum(r["status"] == "certified_to_terminal" for r in selected),
               "paused_before_next_unverified_input": sum(r["status"] != "certified_to_terminal" for r in selected),
               "unique_approved_price_fields_actually_consumed": len(unique),
               "path_field_consumptions_with_cost_repeats": len(consumed_frame),
               "first_old_missing_open_same_side_fills": sum(r["new_same_security_side_actual_trade"] for r in changed),
               "first_old_missing_open_opposite_side_fills": sum(
                   r["new_same_security_any_side_actual_trade"] and not r["new_same_security_side_actual_trade"]
                   for r in changed),
               "source_engine_sha256": source_sha,
               "current_adapter_sha256": binding["adapter_current_sha256"],
               "runtime_binding_receipt_sha256": sha(HERE / "RUN_REPLAY_BINDING_RECEIPT.json"),
               "new_predictor_fit_attempts": 0, "new_preprocessor_fit_attempts": 0,
               "candidate_pool": "R6_UNCHANGED_61963_VERIFIED_47701_UNKNOWN",
               "formal_full_pool_result": False}
    (HERE / "LATEST_27_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
