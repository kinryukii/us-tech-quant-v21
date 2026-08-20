from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r30d_conditional_downside_orthogonality_audit.py"
SPEC = importlib.util.spec_from_file_location("r30d", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def sample(n: int = 100) -> pd.DataFrame:
    index = np.arange(n)
    return pd.DataFrame(
        {
            "candidate_id": [f"c{i:03}" for i in index],
            "decision_timestamp_utc": pd.date_range("2021-01-01", periods=n, freq="h", tz="UTC"),
            "fold": np.where(index < n // 2, "OOF_2021", "OOF_2022"),
            "head": np.where(index % 2, "UP", "DOWN"),
            "action_instrument": np.where(index % 2, "SOXL", "SOXS"),
            "raw_net20": np.linspace(0.10, -0.10, n),
            "actual_loss": np.maximum(np.linspace(-0.10, 0.10, n), 0),
            "pred_t1": np.linspace(0, 1, n),
            "pred_t4": np.linspace(0, 1, n),
        }
    )


def test_oof_identity_reconciliation_one_to_one_and_mismatch_count():
    frame = sample()
    joined, identity = R.reconcile_oof(frame.drop(columns="pred_t4"), frame.drop(columns="pred_t1"))
    assert len(joined) == 100
    assert identity == {"OOF_ROW_COUNT": 100, "OOF_UNMATCHED_COUNT": 0, "OOF_DUPLICATE_COUNT": 0}
    _, mismatch = R.reconcile_oof(frame.drop(columns="pred_t4").iloc[:-1], frame.drop(columns="pred_t1"))
    assert mismatch["OOF_UNMATCHED_COUNT"] == 1


def test_t1_deciles_are_fixed_and_deterministic_under_ties():
    frame = sample(103)
    frame["pred_t1"] = 0.5
    first = R.assign_rank_buckets(frame, "pred_t1", 10, "t1_decile")
    second = R.assign_rank_buckets(frame.sample(frac=1, random_state=4), "pred_t1", 10, "t1_decile")
    assert first.set_index("candidate_id")["t1_decile"].to_dict() == second.set_index("candidate_id")["t1_decile"].to_dict()
    assert sorted(first["t1_decile"].unique()) == list(range(1, 11))


def test_within_decile_t4_median_rank_split_is_deterministic():
    frame = sample(11)
    frame["pred_t4"] = 0.25
    low, high = R.split_t4_halves(frame.sample(frac=1, random_state=2))
    assert len(low) == 6 and len(high) == 5
    assert low["candidate_id"].tolist() == [f"c{i:03}" for i in range(6)]


def test_conditional_spearman_uses_pooled_within_decile_ranks():
    frame = sample()
    frame["actual_loss"] = frame["pred_t4"]
    _, stats, _ = R.conditional_decile_audit(frame)
    assert np.isclose(stats["CONDITIONAL_T4_LOSS_SPEARMAN"], 1.0)
    assert stats["CORRECT_DECILE_COUNT"] == 10


def test_t1_top20_is_exact_and_uses_internal_t4_median_split():
    table, stats = R.top20_internal_split(sample(101))
    assert stats["T1_TOP20_COUNT"] == 21
    assert stats["T1_TOP20_LOW_T4_COUNT"] == 11
    assert stats["T1_TOP20_HIGH_T4_COUNT"] == 10
    assert table["count"].tolist() == [11, 10]


def test_fold_level_isolation_changes_no_rows_between_folds():
    frame = sample()
    left = frame.loc[frame["fold"].eq("OOF_2021")]
    right = frame.loc[frame["fold"].eq("OOF_2022")]
    left_stats, _, _ = R.conditional_summary(left)
    right_stats, _, _ = R.conditional_summary(right)
    assert left_stats["T1_TOP20_COUNT"] == 10 and right_stats["T1_TOP20_COUNT"] == 10


def test_authoritative_hashes_and_actual_oof_reconcile():
    assert R.file_sha256(R.T1_T2_CONTRACT) == R.T1_T2_TARGET_CONTRACT_SHA256
    assert R.file_sha256(R.T4_CONTRACT) == R.T4_TARGET_CONTRACT_SHA256
    assert R.file_sha256(R.R30B_MANIFEST) == R.R30B_FEATURE_MANIFEST_SHA256
    joined, identity = R.reconcile_oof(pd.read_parquet(R.T1_OOF_PATH), pd.read_parquet(R.T4_OOF_PATH))
    assert len(joined) == 998 and identity["OOF_UNMATCHED_COUNT"] == identity["OOF_DUPLICATE_COUNT"] == 0


def test_actual_1197_target_identity_has_explicit_199_row_warmup():
    authority = R.verify_authority()
    target = pd.read_parquet(authority["target_path"], columns=["candidate_id", "decision_timestamp_utc"])
    oof = pd.read_parquet(R.T1_OOF_PATH, columns=["candidate_id"])
    missing = target.loc[~target["candidate_id"].isin(set(oof["candidate_id"]))]
    assert len(target) == 1197 and len(missing) == 199 and set(missing["decision_timestamp_utc"].dt.year) == {2020}


def test_no_model_fit_predict_target_feature_or_holdout_operations():
    source = SCRIPT.read_text(encoding="utf-8")
    assert ".fit(" not in source and ".predict(" not in source and "predict_proba(" not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"NEW_FEATURE_COUNT": 0' in source and '"TARGET_CHANGES": 0' in source
    assert '"FINAL_CONFIRMATION_DATA_USED": False' in source


def test_storage_and_anti_bloat_contract_is_literal_and_no_repo_results():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"ANTI_BLOAT_STATUS": "PASS"' in source
    assert '"R30D_NEW_HELPER_FILE_COUNT": 0' in source
    assert '"R30D_GENERATED_REPO_ARTIFACT_COUNT": 0' in source
    assert '"SHARED_CODE_MODIFICATION_REQUIRED": False' in source
    assert not (R.SOURCE_ROOT / "results").exists()
