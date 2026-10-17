"""R11A1 runtime acceptance: synthetic objects only, every real fit forbidden.

Frozen JSON descriptors are metadata. No bank, label, prediction or result body
is opened. Ledger fixtures are in-memory and backend callbacks are stubs.
"""
import copy
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.research.a2.training import stateful_risk_consumer as c


@pytest.fixture(autouse=True)
def forbid_physical_fit(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("REAL_ESTIMATOR_OR_SCALER_FIT_FORBIDDEN")
    for owner, name in ((c.owner, "_fit_job"), (c.models, "fit"),
                        (c.models, "fit_weighted_scaler"),
                        (StandardScaler, "fit"), (Ridge, "fit"),
                        (HistGradientBoostingRegressor, "fit")):
        monkeypatch.setattr(owner, name, forbidden)


@pytest.fixture
def plan():
    return c.FrozenPlan.load()


def packet(plan, family="LW", *, year=2024, mode="train", head="ENTRY", pair=False):
    spec = plan.family(family)
    yr = year - 1 if mode == "train" else year
    day = f"{yr}-12-12" if mode == "train" else f"{yr}-06-12"
    asof = day + "T21:00:00+00:00"
    cutoff = (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d") + "T21:00:00+00:00"
    assets = tuple(f"SYNTHETIC_SID_{i:02d}" for i in range(21))
    uids = {a: "SYNTHETIC_UID_" + a for a in assets}
    epochs = {a: "SYNTHETIC_EPOCH_1" for a in assets}
    support = {"fixture": "SYNTHETIC_ONLY", "scientific_contract": "a" * 64}
    structural = c.structural_identity(assets=assets, uids=uids, epochs=epochs,
        security_coordinate=c.COORDINATE, source_support_identity=support)
    epoch = "R5_CURRENT_POOL_OBSERVED_UIDS:" + c.content_hash(epochs)
    covariance = np.eye(21, dtype=float) * .01 + np.ones((21, 21), dtype=float) * .0005
    receipt = c.SourceReceipt("SYNTHETIC_SOURCE", "SYNTHETIC_V1", "b" * 64,
        cutoff, synthetic=True, identity_epoch=epoch)
    lineage = dict(family=family, method_id=spec["method"], recipe_sha256=spec["recipe_SHA"],
        structural_identity=structural, source_support_identity_sha256=c.content_hash(support),
        asset_uid_epoch_sha256=c.content_hash(dict(uids=uids, epochs=epochs)))
    state = c.RiskState("SYNTHETIC_STATE_" + family, asof, cutoff, assets,
        receipt.source_identity, c.COORDINATE, 5, covariance,
        np.sqrt(np.diag(covariance)),
        {a: dict(uid=uids[a], identity_epoch=epochs[a], pooled_identity_epoch=epoch) for a in assets},
        {a: 252 for a in assets}, epoch, 3., None, None, None, None, None, None, (),
        receipt, "PASS_SYNTHETIC", spec["method"], ("SYNTHETIC_DEPENDENCY",),
        dict(estimator_lineage=lineage, strict_PIT_promotion_eligible=False,
             quote_qualified=False, certified_nav_qualified=False))
    meta = dict(research_id=c.B_RESEARCH_ID, family=family, method=spec["method"],
        recipe_sha256=spec["recipe_SHA"], producer_sha256=spec["producer_SHA"],
        source_path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/bank.joblib", source_sha256="b" * 64,
        source_identity=receipt.source_identity, source_version=receipt.source_version,
        bank_schema="B_R5_EVENT_RISK_BANK_V1", state_schema="SHARED_RISK_STATE_R2", schema_version=1,
        state_available_at=asof, state_sha256=c.risk_state_sha256(state), state_id=state.risk_state_id,
        fit_dependency_ids=list(state.fit_dependency_ids),
        ledger_ref="D:/us-tech-quant-cache/SYNTHETIC_ONLY/ledger.jsonl", ledger_sha256="c" * 64,
        ordered_U=list(assets), uids=uids, epochs=epochs, security_ids={a: a for a in assets}, security_coordinate=c.COORDINATE,
        source_support_identity=support, parameters={"fixture": "SYNTHETIC_ONLY"},
        history_recipe={"origin_sessions": 252}, horizon=5, coordinate=spec["coordinate"],
        cutoff=cutoff, as_of=asof, psd_qualified=True, coverage_qualified=True,
        source_still_valid=True, maturity_still_valid=True, qualification_status="QUALIFIED")
    binding = copy.deepcopy(meta)
    identity = lambda a: dict(sid=a, uid=uids[a], epoch=epochs[a])
    request = dict(decision_date=day, decision_information_time=day + "T22:00:00+00:00",
        actor=identity(assets[0]), entrant=identity(assets[20]) if pair else None,
        raw20=[identity(a) for a in assets[:20]], action_type=1 if pair else 0)
    return state, meta, binding, request


def projected(plan, args, *, family="LW", head="ENTRY", year=2024, mode="train"):
    return c.project_state(plan, *args, family=family, head=head, year=year, mode=mode)


def state_mutation(args, **updates):
    state, meta, binding, request = copy.deepcopy(args)
    state = replace(state, **updates)
    meta["state_sha256"] = c.risk_state_sha256(state)
    return state, meta, binding, request


def test_frozen_identity_and_exact_140_dag(plan):
    assert plan.design["research_id"] == c.RESEARCH_ID
    assert plan.design["scientific_identity"] == c.IDENTITY
    assert len(plan.dag["scopes"]) == 28 and len(plan.dag["nodes"]) == 140
    assert sum(n["kind"] == "estimator" for n in plan.dag["nodes"]) == 112
    assert sum(n["kind"] == "scaler" for n in plan.dag["nodes"]) == 28
    assert plan.dag["scientific_retry"] == 0 and not plan.dag["cross_family_dedup_assumed"]
    assert plan.dag["unallocated"] == 20 and plan.dag["unallocated_may_not_be_spent"] is True


@pytest.mark.parametrize("family", ["SHR_HP", "SHR_CC", "LW", "OAS", "EWMA", "PCA_FACTOR", "QQQ_RESIDUAL"])
def test_each_continuous_family_entry_formula_and_no_covariance_repair(plan, family):
    args = packet(plan, family)
    before = args[0].covariance.copy()
    result = projected(plan, args, family=family)
    w = np.r_[np.ones(20) / 20, 0.]
    expected = [args[0].marginal_sigma[0], before[0, 0], (before @ w)[0], w @ before @ w]
    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-14)
    np.testing.assert_array_equal(args[0].covariance, before)
    assert result.shape == (4,)


def test_pair_seven_columns_and_sell_structural_zero(plan):
    pair = packet(plan, head="UNIFIED_INCUMBENT", pair=True)
    result = projected(plan, pair, head="UNIFIED_INCUMBENT")
    np.testing.assert_allclose(result[4:], [pair[0].marginal_sigma[20], pair[0].covariance[20, 20], pair[0].covariance[0, 20]])
    sell = projected(plan, packet(plan, head="UNIFIED_INCUMBENT"), head="UNIFIED_INCUMBENT")
    np.testing.assert_array_equal(sell[4:], np.zeros(3))


@pytest.mark.parametrize("field", [
    "research_id", "family", "method", "recipe_sha256", "producer_sha256", "source_path",
    "source_sha256", "source_identity", "source_version", "bank_schema", "state_schema",
    "schema_version", "state_available_at", "state_sha256", "state_id", "fit_dependency_ids",
    "ledger_ref", "ledger_sha256", "ordered_U", "uids", "epochs", "security_ids", "security_coordinate",
    "source_support_identity", "parameters", "history_recipe", "horizon", "coordinate",
    "cutoff", "as_of", "psd_qualified", "coverage_qualified", "source_still_valid",
    "maturity_still_valid", "qualification_status"])
@pytest.mark.parametrize("value", [None, "MISSING"])
def test_required_metadata_null_or_missing_fail_closed(plan, field, value):
    state, meta, binding, request = packet(plan)
    if value == "MISSING":
        del meta[field]
    else:
        meta[field] = value
    with pytest.raises(c.ConsumerBlocked):
        projected(plan, (state, meta, binding, request))


@pytest.mark.parametrize("case", [
    "missing_actor", "wrong_actor_uid", "wrong_actor_epoch", "wrong_ordered_U", "duplicate_uid",
    "wrong_horizon", "future_available", "wrong_recipe", "wrong_producer", "wrong_state_sha",
    "wrong_family", "wrong_source", "missing_raw20", "duplicate_raw20", "wrong_raw20_uid",
    "wrong_raw20_epoch", "raw20_missing_one", "pair_entrant_missing", "pair_self",
    "psd_absent", "qual_string_true", "wrong_schema_version_type", "future_train_state",
    "source_receipt_mismatch", "coverage_mismatch", "wrong_coordinate"])
def test_identity_clock_source_and_raw20_invalid_cases(plan, case):
    state, meta, binding, request = packet(plan, head="UNIFIED_INCUMBENT", pair=True)
    if case == "missing_actor": request["actor"]["sid"] = "ABSENT"
    elif case == "wrong_actor_uid": request["actor"]["uid"] = "OTHER"
    elif case == "wrong_actor_epoch": request["actor"]["epoch"] = "OTHER"
    elif case == "wrong_ordered_U": meta["ordered_U"] = list(reversed(meta["ordered_U"]))
    elif case == "duplicate_uid": meta["uids"][meta["ordered_U"][1]] = meta["uids"][meta["ordered_U"][0]]
    elif case == "wrong_horizon": meta["horizon"] = 20
    elif case == "future_available": meta["state_available_at"] = "2024-01-02T21:00:00+00:00"
    elif case == "wrong_recipe": meta["recipe_sha256"] = "f" * 64
    elif case == "wrong_producer": meta["producer_sha256"] = "f" * 64
    elif case == "wrong_state_sha": meta["state_sha256"] = "f" * 64
    elif case == "wrong_family": meta["family"] = "EWMA"
    elif case == "wrong_source": meta["source_path"] = "D:/other/bank.joblib"
    elif case == "missing_raw20": request["raw20"] = None
    elif case == "duplicate_raw20": request["raw20"][1] = request["raw20"][0]
    elif case == "wrong_raw20_uid": request["raw20"][1]["uid"] = "OTHER"
    elif case == "wrong_raw20_epoch": request["raw20"][1]["epoch"] = "OTHER"
    elif case == "raw20_missing_one": request["raw20"] = request["raw20"][:19]
    elif case == "pair_entrant_missing": request["entrant"]["sid"] = "ABSENT"
    elif case == "pair_self": request["entrant"] = copy.deepcopy(request["actor"])
    elif case == "psd_absent": meta["psd_qualified"] = False
    elif case == "qual_string_true": meta["coverage_qualified"] = "true"
    elif case == "wrong_schema_version_type": meta["schema_version"] = True
    elif case == "future_train_state":
        request["decision_date"] = "2024-06-12"
        request["decision_information_time"] = "2024-06-12T22:00:00+00:00"
        meta["as_of"] = meta["state_available_at"] = "2024-06-12T21:00:00+00:00"
    elif case == "source_receipt_mismatch": state = replace(state, source_receipt=replace(state.source_receipt, source_sha256="f" * 64))
    elif case == "coverage_mismatch": state.coverage[state.assets[0]]["uid"] = "OTHER"
    elif case == "wrong_coordinate": meta["coordinate"] = "OTHER"
    with pytest.raises(c.ConsumerBlocked):
        projected(plan, (state, meta, binding, request), head="UNIFIED_INCUMBENT")


@pytest.mark.parametrize("case", ["nan", "dimension", "asymmetric", "nonpsd", "sigma_nan", "sigma_negative", "sigma_diagonal", "sigma_dimension", "integer_covariance"])
def test_covariance_and_typed_sigma_invariants_block_without_repair(plan, case):
    args = packet(plan)
    covariance = args[0].covariance.copy()
    sigma = args[0].marginal_sigma.copy()
    if case == "nan": covariance[0, 0] = np.nan
    elif case == "dimension": covariance = covariance[:-1, :-1]
    elif case == "asymmetric": covariance[0, 1] = .005
    elif case == "nonpsd": covariance[0, 1] = covariance[1, 0] = .1
    elif case == "sigma_nan": sigma[0] = np.nan
    elif case == "sigma_negative": sigma[0] = -sigma[0]
    elif case == "sigma_diagonal": sigma[0] += .01
    elif case == "sigma_dimension": sigma = sigma[:-1]
    elif case == "integer_covariance": covariance = covariance.astype(int)
    args = state_mutation(args, covariance=covariance, marginal_sigma=sigma)
    before = copy.deepcopy(args[0].covariance)
    with pytest.raises(c.ConsumerBlocked): projected(plan, args)
    np.testing.assert_array_equal(args[0].covariance, before)


@pytest.mark.parametrize("year", [2024, 2025])
def test_evaluation_same_year_allowed_but_never_carried_back_to_fit(plan, year):
    args = packet(plan, year=year, mode="eval")
    assert projected(plan, args, year=year, mode="eval").shape == (4,)
    with pytest.raises(c.ConsumerBlocked): projected(plan, args, year=year, mode="train")
    with pytest.raises(c.ConsumerBlocked): projected(plan, args, year=year-1, mode="eval")


def test_budget_160_pass_161_block_and_boolean_rejected():
    assert c.validate_budget(160) is True
    for value in (161, True, -1):
        with pytest.raises(c.ConsumerBlocked): c.validate_budget(value)



def scope_fixture(plan, family="LW", *, head="ENTRY", year=2024, mode="train", rows=3):
    base_packet = packet(plan, family, year=year, mode=mode, head=head,
                         pair=head == "UNIFIED_INCUMBENT")
    state, meta, binding, request = base_packet
    records = []
    packets = {}
    names = c.parent.SINGLE if head == "ENTRY" else (*c.parent.PAIR, "action_type")
    for j in range(rows):
        sid = f"SYNTHETIC_ROW_{j:02d}"
        row = {name: float(j + 1) / 100 for name in names}
        row.update(sample_id=sid, signal_date=pd.Timestamp(request["decision_date"]),
            label_qualified=True, label_mature_date=pd.Timestamp(request["decision_date"]) + pd.Timedelta(days=1),
            target=.002 * (j + 1), base_weight=1.,
            actor_sid=request["actor"]["sid"], actor_uid=request["actor"]["uid"], actor_epoch=request["actor"]["epoch"],
            decision_information_time=request["decision_information_time"],
            execution_friction_bps=10, decoder="P0", r8_pair_key=sid if head != "ENTRY" else None)
        if head != "ENTRY":
            row.update(action_type=1, **{"entrant_" + k: v for k, v in request["entrant"].items()})
        records.append(row)
        packets[sid] = copy.deepcopy((state, meta, binding))
    frame = pd.DataFrame(records)
    frame.attrs["target_contract"] = "R10_NATIVE_HMEAN_NET_ACTION_ADVANTAGE_H3_H5_H10_H20"
    raw20 = {request["decision_date"]: copy.deepcopy(request["raw20"])}
    return frame, packets, raw20


def package(plan, family="LW", *, head="ENTRY", year=2024):
    frame, packets, raw = scope_fixture(plan, family, head=head, year=year)
    return c.build_scope(plan, family, head, year, frame, packets, raw)


def estimator_node(plan, pkg, learner="hgb", arm="BASE_STATE"):
    return next(n for n in plan.runtime_nodes(pkg) if n.get("learner") == learner and n.get("arm") == arm)


def preset_scaler(pkg):
    width = pkg["joint"].shape[1]
    obj = StandardScaler()
    obj.n_features_in_ = width
    obj.mean_ = np.linspace(.01, .02, width)
    obj.scale_ = np.linspace(1., 2., width)
    obj.var_ = obj.scale_ ** 2
    obj.n_samples_seen_ = len(pkg["joint"])
    return obj


def synthetic_authority():
    return dict(research_id=c.RESEARCH_ID, scientific_identity=c.IDENTITY,
        design_sha256=c.DESIGN_SHA, DAG_sha256=c.DAG_SHA, **{"2026_locked": True},
        **{key: True for key in c.GATES}, information_source_fingerprint="e" * 64,
        registry_admitted=True, publication_bindings={
            key: dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/" + key + ".json",
                      sha256="d" * 64, qualified=True) for key in c.SOURCE_SLOTS})


