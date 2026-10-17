"""R4 bounded run adapter for the existing durable fit ledger and storage owner.

No estimator, labels, source authority, account or research registry lives here.
Stage partitions are disjoint upper bounds; inherited B spend is counted once.
"""
from pathlib import Path
from scripts.research.a2.evaluation.joint_frozen_history_risk_r3 import (
    DurableFitLedger, read_json, write, sha, _pin, REPO)
from scripts.research.a2.risk.shared_risk_budget_r2 import LEARNED_KINDS

ID = "V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4"
CAPS = {"opportunity":864, "calibration_fusion":300, "statistical_risk":626, "other":10}

def guard(run, expected_matrix_sha=None):
    run = Path(run)
    state = read_json(run / "EXECUTION_STATE.json")
    expected = expected_matrix_sha or state.get("matrix_sha256")
    _pin(run / "WHOLE_MATRIX_FREEZE.json", expected, "r4_whole_matrix")
    matrix = read_json(run / "WHOLE_MATRIX_FREEZE.json")
    if (matrix.get("research_id") != ID or matrix.get("2026_locked") is not True
        or matrix.get("strict_PIT_promotion_eligible") is not False
        or matrix.get("quote_qualified") is not False
        or matrix.get("certified_nav_qualified") is not False
        or matrix.get("scientific_retry") != 0):
        raise ValueError("R4_FROZEN_MECHANISM_BOUNDARY_REQUIRED")
    for ref in matrix.get("pinned_artifacts", ()) + matrix.get("code_pins", ()):
        _pin(ref["path"], ref["sha256"], "r4_dependency")
    budget_ref = matrix.get("budget_scope_ref")
    if budget_ref:
        _pin(budget_ref["path"], budget_ref["sha256"], "r4_budget_scope")
    budget = read_json(Path(budget_ref["path"]) if budget_ref else run / "BUDGET_SCOPE_FREEZE.json")
    if (budget.get("prior_ledger",{}).get("reserved"), budget.get("effective_new_cap"),
        budget.get("branch_cumulative_cap"), budget.get("stage_caps")) != (1876,1800,4096,CAPS):
        raise ValueError("R4_BUDGET_IDENTITY_CHANGED")
    if sum(CAPS.values()) != 1800 or 1876+1800>4096:
        raise ValueError("R4_STAGE_PARTITION_INVALID")
    return matrix

class StageLedger(DurableFitLedger):
    """Thin initialization adapter; reservation/sync retain the existing owner."""
    def __init__(self, run, stage, filename=None, *, expected_matrix_sha=None):
        self.run, self.stage = Path(run), stage
        guard(self.run, expected_matrix_sha)
        if stage not in CAPS:
            raise ValueError("UNKNOWN_R4_STAGE")
        self.inherited = 1876
        # A stage can spend only its fixed partition, not other stages' slack.
        self.new_cap = self.stage_cap = CAPS[stage]
        self.filename = filename or {"opportunity":"OPPORTUNITY_FIT_STATUS.json",
            "calibration_fusion":"FUSION_FIT_STATUS.json", "statistical_risk":"RISK_FIT_STATUS.json",
            "other":"OTHER_FIT_STATUS.json"}[stage]
        self.active_rr_correction = self.active_complete_group = None
        target = self.run / "work" / self.filename
        self.status = read_json(target) if target.exists() else dict(status="READY",
            research_id=ID, stage=stage, fit_attempts=1876, inherited_fit_units=1876,
            new_fit_units=0, risk_fit_units=0, records=[], failures=[], physical_events=[],
            account_paths=0, test2026_rows_read=0)
        if (self.status.get("inherited_fit_units") != 1876
            or self.status.get("fit_attempts") != 1876+self.status.get("new_fit_units",-1)
            or self.status.get("stage") != stage or self.status.get("test2026_rows_read") != 0):
            raise ValueError("R4_STAGE_COUNTER_OR_SCOPE_CHANGED")
        self.checkpoint()
    def checkpoint(self):
        write(self.run, "work/"+self.filename, self.status)
    def reserve(self, event):
        if self.status["new_fit_units"]+int(event["kind"] in LEARNED_KINDS)>self.stage_cap:
            raise ValueError("R4_STAGE_CAP_EXCEEDED_NO_REFUND")
        return super().reserve(event)


def stage_writer(run, stage):
    """Partition an existing task_writer lease; no new locking implementation."""
    from scripts.common.storage_paths import assert_safe_output_path, resolve
    from scripts.research.a2.evaluation.joint_method_stages import task_writer
    if stage not in CAPS:
        raise ValueError("UNKNOWN_R4_STAGE")
    lease = Path(run) / "work" / "leases" / stage
    assert_safe_output_path(lease,kind="backtest",paths=resolve(REPO))
    (lease / "work").mkdir(parents=True, exist_ok=True)
    return task_writer(lease)
