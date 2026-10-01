"""No-refit audit: maturity, immutable identities and nonzero gate parameter updates."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import numpy as np
import pandas as pd
import torch
from meta_train import ARTIFACTS, STAGES, SEED, FrozenMeta, sha


def main():
    receipt = json.loads((ARTIFACTS/"TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
    pre = json.loads((ARTIFACTS/"META_PRE_FIT.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS" and receipt["predictive_fits_or_solves"] == 12
    assert sha(pre["source_path"]) == pre["source_sha256"]
    assert sha(pre["root_lock_path"]) == pre["root_lock_sha256"]
    audit = {"status": "PASS", "scope": "post_fit_no_additional_fits_no_new_data", "new_fit_calls": 0,
             "predictive_fits_or_solves_completed": 12, "stages": {}}
    for stage, cutoff in STAGES.items():
        selected = pd.read_parquet(ARTIFACTS/f"SELECTED_KEYS_{stage}.parquet")
        assert len(selected) == 40000
        assert selected.target_end_date.lt(pd.Timestamp(cutoff)).all()
        assert selected.signal_date.dt.year.isin([2024,2025]).all()
        assert selected.base_cutoff.eq(selected.signal_date.dt.year.map({2024:pd.Timestamp("2024-01-01"),2025:pd.Timestamp("2025-01-01")})).all()
        frozen = FrozenMeta(stage)  # Validates every identity and artifact hash without fitting.
        torch.manual_seed(SEED)
        initial = torch.nn.Sequential(torch.nn.Linear(4,8),torch.nn.Tanh(),torch.nn.Linear(8,3))
        initial_params = {"w1":initial[0].weight.detach().numpy(),"b1":initial[0].bias.detach().numpy(),
                          "w2":initial[2].weight.detach().numpy(),"b2":initial[2].bias.detach().numpy()}
        delta = {name: float(np.linalg.norm(frozen.gate[name]-value)) for name,value in initial_params.items()}
        assert all(value > 0 for value in delta.values())
        fit_records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((ARTIFACTS/stage).glob("*_FIT_RECEIPT.json"))]
        assert len(fit_records)==6 and sum(row["model_fit_or_solve_count"] for row in fit_records)==6
        gate_receipt = next(row for row in fit_records if row["method"]=="conditional_gate")
        audit["stages"][stage] = {
            "selected_keys":len(selected),"selected_dates":int(selected.signal_date.nunique()),
            "latest_signal_date":str(selected.signal_date.max().date()),
            "latest_mature_label_date":str(selected.target_end_date.max().date()),
            "cutoff_exclusive":cutoff,"stage_identity_and_all_artifact_hashes_valid":True,
            "learned_fixed_coefficients_ridge_hgb_mlp":frozen.coefficients.tolist(),
            "gate_epochs":gate_receipt["details"]["epochs"],
            "gate_initial_to_final_parameter_L2":delta,
            "gate_all_parameter_tensors_changed":True,
            "gate_numpy_torch_max_prediction_error":gate_receipt["details"]["numpy_torch_max_prediction_error"],
            "warnings_by_method":{row["method"]:row["warnings"] for row in fit_records if row["warnings"]},
            "train_diagnostics_not_method_selection":True}
    audit["train_receipt_sha256"]=sha(ARTIFACTS/"TRAIN_RECEIPT.json")
    audit["pre_fit_sha256"]=sha(ARTIFACTS/"META_PRE_FIT.json")
    output=ARTIFACTS/"POST_FIT_AUDIT.json"
    if output.exists():
        raise RuntimeError("COMPLETED_POST_FIT_AUDIT_PRESERVED")
    output.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(audit,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
