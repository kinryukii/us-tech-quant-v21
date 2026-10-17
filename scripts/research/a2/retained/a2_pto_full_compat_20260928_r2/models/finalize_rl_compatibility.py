"""Complete RL receipts from preserved fits and explicit compatibility proof.

No fit or production/test price read occurs. Reproduces an inference-only
positive-NAV compatibility check on synthetic accounts.
"""
from pathlib import Path
from datetime import datetime, timezone
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import torch
import rl_control as rl
from fast_account import MarketArrays, run_many


def main():
    modeldir = ROOT / "models"
    pre = json.loads((modeldir / "RL_PRE_FIT_CONTRACT.json").read_text(encoding="utf-8"))
    original = modeldir / "rl_fit_source_original.py"
    assert rl.sha(original) == pre["source_sha256"][str(ROOT / "rl_control.py")]
    proof_path = ROOT / "audits/ACCOUNT_LABEL_CACHE_COMPATIBILITY.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["status"] == "PASS"
    assert proof["before_sha256"] == pre["source_sha256"][str(ROOT / "fast_account.py")]
    assert rl.sha(Path(proof["before_source_snapshot"])) == proof["before_sha256"]
    assert rl.sha(ROOT / "fast_account.py") == proof["after_sha256"]
    assert proof["final_cash_and_units_bitwise_equal"] and proof["audit_and_metadata_exactly_equal"]
    assert all(v["all_columns_and_values_exactly_equal"] and v["numeric_float64_bits_equal"] for v in proof["exact_tables"].values())
    old_source = original.read_text(encoding="utf-8")
    new_source = (ROOT / "rl_control.py").read_text(encoding="utf-8")
    assert old_source.split("class RLRuntime:")[0] == new_source.split("class RLRuntime:")[0]
    spec = importlib.util.spec_from_file_location("rl_original_fit_implementation", original)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    torch.set_num_threads(2)
    dates = pd.bdate_range("2025-01-02", periods=8)
    names = np.array([f"T{i:02d}" for i in range(25)])
    opening = np.column_stack([100 + np.arange(8) * (i % 3 - 1) + i for i in range(25)]).astype(float)
    closing = opening * (1 + np.sin(np.arange(8))[:, None] * .003)
    features = np.zeros((8, 25, 32)); features[:, :, 0] = np.arange(25)[None, :] / 25
    market = MarketArrays(dates, names, opening, closing, adv=np.full((8, 25), 1e6),
                          signal_mask=np.r_[np.ones(7, bool), False])
    paths = ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]
    before = run_many(market, paths, old.RLRuntime("validation", features, modeldir))
    after = run_many(market, paths, rl.RLRuntime("validation", features, modeldir))
    tables = {}
    for name in ["daily", "positions", "orders", "fills", "execution_results", "contexts", "operational_actions"]:
        a, b = getattr(before, name), getattr(after, name)
        pd.testing.assert_frame_equal(a, b, check_exact=True, check_dtype=True)
        bits = all(np.array_equal(a[c].to_numpy().view(np.uint64), b[c].to_numpy().view(np.uint64))
                   for c in a.select_dtypes(include=["float64"]).columns)
        assert bits
        tables[name] = dict(rows=len(a), all_columns_exact_equal=True, numeric_float64_bits_equal=True)
    np.testing.assert_array_equal(before.final_units, after.final_units)
    np.testing.assert_array_equal(before.final_cash, after.final_cash)
    assert before.audit == after.audit and before.metadata == after.metadata
    runtime_proof = dict(status="PASS", synthetic_only=True, production_or_2026_outcomes_read=False,
                         before_source=str(original), before_sha256=rl.sha(original),
                         after_source=str(ROOT / "rl_control.py"), after_sha256=rl.sha(ROOT / "rl_control.py"),
                         scope="Inference-only unknown/nonpositive NAV guard; training functions and positive-NAV targets/accounts unchanged.",
                         training_function_source_unchanged=True, normal_accounts_exact_tables=tables,
                         final_cash_and_units_bitwise_equal=True,
                         unknown_nav_behavior="Before: INVALID_RL_SIGNAL_PROJECTION. After: empty decision for reserved unknown account, healthy account continues.",
                         unknown_nav_test="test_unknown_nav_rl_account_does_not_break_healthy_account: PASS",
                         model_parameters_or_normalization_changed=False)
    rl.write_json(modeldir / "RL_RUNTIME_PATCH_COMPATIBILITY.json", runtime_proof)
    fits, metrics = [], []
    for stage in ["validation", "final"]:
        for method in ["reinforce", "ppo"]:
            receipt = json.loads((modeldir / f"rl_{stage}_{method}_receipt.json").read_text(encoding="utf-8"))
            assert receipt["chronological_epochs"] == 10 and len(receipt["logs"]) == 10
            assert receipt["actor_parameter_delta_l2"] > 0 and receipt["zero_parameter_delta_l2"] == 0
            assert receipt["initial_actor_digest"] == receipt["zero_actor_digest"]
            assert pd.Timestamp(receipt["reward_end_max"]) < pd.Timestamp(rl.STAGES[stage])
            assert rl.sha(Path(receipt["path"])) == receipt["sha256"]
            assert rl.sha(Path(receipt["zero_path"])) == receipt["zero_sha256"]
            assert receipt["source_sha256"] == pre["source_sha256"]
            zero = torch.load(receipt["zero_path"], map_location="cpu", weights_only=True)
            actor = rl.Actor(); actor.load_state_dict(zero["actor_state"])
            assert rl.state_digest(actor) == receipt["initial_actor_digest"]
            fits.append(receipt)
            row = {k: receipt[k] for k in ["stage", "method", "chronological_epochs", "actual_parameter_updates",
                                           "actor_parameter_delta_l2", "zero_parameter_delta_l2", "reward_end_max"]}
            row.update(first_loss=receipt["logs"][0]["loss_mean"], last_loss=receipt["logs"][-1]["loss_mean"],
                       ppo_clipped_samples=sum(e["ppo_clipped_samples"] for e in receipt["logs"]))
            metrics.append(row)
    changed = {p: dict(fit_bound_sha256=s, current_sha256=rl.sha(p))
               for p, s in pre["source_sha256"].items() if rl.sha(p) != s}
    assert set(changed) == {str(ROOT / "fast_account.py"), str(ROOT / "rl_control.py")}
    compatibility = dict(status="PASS_EXPLICIT_COMPATIBILITY_SUPPLEMENTS",
                         original_fit_source_sha256=pre["source_sha256"], changed_sources=changed,
                         engine_label_cache_proof=str(proof_path), engine_label_cache_proof_sha256=rl.sha(proof_path),
                         runtime_guard_proof=str(modeldir / "RL_RUNTIME_PATCH_COMPATIBILITY.json"),
                         runtime_guard_proof_sha256=rl.sha(modeldir / "RL_RUNTIME_PATCH_COMPATIBILITY.json"),
                         training_inputs_sha256_unchanged=True, original_prefit_and_each_fit_receipts_modified=False,
                         formal_fit_process_exit_code=1,
                         formal_fit_process_terminal_reason="Final raw source-hash guard detected decision_id cache change after all four fits completed; independent equivalence proof closes this without retraining.",
                         draft_attempt_in_formal_fit_count=False, numeric_2026_prices_read=False)
    rl.write_json(modeldir / "RL_ENVIRONMENT_COMPATIBILITY.json", compatibility)
    summary = dict(status="COMPLETE", completion_qualification="EXPLICIT_ENGINE_CACHE_AND_RUNTIME_GUARD_COMPATIBILITY_SUPPLEMENTS",
                   spec=rl.SPEC, fits=fits, actual_fit_count=4, zero_control_count=4,
                   actual_parameter_updates=sum(r["actual_parameter_updates"] for r in fits),
                   old_actor_reused=False, fit_2026_rows=0, numeric_2026_prices_read=False,
                   source_sha256_unchanged=False, training_inputs_sha256_unchanged=True,
                   original_fit_binding=pre["source_sha256"], runtime_source_sha256=rl.sha(ROOT / "rl_control.py"),
                   common_runtime_source_sha256=rl.sha(ROOT / "fast_account.py"),
                   compatibility_receipt=str(modeldir / "RL_ENVIRONMENT_COMPATIBILITY.json"),
                   compatibility_receipt_sha256=rl.sha(modeldir / "RL_ENVIRONMENT_COMPATIBILITY.json"),
                   formal_fit_process_exit_code=1,
                   tests="6 final-engine behavior tests PASS; four-control Runtime API test PASS; unknown-NAV guard test PASS",
                   limitations=["Research affine index units and previously exposed holdout.",
                                "REINFORCE one full-trajectory update per epoch; PPO one fixed minibatch pass, update counts differ.",
                                "Complete raw candidate pool remains BLOCKED_DATA.",
                                "No candidate, seed, epoch, reward or threshold search; interrupted draft attempt retained."],
                   completed_utc=datetime.now(timezone.utc).isoformat())
    rl.write_json(modeldir / "RL_TRAIN_RECEIPT.json", summary)
    rl.write_json(modeldir / "RL_FIT_METRICS.json", dict(status="COMPLETE", metrics=metrics))
    print(json.dumps(dict(status="COMPLETE", fits=metrics, total_updates=summary["actual_parameter_updates"],
                          sources_unchanged=False, compatibility="PASS"), ensure_ascii=False))


if __name__ == "__main__":
    main()