def test_matched_arms_share_exact_rows_y_weights_dates_and_keys(plan):
    frame, packets, raw = scope_fixture(plan)
    bad = frame.iloc[1].sample_id
    packets[bad][1]["state_sha256"] = "f" * 64
    pkg = c.build_scope(plan, "LW", "ENTRY", 2024, frame, packets, raw)
    assert pkg["matched"]["row_keys"] == ["SYNTHETIC_ROW_00", "SYNTHETIC_ROW_02"]
    assert pkg["blocked_rows"][0]["sample_id"] == bad
    assert pkg["matched"]["target"] == pkg["target"].tolist()
    assert pkg["matched"]["weights"] == pkg["weights"].tolist()
    assert pkg["matched"]["action_keys"] == pkg["matched"]["row_keys"]
    assert pkg["matched"]["cutoff"] == "2024-01-01"
    assert pkg["matched"]["friction_bps"] == 10 and pkg["matched"]["decoder"] == "P0"
    base = c.arm_input(pkg, estimator_node(plan, pkg))[0]
    plus = c.arm_input(pkg, estimator_node(plan, pkg, arm="BASE_PLUS_ONE_RISK_STATE"))[0]
    assert base.shape[0] == plus.shape[0] == len(pkg["target"])
    np.testing.assert_array_equal(base, plus[:, :base.shape[1]])


