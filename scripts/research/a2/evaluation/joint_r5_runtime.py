"""Thin R5 activation and budget binding over the existing durable lifecycle."""
from pathlib import Path
from contextlib import contextmanager
import json
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as parent

ID = "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5"
BASELINE, CAP, MAX_NEW = 3027, 4096, 1069


def guard(run, *, numeric=False, expected_freeze_sha256=None):
    run = Path(run)
    paths = resolve(parent.REPO)
    assert_safe_output_path(run, kind="backtest", paths=paths)
    config = parent.read_json(run / "run_config.json")
    if (config.get("task_id") != ID or config.get("prior_cumulative_fit_debits") != BASELINE
            or config.get("new_fit_budget_cap") != MAX_NEW or config.get("cumulative_fit_cap") != CAP
            or config.get("strict_PIT_promotion_eligible") is not False
            or config.get("quote_qualified") is not False
            or config.get("certified_nav_qualified") is not False):
        raise ValueError("EXACT_R5_MECHANISM_SCOPE_REQUIRED")
    authority = parent.read_json(run / "SOURCE_AUTHORITY.json")
    if (authority.get("research_id") != ID or authority.get("EF_access") is not False
            or authority.get("network_provider_fetch") is not False
            or authority.get("test2026_reads") != 0 or authority.get("2026_locked") is not True):
        raise ValueError("R5_NO_EF_PROVIDER_OR_TEST_ACCESS_REQUIRED")
    if numeric:
        path = run / "R5_SCIENCE_AND_EXECUTION_FREEZE.json"
        if not expected_freeze_sha256 or parent.sha(path) != expected_freeze_sha256:
            raise ValueError("EXACT_R5_PRE_NUMERIC_FREEZE_SHA_REQUIRED")
        freeze = parent.read_json(path)
        if (freeze.get("status") != "FROZEN_BEFORE_NUMERIC" or type(freeze.get("maximum_new_fit_units")) is not int
                or not 0 <= freeze["maximum_new_fit_units"] <= MAX_NEW
                or freeze.get("source_authority_ref", {}).get("sha256") != parent.sha(run / "SOURCE_AUTHORITY.json")):
            raise ValueError("R5_FROZEN_SOURCE_AND_BUDGET_REQUIRED")
        pins = freeze.get("source_code_pins")
        required = {Path(__file__).resolve(), Path(parent.__file__).resolve(),
                    (parent.REPO / "scripts/research/a2/risk/event_risk_contract_r5.py").resolve(),
                    (parent.REPO / "scripts/research/a2/risk/shared_risk_budget_r2.py").resolve()}
        if (not isinstance(pins, list) or not pins
                or not required.issubset({Path(v["path"]).resolve() for v in pins})):
            raise ValueError("COMPLETE_NONEMPTY_PINNED_R5_CLOSURE_REQUIRED")
        for ref in pins:
            parent._pin(ref["path"], ref["sha256"], "R5_CODE")
        _registered_scope(run, freeze, expected_freeze_sha256)
    return run


def _registered_scope(run, freeze, freeze_sha):
    """Read the existing accepted registry; never create/override admission."""
    from scripts.maintenance import research_registry
    config = parent.read_json(parent.REPO / "config/research_registry.json")
    view = research_registry.query_registry(config["registry_root"], entity_id=ID)
    if view.get("status") != "PASS" or view.get("count") != 1:
        raise ValueError("ACCEPTED_R5_REGISTRY_IDENTITY_REQUIRED_BEFORE_NUMERIC")
    row = view["entities"][0]
    metadata = row.get("metadata", {})
    if (row.get("status") not in {"OPEN", "ACTIVE"}
            or row.get("parent_entity_id") != "V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4"
            or Path(row.get("source_contract_ref", "")).resolve() != (run / "SOURCE_AUTHORITY.json").resolve()
            or metadata.get("event_science_freeze_sha256") != freeze_sha
            or metadata.get("event_source_authority_sha256") != freeze["source_authority_ref"]["sha256"]
            or metadata.get("strict_PIT_promotion_eligible") is not False
            or metadata.get("fit_authority") is not False
            or metadata.get("formal_freeze_authority") is not False):
        raise ValueError("REGISTERED_R5_EXACT_FREEZE_SOURCE_AND_METADATA_SCOPE_REQUIRED")


class R5FitLedger(parent.DurableFitLedger):
    """Reuse reserve/sync/no-refund implementation with the new scoped baseline."""
    def __init__(self, run, *, expected_freeze_sha256):
        self.run = guard(run, numeric=True, expected_freeze_sha256=expected_freeze_sha256)
        self.stage = "risk"
        self.inherited = BASELINE
        self.new_cap = self.stage_cap = parent.read_json(self.run / "R5_SCIENCE_AND_EXECUTION_FREEZE.json")["maximum_new_fit_units"]
        path = self.run / "work/FIT_STATUS.json"
        self.status = parent.read_json(path) if path.exists() else dict(
            status="READY", fit_attempts=BASELINE, inherited_fit_units=BASELINE,
            new_fit_units=0, risk_fit_units=0, records=[], failures=[], physical_events=[],
            account_paths=0, test2026_rows_read=0, baseline_source="PARENT_B_CUMULATIVE_NONREFUNDABLE_3027")
        new = self.status.get("new_fit_units")
        if (type(new) is not int or not 0 <= new <= self.new_cap
                or type(self.status.get("risk_fit_units")) is not int or self.status["risk_fit_units"] != new
                or self.status.get("inherited_fit_units") != BASELINE
                or self.status.get("fit_attempts") != BASELINE + self.status.get("new_fit_units", -1)
                or self.status.get("test2026_rows_read") != 0):
            raise ValueError("R5_COUNTER_OR_TEST_BOUNDARY_CHANGED")
        self.active_rr_correction = self.active_complete_group = None


@contextmanager
def stage_writer(run, name):
    run = guard(run)
    if name not in {"risk", "identity", "policy", "freeze"}:
        raise ValueError("EXACT_R5_STAGE_REQUIRED")
    lease = run / "work/leases" / name
    assert_safe_output_path(lease, kind="backtest", paths=resolve(parent.REPO))
    (lease / "work").mkdir(parents=True, exist_ok=True)
    with parent.task_writer(lease):
        yield
