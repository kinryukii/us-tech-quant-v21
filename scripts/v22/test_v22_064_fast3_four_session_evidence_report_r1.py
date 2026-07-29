from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import v22_064_fast3_four_session_evidence_report_r1 as mod


def common_summary(decision: str) -> dict:
    return {
        "final_status": "PASS",
        "final_decision": decision,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "supported_exit_variants_for_replication": [],
    }


def forward_summary(decision: str) -> dict:
    return {
        **common_summary(decision),
        "v22_062pb_validated": True,
        "research_cutoff_date": "2026-07-24",
        "forward_holdout_only": True,
        "rule_change_requires_reset": True,
        "sole_exit_variant": "PREMARKET_0925",
        "historical_pre_cutoff_outcomes_used_for_qualification": False,
        "strategy_rule_change_executed": False,
        "completed_holdout_session_count": 0,
        "forward_trade_count": 0,
        "interim_evaluable": False,
        "final_evaluable": False,
        "forward_replication_pass": False,
    }


def pb_summary() -> dict:
    return {
        **common_summary(
            mod.PREMARKET_HISTORICAL_DECISION
        ),
        "supported_exit_variants_for_replication": [
            "PREMARKET_0925"
        ],
        "quarantined_trade_count": 0,
        "source_trade_count": 969,
        "normalized_trade_count": 2,
    }


def test_parse_supported():
    assert mod.parse_supported(["A", "B"]) == ["A", "B"]
    assert mod.parse_supported("[]") == []
    assert mod.parse_supported(None) == []


def test_safe_number_helpers():
    assert mod.safe_int("12") == 12
    assert mod.safe_int(None) == 0
    assert mod.safe_float("1.5") == pytest.approx(1.5)
    assert np.isnan(mod.safe_float(None))


def test_validate_common_guards():
    mod.validate_common_guards(
        common_summary("X"),
        "X",
    )


def test_validate_common_guards_rejects():
    summary = common_summary("X")
    summary["raw_files_modified"] = True
    with pytest.raises(mod.EvidenceError):
        mod.validate_common_guards(summary, "X")


def test_validate_pb():
    spec = mod.ArchitectureSpec(
        "PREMARKET_062PB",
        "PREMARKET",
        "x",
        mod.Path("x"),
        (mod.PREMARKET_HISTORICAL_DECISION,),
    )
    mod.validate_spec(spec, pb_summary())


def test_validate_forward():
    spec = mod.ArchitectureSpec(
        "PREMARKET_062PR",
        "PREMARKET",
        "x",
        mod.Path("x"),
        tuple(mod.FORWARD_PENDING_DECISIONS),
        True,
    )
    mod.validate_spec(
        spec,
        forward_summary(
            "FORWARD_REPLICATION_IN_PROGRESS_"
            "INSUFFICIENT_INTERIM_SAMPLE"
        ),
    )


def test_validate_rejected_architecture():
    spec = mod.ArchitectureSpec(
        "RTH_063R2_LATE_CONT",
        "RTH",
        "x",
        mod.Path("x"),
        (
            "NO_RTH_LATE_DAY_CONTINUATION_"
            "CANDIDATE_QUALIFIED",
        ),
    )
    mod.validate_spec(
        spec,
        common_summary(
            "NO_RTH_LATE_DAY_CONTINUATION_"
            "CANDIDATE_QUALIFIED"
        ),
    )


def test_rejected_architecture_cannot_support_exit():
    spec = mod.ArchitectureSpec(
        "RTH_063R2_LATE_CONT",
        "RTH",
        "x",
        mod.Path("x"),
        (
            "NO_RTH_LATE_DAY_CONTINUATION_"
            "CANDIDATE_QUALIFIED",
        ),
    )
    summary = common_summary(
        "NO_RTH_LATE_DAY_CONTINUATION_"
        "CANDIDATE_QUALIFIED"
    )
    summary["supported_exit_variants_for_replication"] = [
        "FIXED_60M"
    ]
    with pytest.raises(mod.EvidenceError):
        mod.validate_spec(spec, summary)


def test_evidence_classes():
    assert mod.evidence_class(
        "PREMARKET_062PB",
        mod.PREMARKET_HISTORICAL_DECISION,
    ) == "HISTORICAL_CANDIDATE_FORWARD_REQUIRED"
    assert mod.evidence_class(
        "RTH",
        "NO_RTH_LATE_DAY_CONTINUATION_CANDIDATE_QUALIFIED",
    ) == "HISTORICAL_REJECT"
    assert mod.evidence_class(
        "N",
        (
            "OVERNIGHT_VWAP_MEAN_REVERSION_"
            "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
        ),
    ) == "INCONCLUSIVE_INSUFFICIENT_SAMPLE"


def test_count_helpers():
    assert mod.candidate_count(
        {"signal_candidate_count": 20}
    ) == 20
    assert mod.trade_count(
        {"trade_count_by_exit_variant": {"A": 10, "B": 9}}
    ) == 10
    assert mod.trade_count(
        {"forward_trade_count": 3}
    ) == 3


