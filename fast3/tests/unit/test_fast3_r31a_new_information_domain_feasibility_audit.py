from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r31a_new_information_domain_feasibility_audit.py"
SPEC = importlib.util.spec_from_file_location("r31a", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def synthetic_bars(n: int = 240) -> pd.DataFrame:
    utc = pd.date_range("2024-01-02 14:30", periods=n, freq="min", tz="UTC")
    et = utc.tz_convert("America/New_York")
    return pd.DataFrame({"timestamp_utc": utc, "timestamp_et": et, "broker_trade_date": et.date.astype(str), "session": "RTH", "close": 100 + np.arange(n) / 100, "volume": 1000 + np.arange(n), "turnover": (1000 + np.arange(n)) * (100 + np.arange(n) / 100)})


def test_canonical_root_is_read_only_and_authorities_are_unchanged():
    authority = R.verify_authority()
    assert R.file_sha256(R.R30B_MANIFEST) == R.R30B_FEATURE_MANIFEST_SHA256
    assert authority["priors"]["R30D"]["FAST3_R30D_CLASSIFICATION"] == "D_CONDITIONAL_RESULT_CONTRADICTS_T4_RISK_SIGNAL"


def test_domain_inventory_is_deterministic_and_has_exact_four_domains():
    first, readiness = R.inventory_and_readiness(4); second, _ = R.inventory_and_readiness(4)
    assert first[R.DOMAIN_ORDER[0] == first["DOMAIN"]].iloc[0]["SOURCE_AVAILABLE"]
    assert first.to_json() == second.to_json() and first["DOMAIN"].tolist() == list(R.DOMAIN_ORDER)
    assert set(readiness["DOMAIN_STATUS"]).issubset(R.ALLOWED_DOMAIN_STATUSES)


def test_temporal_coverage_calculation_is_bounded_and_exact():
    assert R.temporal_coverage("2019-01-01", "2026-01-01") == 1.0
    assert R.temporal_coverage(None, None) == 0.0
    assert 0 < R.temporal_coverage("2024-01-01", "2024-12-31") < 1


def test_trailing_candidate_construction_has_no_future_bar_dependency():
    bars = synthetic_bars(); before = R.construct_volume_candidates(bars)
    changed = bars.copy(); changed.loc[changed.index[-1], ["close", "volume", "turnover"]] *= 100
    after = R.construct_volume_candidates(changed)
    pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])


def test_breadth_survivorship_and_proxy_basket_fail_closed():
    inventory, readiness = R.inventory_and_readiness(4)
    breadth = inventory.loc[inventory["DOMAIN"].eq("MARKET_BREADTH_SECTOR_INTERNALS")].iloc[0]
    gate = readiness.loc[readiness["DOMAIN"].eq("MARKET_BREADTH_SECTOR_INTERNALS")].iloc[0]
    assert breadth["SURVIVORSHIP_RISK"] == "UNCONTROLLED_HIGH"
    assert gate["DOMAIN_STATUS"] == "NOT_READY_SURVIVORSHIP" and not gate["PROXY_BASKET"]


def test_no_forward_asof_semantics_exist():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "merge_asof" not in source and "direction=\"forward\"" not in source and "bfill(" not in source


def test_feature_overlap_uses_no_economic_outcome_or_target_ledger():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "raw_net20" not in source and "TARGET_LEDGER_PATH" not in source
    assert "mutual_info" not in source and "roc_auc" not in source
    assert '"ECONOMIC_OUTCOME_COLUMN_READ_COUNT": 0' in source


def test_candidate_and_domain_budgets_are_hard_gated():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "len(approved_domains) > 2" in source and "len(approved_features) > 12" in source
    assert len(R.VOLUME_DEFINITIONS) <= 12


def test_no_model_fit_predict_or_search():
    source = SCRIPT.read_text(encoding="utf-8")
    assert ".fit(" not in source and ".predict(" not in source and "predict_proba(" not in source
    assert "GridSearchCV" not in source and "Optuna" not in source and "sklearn" not in source


def test_no_final_holdout_external_download_or_data_root_write():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"FINAL_CONFIRMATION_DATA_USED": False' in source and '"FINAL_CONFIRMATION_DATA_INSPECTED": False' in source
    assert '"NEW_EXTERNAL_DATA_DOWNLOAD_COUNT": 0' in source and '"DATA_ROOT_WRITE_COUNT": 0' in source
    assert not (R.SOURCE_ROOT / "results").exists()


def test_storage_and_anti_bloat_contract():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"NEW_HELPER_FILE_COUNT": 0' in source and '"SHARED_CODE_MODIFICATION_REQUIRED": False' in source
    assert '"ANTI_BLOAT_STATUS": "PASS"' in source and '"R31A_GENERATED_REPO_ARTIFACT_COUNT": 0' in source