@pytest.mark.parametrize("case", ["target_contract", "friction", "decoder", "r8_pair_key", "label_maturity", "empty_risk"])
def test_native_row_contract_changes_fail_closed(plan, case):
    frame, packets, raw = scope_fixture(plan, head="UNIFIED_INCUMBENT")
    if case == "target_contract": frame.attrs["target_contract"] = "OTHER"
    elif case == "friction": frame["execution_friction_bps"] = 5
    elif case == "decoder": frame["decoder"] = "OTHER"
    elif case == "r8_pair_key": frame["r8_pair_key"] = "OTHER"
    elif case == "label_maturity": frame["label_mature_date"] = pd.Timestamp("2024-01-01")
    elif case == "empty_risk": packets = {}
    with pytest.raises(c.ConsumerBlocked):
        c.build_scope(plan, "LW", "UNIFIED_INCUMBENT", 2024, frame, packets, raw)


def test_scope_isolation_family_masks_are_independent(plan):
    frame, packets, raw = scope_fixture(plan, "EWMA")
    for args in packets.values(): args[1]["state_sha256"] = "f" * 64
    with pytest.raises(c.ConsumerBlocked):
        c.build_scope(plan, "EWMA", "ENTRY", 2024, frame, packets, raw)
    lw = package(plan, "LW")
    hp = package(plan, "SHR_HP", head="UNIFIED_INCUMBENT", year=2025)
    assert lw["scope"] == "LW|ENTRY|2024" and len(lw["target"]) == 3
    assert hp["scope"] == "SHR_HP|UNIFIED_INCUMBENT|2025" and len(hp["target"]) == 3
    frame, packets, raw = scope_fixture(plan, "EWMA")
    packets[frame.iloc[0].sample_id][1]["state_sha256"] = "f" * 64
    ewma = c.build_scope(plan, "EWMA", "ENTRY", 2024, frame, packets, raw)
    assert len(ewma["target"]) == 2 and len(lw["target"]) == 3
    assert ewma["mask_identity"] != lw["mask_identity"]