def test_standardize_period(tmp_path):
    path = tmp_path / "period.csv"
    pd.DataFrame(
        {
            "exit_variant": ["FIXED"],
            "study_period": ["2023-2024_VALIDATION"],
            "trade_count": [10],
            "mean_instrument_return": [0.001],
            "median_instrument_return": [0.0005],
            "profit_factor": [1.2],
        }
    ).to_csv(path, index=False)
    result = mod.standardize_period_frame(
        "A",
        "RTH",
        path,
    )
    assert result.iloc[0]["architecture_id"] == "A"
    assert result.iloc[0]["trade_count"] == 10


def test_standardize_qualification(tmp_path):
    path = tmp_path / "qualification.csv"
    pd.DataFrame(
        {
            "exit_variant": ["FIXED"],
            "sample_pass": [True],
            "research_candidate_for_independent_replication": [
                False
            ],
        }
    ).to_csv(path, index=False)
    result = mod.standardize_qualification_frame(
        "A",
        "RTH",
        path,
    )
    assert bool(result.iloc[0]["sample_pass"])


def test_find_optional_csv(tmp_path):
    path = tmp_path / "x_period_summary.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    assert mod.find_optional_csv(
        tmp_path,
        ("*period_summary.csv",),
    ) == path


def test_best_period_rows():
    frame = pd.DataFrame(
        {
            "architecture_id": ["A", "A"],
            "session": ["RTH", "RTH"],
            "exit_variant": ["X", "Y"],
            "study_period": [
                "2023-2024_VALIDATION",
                "2023-2024_VALIDATION",
            ],
            "trade_count": [10, 10],
            "mean_instrument_return": [-0.001, 0.001],
            "median_instrument_return": [0.0, 0.0],
            "profit_factor": [0.9, 1.1],
        }
    )
    best = mod.best_period_rows(frame)
    assert best.iloc[0]["exit_variant"] == "Y"


def inventory(forward_decision: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "architecture_id": "PREMARKET_062PB",
                "evidence_class": (
                    "HISTORICAL_CANDIDATE_FORWARD_REQUIRED"
                ),
                "final_decision": (
                    mod.PREMARKET_HISTORICAL_DECISION
                ),
            },
            {
                "architecture_id": "PREMARKET_062PR",
                "evidence_class": (
                    mod.evidence_class(
                        "PREMARKET_062PR",
                        forward_decision,
                    )
                ),
                "final_decision": forward_decision,
            },
            {
                "architecture_id": "RTH",
                "evidence_class": "HISTORICAL_REJECT",
                "final_decision": (
                    "NO_RTH_LATE_DAY_CONTINUATION_"
                    "CANDIDATE_QUALIFIED"
                ),
            },
            {
                "architecture_id": "N",
                "evidence_class": (
                    "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
                ),
                "final_decision": (
                    "OVERNIGHT_VWAP_MEAN_REVERSION_"
                    "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
                ),
            },
        ]
    )


def test_build_decision_pending():
    result = mod.build_decision(
        inventory(
            "FORWARD_REPLICATION_IN_PROGRESS_"
            "INSUFFICIENT_INTERIM_SAMPLE"
        )
    )
    assert result["forward_replication_pending"]
    assert not result["multi_session_state_machine_allowed"]
    assert "TRANSITION_RETURN_ATLAS" in result["next_stage"]


def test_build_decision_passed():
    result = mod.build_decision(
        inventory(mod.FORWARD_PASS_DECISION)
    )
    assert result["forward_replication_passed"]
    assert result["multi_session_state_machine_allowed"]
    assert "STATE_MACHINE" in result["next_stage"]


def test_build_decision_failed():
    result = mod.build_decision(
        inventory(mod.FORWARD_FAIL_DECISION)
    )
    assert result["forward_replication_failed"]
    assert not result["multi_session_state_machine_allowed"]


def test_markdown_report():
    inv = pd.DataFrame(
        [
            {
                "session": "RTH",
                "architecture_name": "Test",
                "final_decision": "NO",
                "evidence_class": "HISTORICAL_REJECT",
                "candidate_count": 10,
                "trade_count": 10,
            }
        ]
    )
    best = pd.DataFrame(
        [
            {
                "architecture_id": "A",
                "study_period": "2023-2024_VALIDATION",
                "exit_variant": "X",
                "trade_count": 10,
                "mean_instrument_return": -0.001,
                "median_instrument_return": -0.001,
                "profit_factor": 0.9,
            }
        ]
    )
    text = mod.markdown_report(
        inv,
        best,
        {
            "overall_decision": "TEST",
            "next_stage": "NEXT",
        },
    )
    assert "Architecture inventory" in text
    assert "Best observed exit" in text


def test_atomic_json(tmp_path):
    path = tmp_path / "x.json"
    mod.atomic_json(path, {"a": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_default_specs():
    specs = mod.default_specs(mod.Path("ROOT"))
    assert len(specs) == 8
    assert {
        spec.session
        for spec in specs
    } == {
        "PREMARKET",
        "RTH",
        "OVERNIGHT",
        "AFTER_HOURS",
    }


def test_parse_args():
    args = mod.parse_args(["--execute"])
    assert "us-tech-quant-results" in args.results_root
    assert "V22.064_FAST3" in args.result_dir


def test_policy_constants():
    assert mod.EXPECTED_CUTOFF == "2026-07-24"
    assert mod.FORWARD_PASS_DECISION.endswith(
        "RESEARCH_CANDIDATE_ONLY"
    )
