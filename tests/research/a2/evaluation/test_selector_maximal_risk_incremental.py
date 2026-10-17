"""Pure synthetic equivalence and fail-closed tests; no real artifact readers."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_maximal_risk_incremental as sut

owner = sut.owner


@pytest.fixture(scope="module")
def sample():
    path = Path(__file__).with_name("test_selector_maximal_breadth_evidence.py")
    spec = importlib.util.spec_from_file_location("c14_incremental_existing_synthetic", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    clock, old, progressive, rule = module.series()
    base_new = {"C14_P01":progressive, "C14_P09":progressive*.7+.0004}
    base_rows, base_receipt, base_max = module.stats(old, base_new, clock, rule)
    _, se, _, _ = owner.shared.shared_max_t(old.to_numpy(float), np.arange(732), [True]*147,
        {**rule,"family_candidates":147})
    legacy = [dict(candidate_id=cid, status="COMPLETE", pooled_edge=float(old[cid].mean()),
        bootstrap_se=float(se[j]), year_edges={str(y):float(old.loc[old.index.year == y,cid].mean())
            for y in (2023,2024,2025)}) for j,cid in enumerate(old)]
    payload = dict(schema=sut.SCHEMA, research_id=owner.RESEARCH_ID, strict_PIT_promotion_eligible=False,
        clock_sha256=sut.content_hash(clock), legacy_ids=list(old), legacy_summaries=legacy,
        summaries=base_rows, bootstrap=base_receipt, maxima=base_max,
        source_custody=dict(status="PHYSICAL_FROZEN_EVIDENCE_VERIFIED", physical_sha256_verified=True,
            artifact_refs={k:dict(path="D:/us-tech-quant-backtests/V24/SYNTHETIC/"+k+".synthetic",
                sha256="a"*64) for k in ("c14_evidence","c14_maxima","legacy_summaries")}))
    hybrid = "C14_RX_HGB_LW"; contrast = "C14_INC_RX_HGB"
    full = pd.Series(.02+np.sin(np.arange(732))*.002, index=old.index)
    added = {hybrid:progressive*.5, contrast:progressive*.5-base_new["C14_P09"],
        "C14_G1":progressive*.3, "C14_INC_G1":progressive*.3-progressive, "C14_D01":full}
    endpoints = deepcopy(base_new)
    raw = pd.Series(-.01+np.cos(np.arange(732))*.001, index=old.index)
    proof = dict(status="PASS", source_receipt_sha256="f"*64, horizon_sessions=5, complete_dates=732,
        labels_mature_pre2026=True, native_shareholder_coordinate=True, predicted_risk_decreased=True)
    inputs = {"C14_D01":dict(raw=raw, selected=raw*.5, qualification=proof)}
    expected = module.stats(old, {**base_new,**added}, clock, rule, risk_inputs=inputs)
    return dict(payload=payload, clock=clock, rule=rule, added=added, endpoints=endpoints,
        inputs=inputs, expected=expected, module=module, old=old)


def call(sample, **overrides):
    data = dict(precomputed=sample["payload"], new_edges=sample["added"], clock=sample["clock"],
        rule=sample["rule"], legacy_ids=sample["payload"]["legacy_ids"], new_specs=owner.role_specs(),
        expected_precomputed_sha256=sut.content_hash(sample["payload"]), synthetic=True,
        retained_endpoints=sample["endpoints"], expected_endpoint_sha256=sut.content_hash(sample["endpoints"]),
        risk_inputs=sample["inputs"])
    data.update(overrides)
    return sut.incremental_statistics(**data)


def test_incremental_equals_original_one_shot_and_never_rebootstraps_old(sample, monkeypatch):
    def forbidden(*a, **k): raise AssertionError("OLD_BOOTSTRAP_FORBIDDEN")
    monkeypatch.setattr(owner.shared, "shared_max_t", forbidden)
    before = sut.content_hash(sample["payload"])
    rows, receipt, maxima, legacy = call(sample)
    expected_rows, expected_receipt, expected_maxima = sample["expected"]
    np.testing.assert_array_equal(maxima, expected_maxima)
    assert rows == expected_rows
    for key in ("critical_max_t","shared_draw_sha256","numeric_complete_series",
                "family_candidates","active_nonzero_se_columns","risk_tests","risk_efficiency"):
        assert receipt[key] == expected_receipt[key]
    assert receipt["old147_bootstrap_calls"] == receipt["old_ml_bootstrap_calls"] == 0
    assert receipt["exposure_namespace"] == 321
    assert receipt["strict_PIT_promotion_eligible"] is False and receipt["independent_holdout"] is False
    assert receipt["critical_max_t"] >= sample["payload"]["bootstrap"]["critical_max_t"]
    assert np.all(maxima >= sample["payload"]["maxima"])
    assert len(legacy) == 147
    for current, previous in zip(legacy, sample["payload"]["legacy_summaries"]):
        for key in ("candidate_id","pooled_edge","bootstrap_se","year_edges"):
            assert current[key] == previous[key]
        assert current["legacy_reselected"] is False
    assert sut.content_hash(sample["payload"]) == before


def test_empty_increment_is_exact_maxima_reuse(sample, monkeypatch):
    monkeypatch.setattr(owner.shared,"shared_max_t",lambda *a,**k:pytest.fail("OLD_BOOTSTRAP"))
    rows, receipt, maxima, _ = call(sample, new_edges={}, retained_endpoints={}, risk_inputs={})
    np.testing.assert_array_equal(maxima, sample["payload"]["maxima"])
    assert receipt["critical_max_t"] == sample["payload"]["bootstrap"]["critical_max_t"]
    assert receipt["incremental_numeric_added"] == 0
    assert len(rows) == 75 and len(receipt["risk_tests"]) == 20


@pytest.mark.parametrize("defect", ["maxima","summary","artifact"])
def test_independent_content_pin_blocks_counterfeit_precomputed_evidence(sample, defect):
    bad = deepcopy(sample["payload"])
    if defect == "maxima": bad["maxima"] = np.zeros_like(bad["maxima"])
    elif defect == "summary": bad["summaries"][0]["pooled_edge"] += 1
    else: bad["source_custody"]["artifact_refs"]["c14_maxima"]["sha256"] = "b"*64
    with pytest.raises(ValueError, match="CONTENT_PIN"):
        call(sample, precomputed=bad)


@pytest.mark.parametrize("defect,reason", [
    ("status","REAL_FROZEN"), ("studentization","REAL_FROZEN"), ("threshold","HIGHER_THRESHOLD"),
    ("draw","DRAW_SHA"), ("namespace","REAL_FROZEN"), ("short_maxima","MAXT_VECTOR"),
    ("fake_failed_zero","ZERO_PLACEHOLDER"), ("missing_legacy","SUMMARY_ROSTER"),
    ("missing_year","YEAR_COORDINATES"), ("future_clock","732_CLOCK"),
    ("custody","CUSTODY"), ("complete_count","COUNTS"), ("risk_zero","CANNOT_BE_ZERO"),
])
def test_precomputed_semantics_reject_fake_bootstrap_and_shortened_history(sample, defect, reason):
    bad = deepcopy(sample["payload"]); clock = sample["clock"].copy()
    receipt = bad["bootstrap"]
    if defect == "status": receipt["status"] = "SYNTHETIC_FAKE"
    elif defect == "studentization": receipt["studentization"] = "scalar_proxy"
    elif defect == "threshold": receipt["critical_max_t"] -= .1
    elif defect == "draw": receipt["shared_draw_sha256"] = receipt["legacy_shared_draw_sha256"] = "0"*64
    elif defect == "namespace": receipt["exposure_namespace"] = 301
    elif defect == "short_maxima": bad["maxima"] = bad["maxima"][:-1]
    elif defect == "fake_failed_zero":
        row = next(r for r in bad["summaries"] if r["status"] != "COMPLETE")
        row.update(pooled_edge=0., bootstrap_se=0.)
    elif defect == "missing_legacy": bad["legacy_summaries"].pop()
    elif defect == "missing_year": bad["legacy_summaries"][0]["year_edges"].pop("2023")
    elif defect == "future_clock":
        clock.loc[751,"signal_date"] = pd.Timestamp("2026-01-02"); bad["clock_sha256"] = sut.content_hash(clock)
    elif defect == "custody": bad["source_custody"]["physical_sha256_verified"] = False
    elif defect == "complete_count": receipt["numeric_complete_series"] -= 1
    else: receipt["risk_tests"][0]["pooled_risk_improvement"] = 0.
    with pytest.raises(ValueError,match=reason):
        call(sample,precomputed=bad,clock=clock,expected_precomputed_sha256=sut.content_hash(bad))


@pytest.mark.parametrize("defect", ["missing_day","nan","padded_year","unknown","rerun","failed_zero","bad_contrast","missing_endpoint","endpoint_pin"])
def test_new_roles_preserve_frozen_dates_identity_and_exact_contrasts(sample, defect):
    added = deepcopy(sample["added"]); endpoints = deepcopy(sample["endpoints"]); options = {}
    if defect == "missing_day": added["C14_D01"] = added["C14_D01"].iloc[1:]
    elif defect == "nan": added["C14_D01"].iloc[0] = np.nan
    elif defect == "padded_year": added["C14_G1"] = added["C14_G1"].reindex(sample["old"].index,fill_value=0)
    elif defect == "unknown": added["C14_UNKNOWN"] = added["C14_D01"]
    elif defect == "rerun": added["C14_P01"] = endpoints["C14_P01"]
    elif defect == "failed_zero": options["failed"] = {"C14_D01":"FAILED"}
    elif defect == "bad_contrast": added["C14_INC_G1"] += .001
    elif defect == "missing_endpoint": endpoints.pop("C14_P01")
    else: options["expected_endpoint_sha256"] = "0"*64
    options.update(new_edges=added,retained_endpoints=endpoints)
    if defect != "endpoint_pin": options["expected_endpoint_sha256"] = sut.content_hash(endpoints)
    with pytest.raises(ValueError): call(sample,**options)


@pytest.mark.parametrize("defect", ["bad_owner","short_h5","unknown_risk","repeat_complete"])
def test_only_native_full732_twenty_risk_hypotheses(sample, defect):
    inputs = deepcopy(sample["inputs"]); options = {}
    if defect == "bad_owner": inputs["C14_D01"]["qualification"]["native_shareholder_coordinate"] = False
    elif defect == "short_h5": inputs["C14_D01"]["selected"] = inputs["C14_D01"]["selected"].iloc[1:]
    elif defect == "unknown_risk": inputs["C14_D12"] = inputs["C14_D01"]
    else:
        rows, receipt, maxima, legacy = call(sample)
        payload = deepcopy(sample["payload"])
        payload.update(summaries=rows,bootstrap=receipt,maxima=maxima,legacy_summaries=legacy)
        options.update(precomputed=payload,expected_precomputed_sha256=sut.content_hash(payload),
            new_edges={},retained_endpoints={})
    with pytest.raises(ValueError): call(sample,risk_inputs=inputs,**options)


def test_real_zero_complete_addition_is_distinct_from_failed_fill(sample):
    zero = sample["added"]["C14_D01"]*0
    rows, receipt, _, _ = call(sample,new_edges={"C14_D01":zero},retained_endpoints={},risk_inputs={})
    row = next(r for r in rows if r["candidate_id"] == "C14_D01")
    assert row["status"] == "COMPLETE" and row["bootstrap_se"] == 0 and row["pooled_edge"] == 0
    assert row["simultaneous_lower_95"] is None and not row["supported"]
    assert receipt["incremental_numeric_added"] == 1


def test_production_requires_frozen5000_contract_before_numeric_payload(sample):
    class Poison(dict):
        def __getitem__(self,key): raise AssertionError("NUMERIC_BEFORE_GATE")
    module = sample["module"]; design = module.metadata(); gate = module.gate()
    design["formal_freeze_applied"] = False
    with pytest.raises(ValueError,match="FREEZE"):
        call(sample,precomputed=Poison(),synthetic=False,design=design,gate=gate,
            assembly=module.assembly(),expected_design_sha256="a"*64)
    design = module.metadata()
    with pytest.raises(ValueError,match="PAYLOAD_CHANGED"):
        call(sample,precomputed=Poison(),synthetic=False,design=design,gate=gate,
            assembly=module.assembly(),expected_design_sha256="a"*64)


@pytest.mark.parametrize("defect", ["budget","legacy_threshold","negative_increment","path_escape"])
def test_frozen_budget_threshold_and_artifact_scope_are_not_reinterpreted(sample, defect):
    bad = deepcopy(sample["payload"])
    if defect == "budget":
        row = next(r for r in bad["summaries"] if r["candidate_id"] == "C14_D12")
        row["status"] = "COMPLETE"
    elif defect == "legacy_threshold":
        bad["bootstrap"]["legacy_critical_max_t"] = bad["bootstrap"]["critical_max_t"]+1.
    elif defect == "negative_increment": bad["bootstrap"]["minimum_draw_wise_max_increment"] = -1.
    else:
        bad["source_custody"]["artifact_refs"]["c14_maxima"]["path"] = "D:/us-tech-quant-backtests/../elsewhere/file"
    with pytest.raises(ValueError):
        call(sample,precomputed=bad,expected_precomputed_sha256=sut.content_hash(bad))


def test_joint_threshold_guard_rejects_a_decreased_final_quantile(sample, monkeypatch):
    original = sut.np.quantile
    calls = []
    def lowered_final(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs) if len(calls) == 1 else -100.
    monkeypatch.setattr(sut.np,"quantile",lowered_final)
    with pytest.raises(ValueError,match="MUST_NOT_DECREASE"): call(sample)
    assert len(calls) == 2