def test_runtime_node_exact_frozen_one_to_one_mapping(plan):
    for scope in plan.dag["scopes"]:
        family, head, year = scope.split("|")
        pkg = package(plan, family, head=head, year=int(year))
        runtime = plan.runtime_nodes(pkg)
        frozen = plan.scope_nodes(scope)
        assert len(runtime) == len(frozen) == 5
        assert [n["node_id"] for n in runtime] == [n["node_id"] for n in frozen]
        for actual, original in zip(runtime, frozen):
            assert all(actual[k] == v for k, v in original.items())
            assert actual["mask_identity"] == pkg["mask_identity"]
            assert actual["input_identity"] == pkg["input_identity"]


@pytest.mark.parametrize("field,value", [("capacity", "HIGH"), ("seed", 20260929),
    ("cutoff", "2025-01-01"), ("mask_identity", "f" * 64),
    ("parameters", {"alpha": 1., "solver": "auto"})])
def test_runtime_node_tamper_rejected(plan, field, value):
    pkg = package(plan)
    node = estimator_node(plan, pkg, "ridge")
    node[field] = value
    with pytest.raises(c.ConsumerBlocked): c.scientific_tuple(plan, node, pkg, scaler_binding="e" * 64)


def test_joint_scaler_base_slice_and_plus_all_without_fit(plan):
    pkg = package(plan)
    scaler = preset_scaler(pkg)
    before = copy.deepcopy(scaler.__dict__)
    binding = c.scaler_identity(pkg)
    base, names = c.arm_input(pkg, estimator_node(plan, pkg, "ridge"), scaler=scaler, scaler_binding=binding)
    plus, plus_names = c.arm_input(pkg, estimator_node(plan, pkg, "ridge", "BASE_PLUS_ONE_RISK_STATE"), scaler=scaler, scaler_binding=binding)
    np.testing.assert_array_equal(base, plus[:, :len(pkg["base_names"])] )
    expected = (pkg["joint"] - scaler.mean_) / scaler.scale_
    np.testing.assert_allclose(plus, expected)
    assert names == pkg["base_names"]
    assert plus_names == (*pkg["base_names"], *pkg["risk_names"])
    for key, old in before.items(): np.testing.assert_array_equal(scaler.__dict__[key], old)


@pytest.mark.parametrize("failure", ["missing", "wrong_binding", "wrong_width", "nonfinite_scale"])
def test_ridge_scaler_failure_hgb_survives_same_scope(plan, failure):
    pkg = package(plan)
    scaler = preset_scaler(pkg)
    binding = c.scaler_identity(pkg)
    if failure == "missing": scaler = None
    elif failure == "wrong_binding": binding = "f" * 64
    elif failure == "wrong_width": scaler.n_features_in_ += 1
    else: scaler.scale_[0] = np.nan
    with pytest.raises(c.ConsumerBlocked):
        c.arm_input(pkg, estimator_node(plan, pkg, "ridge"), scaler=scaler, scaler_binding=binding)
    hgb, _ = c.arm_input(pkg, estimator_node(plan, pkg), scaler=scaler, scaler_binding=binding)
    np.testing.assert_array_equal(hgb, pkg["base"])


