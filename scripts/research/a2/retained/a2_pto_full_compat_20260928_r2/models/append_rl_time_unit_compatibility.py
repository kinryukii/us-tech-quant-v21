"""Append a verified runtime-only bridge, preserving every original fit receipt.

Reads receipts and hashes only. Does not fit, infer, or read any market result.
"""
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    proof_path = ROOT / "audits/ACCOUNT_TIME_UNIT_COMPATIBILITY.json"
    proof = read(proof_path)
    assert proof["status"] == "PASS" and proof["synthetic_only"]
    assert not proof["production_or_2026_outcomes_read"]
    assert proof["single_byte_replacement_confirmed"]
    assert not proof["fixed_methods_parameters_seeds_changed"]
    assert sha(proof["before_source_snapshot"]) == proof["before_sha256"]
    assert sha(ROOT / "fast_account.py") == proof["after_sha256"]
    for block in proof["compatibility_proof"].values():
        assert block["final_cash_and_units_bits_equal"] and block["audit_and_metadata_exact_equal"]
        assert block["last_two_signal_sessions_disabled"] and len(block["tables"]) == 7
        for table in block["tables"].values():
            assert table["all_values_exact_equal"] and table["float64_bits_equal"]
            assert table["datetime_unit_normalization_only"]
    env_path = MODELS / "RL_ENVIRONMENT_COMPATIBILITY.json"
    total_path = MODELS / "RL_TRAIN_RECEIPT.json"
    environment, total = read(env_path), read(total_path)
    original_prefit = read(MODELS / "RL_PRE_FIT_CONTRACT.json")
    unchanged = {str(MODELS / "RL_PRE_FIT_CONTRACT.json"): sha(MODELS / "RL_PRE_FIT_CONTRACT.json")}
    for fit in total["fits"]:
        stage_path = MODELS / f"rl_{fit['stage']}_{fit['method']}_receipt.json"
        assert read(stage_path) == fit
        assert fit["source_sha256"] == original_prefit["source_sha256"]
        assert sha(fit["path"]) == fit["sha256"] and sha(fit["zero_path"]) == fit["zero_sha256"]
        unchanged[str(stage_path)] = sha(stage_path)
        unchanged[fit["path"]] = fit["sha256"]
        unchanged[fit["zero_path"]] = fit["zero_sha256"]
    for path in MODELS.glob("rl_*_normalization.npz"):
        unchanged[str(path)] = sha(path)
    engine_source = str(ROOT / "fast_account.py")
    if "terminal_time_unit_proof" in environment:
        assert environment["terminal_time_unit_proof_sha256"] == sha(proof_path)
        assert environment["current_runtime_engine_sha256"] == proof["after_sha256"]
        print("ALREADY_APPENDED_VERIFIED_RUNTIME_BRIDGE", flush=True)
        return
    assert environment["changed_sources"][engine_source]["current_sha256"] == proof["before_sha256"]
    assert total["common_runtime_source_sha256"] == proof["before_sha256"]
    preserved = MODELS / "receipts_before_terminal_time_unit"
    preserved.mkdir(exist_ok=True)
    for path in [env_path, total_path]:
        target = preserved / path.name
        if target.exists():
            assert sha(target) == sha(path)
        else:
            shutil.copyfile(path, target)
    supplement_path = MODELS / "RL_TERMINAL_TIME_UNIT_COMPATIBILITY.json"
    supplement = dict(status="PASS_RUNTIME_ONLY_COMPATIBILITY_BRIDGE",
                      checked_at_utc=datetime.now(timezone.utc).isoformat(),
                      before_runtime_engine_sha256=proof["before_sha256"],
                      current_runtime_engine_sha256=proof["after_sha256"],
                      original_fit_binding=original_prefit["source_sha256"],
                      proof_path=str(proof_path), proof_sha256=sha(proof_path),
                      ordinary_account_values_exact_after_datetime_unit_normalization=True,
                      ordinary_numeric_float64_cash_and_units_bits_equal=True,
                      terminal_branch=proof["terminal_branch"],
                      fit_and_formal_market_last_two_signal_sessions_disabled=True,
                      original_prefit_stage_receipts_actors_and_normalizers_sha256=unchanged,
                      retained_previous_environment_receipt=str(preserved / env_path.name),
                      retained_previous_environment_receipt_sha256=sha(preserved / env_path.name),
                      retained_previous_total_receipt=str(preserved / total_path.name),
                      retained_previous_total_receipt_sha256=sha(preserved / total_path.name),
                      retraining=False, production_or_2026_outcomes_read=False)
    save(supplement_path, supplement)
    environment["terminal_time_unit_proof"] = str(proof_path)
    environment["terminal_time_unit_proof_sha256"] = sha(proof_path)
    environment["terminal_time_unit_rl_supplement"] = str(supplement_path)
    environment["terminal_time_unit_rl_supplement_sha256"] = sha(supplement_path)
    environment["current_runtime_engine_sha256"] = proof["after_sha256"]
    environment["changed_sources"][engine_source]["previous_verified_runtime_sha256"] = proof["before_sha256"]
    environment["changed_sources"][engine_source]["current_sha256"] = proof["after_sha256"]
    save(env_path, environment)
    total["common_runtime_source_sha256"] = proof["after_sha256"]
    total["current_runtime_engine_sha256"] = proof["after_sha256"]
    total["terminal_time_unit_compatibility_receipt"] = str(supplement_path)
    total["terminal_time_unit_compatibility_receipt_sha256"] = sha(supplement_path)
    total["compatibility_receipt_sha256"] = sha(env_path)
    total["completion_qualification"] += "_AND_TERMINAL_TIME_UNIT_RUNTIME_BRIDGE"
    save(total_path, total)
    assert read(total_path)["fits"] == total["fits"]
    assert all(sha(path) == expected for path, expected in unchanged.items())
    print("PASS_APPENDED_RUNTIME_BRIDGE_ORIGINAL_FITS_UNCHANGED", flush=True)


if __name__ == "__main__":
    main()
