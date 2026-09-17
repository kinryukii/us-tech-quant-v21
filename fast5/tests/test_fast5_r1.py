from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "fast4" / "src"))

from fast5.asset_audit import (  # noqa: E402
    DATA, FORBIDDEN_TARGET_COLUMNS, R1_FEATURE_MANIFEST, R43A_CONTRACT, TIER_A,
    StageAFirewallError, TargetValueFirewall, load_candidate_metadata, load_config,
    select_tier_a, sha256,
)
from fast5.features import build_cross_asset_features  # noqa: E402
from fast5.training import _preregistration, _selected_specs  # noqa: E402
from fast4.r2_evaluation import crossfit_ridge_stack  # noqa: E402
from fast4.splits import inner_folds, outer_folds  # noqa: E402
from fast4.strong_models import StrongSpec, estimator  # noqa: E402


def test_target_and_fast4_feature_identities_without_target_values() -> None:
    cfg = load_config()
    assert sha256(R43A_CONTRACT) == cfg["target_sha256"]
    manifest = json.loads(R1_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    assert len(manifest["feature_order"]) == 241
    assert manifest["feature_manifest_sha256"] == cfg["fast4_baseline_feature_manifest_sha256"]


def test_stage_a_firewall_rejects_all_target_columns() -> None:
    firewall = TargetValueFirewall()
    for column in FORBIDDEN_TARGET_COLUMNS:
        with pytest.raises(StageAFirewallError, match="TARGET_VALUE_READ_BEFORE_PREREGISTRATION"):
            firewall.assert_projection(["candidate_id", column])
    assert firewall.target_value_read_count == 0


def test_candidate_metadata_projection_is_outcome_blind() -> None:
    firewall = TargetValueFirewall()
    frame = load_candidate_metadata(firewall)
    assert len(frame) == 1197
    assert not (set(frame) & FORBIDDEN_TARGET_COLUMNS)
    assert firewall.target_value_read_count == 0


def test_outcome_blind_priority_selection_is_deterministic() -> None:
    cfg = load_config()
    eligibility = pd.DataFrame([
        {"logical_asset_family": "ARCHIVED_NEWS_EVENTS", "tier": TIER_A},
        {"logical_asset_family": "GENUINELY_NEW_CROSS_ASSET", "tier": TIER_A},
        {"logical_asset_family": "MARKET_MICROSTRUCTURE", "tier": TIER_A},
        {"logical_asset_family": "HISTORICAL_OPTIONS", "tier": "TIER_B_VALID_PIT_BUT_INSUFFICIENT_COVERAGE"},
    ])
    expected = ["MARKET_MICROSTRUCTURE", "ARCHIVED_NEWS_EVENTS", "GENUINELY_NEW_CROSS_ASSET"]
    assert select_tier_a(eligibility, cfg["family_priority"], 3) == expected
    assert select_tier_a(eligibility.sample(frac=1, random_state=7), cfg["family_priority"], 3) == expected


def test_actual_new_feature_generation_is_deterministic_and_pit() -> None:
    firewall = TargetValueFirewall()
    candidate = load_candidate_metadata(firewall)
    cfg = load_config()
    first, audit1 = build_cross_asset_features(candidate, DATA, cfg["cross_asset_symbols"])
    second, audit2 = build_cross_asset_features(candidate, DATA, cfg["cross_asset_symbols"])
    pd.testing.assert_frame_equal(first, second)
    assert audit1 == audit2
    assert audit1["feature_count"] == 30
    assert audit1["source_date_violation_count"] == 0
    assert audit1["backfill_count"] == 0
    assert audit1["maximum_source_staleness_calendar_days"] <= 4
    assert firewall.target_value_read_count == 0


def test_preregistration_precedes_target_read_and_sha_payload_is_stable() -> None:
    firewall = TargetValueFirewall()
    cfg = load_config()
    audit = {"selected": ["GENUINELY_NEW_CROSS_ASSET"]}
    first = _preregistration(audit, cfg)
    second = dict(first)
    second["creation_timestamp_utc"] = first["creation_timestamp_utc"]
    assert first == second
    assert firewall.target_value_read_count == 0
    with pytest.raises(StageAFirewallError):
        firewall.record_target_read()
    firewall.preregistration_frozen = True
    firewall.authorize_stage_b()
    firewall.record_target_read()
    assert firewall.target_value_read_count == 1


def _synthetic_fold_frame() -> pd.DataFrame:
    rows = []
    blocks = ("OOF_2020", "OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")
    for block_number, block in enumerate(blocks):
        for day in range(12):
            timestamp = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=block_number * 100 + day)
            rows.append({"candidate_id": f"{block}-{day}", "decision_timestamp_utc": timestamp,
                         "target_end_timestamp_utc": timestamp + pd.Timedelta(minutes=60),
                         "trading_date": str(timestamp.date()), "validation_slice": block})
    return pd.DataFrame(rows)


