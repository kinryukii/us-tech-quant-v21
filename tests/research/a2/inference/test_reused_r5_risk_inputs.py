"""Synthetic daily/state fixtures only; no real serialized state or account."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference import reused_r5_risk_inputs as inputs
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity
from scripts.research.a2.risk.shared_risk_engine_r2 import COORDINATE
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash


@pytest.fixture
def example(monkeypatch):
    days = pd.DatetimeIndex(["2022-12-30", "2023-01-03", "2023-01-04", "2023-01-05"])
    assets = ["A", "B"]
    uids = {a: "UID_" + a for a in assets}
    epochs = {a: "EPOCH_" + a for a in assets}
    coords = {a: dict(class_coordinate_status="EXACT_FROZEN_INTERVAL_METADATA_DECLARATION", cusip="SYNTHETIC_" + a) for a in assets}
    signature = dict(ordered_assets=assets, asset_uids=uids, asset_epochs=epochs, blocked_assets={},
        source_identity={"source_inputs_sha256": "c"*64}, security_coordinates=coords,
        ff48_qualified_source_support={a: {"group": 1} for a in assets},
        feature_source_support={a: ["SYNTHETIC"] for a in assets})
    primary_sha = content_hash({k: v for k, v in signature.items() if k != "ff48_qualified_source_support"})
    refs = {k: dict(path="D:/synthetic/R5/"+k+".json", sha256="a"*64) for k in ("plan", "support", "global", "source")}
    event = dict(event_id="SYNTHETIC_EVENT", decision_date="2023-01-03", decision_asof=inputs.producer._clock(days[1]).isoformat(),
        fit_history_cutoff=inputs.producer._clock(days[0]).isoformat(), current_identity_available_at=inputs.producer._clock(days[1]).isoformat(),
        requested_assets=assets, asset_uids=uids, asset_epochs=epochs, segment_starts={a: "2020-01-02" for a in assets}, security_coordinates=coords,
        complete_structural_signature=signature, structural_signature_sha256=content_hash(signature),
        dependency_local_event_ids={"PRIMARY": "PRIMARY_0", "QQQ": "QQQ_0", "FF48": "FF48_0"},
        dependency_local_signature_sha256={"PRIMARY": primary_sha, "QQQ": primary_sha, "FF48": content_hash(signature)},
        history_support=dict(nominal_n={"A": 252, "B": 0}, short0=["B"], current_identity_blockers={}, source_metadata_blockers={}, parent_origin_count=252, qqq_h5_endpoint_key_support=True))
    binding = dict(family="LW", parent_risk="R0", method="R5::LW::SYNTHETIC_CHILD", representation="EVENT_CLASSICAL_WITH_PRIOR_COMPLETION",
                   recipe_sha256="b"*64, producer_sha256="c"*64, availability="READY")
    source = dict(dependency="PRIMARY", dependency_local_event_id="PRIMARY_0", dependency_local_signature_sha256=primary_sha,
                  source_pins={"scientific_contract": refs["plan"]["sha256"], "primary": "c"*64})
    sid = structural_identity(assets=tuple(assets), uids=uids, epochs=epochs, security_coordinate=COORDINATE, source_support_identity=source)
    proof = dict(parent_risk=binding["parent_risk"], representation=binding["representation"], recipe_sha256=binding["recipe_sha256"],
        model_producer_sha256=binding["producer_sha256"], structural_identity=sid, source_support_identity_sha256=content_hash(source),
        asset_uid_epoch_sha256=content_hash(dict(uids=uids, epochs=epochs)))
    record = dict(event_id=event["event_id"], family="LW", dependency_local_event_id="PRIMARY_0", recipe_id="RECIPE_0", method=binding["method"],
        as_of=event["decision_asof"], cutoff=event["fit_history_cutoff"], assets=assets, asset_uids=uids, asset_epochs=epochs,
        status="PASS_FROZEN_HISTORY_MECHANISM", finite_check=True, risk_state_id="SYNTHETIC_STATE", source_support_identity=source, event_policy_binding=proof,
        publication_status="VERIFIED_MECHANISM_STATE", artifact_ref={"path": "D:/synthetic/R5/original.joblib", "sha256": "d"*64},
        typed_state_content_sha256="e"*64, covariance_sha256=None,
        source_receipt=dict(return_coordinate=COORDINATE, status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND", mechanism=True, synthetic=False,
            scientific_contract_sha256=refs["plan"]["sha256"], identity_epoch="R5_CURRENT_POOL_OBSERVED_UIDS:"+content_hash(epochs),
            strict_PIT_promotion_eligible=False, quote_qualified=False, historical_authority_status="UNKNOWN"))
    state = SimpleNamespace(risk_state_id=record["risk_state_id"], assets=tuple(assets), method=record["method"], status=record["status"],
        as_of=record["as_of"], cutoff=record["cutoff"], covariance=np.array([[4., .25], [.25, 1.]]),
        coverage={a: dict(uid=uids[a], identity_epoch=epochs[a], nominal_n=0 if a=="B" else 252, n0_prior_only=a=="B") for a in assets},
        notes={"event_policy_binding": proof, "numeric_check": {"psd_check": "ORIGINAL_SYNTHETIC"}})
    daily = [dict(decision_date=str(d.date()), decision_asof=inputs.producer._clock(d).isoformat(), support_epoch_event_id=event["event_id"],
        dependency_local_event_ids=event["dependency_local_event_ids"], dependency_local_signature_sha256=event["dependency_local_signature_sha256"],
        future_event_date_used=False) for d in days[1:]]
    class Reader:
        def __init__(self): self.calls = []
        def read(self, name, columns, **kwargs):
            self.calls.append((name, tuple(columns), kwargs))
            if name == "raw_open_close":
                assert columns == ("ticker", "trade_date", "code")
                return pd.DataFrame(dict(ticker=assets, trade_date=[kwargs["day"]]*2, code=assets))
            assert name == "prediction_features" and tuple(columns) == tuple(inputs.producer.old.FEATURE_META)
            selected = [kwargs["day"]] if "day" in kwargs else [d for d in days if kwargs["start"] <= d < kwargs["stop"]]
            return pd.DataFrame([dict(ticker=a, signal_date=d, security_id=uids[a]) for d in selected for a in assets], columns=["ticker", "signal_date", "security_id"])
    class Loader:
        def __init__(self): self.loads = 0; self.cache = {}; self.guard_calls = 0
        def __call__(self, row):
            assert row is record
            self.guard_calls += 1
            key = (row["artifact_ref"]["path"], row["artifact_ref"]["sha256"])
            if key not in self.cache:
                self.loads += 1
                self.cache[key] = state
            return self.cache[key]
    pool_calls = []
    def current_pool(features, raw, original_event, day, ordered_assets):
        pool_calls.append(day)
        assert original_event is event and ordered_assets == tuple(assets)
        assert not features.signal_date.gt(day).any() and raw.trade_date.eq(day).all()
        current = features.loc[features.signal_date.eq(day)]
        return current, pd.Series(True, index=current.index), features.copy()
    c = dict(plan={"nodes": [dict(event_id=event["event_id"], recipe_id="RECIPE_0", family_dependencies={"LW": "PRIMARY"})], "method_bindings": [binding]},
        support={"events": [event], "daily_support_chain": daily, "decision_session_count": 3},
        publication={"states_and_retained_attempts": [record]}, reader=Reader(), calendar=days,
        state_loader=Loader(), current_pool=current_pool, current_pool_proof={"exact_original_pure_block": True}, refs=refs)
    factory_calls = []
    def components(interface):
        factory_calls.append(interface)
        return c
    monkeypatch.setattr(inputs, "_load_original_components", components)
    provider = inputs.ExistingR5LWInputs(interface=object(), market_dates=days[1:], master_assets=("OUT", "B", "A"))
    def context(day="2023-01-03", *, decision=(True, False, True), buy=(True, True, True), units=(0., 1., 0.), weights=(0., .1, 0.)):
        return SimpleNamespace(tickers=provider.master_assets, signal_date=pd.Timestamp(day), signal_asof=inputs.producer._clock(day),
            decision_mask=np.array([decision], bool), buy_allowed=np.array([buy], bool), current_units=np.array([units]), current_weights=np.array([weights]))
    return SimpleNamespace(provider=provider, components=c, record=record, state=state, context=context, calls=factory_calls, pool_calls=pool_calls)


def test_construction_and_daily_domain_do_not_load_numeric_state(example):
    assert example.calls == [] and example.provider.loads_count == 0
    mask = example.provider.daily_domain("2023-01-03", decision_as_of=inputs.producer._clock("2023-01-03"))
    assert mask.tolist() == [False, True, True]
    assert example.provider.loads_count == 0
    assert len(example.components["reader"].calls) == 3


def test_exact_principal_projection_keeps_actual_held_and_master_order(example):
    output = example.provider.for_decision(example.context())
    assert output.assets == ("B", "A") and output.columns.tolist() == [1, 2]
    np.testing.assert_array_equal(output.covariance, [[1., .25], [.25, 4.]])
    assert output.pool_mask.tolist() == [False, True, True] and output.covariance_psd_qualified
    assert output.loads_count == 1 and not output.covariance.flags.writeable
    assert not output.columns.flags.writeable and not output.pool_mask.flags.writeable
    receipt = output.source_receipt
    assert receipt["original_covariance_sha256"] is None
    assert receipt["original_artifact_ref"]["sha256"] == "d"*64
    assert receipt["publication_typed_state_content_sha256"] == "e"*64
    assert receipt["historical_publication_authority"] == "UNKNOWN" and not receipt["strict_PIT"]
    np.testing.assert_array_equal(example.state.covariance, [[4., .25], [.25, 1.]])


def test_same_original_state_is_loaded_and_psd_checked_once_across_days(example, monkeypatch):
    original = inputs.validate_covariance
    checks = []
    def guard(*args, **kwargs):
        checks.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(inputs, "validate_covariance", guard)
    example.provider.for_decision(example.context())
    out = example.provider.for_decision(example.context("2023-01-04"))
    assert out.loads_count == 1 and checks == [{"regularize": False}]
    assert example.components["state_loader"].guard_calls == 2
    assert example.pool_calls == [pd.Timestamp("2023-01-03"), pd.Timestamp("2023-01-04")]
    assert out.source_receipt["original_state_asof"] != out.source_receipt["current_use_asof"]


def test_all_cash_empty_required_domain_does_not_load_original_state(example):
    out = example.provider.for_decision(example.context(decision=(True, False, False), units=(0., 0., 0.), weights=(0., 0., 0.)))
    assert out.assets == () and out.columns.size == 0 and out.covariance.shape == (0, 0)
    assert out.loads_count == 0 and not out.source_receipt["numeric_state_loaded"]


@pytest.mark.parametrize("field", ["units", "weights"])
def test_any_positive_actual_holding_outside_pool_blocks_before_numeric_load(example, field):
    kwargs = dict(units=(0., 0., 0.), weights=(0., 0., 0.))
    kwargs[field] = (1e-15, 0., 0.)
    with pytest.raises(inputs.ExistingRiskInputUnavailable, match="ACTUAL_HELD_OUTSIDE") as exc:
        example.provider.for_decision(example.context(**kwargs))
    assert exc.value.receipt["assets"] == ["OUT"] and example.provider.loads_count == 0


def test_buy_disabled_actual_held_asset_stays_required(example):
    out = example.provider.for_decision(example.context(buy=(True, False, False)))
    assert out.assets == ("B",) and out.covariance.tolist() == [[1.]]


@pytest.mark.parametrize("defect,reason", [("uid", "CURRENT_FULL_REQUESTED"), ("recipe", "FAMILY_RECIPE"), ("source", "CURRENT_METHOD_LOCAL"), ("unverified", "STATE_NOT_VERIFIED")])
def test_source_qualification_is_not_replaced_by_numeric_finiteness(example, defect, reason):
    if defect == "uid": example.record["asset_uids"] = {"A": "OTHER", "B": "UID_B"}
    elif defect == "recipe": example.record["recipe_id"] = "OTHER"
    elif defect == "source": example.record["source_support_identity"] = {**example.record["source_support_identity"], "dependency_local_signature_sha256": "f"*64}
    else: example.record["publication_status"] = "BLOCKED"
    with pytest.raises(inputs.ExistingRiskInputUnavailable, match=reason):
        example.provider.for_decision(example.context())
    assert example.provider.loads_count == 0


def test_loaded_state_metadata_checked_before_covariance(example):
    example.state.coverage = {"A": {"uid": "OTHER"}}
    class StateWithoutNumeric:
        def __getattr__(self, key):
            if key == "covariance": pytest.fail("covariance read before metadata qualification")
            return getattr(example.state, key)
    example.components["state_loader"].__class__.__call__ = lambda self, row: StateWithoutNumeric()
    with pytest.raises(inputs.ExistingRiskInputUnavailable, match="FULL_DOMAIN_COVERAGE"):
        example.provider.for_decision(example.context())


@pytest.mark.parametrize("matrix,reason", [(np.ones((1, 1)), "SHAPE_CHANGED"), (np.array([[1., 3.], [3., 1.]]), "NOT_PSD"), (np.array([[1., np.nan], [np.nan, 1.]]), "NONFINITE")])
def test_invalid_original_covariance_is_never_reestimated_or_zero_filled(example, matrix, reason):
    example.state.covariance = matrix
    with pytest.raises(ValueError, match=reason) as exc:
        example.provider.for_decision(example.context())
    assert not isinstance(exc.value, inputs.ExistingRiskInputUnavailable)


def test_changed_clock_is_engineering_error_before_source_io(example):
    ctx = example.context()
    ctx.signal_asof += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="EXACT_PRE2026_CURRENT_CLOSE") as exc:
        example.provider.for_decision(ctx)
    assert not isinstance(exc.value, inputs.ExistingRiskInputUnavailable) and example.calls == []


def test_duplicate_original_dependency_is_engineering_error(example):
    example.components["publication"]["states_and_retained_attempts"].append(deepcopy(example.record))
    with pytest.raises(ValueError, match="DUPLICATE_ORIGINAL_LW") as exc:
        example.provider.for_decision(example.context())
    assert not isinstance(exc.value, inputs.ExistingRiskInputUnavailable)


def test_future_event_lookup_is_refused(example):
    example.components["support"]["daily_support_chain"][0]["future_event_date_used"] = True
    with pytest.raises(ValueError, match="ORIGINAL_DAILY_EVENT_CLOCK"):
        example.provider.for_decision(example.context())


def test_context_master_axis_cannot_silently_reorder(example):
    ctx = example.context()
    ctx.tickers = ("A", "B", "OUT")
    with pytest.raises(ValueError, match="EXACT_MASTER_ASSET_ORDER"):
        example.provider.for_decision(ctx)


def test_two_state_lru_also_evicts_original_loader_cache(example):
    loader = example.components["state_loader"]
    def guarded(self, row):
        self.guard_calls += 1
        key = (row["artifact_ref"]["path"], row["artifact_ref"]["sha256"])
        if key not in self.cache:
            self.loads += 1
            self.cache[key] = deepcopy(example.state)
        return self.cache[key]
    loader.__class__.__call__ = guarded
    for i in range(3):
        example.record["risk_state_id"] = example.state.risk_state_id = "SYNTHETIC_"+str(i)
        example.record["artifact_ref"] = {"path": "D:/synthetic/R5/"+str(i)+".joblib", "sha256": str(i)*64}
        example.provider.for_decision(example.context())
    assert len(example.provider._checked) == len(loader.cache) == 2
    assert all("/0.joblib" not in k[0] for k in loader.cache)
    example.provider.for_decision(example.context())
    assert loader.loads == 3 and loader.guard_calls == 4



def test_causal_domain_keeps_outside_held_action_but_never_reopens_new_buy(example):
    ctx = example.context(units=(1., 1., 0.), weights=(.1, .1, 0.))
    ctx.reserved_mask = np.array([[False, True, False]])
    ctx.operational_mask = np.array([[False, False, False]])
    before = {name: getattr(ctx, name).copy() for name in (
        "decision_mask", "buy_allowed", "current_units", "current_weights",
        "reserved_mask", "operational_mask")}
    result = inputs.causal_held_domain(ctx, np.array([False, True, True]))
    assert result["assets"] == ("OUT", "B", "A")
    assert result["eligible_mask"].tolist() == [False, False, True]
    assert result["held_mask"].tolist() == [True, True, False]
    assert result["decision_mask"].tolist() == [True, False, True]
    assert result["buy_allowed"].tolist() == [False, True, True]
    for name, original in before.items():
        np.testing.assert_array_equal(getattr(ctx, name), original)
    for value in result.values():
        if isinstance(value, np.ndarray):
            assert not value.flags.writeable


def test_causal_domain_preserves_original_held_lock_and_positive_weight_membership(example):
    ctx = example.context(decision=(False, False, True), units=(0., 0., 0.),
                          weights=(1e-15, .1, 0.))
    result = inputs.causal_held_domain(ctx, np.array([False, True, True]))
    assert result["assets"] == ("OUT", "B", "A")
    assert result["held_mask"].tolist() == [True, True, False]
    assert result["decision_mask"].tolist() == [False, False, True]
    assert not result["buy_allowed"][0]


def test_new_domain_method_does_not_override_original_default_held_block(example):
    ctx = example.context(units=(1., 1., 0.), weights=(.1, .1, 0.))
    domain = example.provider.causal_domain(ctx)
    assert domain["assets"] == ("OUT", "B", "A")
    assert domain["source_receipt"]["old_default_qualification_unchanged"]
    assert not domain["source_receipt"]["numeric_state_loaded"]
    with pytest.raises(inputs.ExistingRiskInputUnavailable, match="ACTUAL_HELD_OUTSIDE"):
        example.provider.for_decision(ctx)
    assert example.provider.loads_count == 0


def _axis_record(state_id, assets, *, asof="2023-01-03T21:00:00+00:00",
                 available=None, status="VERIFIED_MECHANISM_STATE"):
    return dict(family="LW", risk_state_id=state_id, assets=list(assets),
                as_of=asof, cutoff="2022-12-30T21:00:00+00:00",
                state_available_at=asof if available is None else available,
                publication_status=status)


@pytest.mark.parametrize("future_field", ["as_of", "state_available_at"])
def test_axis_audit_cannot_use_future_state_or_availability(future_field):
    older = _axis_record("OLDER", ("A", "B"))
    later = _axis_record("FUTURE", ("A", "B"))
    later[future_field] = "2023-01-04T21:00:00+00:00"
    result = inputs.audit_complete_original_lw_axes([later, older], ("B", "A"),
                decision_as_of="2023-01-03T21:00:00+00:00")
    assert result["axis_candidate_ids"] == ["OLDER"]
    assert result["selected_state_id"] is None and not result["state_use_authorized"]
    future = next(row for row in result["states"] if row["risk_state_id"] == "FUTURE")
    assert not future["causal"]
    assert "FUTURE_STATE_OR_MECHANISM_AVAILABILITY" in future["exclusion_reasons"]


def test_axis_audit_refuses_to_union_separate_states_or_invent_cross_covariance():
    records = [_axis_record("A_ONLY", ("A",)), _axis_record("B_ONLY", ("B",))]
    before = deepcopy(records)
    result = inputs.audit_complete_original_lw_axes(records, ("A", "B"),
                decision_as_of="2023-01-03T21:00:00+00:00")
    assert result["status"] == "BLOCKED_NO_COMPLETE_CAUSAL_ORIGINAL_LW_AXIS"
    assert result["axis_candidate_ids"] == [] and result["selected_state_id"] is None
    assert not result["matrix_mixing"] and not result["state_use_authorized"]
    assert result["all_required_cross_covariance_must_exist_in_one_state"]
    assert [row["missing_required_assets"] for row in result["states"]] == [["B"], ["A"]]
    assert records == before


def test_complete_axis_is_candidate_only_and_never_identity_or_numeric_authority():
    complete = _axis_record("AXIS_ONLY", ("A", "B"))
    unverified = _axis_record("UNVERIFIED", ("A", "B"), status="BLOCKED")
    result = inputs.audit_complete_original_lw_axes([complete, unverified], ("B", "A"),
                decision_as_of="2023-01-03T21:00:00+00:00")
    assert result["status"] == "COMPLETE_AXIS_CANDIDATE_REQUIRES_FURTHER_QUALIFICATION"
    assert result["axis_candidate_ids"] == ["AXIS_ONLY"]
    assert result["selected_state_id"] is None and not result["state_use_authorized"]
    assert result["numeric_payloads_read"] == result["new_risk_estimates"] == 0
    assert result["historical_availability_authority"] == "UNKNOWN_ORIGINAL_MECHANISM_ASSUMPTION_ONLY"
    assert "ORIGINAL_STATE_NOT_VERIFIED" in result["states"][1]["exclusion_reasons"]
    # Axis presence alone has supplied no artifact, UID/epoch or PSD evidence.
    assert result["states"][0]["artifact_ref"] is None
    assert result["states"][0]["typed_state_content_sha256"] is None


def test_provider_axis_preflight_is_metadata_only_and_keeps_complete_required_domain(example):
    example.record["state_available_at"] = example.record["as_of"]
    ctx = example.context(units=(1., 1., 0.), weights=(.1, .1, 0.))
    result = example.provider.audit_original_axes(ctx)
    assert result["required_assets"] == ["OUT", "B", "A"]
    assert result["status"] == "BLOCKED_NO_COMPLETE_CAUSAL_ORIGINAL_LW_AXIS"
    assert result["states"][0]["missing_required_assets"] == ["OUT"]
    assert not result["domain_source_receipt"]["numeric_state_loaded"]
    assert example.provider.loads_count == 0



@pytest.fixture
def held_book():
    """Entirely fabricated source refs, raw quantities and identity/session rows."""
    ref = lambda label: dict(path="D:/synthetic/held/"+label+".json", sha256="a"*64)
    identity = dict(security_id="CUSIP_A", security_id_type="CUSIP", cusip="CUSIP_A",
                    share_class="COM", raw_code="US.A", raw_actual_share_coordinate="RAW_ACTUAL_SHARE")
    def seed(day="2023-01-03", **changes):
        return dict(identity, qualified=True, historical_observations_relabelled=False,
            identity_asof=inputs.producer._clock(day).isoformat(), seed_source_ref=ref("seed"),
            seed_source_row_identity="SEED_ROW_A", historical_source_epoch="ORIGINAL_OBSERVED_UID_EPOCH", **changes)
    def guard(day="2023-01-04", **changes):
        result=dict(identity, qualified=True, historical_observations_relabelled=False,
            decision_session=day, mapping_start="2023-01-03", mapping_end_exclusive="2026-01-01",
            mapping_row_count=1, raw_key_count=1, mapping_raw_code="US.A", raw_key_code="US.A",
            raw_key_session=day, current_accounting_mapping_ref=ref("mapping"),
            current_mapping_row_identity="MAPPING_A", raw_exact_key_ref=ref("raw"),
            raw_key_row_identity="RAW_"+day+"_A", declared_catalogue_refs=[ref("catalogue")],
            catalogue_checked_from_session="2023-01-03", catalogue_checked_through_session=day,
            processed_event_fingerprints=[], unsupported_event_fingerprints=[], identity_conflict_count=0,
            quantity_transitions=[])
        result.update(changes)
        return result
    def fill(q=1., before=0., *, side="BUY", order="O1", signal="2023-01-03", day="2023-01-04", **extra):
        row=dict(path_id="P0", order_id=order, signal_date=signal, execution_date=day, ticker="A", side=side,
            fractional_shares=q, index_units_before=before, index_units_after=before+(q if side=="BUY" else -q))
        row.update(extra)
        # Economic columns exist but are never accessed by book column projection.
        row.update(price=object(), nav=object(), indicative_return=object(), cost=object())
        return pd.DataFrame([row])
    def ctx(day="2023-01-04", units=1., weight=.1):
        return SimpleNamespace(tickers=("A",), signal_date=pd.Timestamp(day), signal_asof=inputs.producer._clock(day),
                               current_units=np.array([[units]]), current_weights=np.array([[weight]]))
    book=inputs.HeldPositionLineageBook("P0", fill_owner_ref=ref("owner"), lineage_rule_ref=ref("rule"))
    def admitted():
        book.note_qualified_decision("2023-01-03", {"A":seed()})
        book.observe_fills(fill())
        return book.qualified_proofs(ctx(), {"A":guard()})["A"]
    def transition(kind="SPLIT", before=1., after=2., day="2023-01-05", **changes):
        result=dict(kind=kind, qualified=True, typed_event=True, stage="PRE_OPEN", session=day,
            event_fingerprint="EVENT_1", before_raw_quantity=before, after_raw_quantity=after,
            share_ratio=after/before, old_identity=identity.copy(), new_identity=identity.copy(),
            source_ref=ref("event"), owner_ref=ref("ca_owner"))
        result.update(changes)
        return result
    return SimpleNamespace(book=book, ref=ref, identity=identity, seed=seed, guard=guard, fill=fill,
                           ctx=ctx, admitted=admitted, transition=transition)


def test_held_candidates_do_not_admit_or_authorize_raw_ticker_only_holding(held_book):
    x=held_book
    x.book.note_qualified_decision("2023-01-03", {"A":x.seed()})
    assert x.book.held_assets==()
    with pytest.raises(inputs.HeldLineageUnavailable, match="ADMISSION_SEED_MISSING"):
        x.book.qualified_proofs(x.ctx(), {"A":x.guard()})
    assert x.book.held_assets==() and x.book.pending_fill_count==0


def test_held_actual_fill_seed_produces_exact_22_fields_and_no_historical_relabel(held_book):
    x=held_book
    proof=x.admitted()
    assert tuple(proof)==inputs.HeldPositionLineageBook.PROOF_FIELDS and len(proof)==22
    assert proof["seed_security_id"]=="CUSIP_A" and proof["actual_quantity_binding"]["raw_quantity"]==1.
    assert proof["quantity_transition_refs"][0]["owner_ref"]==x.ref("owner")
    assert proof["lineage_status"]=="QUALIFIED_RESEARCH_HELD_LINEAGE"
    assert "asof" not in proof and "historical_authority" not in proof
    assert x.book.held_assets==("A",) and x.book.pending_fill_count==0
    proof["seed_source_ref"]["sha256"]="b"*64
    nextproof=x.book.qualified_proofs(x.ctx("2023-01-05"), {"A":x.guard("2023-01-05")})["A"]
    assert nextproof["seed_source_ref"]["sha256"]=="a"*64
    assert nextproof["prior_quantity_binding"]["session"]=="2023-01-04"


@pytest.mark.parametrize("change,reason", [
    ({"qualified":False},"QUALIFIED_ENTRY_SEED"),
    ({"historical_observations_relabelled":True},"QUALIFIED_ENTRY_SEED"),
    ({"identity_asof":"2023-01-04T21:00:00+00:00"},"FUTURE_ENTRY"),
    ({"raw_actual_share_coordinate":"INDEX_UNIT"},"RAW_ACTUAL_SHARE"),
    ({"cusip":"ANOTHER"},"SID_CUSIP_CONFLICT"),
    ({"share_class":"UNKNOWN"},"IDENTITY_FIELD"),
    ({"seed_source_ref":dict(path="D:/synthetic",sha256=None)},"PINNED_HELD"),
])
def test_held_bad_seed_is_atomic(held_book,change,reason):
    x=held_book; value=x.seed(); value.update(change)
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):
        x.book.note_qualified_decision("2023-01-03",{"A":value})
    with pytest.raises(inputs.HeldLineageUnavailable,match="SEED_MISSING"):
        x.book.observe_fills(x.fill())
    assert x.book.pending_fill_count==0


def test_held_zero_unfilled_candidate_does_not_admit(held_book):
    x=held_book; x.book.note_qualified_decision("2023-01-03",{"A":x.seed()})
    assert x.book.observe_fills(x.fill(q=0.))==0
    assert x.book.qualified_proofs(x.ctx(units=0.,weight=0.),{})=={}
    assert x.book.held_assets==()


def test_held_duplicate_order_preserves_prior_pending_audit(held_book):
    x=held_book; x.book.note_qualified_decision("2023-01-03",{"A":x.seed()})
    x.book.observe_fills(x.fill())
    with pytest.raises(inputs.HeldLineageUnavailable,match="DUPLICATE"):
        x.book.observe_fills(x.fill())
    assert x.book.pending_fill_count==1
    assert x.book.qualified_proofs(x.ctx(),{"A":x.guard()})["A"]["actual_quantity_binding"]["raw_quantity"]==1.


@pytest.mark.parametrize("change,reason", [
    ({"path_id":"OTHER_ACCOUNT"},"CROSS_ACCOUNT"),
    ({"index_units_after":2.},"QUANTITY_CONFLICT"),
])
def test_held_bad_fill_does_not_consume_candidate_or_queue(held_book,change,reason):
    x=held_book; x.book.note_qualified_decision("2023-01-03",{"A":x.seed()})
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason): x.book.observe_fills(x.fill(**change))
    assert x.book.pending_fill_count==0
    assert x.book.observe_fills(x.fill())==1


@pytest.mark.parametrize("change,reason", [
    ({"security_id":"REUSED_CODE","cusip":"REUSED_CODE"},"IDENTITY_CONFLICT"),
    ({"share_class":"CL B"},"IDENTITY_CONFLICT"),
    ({"raw_key_code":"US.B"},"RAW_CODE_CONFLICT"),
    ({"raw_key_count":2},"UNIQUE_DATED"),
    ({"mapping_row_count":0},"UNIQUE_DATED"),
    ({"mapping_row_count":True},"UNIQUE_DATED"),
    ({"mapping_start":"2023-01-05"},"DATED_MAPPING"),
    ({"catalogue_checked_from_session":"2023-01-04"},"CATALOGUE_INTERVAL"),
    ({"unsupported_event_fingerprints":["UNKNOWN_SPLIT"]},"UNSUPPORTED_SHARE"),
    ({"historical_observations_relabelled":True},"CURRENT_HELD_SOURCE"),
    ({"declared_catalogue_refs":[]},"UNSUPPORTED_SHARE"),
])
def test_held_guard_failure_keeps_pending_and_can_recheck_same_session(held_book,change,reason):
    x=held_book; x.book.note_qualified_decision("2023-01-03",{"A":x.seed()}); x.book.observe_fills(x.fill())
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):
        x.book.qualified_proofs(x.ctx(),{"A":x.guard(**change)})
    assert x.book.pending_fill_count==1 and x.book.held_assets==()
    assert x.book.qualified_proofs(x.ctx(),{"A":x.guard()})["A"]["ticker"]=="A"


def test_held_feature_membership_absence_keeps_actual_lineage_without_entry_restore(held_book):
    x=held_book; original=x.admitted()
    ctx=x.ctx("2023-01-05"); ctx.decision_mask=np.array([[False]]);ctx.buy_allowed=np.array([[False]])
    proof=x.book.qualified_proofs(ctx,{"A":x.guard("2023-01-05")})["A"]
    assert proof["position_id"]==original["position_id"]
    domain=inputs.causal_held_domain(ctx,np.array([False]))
    assert domain["assets"]==("A",) and not domain["buy_allowed"].any()


def test_held_supported_preopen_split_precedes_actual_fill(held_book):
    x=held_book;x.admitted();x.book.note_qualified_decision("2023-01-04",{"A":x.seed("2023-01-04")})
    x.book.observe_fills(x.fill(q=1.,before=2.,order="O2",signal="2023-01-04",day="2023-01-05"))
    guard=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[x.transition()])
    proof=x.book.qualified_proofs(x.ctx("2023-01-05",units=3.),{"A":guard})["A"]
    assert [r.get("kind",r.get("stage")) for r in proof["quantity_transition_refs"]]==["SPLIT","ACTUAL_RAW_SHARE_FILL"]
    assert proof["actual_quantity_binding"]["raw_quantity"]==3.


@pytest.mark.parametrize("change,reason", [
    ({"share_ratio":None},"SHARE_RATIO"),
    ({"share_ratio":1.5},"SHARE_RATIO"),
    ({"typed_event":False},"TYPED_SHARE_TRANSITION"),
    ({"before_raw_quantity":2.},"PRIOR_CONFLICT"),
])
def test_held_share_transition_without_exact_typed_terms_blocked(held_book,change,reason):
    x=held_book;x.admitted();t=x.transition();t.update(change)
    guard=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t])
    with pytest.raises((inputs.HeldLineageUnavailable,ValueError,TypeError),match=reason if change.get("share_ratio","other") is not None else None):
        x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":guard})
    assert x.book.held_assets==("A",)


def test_held_typed_conversion_binds_exact_new_identity_without_rewriting_seed(held_book):
    x=held_book;x.admitted();new=dict(x.identity,security_id="CUSIP_NEW",cusip="CUSIP_NEW",share_class="CL B",raw_code="US.NEW")
    t=x.transition(kind="CONVERSION",new_identity=new)
    guard=x.guard("2023-01-05",**new,mapping_raw_code="US.NEW",raw_key_code="US.NEW",
                  processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t])
    proof=x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":guard})["A"]
    assert proof["seed_security_id"]=="CUSIP_A"
    assert proof["quantity_transition_refs"][0]["new_identity"]["security_id"]=="CUSIP_NEW"


def test_held_cash_only_preserves_raw_quantity_and_identity(held_book):
    x=held_book;old=x.admitted()
    proof=x.book.qualified_proofs(x.ctx("2023-01-05"),{"A":x.guard("2023-01-05",processed_event_fingerprints=["CASH_EVENT"])})["A"]
    assert proof["position_id"]==old["position_id"] and proof["quantity_transition_refs"]==[]
    assert proof["actual_quantity_binding"]["raw_quantity"]==1.


def test_held_direct_quantity_change_cannot_be_explained_by_price_nav_or_catalogue_only(held_book):
    x=held_book;x.admitted()
    with pytest.raises(inputs.HeldLineageUnavailable,match="DIRECT_ACTUAL_HELD_QUANTITY"):
        x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":x.guard("2023-01-05",processed_event_fingerprints=["CASH_EVENT"])})


def test_held_positive_weight_zero_units_does_not_silently_drop_domain(held_book):
    x=held_book;x.admitted()
    with pytest.raises(inputs.HeldLineageUnavailable,match="DIRECT_ACTUAL_HELD_QUANTITY"):
        x.book.qualified_proofs(x.ctx("2023-01-05",units=0.,weight=.1),{"A":x.guard("2023-01-05")})


def test_held_clear_then_reentry_needs_new_causal_seed_and_position_id(held_book):
    x=held_book;old=x.admitted()
    x.book.observe_fills(x.fill(q=1.,before=1.,side="SELL",order="O2",signal="2023-01-04",day="2023-01-05"))
    assert x.book.qualified_proofs(x.ctx("2023-01-05",units=0.,weight=0.),{"A":x.guard("2023-01-05")})=={}
    assert x.book.held_assets==() and len(x.book.closed_positions)==1
    with pytest.raises(inputs.HeldLineageUnavailable,match="SEED_MISSING"):
        x.book.observe_fills(x.fill(order="O3",signal="2023-01-05",day="2023-01-06"))
    x.book.note_qualified_decision("2023-01-05",{"A":x.seed("2023-01-05")})
    x.book.observe_fills(x.fill(order="O3",signal="2023-01-05",day="2023-01-06"))
    proof=x.book.qualified_proofs(x.ctx("2023-01-06"),{"A":x.guard("2023-01-06")})["A"]
    assert proof["position_id"]!=old["position_id"] and proof["seed_admitted_at"]=="2023-01-06"


def test_held_terminal_uses_typed_owner_zero_and_leaves_rights_to_original_owner(held_book):
    x=held_book;x.admitted();t=x.transition(kind="TERMINAL",after=0.)
    guard=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t])
    assert x.book.qualified_proofs(x.ctx("2023-01-05",units=0.,weight=0.),{"A":guard})=={}
    assert x.book.closed_positions[0]["closing_quantity_binding"]["source_transition"]["kind"]=="TERMINAL"
    assert not hasattr(x.book,"cash") and not hasattr(x.book,"receivables")


def test_held_empty_account_and_missing_previous_or_pending_guard(held_book):
    x=held_book
    assert x.book.qualified_proofs(x.ctx(units=0.,weight=0.),{})=={}
    assert x.book.held_assets==()
    x.book.note_qualified_decision("2023-01-04",{"A":x.seed("2023-01-04")})
    x.book.observe_fills(x.fill(order="O2",signal="2023-01-04",day="2023-01-05"))
    with pytest.raises(inputs.HeldLineageUnavailable,match="GUARD_DOMAIN"):
        x.book.qualified_proofs(x.ctx("2023-01-05"),{})
    assert x.book.pending_fill_count==1



def test_held_required_guard_assets_is_read_only_for_empty_pending_and_previous(held_book):
    x=held_book
    assert x.book.required_guard_assets(x.ctx(units=0.,weight=0.))==()
    x.book.note_qualified_decision("2023-01-03",{"A":x.seed()});x.book.observe_fills(x.fill())
    assert x.book.required_guard_assets(x.ctx(units=0.,weight=0.))==("A",)
    assert x.book.pending_fill_count==1 and x.book.held_assets==()
    x.book.qualified_proofs(x.ctx(),{"A":x.guard()})
    assert x.book.required_guard_assets(x.ctx("2023-01-05",units=0.,weight=0.))==("A",)


def test_held_typed_terminal_exact_zero_can_close_missing_current_raw_row(held_book):
    x=held_book;x.admitted();t=x.transition(kind="TERMINAL",after=0.)
    g=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t],
              terminal_raw_key_absence=True,raw_key_count=0)
    for key in ("raw_key_session","raw_key_code","raw_exact_key_ref","raw_key_row_identity"):g.pop(key)
    assert x.book.qualified_proofs(x.ctx("2023-01-05",units=0.,weight=0.),{"A":g})=={}
    assert len(x.book.closed_positions)==1


@pytest.mark.parametrize("weight,typed",[(.1,True),(0.,False)])
def test_held_terminal_missing_key_is_not_generic_zero_or_positive_weight_waiver(held_book,weight,typed):
    x=held_book;x.admitted();t=x.transition(kind="TERMINAL",after=0.,typed_event=typed)
    g=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t],
              terminal_raw_key_absence=True,raw_key_count=0)
    with pytest.raises(inputs.HeldLineageUnavailable):
        x.book.qualified_proofs(x.ctx("2023-01-05",units=0.,weight=weight),{"A":g})
    assert x.book.held_assets==("A",)



def test_held_same_typed_share_event_cannot_be_consumed_again_next_session(held_book):
    x=held_book;x.admitted()
    g=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[x.transition()])
    x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":g})
    t=x.transition(day="2023-01-06",before=2.,after=4.)
    g=x.guard("2023-01-06",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t])
    with pytest.raises(inputs.HeldLineageUnavailable,match="DUPLICATE_TYPED_SHARE"):
        x.book.qualified_proofs(x.ctx("2023-01-06",units=4.),{"A":g})
    assert x.book.held_assets==("A",)
    x.book.qualified_proofs(x.ctx("2023-01-06",units=2.),{"A":x.guard("2023-01-06")})


def test_held_missing_typed_ratio_is_source_failure_and_does_not_consume_event(held_book):
    x=held_book;x.admitted();t=x.transition(share_ratio=None)
    g=x.guard("2023-01-05",processed_event_fingerprints=["EVENT_1"],quantity_transitions=[t])
    with pytest.raises(inputs.HeldLineageUnavailable,match="TYPED_SHARE_RATIO") as exc:
        x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":g})
    assert exc.value.receipt["status"]=="BLOCKED_REQUIRED_HELD_IDENTITY"
    g["quantity_transitions"]=[x.transition()]
    proof=x.book.qualified_proofs(x.ctx("2023-01-05",units=2.),{"A":g})["A"]
    assert proof["quantity_transition_refs"][0]["event_fingerprint"]=="EVENT_1"



@pytest.mark.parametrize("token",[" UNKNOWN "," none "," NaN "])
def test_held_padded_placeholder_is_not_qualified_identity(held_book,token):
    x=held_book;seed=x.seed();seed['share_class']=token
    with pytest.raises(inputs.HeldLineageUnavailable,match="IDENTITY_FIELD"):
        x.book.note_qualified_decision("2023-01-03",{"A":seed})


def test_held_source_lineages_copies_pending_seed_without_admitting_position(held_book):
    x=held_book;x.book.note_qualified_decision("2023-01-03",{"A":x.seed()});x.book.observe_fills(x.fill())
    view=x.book.source_lineages();item=view['A'][0]
    assert item['role']=='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED' and item['position_id'] is None
    assert item['committed_prior_raw_quantity'] is None and x.book.held_assets==()
    assert item['seed']['historical_source_epoch']=='ORIGINAL_OBSERVED_UID_EPOCH'
    item['identity']['security_id']='FOREIGN'
    assert x.book.source_lineages()['A'][0]['identity']['security_id']=='CUSIP_A'
    assert x.book.pending_fill_count==1


def test_held_source_lineages_pending_sell_then_reentry_preserves_both_spells(held_book):
    x=held_book;proof=x.admitted();x.book.note_qualified_decision("2023-01-04",{"A":x.seed("2023-01-04")})
    sell=x.fill(q=1.,before=1.,side="SELL",order="O2",signal="2023-01-04",day="2023-01-05")
    buy=x.fill(q=2.,before=0.,order="O3",signal="2023-01-04",day="2023-01-05")
    x.book.observe_fills(pd.concat([sell,buy],ignore_index=True))
    records=x.book.source_lineages()['A']
    assert len(records)==2 and records[0]['position_id']==proof['position_id']
    assert records[0]['committed_prior_raw_quantity']==1.
    assert records[0]['pending_fill_refs'][0]['actual_owner_fill']['side']=='SELL'
    assert records[1]['role']=='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED'
    assert records[1]['seed']['signal_session']=='2023-01-04'
    assert records[1]['pending_fill_refs'][0]['actual_owner_fill']['side']=='BUY'
    new=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),{'A':x.guard('2023-01-05')})['A']
    assert new['position_id']!=proof['position_id']

@pytest.fixture
def causal(example, monkeypatch):
    class Interface:
        def __init__(self): self.pins=[]
        def pin(self,ref): self.pins.append(dict(ref)); return ref['path']
    example.provider.interface=Interface()
    identities={a:dict(security_id='UID_'+a,security_id_type='SYNTHETIC',cusip='CUSIP_'+a,
        share_class='COM',raw_code=a,raw_actual_share_coordinate='RAW_ACTUAL_SHARE') for a in example.provider.master_assets}
    reference=dict(path='D:/synthetic/owner.py',sha256='a'*64)
    class Sources:
        binding=dict(fill_owner_ref=reference,lineage_rule_ref=reference)
        def session(self,ctx,original,book):
            domain=inputs.causal_held_domain(ctx,original['mask'])
            seeds={a:dict(identities[a],qualified=True,historical_observations_relabelled=False,
                identity_asof=ctx.signal_asof.isoformat(),seed_source_ref=reference,
                seed_source_row_identity='ROW_'+a,historical_source_epoch='EPOCH_'+a)
                for a in domain['assets'] if a in original['record']['assets']}
            return dict(domain=domain,entry_seeds=seeds,held_guards={},current_identities=identities,
                historical_source_epochs={a:'EPOCH_'+a for a in identities},source_receipt={'synthetic':True})
        def observe_owner_transitions(self,payload,account_id): pass
    supplemental=dict(schema='B_APPROVED_SINGLE_LW_PUBLISHED_STATE_R1',status='PASS_APPROVED_SINGLE_LW_STATE',family='LW',
        assets=['OUT','B','A'],asset_uids={a:'UID_'+a for a in identities},
        asset_epochs={a:'FIT_EPOCH_'+a if a=='OUT' else 'EPOCH_'+a for a in identities},
        historical_source_epochs={a:'EPOCH_'+a for a in identities},
        as_of=inputs.producer._clock('2023-01-03').isoformat(),cutoff=inputs.producer._clock('2022-12-30').isoformat(),
        state_available_at=inputs.producer._clock('2023-01-03').isoformat(),risk_state_id='NEW_APPROVED',
        method='APPROVED_LW',recipe_sha256='c'*64,typed_state_content_sha256='f'*64,
        state_ref=dict(path='D:/synthetic/single.joblib',sha256='d'*64),producer_ref=reference,
        original_primary_dependency_epoch=dict(event_id='PRIMARY_0',signature_sha256=example.components['support']['events'][0]['dependency_local_signature_sha256']['PRIMARY']))
    contract=dict(binding=dict(ordered_assets=supplemental['assets'],asset_uids=supplemental['asset_uids'],
        current_authority_epochs=supplemental['asset_epochs'],historical_source_epochs=supplemental['historical_source_epochs'],
        current_identity_asof=supplemental['as_of'],history_cutoff=supplemental['cutoff'],
        held_lineages={'OUT':dict(uid='UID_OUT',share_class='COM',raw_code='OUT')}))
    state=SimpleNamespace(risk_state_id='NEW_APPROVED',assets=tuple(supplemental['assets']),method='APPROVED_LW',
        status='PASS_FROZEN_HISTORY_MECHANISM',as_of=supplemental['as_of'],cutoff=supplemental['cutoff'],
        covariance=np.array([[4.,.3,.2],[.3,1.,.25],[.2,.25,4.]]),
        coverage={a:dict(uid=supplemental['asset_uids'][a],identity_epoch=supplemental['asset_epochs'][a]) for a in identities},
        notes={'estimator_lineage':{'family':'LW','recipe_sha256':'c'*64}})
    from scripts.research.a2.portfolio import shared_joint_adapter_r2
    monkeypatch.setattr(shared_joint_adapter_r2,'risk_state_sha256',lambda x:'f'*64)
    calls=[]
    adapter=inputs.CausalHeldLWInputs(base=example.provider,account_id='NEW_ACCOUNT',sources=Sources(),
        supplemental=supplemental,source_contract=contract,references={'supplemental_lw_state_ref':reference},
        reuse_rule=deepcopy(inputs.CAUSAL_LW_REUSE_RULE),state_loader=lambda r:(calls.append(r),state)[1])
    def proofs(ctx,guards):
        return {'OUT':dict(position_id='NEW_ACCOUNT_POSITION_NOT_FIT_EPOCH',security='UID_OUT')}
    # The pure book already has its own source/quantity synthetic tests. These
    # fixtures isolate composition and immutable risk role guards, not admission.
    monkeypatch.setattr(adapter.book,'qualified_proofs',proofs)
    return SimpleNamespace(adapter=adapter,example=example,state=state,calls=calls,identities=identities)


def test_causal_simple_domain_and_decision_never_deserialize_risk(causal):
    ctx=causal.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    domain=causal.adapter.qualified_causal_domain(ctx)
    assert domain['assets']==('OUT','A')
    assert domain['decision_mask'].tolist()==[True,False,True]
    assert domain['buy_allowed'].tolist()==[False,True,True]
    causal.adapter.note_qualified_decision(ctx,domain)
    assert causal.calls==[] and causal.adapter.loads_count==0


def test_complete_original_primary_is_selected_first(causal):
    ctx=causal.example.context()
    domain=causal.adapter.qualified_causal_domain(ctx)
    result=causal.adapter.for_required_domain(ctx,domain)
    assert result.source_receipt['selected_state_role']=='COMPLETE_ORIGINAL_PRIMARY_FIRST'
    assert result.assets==('B','A') and causal.calls==[]


def test_fallback_retains_all_cross_terms_and_separate_new_position_role(causal):
    ctx=causal.example.context(units=(1.,1.,0.),weights=(.1,.1,0.))
    domain=causal.adapter.qualified_causal_domain(ctx)
    result=causal.adapter.for_required_domain(ctx,domain)
    np.testing.assert_array_equal(result.covariance,causal.state.covariance)
    assert result.assets==('OUT','B','A') and causal.adapter.supplemental_loads_count==1
    bridge=result.source_receipt['current_held_role_bridges']['OUT']
    assert bridge['runtime_actual_position_id']!='FIT_EPOCH_OUT'
    assert bridge['immutable_fit_asof_epoch']=='FIT_EPOCH_OUT'
    assert not result.covariance.flags.writeable
    causal.adapter.for_required_domain(ctx,domain)
    assert len(causal.calls)==1


@pytest.mark.parametrize('defect,reason',[
    ('future','CAUSAL_APPROVED_STATE_CLOCK'),('primary','EXPIRED_AT_NEXT'),
    ('axis','REQUIRED_AXIS_UNAVAILABLE'),('historical','HISTORICAL_SUPPORT_ROLE'),
    ('uid','SECURITY_AND_HISTORICAL'),('class','FIT_ASOF_TO_CURRENT'),('epoch_role','EPOCH_ROLES')])
def test_supplement_source_guards_fail_before_deserialization(causal,defect,reason):
    ctx=causal.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    domain=causal.adapter.qualified_causal_domain(ctx); state=causal.adapter.supplemental
    if defect=='future': state['state_available_at']=inputs.producer._clock('2023-01-04').isoformat()
    elif defect=='primary': state['original_primary_dependency_epoch']['event_id']='NEXT_PRIMARY'
    elif defect=='axis':
        state['assets'].remove('OUT'); causal.adapter.source_contract['binding']['ordered_assets'].remove('OUT')
        for key,target in [('asset_uids','asset_uids'),('asset_epochs','current_authority_epochs'),('historical_source_epochs','historical_source_epochs')]:
            state[key].pop('OUT'); causal.adapter.source_contract['binding'][target].pop('OUT')
    elif defect=='historical': causal.adapter._last['source']['historical_source_epochs']['OUT']='CHANGED'
    elif defect=='uid': causal.identities['OUT']['security_id']='OTHER'
    elif defect=='class': causal.identities['OUT']['share_class']='OTHER'
    else: state['asset_epochs']['OUT']='NEW_ACCOUNT_POSITION_NOT_FIT_EPOCH'
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match=reason):
        causal.adapter.for_required_domain(ctx,domain)
    assert causal.calls==[]


def test_ff48_only_change_does_not_expire_primary_fallback(causal):
    ctx=causal.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    d=causal.adapter.qualified_causal_domain(ctx)
    causal.adapter._last['original']['event']['event_id']='FF48_ONLY_OVERALL_EVENT'
    causal.adapter._last['original']['event']['dependency_local_event_ids']['FF48']='NEW_FF48'
    causal.adapter.for_required_domain(ctx,d)
    assert len(causal.calls)==1


def test_qualified_domain_cannot_be_reused_for_changed_actual_holdings(causal):
    ctx=causal.example.context(); d=causal.adapter.qualified_causal_domain(ctx)
    ctx.current_units[0,0]=1.
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match='ALREADY_QUALIFIED'):
        causal.adapter.for_required_domain(ctx,d)
    assert causal.calls==[]


def test_literal_prohibited_drive_is_rejected_before_interface_io():
    class Interface:
        def pin(self,r): pytest.fail('must not perform I/O')
    for path in ('E:/x','F:/x','C:/x'):
        with pytest.raises(inputs.HeldLineageUnavailable):
            inputs._causal_pin(Interface(),dict(path=path,sha256='a'*64))


@pytest.fixture
def share_guard():
    source=object.__new__(inputs.FrozenHeldSourceGuards)
    owner=dict(path='D:/synthetic/owner.py',sha256='a'*64)
    source.binding=dict(account_owner_ref=owner,fill_owner_ref=owner,original_event_binding_ref=owner)
    source.base=SimpleNamespace(master_assets=('A',))
    day='2023-01-04'; clock=(pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
    source.unit_effects={'SPLIT_1':dict(known_at=clock,old_ticker='A',new_ticker='A',old_security_id='OWNER_A',
        new_security_id='OWNER_A',typed_kind='FORWARD_SPLIT',quantity_multiplier=2.,unit_before_quantity=1.,unit_after_quantity=2.)}
    source.lifecycle_effects={day:dict(account_id='NEW_ACCOUNT',security_tickers={'OWNER_A':'A'},positions_before={'OWNER_A':3.})}
    ctx=SimpleNamespace(signal_date=pd.Timestamp(day),current_units=np.array([[6.]]))
    spell=dict(committed_prior_raw_quantity=3.,pending_fill_refs=[])
    identity=dict(security_id='UID_A',security_id_type='CUSIP',cusip='UID_A',share_class='COM',raw_code='A',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    return SimpleNamespace(source=source,ctx=ctx,spell=spell,identity=identity,row=dict(fp='SPLIT_1'))


def test_split_uses_direct_preopen_and_no_fill_current_quantity(share_guard):
    x=share_guard; r=x.source._share_transition('A',x.row,x.ctx,x.spell,x.identity)
    assert r['before_raw_quantity']==3. and r['after_raw_quantity']==6.
    assert r['quantity_before_role']=='DIRECT_ORIGINAL_PRE_OPEN_RAW_BEFORE'
    assert r['quantity_after_role']=='DIRECT_CURRENT_RAW_QUANTITY_NO_ASSET_FILLS'
    x.ctx.current_units[0,0]=999.
    r=x.source._share_transition('A',x.row,x.ctx,x.spell,x.identity)
    assert r['after_raw_quantity']==999.  # no factor-created quantity


def test_split_fill_first_after_is_pre_execution_fill_not_close_quantity(share_guard):
    x=share_guard
    x.spell['pending_fill_refs']=[dict(actual_owner_fill=dict(execution_date='2023-01-04',path_id='NEW_ACCOUNT',
        order_id='SELL_1',index_units_before=6.))]
    x.ctx.current_units[0,0]=5.
    r=x.source._share_transition('A',x.row,x.ctx,x.spell,x.identity)
    assert r['after_raw_quantity']==6. and r['actual_quantity_evidence_ref']['order_id']=='SELL_1'


@pytest.mark.parametrize('defect,reason',[
    ('missing_lifecycle','RAW_BEFORE'),('missing_sid','RAW_BEFORE'),('prior','PRIOR_QUANTITY'),
    ('future','CAUSAL_SAME_SECURITY'),('conversion','CONVERSION'),('factor','FACTOR_COMMITMENT')])
def test_split_source_requires_actual_before_and_causal_same_security(share_guard,defect,reason):
    x=share_guard
    if defect=='missing_lifecycle': x.source.lifecycle_effects.clear()
    elif defect=='missing_sid': x.source.lifecycle_effects['2023-01-04']['security_tickers']={}
    elif defect=='prior': x.source.lifecycle_effects['2023-01-04']['positions_before']['OWNER_A']=4.
    elif defect=='future': x.source.unit_effects['SPLIT_1']['known_at']+=pd.Timedelta(seconds=1)
    elif defect=='conversion': x.source.unit_effects['SPLIT_1']['typed_kind']='CONVERSION'
    else: x.source.unit_effects['SPLIT_1']['unit_after_quantity']=3.
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):
        x.source._share_transition('A',x.row,x.ctx,x.spell,x.identity)
@pytest.mark.parametrize('kind',['SIMPLE_FEASIBLE','JOINT_REUSE'])
def test_real_runner_public_api_consumes_real_causal_adapter(causal,kind):
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext
    ctx=AccountContext(signal_index=1,signal_date=pd.Timestamp('2023-01-03'),
        signal_asof=inputs.producer._clock('2023-01-03'),path_ids=('NEW_ACCOUNT',),
        tickers=np.array(causal.example.provider.master_assets),current_units=np.array([[1.,0.,0.]]),
        current_weights=np.array([[.1,0.,0.]]),cash=np.array([90.]),cash_weight=np.array([.9]),nav=np.array([100.]),
        reserved_mask=np.zeros((1,3),bool),reserved_weight=np.array([0.]),reserved_slots=np.array([0]),
        available_budget=np.array([1.]),available_slots=np.array([20]),
        buy_allowed=np.ones((1,3),bool),sell_restricted=np.zeros((1,3),bool),
        input_present=np.ones((1,3),bool),decision_mask=np.ones((1,3),bool),
        operational_mask=np.zeros((1,3),bool),max_positions=20,max_weight=.1,max_invested=1.)
    forecasts=SimpleNamespace(for_decision=lambda day,assets,*args,**kw: SimpleNamespace(
        assets=tuple(assets),mean=np.arange(len(assets),dtype=float),uncertainty=np.ones(len(assets)),source_receipt={}))
    result=causal_policy_decision(kind,ctx,causal.adapter,forecasts)
    assert result['domain_receipt']['schema']=='B_CAUSAL_CURRENT_REQUIRED_DOMAIN_V1'
    assert result['columns'].tolist()==[0,1,2]
    assert causal.adapter._last['domain']['pool_mask'].tolist()==[False,True,True]
    assert not causal.adapter._last['domain']['pool_mask'].flags.writeable
    assert causal.adapter.supplemental_loads_count==(0 if kind=='SIMPLE_FEASIBLE' else 1)
@pytest.fixture
def freeze_metadata(causal,monkeypatch):
    names=('held_support_admission_ref','single_lw_approval_ref','single_lw_preflight_ref',
        'supplemental_lw_state_ref','held_identity_source_binding_ref','runtime_independent_acceptance_ref')
    ref=lambda name:dict(path='D:/synthetic/'+name+'.json',sha256='a'*64)
    refs={n:ref(n) for n in names}; identity=ref('identity'); proposal=ref('proposal'); execution=ref('execution')
    own=dict(path=str(inputs.Path(inputs.__file__).resolve()),sha256='b'*64)
    approval=dict(schema='B_SPECIFIC_SINGLE_LW_HUMAN_APPROVAL_V1',proposal_ref=proposal,
        output_count_max=1,learned_units_max=9,physical_operations_max=14,retry_max=0,
        subsequent_estimate_or_refresh_authorized=False,old_R5_R6_balance_used=False)
    preflight=dict(status='PASS_SOURCE_NUMERIC_PREFLIGHT_NO_FIT',new_fits=0,budget_reservations=0,contract_ref=identity)
    state=dict(causal.adapter.supplemental,independent=True,actual_exit_code=0,learned_units=9,physical_operations=14,
        inherited_learned_units=0,old_budget_balance_used=False,one_approved_outer_invocation=True,retry_max=0,
        physical_events_started_remaining=0,all_14_cached_result_commitments_verified=True,
        cache_budget_matches_actual_ledger=True,execution_freeze_ref=execution,source_identity_contract_ref=identity)
    accepted=dict(schema='B_CAUSAL_HELD_RUNTIME_INDEPENDENT_ACCEPTANCE_V1',status='PASS_SOURCE_RUNTIME_READY_FOR_PAIRED_REPLAY',
        independent=True,single_lw_state_ref=refs['supplemental_lw_state_ref'],
        held_identity_source_binding_ref=refs['held_identity_source_binding_ref'],producer_source_pins=[own])
    contract=dict(causal.adapter.source_contract,approval_ref=refs['single_lw_approval_ref'],proposal_ref=proposal)
    docs={refs['single_lw_approval_ref']['path']:approval,refs['single_lw_preflight_ref']['path']:preflight,
        refs['supplemental_lw_state_ref']['path']:state,refs['runtime_independent_acceptance_ref']['path']:accepted,
        refs['held_identity_source_binding_ref']['path']:{},refs['held_support_admission_ref']['path']:{},
        execution['path']:dict(approval_ref=refs['single_lw_approval_ref'],proposal_ref=proposal,
            numeric_ref=refs['single_lw_preflight_ref'],identity_contract_ref=identity),identity['path']:contract}
    base=causal.example.provider
    base.interface.read=lambda p:docs[p]
    sources=SimpleNamespace(binding=dict(fill_owner_ref=ref('owner'),lineage_rule_ref=refs['held_support_admission_ref']))
    monkeypatch.setattr(inputs,'FrozenHeldSourceGuards',lambda *args,**kwargs:sources)
    freeze=dict(refs,source_pins=[own],causal_lw_reuse_rule=deepcopy(inputs.CAUSAL_LW_REUSE_RULE),
        accounting_freeze_ref=ref('accounting_freeze'))
    def factory():
        return inputs.CausalHeldLWInputs.from_freeze(freeze=freeze,base_shared=base,account_id='NEW',
            market_dates=base.market_dates,master_assets=base.master_assets,source_context={})
    return SimpleNamespace(factory=factory,accepted=accepted,state=state,approval=approval,
        preflight=preflight,contract=contract,docs=docs,refs=refs,freeze=freeze,causal=causal)


def test_from_freeze_binds_actual_subject_and_only_pins_numeric_artifact(freeze_metadata):
    x=freeze_metadata; adapter=x.factory()
    assert adapter.supplemental_loads_count==0 and adapter._supplement is None
    assert x.causal.calls==[]


@pytest.mark.parametrize('defect,reason',[
    ('state_subject','REVIEWED_STATE'),('source_subject','REVIEWED_STATE'),
    ('exit','TERMINAL_STATE'),('unreviewed','TERMINAL_STATE'),('budget','TERMINAL_STATE'),
    ('started','TERMINAL_STATE'),('source_contract','QUALIFIED_STATE_SOURCE'),
    ('approval','SOURCE_IDENTITY_APPROVAL'),('extra_fit','NO_FURTHER_ESTIMATE'),
    ('execution','STATE_SOURCE_AND_PROPOSAL'),('closure','FREEZE_SOURCE_CLOSURE')])
def test_from_freeze_rejects_wrong_subject_or_authority_before_runtime(freeze_metadata,defect,reason):
    x=freeze_metadata; other=dict(path='D:/synthetic/OTHER.json',sha256='c'*64)
    if defect=='state_subject': x.accepted['single_lw_state_ref']=other
    elif defect=='source_subject': x.accepted['held_identity_source_binding_ref']=other
    elif defect=='exit': x.state['actual_exit_code']=1
    elif defect=='unreviewed': x.state['independent']=False
    elif defect=='budget': x.state['learned_units']=10
    elif defect=='started': x.state['physical_events_started_remaining']=1
    elif defect=='source_contract': x.preflight['contract_ref']=other
    elif defect=='approval': x.contract['approval_ref']=other
    elif defect=='extra_fit': x.approval['subsequent_estimate_or_refresh_authorized']=True
    elif defect=='execution':
        x.docs[x.state['execution_freeze_ref']['path']]['numeric_ref']=other
    else: x.freeze['source_pins']=[]
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match=reason): x.factory()
    assert x.causal.calls==[]


@pytest.fixture
def full_source_guard(monkeypatch):
    days=pd.to_datetime(['2023-01-03','2023-01-04'])
    assets=('OUT','A'); owner=dict(path='D:/synthetic/owner.py',sha256='a'*64)
    source=object.__new__(inputs.FrozenHeldSourceGuards)
    source.descriptor_bridges=()
    source.binding={k:owner for k in ('fill_owner_ref','account_owner_ref','mapping_ref',
        'original_event_binding_ref','static_event_source_ref','source_account_contract_ref','source_manifest_ref')}
    rows=[dict(ticker=a,effective_start=pd.Timestamp('2023-01-03'),effective_end=pd.Timestamp('2023-01-03' if a=='OUT' else '2025-12-31'),
        security_id='UID_'+a,security_id_type='SYNTHETIC',cusip='CUSIP_'+a,issuer_name='ISSUER_'+a,
        title_of_class='COM',moomoo_transport_code=a,mapping_status='RESOLVED',mapping_source='SYNTHETIC',source_filing='SYNTHETIC') for a in assets]
    raw=pd.DataFrame(dict(ticker=assets,trade_date=[days[1]]*2,code=assets))
    audits=pd.DataFrame(columns=inputs.FrozenHeldSourceGuards.AUDIT_COLUMNS)
    calls=[]
    class Reader:
        sources={k:owner for k in ('uid_intervals','raw_open_close','share_ca_audit')}
        def read(self,name,columns,**kwargs):
            calls.append((name,tuple(columns),kwargs))
            return {'uid_intervals':pd.DataFrame(rows),'raw_open_close':raw,'share_ca_audit':audits}[name].copy()
    source.base=SimpleNamespace(master_assets=assets,market_dates=days,_components={'reader':Reader(),'refs':{'source':owner}})
    source.present=np.ones((2,2),bool)
    source.mapping=dict(records=[dict(ticker=a,start='2023-01-03',end='2026-01-01',coordinate='RAW_ACTUAL_SHARE',sid='FROZEN_RAW_TRANSPORT_CODE:'+a) for a in assets],
        basis_by_ticker={a:dict(kind='FROZEN_RAW_TRANSPORT_INSTRUMENT_COORDINATE',source_sid='FROZEN_RAW_TRANSPORT_CODE:'+a,source_ref=owner,not_a_CUSIP_claim=True) for a in assets})
    source.original_events=();source.static_events=();source.share_events=[];source.cash_events=[];source.terminal_events=[]
    source.unsupported=();source.unit_effects={};source.lifecycle_effects={}
    identity=dict(security_id='UID_OUT',security_id_type='SYNTHETIC',cusip='CUSIP_OUT',share_class='COM',raw_code='OUT',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    spell=dict(role='ACCEPTED_POSITION',identity=identity,seed=dict(identity,signal_session='2023-01-03',historical_source_epoch='HIST_OUT'),
        committed_prior_raw_quantity=3.,pending_fill_refs=[])
    book=SimpleNamespace(account_id='SYNTHETIC_ACCOUNT',required_guard_assets=lambda ctx:('OUT',),source_lineages=lambda:{'OUT':(spell,)})
    ctx=SimpleNamespace(tickers=assets,signal_date=days[1],signal_asof=inputs.producer._clock(days[1]),
        current_units=np.array([[3.,0.]]),current_weights=np.array([[.1,0.]]),decision_mask=np.ones((1,2),bool),buy_allowed=np.ones((1,2),bool))
    original=dict(mask=np.array([False,True]),record=dict(asset_uids={'A':'UID_A'},asset_epochs={'A':'EPOCH_A'}))
    return SimpleNamespace(source=source,book=book,ctx=ctx,original=original,rows=rows,raw=raw,
        audits=audits,calls=calls,spell=spell,identity=identity)


def test_source_guard_keeps_expired_entry_membership_separate_from_current_held(full_source_guard):
    x=full_source_guard; result=x.source.session(x.ctx,x.original,x.book)
    assert result['domain']['assets']==('OUT','A')
    assert set(result['entry_seeds'])=={'A'}
    assert result['held_guards']['OUT']['qualified']
    assert result['historical_source_epochs']['OUT']=='HIST_OUT'
    assert all(not set(cols)&{'Open','Close','NAV','price','notional'} for _,cols,_ in x.calls)


@pytest.mark.parametrize('defect,reason',[
    ('mapping','RAW_ACCOUNTING_MAPPING'),('raw','RAW_KEY'),('identity','SECURITY_COORDINATE'),
    ('catalogue','UNSUPPORTED_DECLARED'),('residual','UNSUPPORTED_DECLARED'),('multi','INTERMEDIATE')])
def test_full_source_guard_rejects_source_gaps(full_source_guard,defect,reason):
    x=full_source_guard
    if defect=='mapping': x.source.mapping['records'][0]['sid']='OTHER'
    elif defect=='raw': x.raw.loc[0,'code']='OTHER'
    elif defect=='identity': x.rows[0]['title_of_class']='OTHER'
    elif defect=='catalogue': x.source.original_events=({'ticker':'OUT','event_date':'2023-01-04'},)
    elif defect=='residual': x.source.unsupported=({'ticker':'OUT','effective_date':'2023-01-04'},)
    else: x.source.share_events=[dict(ticker='OUT',day='2023-01-04',fp='SPLIT_1'),dict(ticker='OUT',day='2023-01-04',fp='SPLIT_2')]
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason): x.source.session(x.ctx,x.original,x.book)


def test_future_unit_commitment_is_cached_but_not_current_processed(full_source_guard):
    x=full_source_guard;x.source.share_events=[dict(ticker='OUT',day='2023-01-05',fp='FUTURE')]
    x.source.observe_owner_transitions(dict(role='UNIT_COORDINATE_APPLIED',owner_ref=x.source.binding['account_owner_ref'],
        effective_session='2023-01-05',event_fingerprint='FUTURE',quantity_coordinate='ORIGINAL_OWNER_UNIT_FACTOR_COMMITMENT'), 'NEW')
    result=x.source.session(x.ctx,x.original,x.book)
    assert 'FUTURE' not in result['held_guards']['OUT']['processed_event_fingerprints']
    assert not result['held_guards']['OUT']['quantity_transitions']

def test_nonshare_quote_diagnostic_is_preserved_and_grants_no_quote_authority(full_source_guard):
    x=full_source_guard
    x.source.original_events=({'ticker':'OUT','event_date':'2023-01-04','status':'UNSUPPORTED',
        'reason':'VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY','source_fingerprint':'SYNTHETIC'},)
    x.audits.loc[0]=dict(ticker='OUT',event_date=pd.Timestamp('2023-01-04'),source_event_date=pd.Timestamp('2023-01-04'),
        code='OUT',audit_kind='LARGE_RAW_MOVE_NO_VENDOR_EVENT',share_event=False,manual_wolf=False,aligned_to_next_session=False)
    result=x.source.session(x.ctx,x.original,x.book)
    guard=result['held_guards']['OUT']
    assert len(guard['nonshare_quote_diagnostics'])==2
    assert guard['quote_qualification_granted'] is False
    assert guard['original_account_quote_and_unsupported_gates_unchanged']
    # An actual residual original account unsupported event is still a blocker.
    x.source.unsupported=({'ticker':'OUT','effective_date':'2023-01-04'},)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)


@pytest.mark.parametrize('kind',['FORWARD_SPLIT','REVERSE_SPLIT','OTHER_SHARE_COUNT_TRANSFORM'])
def test_exact_original_same_security_share_kinds_use_owner_commitment(share_guard,kind):
    x=share_guard;x.source.unit_effects['SPLIT_1']['typed_kind']=kind
    assert x.source._share_transition('A',x.row,x.ctx,x.spell,x.identity)['kind']=='SPLIT'


def test_final_book_proof_retains_actual_before_and_after_evidence_roles(held_book):
    x=held_book;x.admitted();owner=x.ref('ca_owner')
    transition=x.transition(quantity_after_role='DIRECT_CURRENT_RAW_QUANTITY_NO_ASSET_FILLS',
        actual_quantity_evidence_ref=dict(owner_ref=owner,session='2023-01-05',actual_raw_quantity=2.,quantity_field='current_units'),
        quantity_before_role='DIRECT_ORIGINAL_PRE_OPEN_RAW_BEFORE',
        actual_before_quantity_evidence_ref=dict(owner_ref=owner,session='2023-01-05',actual_raw_quantity=1.,quantity_field='positions_before'))
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),
        {'A':x.guard('2023-01-05',processed_event_fingerprints=['EVENT_1'],quantity_transitions=[transition])})['A']
    assert len(proof)==22
    row=proof['quantity_transition_refs'][0]
    assert row['quantity_before_role']=='DIRECT_ORIGINAL_PRE_OPEN_RAW_BEFORE'
    assert row['actual_before_quantity_evidence_ref']['actual_raw_quantity']==1.
    assert row['quantity_after_role']=='DIRECT_CURRENT_RAW_QUANTITY_NO_ASSET_FILLS'
    assert row['actual_quantity_evidence_ref']['actual_raw_quantity']==2.
@pytest.mark.parametrize('role',['vendor_share','manual','declared_share'])
def test_cash_same_key_cannot_certify_share_or_manual_source(full_source_guard,role):
    x=full_source_guard
    x.source.cash_events=[dict(ticker='OUT',day='2023-01-04',fp='CASH_ONLY')]
    if role=='declared_share':
        x.source.original_events=({'ticker':'OUT','event_date':'2023-01-04','status':'SHARE_ONLY_SUPPORTED'},)
    else:
        x.audits.loc[0]=dict(ticker='OUT',event_date=pd.Timestamp('2023-01-04'),source_event_date=pd.Timestamp('2023-01-04'),
            code='OUT',audit_kind='VENDOR_CA',share_event=role=='vendor_share',manual_wolf=role=='manual',aligned_to_next_session=False)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)

@pytest.fixture
def issuer_mapping_guard(full_source_guard):
    x=full_source_guard;source=x.source
    class Cash:
        def __init__(self,sid,ticker):self.old_security_id=sid;self.ticker=ticker
        @property
        def event_fingerprint(self):raise AssertionError('Do not read/recompute cash values')
    class Terminal(Cash):pass
    sid='SOURCE_ISSUER_COMMON_CLASS:'+'b'*64
    identity=dict(security_id=sid,identity_kind='SOURCE_DERIVED_ISSUER_COMMON_CLASS',
        issuer='SYNTHETIC ISSUER',ticker='A',listing_identity='NASDAQ:A',security_type='COMMON_STOCK')
    envelope=dict(identity=identity,identity_payload_sha256=content_hash(identity),
        source_reference='https://synthetic.invalid/historical-issuer',source_fingerprint='c'*64,
        available_at='2025-09-05T23:59:59Z',CUSIP_claim=False)
    proof=dict(event_fingerprint='LATE_CASH_LABEL',identity=envelope,
        cash_per_raw_old_share='FORBIDDEN_SENTINEL_NOT_READ',small_cash_predicate='FORBIDDEN_SENTINEL_NOT_READ')
    cashref=dict(path='D:/synthetic/old_cash.joblib',sha256='d'*64)
    source.binding['account_input_refs']={'cash_kwargs':cashref}
    source.mapping['records'][1]['sid']=sid
    source.mapping['basis_by_ticker']['A']=dict(kind='EXACT_REUSED_SOURCE_CASH_ISSUER_CLASS',
        source_sid=sid,source_ref=cashref,not_a_CUSIP_claim=False)
    parent=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',manifest=dict(proofs=[proof]))
    cover=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',security_tickers={sid:'A'},
        manifest=dict(proofs=[],parent_source_binding=parent))
    source.events=dict(entitlement_security_tickers={sid:'A'},entitlement_source_binding=cover)
    source.typed_classes=dict(cash=Cash,terminal=Terminal)
    source.cash_events=[dict(event=Cash(sid,'A'),ticker='A',day='2025-09-22',fp='LATE_CASH_LABEL')]
    return SimpleNamespace(x=x,source=source,sid=sid,identity=identity,envelope=envelope,proof=proof,parent=parent,cover=cover,cashref=cashref)


def test_late_frozen_issuer_accounting_label_preserves_independent_legal_seed(issuer_mapping_guard):
    f=issuer_mapping_guard;x=f.x;before=deepcopy(x.source.mapping)
    result=x.source.session(x.ctx,x.original,x.book)
    seed=result['entry_seeds']['A'];p=seed['accounting_mapping_basis_proof']
    assert seed['security_id']=='UID_A' and seed['cusip']=='CUSIP_A' and seed['raw_code']=='A'
    assert p['mapping_sid']==f.sid and p['raw_code']=='A'
    assert p['identity_representation_proofs'][0]['identity_available_at_as_recorded']=='2025-09-05T23:59:59Z'
    assert p['identity_representation_proofs'][0]['historical_availability_qualified'] is False
    assert all(p[k] is False for k in ('current_security_identity_granted','historical_availability_granted',
        'cash_permission_granted','quote_qualification_granted','terminal_or_settlement_qualification_granted'))
    assert x.source.mapping==before and 'LATE_CASH_LABEL' not in result['held_guards']['OUT']['processed_event_fingerprints']
    assert 'cash_per_raw_old_share' not in str(p) and 'small_cash_predicate' not in str(p)


@pytest.mark.parametrize('defect,reason',[
    ('missing_basis','EXPLICIT_FROZEN'),('unknown_basis','UNKNOWN_FROZEN'),
    ('source_sid','ISSUER_ACCOUNTING_LABEL'),('source_sha','ISSUER_ACCOUNTING_LABEL'),
    ('owner_sid','ISSUER_ACCOUNTING_LABEL'),('owner_duplicate','ISSUER_ACCOUNTING_LABEL'),
    ('event_sid','TYPED_ISSUER'),('missing_proof','TYPED_ISSUER'),('duplicate_proof','TYPED_ISSUER'),
    ('identity_hash','ISSUER_CLASS_NAMESPACE'),('class_prefix','ISSUER_CLASS_NAMESPACE'),
    ('ticker','ISSUER_CLASS_NAMESPACE'),('duplicate_mapping','RAW_ACCOUNTING_MAPPING'),
    ('missing_legal_uid','CURRENT_ENTRY_IDENTITY_CONFLICT'),('conflict_rawcode','CURRENT_ENTRY_IDENTITY_CONFLICT')])
def test_issuer_accounting_label_cannot_replace_exact_sources(issuer_mapping_guard,defect,reason):
    f=issuer_mapping_guard;x=f.x;b=x.source.mapping['basis_by_ticker']['A']
    if defect=='missing_basis':del x.source.mapping['basis_by_ticker']['A']
    elif defect=='unknown_basis':b['kind']='UNKNOWN'
    elif defect=='source_sid':b['source_sid']='OTHER'
    elif defect=='source_sha':b['source_ref']=dict(f.cashref,sha256='e'*64)
    elif defect=='owner_sid':x.source.events['entitlement_security_tickers']={'OTHER':'A'}
    elif defect=='owner_duplicate':x.source.events['entitlement_security_tickers']['OTHER']='A';f.cover['security_tickers']['OTHER']='A'
    elif defect=='event_sid':x.source.cash_events[0]['event'].old_security_id='OTHER'
    elif defect=='missing_proof':f.parent['manifest']['proofs']=[]
    elif defect=='duplicate_proof':f.parent['manifest']['proofs'].append(f.proof)
    elif defect=='identity_hash':f.envelope['identity_payload_sha256']='f'*64
    elif defect=='class_prefix':f.identity['security_type']='AMERICAN_DEPOSITARY_SHARE';f.envelope['identity_payload_sha256']=content_hash(f.identity)
    elif defect=='ticker':f.identity['ticker']='OTHER';f.envelope['identity_payload_sha256']=content_hash(f.identity)
    elif defect=='duplicate_mapping':x.source.mapping['records'].append(deepcopy(x.source.mapping['records'][1]))
    elif defect=='missing_legal_uid':x.original['record']['asset_uids']['A']='OTHER'
    else:x.raw.loc[1,'code']='OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):x.source.session(x.ctx,x.original,x.book)


def test_issuer_ads_namespace_is_preserved_without_common_share_substitution(issuer_mapping_guard):
    f=issuer_mapping_guard;old=f.sid;sid='SOURCE_ISSUER_ADS_CLASS:'+'b'*64
    f.source.mapping['records'][1]['sid']=sid;f.source.mapping['basis_by_ticker']['A']['source_sid']=sid
    f.source.events['entitlement_security_tickers']={sid:'A'};f.cover['security_tickers']={sid:'A'}
    f.source.cash_events[0]['event'].old_security_id=sid
    f.identity.update(security_id=sid,security_type='AMERICAN_DEPOSITARY_SHARE')
    f.envelope['identity_payload_sha256']=content_hash(f.identity)
    result=f.source.session(f.x.ctx,f.x.original,f.x.book)
    assert result['entry_seeds']['A']['security_id']=='UID_A'
    assert result['entry_seeds']['A']['accounting_mapping_basis_proof']['mapping_sid']==sid


@pytest.mark.parametrize('defect',['sid','basis_sid','raw_source','cusip_claim'])
def test_transport_basis_requires_its_exact_frozen_raw_commitment(full_source_guard,defect):
    x=full_source_guard;b=x.source.mapping['basis_by_ticker']['A']
    if defect=='sid':x.source.mapping['records'][1]['sid']='OTHER'
    elif defect=='basis_sid':b['source_sid']='OTHER'
    elif defect=='raw_source':b['source_ref']=dict(path='D:/synthetic/other.parquet',sha256='e'*64)
    else:b['not_a_CUSIP_claim']=False
    with pytest.raises(inputs.HeldLineageUnavailable,match='RAW_ACCOUNTING_MAPPING'):x.source.session(x.ctx,x.original,x.book)


@pytest.fixture
def direct_legal_mapping_guard(full_source_guard):
    x=full_source_guard;source=x.source;sid='CUSIP:123456789'
    x.rows[1].update(security_id='123456789',security_id_type='CUSIP',cusip='123456789')
    x.original['record']['asset_uids']['A']='123456789'
    source.mapping['records'][1]['sid']=sid
    source.mapping['basis_by_ticker']['A']=dict(kind='FROZEN_POST_VERIFIED_CUSIP_SPLIT_AND_TERMINAL_BINDING',
        proof=dict(path='D:/synthetic/frozen_postverified.json',sha256='e'*64))
    source.events=dict(entitlement_security_tickers={sid:'A'},
        entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',security_tickers={sid:'A'}))
    return x


def test_existing_cusip_label_uses_only_direct_legal_uid_and_owner_coordinate(direct_legal_mapping_guard):
    x=direct_legal_mapping_guard
    # Future/unsupported corporate actions remain separate from this label.
    x.source.unsupported=({'ticker':'A','effective_date':'2025-01-03'},)
    result=x.source.session(x.ctx,x.original,x.book)
    seed=result['entry_seeds']['A'];p=seed['accounting_mapping_basis_proof']
    assert seed['security_id']=='123456789' and p['mapping_sid']=='CUSIP:123456789'
    assert p['bridge']=='DIRECT_CURRENT_LEGAL_ID_ACCOUNTING_COORDINATE'
    assert p['postverified_basis_proof_not_consumed'] is True
    assert p['terminal_or_settlement_qualification_granted'] is False
    assert p['cash_permission_granted'] is False
    assert x.source.unsupported==({'ticker':'A','effective_date':'2025-01-03'},)


@pytest.mark.parametrize('defect',['legal_type','cusip','row_sid','raw_code'])
def test_cusip_accounting_bridge_cannot_create_identity(direct_legal_mapping_guard,defect):
    x=direct_legal_mapping_guard
    if defect=='legal_type':x.rows[1]['security_id_type']='OTHER'
    elif defect=='cusip':x.rows[1]['cusip']='987654321'
    elif defect=='row_sid':x.source.mapping['records'][1]['sid']='CUSIP:987654321'
    else:x.raw.loc[1,'code']='OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable,match='DIRECT_CURRENT_LEGAL|CURRENT_ENTRY_IDENTITY|SID_CUSIP_CONFLICT'):
        x.source.session(x.ctx,x.original,x.book)



def test_original_cash_identity_ascii_commitment_is_not_typed_state_hash(issuer_mapping_guard):
    import hashlib,json
    f=issuer_mapping_guard;f.identity['issuer']='SYNTHETIC_ISSUER_日本'
    original_hash=hashlib.sha256(json.dumps(f.identity,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str).encode()).hexdigest()
    assert original_hash!=content_hash(f.identity)
    f.envelope['identity_payload_sha256']=original_hash
    result=f.source.session(f.x.ctx,f.x.original,f.x.book)
    assert result['entry_seeds']['A']['accounting_mapping_basis_proof']['identity_representation_proofs'][0]['identity_payload_sha256']==original_hash


@pytest.mark.parametrize('unrelated_cash',['absent','different_sid','duplicate_ticker','unqualified_cash'])
def test_direct_legal_cusip_label_has_no_unused_cash_namespace_dependency(direct_legal_mapping_guard,unrelated_cash):
    x=direct_legal_mapping_guard
    if unrelated_cash=='absent':x.source.events={}
    elif unrelated_cash=='different_sid':x.source.events=dict(entitlement_security_tickers={'CUSIP:987654321':'A'})
    elif unrelated_cash=='duplicate_ticker':x.source.events=dict(entitlement_security_tickers={'CUSIP:123456789':'A','CUSIP:987654321':'A'})
    else:x.source.events=dict(entitlement_source_binding={'status':'UNQUALIFIED'})
    result=x.source.session(x.ctx,x.original,x.book)
    seed=result['entry_seeds']['A'];p=seed['accounting_mapping_basis_proof']
    assert seed['security_id']=='123456789' and p['mapping_sid']=='CUSIP:123456789'
    assert p['cash_permission_granted'] is False and p['terminal_or_settlement_qualification_granted'] is False
    assert p['current_security_identity_granted'] is False and p['historical_availability_granted'] is False
    assert p['postverified_basis_proof_not_consumed'] is True


@pytest.mark.parametrize('defect',['missing_uid','unknown_uid','no_mapping','duplicate_mapping','wrong_coordinate'])
def test_literal_cusip_label_still_requires_independent_current_legal_source(direct_legal_mapping_guard,defect):
    x=direct_legal_mapping_guard;x.source.events={}
    if defect=='missing_uid':x.rows.pop(1)
    elif defect=='unknown_uid':x.rows[1]['security_id']='UNKNOWN';x.original['record']['asset_uids']['A']='UNKNOWN'
    elif defect=='no_mapping':x.source.mapping['records'].pop(1)
    elif defect=='duplicate_mapping':x.source.mapping['records'].append(deepcopy(x.source.mapping['records'][1]))
    else:x.source.mapping['records'][1]['coordinate']='ADJUSTED_SHARE'
    with pytest.raises(inputs.HeldLineageUnavailable):x.source.session(x.ctx,x.original,x.book)


@pytest.mark.parametrize('actual_blocker',['unsupported','declared_share','terminal_without_effect'])
def test_direct_cusip_label_does_not_admit_unknown_held_corporate_actions(full_source_guard,actual_blocker):
    x=full_source_guard;sid='CUSIP:123456789';identity=dict(x.identity,security_id='123456789',security_id_type='CUSIP',cusip='123456789')
    x.rows[0].update(security_id='123456789',security_id_type='CUSIP',cusip='123456789')
    x.spell['identity']=identity;x.spell['seed'].update(identity)
    x.source.mapping['records'][0]['sid']=sid
    x.source.mapping['basis_by_ticker']['OUT']=dict(kind='FROZEN_POST_VERIFIED_CUSIP_SPLIT_AND_TERMINAL_BINDING',
        proof=dict(path='D:/synthetic/frozen_postverified.json',sha256='e'*64))
    x.source.events={}
    if actual_blocker=='unsupported':x.source.unsupported=({'ticker':'OUT','effective_date':'2023-01-04'},)
    elif actual_blocker=='declared_share':x.source.original_events=({'ticker':'OUT','event_date':'2023-01-04','status':'SHARE_ONLY_SUPPORTED'},)
    else:x.source.terminal_events=[dict(ticker='OUT',day='2023-01-04',fp='UNKNOWN_TERMINAL',event=SimpleNamespace(old_security_id='123456789'))]
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED|TERMINAL'):
        x.source.session(x.ctx,x.original,x.book)


@pytest.mark.parametrize('separate_callbacks', [False, True])
def test_original_target_order_sell_buy_legs_preserve_tiny_buy_and_chain(held_book, separate_callbacks):
    x=held_book; old=x.admitted()
    x.book.note_qualified_decision('2023-01-04', {'A':x.seed('2023-01-04')})
    sell=x.fill(q=.25,before=1.,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    buy=x.fill(q=1e-12,before=.75,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    if separate_callbacks:
        assert x.book.observe_fills(sell)==1
        assert x.book.observe_fills(buy)==1
    else:
        assert x.book.observe_fills(pd.concat([sell,buy],ignore_index=True))==2
    rows=x.book.source_lineages()['A'][0]['pending_fill_refs']
    assert [r['actual_owner_fill']['side'] for r in rows]==['SELL','BUY']
    assert [r['actual_owner_fill']['order_id'] for r in rows]==['O2','O2']
    assert rows[1]['actual_owner_fill']['fractional_shares']==1e-12
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=.75+1e-12),{'A':x.guard('2023-01-05')})['A']
    assert proof['position_id']==old['position_id']
    assert [r['side'] for r in proof['quantity_transition_refs']]==['SELL','BUY']
    assert proof['quantity_transition_refs'][0]['after_raw_quantity']==proof['quantity_transition_refs'][1]['before_raw_quantity']
    assert proof['quantity_transition_refs'][1]['raw_quantity']==1e-12


@pytest.mark.parametrize('separate_callbacks', [False, True])
def test_original_same_target_close_reentry_has_distinct_position_spell(held_book, separate_callbacks):
    x=held_book; old=x.admitted()
    x.book.note_qualified_decision('2023-01-04',{'A':x.seed('2023-01-04')})
    sell=x.fill(q=1.,before=1.,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    buy=x.fill(q=2.,before=0.,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    if separate_callbacks:
        x.book.observe_fills(sell);x.book.observe_fills(buy)
    else:x.book.observe_fills(pd.concat([sell,buy],ignore_index=True))
    lineages=x.book.source_lineages()['A']
    assert len(lineages)==2 and lineages[0]['position_id']==old['position_id']
    assert lineages[1]['role']=='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED'
    new=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),{'A':x.guard('2023-01-05')})['A']
    assert new['position_id']!=old['position_id']
    assert x.book.closed_positions[-1]['position_id']==old['position_id']
    assert new['seed_admitted_at']=='2023-01-05'
    assert new['seed_source_row_identity']==old['seed_source_row_identity']
    assert [r['order_id'] for r in new['quantity_transition_refs']]==['O2','O2']
    assert [r['side'] for r in new['quantity_transition_refs']]==['SELL','BUY']


@pytest.mark.parametrize('defect,reason', [
    ('same_side','DUPLICATE_ACTUAL_FILL_LEG'),
    ('reverse','ACTUAL_FILL_LEG_SEQUENCE_CONFLICT'),
    ('ticker','ACTUAL_FILL_ORDER_IDENTITY_CONFLICT'),
    ('signal','ACTUAL_FILL_ORDER_IDENTITY_CONFLICT'),
    ('execution','ACTUAL_FILL_ORDER_IDENTITY_CONFLICT'),
    ('path','CROSS_ACCOUNT_FILL_REJECTED'),
    ('chain','ACTUAL_FILL_LEG_QUANTITY_CHAIN_CONFLICT'),
])
@pytest.mark.parametrize('single_frame', [False, True])
def test_original_order_leg_conflicts_are_atomic(held_book, defect, reason, single_frame):
    x=held_book;x.admitted();x.book.note_qualified_decision('2023-01-04',{'A':x.seed('2023-01-04')})
    first=x.fill(q=.25,before=1.,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    second=x.fill(q=.1,before=.75,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    if defect=='same_side':second=x.fill(q=.1,before=.75,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    elif defect=='reverse':
        first=x.fill(q=.1,before=1.,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
        second=x.fill(q=.1,before=1.1,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    elif defect=='ticker':second.loc[0,'ticker']='B'
    elif defect=='signal':second.loc[0,'signal_date']='2023-01-03'
    elif defect=='execution':second.loc[0,'execution_date']='2023-01-06'
    elif defect=='path':second.loc[0,'path_id']='OTHER_ACCOUNT'
    else:second=x.fill(q=.1,before=.76,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    if not single_frame:x.book.observe_fills(first)
    before=deepcopy((x.book._orders,x.book._pending,x.book._candidates,x.book._positions))
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):
        x.book.observe_fills(pd.concat([first,second],ignore_index=True) if single_frame else second)
    assert (x.book._orders,x.book._pending,x.book._candidates,x.book._positions)==before
    assert x.book.pending_fill_count==(0 if single_frame else 1)
    if single_frame:assert x.book.observe_fills(first)==1


def test_original_target_third_leg_or_reused_date_cannot_reenter(held_book):
    x=held_book;x.admitted();x.book.note_qualified_decision('2023-01-04',{'A':x.seed('2023-01-04')})
    sell=x.fill(q=.25,before=1.,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    buy=x.fill(q=.1,before=.75,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    x.book.observe_fills(pd.concat([sell,buy],ignore_index=True))
    before=deepcopy((x.book._orders,x.book._pending))
    third=x.fill(q=.1,before=.85,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    with pytest.raises(inputs.HeldLineageUnavailable,match='DUPLICATE_ACTUAL_FILL_LEG'):x.book.observe_fills(third)
    assert (x.book._orders,x.book._pending)==before
    x.book.qualified_proofs(x.ctx('2023-01-05',units=.85),{'A':x.guard('2023-01-05')})
    x.book.note_qualified_decision('2023-01-05',{'A':x.seed('2023-01-05')})
    later=x.fill(q=.1,before=.85,side='SELL',order='O2',signal='2023-01-05',day='2023-01-06')
    with pytest.raises(inputs.HeldLineageUnavailable,match='ACTUAL_FILL_ORDER_IDENTITY_CONFLICT'):x.book.observe_fills(later)
    assert x.book.pending_fill_count==0


def test_original_valid_leg_pair_then_bad_row_leaves_all_new_orders_unconsumed(held_book):
    x=held_book;x.admitted();x.book.note_qualified_decision('2023-01-04',{'A':x.seed('2023-01-04')})
    sell=x.fill(q=.25,before=1.,side='SELL',order='O2',signal='2023-01-04',day='2023-01-05')
    buy=x.fill(q=.1,before=.75,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    bad=x.fill(q=.1,before=.85,side='BUY',order='O2',signal='2023-01-04',day='2023-01-05')
    before=deepcopy((x.book._orders,x.book._pending,x.book._candidates))
    with pytest.raises(inputs.HeldLineageUnavailable,match='DUPLICATE_ACTUAL_FILL_LEG'):
        x.book.observe_fills(pd.concat([sell,buy,bad],ignore_index=True))
    assert (x.book._orders,x.book._pending,x.book._candidates)==before
    assert x.book.observe_fills(pd.concat([sell,buy],ignore_index=True))==2



@pytest.fixture
def original_boundary_guard(full_source_guard,monkeypatch):
    """Real constructor and observer; every source here is synthetic metadata."""
    x=full_source_guard; old=x.source
    owner=old.binding['account_owner_ref']; convention=dict(path='D:/synthetic/convention.json',sha256='b'*64)
    static=dict(path='D:/synthetic/static_events.py',sha256='c'*64)
    binding=dict(old.binding,schema=inputs.HELD_RUNTIME_BINDING_SCHEMA,
        date_start='2023-01-03',date_stop_exclusive='2026-01-01',strict_PIT=False,
        production_qualified=False,quote_qualified=False,certified_NAV=False,
        static_event_source_ref=static,lineage_rule_ref=owner,typed_ca_owner_ref=owner,
        account_input_refs={'cash_kwargs':owner},
        legacy_input_code_ref_role='INHERITED_LOGICAL_COMMITMENT_NOT_CURRENT_EXECUTION_SOURCE; preserve original loader/custody resolution')
    event=dict(ticker='OUT',effective_date='2023-01-04',
        reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',
        source_reference='D:/synthetic/vendor-event.json',source_fingerprint='e'*64)
    mapping=dict(old.mapping,coordinate='RAW_ACTUAL_SHARE',role='ACCOUNTING_MAPPING_ONLY')
    calls=[]
    class Interface:
        def pin(self,ref):calls.append(('pin',dict(ref)));return ref['path']
        def read(self,path):
            assert path==owner['path']
            # The original event and mapping deliberately share a synthetic ref;
            # no market, cash rate, price, serialized state or account is read.
            return dict(mapping,event_records=[dict(ticker='OUT',event_date='2023-01-04',
                status='UNSUPPORTED',reason=event['reason'],source_fingerprint=event['source_fingerprint'])])
    x.source.base.interface=Interface()
    class Cash:pass
    class Terminal(Cash):pass
    original_read=inputs.Path.read_text
    def static_only(path,*args,**kwargs):
        if str(path).replace('\\','/')==static['path']:
            return 'def frozen_evidence_records():\n    records=[]\n    return records\n'.replace('\\n','\n')
        return original_read(path,*args,**kwargs)
    monkeypatch.setattr(inputs.Path,'read_text',static_only)
    rows=[]
    context=dict(owner_ref=owner,input_refs=binding['account_input_refs'],
        source_account_contract_ref=binding['source_account_contract_ref'],
        market_dates=tuple(old.base.market_dates),master_assets=old.base.master_assets,
        raw_row_present=old.present,events=dict(corporate_actions=(),entitlement_events=(),unsupported_events=(event,)),
        typed_ca_owner_ref=owner,typed_entitlement_classes=dict(cash=Cash,terminal=Terminal),
        account_boundary_context=dict(account_id=x.book.account_id,owner_ref=owner,convention_ref=convention,rows=rows))
    x.source=inputs.FrozenHeldSourceGuards(old.base,binding,context,
        account_id=x.book.account_id,accounting_freeze_ref=convention)
    assert x.source.unit_effects=={} and x.source.lifecycle_effects=={}
    # This position was bought after PRE_OPEN; it was not held at the boundary.
    x.spell['role']='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED'
    x.spell['committed_prior_raw_quantity']=None
    opened=pd.Timestamp('2023-01-04T14:30:00Z')
    x.source.observe_owner_transitions(dict(role='PRE_OPEN_LIFECYCLE_APPLIED',
        owner_ref=owner,account_id=x.book.account_id,session='2023-01-04',session_open_at=opened,
        quantity_coordinate='RAW_ACTUAL_SHARE',security_tickers={'OWNER_OUT':'OUT'},
        positions_before={'OWNER_OUT':0.},positions_after={'OWNER_OUT':0.},terminal_effect_records=[]),x.book.account_id)
    boundary=dict(event,path_id=x.book.account_id,accounting_boundary_at=opened.isoformat(),
        pre_open_engine_units=0.,pre_open_raw_shares=0.,prior_session_quantity_factor=1.,
        disposition='NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX',clock_role='RESEARCH_SESSION_BOUNDARY_ACCOUNTING_CONVENTION')
    return SimpleNamespace(x=x,rows=rows,event=event,boundary=boundary,context=context,
        convention=convention,owner=owner,calls=calls)


def test_original_owner_live_boundary_preserves_residual_and_no_authority_upgrade(original_boundary_guard):
    f=original_boundary_guard;x=f.x
    assert x.source.account_boundary_context['rows'] is f.rows
    assert x.source.lifecycle_effects['2023-01-04']['positions_before']=={'OWNER_OUT':0.}
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)
    before=deepcopy(x.source.unsupported)
    f.rows.append(deepcopy(f.boundary))  # Only the original owner appends this list.
    result=x.source.session(x.ctx,x.original,x.book)
    guard=result['held_guards']['OUT'];proof=guard['account_prefix_nonapplicability_proofs'][0]
    assert x.source.unsupported==before and f.rows==[f.boundary]
    assert guard['original_residual_unsupported_events']==[f.event]
    assert guard['processed_event_fingerprints']==[] and guard['quantity_transitions']==[]
    assert proof['original_event_key']==f.event and proof['account_id']==x.book.account_id
    assert proof['owner_ref']==f.owner and proof['convention_ref']==f.convention
    assert all(proof[k] is False for k in ('typed_cash_processed','cash_or_share_or_terminal_permission_granted',
        'quote_qualification_granted','historical_availability_granted'))
    assert guard['quote_qualification_granted'] is False
    assert guard['original_account_quote_and_unsupported_gates_unchanged']
    assert result['source_receipt']['quantity_guard_proofs']['OUT']['account_prefix_nonapplicability_proofs']==[proof]


def test_original_boundary_historical_same_key_reuse_does_not_use_latest_lifecycle(original_boundary_guard):
    f=original_boundary_guard;x=f.x;f.rows.append(deepcopy(f.boundary))
    later=SimpleNamespace(signal_date=pd.Timestamp('2023-01-05'),signal_asof=inputs.producer._clock('2023-01-05'))
    x.source.observe_owner_transitions(dict(role='PRE_OPEN_LIFECYCLE_APPLIED',owner_ref=f.owner,
        account_id=x.book.account_id,session='2023-01-05',session_open_at='2023-01-05T14:30:00Z',
        quantity_coordinate='RAW_ACTUAL_SHARE',security_tickers={'OWNER_OUT':'OUT'},
        positions_before={'OWNER_OUT':3.},positions_after={'OWNER_OUT':3.},terminal_effect_records=[]),x.book.account_id)
    assert list(x.source.lifecycle_effects)==['2023-01-05']
    proof=x.source._account_prefix_nonapplicability(f.event,later,x.book.account_id)
    assert proof['accounting_boundary_at']=='2023-01-04T14:30:00+00:00'
    assert proof['pre_open_engine_units']==proof['pre_open_raw_shares']==0.
    assert x.source.account_boundary_context['rows'] is f.rows


@pytest.mark.parametrize('defect',[
    'missing','duplicate','other_account','changed_ticker','changed_date','changed_reason','changed_reference','changed_fingerprint',
    'blocked','positive_engine_raw_underflow','tiny_engine','tiny_raw','negative_engine','negative_raw',
    'engine_nan','raw_inf','factor_nan','factor_zero','factor_negative','engine_bool','raw_string',
    'naive_clock','late_clock','wrong_open','wrong_clock_role','future_event','wrong_context_account'])
def test_original_boundary_conflict_or_any_positive_quantity_remains_source_block(original_boundary_guard,defect):
    f=original_boundary_guard;x=f.x;row=deepcopy(f.boundary);f.rows.append(row)
    if defect=='missing':f.rows.clear()
    elif defect=='duplicate':f.rows.append(deepcopy(row))
    elif defect=='other_account':row['path_id']='OTHER_ACCOUNT'
    elif defect=='changed_ticker':row['ticker']='OTHER'
    elif defect=='changed_date':row['effective_date']='2023-01-03'
    elif defect=='changed_reason':row['reason']='OTHER'
    elif defect=='changed_reference':row['source_reference']='D:/synthetic/other.json'
    elif defect=='changed_fingerprint':row['source_fingerprint']='f'*64
    elif defect=='blocked':row['disposition']='ACCOUNTING_BLOCKED'
    elif defect=='positive_engine_raw_underflow':row.update(pre_open_engine_units=1.,pre_open_raw_shares=0.,prior_session_quantity_factor=1e-320)
    elif defect=='tiny_engine':row['pre_open_engine_units']=np.nextafter(0.,1.)
    elif defect=='tiny_raw':row['pre_open_raw_shares']=np.nextafter(0.,1.)
    elif defect=='negative_engine':row['pre_open_engine_units']=-1.
    elif defect=='negative_raw':row['pre_open_raw_shares']=-1.
    elif defect=='engine_nan':row['pre_open_engine_units']=np.nan
    elif defect=='raw_inf':row['pre_open_raw_shares']=np.inf
    elif defect=='factor_nan':row['prior_session_quantity_factor']=np.nan
    elif defect=='factor_zero':row['prior_session_quantity_factor']=0.
    elif defect=='factor_negative':row['prior_session_quantity_factor']=-1.
    elif defect=='engine_bool':row['pre_open_engine_units']=False
    elif defect=='raw_string':row['pre_open_raw_shares']='0'
    elif defect=='naive_clock':row['accounting_boundary_at']='2023-01-04T14:30:00'
    elif defect=='late_clock':row['accounting_boundary_at']='2023-01-04T22:01:00Z'
    elif defect=='wrong_open':row['accounting_boundary_at']='2023-01-04T14:31:00Z'
    elif defect=='wrong_clock_role':row['clock_role']='GUESSED_CLOCK'
    elif defect=='future_event':x.ctx.signal_asof=inputs.producer._clock('2023-01-03')
    else:x.source.account_boundary_context['account_id']='OTHER_ACCOUNT'
    before=deepcopy(x.source.unsupported)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)
    assert x.source.unsupported==before
    assert x.spell['role']=='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED'


@pytest.mark.parametrize('defect',['account','owner','convention','not_list','extra_key'])
def test_boundary_binding_requires_exact_actual_owner_convention_account_and_list(original_boundary_guard,defect):
    f=original_boundary_guard;x=f.x;context=dict(f.context['account_boundary_context'])
    if defect=='account':context['account_id']='OTHER_ACCOUNT'
    elif defect=='owner':context['owner_ref']=dict(f.owner,sha256='f'*64)
    elif defect=='convention':context['convention_ref']=dict(f.convention,sha256='f'*64)
    elif defect=='not_list':context['rows']=tuple(f.rows)
    else:context['parallel_ledger']=[]
    before=x.source.account_boundary_context
    with pytest.raises(inputs.HeldLineageUnavailable,match='EXACT_ORIGINAL_ACCOUNT_BOUNDARY_CONTEXT'):
        x.source._bind_account_boundary_context(context,account_id=x.book.account_id,accounting_freeze_ref=f.convention)
    assert x.source.account_boundary_context is before


@pytest.mark.parametrize('kind',['share_audit','manual_audit','unknown_catalogue','new_residual_key'])
def test_original_zero_boundary_cannot_waive_other_share_cash_or_source_gates(original_boundary_guard,kind):
    f=original_boundary_guard;x=f.x;f.rows.append(deepcopy(f.boundary))
    if kind in ('share_audit','manual_audit'):
        x.audits.loc[0]=dict(ticker='OUT',event_date=pd.Timestamp('2023-01-04'),source_event_date=pd.Timestamp('2023-01-04'),
            code='OUT',audit_kind='REAL_UNBOUND_SOURCE',share_event=kind=='share_audit',manual_wolf=kind=='manual_audit',aligned_to_next_session=False)
    elif kind=='unknown_catalogue':x.source.original_events+=({'ticker':'OUT','event_date':'2023-01-04','status':'UNSUPPORTED','reason':'REAL_UNKNOWN_SOURCE'},)
    else:x.source.unsupported+= (dict(f.event,source_fingerprint='f'*64),)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)



@pytest.mark.parametrize('left,right',[
    ('COM     NEW','COM NEW'),(' COM\tNEW ','COM NEW'),
    ('COM\r\nNEW','COM\nNEW'),('COM\fNEW','COM\vNEW'),
    ('COM A','COM A'),('PFD.','PFD.'),('COM\u00a0NEW','COM\u00a0NEW')])
def test_ascii_class_comparison_preserves_raw_case_punctuation_and_tokens(left,right):
    assert inputs._held_class_equal(left,right) and inputs._held_class_equal(right,left)
    assert left==left and right==right


@pytest.mark.parametrize('left,right',[
    ('COM A','COM B'),('COM NEW','COM'),('COM NEW','NEW COM'),('COM NEW','com NEW'),
    ('COM-NEW','COM NEW'),('COM NEW.','COM NEW'),('COM\u00a0NEW','COM NEW'),
    ('COM\u2003NEW','COM NEW'),
    ('COM\u202fNEW','COM NEW'),('COM\u0085NEW','COM NEW'),
    ('',''),(' \t\r\n','COM'),('UNKNOWN','UNKNOWN'),(' NONE ','NONE'),('NaN','NaN'),
    (None,'COM'),(1,'COM'),(False,'COM')])
def test_ascii_class_does_not_alias_real_unknown_or_unicode_class(left,right):
    assert not inputs._held_class_equal(left,right)
    assert not inputs._held_class_equal(right,left)


@pytest.mark.parametrize('field,value',[
    ('security_id','OTHER'),('security_id_type','OTHER'),('cusip','OTHER'),
    ('raw_code','US.OTHER'),('raw_actual_share_coordinate','INDEX_UNIT'),
    ('share_class','COM A'),('share_class','UNKNOWN'),('share_class','COM\u00a0NEW')])
def test_ascii_security_identity_requires_every_other_exact_coordinate(held_book,field,value):
    old=dict(held_book.identity,share_class='COM     NEW')
    new=dict(old,share_class='COM NEW');new[field]=value
    before=deepcopy((old,new))
    assert not inputs._held_security_identity_equal(old,new)
    assert (old,new)==before


def test_ascii_security_identity_comparison_has_no_rewrite_or_missing_field_authority(held_book):
    old=dict(held_book.identity,share_class='COM     NEW');new=dict(old,share_class='COM NEW')
    before=deepcopy((old,new))
    assert inputs._held_security_identity_equal(old,new)
    assert (old,new)==before and content_hash(old)!=content_hash(new)
    missing=dict(new);del missing['raw_code']
    assert not inputs._held_security_identity_equal(old,missing)
    assert not inputs._held_security_identity_equal(old,dict(new,extra_authority=True))


def test_ascii_class_real_book_existing_hold_and_dated_add_keep_both_original_seeds(held_book):
    x=held_book;x.identity['share_class']='COM     NEW'
    first=x.admitted();old_position=first['position_id'];old_source=first['seed_source_row_identity']
    second_seed=dict(x.seed('2023-01-04'),share_class='COM NEW',seed_source_row_identity='NEW_ORIGINAL_SOURCE_ROW')
    second_before=deepcopy(second_seed)
    x.book.note_qualified_decision('2023-01-04',{'A':second_seed})
    x.book.observe_fills(x.fill(q=1.,before=1.,order='ADD',signal='2023-01-04',day='2023-01-05'))
    records=x.book.source_lineages()['A']
    assert len(records)==1 and records[0]['role']=='ACCEPTED_POSITION'
    assert records[0]['seed']['share_class']=='COM     NEW'
    assert records[0]['pending_fill_refs'][0]['candidate_seed']['share_class']=='COM NEW'
    assert records[0]['pending_fill_refs'][0]['candidate_seed']['seed_source_row_identity']=='NEW_ORIGINAL_SOURCE_ROW'
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),
        {'A':x.guard('2023-01-05',share_class='COM NEW')})['A']
    assert proof['position_id']==old_position and proof['seed_share_class']=='COM     NEW'
    assert proof['seed_source_row_identity']==old_source
    assert [r.get('stage') for r in proof['quantity_transition_refs']]==['ACTUAL_RAW_SHARE_FILL']
    assert proof['actual_quantity_binding']['raw_quantity']==2.
    assert second_seed==second_before and x.book.source_lineages()['A'][0]['identity']['share_class']=='COM     NEW'


@pytest.mark.parametrize('change',[
    dict(share_class='COM A'),dict(share_class='COM'),dict(share_class='COM\u2003NEW'),
    dict(security_id='OTHER',cusip='OTHER'),dict(security_id_type='OTHER'),
    dict(raw_code='US.OTHER',mapping_raw_code='US.OTHER',raw_key_code='US.OTHER')])
def test_ascii_class_real_book_true_guard_conflict_does_not_commit_add(held_book,change):
    x=held_book;x.identity['share_class']='COM     NEW';first=x.admitted()
    x.book.note_qualified_decision('2023-01-04',{'A':dict(x.seed('2023-01-04'),share_class='COM NEW')})
    x.book.observe_fills(x.fill(q=1.,before=1.,order='ADD',signal='2023-01-04',day='2023-01-05'))
    before=x.book.source_lineages()
    with pytest.raises(inputs.HeldLineageUnavailable,match='IDENTITY_CONFLICT'):
        x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),{'A':x.guard('2023-01-05',**change)})
    assert x.book.source_lineages()==before and x.book.pending_fill_count==1
    assert before['A'][0]['position_id']==first['position_id']


def test_ascii_class_dated_source_intervals_keep_original_rows_and_spell_values(full_source_guard):
    x=full_source_guard
    x.identity['share_class']='COM     NEW';x.spell['seed']['share_class']='COM     NEW'
    x.rows[0]['title_of_class']='COM     NEW'
    newer=dict(x.rows[0],effective_start=pd.Timestamp('2023-01-04'),effective_end=pd.Timestamp('2023-01-05'),
        title_of_class='COM NEW',source_filing='NEW_ORIGINAL_FILING')
    x.rows.append(newer)
    candidate=deepcopy(x.spell);candidate['role']='PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED'
    candidate['identity']['share_class']='COM NEW';candidate['seed']['share_class']='COM NEW'
    x.book.source_lineages=lambda:{'OUT':(x.spell,candidate)}
    before=deepcopy((x.rows,x.spell,candidate));row_hashes=[content_hash(r) for r in x.rows]
    result=x.source.session(x.ctx,x.original,x.book)
    assert result['held_guards']['OUT']['share_class']=='COM NEW'
    assert (x.rows,x.spell,candidate)==before and [content_hash(r) for r in x.rows]==row_hashes
    assert result['held_guards']['OUT']['quantity_transitions']==[]
    assert result['held_guards']['OUT']['quote_qualification_granted'] is False


@pytest.mark.parametrize('field,value',[
    ('title_of_class','COM A'),('title_of_class','COM'),('title_of_class','COM\u00a0NEW'),
    ('title_of_class','UNKNOWN'),('title_of_class',''),('security_id','OTHER'),
    ('security_id_type','OTHER'),('cusip','OTHER'),('moomoo_transport_code','US.OTHER'),
    ('mapping_status','UNRESOLVED')])
def test_ascii_class_dated_source_true_coordinate_conflict_remains_block(full_source_guard,field,value):
    x=full_source_guard;x.identity['share_class']='COM     NEW';x.spell['seed']['share_class']='COM     NEW'
    x.rows[0]['title_of_class']='COM     NEW'
    newer=dict(x.rows[0],effective_start=pd.Timestamp('2023-01-04'),effective_end=pd.Timestamp('2023-01-05'),title_of_class='COM NEW')
    newer[field]=value;x.rows.append(newer);before=deepcopy(x.rows)
    with pytest.raises(inputs.HeldLineageUnavailable,match='HELD_DATED_SECURITY_COORDINATE_CONFLICT'):
        x.source.session(x.ctx,x.original,x.book)
    assert x.rows==before


def test_ascii_class_typed_owner_effect_once_keeps_raw_before_after_and_old_seed(held_book):
    x=held_book;x.identity['share_class']='COM     NEW';first=x.admitted()
    old=dict(x.identity,share_class='COM\tNEW');new=dict(x.identity,share_class='COM NEW')
    transition=x.transition(old_identity=old,new_identity=new)
    original_transition=deepcopy(transition)
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),
        {'A':x.guard('2023-01-05',share_class='COM NEW',processed_event_fingerprints=['EVENT_1'],quantity_transitions=[transition])})['A']
    assert proof['position_id']==first['position_id'] and proof['seed_share_class']=='COM     NEW'
    assert len(proof['quantity_transition_refs'])==1
    effect=proof['quantity_transition_refs'][0]
    assert effect['old_identity']['share_class']=='COM\tNEW' and effect['new_identity']['share_class']=='COM NEW'
    assert effect['before_raw_quantity']==1. and effect['after_raw_quantity']==2.
    assert proof['actual_quantity_binding']['raw_quantity']==2. and transition==original_transition


@pytest.mark.parametrize('defect,reason',[
    ('old_class','PRIOR_CONFLICT'),('old_sid','PRIOR_CONFLICT'),('old_raw','PRIOR_CONFLICT'),
    ('new_class','SPLIT_CANNOT_RENAME'),('new_sid','SPLIT_CANNOT_RENAME'),('new_raw','SPLIT_CANNOT_RENAME'),
    ('unqualified','APPROVED_TYPED'),('clock','APPROVED_TYPED'),('unprocessed','UNPROCESSED_TYPED'),
    ('ratio','SHARE_RATIO')])
def test_ascii_class_typed_observer_never_waives_effect_source_or_real_identity_conflict(held_book,defect,reason):
    x=held_book;x.identity['share_class']='COM     NEW';x.admitted()
    old=dict(x.identity,share_class='COM\tNEW');new=dict(x.identity,share_class='COM NEW')
    transition=x.transition(old_identity=old,new_identity=new)
    processed=['EVENT_1']
    if defect=='old_class':old['share_class']='COM A'
    elif defect=='old_sid':old.update(security_id='OTHER',cusip='OTHER')
    elif defect=='old_raw':old['raw_code']='US.OTHER'
    elif defect=='new_class':new['share_class']='COM A'
    elif defect=='new_sid':new.update(security_id='OTHER',cusip='OTHER')
    elif defect=='new_raw':new['raw_code']='US.OTHER'
    elif defect=='unqualified':transition['qualified']=False
    elif defect=='clock':transition['session']='2023-01-06'
    elif defect=='unprocessed':processed=[]
    else:transition['share_ratio']=3.
    before=x.book.source_lineages()
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):
        x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),
            {'A':x.guard('2023-01-05',share_class='COM NEW',processed_event_fingerprints=processed,quantity_transitions=[transition])})
    assert x.book.source_lineages()==before


def test_ascii_class_current_to_fit_role_keeps_both_raw_identity_proofs(causal):
    x=causal;x.identities['OUT']['share_class']='COM     NEW'
    x.adapter.source_contract['binding']['held_lineages']['OUT']['share_class']='COM NEW'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));domain=x.adapter.qualified_causal_domain(ctx)
    before=deepcopy((x.identities,x.adapter.source_contract))
    bridge=x.adapter._guard_supplement(ctx,domain,x.adapter._last)['OUT']
    assert bridge['relation']=='SAME_SECURITY_AND_HISTORICAL_SUPPORT_NOT_SAME_POSITION_ID'
    assert (x.identities,x.adapter.source_contract)==before and x.calls==[]


@pytest.mark.parametrize('defect,reason',[
    ('true_class','UNPROVED_FIT_ASOF'),('unicode','UNPROVED_FIT_ASOF'),('unknown','UNPROVED_FIT_ASOF'),
    ('uid','UNPROVED_FIT_ASOF'),('raw','UNPROVED_FIT_ASOF'),('future','CAUSAL_APPROVED_STATE_CLOCK'),
    ('primary','EXPIRED_AT_NEXT'),('historical_role','CURRENT_SECURITY_AND_HISTORICAL_SUPPORT')])
def test_ascii_class_fit_bridge_does_not_relax_identity_clock_or_source_roles(causal,defect,reason):
    x=causal;x.identities['OUT']['share_class']='COM     NEW'
    x.adapter.source_contract['binding']['held_lineages']['OUT']['share_class']='COM NEW'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));domain=x.adapter.qualified_causal_domain(ctx)
    old=x.adapter.source_contract['binding']['held_lineages']['OUT']
    if defect=='true_class':old['share_class']='COM A'
    elif defect=='unicode':old['share_class']='COM\u2003NEW'
    elif defect=='unknown':old['share_class']='UNKNOWN'
    elif defect=='uid':old['uid']='OTHER'
    elif defect=='raw':old['raw_code']='OTHER'
    elif defect=='future':x.adapter.supplemental['state_available_at']=inputs.producer._clock('2023-01-04').isoformat()
    elif defect=='primary':x.adapter._last['original']['event']['dependency_local_event_ids']['PRIMARY']='NEXT_PRIMARY'
    else:x.adapter._last['source']['historical_source_epochs']['OUT']='OTHER_HISTORY'
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match=reason):
        x.adapter._guard_supplement(ctx,domain,x.adapter._last)
    assert x.calls==[]


@pytest.fixture
def continuous(causal,monkeypatch):
    from scripts.research.a2.risk.continuous_lw_support import CONTINUOUS_LW_RULE,RECIPE
    old=causal.adapter
    new=inputs.ContinuousCausalLWInputs(base=old.base,account_id=old.account_id,sources=old.sources,
        supplemental=old.supplemental,source_contract=old.source_contract,references=old.references,
        reuse_rule=old.reuse_rule,state_loader=old._state_loader)
    monkeypatch.setattr(new.book,'qualified_proofs',lambda c,g:{'OUT':dict(position_id='OWN_POSITION')})
    new.continuous_rule=deepcopy(CONTINUOUS_LW_RULE)
    called=[]
    def callback(request):
        called.append(deepcopy(request))
        assets=request['U'];n=len(assets)
        state=deepcopy(causal.state);state.assets=tuple(assets);state.risk_state_id='GENERATED'
        state.as_of=request['as_of'];state.cutoff=request['cutoff']
        state.notes={'estimator_lineage':{'family':'LW','recipe_sha256':RECIPE}}
        state.covariance=np.full((n,n),.2)+np.eye(n)
        epochs={a:'FIT_CURRENT_'+a for a in assets}
        state.coverage={a:dict(uid='UID_'+a,identity_epoch=epochs[a]) for a in assets}
        metadata=dict(status='COMPLETE_WHOLE_LW_OUTPUT',assets=assets,
            asset_uids={a:'UID_'+a for a in assets},asset_epochs=epochs,
            historical_source_epochs={a:'EPOCH_'+a for a in assets},current_identities=deepcopy(causal.identities),
            original_primary_dependency_epoch=request['original_primary_dependency_epoch'],
            as_of=request['as_of'],cutoff=request['cutoff'],state_available_at=request['as_of'],
            risk_state_id='GENERATED',method=state.method,recipe_sha256=RECIPE,
            typed_state_content_sha256='f'*64,state_ref={'path':'D:/synthetic/generated.joblib','sha256':'a'*64},
            producer_ref={'path':'D:/synthetic/backend.py','sha256':'a'*64},
            covariance_sha256=content_hash(state.covariance),learned_units=9,physical_operations=14)
        return dict(state=state,metadata=metadata)
    new.estimate_callback=callback
    return SimpleNamespace(adapter=new,example=causal.example,calls=called,callback=callback)


def test_continuous_prefailure_describes_full_P_not_eligible_only(continuous):
    x=continuous;ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    request=x.adapter.describe_required_domains(ctx)
    assert request['P']==['A','B'] and request['E']==['A'] and request['H']==['OUT']
    assert request['D']==['OUT','A'] and request['U']==['A','B','OUT']
    assert request['cutoff']==inputs.producer._clock('2022-12-30').isoformat()
    assert x.calls==[] and x.adapter.loads_count==0


def test_continuous_simple_source_stays_zero_risk_and_zero_estimates(continuous):
    x=continuous;ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    domain=x.adapter.qualified_causal_domain(ctx)
    x.adapter.note_qualified_decision(ctx,domain)
    assert x.calls==[] and x.adapter.loads_count==0
    assert x.adapter.last_request['source_qualification_status']=='CURRENT_ACCOUNT_SOURCE_QUALIFIED'


def test_continuous_complete_original_primary_and_paid_single_reuse_first(continuous):
    x=continuous
    ctx=x.example.context();d=x.adapter.qualified_causal_domain(ctx)
    assert x.adapter.for_required_domain(ctx,d).source_receipt['selected_state_role']=='COMPLETE_ORIGINAL_PRIMARY_FIRST'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));d=x.adapter.qualified_causal_domain(ctx)
    assert x.adapter.for_required_domain(ctx,d).source_receipt['selected_state_role']=='APPROVED_SINGLE_WHOLE_LW_NECESSARY_FALLBACK'
    assert x.calls==[]


def test_continuous_new_output_full_P_includes_disabled_member_and_all_cross_terms(continuous):
    x=continuous;x.adapter.supplemental['original_primary_dependency_epoch']['event_id']='EXPIRED'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));d=x.adapter.qualified_causal_domain(ctx)
    result=x.adapter.for_required_domain(ctx,d)
    assert x.calls[0]['U']==['A','B','OUT'] and x.calls[0]['E']==['A']
    np.testing.assert_array_equal(result.covariance,[[1.2,.2],[.2,1.2]])
    assert result.assets==('OUT','A') and result.source_receipt['exact_principal_projection']
    assert x.adapter.new_outputs_count==1 and x.adapter.generated_loads_count==0
    x.adapter.for_required_domain(ctx,d)
    assert len(x.calls)==1


@pytest.mark.parametrize('defect,reason',[
    ('axis','EXACT_FULL_P'),('future','FUTURE_CLOCK'),('uid','SOURCE_IDENTITY'),
    ('historical','HISTORICAL_ROLE'),('epoch','PRIMARY_EPOCH'),('cross','COMPLETE_CROSS'),
    ('covdigest','COMPLETE_CROSS'),('typed','PERSISTED_ORIGINAL'),('recipe','PERSISTED_ORIGINAL'),
    ('coverage','COVERAGE_IDENTITY'),('units','INVOCATION_BUDGET')])
def test_continuous_generated_output_rejects_incomplete_or_unqualified_state(continuous,defect,reason):
    x=continuous;x.adapter.supplemental['original_primary_dependency_epoch']['event_id']='EXPIRED'
    original=x.callback
    def broken(request):
        out=original(request);m=out['metadata'];state=out['state']
        if defect=='axis':m['assets']=['A','OUT']
        elif defect=='future':m['state_available_at']=inputs.producer._clock('2023-01-04').isoformat()
        elif defect=='uid':m['current_identities']['OUT']['security_id']='OTHER'
        elif defect=='historical':m['historical_source_epochs']['OUT']='OTHER'
        elif defect=='epoch':m['original_primary_dependency_epoch']['event_id']='NEXT'
        elif defect=='cross':state.covariance=np.eye(2)
        elif defect=='covdigest':m['covariance_sha256']='0'*64
        elif defect=='typed':m['typed_state_content_sha256']='0'*64
        elif defect=='recipe':m['recipe_sha256']='0'*64
        elif defect=='coverage':state.coverage['OUT']['uid']='OTHER'
        else:m['learned_units']=10
        return out
    x.adapter.estimate_callback=broken
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));d=x.adapter.qualified_causal_domain(ctx)
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match=reason):x.adapter.for_required_domain(ctx,d)
    assert not x.adapter.generated and x.adapter.last_request['estimation_status']=='FAILED'
    assert x.adapter.last_request['P']==['A','B']


def test_continuous_source_failure_keeps_complete_requested_domain_without_fit(continuous):
    x=continuous;ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.))
    def broken(*args):raise inputs.HeldLineageUnavailable('SOURCE_GAP',asset='OUT')
    x.adapter.sources.session=broken
    with pytest.raises(inputs.HeldLineageUnavailable,match='SOURCE_GAP'):x.adapter.qualified_causal_domain(ctx)
    assert x.adapter.last_request['U']==['A','B','OUT'] and x.adapter.last_request['source_qualification_status']=='FAILED'
    assert x.calls==[]


def test_continuous_factory_uses_new_config_current_pins_but_retains_old_state_subject(freeze_metadata,monkeypatch):
    from scripts.research.a2.risk import continuous_lw_support as backend
    x=freeze_metadata;f=deepcopy(x.freeze)
    config_ref={'path':'D:/synthetic/new_config.json','sha256':'d'*64}
    f.update(task_id=backend.TASK,continuous_lw_rule=deepcopy(backend.CONTINUOUS_LW_RULE),research_config_ref=config_ref,
        continuous_lw_source_science=dict(scientific_contract_identity=backend.TASK+'::NEW',
            scientific_contract_sha256=config_ref['sha256'],actual_snapshot_timestamp=backend.SOURCE_SNAPSHOT))
    inherited=f['held_identity_source_binding_ref']
    derived_ref={'path':'D:/synthetic/derived_identity.json','sha256':'b'*64}
    source_ref={'path':'D:/synthetic/new_cash_source.json','sha256':'c'*64}
    f.update(inherited_held_identity_source_binding_ref=inherited,
        held_identity_source_binding_ref=derived_ref,source_account_contract_ref=source_ref)
    x.docs[derived_ref['path']]=dict(parent_binding_ref=inherited,
        source_binding_revision='AUTHORIZED_FAST_TRACK_CA_SOURCE_DESCENDANT_ONLY',
        task_id=backend.TASK,status='FROZEN_SOURCE_BOUND_RUNTIME_ACCEPTANCE_PENDING',
        source_account_contract_ref=source_ref)
    x.docs[config_ref['path']]=dict(schema='B_FAST_TRACK_HUMAN_AUTHORIZED_RESEARCH_CONFIG_V1',
        status='FROZEN_RESEARCH_CONFIGURATION',task_id=backend.TASK,continuous_lw_rule=f['continuous_lw_rule'])
    # The old producer commitment stays historical; current bytes use new pins.
    f['source_pins']=[dict(path=str(inputs.Path(inputs.__file__).resolve()),sha256='e'*64),
        dict(path=str(inputs.Path(backend.__file__).resolve()),sha256='f'*64)]
    callback=lambda request:None
    obj=inputs.ContinuousCausalLWInputs.from_freeze(freeze=f,base_shared=x.causal.example.provider,
        account_id='NEW',market_dates=x.causal.example.provider.market_dates,
        master_assets=x.causal.example.provider.master_assets,source_context={},estimate_callback=callback)
    assert obj.estimate_callback is callback and obj._supplement is None
    x.accepted['single_lw_state_ref']={'path':'D:/synthetic/OTHER.json','sha256':'a'*64}
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match='REVIEWED_STATE'):
        inputs.ContinuousCausalLWInputs.from_freeze(freeze=f,base_shared=x.causal.example.provider,
            account_id='NEW',market_dates=x.causal.example.provider.market_dates,
            master_assets=x.causal.example.provider.master_assets,source_context={},estimate_callback=callback)


def test_typed_hash_owner_equals_dataclass_content_hash_without_authority_substitution():
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState
    from scripts.research.a2.portfolio.shared_joint_adapter_r2 import risk_state_sha256
    fields={k:None for k in RiskState.__dataclass_fields__}
    fields.update(risk_state_id='SYNTHETIC',assets=('A',),covariance=np.array([[1.]]),
        notes={'existing_nested_array':np.array([1.,2.])})
    state=RiskState(**fields)
    assert content_hash(state)==risk_state_sha256(state)


@pytest.mark.parametrize('label', [
    'JOINT_REUSE_S5', 'JOINT_REUSE_S10', 'JOINT_REUSE_S20',
    'JOINT_REUSE_NO_ALPHA_S10', 'JOINT_REUSE_G1_S10',
    'JOINT_REUSE_A2_S10', 'JOINT_REUSE_G1_A2_S10',
    'PTO_REUSE_ROBUST_COST_S10',
])
def test_continuous_logical_account_identity_admits_original_books_and_exact_pto_s10(label):
    from scripts.research.a2.risk import continuous_lw_support as backend
    account_id=backend.TASK+'::'+label
    assert backend.logical_joint_account_id(dict(account_id=account_id))==account_id


@pytest.mark.parametrize('suffix', [
    'PTO_REUSE_ROBUST_COST_S5', 'PTO_REUSE_ROBUST_COST_S20',
    'PTO_REUSE_ROBUST_COST_S010', 'PTO_REUSE_ROBUST_COST_S10_EXTRA',
    'pto_reuse_robust_cost_S10', 'JOINT_REUSE_G1_S5', 'SIMPLE_FEASIBLE_S10',
    'attempt::PTO_REUSE_ROBUST_COST_S10', 'PTO_REUSE_ROBUST_COST_S10/attempt',
])
def test_continuous_logical_account_identity_rejects_unfrozen_or_attempt_labels(suffix):
    from scripts.research.a2.risk import continuous_lw_support as backend
    with pytest.raises(ValueError,match='EXISTING_LOGICAL_JOINT_POLICY_ACCOUNT_ID_REQUIRED'):
        backend.logical_joint_account_id(dict(account_id=backend.TASK+'::'+suffix))


@pytest.mark.parametrize('account_id', [None, '', 'OTHER_TASK::PTO_REUSE_ROBUST_COST_S10'])
def test_continuous_logical_account_identity_requires_exact_task_prefix(account_id):
    from scripts.research.a2.risk import continuous_lw_support as backend
    with pytest.raises(ValueError,match='EXISTING_LOGICAL_JOINT_POLICY_ACCOUNT_ID_REQUIRED'):
        backend.logical_joint_account_id(dict(account_id=account_id))


@pytest.fixture
def continuous_ledger(tmp_path,monkeypatch):
    from scripts.research.a2.risk import continuous_lw_support as backend
    monkeypatch.setattr(backend,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(backend,'resolve',lambda *a:None)
    def checkpoint(ledger):
        import json
        path=ledger.run/'work/FIT_STATUS.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(backend.old._json(ledger.status)),encoding='utf-8')
    monkeypatch.setattr(backend.ContinuousLWLedger,'checkpoint',checkpoint)
    inherited={'path':'D:/synthetic/paid.json','sha256':'a'*64}
    ledger=backend.ContinuousLWLedger(tmp_path/'run',inherited_ref=inherited)
    request=dict(decision_session='2023-02-22',P=['A','B'],E=['A'],H=['OUT'],
        D=['A','OUT'],U=['A','B','OUT'])
    def qualified(request=request):
        ledger.begin(deepcopy(request));ledger.active_request['status']='SOURCE_QUALIFIED_BEFORE_RESERVATION'
    return SimpleNamespace(backend=backend,ledger=ledger,request=request,qualified=qualified,
        inherited=inherited,run=tmp_path/'run')


def _continuous_test_event(index,kind='covariance'):
    return dict(key=content_hash(str(index)),kind=kind,name='SYNTHETIC_'+str(index),
        status='RESERVED',context={'synthetic':True,'mechanism':False},
        inputs_sha256='a'*64,parameters={},synthetic=True,mechanism=False)


def test_continuous_ledger_requires_qualification_before_any_reservation(continuous_ledger):
    x=continuous_ledger;x.ledger.begin(x.request)
    with pytest.raises(ValueError,match='ACTIVE_QUALIFIED'):x.ledger.reserve(_continuous_test_event(0))
    assert x.ledger.status['new_fit_units']==0 and not x.ledger.status['physical_events']


def test_continuous_durable_failed_units_not_refunded_or_unchanged_request_retried(continuous_ledger):
    x=continuous_ledger;x.qualified();event=_continuous_test_event(0)
    x.ledger.reserve(event);event['status']='FAILED';x.ledger.sync([event])
    x.ledger.finish(dict(status='TERMINAL_FAILED_CONTINUOUS_LW_REQUEST'))
    restored=x.backend.ContinuousLWLedger(x.run,inherited_ref=x.inherited)
    assert restored.status['new_fit_units']==1 and restored.status['physical_events'][0]['status']=='FIT_FAILURE'
    with pytest.raises(ValueError,match='UNCHANGED_REQUEST'):restored.begin(x.request)
    changed=deepcopy(x.request);changed['engineering_repair_ref']='EXPLICIT_NEW_SOURCE'
    restored.begin(changed);restored.active_request['status']='SOURCE_QUALIFIED_BEFORE_RESERVATION'
    restored.reserve(_continuous_test_event(1))
    assert restored.status['new_fit_units']==2 and restored.status['inherited_fit_units']==0
    assert restored.status['inherited_state_history']['learned_units']==9


@pytest.mark.parametrize('kind,count',[('scaler',2),('covariance',7),('deterministic_transform',5),('model_fit',0),('horizon',0)])
def test_continuous_ledger_original_DAG_kind_caps(continuous_ledger,kind,count):
    x=continuous_ledger;x.qualified()
    for i in range(count):x.ledger.reserve(_continuous_test_event(i,kind))
    with pytest.raises(ValueError,match='PHYSICAL_OR_KIND_CAP'):x.ledger.reserve(_continuous_test_event(count,kind))
    assert len(x.ledger.status['physical_events'])==count
    assert x.ledger.status['new_fit_units']==(0 if kind=='deterministic_transform' else count)


def test_continuous_ledger_nine_learned_fourteen_physical_and_one_output_per_day(continuous_ledger):
    x=continuous_ledger;x.qualified()
    kinds=['scaler']*2+['covariance']*7+['deterministic_transform']*5
    events=[]
    for i,k in enumerate(kinds):
        e=_continuous_test_event(i,k);x.ledger.reserve(e);e['status']='SUCCEEDED';e['result_sha256']='e'*64;events.append(e)
    x.ledger.sync(events)
    assert x.ledger.status['new_fit_units']==9 and len(x.ledger.status['physical_events'])==14
    with pytest.raises(ValueError,match='PHYSICAL_OR_KIND_CAP'):x.ledger.reserve(_continuous_test_event(15))
    x.ledger.finish(dict(status='COMPLETE_WHOLE_LW_OUTPUT'))
    changed=deepcopy(x.request);changed['different_axis_request']=True
    with pytest.raises(ValueError,match='ONE_WHOLE_LW_OUTPUT'):x.ledger.begin(changed)
    other=deepcopy(x.request);other['decision_session']='2023-02-23';x.ledger.begin(other)
    assert x.ledger.status['new_fit_units']==9


def test_continuous_ledger_rejects_mutated_counts_on_reload(continuous_ledger):
    x=continuous_ledger;x.qualified();x.ledger.reserve(_continuous_test_event(0))
    x.ledger.status['new_fit_units']=0;x.ledger.status['fit_attempts']=0;x.ledger.checkpoint()
    with pytest.raises(ValueError,match='COUNTERS'):x.backend.ContinuousLWLedger(x.run,inherited_ref=x.inherited)


def test_held_backend_continuity_does_not_extend_expired_membership_interval():
    from scripts.research.a2.risk import continuous_lw_support as backend
    ref={'path':'D:/synthetic/raw.parquet','sha256':'a'*64}
    identity=dict(security_id='CUSIP_A',security_id_type='CUSIP',cusip='CUSIP_A',share_class='COM',
        raw_code='US.A',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    raw=pd.DataFrame([dict(ticker='A',trade_date=pd.Timestamp('2023-02-22'),code='US.A')])
    proof=dict(lineage_status='QUALIFIED_RESEARCH_HELD_LINEAGE',decision_session='2023-02-22',
        actual_quantity_binding=dict(account_id='OWN',session='2023-02-22',stage='DECISION_CLOSE_RAW_ACTUAL_SHARE',raw_quantity=.000001),
        raw_exact_key_ref=dict(source_ref=ref,row_identity=inputs._held_raw_key_row_identity(raw)),
        seed_security_id='CUSIP_A',seed_security_id_type='CUSIP',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    request=dict(decision_session='2023-02-22',current_identities={'A':identity},held_lineage_proofs={'A':proof})
    # No active membership row is needed or manufactured for a held-only asset.
    observed=backend._held_current_identity(request,raw,'A','OWN',ref)
    assert observed==identity and proof['actual_quantity_binding']['raw_quantity']==.000001
    proof['seed_security_id']='OTHER'
    with pytest.raises(ValueError,match='SEED_IDENTITY'):backend._held_current_identity(request,raw,'A','OWN',ref)


@pytest.mark.parametrize('defect', ['account','date','zero','nan','raw','source','row','status'])
def test_held_backend_rejects_real_source_or_account_conflict(defect):
    from scripts.research.a2.risk import continuous_lw_support as backend
    ref={'path':'D:/synthetic/raw.parquet','sha256':'a'*64}
    identity=dict(security_id='CUSIP_A',security_id_type='CUSIP',cusip='CUSIP_A',share_class='COM',
        raw_code='US.A',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    raw=pd.DataFrame([dict(ticker='A',trade_date=pd.Timestamp('2023-02-22'),code='US.A')])
    proof=dict(lineage_status='QUALIFIED_RESEARCH_HELD_LINEAGE',decision_session='2023-02-22',
        actual_quantity_binding=dict(account_id='OWN',session='2023-02-22',stage='DECISION_CLOSE_RAW_ACTUAL_SHARE',raw_quantity=1.),
        raw_exact_key_ref=dict(source_ref=ref,row_identity=inputs._held_raw_key_row_identity(raw)),
        seed_security_id='CUSIP_A',seed_security_id_type='CUSIP',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    if defect=='account':proof['actual_quantity_binding']['account_id']='OTHER'
    elif defect=='date':proof['decision_session']='2023-02-23'
    elif defect=='zero':proof['actual_quantity_binding']['raw_quantity']=0.
    elif defect=='nan':proof['actual_quantity_binding']['raw_quantity']=np.nan
    elif defect=='raw':raw.loc[0,'code']='US.OTHER'
    elif defect=='source':proof['raw_exact_key_ref']['source_ref']={'path':'D:/synthetic/OTHER.parquet','sha256':'a'*64}
    elif defect=='row':proof['raw_exact_key_ref']['row_identity']='0'*64
    else:proof['lineage_status']='UNKNOWN'
    request=dict(decision_session='2023-02-22',current_identities={'A':identity},held_lineage_proofs={'A':proof})
    with pytest.raises(ValueError):backend._held_current_identity(request,raw,'A','OWN',ref)


@pytest.mark.parametrize('failure', ['none','source','fit','persist','cache'])
def test_continuous_backend_atomic_terminal_record_and_failed_debit(continuous_ledger,monkeypatch,failure):
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState
    x=continuous_ledger;b=x.backend
    engine=object.__new__(b.ContinuousLWEstimator)
    engine.base=SimpleNamespace(interface=SimpleNamespace(pin=lambda ref:ref['path']))
    engine.freeze=dict(source_pins=[],supplemental_lw_state_ref=x.inherited,
        research_config_ref={'path':'D:/synthetic/config.json','sha256':'a'*64})
    engine.run=x.run;engine.science={'scientific_contract_sha256':'a'*64};engine.ledger=x.ledger
    engine.account_id='OWN';engine.last_request=None;engine.estimator=None
    engine._producer_ref={'path':'D:/synthetic/backend_custody.py','sha256':'d'*64}
    request=deepcopy(x.request);request.update(as_of=inputs.producer._clock('2023-02-22').isoformat(),
        cutoff=inputs.producer._clock('2023-02-21').isoformat())
    assets=request['U'];n=len(assets)
    fields={k:None for k in RiskState.__dataclass_fields__}
    fields.update(risk_state_id='SYNTHETIC',assets=tuple(assets),as_of=request['as_of'],cutoff=request['cutoff'],
        status='PASS_FROZEN_HISTORY_MECHANISM',method='SYNTHETIC_LW',covariance=np.eye(n),fit_dependency_ids=(),
        notes={'estimator_lineage':{'family':'LW','recipe_sha256':b.RECIPE}})
    state=RiskState(**fields)
    prepared=dict(inputs=SimpleNamespace(asset_uids={a:'UID_'+a for a in assets}),
        keys=pd.DataFrame(),qualification={'metadata_proof_sha256':'a'*64},proof={'qualified_synthetic':True},
        historical_source_epochs={a:'H_'+a for a in assets},current_authority_epochs={a:'C_'+a for a in assets},
        identities={},held_lineages={},original_primary_dependency_epoch={'event_id':'P','signature_sha256':'a'*64})
    def prepare(request):
        if failure=='source':raise ValueError('REAL_SOURCE_GAP')
        return prepared
    engine._prepare=prepare
    fit_calls=[]
    class Estimator:
        recipe_sha256=b.RECIPE
        def __init__(self,*args):pass
        def make_cache(self,inputs,as_of,budget):return SimpleNamespace(budget=budget)
        def fit_family(self,*args,**kwargs):
            fit_calls.append(True)
            budget=kwargs['cache'].budget
            event=budget.reserve('f'*64,'covariance','SYNTHETIC_LW',{'synthetic':True,'mechanism':False},'a'*64,{})
            event['status']='FAILED' if failure=='fit' else 'SUCCEEDED'
            if failure=='fit':raise ValueError('REAL_COMPUTE_FAILURE')
            event['result_sha256']='c'*64
            return state
    monkeypatch.setattr(b.owner,'EventRiskEstimator',Estimator)
    def persist(*args):
        if failure=='persist':raise OSError('PERSISTENCE_FAILURE')
        return {'path':'D:/synthetic/state.joblib','sha256':'c'*64}
    def save_cache(*args):
        if failure=='cache':raise OSError('CACHE_PERSISTENCE_FAILURE')
        return {'path':'D:/synthetic/cache.joblib','sha256':'d'*64}
    monkeypatch.setattr(b.prior,'_persist_state',persist)
    monkeypatch.setattr(b.event_owner,'_save_cache',save_cache)
    if failure=='none':
        out=engine(request)
        assert out['metadata']['status']=='COMPLETE_WHOLE_LW_OUTPUT'
    else:
        with pytest.raises((ValueError,OSError)):engine(request)
    assert len(x.ledger.status['records'])==1 and x.ledger.active_request is None
    row=x.ledger.status['records'][0]
    assert x.ledger.status['new_fit_units']==(0 if failure=='source' else 1)
    assert row['status']==('COMPLETE_WHOLE_LW_OUTPUT' if failure=='none' else 'TERMINAL_FAILED_CONTINUOUS_LW_REQUEST')
    assert len(fit_calls)==(0 if failure=='source' else 1)
    summary=engine.budget_summary()
    assert summary['charged_new_learned_units']==(0 if failure=='source' else 1)
    assert summary['new_complete_outputs']==int(failure=='none')
    if failure=='fit':assert summary['physical_failed']==1
    with pytest.raises(ValueError,match='UNCHANGED_REQUEST'):engine(request)
    assert len(fit_calls)==(0 if failure=='source' else 1)



def test_continuous_preexisting_complete_state_recovered_lazily_without_refit(continuous,monkeypatch):
    x=continuous;x.adapter.supplemental['original_primary_dependency_epoch']['event_id']='EXPIRED'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));d=x.adapter.qualified_causal_domain(ctx)
    request=x.adapter.describe_required_domains(ctx)
    request.update(current_identities=deepcopy(x.adapter._last['source']['current_identities']))
    output=x.callback(request)
    x.calls.clear();loads=[]
    class Callback:
        def available_state_records(self,*args):return [deepcopy(output['metadata'])]
        def __call__(self,*args):raise AssertionError('PREVIOUS_PAID_OUTPUT_MUST_NOT_REFIT')
    x.adapter.estimate_callback=Callback()
    import joblib
    monkeypatch.setattr(joblib,'load',lambda p:(loads.append(p),output['state'])[1])
    result=x.adapter.for_required_domain(ctx,d)
    assert result.assets==('OUT','A') and len(loads)==1 and x.adapter.new_outputs_count==0
    x.adapter.for_required_domain(ctx,d)
    assert len(loads)==1 and x.calls==[]


def test_continuous_stored_future_or_expired_metadata_not_exposed_as_candidate(continuous_ledger):
    x=continuous_ledger;engine=object.__new__(x.backend.ContinuousLWEstimator)
    engine.run=x.run;engine.ledger=x.ledger
    epoch={'event_id':'P','signature_sha256':'a'*64}
    x.ledger.status['records']=[dict(status='COMPLETE_WHOLE_LW_OUTPUT',as_of='2023-02-22T21:00:00+00:00',
        state_available_at='2023-02-22T21:00:00+00:00',original_primary_dependency_epoch=epoch),
        dict(status='COMPLETE_WHOLE_LW_OUTPUT',as_of='2023-02-23T21:00:00+00:00',
        state_available_at='2023-02-23T21:00:00+00:00',original_primary_dependency_epoch=epoch),
        dict(status='COMPLETE_WHOLE_LW_OUTPUT',as_of='2023-02-21T21:00:00+00:00',
        state_available_at='2023-02-21T21:00:00+00:00',original_primary_dependency_epoch={'event_id':'OLD'})]
    selected=engine.available_state_records('2023-02-22T21:00:00+00:00',epoch)
    assert len(selected)==1 and selected[0]['as_of']=='2023-02-22T21:00:00+00:00'


@pytest.fixture
def admitted_outpool_pair(full_source_guard):
    """Real guard -> real Book -> backend; fabricated HD/LYFT outside P."""
    x=full_source_guard;source=x.source;owner=source.binding['fill_owner_ref']
    assets=('HD','LYFT','A');days=pd.to_datetime(['2023-01-03','2023-01-04','2023-01-05'])
    rows=[dict(ticker=a,effective_start=days[0],effective_end=days[0] if a!='A' else pd.Timestamp('2025-12-31'),
        security_id='UID_'+a,security_id_type='CUSIP',cusip='UID_'+a,issuer_name='ISSUER_'+a,
        title_of_class='COM',moomoo_transport_code='US.'+a,mapping_status='RESOLVED',
        mapping_source='SYNTHETIC',source_filing='SYNTHETIC') for a in assets]
    raw=pd.DataFrame(dict(ticker=assets,trade_date=[days[1]]*3,code=['US.'+a for a in assets]))
    audits=pd.DataFrame(columns=source.AUDIT_COLUMNS);calls=[]
    class Reader:
        sources={k:owner for k in ('uid_intervals','raw_open_close','share_ca_audit')}
        def read(self,name,columns,*,date_field,start=None,stop=None,day=None,tickers=None):
            calls.append((name,dict(start=start,stop=stop,day=day,tickers=tickers,columns=columns)))
            frame={'uid_intervals':pd.DataFrame(rows),'raw_open_close':raw,'share_ca_audit':audits}[name]
            dates=pd.to_datetime(frame[date_field]);keep=dates.lt(pd.Timestamp('2026-01-01'))
            if start is not None:keep&=dates.ge(pd.Timestamp(start))
            if stop is not None:keep&=dates.lt(pd.Timestamp(stop))
            if day is not None:keep&=dates.eq(pd.Timestamp(day))
            if tickers is not None:keep&=frame.ticker.isin(tickers)
            return frame.loc[keep,list(columns)].copy()
    source.base=SimpleNamespace(master_assets=assets,market_dates=days,
        _components={'reader':Reader(),'refs':{'source':owner}})
    source.present=np.ones((3,3),bool)
    source.mapping=dict(records=[dict(ticker=a,start='2023-01-03',end='2026-01-01',
        coordinate='RAW_ACTUAL_SHARE',sid='FROZEN_RAW_TRANSPORT_CODE:US.'+a) for a in assets],
        basis_by_ticker={a:dict(kind='FROZEN_RAW_TRANSPORT_INSTRUMENT_COORDINATE',
            source_sid='FROZEN_RAW_TRANSPORT_CODE:US.'+a,source_ref=owner,not_a_CUSIP_claim=True) for a in assets})
    identities={a:dict(security_id='UID_'+a,security_id_type='CUSIP',cusip='UID_'+a,
        share_class='COM',raw_code='US.'+a,raw_actual_share_coordinate='RAW_ACTUAL_SHARE') for a in assets}
    book=inputs.HeldPositionLineageBook('OWN_JOINT',fill_owner_ref=owner,lineage_rule_ref=owner)
    seeds={a:dict(identities[a],qualified=True,historical_observations_relabelled=False,
        identity_asof=inputs.producer._clock(days[0]).isoformat(),seed_source_ref=owner,
        seed_source_row_identity='ORIGINAL_SEED_'+a,historical_source_epoch='HIST_'+a) for a in ('HD','LYFT')}
    book.note_qualified_decision(days[0],seeds)
    book.observe_fills(pd.DataFrame([dict(path_id='OWN_JOINT',order_id='BUY_'+a,ticker=a,side='BUY',
        signal_date=days[0],execution_date=days[1],fractional_shares=1.,index_units_before=0.,
        index_units_after=1.) for a in ('HD','LYFT')]))
    ctx=SimpleNamespace(tickers=assets,signal_date=days[1],signal_asof=inputs.producer._clock(days[1]),
        current_units=np.array([[1.,1.,0.]]),current_weights=np.array([[.1,.1,0.]]),
        decision_mask=np.ones((1,3),bool),buy_allowed=np.ones((1,3),bool))
    original=dict(mask=np.array([False,False,True]),record=dict(asset_uids={'A':'UID_A'},asset_epochs={'A':'EPOCH_A'}))
    return SimpleNamespace(source=source,book=book,ctx=ctx,original=original,rows=rows,raw=raw,
        audits=audits,calls=calls,owner=owner,identities=identities)


def test_held_backend_raw_commitment_from_real_guard_and_book_outside_pool(admitted_outpool_pair):
    from scripts.research.a2.risk import continuous_lw_support as backend
    x=admitted_outpool_pair;source=x.source.session(x.ctx,x.original,x.book)
    proofs=x.book.qualified_proofs(x.ctx,source['held_guards'])
    request=dict(decision_session='2023-01-04',current_identities=source['current_identities'],held_lineage_proofs=proofs)
    assert set(source['entry_seeds'])=={'A'} and set(proofs)=={'HD','LYFT'}
    assert len([c for c in x.calls if c[0]=='share_ca_audit'])==1
    for a in ('HD','LYFT'):
        rows=x.raw.loc[x.raw.ticker.eq(a)]
        assert proofs[a]['raw_exact_key_ref']['row_identity']==content_hash(rows.astype(str).to_dict('records'))
        assert proofs[a]['raw_exact_key_ref']['row_identity']!=content_hash(rows.iloc[0].to_dict())
        assert backend._held_current_identity(request,x.raw,a,'OWN_JOINT',x.owner)==x.identities[a]
    # Exact raw/source/seed commitment is still required, not an alias fallback.
    request['held_lineage_proofs']['HD']['raw_exact_key_ref']['row_identity']=content_hash(x.raw.iloc[0].to_dict())
    with pytest.raises(ValueError,match='SEED_IDENTITY'):
        backend._held_current_identity(request,x.raw,'HD','OWN_JOINT',x.owner)


@pytest.mark.parametrize('defect',['seed_uid','seed_type','coordinate','source_sha','raw_date','duplicate_raw'])
def test_held_backend_raw_commitment_cross_owner_conflicts_still_reject(admitted_outpool_pair,defect):
    from scripts.research.a2.risk import continuous_lw_support as backend
    x=admitted_outpool_pair;s=x.source.session(x.ctx,x.original,x.book)
    proofs=x.book.qualified_proofs(x.ctx,s['held_guards']);proof=proofs['HD']
    request=dict(decision_session='2023-01-04',current_identities=s['current_identities'],held_lineage_proofs=proofs)
    raw=x.raw.copy()
    if defect=='seed_uid':proof['seed_security_id']='OTHER'
    elif defect=='seed_type':proof['seed_security_id_type']='OTHER'
    elif defect=='coordinate':proof['raw_actual_share_coordinate']='ADJUSTED'
    elif defect=='source_sha':proof['raw_exact_key_ref']['source_ref']=dict(x.owner,sha256='b'*64)
    elif defect=='raw_date':raw.loc[raw.ticker.eq('HD'),'trade_date']=pd.Timestamp('2023-01-05')
    else:raw=pd.concat((raw,raw.loc[raw.ticker.eq('HD')]),ignore_index=True)
    with pytest.raises(ValueError):backend._held_current_identity(request,raw,'HD','OWN_JOINT',x.owner)


def test_audit_batch_exact_differing_prefixes_and_no_future_rows(admitted_outpool_pair):
    x=admitted_outpool_pair;s=x.source.session(x.ctx,x.original,x.book)
    x.book.qualified_proofs(x.ctx,s['held_guards']);x.calls.clear()
    x.ctx.signal_date=pd.Timestamp('2023-01-05');x.ctx.signal_asof=inputs.producer._clock(x.ctx.signal_date)
    x.raw['trade_date']=x.ctx.signal_date
    lineages=x.book.source_lineages();lineages['LYFT'][0]['seed']['signal_session']='2023-01-04'
    proxy=SimpleNamespace(account_id=x.book.account_id,required_guard_assets=x.book.required_guard_assets,
        source_lineages=lambda:deepcopy(lineages))
    for ticker,date in [('HD','2023-01-03'),('LYFT','2023-01-03'),('LYFT','2023-01-04'),
                        ('LYFT','2023-01-05'),('LYFT','2023-01-06'),('HD','2026-01-01')]:
        x.audits.loc[len(x.audits)]=dict(ticker=ticker,event_date=pd.Timestamp(date),source_event_date=pd.Timestamp(date),
            code='US.'+ticker,audit_kind='PRICE_DIAGNOSTIC',share_event=False,manual_wolf=False,aligned_to_next_session=False)
    result=x.source.session(x.ctx,x.original,proxy)
    calls=[c for c in x.calls if c[0]=='share_ca_audit'];assert len(calls)==1
    assert calls[0][1]['start']==pd.Timestamp('2023-01-03') and calls[0][1]['stop']==pd.Timestamp('2023-01-06')
    assert calls[0][1]['tickers']==('HD','LYFT')
    for a,start in [('HD','2023-01-03'),('LYFT','2023-01-04')]:
        old=x.audits.loc[x.audits.ticker.eq(a)&pd.to_datetime(x.audits.event_date).ge(pd.Timestamp(start))
            &pd.to_datetime(x.audits.event_date).lt(pd.Timestamp('2023-01-06'))]
        observed=result['held_guards'][a]['nonshare_quote_diagnostics']
        assert observed==[{k:r.get(k) for k in ('ticker','event_date','audit_kind','code')} for r in old.to_dict('records')]
        assert result['held_guards'][a]['quote_qualification_granted'] is False


@pytest.mark.parametrize('share_event,manual',[(True,False),(False,True)])
def test_audit_batch_keeps_real_unhandled_share_source_blocker(admitted_outpool_pair,share_event,manual):
    x=admitted_outpool_pair
    x.audits.loc[0]=dict(ticker='LYFT',event_date=x.ctx.signal_date,source_event_date=x.ctx.signal_date,
        code='US.LYFT',audit_kind='REAL_SHARE',share_event=share_event,manual_wolf=manual,aligned_to_next_session=False)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNSUPPORTED_DECLARED'):
        x.source.session(x.ctx,x.original,x.book)
    assert len([c for c in x.calls if c[0]=='share_ca_audit'])==1
    assert x.book.pending_fill_count==2 and not x.book.held_assets


def test_audit_batch_keeps_prior_identity_first_failure_without_audit_read(admitted_outpool_pair):
    x=admitted_outpool_pair;x.rows[0]['title_of_class']='OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable,match='SECURITY_COORDINATE'):
        x.source.session(x.ctx,x.original,x.book)
    assert not any(c[0]=='share_ca_audit' for c in x.calls)


def test_audit_batch_empty_needed_does_not_read_or_construct_holding(admitted_outpool_pair):
    x=admitted_outpool_pair;x.ctx.current_units[:]=0.;x.ctx.current_weights[:]=0.
    empty=inputs.HeldPositionLineageBook('OWN_JOINT',fill_owner_ref=x.owner,lineage_rule_ref=x.owner)
    result=x.source.session(x.ctx,x.original,empty)
    assert result['held_guards']=={} and set(result['entry_seeds'])=={'A'}
    assert not any(c[0]=='share_ca_audit' for c in x.calls)


def test_continuous_prepare_history_schema_preserves_availability_and_uid_epoch_guards(monkeypatch):
    """Exercise the real prepare path up to the original assembler boundary."""
    from scripts.research.a2.risk import continuous_lw_support as backend
    b=backend;days=pd.bdate_range('2021-01-04',periods=320);day=days[-1];prior_day=days[-2]
    feature_dates=[days[0],days[-20],prior_day,day]
    features=pd.DataFrame(dict(ticker=['A']*4,signal_date=feature_dates,
        security_id=['OLD_UID','UID_A','UID_A','UID_A']))
    source_ref={'path':'D:/synthetic/source.json','sha256':'a'*64}
    refs={k:{'path':'D:/synthetic/'+k+'.parquet','sha256':'a'*64} for k in
        ('extended_shareholder_y5','prediction_features','uid_intervals','raw_open_close')}
    interval=pd.DataFrame([dict(ticker='A',effective_start=days[0],effective_end=day,
        security_id='UID_A',security_id_type='CUSIP',cusip='UID_A',issuer_name='ISSUER_A',
        title_of_class='COM',moomoo_transport_code='US.A',mapping_status='RESOLVED',
        mapping_source='SYNTHETIC',source_filing='SYNTHETIC',report_quarter='SYNTHETIC')])
    reads=[]
    class Reader:
        sources=refs;phase='support'
        def read(self,name,columns,**kwargs):
            reads.append((name,tuple(columns),deepcopy(kwargs)))
            if name=='prediction_features':return features.copy()
            if name=='uid_intervals':return interval.loc[:,list(columns)].copy()
            if name=='raw_open_close':
                return pd.DataFrame([dict(ticker='A',trade_date=day,code='US.A')])
            return pd.DataFrame(columns=columns)
    primary=dict(event_id='PRIMARY_A',signature_sha256='b'*64)
    original=dict(record=dict(assets=['A'],asset_uids={'A':'UID_A'},asset_epochs={'A':'CURRENT_EPOCH'}),
        event=dict(segment_starts={'A':str(days[-20].date())},
            dependency_local_event_ids={'PRIMARY':primary['event_id']},
            dependency_local_signature_sha256={'PRIMARY':primary['signature_sha256']}))
    components=dict(reader=Reader(),calendar=days,refs={'source':source_ref},support={'events':[]})
    base=SimpleNamespace(_components=components,_initialize=lambda:None,_domain=lambda *args:original)
    engine=object.__new__(b.ContinuousLWEstimator)
    engine.base=base;engine._source={'sources':refs};engine.science={};engine.account_id='OWN'
    engine.freeze={};engine.descriptor_bridges=None
    engine._producer_custody=lambda:source_ref
    monkeypatch.setattr(b.old,'_receipt',lambda *a,**k:SimpleNamespace(return_coordinate='SYNTHETIC_COORDINATE'))
    captured=[]
    class AssemblyBoundary(Exception):pass
    def capture(bound,calendar,**kwargs):
        captured.append(deepcopy(kwargs))
        raise AssemblyBoundary
    monkeypatch.setattr(b.event_owner,'assemble_risk_inputs',capture)
    request=dict(decision_session=str(day.date()),as_of=b.event_owner._clock(day).isoformat(),
        cutoff=b.event_owner._clock(prior_day).isoformat(),P=['A'],H=[],D=['A'],U=['A'],
        original_primary_dependency_epoch=primary,current_identities={})
    with pytest.raises(AssemblyBoundary):engine._prepare(request)
    history=captured[0]['identity_history']
    assert list(history.columns)==['ticker','signal_date','security_id','available_at','identity_epoch']
    assert list(history.security_id)==['OLD_UID','UID_A','UID_A']
    assert list(history.identity_epoch)==['PRIOR_OBSERVED_UID_EPOCH','CURRENT_EPOCH','CURRENT_EPOCH']
    assert list(history.available_at)==[b.old._clock(d) for d in feature_dates[:-1]]
    assert history.signal_date.max()==prior_day and list(features.columns)==['ticker','signal_date','security_id']
    assert all(columns!=('ticker','signal_date','security_id','y_open5') for _,columns,_ in reads)


@pytest.fixture
def descriptor_bridge_document(monkeypatch):
    ref=lambda label:dict(path='D:/synthetic/'+label+'.json',sha256='a'*64)
    uidref=dict(path='D:/synthetic/uid.parquet',sha256='cafd53e665143e56d31c3f7b5299593a099fc53a0032879d63fbd8abae6a0d30')
    coordinate=dict(security_id='65345M108',security_id_type='CUSIP',cusip='65345M108',
        raw_code='US.NXDR',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    rows=[]
    for title,start,end,filing in [('COM CL A','2023-02-22','2023-05-22','OLD'),
                                 ('Common Stock','2023-05-23','2023-08-20','FIRST;SECOND')]:
        row=dict(ticker='NXDR',effective_start=pd.Timestamp(start),effective_end=pd.Timestamp(end),
            security_id=coordinate['security_id'],security_id_type='CUSIP',cusip=coordinate['cusip'],
            issuer_name='ORIGINAL ISSUER',title_of_class=title,moomoo_transport_code='US.NXDR',
            mapping_status='RESOLVED',mapping_source='ORIGINAL',source_filing=filing)
        rows.append(dict(source_row=row,source_row_content_sha256=content_hash(row),
            identity=dict(coordinate,share_class=title)))
    scope=dict(scope='EXACT_ISSUER_CUSIP_CLASS_SPECIFIC_SOURCE_DESCRIPTOR_EQUIVALENCE_FOR_RETAINED_ACCOUNT_IDENTITY_ONLY',
        source_row_identity_commitments_required=[r['source_row_content_sha256'] for r in rows],
        buy_permission_extension_allowed=False,class_B_or_preferred_or_warrant_bridge_allowed=False,
        cross_cusip_substitution_allowed=False,membership_interval_extension_allowed=False,
        new_ticker_alias_inference_allowed=False)
    facts=[dict(ACCESSION_NUMBER=a,CUSIP='65345M108',SSHPRNAMTTYPE='SH',PUTCALL=None,TITLEOFCLASS=c)
        for a,c in [('OLD','COM CL A'),('FIRST','COM CL A'),('SECOND','Common Stock')]]
    doc=dict(schema='B_ISSUER_CUSIP_SOURCE_BOUND_SHARE_CLASS_DESCRIPTOR_BRIDGE_V1',
        status='SOURCE_FACTS_VERIFIED_BRIDGE_CANDIDATE_NOT_RUNTIME_ADMISSION',
        original_interval_authority_unchanged=True,bridge_binding_requirements=scope,
        authority=dict(research_identity_descriptor_evidence_only=True,strict_PIT=False,
            production_qualified=False,quote_qualified=False,certified_NAV=False),
        subject=dict(security_id='65345M108',security_id_type='CUSIP',cusip='65345M108',
            share_unit='RAW_ACTUAL_SHARE',source_descriptor_pair=['COM CL A','Common Stock']),
        original_interval_rows=rows,existing_official_dataset_refs=[dict(path=ref('13f')['path'],physical_sha256='a'*64)],
        existing_official_dataset_identity_rows=facts,
        existing_official_dataset_submission_rows=[dict(ACCESSION_NUMBER=a,FILING_DATE=d,PERIODOFREPORT=q)
            for a,d,q in [('OLD','14-FEB-2023','31-DEC-2022'),('FIRST','15-MAY-2023','31-MAR-2023'),
                           ('SECOND','17-APR-2023','31-MAR-2023')]],
        identity_source_filing_availability=dict(historical_bridge_available_at=None))
    pins=[]
    interface=SimpleNamespace(pin=lambda r:(pins.append(deepcopy(r)),r['path'])[1],read=lambda p:deepcopy(doc))
    return SimpleNamespace(doc=doc,reference=ref('bridge'),uidref=uidref,coordinate=coordinate,
        pins=pins,load=lambda:inputs._load_share_class_descriptor_bridge(interface,ref('bridge'),uidref))


def test_source_descriptor_bridge_binds_original_rows_and_does_not_rewrite(descriptor_bridge_document):
    x=descriptor_bridge_document;before=deepcopy(x.doc);bridge=x.load()
    old=dict(x.coordinate,share_class='COM CL A');new=dict(old,share_class='Common Stock')
    assert not inputs._held_security_identity_equal(old,new)
    assert inputs._held_security_identity_equal(old,new,bridge)
    assert inputs._held_security_identity_equal(new,old,bridge)
    assert x.doc==before and content_hash(old)!=content_hash(new)
    assert len(x.pins)==2 and bridge[0]['historical_availability_qualified'] is False
    assert bridge[0]['historical_bridge_available_at'] is None
    assert all(inputs._held_source_row_descriptor_bridge(r,old,bridge) for r in bridge[0]['original_rows'])


@pytest.mark.parametrize('defect',[ 'status','PIT','permission','UID','raw_unit','duplicate_descriptor',
    'row_hash','class_B','coordinate','date2026','filing_future','putcall','share_unit','report_mismatch','uid_source'])
def test_source_descriptor_bridge_rejects_unproved_source_scope(descriptor_bridge_document,defect):
    x=descriptor_bridge_document;d=x.doc
    if defect=='status':d['status']='PASS'
    elif defect=='PIT':d['authority']['strict_PIT']=True
    elif defect=='permission':d['bridge_binding_requirements']['buy_permission_extension_allowed']=True
    elif defect=='UID':d['subject']['security_id']='OTHER'
    elif defect=='raw_unit':d['subject']['share_unit']='INDEX_UNITS'
    elif defect=='duplicate_descriptor':d['subject']['source_descriptor_pair']=['COM CL A']*2
    elif defect=='row_hash':d['original_interval_rows'][1]['source_row']['source_filing']='ALTERED'
    elif defect=='class_B':d['original_interval_rows'][1]['identity']['share_class']='Class B'
    elif defect=='coordinate':d['original_interval_rows'][1]['identity']['raw_code']='OTHER'
    elif defect=='date2026':d['original_interval_rows'][1]['source_row']['effective_end']=pd.Timestamp('2026-01-02')
    elif defect=='filing_future':d['existing_official_dataset_submission_rows'][2]['FILING_DATE']='01-JUN-2023'
    elif defect=='putcall':d['existing_official_dataset_identity_rows'][2]['PUTCALL']='CALL'
    elif defect=='share_unit':d['existing_official_dataset_identity_rows'][2]['SSHPRNAMTTYPE']='PRN'
    elif defect=='report_mismatch':d['existing_official_dataset_submission_rows'][2]['PERIODOFREPORT']='30-JUN-2023'
    else:x.uidref['sha256']='b'*64
    with pytest.raises((inputs.HeldLineageUnavailable,inputs.ExistingRiskInputUnavailable,ValueError)):
        x.load()


@pytest.mark.parametrize('field,value',[('security_id','OTHER'),('cusip','OTHER'),('security_id_type','UNKNOWN'),
    ('raw_code','US.OTHER'),('raw_actual_share_coordinate','INDEX_UNIT'),('share_class','Class B'),
    ('share_class','Common stock'),('share_class','UNKNOWN')])
def test_descriptor_bridge_never_relaxes_other_coordinates(descriptor_bridge_document,field,value):
    x=descriptor_bridge_document;bridge=x.load();old=dict(x.coordinate,share_class='COM CL A')
    new=dict(old,share_class='Common Stock');new[field]=value
    assert not inputs._held_security_identity_equal(old,new,bridge)


def test_descriptor_bridge_cannot_extend_source_intervals_or_new_row(descriptor_bridge_document):
    x=descriptor_bridge_document;bridge=x.load();old=dict(x.coordinate,share_class='COM CL A')
    row=deepcopy(bridge[0]['original_rows'][1]);row['effective_end']=pd.Timestamp('2025-12-31')
    assert not inputs._held_source_row_descriptor_bridge(row,old,bridge)
    row=deepcopy(bridge[0]['original_rows'][1]);row['source_filing']='NEW_UNPROVED_FILING'
    assert not inputs._held_source_row_descriptor_bridge(row,old,bridge)


def test_descriptor_bridge_real_book_add_preserves_original_spell_and_both_seeds(held_book):
    x=held_book;x.identity['share_class']='COM CL A'
    coordinates={k:v for k,v in x.identity.items() if k!='share_class'}
    x.book.descriptor_bridges=(dict(coordinates=coordinates,descriptors=('COM CL A','Common Stock')),)
    first=x.admitted();seed_source=first['seed_source_row_identity']
    x.book.note_qualified_decision('2023-01-04',{'A':dict(x.seed('2023-01-04'),share_class='Common Stock')})
    x.book.observe_fills(x.fill(q=1.,before=1.,order='ADD',signal='2023-01-04',day='2023-01-05'))
    assert len(x.book.source_lineages()['A'])==1
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),
        {'A':x.guard('2023-01-05',share_class='Common Stock')})['A']
    assert proof['position_id']==first['position_id'] and proof['seed_share_class']=='COM CL A'
    assert proof['seed_source_row_identity']==seed_source
    assert x.book.source_lineages()['A'][0]['identity']['share_class']=='COM CL A'
    assert len(proof['quantity_transition_refs'])==1


def test_descriptor_bridge_original_dated_guard_rows_are_still_required(full_source_guard):
    x=full_source_guard;x.identity['share_class']='COM CL A';x.spell['seed']['share_class']='COM CL A'
    x.rows[0]['title_of_class']='COM CL A'
    newer=dict(x.rows[0],effective_start=pd.Timestamp('2023-01-04'),effective_end=pd.Timestamp('2023-01-05'),
        title_of_class='Common Stock',source_filing='SECOND_ORIGINAL_SOURCE')
    x.rows.append(newer);coordinates={k:v for k,v in x.identity.items() if k!='share_class'}
    bridge=dict(coordinates=coordinates,descriptors=('COM CL A','Common Stock'),
        row_hashes=tuple(content_hash(r) for r in (x.rows[0],newer)),source_ref=x.source.binding['mapping_ref'])
    x.source.descriptor_bridges=(bridge,);before=deepcopy(x.rows)
    result=x.source.session(x.ctx,x.original,x.book)
    assert result['held_guards']['OUT']['share_class']=='COM CL A' and x.rows==before
    assert result['held_guards']['OUT']['processed_event_fingerprints']==[]
    x.rows[-1]['source_filing']='UNPROVED_OTHER_SOURCE'
    with pytest.raises(inputs.HeldLineageUnavailable,match='HELD_DATED_SECURITY_COORDINATE_CONFLICT'):
        x.source.session(x.ctx,x.original,x.book)


@pytest.mark.parametrize('defect',['none','actual','inherited','context','source_pin','other_field'])
def test_fast_track_actual_typed_owner_descendant_is_exact(freeze_metadata,monkeypatch,defect):
    from pathlib import Path
    from scripts.research.a2.risk import continuous_lw_support as backend
    x=freeze_metadata;ref=lambda name:dict(path='D:/synthetic/'+name+'.json',sha256='a'*64)
    old=ref('original_binding');derived=ref('derived_binding');actual=ref('canonical_cash_owner');oldtype=ref('79cb')
    original_binding=dict(typed_ca_owner_ref=oldtype,unchanged_input='ORIGINAL')
    x.docs[old['path']]=original_binding
    x.docs[derived['path']]=dict(original_binding,task_id=backend.TASK,status='FROZEN_SOURCE_BOUND_RUNTIME_ACCEPTANCE_PENDING',
        parent_binding_ref=old,source_binding_revision='AUTHORIZED_FAST_TRACK_SOURCE_AND_EXACT_CASH_NAMESPACE_DESCENDANT',
        source_account_contract_ref=ref('new_source_contract'),typed_ca_owner_ref=actual,inherited_typed_ca_owner_ref=oldtype)
    config=ref('config');x.docs[config['path']]=dict(schema='B_FAST_TRACK_HUMAN_AUTHORIZED_RESEARCH_CONFIG_V1',
        task_id=backend.TASK,status='FROZEN_RESEARCH_CONFIGURATION',continuous_lw_rule=backend.CONTINUOUS_LW_RULE)
    x.accepted['held_identity_source_binding_ref']=old
    x.freeze.update(task_id=backend.TASK,continuous_lw_rule=deepcopy(backend.CONTINUOUS_LW_RULE),
        held_identity_source_binding_ref=derived,inherited_held_identity_source_binding_ref=old,
        research_config_ref=config,continuous_lw_source_science=dict(scientific_contract_sha256=config['sha256']),
        source_account_contract_ref=ref('new_source_contract'),frozen_history_cash_owner_ref=actual)
    x.freeze['source_pins']=[dict(path=str(Path(inputs.__file__).resolve()),sha256='a'*64),
        dict(path=str(Path(backend.__file__).resolve()),sha256='a'*64),actual]
    context=dict(typed_ca_owner_ref=actual)
    if defect=='actual':x.docs[derived['path']]['typed_ca_owner_ref']=ref('OTHER')
    elif defect=='inherited':x.docs[derived['path']]['inherited_typed_ca_owner_ref']=actual
    elif defect=='context':context['typed_ca_owner_ref']=oldtype
    elif defect=='source_pin':x.freeze['source_pins'].pop()
    elif defect=='other_field':x.docs[derived['path']]['unchanged_input']='ALTERED'
    monkeypatch.setattr(backend,'make_continuous_lw_estimator',lambda *a,**k:SimpleNamespace())
    def factory():return inputs.ContinuousCausalLWInputs.from_freeze(freeze=x.freeze,
        base_shared=x.causal.example.provider,account_id='NEW',market_dates=x.causal.example.provider.market_dates,
        master_assets=x.causal.example.provider.master_assets,source_context=context)
    if defect=='none':assert factory().supplemental_loads_count==0
    else:
        with pytest.raises(inputs.ExistingRiskInputUnavailable):factory()


@pytest.fixture
def descriptor_bridge_extension_document(descriptor_bridge_document):
    x=descriptor_bridge_document;base=x.load();entries=[]
    for r in x.doc['original_interval_rows']:
        entries.append(dict(source_row=deepcopy(r['source_row']),source_row_content_sha256=r['source_row_content_sha256'],
            status='VERIFIED_BY_UNCHANGED_BASE_SOURCE_RECEIPT',bridge_allowed=True,membership_interval_unchanged=True))
    starts=['2023-08-21','2023-11-21','2024-02-22','2024-05-22','2024-08-21','2024-11-21']
    reports=['2023-06-30','2023-09-30','2023-12-31','2024-03-31','2024-06-30','2024-09-30']
    for i,(start,report) in enumerate(zip(starts,reports)):
        day=pd.Timestamp(start);first,second='EXPLICIT_'+str(i),'GENERIC_'+str(i)
        row=dict(x.doc['original_interval_rows'][1]['source_row'],effective_start=day,
            effective_end=pd.Timestamp(starts[i+1])-pd.Timedelta(days=1) if i<5 else pd.Timestamp('2025-02-23'),
            source_filing=first+';'+second)
        facts=[]
        for accession,title in [(first,'COM CL A'),(second,'Common Stock')]:
            filing=day-pd.Timedelta(days=7)
            facts.append(dict(report_date_iso=report,filing_date_iso=str(filing.date()),
                identity_row=dict(ACCESSION_NUMBER=accession,NAMEOFISSUER=row['issuer_name'],CUSIP=x.coordinate['cusip'],SSHPRNAMTTYPE='SH',PUTCALL=None,TITLEOFCLASS=title),
                submission_row=dict(ACCESSION_NUMBER=accession,FILING_DATE=str(filing.date()),PERIODOFREPORT=report)))
        entries.append(dict(source_row=row,source_row_content_sha256=content_hash(row),
            status='VERIFIED_EXACT_SAME_REPORT_DESCRIPTOR_PAIR',bridge_allowed=True,membership_interval_unchanged=True,
            original_source_filing_accessions=[first,second],same_report_descriptor_pair_observed=True,source_facts=facts))
    blocked=[]
    for start,end in [('2025-02-24','2025-05-21'),('2025-05-22','2025-08-21'),
                      ('2025-08-22','2025-11-20'),('2025-11-21','2025-12-31')]:
        row=dict(entries[-1]['source_row'],effective_start=pd.Timestamp(start),effective_end=pd.Timestamp(end),source_filing='GENERIC_ONLY')
        digest=content_hash(row);blocked.append(digest)
        entries.append(dict(source_row=row,source_row_content_sha256=digest,bridge_allowed=False,membership_interval_unchanged=True,
            status='BLOCKED_NO_CLASS_EXPLICIT_SAME_REPORT_COUNTERPART_IN_ORIGINAL_SOURCE_FILINGS'))
    doc=dict(schema='B_NXDR_DATED_DESCRIPTOR_SOURCE_COMPLETENESS_EXTENSION_V1',
        status='PARTIAL_SOURCE_FACT_EXTENSION_COMPLETE_NOT_RUNTIME_ADMISSION',
        base_receipt=dict(path=x.reference['path'],physical_sha256=x.reference['sha256'],unchanged=True),
        authority=deepcopy(x.doc['authority']),subject=deepcopy(x.doc['subject']),
        uid_interval_source=dict(path=x.uidref['path'],accepted_immutable_physical_sha256=x.uidref['sha256']),
        bridge_binding_requirements=deepcopy(x.doc['bridge_binding_requirements']),
        original_interval_assessments=entries,blocked_original_row_content_sha256=blocked,
        new_existing_official_dataset_refs=[dict(path='D:/synthetic/new13f.parquet',physical_sha256='b'*64)],
        counts=dict(additional_same_report_source_proven_rows=6,unchanged_base_bridge_rows=2,bridge_bound_rows_total=8))
    doc['bridge_binding_requirements']['source_row_identity_commitments_required']=[r['source_row_content_sha256'] for r in entries if r['bridge_allowed']]
    reference=dict(path='D:/synthetic/extension.json',sha256='c'*64);pins=[]
    interface=SimpleNamespace(pin=lambda r:(pins.append(deepcopy(r)),r['path'])[1],read=lambda p:deepcopy(doc))
    return SimpleNamespace(base=x,bridges=base,doc=doc,pins=pins,reference=reference,
        load=lambda:inputs._extend_share_class_descriptor_bridge(interface,base,reference,x.uidref))


def test_descriptor_extension_adds_only_six_proven_original_rows(descriptor_bridge_extension_document):
    x=descriptor_bridge_extension_document;before=deepcopy((x.bridges,x.doc));extended=x.load()
    assert len(extended)==1 and len(extended[0]['row_hashes'])==8
    assert set(x.bridges[0]['row_hashes']).issubset(extended[0]['row_hashes'])
    assert extended[0]['source_ref']==x.bridges[0]['source_ref'] and len(x.pins)==2
    identity=dict(x.base.coordinate,share_class='COM CL A')
    for r in x.doc['original_interval_assessments']:
        matched=inputs._held_source_row_descriptor_bridge(r['source_row'],identity,extended)
        assert matched==r['bridge_allowed']
    assert (x.bridges,x.doc)==before and len(extended[0]['blocked_original_row_hashes'])==4
    assert extended[0]['historical_availability_qualified'] is False


@pytest.mark.parametrize('defect',['base_ref','unchanged','uid_source','PIT','permission','subject','row_hash','raw',
    'other_CUSIP','interval_extend','missing_fact','classB','report','filing','accession','PUTCALL','unit','blocked_admission',
    'duplicate_row','missing_base','approved_hashes','blocked_hashes'])
def test_descriptor_extension_rejects_unproved_rows_and_filing_pairs(descriptor_bridge_extension_document,defect):
    x=descriptor_bridge_extension_document;doc=x.doc;r=doc['original_interval_assessments'][2]
    if defect=='base_ref':doc['base_receipt']['physical_sha256']='d'*64
    elif defect=='unchanged':doc['base_receipt']['unchanged']=False
    elif defect=='uid_source':doc['uid_interval_source']['accepted_immutable_physical_sha256']='d'*64
    elif defect=='PIT':doc['authority']['strict_PIT']=True
    elif defect=='permission':doc['bridge_binding_requirements']['membership_interval_extension_allowed']=True
    elif defect=='subject':doc['subject']['cusip']='OTHER'
    elif defect=='row_hash':r['source_row']['source_filing']='ALTERED'
    elif defect=='raw':
        r['source_row']['moomoo_transport_code']='OTHER';r['source_row_content_sha256']=content_hash(r['source_row'])
    elif defect=='other_CUSIP':r['source_facts'][0]['identity_row']['CUSIP']='OTHER'
    elif defect=='interval_extend':r['source_row']['effective_end']+=pd.Timedelta(days=1)
    elif defect=='missing_fact':r['source_facts'].pop()
    elif defect=='classB':r['source_facts'][0]['identity_row']['TITLEOFCLASS']='Class B'
    elif defect=='report':r['source_facts'][0]['report_date_iso']='2023-03-31'
    elif defect=='filing':r['source_facts'][0]['filing_date_iso']='2023-08-22'
    elif defect=='accession':r['source_facts'][0]['identity_row']['ACCESSION_NUMBER']='OTHER'
    elif defect=='PUTCALL':r['source_facts'][0]['identity_row']['PUTCALL']='PUT'
    elif defect=='unit':r['source_facts'][0]['identity_row']['SSHPRNAMTTYPE']='PRN'
    elif defect=='blocked_admission':doc['original_interval_assessments'][-1]['bridge_allowed']=True
    elif defect=='duplicate_row':doc['original_interval_assessments'].append(deepcopy(r))
    elif defect=='missing_base':doc['original_interval_assessments'].pop(0)
    elif defect=='approved_hashes':doc['bridge_binding_requirements']['source_row_identity_commitments_required'].pop()
    else:doc['blocked_original_row_content_sha256'].pop()
    before=deepcopy(x.bridges)
    with pytest.raises((inputs.ExistingRiskInputUnavailable,inputs.HeldLineageUnavailable,KeyError)):
        x.load()
    assert x.bridges==before


@pytest.fixture
def descriptor_other_filer_document(descriptor_bridge_extension_document):
    x=descriptor_bridge_extension_document;doc=x.doc;entry=doc['original_interval_assessments'][8]
    row=entry['source_row'];original=row['source_filing'];extra='CLASS_A_OTHER_FILER'
    filing=pd.Timestamp(row['effective_start'])-pd.Timedelta(days=7);report='2024-12-31'
    identity_ref=dict(path='D:/synthetic/new13f.parquet',sha256='b'*64)
    submission_ref=dict(path='D:/synthetic/new_submission.parquet',sha256='d'*64)
    doc['new_existing_official_dataset_refs'].append(dict(path=submission_ref['path'],physical_sha256=submission_ref['sha256']))
    facts=[]
    for i,(accession,title,role) in enumerate([(original,'Common Stock','ORIGINAL_ARK_GENERIC_SOURCE'),
            (extra,'COM CL A','ADDITIONAL_OTHER_FILER_CLASS_EXPLICIT_SOURCE')]):
        identity=dict(ACCESSION_NUMBER=accession,INFOTABLE_SK=str(100+i),CUSIP=x.base.coordinate['cusip'],
            NAMEOFISSUER=row['issuer_name'].lower() if i else row['issuer_name'],SSHPRNAMTTYPE='SH',PUTCALL=None,TITLEOFCLASS=title)
        submission=dict(ACCESSION_NUMBER=accession,FILING_DATE=str(filing.date()),PERIODOFREPORT=report,SUBMISSIONTYPE='13F-HR')
        facts.append(dict(role=role,report_date_iso=report,filing_date_iso=str(filing.date()),
            identity_row=identity,submission_row=submission,identity_source_ref=deepcopy(identity_ref),
            submission_source_ref=deepcopy(submission_ref),identity_row_content_sha256=content_hash(identity),
            submission_row_content_sha256=content_hash(submission)))
    entry.update(status='VERIFIED_EXACT_SAME_REPORT_DESCRIPTOR_PAIR',bridge_allowed=True,
        original_source_filing_accessions=[original],counterpart_source_accessions=[extra],
        counterpart_source_binding_kind='EXISTING_OFFICIAL_SAME_REPORT_CUSIP_CLASS_COUNTERPART',
        same_report_descriptor_pair_observed=True,source_facts=facts)
    doc['blocked_original_row_content_sha256'].remove(entry['source_row_content_sha256'])
    doc['bridge_binding_requirements']['source_row_identity_commitments_required'].append(entry['source_row_content_sha256'])
    doc['counts'].update(additional_same_report_source_proven_rows=7,bridge_bound_rows_total=9)
    return x


def test_descriptor_other_filer_preserves_original_filing_and_exact_sk_commitments(descriptor_other_filer_document):
    x=descriptor_other_filer_document;before=deepcopy((x.bridges,x.doc));extended=x.load()
    assert len(extended[0]['row_hashes'])==9 and len(extended[0]['blocked_original_row_hashes'])==3
    row=x.doc['original_interval_assessments'][8]['source_row']
    assert row['source_filing']=='GENERIC_ONLY'
    assert inputs._held_source_row_descriptor_bridge(row,dict(x.base.coordinate,share_class='COM CL A'),extended)
    assert (x.bridges,x.doc)==before and len(x.pins)==3
    assert extended[0]['historical_availability_qualified'] is False


@pytest.mark.parametrize('defect',['kind','duplicate_accession','original_overlap','missing_extra','missing_original',
    'roles','original_role','extra_role','SK','identity_hash','submission_hash','identity_ref','submission_ref',
    'unlisted_ref','submission_type','original_descriptor','extra_descriptor','report','late_filing',
    'CUSIP','PUTCALL','share_unit','row_hash','membership','counts','blocked_hashes'])
def test_descriptor_other_filer_rejects_unbound_identity_source_and_clock(descriptor_other_filer_document,defect):
    x=descriptor_other_filer_document;doc=x.doc;r=doc['original_interval_assessments'][8];original,extra=r['source_facts']
    if defect=='kind':r['counterpart_source_binding_kind']='GUESS'
    elif defect=='duplicate_accession':r['counterpart_source_accessions']*=2
    elif defect=='original_overlap':r['counterpart_source_accessions']=[r['source_row']['source_filing']]
    elif defect=='missing_extra':r['counterpart_source_accessions']=['OTHER']
    elif defect=='missing_original':original['identity_row']['ACCESSION_NUMBER']='OTHER'
    elif defect=='roles':extra['role']=original['role']
    elif defect=='original_role':original['role']='ADDITIONAL_OTHER_FILER_CLASS_EXPLICIT_SOURCE'
    elif defect=='extra_role':extra['role']='ORIGINAL_ARK_GENERIC_SOURCE'
    elif defect=='SK':extra['identity_row']['INFOTABLE_SK']='UNKNOWN';extra['identity_row_content_sha256']=content_hash(extra['identity_row'])
    elif defect=='identity_hash':extra['identity_row']['INFOTABLE_SK']='ALTERED'
    elif defect=='submission_hash':extra['submission_row']['CIK']='ALTERED'
    elif defect=='identity_ref':extra['identity_source_ref']['sha256']='e'*64
    elif defect=='submission_ref':extra['submission_source_ref']['sha256']='e'*64
    elif defect=='unlisted_ref':extra['identity_source_ref']['path']='D:/synthetic/unlisted.parquet'
    elif defect=='submission_type':extra['submission_row']['SUBMISSIONTYPE']='13F-NT';extra['submission_row_content_sha256']=content_hash(extra['submission_row'])
    elif defect=='original_descriptor':
        original['identity_row']['TITLEOFCLASS']='COM CL A';extra['identity_row']['TITLEOFCLASS']='Common Stock'
        for f in r['source_facts']:f['identity_row_content_sha256']=content_hash(f['identity_row'])
    elif defect=='extra_descriptor':extra['identity_row']['TITLEOFCLASS']='Class B';extra['identity_row_content_sha256']=content_hash(extra['identity_row'])
    elif defect=='report':extra['report_date_iso']='2024-09-30'
    elif defect=='late_filing':
        extra['filing_date_iso']='2025-02-25';extra['submission_row']['FILING_DATE']='2025-02-25'
        extra['submission_row_content_sha256']=content_hash(extra['submission_row'])
    elif defect=='CUSIP':extra['identity_row']['CUSIP']='OTHER';extra['identity_row_content_sha256']=content_hash(extra['identity_row'])
    elif defect=='PUTCALL':extra['identity_row']['PUTCALL']='PUT';extra['identity_row_content_sha256']=content_hash(extra['identity_row'])
    elif defect=='share_unit':extra['identity_row']['SSHPRNAMTTYPE']='PRN';extra['identity_row_content_sha256']=content_hash(extra['identity_row'])
    elif defect=='row_hash':r['source_row']['source_filing']='REPLACED'
    elif defect=='membership':r['membership_interval_unchanged']=False
    elif defect=='counts':doc['counts']['additional_same_report_source_proven_rows']=6
    else:doc['blocked_original_row_content_sha256'].append(r['source_row_content_sha256'])
    before=deepcopy(x.bridges)
    with pytest.raises((inputs.ExistingRiskInputUnavailable,inputs.HeldLineageUnavailable,KeyError)):
        x.load()
    assert x.bridges==before


@pytest.mark.parametrize('name',['OTHER ISSUER',' ORIGINAL ISSUER','ORIGINAL  ISSUER','ORIGINAL ISSUER.',
    'ISSUER ORIGINAL','ORIGINAL\u00a0ISSUER','',None,True])
def test_descriptor_extension_rejects_non_case_issuer_changes(descriptor_other_filer_document,name):
    x=descriptor_other_filer_document;fact=x.doc['original_interval_assessments'][8]['source_facts'][1]
    fact['identity_row']['NAMEOFISSUER']=name
    fact['identity_row_content_sha256']=content_hash(fact['identity_row'])
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match='EXACT_ASCII_CASE_ONLY_SOURCE_ISSUER_BINDING_REQUIRED'):
        x.load()


@pytest.fixture
def parent_cash_mapping_guard(issuer_mapping_guard):
    f=issuer_mapping_guard;event=f.source.cash_events[0]['event']
    event.event_id='ORIGINAL_CASH_EVENT'
    event.source_reference='https://synthetic.invalid/original-cash'
    event.source_fingerprint='e'*64
    event.available_at='2025-09-04T23:59:59Z'
    current=deepcopy(f.envelope)
    current.update(source_reference='https://synthetic.invalid/current-identity',
        source_fingerprint='f'*64,available_at='2025-09-06T00:00:00Z')
    proof=dict(event_fingerprint='LATE_CASH_LABEL',identity=current,
        event_binding_role='EXACT_PARENT_CASH_CORROBORATION_NO_NEW_EVENT',
        original_typed_event_ref=dict(event_id=event.event_id,event_fingerprint='LATE_CASH_LABEL'),
        source_fact_ref=dict(path='D:/synthetic/current-cash-fact.json',sha256='1'*64),
        original_source_reference=event.source_reference,original_source_fingerprint=event.source_fingerprint,
        original_available_at=event.available_at,new_source_publication_bound='2025-09-07T00:00:00Z',
        original_typed_fields_and_fingerprint_preserved=True,original_frozen_classification_unchanged=True,
        descendant_ordinary_cash_clock='SYNTHETIC_DESCENDANT_ORDINARY_CASH_CLOCK',
        descendant_clock_is_new_source_account_identity=True,
        cash_per_raw_old_share='FORBIDDEN_SENTINEL_NOT_READ',small_cash_predicate='FORBIDDEN_SENTINEL_NOT_READ')
    f.cover['manifest']['proofs']=[proof]
    f.current=current;f.corroboration=proof;f.event=event
    return f


def test_parent_cash_accounting_corrob_keeps_original_authority_and_each_independent_source(parent_cash_mapping_guard):
    f=parent_cash_mapping_guard;before=deepcopy(f.source.events)
    result=f.source.session(f.x.ctx,f.x.original,f.x.book)
    seed=result['entry_seeds']['A'];basis=seed['accounting_mapping_basis_proof']
    assert seed['security_id']=='UID_A' and seed['cusip']=='CUSIP_A'
    original=basis['identity_representation_proofs'][0]
    assert original['identity_source_fingerprint']==f.envelope['source_fingerprint']
    assert original['identity_available_at_as_recorded']==f.envelope['available_at']
    checked=original['exact_parent_cash_corroborations']
    assert len(checked)==1 and checked[0]['identity']==f.identity
    assert checked[0]['identity_source_fingerprint']==f.current['source_fingerprint']
    assert checked[0]['original_identity_proof_chain_depth']>checked[0]['corroboration_proof_chain_depth']
    assert checked[0]['identity_source_reference']==f.current['source_reference']
    assert checked[0]['identity_available_at_as_recorded']==f.current['available_at']
    assert checked[0]['original_source_fingerprint']==f.event.source_fingerprint
    assert checked[0]['original_available_at']==f.event.available_at
    assert checked[0]['new_source_publication_bound']==f.corroboration['new_source_publication_bound']
    assert checked[0]['source_fact_ref']==f.corroboration['source_fact_ref']
    assert checked[0]['historical_availability_qualified'] is False
    assert checked[0]['CUSIP_equivalence_granted'] is False
    assert all(basis[k] is False for k in ('current_security_identity_granted','historical_availability_granted',
        'cash_permission_granted','quote_qualification_granted','terminal_or_settlement_qualification_granted'))
    assert f.source.events==before
    assert 'cash_per_raw_old_share' not in str(basis) and 'small_cash_predicate' not in str(basis)
    assert 'LATE_CASH_LABEL' not in result['held_guards']['OUT']['processed_event_fingerprints']


@pytest.mark.parametrize('defect,reason',[
    ('missing_original','TYPED_ISSUER'),('duplicate_original','TYPED_ISSUER'),
    ('unmarked_current','TYPED_ISSUER'),('unknown_role','TYPED_ISSUER'),
    ('identity','PARENT_CASH_ACCOUNTING_CORROBORATION'),('identity_hash','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('event_id','PARENT_CASH_ACCOUNTING_CORROBORATION'),('event_fp','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('top_fp','PARENT_CASH_ACCOUNTING_CORROBORATION'),('duplicate_corrob','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('duplicate_typed_event','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('same_manifest_origin','PARENT_CASH_ACCOUNTING_CORROBORATION'),('reversed_parent_chain','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('original_source_ref','PARENT_CASH_ACCOUNTING_CORROBORATION'),('original_source_fp','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('original_available','PARENT_CASH_ACCOUNTING_CORROBORATION'),('event_ticker','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('fields_preserved','PARENT_CASH_ACCOUNTING_CORROBORATION'),('classification_preserved','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('new_identity_role','PARENT_CASH_ACCOUNTING_CORROBORATION'),('cusip_claim','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('current_source_ref','PARENT_CASH_ACCOUNTING_CORROBORATION'),('current_source_fp','PARENT_CASH_ACCOUNTING_CORROBORATION'),
    ('fact_ref','PINNED_HELD_SOURCE_REF')])
def test_parent_cash_accounting_corrob_cannot_hide_duplicate_or_conflicting_evidence(parent_cash_mapping_guard,defect,reason):
    f=parent_cash_mapping_guard;p=f.corroboration
    if defect=='missing_original':f.parent['manifest']['proofs']=[]
    elif defect=='duplicate_original':f.parent['manifest']['proofs'].append(deepcopy(f.proof))
    elif defect=='unmarked_current':del p['event_binding_role']
    elif defect=='unknown_role':p['event_binding_role']='UNKNOWN'
    elif defect=='identity':f.current['identity']=dict(f.identity,issuer='OTHER')
    elif defect=='identity_hash':f.current['identity_payload_sha256']='2'*64
    elif defect=='event_id':p['original_typed_event_ref']['event_id']='OTHER'
    elif defect=='event_fp':p['original_typed_event_ref']['event_fingerprint']='OTHER'
    elif defect=='top_fp':p['event_fingerprint']='OTHER'
    elif defect=='duplicate_corrob':f.cover['manifest']['proofs'].append(deepcopy(p))
    elif defect=='duplicate_typed_event':f.source.cash_events.append(dict(f.source.cash_events[0]))
    elif defect=='same_manifest_origin':
        f.parent['manifest']['proofs']=[];f.cover['manifest']['proofs'].append(f.proof)
    elif defect=='reversed_parent_chain':
        f.cover['manifest']['proofs']=[f.proof];f.parent['manifest']['proofs']=[p]
    elif defect=='original_source_ref':p['original_source_reference']='https://synthetic.invalid/other'
    elif defect=='original_source_fp':p['original_source_fingerprint']='2'*64
    elif defect=='original_available':p['original_available_at']='2025-09-03T23:59:59Z'
    elif defect=='event_ticker':f.event.ticker='OTHER'
    elif defect=='fields_preserved':p['original_typed_fields_and_fingerprint_preserved']=False
    elif defect=='classification_preserved':p['original_frozen_classification_unchanged']=False
    elif defect=='new_identity_role':p['descendant_clock_is_new_source_account_identity']=False
    elif defect=='cusip_claim':f.current['CUSIP_claim']=True
    elif defect=='current_source_ref':f.current['source_reference']=''
    elif defect=='current_source_fp':f.current['source_fingerprint']='INVALID'
    else:p['source_fact_ref']['sha256']='INVALID'
    with pytest.raises(inputs.HeldLineageUnavailable,match=reason):f.source.session(f.x.ctx,f.x.original,f.x.book)


def test_parent_cash_current_corrob_never_replaces_independent_legal_gate(parent_cash_mapping_guard):
    f=parent_cash_mapping_guard;f.x.original['record']['asset_uids']['A']='OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable,match='CURRENT_ENTRY_IDENTITY_CONFLICT'):
        f.source.session(f.x.ctx,f.x.original,f.x.book)


def test_parent_cash_future_corrob_append_does_not_change_current_legal_seed_or_holding(parent_cash_mapping_guard):
    f=parent_cash_mapping_guard
    before=f.source.session(f.x.ctx,f.x.original,f.x.book)
    future=type(f.event)(f.sid,'A')
    future.event_id='FUTURE_ORIGINAL_CASH_EVENT'
    future.source_reference='https://synthetic.invalid/future-original-cash'
    future.source_fingerprint='5'*64;future.available_at='2025-11-30T23:59:59Z'
    f.source.cash_events.append(dict(event=future,ticker='A',day='2025-12-22',fp='FUTURE_CASH_LABEL'))
    parent_proof=deepcopy(f.proof);parent_proof['event_fingerprint']='FUTURE_CASH_LABEL'
    f.parent['manifest']['proofs'].append(parent_proof)
    more=deepcopy(f.corroboration);more['event_fingerprint']='FUTURE_CASH_LABEL'
    more['original_typed_event_ref']=dict(event_id=future.event_id,event_fingerprint='FUTURE_CASH_LABEL')
    more.update(original_source_reference=future.source_reference,original_source_fingerprint=future.source_fingerprint,
        original_available_at=future.available_at)
    more['source_fact_ref']=dict(path='D:/synthetic/later-cash-fact.json',sha256='3'*64)
    more['identity'].update(source_reference='https://synthetic.invalid/later-identity',
        source_fingerprint='4'*64,available_at='2025-12-01T23:59:59Z')
    more['new_source_publication_bound']='2025-12-02T00:00:00Z'
    f.cover['manifest']['proofs'].append(more)
    after=f.source.session(f.x.ctx,f.x.original,f.x.book)
    audit=after['entry_seeds']['A']['accounting_mapping_basis_proof']
    assert len(audit['identity_representation_proofs'])==2
    assert all(len(p['exact_parent_cash_corroborations'])==1 for p in audit['identity_representation_proofs'])
    for key in ('security_id','security_id_type','cusip','share_class','raw_code','historical_source_epoch','seed_source_row_identity'):
        assert after['entry_seeds']['A'][key]==before['entry_seeds']['A'][key]
    assert after['domain']['assets']==before['domain']['assets']
    assert after['held_guards']==before['held_guards']


@pytest.fixture
def cboe_issuer_mapping_guard(issuer_mapping_guard):
    f=issuer_mapping_guard;x=f.x
    f.identity.update(issuer='Cboe Global Markets, Inc.',ticker='CBOE',listing_identity='CBOE:CBOE')
    f.envelope['identity_payload_sha256']=content_hash(f.identity)
    f.source.base.master_assets=('OUT','CBOE')
    x.rows[1].update(ticker='CBOE',security_id='UID_CBOE',cusip='CUSIP_CBOE',moomoo_transport_code='CBOE')
    x.raw.loc[1,['ticker','code']]=['CBOE','CBOE']
    f.source.mapping['records'][1]['ticker']='CBOE'
    f.source.mapping['basis_by_ticker']['CBOE']=f.source.mapping['basis_by_ticker'].pop('A')
    f.source.events['entitlement_security_tickers']={f.sid:'CBOE'};f.cover['security_tickers']={f.sid:'CBOE'}
    f.source.cash_events[0]['ticker']='CBOE';f.source.cash_events[0]['event'].ticker='CBOE'
    x.ctx.tickers=('OUT','CBOE')
    x.original['record']['asset_uids']={'CBOE':'UID_CBOE'}
    x.original['record']['asset_epochs']={'CBOE':'EPOCH_CBOE'}
    return f


def test_cboe_common_source_label_uses_existing_ontology_without_replacing_frozen_sid_or_legal_identity(cboe_issuer_mapping_guard):
    f=cboe_issuer_mapping_guard;before=deepcopy(f.source.mapping)
    result=f.source.session(f.x.ctx,f.x.original,f.x.book)
    seed=result['entry_seeds']['CBOE'];proof=seed['accounting_mapping_basis_proof']
    assert seed['security_id']=='UID_CBOE' and seed['cusip']=='CUSIP_CBOE' and seed['raw_code']=='CBOE'
    assert proof['mapping_sid']==f.sid and f.source.mapping==before
    assert proof['identity_representation_proofs'][0]['identity']['listing_identity']=='CBOE:CBOE'
    assert all(proof[k] is False for k in ('current_security_identity_granted','historical_availability_granted',
        'cash_permission_granted','quote_qualification_granted','terminal_or_settlement_qualification_granted'))


@pytest.mark.parametrize('listing,kind',[
    ('CBOE:OTHER','COMMON_STOCK'),('BZX:CBOE','COMMON_STOCK'),('Cboe:CBOE','COMMON_STOCK'),
    ('CBOE:CBOE','AMERICAN_DEPOSITARY_SHARE'),('CBOE:CBOE','CLASS_B_COMMON_STOCK'),
    ('CBOE:CBOE','PREFERRED_STOCK')])
def test_cboe_source_label_cannot_create_other_venue_or_share_class(cboe_issuer_mapping_guard,listing,kind):
    f=cboe_issuer_mapping_guard;f.identity.update(listing_identity=listing,security_type=kind)
    if kind=='AMERICAN_DEPOSITARY_SHARE':
        sid='SOURCE_ISSUER_ADS_CLASS:'+'b'*64
        f.source.mapping['records'][1]['sid']=sid;f.source.mapping['basis_by_ticker']['CBOE']['source_sid']=sid
        f.source.events['entitlement_security_tickers']={sid:'CBOE'};f.cover['security_tickers']={sid:'CBOE'}
        f.source.cash_events[0]['event'].old_security_id=sid;f.identity['security_id']=sid
    f.envelope['identity_payload_sha256']=content_hash(f.identity)
    with pytest.raises(inputs.HeldLineageUnavailable,match='ISSUER_CLASS_NAMESPACE'):
        f.source.session(f.x.ctx,f.x.original,f.x.book)


def test_cboe_accounting_label_cannot_waive_current_legal_uid(cboe_issuer_mapping_guard):
    f=cboe_issuer_mapping_guard;f.x.original['record']['asset_uids']['CBOE']='OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable,match='CURRENT_ENTRY_IDENTITY_CONFLICT'):
        f.source.session(f.x.ctx,f.x.original,f.x.book)


# Declared delayed metadata transport: all rows, quantities and sources below are fabricated.
@pytest.fixture
def delayed_identity_document():
    ref=lambda name:dict(path='D:/synthetic/delayed/'+name+'.json',sha256='a'*64)
    uidref=ref('original_uid_intervals');eventref=ref('original_event');factsref=ref('facts');declref=ref('declaration')
    rows=[]
    for start,end,sid,title,filing in [
            ('2023-01-03','2023-01-04','OLD_COMMON','COM','PRIOR_FILING'),
            ('2023-01-05','2023-01-10','NEW_COMMON','COM NEW','CURRENT_FILING')]:
        row=dict(ticker='OUT',effective_start=pd.Timestamp(start),effective_end=pd.Timestamp(end),
            security_id=sid,security_id_type='CUSIP',cusip=sid,issuer_name='SYNTHETIC COMMON ISSUER',
            title_of_class=title,moomoo_transport_code='US.OUT',mapping_status='RESOLVED',
            mapping_source='SYNTHETIC',source_filing=filing)
        identity=inputs._held_identity(dict(row,share_class=title,raw_code='US.OUT',raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
        rows.append(dict(source_row=row,source_row_content_sha256=content_hash(row),identity=identity))
    event=dict(ticker='OUT',event_date='2023-01-02',status='SHARE_ONLY_SUPPORTED',
        quantity_multiplier=1/12,event_fingerprint='ORIGINAL_ACTION',source_fingerprint='ORIGINAL_SOURCE')
    facts=dict(schema='B_HISTORICAL_SOURCE_BACKED_COMMON_CUSIP_TRANSITION_CANDIDATE_V1',
        status='PRIMARY_SAME_COMMON_POST_SPLIT_CUSIP_AND_PRIOR_FROZEN_COMMON_IDENTITY_SOURCE_READY_FOR_OWNER_ADJUDICATION',
        ticker='OUT',old_cusip='OLD_COMMON',new_cusip='NEW_COMMON',
        old_CUSIP_source_role='EXPLICIT_OLD_LITERAL_IN_ORIGINAL_PINNED_PRIOR_MANAGER_SEC_INFORMATION_TABLE',
        new_CUSIP_source_role='EXPLICIT_NEW_LITERAL_IN_ISSUER_SEC_8K_AND_ORIGINAL_ISSUER_EX99_1_FOR_SAME_ISSUED_AND_OUTSTANDING_COMMON_STOCK',
        one_primary_document_prints_both_CUSIPs=False,primary_8K_old_CUSIP_literal_match_count=0,
        availability_scope=dict(historical_original_archive_vintage='UNKNOWN',historical_PIT_not_granted=True),
        quantity_scope=dict(do_not_multiply_current_holding_again=True,no_NEW_quantity_effect_or_CA_engine=True,
            source_ratio_literal='one-for-twelve /1-for-12'),
        strict_PIT=False,source_refs=[ref('old_primary'),ref('new_primary')],
        original_prior_manager_source_identity=dict(source_role='ORIGINAL_PRIOR_FROZEN_MANAGER_13F_COMMON_SECURITY_IDENTITY',
            identity_projection=dict(nameOfIssuer='SYNTHETIC COMMON ISSUER',titleOfClass='COM',cusip='OLD_COMMON')),
        existing_owner_identity_metadata_context=dict(old_row_hash=rows[0]['source_row_content_sha256'],
            new_row_hash=rows[1]['source_row_content_sha256'],old_source_filing='PRIOR_FILING',new_source_filing='CURRENT_FILING'),
        old_source_common_class_literal='COM',current_frozen_metadata_class_literal='COM NEW',
        new_source_common_class_literal='common stock',issuer_filed_as_of_date='2023-01-03',
        post_split_trading_session='2023-01-02',effective_time_literal='source effective time',
        issuer_EX99_1_fragment=dict(text='same issued and outstanding common stock 1-for-12'))
    # Source filing for this fabricated action precedes the immutable old-row start.
    facts['issuer_filed_as_of_date']='2023-01-03'
    # Use an old row starting before the source filing, but a seed strictly after the action.
    rows[0]['source_row']['effective_start']=pd.Timestamp('2022-12-29')
    rows[0]['source_row_content_sha256']=content_hash(rows[0]['source_row'])
    facts['existing_owner_identity_metadata_context']['old_row_hash']=rows[0]['source_row_content_sha256']
    facts['issuer_filed_as_of_date']='2022-12-30'
    value=dict(schema='B_SOURCE_BOUND_DELAYED_IDENTITY_METADATA_TRANSPORT_V1',
        status='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION',rule=deepcopy(inputs.DELAYED_IDENTITY_METADATA_TRANSPORT_RULE),
        relation_role='SAME_ISSUED_AND_OUTSTANDING_COMMON_STOCK_OLD_13F_AND_NEW_ISSUER_SOURCE',
        historical_original_archive_vintage='UNKNOWN',strict_PIT=False,quantity_effect=False,
        typed_CA_event=False,historical_observations_relabelled=False,
        original_uid_intervals_ref=uidref,original_event_binding_ref=eventref,historical_sources_candidate_ref=factsref,
        original_rows=rows,original_event=deepcopy(event),split_effective_at='2022-12-30T22:00:00+00:00',
        post_split_trading_session='2023-01-02',source_effective_time_literal='source effective time',
        source_filing_day='2022-12-30')
    docs={declref['path']:value,factsref['path']:facts,eventref['path']:dict(event_records=[event])}
    pins=[]
    interface=SimpleNamespace(pin=lambda r:(pins.append(deepcopy(r)),r['path'])[1],read=lambda p:deepcopy(docs[p]))
    return SimpleNamespace(value=value,facts=facts,event=event,uidref=uidref,eventref=eventref,ref=ref,
        rows=rows,pins=pins,load=lambda:inputs._load_delayed_identity_metadata_transport(interface,declref,uidref,eventref))


def test_delayed_identity_loader_pins_distinct_common_sources_and_original_rows(delayed_identity_document):
    x=delayed_identity_document;before=deepcopy((x.value,x.facts,x.event))
    transports=x.load();item=transports[0]
    assert item['old_identity']['security_id']=='OLD_COMMON'
    assert item['new_identity']['security_id']=='NEW_COMMON'
    assert item['old_row_hash']==x.rows[0]['source_row_content_sha256']
    assert item['original_event']['quantity_multiplier']==1/12
    assert (x.value,x.facts,x.event)==before
    assert not item['historical_availability_qualified']
    assert x.ref('old_primary') in x.pins and x.ref('new_primary') in x.pins
    assert not inputs._held_security_identity_equal(item['old_identity'],item['new_identity'])


@pytest.mark.parametrize('defect',[
    'quantity_rule','PIT','source_role','old_literal','preferred','rowhash','prefix_sid','issuer','raw',
    'event_ratio','event_fp','future_filing','action_clock','new_before_action'])
def test_delayed_identity_loader_rejects_unproved_roles_rows_and_action(delayed_identity_document,defect):
    x=delayed_identity_document;v=x.value;f=x.facts
    if defect=='quantity_rule':v['rule']['quantity_effect']=True
    elif defect=='PIT':v['strict_PIT']=True
    elif defect=='source_role':f['old_CUSIP_source_role']='ISSUER_DOCUMENT_GUESSED_OLD'
    elif defect=='old_literal':f['old_cusip']='OTHER'
    elif defect=='preferred':f['new_source_common_class_literal']='preferred stock'
    elif defect=='rowhash':v['original_rows'][0]['source_row_content_sha256']='b'*64
    elif defect=='prefix_sid':v['original_rows'][1]['identity']['security_id']='CUSIP:NEW_COMMON'
    elif defect in ('issuer','raw'):
        key='issuer_name' if defect=='issuer' else 'moomoo_transport_code'
        v['original_rows'][1]['source_row'][key]='OTHER'
        v['original_rows'][1]['source_row_content_sha256']=content_hash(v['original_rows'][1]['source_row'])
    elif defect=='event_ratio':
        v['original_event']['quantity_multiplier']=.5;x.event['quantity_multiplier']=.5
    elif defect=='event_fp':v['original_event']['event_fingerprint']='OTHER'
    elif defect=='future_filing':v['source_filing_day']='2023-01-06';f['issuer_filed_as_of_date']='2023-01-06'
    elif defect=='action_clock':v['split_effective_at']='2023-01-06T22:00:00+00:00'
    else:
        row=v['original_rows'][1]['source_row'];row['effective_start']=pd.Timestamp('2023-01-02')
        v['original_rows'][1]['source_row_content_sha256']=content_hash(row)
        f['existing_owner_identity_metadata_context']['new_row_hash']=content_hash(row)
    with pytest.raises((inputs.ExistingRiskInputUnavailable,inputs.HeldLineageUnavailable)):
        x.load()


@pytest.fixture
def delayed_identity_chain(full_source_guard,delayed_identity_document):
    """Existing real source guard -> real book, original/current source rows retained."""
    x=full_source_guard;d=delayed_identity_document;source=x.source
    source.binding['lineage_rule_ref']=d.ref('explicit_lineage_rule')
    transports=d.load();source.identity_transports=transports
    days=pd.to_datetime(['2023-01-03','2023-01-04','2023-01-05','2023-01-06','2023-01-09'])
    source.base.market_dates=days;source.base._components['calendar']=days
    source.base.loads_count=0;source.base._initialize=lambda:None
    source.present=np.ones((len(days),2),bool)
    x.rows[0].clear();x.rows[0].update(deepcopy(d.rows[0]['source_row']))
    x.rows.append(deepcopy(d.rows[1]['source_row']))
    source.base._components['reader'].sources['uid_intervals']=d.uidref
    x.raw.loc[x.raw.ticker.eq('OUT'),'code']='US.OUT'
    source.mapping['records'][0]['sid']='FROZEN_RAW_TRANSPORT_CODE:US.OUT'
    source.mapping['basis_by_ticker']['OUT']['source_sid']='FROZEN_RAW_TRANSPORT_CODE:US.OUT'
    # Reader projection obeys date/ticker boundaries, as the existing production reader does.
    calls=x.calls;reader=source.base._components['reader']
    def read(name,columns,*,date_field,start=None,stop=None,day=None,tickers=None):
        calls.append((name,tuple(columns),dict(start=start,stop=stop,day=day,tickers=tickers)))
        frame={'uid_intervals':pd.DataFrame(x.rows),'raw_open_close':x.raw,'share_ca_audit':x.audits}[name]
        dates=pd.to_datetime(frame[date_field]);keep=dates.lt(pd.Timestamp('2026-01-01'))
        if start is not None:keep&=dates.ge(pd.Timestamp(start))
        if stop is not None:keep&=dates.lt(pd.Timestamp(stop))
        if day is not None:keep&=dates.eq(pd.Timestamp(day))
        if tickers is not None:keep&=frame.ticker.isin(tickers)
        return frame.loc[keep,list(columns)].copy()
    reader.read=read
    book=inputs.HeldPositionLineageBook('SYNTHETIC_ACCOUNT',fill_owner_ref=source.binding['fill_owner_ref'],
        lineage_rule_ref=source.binding['lineage_rule_ref'],identity_transports=transports)
    seed=dict(transports[0]['old_identity'],qualified=True,historical_observations_relabelled=False,
        identity_asof=inputs.producer._clock('2023-01-03').isoformat(),seed_source_ref=d.uidref,
        seed_source_row_identity=transports[0]['old_row_hash'],historical_source_epoch='HIST_OLD')
    book.note_qualified_decision('2023-01-03',{'OUT':seed})
    def fill(side='BUY',q=1.,before=0.,signal='2023-01-03',day='2023-01-04',order='INITIAL'):
        return pd.DataFrame([dict(path_id=book.account_id,order_id=order,signal_date=signal,execution_date=day,
            ticker='OUT',side=side,fractional_shares=q,index_units_before=before,
            index_units_after=before+(q if side=='BUY' else -q))])
    def at(day,units=1.,in_pool=True):
        x.ctx.signal_date=pd.Timestamp(day);x.ctx.signal_asof=inputs.producer._clock(day)
        x.ctx.current_units=np.array([[units,0.]]);x.ctx.current_weights=np.array([[.1 if units else 0.,0.]])
        x.raw['trade_date']=pd.Timestamp(day)
        uid='OLD_COMMON' if day<'2023-01-05' else 'NEW_COMMON'
        epoch='HIST_OLD' if day<'2023-01-05' else 'HIST_NEW'
        x.original['mask']=np.array([in_pool,True])
        x.original['record']=dict(assets=['OUT','A'] if in_pool else ['A'],
            asset_uids=dict(A='UID_A',**({'OUT':uid} if in_pool else {})),
            asset_epochs=dict(A='EPOCH_A',**({'OUT':epoch} if in_pool else {})),
            artifact_ref=d.ref('original_primary'))
        x.original['receipt']=dict(synthetic_original=True)
        x.original['event']=dict(dependency_local_event_ids={'PRIMARY':'PRIMARY_CURRENT'},
            dependency_local_signature_sha256={'PRIMARY':'b'*64})
        return x.ctx
    book.observe_fills(fill())
    ctx=at('2023-01-04');initial=source.session(ctx,x.original,book)
    admitted=book.qualified_proofs(ctx,initial['held_guards'])['OUT']
    source.base._components['support']=dict(events=[
        dict(event_id='OLD_SOURCE_EVENT',decision_asof=inputs.producer._clock('2023-01-04').isoformat(),
            asset_uids={'OUT':'OLD_COMMON'},asset_epochs={'OUT':'HIST_OLD'},segment_starts={'OUT':'2022-12-29'}),
        dict(event_id='NEW_SOURCE_EVENT',decision_asof=inputs.producer._clock('2023-01-05').isoformat(),
            asset_uids={'OUT':'NEW_COMMON'},asset_epochs={'OUT':'HIST_NEW'},segment_starts={'OUT':'2023-01-05'})])
    source.base._domain=lambda day,asof:x.original
    source.base.interface=SimpleNamespace(pin=lambda r:r['path'])
    return SimpleNamespace(source=source,book=book,at=at,original=x.original,raw=x.raw,rows=x.rows,
        initial=admitted,transports=transports,fill=fill,calls=calls,doc=d,ctx=x.ctx)


def test_delayed_current_pool_identity_transport_keeps_immutable_seed_and_quantity(delayed_identity_chain):
    x=delayed_identity_chain;seed=deepcopy(x.book._positions['OUT']['seed']);pid=x.initial['position_id']
    ctx=x.at('2023-01-05');s=x.source.session(ctx,x.original,x.book)
    assert s['entry_seeds']['OUT']['security_id']=='NEW_COMMON'
    assert s['current_identities']['OUT']['security_id']=='NEW_COMMON'
    assert s['historical_source_epochs']['OUT']=='HIST_NEW'
    proof=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    assert len(x.initial)==22 and len(proof)==23 and tuple(proof)[:22]==inputs.HeldPositionLineageBook.PROOF_FIELDS
    assert proof['seed_security_id']=='OLD_COMMON' and proof['position_id']==pid
    assert proof['actual_quantity_binding']['raw_quantity']==1.
    assert proof['quantity_transition_refs']==[] and proof['processed_event_fingerprints']==[]
    binding=proof['current_identity_metadata_binding']
    assert binding['raw_quantity_effect']==0 and not binding['typed_CA_event']
    assert binding['source_binding']['seed_historical_source_epoch']=='HIST_OLD'
    assert x.book._positions['OUT']['seed']==seed
    assert x.book._positions['OUT']['identity']==x.transports[0]['new_identity']
    assert all(not set(cols)&{'Open','Close','price','NAV','notional'} for _,cols,_ in x.calls)


def test_delayed_current_pool_new_uid_buy_adds_without_rewriting_original_spell(delayed_identity_chain):
    x=delayed_identity_chain;ctx=x.at('2023-01-05');s=x.source.session(ctx,x.original,x.book)
    first=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    x.book.note_qualified_decision(ctx.signal_date,s['entry_seeds'])
    x.book.observe_fills(x.fill(q=.5,before=1.,signal='2023-01-05',day='2023-01-06',order='ADD'))
    ctx=x.at('2023-01-06',units=1.5);s=x.source.session(ctx,x.original,x.book)
    proof=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    assert proof['position_id']==first['position_id'] and proof['seed_security_id']=='OLD_COMMON'
    assert proof['actual_quantity_binding']['raw_quantity']==1.5
    assert proof['quantity_transition_refs'][0]['stage']=='ACTUAL_RAW_SHARE_FILL'
    assert not proof['current_identity_metadata_binding']['typed_CA_event']


def test_delayed_pending_old_seed_first_admission_and_zero_prefix(delayed_identity_chain):
    x=delayed_identity_chain
    seed=dict(x.transports[0]['old_identity'],qualified=True,historical_observations_relabelled=False,
        identity_asof=inputs.producer._clock('2023-01-04').isoformat(),seed_source_ref=x.doc.uidref,
        seed_source_row_identity=x.transports[0]['old_row_hash'],historical_source_epoch='HIST_OLD')
    def fresh_book():
        book=inputs.HeldPositionLineageBook(x.book.account_id,fill_owner_ref=x.source.binding['fill_owner_ref'],
            lineage_rule_ref=x.source.binding['lineage_rule_ref'],identity_transports=x.transports)
        book.note_qualified_decision('2023-01-04',{'OUT':seed})
        return book
    zero=fresh_book();ctx=x.at('2023-01-05',units=0.)
    assert zero.observe_fills(x.fill(q=0.,signal='2023-01-04',day='2023-01-05',order='ZERO'))==0
    assert zero.qualified_proofs(ctx,{})=={} and zero.held_assets==()
    positive=fresh_book()
    positive.observe_fills(x.fill(signal='2023-01-04',day='2023-01-05',order='FIRST'))
    ctx=x.at('2023-01-05');s=x.source.session(ctx,x.original,positive)
    proof=positive.qualified_proofs(ctx,s['held_guards'])['OUT']
    assert proof['seed_security_id']=='OLD_COMMON' and len(proof)==23
    assert proof['actual_quantity_binding']['raw_quantity']==1.


def test_delayed_sell_to_zero_then_new_uid_buy_keeps_original_fill_leg_order(delayed_identity_chain):
    x=delayed_identity_chain;ctx=x.at('2023-01-05');s=x.source.session(ctx,x.original,x.book)
    original=x.book.qualified_proofs(ctx,s['held_guards'])['OUT'];x.book.note_qualified_decision(ctx.signal_date,s['entry_seeds'])
    x.book.observe_fills(x.fill(side='SELL',q=1.,before=1.,signal='2023-01-05',day='2023-01-06',order='TARGET'))
    x.book.observe_fills(x.fill(q=.25,before=0.,signal='2023-01-05',day='2023-01-06',order='TARGET'))
    ctx=x.at('2023-01-06',units=.25);s=x.source.session(ctx,x.original,x.book)
    proof=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    assert proof['seed_security_id']=='NEW_COMMON' and proof['position_id']!=original['position_id']
    assert [r['side'] for r in proof['quantity_transition_refs']]==['SELL','BUY']
    assert 'current_identity_metadata_binding' not in proof
    assert x.book.closed_positions[-1]['position_id']==original['position_id']


@pytest.mark.parametrize('defect',['missing_transport','unbound_row','pre_action_seed','new_row_missing','wrong_raw'])
def test_delayed_source_unproved_coordinate_stays_blocked_atomically(delayed_identity_chain,defect):
    x=delayed_identity_chain;before=deepcopy(x.book._positions);ctx=x.at('2023-01-05')
    if defect=='missing_transport':x.source.identity_transports=()
    elif defect=='unbound_row':x.rows[0]['source_filing']='OTHER'
    elif defect=='pre_action_seed':x.book._positions['OUT']['seed']['signal_session']='2022-12-30'
    elif defect=='new_row_missing':x.rows.pop()
    else:x.raw.loc[x.raw.ticker.eq('OUT'),'code']='US.OTHER'
    with pytest.raises(inputs.HeldLineageUnavailable):x.source.session(ctx,x.original,x.book)
    if defect!='pre_action_seed':assert x.book._positions==before


def test_delayed_held_only_requires_new_uid_original_past_witness(delayed_identity_chain):
    x=delayed_identity_chain;ctx=x.at('2023-01-05',in_pool=False)
    with pytest.raises(inputs.HeldLineageUnavailable,match='CURRENT_UID_HISTORICAL_EPOCH_WITNESS'):
        x.source.session(ctx,x.original,x.book)
    assert x.book._positions['OUT']['identity']['security_id']=='OLD_COMMON'
    ctx=x.at('2023-01-06',in_pool=False);s=x.source.session(ctx,x.original,x.book)
    proof=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    assert set(s['entry_seeds'])=={'A'} and s['historical_source_epochs']['OUT']=='HIST_NEW'
    from scripts.research.a2.risk import continuous_lw_support as backend
    request=dict(decision_session='2023-01-06',current_identities=s['current_identities'],
        held_lineage_proofs={'OUT':proof},held_source_receipt=s['source_receipt'])
    assert backend._held_current_identity(request,x.raw,'OUT',x.book.account_id,
        x.source.base._components['reader'].sources['raw_open_close'])==x.transports[0]['new_identity']


@pytest.mark.parametrize('defect',['missing_binding','seed_uid','seed_row','quantity_effect','current_uid','source_guard','account'])
def test_delayed_backend_requires_exact_separate_current_metadata_binding(delayed_identity_chain,defect):
    x=delayed_identity_chain;ctx=x.at('2023-01-06',in_pool=False);s=x.source.session(ctx,x.original,x.book)
    proof=x.book.qualified_proofs(ctx,s['held_guards'])['OUT']
    request=dict(decision_session='2023-01-06',current_identities=deepcopy(s['current_identities']),
        held_lineage_proofs={'OUT':proof},held_source_receipt=deepcopy(s['source_receipt']))
    if defect=='missing_binding':proof.pop('current_identity_metadata_binding')
    elif defect=='seed_uid':proof['seed_security_id']='OTHER'
    elif defect=='seed_row':proof['seed_source_row_identity']='OTHER'
    elif defect=='quantity_effect':proof['current_identity_metadata_binding']['raw_quantity_effect']=1.
    elif defect=='current_uid':request['current_identities']['OUT']['security_id']='OTHER';request['current_identities']['OUT']['cusip']='OTHER'
    elif defect=='source_guard':request['held_source_receipt']['quantity_guard_proofs']['OUT']['identity_metadata_bindings']=[]
    else:proof['actual_quantity_binding']['account_id']='OTHER'
    from scripts.research.a2.risk import continuous_lw_support as backend
    with pytest.raises(ValueError):
        backend._held_current_identity(request,x.raw,'OUT',x.book.account_id,
            x.source.base._components['reader'].sources['raw_open_close'])


@pytest.mark.parametrize('stale',['uid','historical','PRIMARY'])
def test_delayed_real_source_and_book_reject_stale_whole_generated_then_select_current_full_U(
        delayed_identity_chain,continuous,stale,monkeypatch):
    x=delayed_identity_chain;old=continuous.adapter
    adapter=inputs.ContinuousCausalLWInputs(base=x.source.base,account_id=x.book.account_id,sources=x.source,
        supplemental=old.supplemental,source_contract=old.source_contract,references=old.references,
        reuse_rule=old.reuse_rule,state_loader=lambda r:pytest.fail('ineligible paid state loaded'))
    adapter.book=x.book;adapter.continuous_rule=deepcopy(old.continuous_rule)
    adapter.supplemental['original_primary_dependency_epoch']['event_id']='EXPIRED'
    ctx=x.at('2023-01-06',in_pool=False);domain=adapter.qualified_causal_domain(ctx)
    calls=[]
    from scripts.research.a2.risk.continuous_lw_support import RECIPE
    def callback(request):
        calls.append(deepcopy(request));assets=request['U'];n=len(assets)
        state=deepcopy(continuous.callback(request)['state'])
        state.assets=tuple(assets);state.covariance=np.eye(n)+.2
        current=deepcopy(request['current_identities'])
        uids={a:current[a]['security_id'] for a in assets};epochs={a:'FIT_'+a for a in assets}
        state.coverage={a:dict(uid=uids[a],identity_epoch=epochs[a]) for a in assets}
        metadata=dict(status='COMPLETE_WHOLE_LW_OUTPUT',assets=assets,asset_uids=uids,asset_epochs=epochs,
            historical_source_epochs=deepcopy(request['historical_source_epochs']),current_identities=current,
            original_primary_dependency_epoch=deepcopy(request['original_primary_dependency_epoch']),
            as_of=request['as_of'],cutoff=request['cutoff'],state_available_at=request['as_of'],
            risk_state_id=state.risk_state_id,method=state.method,recipe_sha256=RECIPE,
            typed_state_content_sha256='f'*64,state_ref=x.doc.ref('generated'),producer_ref=x.doc.ref('backend'),
            covariance_sha256=content_hash(state.covariance),learned_units=0,physical_operations=0)
        return dict(state=state,metadata=metadata)
    adapter.estimate_callback=callback
    # This fabricated full matrix retains its old metadata and is never loaded/aliased.
    current=adapter._last
    request=deepcopy(adapter.last_request)
    request.update(current_identities=current['source']['current_identities'],
        historical_source_epochs=current['source']['historical_source_epochs'])
    prior=callback(request);calls.clear()
    if stale=='uid':
        prior['metadata']['current_identities']['OUT']=deepcopy(x.transports[0]['old_identity'])
        prior['metadata']['asset_uids']['OUT']='OLD_COMMON'
    elif stale=='historical':prior['metadata']['historical_source_epochs']['OUT']='HIST_OLD'
    else:prior['metadata']['original_primary_dependency_epoch']['event_id']='OLD_PRIMARY'
    adapter.generated=[dict(state=None,metadata=prior['metadata'])]
    result=adapter.for_required_domain(ctx,domain)
    assert len(calls)==1 and calls[0]['P']==['A'] and calls[0]['U']==['A','OUT']
    assert calls[0]['current_identities']['OUT']['security_id']=='NEW_COMMON'
    assert calls[0]['historical_source_epochs']['OUT']=='HIST_NEW'
    assert calls[0]['held_lineage_proofs']['OUT']['seed_security_id']=='OLD_COMMON'
    assert adapter.generated_loads_count==0 and result.assets==('OUT','A')
    np.testing.assert_array_equal(result.covariance,np.array([[1.2,.2],[.2,1.2]]))
    adapter.for_required_domain(ctx,domain)
    assert len(calls)==1 and adapter.new_outputs_count==1


def test_delayed_untransported_held_source_history_keeps_original_seed_role(full_source_guard):
    x=full_source_guard;x.original['record']['asset_uids']['OUT']='UID_OUT'
    x.original['record']['asset_epochs']['OUT']='LATER_UNRELATED_POOL_EPOCH'
    result=x.source.session(x.ctx,x.original,x.book)
    assert result['historical_source_epochs']['OUT']=='HIST_OUT'

@pytest.mark.parametrize('scope',['current_pool','held_only','held_only_missing_witness'])
def test_delayed_real_backend_prepare_uses_new_uid_epoch_without_relabelling_history(
        delayed_identity_chain,scope,monkeypatch):
    from scripts.research.a2.risk import continuous_lw_support as b
    x=delayed_identity_chain;in_pool=scope=='current_pool'
    ctx=x.at('2023-01-06',in_pool=in_pool);s=x.source.session(ctx,x.original,x.book)
    proofs=x.book.qualified_proofs(ctx,s['held_guards'])
    c=x.source.base._components;original=x.original
    original['event']['segment_starts']={'A':'2023-01-03','OUT':'2023-01-05'}
    original_reader=c['reader'];read_calls=[]
    class Reader:
        sources=dict(original_reader.sources,extended_shareholder_y5=x.doc.ref('labels'),
            prediction_features=x.doc.ref('feature_metadata'))
        phase='support'
        def read(self,name,columns,**kw):
            read_calls.append((name,tuple(columns),deepcopy(kw)))
            if name=='prediction_features':
                return pd.DataFrame([
                    dict(ticker='OUT',signal_date=pd.Timestamp('2023-01-04'),security_id='OLD_COMMON'),
                    dict(ticker='OUT',signal_date=pd.Timestamp('2023-01-05'),security_id='NEW_COMMON'),
                    dict(ticker='A',signal_date=pd.Timestamp('2023-01-05'),security_id='UID_A')])
            if name=='uid_intervals':
                return pd.DataFrame(x.rows).assign(report_quarter='SYNTHETIC').loc[:,list(columns)]
            if name=='raw_open_close':return x.raw.loc[:,list(columns)].copy()
            return pd.DataFrame(columns=columns)
    c['reader']=Reader()
    if scope=='held_only_missing_witness':
        c['support']['events']=c['support']['events'][:1]
    engine=object.__new__(b.ContinuousLWEstimator)
    engine.base=x.source.base;engine._source={'sources':c['reader'].sources};engine.science={}
    engine.account_id=x.book.account_id;engine.freeze={};engine.descriptor_bridges=()
    engine._producer_custody=lambda:x.doc.ref('backend')
    monkeypatch.setattr(b.old,'_receipt',lambda *a,**kw:SimpleNamespace(return_coordinate='SYNTHETIC_COORDINATE'))
    captured=[]
    class AssemblyBoundary(Exception):pass
    def capture(bound,calendar,**kwargs):
        captured.append(deepcopy(kwargs));raise AssemblyBoundary
    monkeypatch.setattr(b.event_owner,'assemble_risk_inputs',capture)
    request=dict(decision_session='2023-01-06',as_of=ctx.signal_asof.isoformat(),
        cutoff=inputs.producer._clock('2023-01-05').isoformat(),
        P=original['record']['assets'],H=['OUT'],D=['OUT','A'],U=['A','OUT'],
        original_primary_dependency_epoch=dict(event_id='PRIMARY_CURRENT',signature_sha256='b'*64),
        current_identities=s['current_identities'],historical_source_epochs=s['historical_source_epochs'],
        held_lineage_proofs=proofs,held_source_receipt=s['source_receipt'])
    if scope=='held_only_missing_witness':
        with pytest.raises(ValueError,match='ORIGINAL_HELD_HISTORICAL_EPOCH_WITNESS'):
            engine._prepare(request)
        assert captured==[]
    else:
        with pytest.raises(AssemblyBoundary):engine._prepare(request)
        actual=captured[0]
        assert actual['asset_uids']['OUT']=='NEW_COMMON'
        assert actual['asset_epochs']['OUT']=='HIST_NEW'
        history=actual['identity_history'].loc[actual['identity_history'].ticker.eq('OUT')]
        assert list(history.security_id)==['OLD_COMMON','NEW_COMMON']
        assert list(history.identity_epoch)==['PRIOR_OBSERVED_UID_EPOCH','HIST_NEW']
        assert history.signal_date.max()==pd.Timestamp('2023-01-05')
    assert not any('y_open5' in columns for _,columns,_ in read_calls)


# Generic common-share wording: keep original source literals and all other axes.
@pytest.mark.parametrize('left,right',[
    ('COM','Common Stock'),('Common Stock','COM'),('COM','COMMON STOCK'),
    (' COM ','Common\tStock'),('Common\r\nStock','COM'),('com','common stock')])
def test_generic_common_wording_is_symmetric_and_keeps_strings(left,right):
    before=(left,right)
    assert inputs._held_class_equal(left,right) and inputs._held_class_equal(right,left)
    assert (left,right)==before

@pytest.mark.parametrize('other',[
    'COM NEW','COM SHS','COM CL A','Class A','Class B','Common Stock Class A',
    'COMMON STOCK CLASS B','Common Shares','ADS','ADR','PFD','PREFERRED STOCK',
    'COM.','COMMON STOCK.','Common\u00a0Stock','Common\u2003Stock',
    'Common\u017ftock','common\u017ftock','COMMon \u017fTOCK','UNKNOWN',''])
def test_generic_common_never_infers_other_class_or_unicode_alias(other):
    assert not inputs._held_class_equal('COM',other)
    assert not inputs._held_class_equal('Common Stock',other)

@pytest.mark.parametrize('field,value',[
    ('security_id','OTHER'),('security_id_type','OTHER'),('cusip','OTHER'),
    ('raw_code','US.OTHER'),('raw_actual_share_coordinate','INDEX_UNIT'),
    ('share_class','COM NEW'),('share_class','Class A'),('share_class','ADS')])
def test_generic_common_still_requires_all_five_other_axes(held_book,field,value):
    old=dict(held_book.identity,share_class='Common Stock')
    now=dict(old,share_class='COM');now[field]=value;before=deepcopy((old,now))
    assert not inputs._held_security_identity_equal(old,now)
    assert (old,now)==before


def _boundary(x,held='Common Stock',current='COM'):
    # A current primary entrant also remains a partial actual held position.
    x.identity['share_class']=held;x.spell['seed']['share_class']=held
    x.rows[0]['title_of_class']=held
    x.rows.append(dict(x.rows[0],effective_start=pd.Timestamp('2023-01-04'),
        effective_end=pd.Timestamp('2025-12-31'),title_of_class=current,
        source_filing='NEXT_FROZEN_IDENTITY_FILING'))
    x.original['mask']=np.array([True,True])
    x.original['record']['asset_uids']['OUT']='UID_OUT'
    x.original['record']['asset_epochs']['OUT']='HIST_OUT'
    return x


def test_current_entry_COM_and_held_Common_Stock_consumes_real_session_without_rewrite(full_source_guard):
    x=_boundary(full_source_guard)
    before=deepcopy((x.rows,x.spell));hashes=[content_hash(row) for row in x.rows]
    result=x.source.session(x.ctx,x.original,x.book)
    assert result['entry_seeds']['OUT']['share_class']=='COM'
    assert result['current_identities']['OUT']['share_class']=='Common Stock'
    assert result['held_guards']['OUT']['share_class']=='Common Stock'
    assert result['held_guards']['OUT']['quantity_transitions']==[]
    assert result['held_guards']['OUT']['quote_qualification_granted'] is False
    assert result['historical_source_epochs']['OUT']=='HIST_OUT'
    assert (x.rows,x.spell)==before and [content_hash(row) for row in x.rows]==hashes
    assert all(not set(cols)&{'Open','Close','NAV','price','notional'} for _,cols,_ in x.calls)

@pytest.mark.parametrize('field,value',[
    ('title_of_class','COM NEW'),('title_of_class','Class A'),('title_of_class','ADS'),
    ('security_id','OTHER'),('security_id_type','OTHER'),('cusip','OTHER'),
    ('moomoo_transport_code','US.OTHER'),('mapping_status','UNRESOLVED')])
def test_current_entry_consumer_true_class_or_nonclass_conflict_stays_blocked(full_source_guard,field,value):
    x=_boundary(full_source_guard);x.rows[-1][field]=value;before=deepcopy((x.rows,x.spell))
    with pytest.raises(inputs.HeldLineageUnavailable):x.source.session(x.ctx,x.original,x.book)
    assert (x.rows,x.spell)==before

@pytest.mark.parametrize('change',[
    {'effective_start':pd.Timestamp('2023-01-05')},
    {'effective_end':pd.Timestamp('2023-01-03')}])
def test_generic_common_does_not_extend_current_source_interval(full_source_guard,change):
    x=_boundary(full_source_guard);x.rows[-1].update(change)
    with pytest.raises(inputs.HeldLineageUnavailable,match='UNIQUE_CURRENT_ENTRY'):
        x.source.session(x.ctx,x.original,x.book)


def test_real_book_partial_sell_keeps_old_common_literal_and_exact_raw_quantity(held_book):
    x=held_book;x.identity['share_class']='Common Stock';first=x.admitted();old=deepcopy(first)
    x.book.observe_fills(x.fill(q=.4,before=1.,side='SELL',order='SELL',signal='2023-01-04',day='2023-01-05'))
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=.6),
        {'A':x.guard('2023-01-05',share_class='COM')})['A']
    assert proof['position_id']==old['position_id'] and proof['seed_share_class']=='Common Stock'
    assert proof['seed_source_row_identity']==old['seed_source_row_identity']
    assert proof['actual_quantity_binding']['raw_quantity']==pytest.approx(.6)
    assert [r['stage'] for r in proof['quantity_transition_refs']]==['ACTUAL_RAW_SHARE_FILL']
    assert x.book.source_lineages()['A'][0]['identity']['share_class']=='Common Stock'
    assert x.book.pending_fill_count==0


def test_real_book_add_keeps_two_exact_source_seeds_and_old_position(held_book):
    x=held_book;x.identity['share_class']='Common Stock';first=x.admitted()
    seed=dict(x.seed('2023-01-04'),share_class='COM',seed_source_row_identity='NEXT_ORIGINAL_ROW')
    before=deepcopy(seed);x.book.note_qualified_decision('2023-01-04',{'A':seed})
    x.book.observe_fills(x.fill(q=1.,before=1.,order='ADD',signal='2023-01-04',day='2023-01-05'))
    pending=x.book.source_lineages()['A'][0]['pending_fill_refs'][0]['candidate_seed']
    assert pending['share_class']=='COM' and pending['seed_source_row_identity']=='NEXT_ORIGINAL_ROW'
    proof=x.book.qualified_proofs(x.ctx('2023-01-05',units=2.),{'A':x.guard('2023-01-05',share_class='COM')})['A']
    assert proof['position_id']==first['position_id'] and proof['seed_share_class']=='Common Stock'
    assert proof['seed_source_row_identity']==first['seed_source_row_identity']
    assert proof['actual_quantity_binding']['raw_quantity']==2.
    assert [r['stage'] for r in proof['quantity_transition_refs']]==['ACTUAL_RAW_SHARE_FILL']
    assert seed==before


def test_generic_common_current_to_fit_bridge_keeps_clock_source_and_raw_literals(causal):
    x=causal;x.identities['OUT']['share_class']='Common Stock'
    x.adapter.source_contract['binding']['held_lineages']['OUT']['share_class']='COM'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));domain=x.adapter.qualified_causal_domain(ctx)
    before=deepcopy((x.identities,x.adapter.source_contract))
    bridge=x.adapter._guard_supplement(ctx,domain,x.adapter._last)['OUT']
    assert bridge['relation']=='SAME_SECURITY_AND_HISTORICAL_SUPPORT_NOT_SAME_POSITION_ID'
    assert (x.identities,x.adapter.source_contract)==before and x.calls==[]

@pytest.mark.parametrize('defect,reason',[
    ('class','UNPROVED_FIT_ASOF'),('uid','UNPROVED_FIT_ASOF'),('raw','UNPROVED_FIT_ASOF'),
    ('future','CAUSAL_APPROVED_STATE_CLOCK'),('primary','EXPIRED_AT_NEXT'),
    ('history','CURRENT_SECURITY_AND_HISTORICAL_SUPPORT')])
def test_generic_common_fit_role_does_not_relax_state_gates(causal,defect,reason):
    x=causal;x.identities['OUT']['share_class']='Common Stock'
    x.adapter.source_contract['binding']['held_lineages']['OUT']['share_class']='COM'
    ctx=x.example.context(units=(1.,0.,0.),weights=(.1,0.,0.));domain=x.adapter.qualified_causal_domain(ctx)
    old=x.adapter.source_contract['binding']['held_lineages']['OUT']
    if defect=='class':old['share_class']='COM NEW'
    elif defect=='uid':old['uid']='OTHER'
    elif defect=='raw':old['raw_code']='OTHER'
    elif defect=='future':x.adapter.supplemental['state_available_at']=inputs.producer._clock('2023-01-04').isoformat()
    elif defect=='primary':x.adapter._last['original']['event']['dependency_local_event_ids']['PRIMARY']='NEXT'
    else:x.adapter._last['source']['historical_source_epochs']['OUT']='OTHER'
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match=reason):
        x.adapter._guard_supplement(ctx,domain,x.adapter._last)
    assert x.calls==[]


def test_generic_ASCII_gate_preserves_prior_exact_nonASCII_tokens():
    literal='Common\u017ftock'
    assert inputs._held_class_equal(literal,literal)
    assert inputs._held_class_equal('Common\t\u017ftock','Common \u017ftock')
    assert not inputs._held_class_equal('COM',literal)



def _spot_descriptor_document(x):
    d=x.doc
    x.coordinate.update(security_id='L8681T102',cusip='L8681T102',raw_code='US.SPOT')
    d['same_report_date']='31-DEC-2022'
    d['subject'].update(security_id='L8681T102',cusip='L8681T102',
        source_descriptor_pair=['Common Stock','SHS'],
        issuer_source_names=['Spotify Technology SA','SPOTIFY TECHNOLOGY S A'])
    for entry,title,start,end,issuer in zip(d['original_interval_rows'],
            ['Common Stock','SHS'],['2022-11-21','2023-02-22'],['2023-02-21','2023-05-22'],
            d['subject']['issuer_source_names']):
        row=entry['source_row'];row.update(ticker='SPOT',security_id='L8681T102',cusip='L8681T102',
            moomoo_transport_code='US.SPOT',issuer_name=issuer,title_of_class=title,
            effective_start=pd.Timestamp(start),effective_end=pd.Timestamp(end))
        entry['identity']=dict(x.coordinate,share_class=title)
        entry['source_row_content_sha256']=content_hash(row)
    d['bridge_binding_requirements']['source_row_identity_commitments_required']=[
        r['source_row_content_sha256'] for r in d['original_interval_rows']]
    for fact,title,issuer in zip(d['existing_official_dataset_identity_rows'],
            ['Common Stock','SHS','SHS'],['Spotify Technology SA','SPOTIFY TECHNOLOGY S A','SPOTIFY TECHNOLOGY S A']):
        fact.update(CUSIP='L8681T102',TITLEOFCLASS=title,NAMEOFISSUER=issuer)
    for filing,date in zip(d['existing_official_dataset_submission_rows'],['24-JAN-2023','13-FEB-2023','14-FEB-2023']):
        filing.update(FILING_DATE=date,PERIODOFREPORT='31-DEC-2022')
    return x


def test_spot_explicit_prior_report_source_pair_does_not_create_generic_shs_alias(descriptor_bridge_document):
    x=_spot_descriptor_document(descriptor_bridge_document);before=deepcopy(x.doc)
    old=dict(x.coordinate,share_class='Common Stock');new=dict(x.coordinate,share_class='SHS')
    assert not inputs._held_security_identity_equal(old,new)
    bridge=x.load()
    assert inputs._held_security_identity_equal(old,new,bridge)
    assert all(inputs._held_source_row_descriptor_bridge(row['source_row'],old,bridge)
        for row in x.doc['original_interval_rows'])
    assert x.doc==before
    other=dict(new,cusip='OTHER')
    assert not inputs._held_security_identity_equal(old,other,bridge)


def test_spot_proof_cannot_silently_change_legacy_default_report_gate(descriptor_bridge_document):
    x=_spot_descriptor_document(descriptor_bridge_document)
    x.doc.pop('same_report_date')
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match='SHARE_DESCRIPTOR_FACTS'):
        x.load()


@pytest.mark.parametrize('report',[None,True,20221231,'2022-12-31','31-dec-2022','31-DEC-2026','31-DEC-2021'])
def test_spot_report_date_is_explicit_typed_and_not_an_open_search(descriptor_bridge_document,report):
    x=_spot_descriptor_document(descriptor_bridge_document);x.doc['same_report_date']=report
    with pytest.raises(inputs.ExistingRiskInputUnavailable,match='EXACT_DECLARED_DESCRIPTOR_SAME_REPORT_DATE'):
        x.load()


@pytest.mark.parametrize('defect',['issuer','issuer_set','cusip','share_unit','putcall','report','late_filing','row_hash','permission'])
def test_spot_prior_report_retains_original_source_maturity_and_hard_guards(descriptor_bridge_document,defect):
    x=_spot_descriptor_document(descriptor_bridge_document);d=x.doc
    if defect=='issuer':d['existing_official_dataset_identity_rows'][0]['NAMEOFISSUER']='OTHER ISSUER'
    elif defect=='issuer_set':d['subject']['issuer_source_names']=['Spotify Technology SA']
    elif defect=='cusip':d['existing_official_dataset_identity_rows'][0]['CUSIP']='OTHER'
    elif defect=='share_unit':d['existing_official_dataset_identity_rows'][0]['SSHPRNAMTTYPE']='PRN'
    elif defect=='putcall':d['existing_official_dataset_identity_rows'][0]['PUTCALL']='CALL'
    elif defect=='report':d['existing_official_dataset_submission_rows'][0]['PERIODOFREPORT']='30-SEP-2022'
    elif defect=='late_filing':d['existing_official_dataset_submission_rows'][0]['FILING_DATE']='22-FEB-2023'
    elif defect=='row_hash':d['original_interval_rows'][0]['source_row']['source_filing']='MUTATED'
    else:d['bridge_binding_requirements']['buy_permission_extension_allowed']=True
    with pytest.raises(inputs.ExistingRiskInputUnavailable):x.load()


# DNA source descendants below are synthetic identity facts, never real account rows.
def _dna_descriptor_document(x):
    x=_spot_descriptor_document(x);d=x.doc
    x.coordinate.update(security_id='37611X100',cusip='37611X100',raw_code='US.DNA')
    d['same_report_date']='30-JUN-2024'
    d['subject'].update(security_id='37611X100',cusip='37611X100',source_descriptor_pair=['Common Stock','CL A SHS'],
        issuer_source_names=['Ginkgo Bioworks Holdings Inc','GINKGO BIOWORKS HOLDINGS INC'])
    for entry,title,start,end,issuer in zip(d['original_interval_rows'],['Common Stock','CL A SHS'],
            ['2024-05-22','2024-08-21'],['2024-08-20','2024-11-20'],d['subject']['issuer_source_names']):
        row=entry['source_row'];row.update(ticker='DNA',security_id='37611X100',cusip='37611X100',
            moomoo_transport_code='US.DNA',issuer_name=issuer,title_of_class=title,
            effective_start=pd.Timestamp(start),effective_end=pd.Timestamp(end))
        entry['identity']=dict(x.coordinate,share_class=title);entry['source_row_content_sha256']=content_hash(row)
    d['bridge_binding_requirements']['source_row_identity_commitments_required']=[
        r['source_row_content_sha256'] for r in d['original_interval_rows']]
    for fact,title,issuer in zip(d['existing_official_dataset_identity_rows'],['Common Stock','CL A SHS','CL A SHS'],
            [d['subject']['issuer_source_names'][0],d['subject']['issuer_source_names'][1],d['subject']['issuer_source_names'][1]]):
        fact.update(CUSIP='37611X100',TITLEOFCLASS=title,NAMEOFISSUER=issuer)
    for filing,date in zip(d['existing_official_dataset_submission_rows'],['26-JUL-2024','14-AUG-2024','14-AUG-2024']):
        filing.update(FILING_DATE=date,PERIODOFREPORT='30-JUN-2024')
    return x


def test_dna_exact_same_report_descriptor_source_is_not_a_class_a_alias(descriptor_bridge_document):
    x=_dna_descriptor_document(descriptor_bridge_document);before=deepcopy(x.doc);bridges=x.load()
    old,new=[r['identity'] for r in x.doc['original_interval_rows']]
    assert not inputs._held_security_identity_equal(old,new)
    assert inputs._held_security_identity_equal(old,new,bridges)
    assert not inputs._held_security_identity_equal(old,dict(new,cusip='37611X209',security_id='37611X209'),bridges)
    assert x.doc==before


@pytest.mark.parametrize('defect',['issuer','unit','putcall','report','late','row','permission'])
def test_dna_descriptor_keeps_original_hard_source_gates(descriptor_bridge_document,defect):
    x=_dna_descriptor_document(descriptor_bridge_document);d=x.doc
    if defect=='issuer':d['existing_official_dataset_identity_rows'][0]['NAMEOFISSUER']='OTHER'
    elif defect=='unit':d['existing_official_dataset_identity_rows'][0]['SSHPRNAMTTYPE']='PRN'
    elif defect=='putcall':d['existing_official_dataset_identity_rows'][0]['PUTCALL']='CALL'
    elif defect=='report':d['existing_official_dataset_submission_rows'][0]['PERIODOFREPORT']='31-MAR-2024'
    elif defect=='late':d['existing_official_dataset_submission_rows'][0]['FILING_DATE']='21-AUG-2024'
    elif defect=='row':d['original_interval_rows'][0]['source_row']['source_filing']='OTHER'
    else:d['bridge_binding_requirements']['cross_cusip_substitution_allowed']=True
    with pytest.raises(inputs.ExistingRiskInputUnavailable):x.load()


@pytest.fixture
def dna_pre_action_extension(descriptor_bridge_document,monkeypatch):
    x=_dna_descriptor_document(descriptor_bridge_document);bridges=x.load();ref=lambda n:dict(path='D:/synthetic/dna/'+n+'.json',sha256='a'*64)
    oldentry,postentry=deepcopy(x.doc['original_interval_rows'])
    oldrow,postrow=[r['source_row'] for r in (oldentry,postentry)]
    newrow=dict(postrow,effective_start=pd.Timestamp('2024-11-21'),effective_end=pd.Timestamp('2025-02-23'),
        security_id='37611X209',cusip='37611X209',title_of_class='CL A NEW',source_filing='SYNTHETIC_NEW')
    new=inputs._held_identity(dict(newrow,share_class='CL A NEW',raw_code='US.DNA',raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
    event=dict(ticker='DNA',event_date='2024-08-20',status='SHARE_ONLY_SUPPORTED',quantity_multiplier=.025,
        event_fingerprint='b'*64,source_fingerprint='c'*64)
    typed=dict(event,event_fingerprint='d'*64)
    parent=dict(source_ref=ref('parent'),facts_ref=ref('facts'),original_uid_intervals_ref=x.uidref,
        original_event_binding_ref=ref('event'),original_event=event,old_identity=postentry['identity'],new_identity=new,
        old_row=postrow,new_row=newrow,old_row_hash=content_hash(postrow),new_row_hash=content_hash(newrow),
        post_split_trading_session='2024-08-20',source_filing_day='2024-08-19',historical_availability_qualified=False,
        original_event_pre2026_projection_ref=ref('projection'))
    value=dict(schema='B_SOURCE_BOUND_PRE_ACTION_CLASS_A_SEED_EXTENSION_V1',status='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION',
        rule=deepcopy(inputs.DELAYED_IDENTITY_METADATA_TRANSPORT_RULE),
        relation_role='EXACT_PRE_ACTION_IMMUTABLE_SEED_TO_EXISTING_POST_SPLIT_CLASS_A_SOURCE_RELATION',
        original_uid_intervals_ref=x.uidref,original_event_binding_ref=parent['original_event_binding_ref'],
        historical_original_archive_vintage='UNKNOWN',existing_post_action_transport_ref=parent['source_ref'],
        share_class_descriptor_bridge_ref=ref('bridge'),original_pre_action_seed_row=oldentry,account_owner_ref=ref('account_owner'))
    for k in ('quantity_effect','typed_CA_event','historical_observations_relabelled','historical_availability_qualified',
            'strict_PIT','production_qualified','quote_qualified','certified_NAV','BUY_permission','pool_interval_extension'):value[k]=False
    facts=dict(original_share_event=typed)
    docs={ref('parent')['path']:dict(schema='B_SOURCE_BOUND_DELAYED_COMMON_CLASS_IDENTITY_METADATA_TRANSPORT_V2'),ref('facts')['path']:facts}
    pins=[];calls=[]
    interface=SimpleNamespace(pin=lambda r:(pins.append(deepcopy(r)),r['path'])[1],read=lambda p:deepcopy(docs[p]))
    def parent_load(i,r,u,e):
        calls.append(deepcopy(r));assert r==parent['source_ref'] and u==x.uidref and e==parent['original_event_binding_ref']
        return (deepcopy(parent),)
    monkeypatch.setattr(inputs,'_load_delayed_identity_metadata_transport',parent_load)
    monkeypatch.setattr(inputs,'_load_share_class_descriptor_bridge',lambda i,r,u:deepcopy(bridges))
    def load():return inputs._load_pre_action_class_a_seed_extension(interface,ref('extension'),value,x.uidref,parent['original_event_binding_ref'])
    return SimpleNamespace(load=load,value=value,parent=parent,facts=facts,bridges=bridges,pins=pins,calls=calls,ref=ref)


def test_dna_pre_action_extension_reuses_existing_v2_and_immutable_exact_rows(dna_pre_action_extension):
    x=dna_pre_action_extension;before=deepcopy((x.value,x.parent,x.facts,x.bridges));item=x.load()[0]
    assert x.calls==[x.parent['source_ref']]
    assert item['original_event']==x.facts['original_share_event']
    assert item['original_source_event']==x.parent['original_event']
    assert item['old_row_hash']==x.value['original_pre_action_seed_row']['source_row_content_sha256']
    assert item['new_row_hash']==x.parent['new_row_hash']
    assert (x.value,x.parent,x.facts,x.bridges)==before
    assert item['original_event']['quantity_multiplier']==.025 and item['pre_action_existing_held'] is True
    assert x.ref('account_owner') in x.pins
    for row in item['exact_pre_action_historical_rows']:assert inputs._held_pre_action_class_a_past_row(row,item)
    extra=dict(item['old_row'],source_filing='UNPROVEN_SAME_COORDINATE_ROW')
    assert not inputs._held_pre_action_class_a_past_row(extra,item)


@pytest.mark.parametrize('defect',['rowhash','source_ref','class','date','future_seed','bridge_rows','new_cusip','typed_ratio','quantity','owner'])
def test_dna_pre_action_extension_keeps_original_source_and_no_new_event_gates(dna_pre_action_extension,defect):
    x=dna_pre_action_extension;v=x.value
    if defect=='rowhash':v['original_pre_action_seed_row']['source_row_content_sha256']='f'*64
    elif defect=='source_ref':v['original_uid_intervals_ref']=x.ref('OTHER')
    elif defect=='class':v['original_pre_action_seed_row']['identity']['share_class']='Class B'
    elif defect=='date':v['original_pre_action_seed_row']['source_row']['effective_end']=pd.Timestamp('2024-08-19')
    elif defect=='future_seed':v['original_pre_action_seed_row']['source_row']['effective_start']=pd.Timestamp('2024-08-20')
    elif defect=='bridge_rows':x.bridges[0]['row_hashes']=('f'*64,x.parent['old_row_hash'])
    elif defect=='new_cusip':x.parent['new_identity']['cusip']='37611X100'
    elif defect=='typed_ratio':x.facts['original_share_event']['quantity_multiplier']=.05
    elif defect=='quantity':v['quantity_effect']=True
    else:v['account_owner_ref']['sha256']='invalid'
    with pytest.raises((inputs.ExistingRiskInputUnavailable,inputs.HeldLineageUnavailable,ValueError)):x.load()


def _dna_own_processed_spell(item):
    seed=dict(item['old_identity'],signal_session='2024-06-13',seed_source_ref=item['original_uid_intervals_ref'],
        seed_source_row_identity=item['old_row_hash'],historical_source_epoch='SYNTHETIC_JUNE')
    actual=dict(position_id='OWN_POSITION',kind='SPLIT',session='2024-08-20',
        event_fingerprint=item['original_event']['event_fingerprint'],old_identity=deepcopy(item['old_identity']),
        new_identity=deepcopy(item['old_identity']),source_ref=item['original_event_binding_ref'],owner_ref=item['account_owner_ref'],
        before_raw_quantity=40.,after_raw_quantity=1.)
    spell=dict(role='ACCEPTED_POSITION',position_id='OWN_POSITION',seed=seed,seed_admitted_at='2024-06-14',processed_share_transitions=[actual])
    return seed,spell


def test_dna_new_metadata_requires_own_already_processed_share_chain_and_adds_no_quantity(dna_pre_action_extension):
    item=dna_pre_action_extension.load()[0];seed,spell=_dna_own_processed_spell(item);before=deepcopy((seed,spell))
    assert inputs._held_identity_metadata_binding(seed,item['old_identity'],'2024-08-21',(item,),held_spell=spell) is None
    for day in ('2024-11-21','2025-02-24','2025-05-22','2025-08-22','2025-11-21','2025-12-31'):
        out=inputs._held_identity_metadata_binding(seed,item['old_identity'],day,(item,),held_spell=spell)
        assert out['current_identity']==item['new_identity'] and out['quantity_effect'] is False and out['typed_CA_event'] is False
        assert out['actual_processed_share_transition']==spell['processed_share_transitions'][0]
    assert (seed,spell)==before


@pytest.mark.parametrize('defect',['missing','duplicate','fingerprint','position','source','owner','before','ratio','old_class','new_identity','pending','late_admission','seedrow'])
def test_dna_pre_action_binding_rejects_any_unproved_own_chain(dna_pre_action_extension,defect):
    item=dna_pre_action_extension.load()[0];seed,spell=_dna_own_processed_spell(item);actual=spell['processed_share_transitions'][0]
    if defect=='missing':spell['processed_share_transitions']=[]
    elif defect=='duplicate':spell['processed_share_transitions'].append(deepcopy(actual))
    elif defect=='fingerprint':actual['event_fingerprint']='OTHER'
    elif defect=='position':actual['position_id']='OTHER_ACCOUNT_POSITION'
    elif defect in ('source','owner'):actual[defect+'_ref']=dna_pre_action_extension.ref('OTHER')
    elif defect=='before':actual['before_raw_quantity']=0.
    elif defect=='ratio':actual['after_raw_quantity']=.025
    elif defect=='old_class':actual['old_identity']['share_class']='CL A SHS'
    elif defect=='new_identity':actual['new_identity']=deepcopy(item['new_identity'])
    elif defect=='pending':spell['role']='PENDING_BUY'
    elif defect=='late_admission':spell['seed_admitted_at']='2024-08-21'
    else:seed['seed_source_row_identity']='OTHER'
    assert inputs._held_identity_metadata_binding(seed,item['old_identity'],'2024-11-21',(item,),held_spell=spell) is None



def test_dna_original_book_commits_own_split_then_transports_only_metadata(dna_pre_action_extension):
    x=dna_pre_action_extension;item=x.load()[0];old=item['old_identity'];new=item['new_identity'];account='SYNTHETIC_DNA'
    book=inputs.HeldPositionLineageBook(account,fill_owner_ref=item['account_owner_ref'],lineage_rule_ref=x.ref('lineage'),
        descriptor_bridges=x.bridges,identity_transports=(item,))
    seed=dict(old,qualified=True,historical_observations_relabelled=False,
        identity_asof=inputs.producer._clock('2024-06-13').isoformat(),seed_source_ref=item['original_uid_intervals_ref'],
        seed_source_row_identity=item['old_row_hash'],historical_source_epoch='SYNTHETIC_JUNE')
    def ctx(day,q):return SimpleNamespace(tickers=('DNA',),signal_date=pd.Timestamp(day),signal_asof=inputs.producer._clock(day),
        current_units=np.array([[q]]),current_weights=np.array([[.1]]))
    def guard(day,identity,**extra):
        out=dict(identity,qualified=True,historical_observations_relabelled=False,decision_session=day,
            mapping_start='2024-06-13',mapping_end_exclusive='2026-01-01',mapping_row_count=1,raw_key_count=1,
            mapping_raw_code='US.DNA',raw_key_code='US.DNA',raw_key_session=day,current_accounting_mapping_ref=x.ref('mapping'),
            current_mapping_row_identity='SYNTHETIC_MAPPING',raw_exact_key_ref=x.ref('raw'),raw_key_row_identity='SYNTHETIC_RAW',
            declared_catalogue_refs=[x.ref('catalogue')],catalogue_checked_from_session='2024-06-13',catalogue_checked_through_session=day,
            processed_event_fingerprints=[],unsupported_event_fingerprints=[],identity_conflict_count=0,
            quantity_transitions=[],identity_metadata_bindings=[])
        out.update(extra);return out
    book.note_qualified_decision('2024-06-13',{'DNA':seed})
    book.observe_fills(pd.DataFrame([dict(path_id=account,order_id='SYNTHETIC_INITIAL',signal_date='2024-06-13',
        execution_date='2024-06-14',ticker='DNA',side='BUY',fractional_shares=40.,index_units_before=0.,index_units_after=40.)]))
    book.qualified_proofs(ctx('2024-06-14',40.),{'DNA':guard('2024-06-14',old)})
    fp=item['original_event']['event_fingerprint']
    transition=dict(qualified=True,typed_event=True,stage='PRE_OPEN',kind='SPLIT',session='2024-08-20',event_fingerprint=fp,
        before_raw_quantity=40.,after_raw_quantity=1.,old_identity=deepcopy(old),new_identity=deepcopy(old),share_ratio=.025,
        source_ref=item['original_event_binding_ref'],owner_ref=item['account_owner_ref'])
    book.qualified_proofs(ctx('2024-08-20',1.),{'DNA':guard('2024-08-20',old,processed_event_fingerprints=[fp],quantity_transitions=[transition])})
    book.qualified_proofs(ctx('2024-08-21',1.),{'DNA':guard('2024-08-21',x.parent['old_identity'])})
    prior=deepcopy(book._positions['DNA']);spell=book.source_lineages()['DNA'][0]
    evidence=inputs._held_identity_metadata_binding(spell['seed'],spell['identity'],'2024-11-21',(item,),held_spell=spell)
    current=guard('2024-11-21',new,identity_metadata_bindings=[evidence])
    proof=book.qualified_proofs(ctx('2024-11-21',1.),{'DNA':current})['DNA']
    assert proof['seed_security_id']=='37611X100' and proof['seed_share_class']=='Common Stock'
    assert book._positions['DNA']['seed']==prior['seed'] and book._positions['DNA']['quantity']==prior['quantity']==1.
    assert proof['quantity_transition_refs']==[] and len(book._positions['DNA']['processed_share_transitions'])==1
    assert inputs._held_metadata_proof_matches_current(proof,new,current)
    # A second metadata day neither replays nor re-applies the split.
    spell=book.source_lineages()['DNA'][0]
    evidence=inputs._held_identity_metadata_binding(spell['seed'],spell['identity'],'2025-12-31',(item,),held_spell=spell)
    proof=book.qualified_proofs(ctx('2025-12-31',1.),{'DNA':guard('2025-12-31',new,identity_metadata_bindings=[evidence])})['DNA']
    assert book._positions['DNA']['quantity']==1. and len(book._positions['DNA']['processed_share_transitions'])==1


@pytest.mark.parametrize('which',['seed','post_action','unproved_same_coordinates','wrong_issuer','wrong_class'])
def test_dna_actual_owner_historical_row_predicate_is_exact(dna_pre_action_extension,which):
    import ast
    from pathlib import Path
    x=dna_pre_action_extension;item=x.load()[0]
    row=deepcopy(item['exact_pre_action_historical_rows'][which=='post_action'])
    if which=='unproved_same_coordinates':row['source_filing']='UNPROVEN_SAME_CUSIP'
    elif which=='wrong_issuer':row['issuer_name']='OTHER'
    elif which=='wrong_class':row['title_of_class']='Class B'
    cls=next(n for n in ast.parse(Path(inputs.__file__).read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='FrozenHeldSourceGuards')
    node=next(n for n in ast.walk(cls) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='bound_old' for t in n.targets))
    ns=dict(vars(inputs),r=row,metadata_bindings=[{'synthetic':True}],transports=(item,),identity=item['new_identity'],day=pd.Timestamp('2024-11-21'),self=SimpleNamespace(descriptor_bridges=x.bridges))
    assert eval(compile(ast.Expression(node.value),'<actual-DNA-source-row-predicate>','eval'),ns) is (which in ('seed','post_action'))
