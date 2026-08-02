"""Pre-registered FAST3-005 abstention layer; it emits decisions, never orders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..common.contracts import ContractViolation, assert_confirmation_forbidden


REQUIRED_COLUMNS = {"event_id", "opportunity_score", "direction_score_up", "direction_model_score_spread",
                    "data_trust_ok", "expected_net_return_10bps", "expected_net_return_20bps"}


def load_abstention_policy(path: str | Path) -> dict[str, Any]:
    """Load the one frozen policy and reject unsafe or threshold-changing variants."""
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("stage_id") != "FAST3-005" or policy.get("schema_version") != "1.0.0":
        raise ContractViolation("FAST3_005_POLICY_ID_OR_SCHEMA_INVALID")
    if policy["frozen_fast3_002_contract_sha256"] != "72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead":
        raise ContractViolation("FAST3_002_CONTRACT_HASH_MISMATCH")
    if policy["frozen_fast3_004_opportunity_threshold"] != 0.6:
        raise ContractViolation("FAST3_004_OPPORTUNITY_THRESHOLD_MUST_REMAIN_060")
    if policy["safety"] != {"development_or_validation_run_allowed": False, "confirmation_read_count": 0,
                            "live_trading_allowed": False, "broker_action_allowed": False,
                            "final_model_training_allowed": False}:
        raise ContractViolation("FAST3_005_SAFETY_CONTRACT_VIOLATION")
    if policy["priority_order"] != ["DATA_TRUST_FAILED", "OPPORTUNITY_BELOW_FROZEN_GATE", "DIRECTION_CONFIDENCE_BELOW_FLOOR",
                                    "MODEL_DISAGREEMENT_EXCEEDS_LIMIT", "COST_EXPECTANCY_NON_POSITIVE_10BPS",
                                    "COST_EXPECTANCY_NON_POSITIVE_20BPS"]:
        raise ContractViolation("FAST3_005_PRIORITY_ORDER_NOT_FROZEN")
    return policy


def _reason(row: pd.Series, policy: dict[str, Any]) -> str | None:
    """Return the first pre-registered reason, making abstention deterministic."""
    threshold = policy["thresholds"]
    if not bool(row.data_trust_ok):
        return "DATA_TRUST_FAILED"
    if float(row.opportunity_score) < policy["frozen_fast3_004_opportunity_threshold"]:
        return "OPPORTUNITY_BELOW_FROZEN_GATE"
    confidence = max(float(row.direction_score_up), 1.0 - float(row.direction_score_up))
    if confidence < threshold["direction_confidence_minimum"]:
        return "DIRECTION_CONFIDENCE_BELOW_FLOOR"
    if float(row.direction_model_score_spread) > threshold["model_disagreement_maximum"]:
        return "MODEL_DISAGREEMENT_EXCEEDS_LIMIT"
    if float(row.expected_net_return_10bps) <= threshold["expected_net_return_minimum"]:
        return "COST_EXPECTANCY_NON_POSITIVE_10BPS"
    if float(row.expected_net_return_20bps) <= threshold["expected_net_return_minimum"]:
        return "COST_EXPECTANCY_NON_POSITIVE_20BPS"
    return None


def apply_abstention_policy(scored: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    """Attach a zero-order decision record to each FAST3-004 scored event."""
    missing = REQUIRED_COLUMNS - set(scored.columns)
    if missing:
        raise ContractViolation(f"FAST3_005_MISSING_SCORED_FIELDS:{sorted(missing)}")
    x = scored.copy()
    if "decision_timestamp_et" in x:
        assert_confirmation_forbidden(pd.to_datetime(x.decision_timestamp_et), "2025-02-08T00:00:00-05:00")
    rows: list[dict[str, Any]] = []
    for row in x.itertuples(index=False):
        item = row._asdict()
        reason = _reason(pd.Series(item), policy)
        abstain = reason is not None
        direction = "UP" if float(item["direction_score_up"]) >= 0.5 else "DOWN"
        rows.append({**item, "direction_confidence": max(float(item["direction_score_up"]), 1.0 - float(item["direction_score_up"])),
                     "abstain": abstain, "abstention_reason": reason, "decision": "ABSTAIN" if abstain else "ELIGIBLE_FOR_FAST3_002",
                     "candidate_direction": None if abstain else direction, "proposed_position_count": 0,
                     "orders_emitted": 0, "live_trading_allowed": False})
    return pd.DataFrame(rows)


def safety_summary(decisions: pd.DataFrame) -> dict[str, int | bool]:
    """Expose flat-output and single-account invariants without opening a position."""
    return {"decision_count": int(len(decisions)), "abstention_count": int(decisions.abstain.sum()),
            "eligible_signal_count": int((~decisions.abstain).sum()), "proposed_position_count": int(decisions.proposed_position_count.sum()),
            "orders_emitted": int(decisions.orders_emitted.sum()), "single_account_max_concurrent_positions": 1,
            "live_trading_allowed": False}