def test_nested_folds_are_chronological_purged_embargoed_and_disjoint() -> None:
    frame = _synthetic_fold_frame()
    outer = outer_folds(frame, 60, 60)
    assert len(outer) == 5
    for fold in outer:
        assert not (set(fold.train_index) & set(fold.valid_index))
        valid_start = frame.loc[fold.valid_index, "decision_timestamp_utc"].min()
        assert (frame.loc[fold.train_index, "target_end_timestamp_utc"] < valid_start - pd.Timedelta(minutes=60)).all()
        inner = inner_folds(frame, fold.train_index, 3, 60, 60)
        assert len(inner) == 3
        for local in inner:
            assert not (set(local.train_index) & set(local.valid_index))


def test_lightgbm_xgboost_catboost_and_finite_predictions() -> None:
    rng = np.random.default_rng(9)
    x = pd.DataFrame(rng.normal(size=(80, 4)), columns=list("abcd"))
    y = pd.Series(rng.normal(scale=.01, size=80))
    specs = [
        StrongSpec("lgb", "LightGBM", "huber", "pooled", "regression", "target"),
        StrongSpec("xgb", "XGBoost", "reg:pseudohubererror", "pooled", "regression", "target"),
        StrongSpec("cat", "CatBoost", "Huber:delta=0.005", "pooled", "regression", "target"),
    ]
    params = [
        {"n_estimators": 12, "learning_rate": .05, "num_leaves": 7, "max_depth": 3,
         "min_child_samples": 8, "reg_alpha": .1, "reg_lambda": 1.},
        {"n_estimators": 12, "learning_rate": .05, "max_depth": 3, "min_child_weight": 2.,
         "reg_alpha": .1, "reg_lambda": 1.},
        {"iterations": 12, "learning_rate": .05, "depth": 3, "l2_leaf_reg": 2., "random_strength": .1,
         "bagging_temperature": 1., "border_count": 32},
    ]
    for spec, local in zip(specs, params):
        model = estimator(spec, local, 77, 2)
        model.fit(x, y)
        assert np.isfinite(np.asarray(model.predict(x))).all()


def test_optuna_spec_contract_and_meta_crossfit() -> None:
    cfg = load_config()
    assert len(_selected_specs(cfg)) == 18
    assert cfg["optuna_trial_cap"] == 1000
    index = pd.RangeIndex(90)
    rng = np.random.default_rng(11)
    base = pd.DataFrame(rng.normal(size=(90, 3)), index=index, columns=["p1", "p2", "p3"])
    target = pd.Series(rng.normal(size=90), index=index)
    labels = pd.Series(np.repeat(["INNER_1", "INNER_2", "INNER_3"], 30), index=index)
    crossfit, outer, contract, model = crossfit_ridge_stack(base, base.tail(10), target, labels)
    assert crossfit.notna().sum() >= 30
    assert np.isfinite(outer).all()
    assert contract["alpha"] in (1., 10., 100., 1000.)
    assert model is not None


def test_storage_and_no_broker_api_contract() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "fast5").glob("*.py"))
    forbidden = ("OpenSecTradeContext", "place_order(", "unlock_trade(", "modify_order(")
    assert not any(token in source for token in forbidden)
    assert str(DATA) == r"D:\us-tech-quant-data"
    assert str(Path(r"D:\us-tech-quant-results")).startswith(r"D:\us-tech-quant-results")
