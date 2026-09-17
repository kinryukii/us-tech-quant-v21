from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
OUT = Path(r"D:\us-tech-quant-results\A2_R6_DOMAIN_TRANSPORTABILITY_AND_FIXED_SPEC_REPLAY_R1")
SOURCE = REPO / "scripts/v22/a2_r6_domain_transportability_and_fixed_spec_replay_r1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("r6_transport_tested", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixed_contract_and_transportability_evidence():
    c = json.loads((OUT / "classification.json").read_text(encoding="utf-8"))
    s = json.loads((OUT / "r6_specification_and_transportability.json").read_text(encoding="utf-8"))
    assert c["raw_a2_reconciliation"] == "PASS_EXACT_1E-12"
    assert c["r6_specification_status"] == "PASS_CROSS_VERIFIED_FIXED_SPEC"
    assert c["r6_domain_type"] == "HYBRID"
    assert c["r6_fixed_spec_refit_used"] is False
    assert c["missingness"]["legacy_covered_security_dates"] == 9897
    assert c["missingness"]["initial_missing_security_dates"] == 2283
    assert c["missingness"]["transport_covered_security_dates"] == c["missingness"]["required_security_dates"]
    assert c["missingness"]["transport_security_date_coverage"] == 1.0
    assert c["missingness"]["transport_full_date_coverage"] == 1.0
    assert c["2026_outcome_used"] is False
    assert c["candidate_selection_count"] == 0
    assert c["hyperparameter_change_count"] == 0
    assert c["feature_change_count"] == 0
    assert c["threshold_change_count"] == 0
    assert c["exposure_change_count"] == 0
    assert s["model"]["candidate_id"] == "LGBM_BAD_ASYM_2"
    assert s["overlay"]["threshold"] == .90
    assert s["overlay"]["high_risk_multiplier"] == .50
    assert all(pd.Timestamp(f["train_max_target_end"]) < pd.Timestamp(f["embargo_cutoff"]) for f in s["temporal_refit"]["folds"])
    assert all(pd.Timestamp(f["train_max_target_end"]) < pd.Timestamp("2026-01-01") for f in s["temporal_refit"]["folds"])


def test_constant_and_gross_matched_arithmetic_does_not_mutate_contract():
    module = load_module()
    rows = []
    for day in ["2025-01-02", "2025-01-03"]:
        for i in range(20):
            rows.append({"signal_date": pd.Timestamp(day), "ticker": f"T{i:02d}", "risk_percentile": .95 if i < 2 else .50})
    scored = pd.DataFrame(rows)
    targets = module.build_targets(scored)
    for date in sorted(targets["ARM0_RAW"]):
        raw = targets["ARM0_RAW"][date]
        r6 = targets["ARM1_R6"][date]
        const = targets["ARM2_R6_CONSTANT_GROSS"][date]
        gross = targets["ARM3_RAW_GROSS_MATCHED"][date]
        assert abs(sum(raw.values()) - 1.0) <= 1e-12
        assert abs(sum(const.values()) - 1.0) <= 1e-12
        assert abs(sum(gross.values()) - sum(r6.values())) <= 1e-12
        assert all(abs(raw[t] - .05) <= 1e-12 for t in raw)
        ratio = const["T00"] / const["T02"]
        assert abs(ratio - .5) <= 1e-12
    assert module.ANALYSIS_CONTRACT["risk_rule"] == "risk_percentile>=0.90 => multiplier 0.50; otherwise 1.00; removed weight to cash"


def test_paired_bootstrap_is_deterministic_and_non_iid_blocked():
    module = load_module()
    helper = module.import_file("r6_transport_test_helper", module.HELPER_SOURCE)
    values = np.sin(np.arange(100) / 9) / 1000
    left = helper.paired_stats(values, 777)
    right = helper.paired_stats(values, 777)
    assert left == right
    assert helper.BLOCK == 10
    assert helper.BOOTSTRAPS == 2000


def test_output_hashes_and_artifact_bound():
    manifest = json.loads((OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    files = [p for p in OUT.iterdir() if p.is_file()]
    assert len(files) == 7
    assert manifest["artifact_count_including_manifest"] == 7
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    for row in manifest["artifacts"]:
        actual = hashlib.sha256((OUT / row["name"]).read_bytes()).hexdigest()
        assert actual == row["sha256"]
    folds = pd.read_csv(OUT / "fold_and_paired_comparison.csv")
    assert set(folds.loc[folds.row_type.eq("OOS_FOLD"), "fold_or_comparison"].astype(str)) == {"2023", "2024", "2025"}
    assert set(pd.read_csv(OUT / "arm_summary.csv").arm) == {
        "ARM0_RAW", "ARM1_R6", "ARM2_R6_CONSTANT_GROSS", "ARM3_RAW_GROSS_MATCHED"
    }