def test_reserve_persist_happens_before_stub_backend(plan):
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    events = []
    order = []
    def persist(event):
        order.append(event["event"])
        events.append(copy.deepcopy(event))
    def backend(*args):
        assert order == ["A1_NODE_RESERVED"]
        assert len(events) == 1 and events[0]["node_id"] == node["node_id"]
        order.append("STUB_BACKEND")
        return "SYNTHETIC_NO_FIT"
    assert c.dispatch_reserved(plan, node, pkg, events, persist, backend, synthetic_authority()) == "SYNTHETIC_NO_FIT"
    assert order == ["A1_NODE_RESERVED", "STUB_BACKEND", "A1_NODE_COMPLETE"]


def test_durable_reservation_failure_prevents_backend(plan):
    pkg = package(plan)
    calls = []
    def persist(event): raise OSError("SYNTHETIC_PERSIST_FAILURE")
    with pytest.raises(OSError):
        c.dispatch_reserved(plan, estimator_node(plan, pkg), pkg, [], persist,
                            lambda *a: calls.append("FORBIDDEN"), synthetic_authority())
    assert not calls


def test_failed_stub_backend_no_refund_and_no_retry(plan):
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    events = []
    def persist(event): events.append(copy.deepcopy(event))
    def fail(*a): raise RuntimeError("SYNTHETIC_BACKEND_FAILURE")
    with pytest.raises(RuntimeError, match="SYNTHETIC_BACKEND_FAILURE"):
        c.dispatch_reserved(plan, node, pkg, events, persist, fail, synthetic_authority())
    assert [e["event"] for e in events] == ["A1_NODE_RESERVED", "A1_NODE_FAILED"]
    assert sum(e.get("units", 0) for e in events) == 1
    with pytest.raises(c.ConsumerBlocked, match="RETRY"):
        c.dispatch_reserved(plan, node, pkg, events, persist, fail, synthetic_authority())
    assert len(events) == 2


def test_all_140_nodes_reserve_once_and_unallocated20_unspendable(plan):
    events = []
    def persist(event): events.append(copy.deepcopy(event))
    for scope in plan.dag["scopes"]:
        family, head, year = scope.split("|")
        pkg = package(plan, family, head=head, year=int(year))
        for node in plan.runtime_nodes(pkg):
            proof = c.scientific_tuple(plan, node, pkg, scaler_binding=c.scaler_identity(pkg))
            c.reserve_node(plan, node, proof, events, persist)
    assert len(events) == 140 and sum(e["units"] for e in events) == 140
    unknown = copy.deepcopy(node)
    unknown["node_id"] += "|UNALLOCATED"
    with pytest.raises(c.ConsumerBlocked): c.reserve_node(plan, unknown, proof, events, persist)
    assert len(events) == 140


@pytest.mark.parametrize("field", c.REUSE_FIELDS)
def test_exact_reuse_requires_every_runtime_proof_field(plan, field):
    pkg = package(plan)
    node = estimator_node(plan, pkg, "ridge")
    proof = c.scientific_tuple(plan, node, pkg, scaler_binding=c.scaler_identity(pkg))
    assert c.exact_reuse_proof(proof, copy.deepcopy(proof)) is True
    changed = copy.deepcopy(proof)
    changed[field] = {"SYNTHETIC_DIFFERENT": True}
    assert c.exact_reuse_proof(proof, changed) is False
    missing = copy.deepcopy(proof)
    del missing[field]
    with pytest.raises(c.ConsumerBlocked): c.exact_reuse_proof(proof, missing)


@pytest.mark.parametrize("field", ["source_path", "source_sha256", "source_version", "schema_version",
    "cutoff", "state_available_at", "ordered_U", "uids", "epochs", "security_ids", "horizon", "coordinate", "method",
    "parameters", "history_recipe", "state_sha256", "ledger_ref", "ledger_sha256", "fit_dependency_ids"])
def test_synthetic_fingerprint_deterministic_and_sensitive(plan, field):
    meta = packet(plan)[1]
    original = c.source_fingerprint(meta)
    assert original == c.source_fingerprint(copy.deepcopy(meta))
    changed = copy.deepcopy(meta)
    if field.endswith("sha256"): changed[field] = "f" * 64
    elif field in ("schema_version", "horizon"): changed[field] += 1
    elif isinstance(changed[field], dict): changed[field]["fixture_change"] = "SYNTHETIC"
    elif isinstance(changed[field], list): changed[field] = list(reversed(changed[field])) + ["SYNTHETIC_CHANGE"]
    else: changed[field] += "|SYNTHETIC_CHANGE"
    assert original != c.source_fingerprint(changed)
    changed[field] = None
    with pytest.raises(c.ConsumerBlocked): c.source_fingerprint(changed)


@pytest.mark.parametrize("gate", c.GATES)
@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_every_literal_activation_gate_blocks_non_true(plan, gate, value):
    authority = synthetic_authority()
    authority[gate] = value
    pkg = package(plan)
    calls = []
    with pytest.raises(c.ConsumerBlocked):
        c.dispatch_reserved(plan, estimator_node(plan, pkg), pkg, [], calls.append,
                            lambda *a: calls.append("FORBIDDEN_BACKEND"), authority)
    assert not calls


