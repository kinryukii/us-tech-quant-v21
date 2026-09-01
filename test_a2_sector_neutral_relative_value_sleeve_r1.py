from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import research_registry as registry


MODULE_PATH = Path(__file__).with_name("a2_sector_neutral_relative_value_sleeve_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_sector_neutral_relative_value_sleeve_r1", MODULE_PATH)
assert SPEC and SPEC.loader
rv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rv)


def test_frozen_geometry_is_sector_neutral_and_two_sided() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D", "E", "F"],
            "sector": ["S1", "S1", "S1", "S2", "S2", "S2"],
            "score": [3.0, 2.0, 1.0, 12.0, 11.0, 10.0],
        }
    )
    result = rv.sector_neutral_weights(frame)
    sector_net = result.groupby("sector").weight.sum()
    assert np.allclose(sector_net.to_numpy(), 0.0, atol=1e-12)
    assert np.isclose(result.loc[result.weight > 0, "weight"].sum(), 1.0)
    assert np.isclose(-result.loc[result.weight < 0, "weight"].sum(), 1.0)
    assert np.isclose(result.weight.sum(), 0.0)
    assert set(result.loc[result.weight > 0, "ticker"]) == {"A", "D"}
    assert set(result.loc[result.weight < 0, "ticker"]) == {"C", "F"}


def test_ties_use_average_percentile_and_singleton_is_zero() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D", "E"],
            "sector": ["S1", "S1", "S1", "S1", "S2"],
            "score": [3.0, 2.0, 2.0, 1.0, 9.0],
        }
    )
    result = rv.sector_neutral_weights(frame)
    assert np.isclose(
        result.loc[result.ticker == "B", "signal"].iloc[0],
        result.loc[result.ticker == "C", "signal"].iloc[0],
    )
    assert np.isclose(result.loc[result.ticker == "E", "signal"].iloc[0], 0.0)


def test_contract_and_frozen_input_hashes_are_exact() -> None:
    verified = rv.verify_frozen_inputs()
    assert set(verified) == {str(path) for path in rv.EXPECTED_SHA256}
    assert all(row["status"] == "PASS" for row in verified.values())


def test_coverage_gate_fails_closed_on_top20_conditioned_taxonomy() -> None:
    coverage, audit = rv.reconcile_coverage()
    assert audit["selection_conditioned_taxonomy"] is True
    assert audit["physical_taxonomy_keyset_equals_raw_a2_top20"] is True
    assert audit["valid_taxonomy_keyset_subset_of_raw_a2_top20"] is True
    assert audit["sector_matched_rows"] == 14_990
    assert audit["matched_rank_gt20_rows"] == 0
    assert audit["matched_rank_max"] == 20
    assert audit["sector_coverage_ratio"] < 0.05
    assert audit["pit_taxonomy_timing_status"] == "PASS_DAY_LEVEL_WITH_INTRADAY_UNRESOLVED"
    assert coverage.loc[coverage.scope == "FULL_PRE2026", "status"].iloc[0] == "UNTESTABLE_SELECTION_CONDITIONED_TAXONOMY"


def test_empty_daily_output_schema_is_explicit_not_zero_filled() -> None:
    frame = rv.empty_daily_sleeve()
    assert frame.empty
    assert {"gross_return", "net_return", "turnover", "long_gross", "short_gross", "status"}.issubset(frame.columns)


def test_registry_allows_only_explicit_active_parent_geometry_extension() -> None:
    def fp(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode()).hexdigest()

    parent = {
        "entity_id": "RAW",
        "canonical_name": "RAW",
        "entity_type": "CORE_BASELINE",
        "status": "ACTIVE",
        "specification_fingerprint": fp("raw-spec"),
        "information_source_fingerprint": fp("raw-info"),
        "mechanism_fingerprint": fp("raw-rank"),
        "decision_layer": "TOP20",
        "evidence_source_temporal_status": "SAFE_PRE2026",
        "excluded_source_refs": [],
        "temporal_evidence_limitations": [],
        "authoritative_artifact_refs": ["synthetic://raw-contract"],
        "post_2025_observation_count": 0,
        "aliases": [],
        "metadata": {
            "information_source": "raw-a2-score",
            "information_family": "raw-a2-score",
            "feature_input_family": "raw-a2-score",
        },
    }
    child = dict(parent)
    child.update(
        {
            "entity_id": "RAW_RV",
            "canonical_name": "RAW_RV",
            "status": "OPEN",
            "specification_fingerprint": fp("rv-contract"),
            "mechanism_fingerprint": fp("raw-rank"),
            "decision_layer": "SEPARATE_RESEARCH_SLEEVE",
            "parent_entity_id": "RAW",
            "authoritative_artifact_refs": ["synthetic://rv-contract"],
            "metadata": {
                "information_source": "raw-a2-score",
                "information_family": "raw-a2-score",
                "feature_input_family": "raw-a2-score",
                "portfolio_geometry_fingerprint": fp("sector-neutral-geometry"),
            },
        }
    )
    proposal = {"change_type": "NEW_PORTFOLIO_GEOMETRY_ONLY", "parent_entity_id": "RAW", "candidate": child}
    decision = registry.evaluate_proposal(
        proposal,
        [registry._normalize_entity(parent)],
        [],
        head_sha256=registry.GENESIS,
    )
    assert decision["status"] == "PASS"
    assert decision["decision"] == "EXTEND_EXISTING"
    assert decision["matched_entity_ids"] == ["RAW"]

    registered_child = registry._normalize_entity(child)
    renamed = dict(child)
    renamed.update(
        {
            "entity_id": "RAW_RV_RENAMED",
            "canonical_name": "RAW_RV_RENAMED",
            "specification_fingerprint": fp("renamed-contract"),
            "decision_layer": "RENAMED_SEPARATE_SLEEVE",
        }
    )
    renamed_proposal = {
        "change_type": "NEW_PORTFOLIO_GEOMETRY_ONLY",
        "parent_entity_id": "RAW",
        "candidate": renamed,
    }
    renamed_decision = registry.evaluate_proposal(
        renamed_proposal,
        [registry._normalize_entity(parent), registered_child],
        [],
        head_sha256=registry.GENESIS,
    )
    assert renamed_decision["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"
    assert renamed_decision["matched_entity_ids"] == ["RAW_RV"]

    terminal_child = dict(registered_child)
    terminal_child["status"] = "CLOSED"
    terminal_decision = registry.evaluate_proposal(
        renamed_proposal,
        [registry._normalize_entity(parent), terminal_child],
        [],
        head_sha256=registry.GENESIS,
    )
    assert terminal_decision["decision"] == "BLOCKED_CLOSED_BRANCH"
    assert terminal_decision["matched_entity_ids"] == ["RAW_RV"]

    changed_mechanism = dict(child)
    changed_mechanism["mechanism_fingerprint"] = fp("new-mechanism")
    changed_decision = registry.evaluate_proposal(
        {"change_type": "NEW_PORTFOLIO_GEOMETRY_ONLY", "parent_entity_id": "RAW", "candidate": changed_mechanism},
        [registry._normalize_entity(parent)],
        [],
        head_sha256=registry.GENESIS,
    )
    assert changed_decision["decision"] != "EXTEND_EXISTING"
