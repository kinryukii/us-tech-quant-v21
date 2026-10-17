"""Synthetic gate tests only; no registry/data access."""
import copy
import pytest
from scripts.maintenance import research_registry as r

@pytest.mark.parametrize("decision", ["BLOCKED_TERMINAL_HISTORY", "BLOCKED_FUNCTIONAL_REDUNDANCY", "BLOCKED_ALIAS_CONFLICT", "PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"])
def test_new_scope_cannot_override_other_automatic_decisions(decision):
    with pytest.raises(r.RegistryError, match="AUTOMATIC_DECISION_REQUIRED"):
        r._resolve_a_frozen_research_child_review({"entity": {}}, {}, {}, {"decision": decision, "reasons": []}, {}, "0"*64, scope=r._A_BASE_GROSS_COMBINATION_REVIEW_SCOPE)

def test_copied_scope_cannot_create_general_override():
    with pytest.raises(r.RegistryError, match="SCOPE_NOT_AUTHORIZED"):
        r._resolve_a_frozen_research_child_review({}, {}, {}, {}, {}, "0"*64, scope=copy.deepcopy(r._A_BASE_GROSS_COMBINATION_REVIEW_SCOPE))

def test_exact_scope_is_only_new_economic_child_and_no_runtime_authority():
    scope=r._A_BASE_GROSS_COMBINATION_REVIEW_SCOPE
    assert scope["change_type"] == "NEW_ECONOMIC_MECHANISM"
    assert scope["parent_entity_id"] == "V24_A_LEARNED_GROSS_CASH_PRE2026_R7"
    assert scope["additional_binding"]["new_account_execution_authority"] is False
    assert scope["additional_binding"]["new_training_authority"] is False
    assert len(scope["additional_custody"]) >= 2
    assert all(len(x["sha256"]) == 64 for x in scope["additional_custody"])