def test_handoff_schema_is_metadata_only_and_no_fake_bank():
    schema = c.handoff_schema()
    assert schema["$id"] == "R11A1_B_R5_HANDOFF_MANIFEST_SCHEMA_R1"
    assert set(c.SOURCE_SLOTS).issubset(schema["required"])
    state_keys = schema["properties"]["states"]["items"]["required"]
    assert {"ordered_U", "uids", "epochs", "horizon", "coordinate", "event_ids"}.issubset(state_keys)
    assert "covariance" not in state_keys and "marginal_sigma" not in state_keys



@pytest.mark.parametrize("field", ["target", "weights", "base", "risk", "joint", "dates", "source_state_fingerprints"])
def test_runtime_rejects_mutable_package_drift(plan, field):
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    if field != "source_state_fingerprints": pkg[field] = pkg[field].copy()
    if field == "dates": pkg[field][0] = np.datetime64("2023-12-13")
    elif field == "source_state_fingerprints": pkg[field] = ("f" * 64, *pkg[field][1:])
    else: pkg[field].flat[0] += .25
    with pytest.raises(c.ConsumerBlocked): c.scientific_tuple(plan, node, pkg)



@pytest.mark.parametrize("case", ["family", "budget", "node_parameter"])
def test_in_memory_frozen_plan_mutation_rejected(plan, case):
    args = packet(plan)
    if case == "family": plan.design["families_order"][0] = "NEW_FAMILY"
    elif case == "budget": plan.dag["hard_physical_cap"] = 161
    else: plan.dag["nodes"][1]["parameters"]["alpha"] = 1.
    with pytest.raises(c.ConsumerBlocked): projected(plan, args)


def registry_view(authority):
    return dict(status="PASS", count=1, head_sha256="a" * 64, entities=[dict(
        entity_id=c.RESEARCH_ID, row_hash="b" * 64, status="OPEN",
        information_source_fingerprint=authority["information_source_fingerprint"],
        metadata=dict(frozen_design_sha256=c.DESIGN_SHA, frozen_DAG_sha256=c.DAG_SHA,
            scientific_identity=c.IDENTITY, publication_bindings=authority["publication_bindings"],
            scope_input_bindings=authority.get("scope_input_bindings"),
            strict_PIT_promotion_eligible=False, account_qualified=False,
            **{"2026_locked": True}, numeric_execution_authorized=True))])


def mocked_registry(monkeypatch, view):
    from pathlib import Path
    from scripts.maintenance import research_registry as registry
    monkeypatch.setattr(registry, "_load_config", lambda *a, **k: (Path("D:/SYNTHETIC_ONLY/registry"), {}))
    monkeypatch.setattr(registry, "query_registry", lambda *a, **k: copy.deepcopy(view))


def test_caller_claim_admission_cannot_replace_canonical_registry(monkeypatch):
    authority = synthetic_authority()
    mocked_registry(monkeypatch, dict(status="PASS", count=0, head_sha256="a" * 64, entities=[]))
    with pytest.raises(c.ConsumerBlocked): c.verify_registry_acceptance(authority)


@pytest.mark.parametrize("case", ["valid", "head", "row", "source", "design", "scope", "numeric", "promotion"])
def test_pinned_canonical_registry_acceptance_synthetic_only(monkeypatch, case):
    authority = synthetic_authority()
    authority.update(registry_head_sha256="a" * 64, registry_row_hash="b" * 64)
    view = registry_view(authority)
    row = view["entities"][0]
    if case == "head": view["head_sha256"] = "f" * 64
    elif case == "row": row["row_hash"] = "f" * 64
    elif case == "source": row["information_source_fingerprint"] = "f" * 64
    elif case == "design": row["metadata"]["frozen_design_sha256"] = "f" * 64
    elif case == "scope": row["metadata"]["scope_input_bindings"] = {"OTHER": True}
    elif case == "numeric": row["metadata"]["numeric_execution_authorized"] = False
    elif case == "promotion": row["metadata"]["strict_PIT_promotion_eligible"] = True
    mocked_registry(monkeypatch, view)
    if case == "valid": assert c.verify_registry_acceptance(authority) is True
    else:
        with pytest.raises(c.ConsumerBlocked): c.verify_registry_acceptance(authority)


def test_execute_hook_reuses_same_lock_ledger_and_physical_owner_without_io(plan, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path
    import json
    import joblib
    from scripts.research.a2.training import stateful_execution as execution
    from scripts.storage import storage_r2a as storage
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    run = Path("D:/us-tech-quant-backtests/SYNTHETIC_ONLY_R11A1")
    authority = synthetic_authority()
    authority.update(registry_head_sha256="a" * 64, registry_row_hash="b" * 64,
        scope_input_bindings={pkg["scope"]: dict(input_identity=pkg["input_identity"],
            source_states=list(pkg["source_state_fingerprints"]))})
    mocked_registry(monkeypatch, registry_view(authority))
    cfg = dict(research_id=c.RESEARCH_ID, frozen_design_sha256=c.DESIGN_SHA, frozen_DAG_sha256=c.DAG_SHA,
        execution_authority_sha256=c.owner.digest(authority),
        information_source_fingerprint=authority["information_source_fingerprint"],
        real_numeric_execution_authorized=True, dependency_paths=[])
    events = []
    order = []
    @contextmanager
    def lock(*args, **kw):
        assert args[0] == run and kw["namespace"] == c.RESEARCH_ID
        order.append("LOCK")
        yield "SYNTHETIC_NO_FILE_LOCK"
        order.append("UNLOCK")
    monkeypatch.setattr(execution, "continuation_lock", lock)
    monkeypatch.setattr(c, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(c, "validate_parent_source_pins", lambda *a, **k: None)
    original_read = Path.read_text
    def read(path, *a, **kw):
        if path == run / "run_config.json":
            assert order == ["LOCK"]
            order.append("CONFIG")
            return json.dumps(cfg)
        return original_read(path, *a, **kw)
    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(c.owner, "sha", lambda *a, **k: "d" * 64)
    monkeypatch.setattr(c.owner, "_events", lambda *a: events)
    def append(path, event):
        assert path == run / "FIT_LOG.jsonl"
        order.append(event["event"])
        events.append(copy.deepcopy(event))
    monkeypatch.setattr(c.owner, "_append", append)
    original_mkdir, original_exists = Path.mkdir, Path.exists
    monkeypatch.setattr(Path, "mkdir", lambda path, *a, **k: None if path.is_relative_to(run) else original_mkdir(path, *a, **k))
    monkeypatch.setattr(Path, "exists", lambda path: False if path.is_relative_to(run) else original_exists(path))
    monkeypatch.setattr(storage, "write_json_atomic", lambda *a, **k: None)
    monkeypatch.setattr(joblib, "dump", lambda *a, **k: None)
    def physical_stub(operation, model_id, x, payload, *args, **kw):
        assert operation == "mechanism" and model_id == node["node_id"]
        assert events[0]["event"] == "A1_NODE_RESERVED"
        assert kw["worker_target"] is c.models.fit_worker
        assert kw["auth"]["max_fit_units"] == 140
        order.append("EXISTING_OWNER_STUB")
        append(run / "FIT_LOG.jsonl", dict(event="FIT_STARTED", fit_units=1, role="SYNTHETIC_NO_FIT"))
        kw["receipt"]["fit_units"] = 1
        return "SYNTHETIC_MODEL_NO_FIT"
    monkeypatch.setattr(c.owner, "_fit_job", physical_stub)
    assert c.execute_node(plan, node, pkg, run, authority) == "SYNTHETIC_MODEL_NO_FIT"
    assert order == ["LOCK", "CONFIG", "A1_NODE_RESERVED", "EXISTING_OWNER_STUB", "FIT_STARTED", "A1_NODE_COMPLETE", "UNLOCK"]



@pytest.mark.parametrize("typed_sigma", [0., 1e-7])
def test_zero_variance_typed_sigma_exact_diagonal_semantics(plan, typed_sigma):
    args = packet(plan)
    covariance = args[0].covariance.copy()
    covariance[0, :] = 0.
    covariance[:, 0] = 0.
    sigma = args[0].marginal_sigma.copy()
    sigma[0] = typed_sigma
    args = state_mutation(args, covariance=covariance, marginal_sigma=sigma)
    if typed_sigma == 0.:
        result = projected(plan, args)
        assert result[0] == result[1] == result[2] == 0.
    else:
        with pytest.raises(c.ConsumerBlocked): projected(plan, args)



def ticker_packet(plan):
    state, meta, _, request = packet(plan)
    assets = tuple(f"SYNTHETIC_TICKER_{j:02d}" for j in range(len(state.assets)))
    lookup = dict(zip(state.assets, assets))
    uids = {lookup[a]: uid for a, uid in meta["uids"].items()}
    epochs = {lookup[a]: epoch for a, epoch in meta["epochs"].items()}
    security_ids = {lookup[a]: a for a in state.assets}
    epoch = "R5_CURRENT_POOL_OBSERVED_UIDS:" + c.content_hash(epochs)
    structural = c.structural_identity(assets=assets, uids=uids, epochs=epochs,
        security_coordinate=c.COORDINATE, source_support_identity=meta["source_support_identity"])
    notes = copy.deepcopy(state.notes)
    notes["estimator_lineage"].update(structural_identity=structural,
        asset_uid_epoch_sha256=c.content_hash(dict(uids=uids, epochs=epochs)))
    coverage = {lookup[a]: {**row, "pooled_identity_epoch": epoch} for a, row in state.coverage.items()}
    receipt = replace(state.source_receipt, identity_epoch=epoch)
    state = replace(state, assets=assets, identity_epoch=epoch, source_receipt=receipt,
        coverage=coverage, notes=notes, effective_sample_size={a: 252 for a in assets})
    meta.update(ordered_U=list(assets), uids=uids, epochs=epochs, security_ids=security_ids,
                state_sha256=c.risk_state_sha256(state))
    return state, meta, copy.deepcopy(meta), request


def test_b_ticker_asset_keys_bind_independent_security_ids(plan):
    args = ticker_packet(plan)
    expected = projected(plan, packet(plan))
    result = projected(plan, args)
    np.testing.assert_array_equal(result, expected)
    assert args[0].assets[0] != args[3]["actor"]["sid"]


@pytest.mark.parametrize("case", ["wrong_request_sid", "missing_source_sid_map", "wrong_bound_sid_map", "missing_asset_sid", "duplicate_sid"])
def test_ticker_to_sid_mapping_missing_wrong_or_duplicate_blocks(plan, case):
    state, meta, binding, request = ticker_packet(plan)
    asset = state.assets[0]
    if case == "wrong_request_sid": request["actor"]["sid"] = "OTHER_SID"
    elif case == "missing_source_sid_map": del meta["security_ids"]
    elif case == "wrong_bound_sid_map": meta["security_ids"][asset] = "OTHER_SID"
    elif case == "missing_asset_sid":
        del meta["security_ids"][asset]
        binding["security_ids"] = copy.deepcopy(meta["security_ids"])
    elif case == "duplicate_sid":
        meta["security_ids"][state.assets[1]] = meta["security_ids"][asset]
        binding["security_ids"] = copy.deepcopy(meta["security_ids"])
    with pytest.raises(c.ConsumerBlocked): projected(plan, (state, meta, binding, request))


@pytest.mark.parametrize("case", ["valid", "unknown_field", "wrong_field_type", "wrong_container_type"])
def test_shared_persisted_source_receipt_dict_normalized_without_state_mutation(plan, case):
    from dataclasses import asdict
    args = packet(plan)
    receipt = asdict(args[0].source_receipt)
    if case == "unknown_field": receipt["UNKNOWN_EXTRA_FIELD"] = True
    elif case == "wrong_field_type": receipt["source_sha256"] = 42
    elif case == "wrong_container_type": receipt = [receipt]
    args = state_mutation(args, source_receipt=receipt)
    before = c.risk_state_sha256(args[0])
    if case == "valid": assert projected(plan, args).shape == (4,)
    else:
        with pytest.raises(c.ConsumerBlocked): projected(plan, args)
    assert c.risk_state_sha256(args[0]) == before
    assert type(args[0].source_receipt) is (list if case == "wrong_container_type" else dict)


def alias_fixture(plan):
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    proof = c.scientific_tuple(plan, node, pkg)
    events = []
    reservation = c.reserve_node(plan, node, proof, events, lambda e: events.append(copy.deepcopy(e)))
    events.append(dict(event="A1_NODE_COMPLETE", research_id=c.RESEARCH_ID,
        node_id=node["node_id"], reservation_sha256=c.owner.digest(reservation)))
    receipt = dict(status="TRAINED", research_id=c.RESEARCH_ID, fit_units=1,
        scientific_tuple=copy.deepcopy(proof), reservation=copy.deepcopy(reservation),
        model_path="D:/us-tech-quant-backtests/SYNTHETIC_ONLY/model.joblib", model_sha256="d" * 64)
    return pkg, node, receipt, events


def test_runtime_exact_reuse_alias_zero_units_preserves_hypothesis(plan, monkeypatch):
    pkg, node, receipt, events = alias_fixture(plan)
    monkeypatch.setattr(c.owner, "sha", lambda *a: "d" * 64)
    monkeypatch.setattr(c, "assert_safe_output_path", lambda *a, **k: None)
    before_units = sum(e.get("units", 0) for e in events)
    alias = c.exact_reuse_alias(plan, node, pkg, receipt, events, lambda e: events.append(copy.deepcopy(e)))
    assert alias["units"] == 0 and alias["hypothesis_identity_preserved"] is True
    assert alias["node_id"] == node["node_id"]
    assert alias["event"] == "A1_NODE_EXACT_REUSED"
    assert sum(e.get("units", 0) for e in events) == before_units == 1


@pytest.mark.parametrize("case", ["failed_receipt", "wrong_proof", "wrong_hash", "missing_completion", "missing_reservation", "failed_attempt", "duplicate_reservation"])
def test_exact_reuse_failed_or_unproven_artifact_never_aliases(plan, monkeypatch, case):
    pkg, node, receipt, events = alias_fixture(plan)
    monkeypatch.setattr(c.owner, "sha", lambda *a: "f" * 64 if case == "wrong_hash" else "d" * 64)
    monkeypatch.setattr(c, "assert_safe_output_path", lambda *a, **k: None)
    if case == "failed_receipt": receipt["status"] = "FAILED"
    elif case == "wrong_proof": receipt["scientific_tuple"]["y"] = "f" * 64
    elif case == "missing_completion": events = events[:1]
    elif case == "missing_reservation": events = events[1:]
    elif case == "failed_attempt": events.append(dict(event="A1_NODE_FAILED", node_id=node["node_id"]))
    elif case == "duplicate_reservation": events.append(copy.deepcopy(events[0]))
    appended = []
    with pytest.raises(c.ConsumerBlocked): c.exact_reuse_alias(plan, node, pkg, receipt, events, appended.append)
    assert not appended


def test_runtime_parent_source_pin_change_blocks_before_any_reservation(plan, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path
    import json
    from scripts.research.a2.training import stateful_execution as execution
    pkg = package(plan)
    node = estimator_node(plan, pkg)
    run = Path("D:/us-tech-quant-backtests/SYNTHETIC_ONLY")
    authority = synthetic_authority()
    authority.update(registry_head_sha256="a" * 64, registry_row_hash="b" * 64,
        scope_input_bindings={pkg["scope"]: dict(input_identity=pkg["input_identity"],
            source_states=list(pkg["source_state_fingerprints"]))})
    mocked_registry(monkeypatch, registry_view(authority))
    cfg = dict(research_id=c.RESEARCH_ID, frozen_design_sha256=c.DESIGN_SHA, frozen_DAG_sha256=c.DAG_SHA,
        execution_authority_sha256=c.owner.digest(authority), information_source_fingerprint=authority["information_source_fingerprint"],
        real_numeric_execution_authorized=True, dependency_paths=[])
    calls = []
    @contextmanager
    def lock(*a, **k):
        calls.append("LOCK")
        yield "SYNTHETIC_LOCK"
    monkeypatch.setattr(execution, "continuation_lock", lock)
    monkeypatch.setattr(c, "assert_safe_output_path", lambda *a, **k: None)
    original_read = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **k: json.dumps(cfg) if path == run / "run_config.json" else original_read(path, *a, **k))
    def changed(*a, **k): raise c.ConsumerBlocked("SYNTHETIC_PARENT_SOURCE_PIN_CHANGED")
    monkeypatch.setattr(c, "validate_parent_source_pins", changed)
    monkeypatch.setattr(c.owner, "_append", lambda *a, **k: calls.append("FORBIDDEN_RESERVATION"))
    with pytest.raises(c.ConsumerBlocked, match="SOURCE_PIN_CHANGED"):
        c.execute_node(plan, node, pkg, run, authority)
    assert calls == ["LOCK"]
