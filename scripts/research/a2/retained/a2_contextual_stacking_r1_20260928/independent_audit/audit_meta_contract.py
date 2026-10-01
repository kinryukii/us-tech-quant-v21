"""Read-only independent verification; never fit models or inspect 2026 returns.

Recompute moments and first-order conditions from already frozen panels, verify
actual deserialization and production allocator/data identities, and inspect
runtime load receipts only. The separate root ledger audit owns reconciliation.
"""
from __future__ import annotations
import argparse
import ast
import copy
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import meta as m
import replay as r
import ensemble as old_ensemble


def require(condition, message):
    if not bool(condition):
        raise RuntimeError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                   allow_nan=False, default=str), encoding="utf-8")


def normalize_dates(dates, allowed, weights):
    _, inv = np.unique(dates, return_inverse=True)
    w = np.asarray(weights, float).copy()
    w[~allowed] = 0.
    total = np.bincount(inv, weights=w)
    return np.where(allowed, w / total[inv], 0.)


def load_panel(year):
    path = ROOT / "panel_artifacts" / f"panel_{year}.npz"
    with np.load(path, allow_pickle=False) as file:
        a = {key: file[key].copy() for key in ("p", "basis", "z", "row_dates", "allowed", "weights", "target_clip")}
    keys = pd.read_parquet(ROOT / "panel_artifacts" / f"panel_keys_{year}.parquet",
                          columns=["signal_date", "label_end_date", "behavior_path"])
    a["label_end_dates"] = np.repeat(keys.label_end_date.to_numpy(), 5)
    a["path"] = np.repeat(keys.behavior_path.to_numpy(str), 5)
    return a


def population(panels, stage):
    if stage == "final":
        data = {key: np.concatenate([panels[2024][key], panels[2025][key]]) for key in panels[2024]}
    else:
        data = {key: value.copy() for key, value in panels[2024].items()}
    if stage == "internal":
        mask = (data["row_dates"] < np.datetime64("2024-10-01")) & (
                data["label_end_dates"] < np.datetime64("2024-10-01"))
        data = {key: value[mask] for key, value in data.items()}
        data["weights"] = normalize_dates(data["row_dates"], data["allowed"], data["weights"])
    return data


def raw_moments(matrix, weights):
    total = float(weights.sum())
    mean = (matrix * weights[:, None]).sum(axis=0) / total
    variance = ((matrix - mean)**2 * weights[:, None]).sum(axis=0) / total
    positive = matrix[weights > 0]
    minimum, maximum = positive.min(axis=0), positive.max(axis=0)
    constant = minimum == maximum
    mean[constant], variance[constant] = minimum[constant], 0.
    scale = np.sqrt(np.maximum(variance, 0.))
    scale[scale <= np.finfo(float).eps] = 1.
    return dict(mean=mean, variance=variance, scale=scale, minimum=minimum, maximum=maximum)


def check_scaler(scaler, matrix, weights):
    moments = raw_moments(matrix, weights)
    max_errors = {}
    for field, attr in [("mean", "mean_"), ("variance", "var_"), ("scale", "scale_"),
                         ("minimum", "min_"), ("maximum", "max_")]:
        got = np.asarray(getattr(scaler, attr))
        error = float(np.max(np.abs(moments[field] - got)))
        require(np.allclose(moments[field], got, rtol=1e-10, atol=1e-11), f"SCALER_TRAIN_POPULATION_MISMATCH:{field}")
        max_errors[field] = error
    require(np.isclose(scaler.weight_sum_, weights.sum(), rtol=1e-12), "SCALER_WEIGHT_SUM_MISMATCH")
    require(scaler.positive_rows_ == np.count_nonzero(weights), "SCALER_POSITIVE_ROW_MISMATCH")
    return max_errors


def independent_design(model, data):
    raw = np.column_stack([data["p"], data["basis"], data["z"]])
    main = (raw - model.main_scaler.mean_) / model.main_scaler.scale_
    product = np.einsum("ni,nj->nij", main[:, :12], main[:, 17:21]).reshape(-1, 48)
    interaction = (product - model.interaction_scaler.mean_) / model.interaction_scaler.scale_
    return main if model.kind == "M0" else np.column_stack([main, interaction])


def check_fit_model(model, record, data):
    expected_order = m.MAIN_FEATURES + (m.INTERACTION_FEATURES if model.kind == "M1" else [])
    require(model.feature_order == expected_order == record["feature_order"], "UNPLANNED_META_FEATURE")
    require(len(model.coefficients) == (21 if model.kind == "M0" else 69), "WRONG_META_WIDTH")
    require(model.alpha_main == record["alpha_main"] == 100., "MAIN_PENALTY_DRIFT")
    require(model.interaction_multiplier == record["interaction_multiplier"], "INTERACTION_MULTIPLIER_DRIFT")
    cutoff = np.datetime64("2024-10-01" if model.stage == "internal" else m.STAGE_CUTOFFS[model.stage])
    require((data["row_dates"] < cutoff).all() and (data["label_end_dates"] < cutoff).all(), "META_LABEL_TIME_LEAKAGE")
    require(record["train_days"] == len(np.unique(data["row_dates"])), "TRAIN_DAY_RECEIPT_MISMATCH")
    require(record["fit_rows"] == len(data["p"]), "TRAIN_ROW_RECEIPT_MISMATCH")
    coefficients = pd.read_parquet(record["coefficient_artifact"])
    require(coefficients.feature.tolist() == expected_order, "COEFFICIENT_ORDER_DRIFT")
    require(np.array_equal(coefficients.coefficient.to_numpy(), model.coefficients), "COEFFICIENT_CONTENT_MISMATCH")
    penalty = np.r_[np.full(21, 100.), np.full(48, 100. * model.interaction_multiplier) if model.kind == "M1" else []]
    require(np.array_equal(coefficients.penalty.to_numpy(), penalty), "RECORDED_REGULARIZATION_MISMATCH")
    design = independent_design(model, data)
    action_constant_interactions = []
    if model.kind == "M1":
        action_constant_interactions = [index for index, name in enumerate(m.INTERACTION_FEATURES)
            if name.startswith("mlp_logit__times__") or name.startswith("mlp_preference__times__")]
        require(len(action_constant_interactions)==8, "WRONG_STRUCTURAL_ACTION_CONSTANT_COUNT")
        constant_values=design[:,np.array(action_constant_interactions)+21].reshape(-1,5,8)
        require(np.max(np.abs(constant_values-constant_values[:,:1,:]))<1e-12,
                "EXPECTED_ACTION_CONSTANT_INTERACTIONS_VARY_BY_ACTION")
    predicted = model.intercept + design @ model.coefficients
    require(np.allclose(predicted, model.predict(data["p"], data["z"], data["basis"]), rtol=1e-12, atol=1e-12), "MODEL_HAS_NONCONTRACT_TERM")
    weights = normalize_dates(data["row_dates"], data["allowed"], data["weights"])
    residual = predicted - data["target_clip"]
    augmented = np.column_stack([np.ones(len(design)), design])
    gradient = augmented.T @ (weights * residual)
    gradient[1:] += penalty * model.coefficients
    rhs = augmented.T @ (weights * data["target_clip"])
    relative = float(np.linalg.norm(gradient) / max(np.linalg.norm(rhs), np.finfo(float).tiny))
    require(relative < 1e-10, "INDEPENDENT_PENALIZED_OBJECTIVE_NOT_STATIONARY")
    take = np.unique(np.linspace(0, len(data["p"])-1, min(32, len(data["p"])), dtype=int))
    p, z, basis = data["p"][take], data["z"][take], data["basis"][take]
    derivative = model.effective_coefficients(z)["raw"]
    errors = []
    baseline = model.predict(p, z, basis)
    for column in range(12):
        step = .01 * model.main_scaler.scale_[column]
        changed = p.copy(); changed[:, column] += step
        observed = (model.predict(changed, z, basis) - baseline) / step
        errors.append(float(np.max(np.abs(observed-derivative[:,column]))))
        require(np.allclose(observed, derivative[:,column], rtol=1e-7, atol=1e-7), "EFFECTIVE_COEFFICIENT_IS_NOT_UTILITY_DERIVATIVE")
    require(record["coefficients_are_funding_weights"] is False, "COEFFICIENTS_MISLABELLED_AS_FUNDING")
    return dict(stage=model.stage, kind=model.kind, interaction_multiplier=model.interaction_multiplier,
        main_columns=21, added_interaction_columns=48 if model.kind == "M1" else 0,
        structurally_action_constant_interactions=8 if model.kind == "M1" else 0,
        maximum_interactions_directly_affecting_action_minus_zero=40 if model.kind == "M1" else 0,
        main_penalty=100., interaction_penalty=100.*model.interaction_multiplier if model.kind == "M1" else None,
        train_days=record["train_days"], rows=len(design), train_signal_max=record["train_signal_max"],
        train_label_end_max=record["train_label_end_max"], artifact_sha256=m.sha(record["artifact"]),
        main_scaler_sha256=record["main_scaler_sha256"],
        embedded_main_scaler_array_sha256=m.scaler_array_sha256(model.main_scaler),
        independent_stationarity_relative_residual=relative,
        maximum_effective_raw_derivative_error=max(errors), coefficient_semantics="derivative of action utility, never capital shares")


def check_internal_selection(panels, receipt):
    selection = read(m.OUT / "INTERNAL_SELECTION.json")
    data = panels[2024]
    train_mask = (data["row_dates"] < np.datetime64("2024-10-01")) & (data["label_end_dates"] < np.datetime64("2024-10-01"))
    val_mask = (data["row_dates"] >= np.datetime64("2024-10-01")) & (data["label_end_dates"] < np.datetime64("2025-01-01"))
    predictions = pd.read_parquet(selection["predictions_path"])
    require(predictions.signal_date.dt.year.eq(2024).all() and predictions.label_end_date.lt("2025-01-01").all(), "SELECTION_READ_AFTER_2024")
    require(np.array_equal(predictions.panel_row_index.to_numpy(), np.flatnonzero(val_mask)), "SELECTION_ROW_POPULATION_MISMATCH")
    require(selection["candidates"] == [4.,16.,64.] and selection["selection_2025_rows"] == selection["selection_2026_rows"] == 0,
            "SELECTION_SCOPE_DRIFT")
    metrics = []
    weights = normalize_dates(data["row_dates"][val_mask], data["allowed"][val_mask], data["weights"][val_mask])
    for multiplier in [4.,16.,64.]:
        model = joblib.load(m.OUT / f"internal_M1_{int(multiplier)}.joblib")
        predicted = model.predict(data["p"][val_mask],data["z"][val_mask],data["basis"][val_mask])
        saved_prediction=predictions[f"prediction_M1_{int(multiplier)}"].to_numpy()
        prediction_error=float(np.max(np.abs(predicted-saved_prediction)))
        require(np.allclose(predicted,saved_prediction,rtol=1e-12,atol=1e-14), "INTERNAL_PREDICTION_NOT_REPRODUCED")
        # Raw target is read separately to keep all model fits tied to clipped labels.
        with np.load(ROOT/"panel_artifacts/panel_2024.npz",allow_pickle=False) as f:
            raw_target = f["target_unclipped"][val_mask]
        e = pd.DataFrame({"date":data["row_dates"][val_mask],"loss":weights*(predicted-raw_target)**2})
        mse = float(e.groupby("date").loss.sum().mean())
        expected = next(x["date_equal_mse"] for x in selection["metrics"] if x["kind"]=="M1" and x["multiplier"]==multiplier and x["target"]=="target_unclipped")
        require(np.isclose(mse,expected,rtol=1e-12,atol=1e-18), "SELECTION_OBJECTIVE_MISMATCH")
        metrics.append(dict(multiplier=multiplier,date_equal_unclipped_mse=mse,
            saved_prediction_max_abs_reinference_error=prediction_error))
    best = min(x["date_equal_unclipped_mse"] for x in metrics)
    chosen = max(x["multiplier"] for x in metrics if abs(x["date_equal_unclipped_mse"]-best) <= 1e-12*abs(best))
    require(chosen == selection["selected_multiplier"] == receipt["selected_interaction_multiplier"] == 16., "SELECTION_CHANGED_AFTER_2024")
    return dict(training_dates=int(len(np.unique(data["row_dates"][train_mask]))),
        validation_dates=int(len(np.unique(data["row_dates"][val_mask]))),
        purged_rows=int((~(train_mask|val_mask)).sum()), selected_multiplier=chosen,
        candidates=metrics, selection_after_2024_rows=0, raw_selection_predictions_reproduced=True)


def check_allocator_and_engine():
    require(Path(r.engine_v2.__file__).resolve() == (m.OLD_ROOT/"engine_v2.py").resolve(), "NEW_ENGINE_USED")
    require(Path(r.v.__file__).resolve() == (m.OLD_ROOT/"values.py").resolve(), "NEW_ALLOCATOR_USED")
    original = r.v.allocate_joint_scores
    calls = []
    def spy(scores,tickers,**kwargs):
        calls.append(dict(tickers=list(tickers),max_names=kwargs["max_names"],max_units=kwargs["max_units"],allowed=kwargs["allowed"].copy()))
        return original(scores,tickers,**kwargs)
    ctx = SimpleNamespace(buy_restricted_tickers=("B",),available_slots=17,available_weight=.4321)
    day = pd.DataFrame({"ticker":["A","B","C","D","E"],"new_buy_eligible":[True,True,False,True,True]})
    current = np.array([0.,.075,.05,.025,.1])
    scores = np.array([[0,.1,.15,.25,.3],[0,.2,.25,.3,.5],[0,.3,.4,.6,.7],[0,.2,.3,.32,.35],[0,.1,.2,.3,.4]])
    try:
        r.v.allocate_joint_scores = spy
        weights, selected, allowed = r.allocate(day,ctx,current,scores)
    finally:
        r.v.allocate_joint_scores = original
    expected_allowed = (day.new_buy_eligible.to_numpy(bool)&~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy())[:,None] | (r.v.ACTIONS[None,:] <= current[:,None]+1e-10)
    _, expected = original(scores,day.ticker.tolist(),max_names=17,max_units=17,allowed=expected_allowed)
    require(len(calls)==1 and calls[0]["max_units"]==17 and calls[0]["max_names"]==17, "DOWNSTREAM_RULE_DRIFT")
    require(np.array_equal(selected,expected) and np.array_equal(allowed,expected_allowed), "COMMON_ALLOCATOR_NOT_OLD_STACK_RULE")
    main_ast = ast.parse(inspect.getsource(r.main))
    engine_calls = [node for node in ast.walk(main_ast) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                    and isinstance(node.func.value,ast.Name) and node.func.value.id=="engine_v2" and node.func.attr=="run_replay"]
    require(len(engine_calls)==1, "ENGINE_CALL_INTERFACE_DRIFT")
    kws = {k.arg:ast.unparse(k.value) for k in engine_calls[0].keywords}
    require(kws["capacity_fraction"]=="0.01" and kws["cost_bps"]=="args.cost", "EXECUTION_POLICY_DRIFT")
    require(not any(name in kws for name in ["max_weight","max_positions","max_invested","capacity_on_sells"]), "ORIGINAL_EXECUTION_DEFAULTS_CHANGED")
    defaults = inspect.signature(r.engine_v2.run_replay).parameters
    require(defaults["max_weight"].default==.1 and defaults["max_positions"].default==20 and defaults["max_invested"].default==.95,
            "ORIGINAL_ENGINE_DEFAULTS_CHANGED")
    return dict(engine_path=r.engine_v2.__file__,engine_sha256=m.sha(r.engine_v2.__file__),
        allocator_path=r.v.__file__,allocator_sha256=m.sha(r.v.__file__),
        live_allocator_identity_verified=True,toy_call_matches_original_stack=True,
        run_replay_call_keywords=kws,capacity_fraction=.01,max_positions=20,max_weight=.1,max_invested=.95,
        no_extra_allocator_cost_or_covariance_penalty=True)


def check_glw_source():
    features = m.OLD_ROOT/"data/test_features_context.parquet"
    prices = m.OLD_ROOT/"data/test_prices.parquet"
    receipt = read(m.OLD_ROOT/"data/ADMISSIBILITY_RECEIPT.json")
    require(m.sha(features)==receipt["output_sha256"][features.name] and m.sha(prices)==receipt["output_sha256"][prices.name], "ORIGINAL_ISOLATED_TEST_DATA_DRIFT")
    f = pd.read_parquet(features,columns=["ticker","signal_date"],filters=[("ticker","==","GLW"),("signal_date","==",pd.Timestamp("2026-02-26"))])
    p = pd.read_parquet(prices,columns=["ticker","trade_date","price_quality_warning"],filters=[("ticker","==","GLW"),("trade_date","==",pd.Timestamp("2026-02-26"))])
    require(len(f)==0 and len(p)==1 and bool(p.price_quality_warning.iloc[0]), "GLW_ORIGINAL_QUARANTINE_CHANGED")
    return dict(feature_path=str(features),feature_sha256=m.sha(features),price_path=str(prices),price_sha256=m.sha(prices),
        glw_event="2026-02-26",quarantined_feature_rows=0,quarantined_price_warning=True,
        no_2026_performance_read=True)


def check_runtime_receipts(expected_loads, glw, strict):
    records, missing = [], []
    for year in (2025,2026):
        stage = "validation" if year==2025 else "final"
        for cost in (5,10,25):
            scenario = ROOT/f"evaluation_{year}"/f"cost_{cost}"
            for kind in ("M0","M1"):
                path = scenario/kind/"RUNTIME_LOAD_RECEIPT.json"
                if not path.exists():
                    missing.append(str(path)); continue
                runtime = read(path)
                require(runtime["stage"]==stage and runtime["method"]==kind and runtime["year"]==year and
                        runtime["evaluation_cost_bps"]==cost, "REPLAY_STAGE_OR_COST_MISMATCH")
                expected = expected_loads[(stage,kind)]
                actual = runtime["actual_loader_receipt"]
                require(actual["base_stage"]==stage and actual["model_artifact"]==expected["model_artifact"], "REPLAY_LOADED_WRONG_STAGE")
                for p,h in expected["actual_loaded_hashes"].items():
                    require(actual["actual_loaded_hashes"].get(p)==h and runtime["actual_loaded_source_sha256"].get(p)==h, "RUNTIME_LOADED_HASH_NOT_SAVED")
                for p,h in runtime["actual_loaded_source_sha256"].items():
                    require(m.sha(p)==h, "RUNTIME_SOURCE_CHANGED")
                require(runtime["fit_guard_installed"] and runtime["label_interface_absent"] and runtime["original_engine"] and runtime["original_allocator"], "RUNTIME_GUARD_OR_SHARED_RULE_MISSING")
                require(set(runtime["custom_fit_entrypoints_blocked"]) >= {"meta.fit_meta","meta.fit_scalers","WeightedScaler.fit_chunks"}, "CUSTOM_META_FIT_UNGUARDED")
                comparator=runtime.get("comparator_loaded_receipt")
                if year==2025 and cost==10 and kind=="M0":
                    require(comparator is not None and comparator["kind"]=="M1" and comparator["stage"]==stage and
                            comparator["model_artifact"]==expected_loads[(stage,"M1")]["model_artifact"],
                            "SAME_ACCOUNT_COMPARATOR_STAGE_MISMATCH")
                    require(all(runtime["actual_loaded_source_sha256"].get(p)==h==m.sha(p)
                        for p,h in comparator["actual_loaded_hashes"].items()), "COMPARATOR_LOADED_HASH_NOT_SAVED")
                if year==2026:
                    require(runtime["data_source_sha256"].get(glw["feature_path"])==glw["feature_sha256"] and
                            runtime["data_source_sha256"].get(glw["price_path"])==glw["price_sha256"], "RUNTIME_USED_OTHER_TEST_DATA")
                binding = read(scenario/"FROZEN_BEFORE_REPLAY.json")
                require(binding["year"]==year and binding["cost_bps"]==cost and binding["stage"]==stage,
                        "FROZEN_SCENARIO_BINDING_MISMATCH")
                require(Path(binding["engine_path"]).resolve()==(m.OLD_ROOT/"engine_v2.py").resolve() and
                        Path(binding["allocator_path"]).resolve()==(m.OLD_ROOT/"values.py").resolve(), "RUNTIME_NEW_DOWNSTREAM_SOURCE")
                records.append(dict(year=year,cost_bps=cost,kind=kind,stage=stage,runtime_receipt_sha256=m.sha(path),
                    actual_meta_artifact=actual["model_artifact"],loaded_hash_count=len(runtime["actual_loaded_source_sha256"]),status="PASS"))
    if strict:
        require(len(records)==12 and not missing, "NOT_ALL_12_RUNTIME_LOAD_RECEIPTS_READY")
    failed_attempts = sorted(str(p) for y in (2025,2026) for scenario in (ROOT/f"evaluation_{y}").glob("cost_*") if scenario.is_dir()
                             for p in scenario.iterdir() if p.is_dir() and p.name not in ("M0","M1"))
    return dict(status="PASS" if len(records)==12 else "PARTIAL_PENDING_RUNTIME_RECEIPTS",checked=len(records),expected=12,
        receipts=records,missing=missing,preserved_failed_attempt_directories=failed_attempts,
        failed_attempts_counted_as_completed=False,no_ledger_or_return_data_read=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--require-all-runtime",action="store_true")
    args = parser.parse_args()
    guard = r.forbid_fitting(); r.forbid_custom_fitting(m,guard)
    receipt = read(m.OUT/"FIT_RECEIPT.json")
    require(receipt["status"]=="PASS" and receipt["meta_fit_calls"]==8 and len(receipt["fits"])==8, "UNEXPECTED_META_FIT_COUNT")
    require(receipt["new_base_expert_fit_calls"]==receipt["fit_2026_rows"]==receipt["test_rows_read"]==0, "FORBIDDEN_EXPERT_OR_2026_FIT")
    require(receipt["main_scaler_fit_calls"]==receipt["interaction_scaler_fit_calls"]==3, "SCALER_PHASE_COUNT_DRIFT")
    lock = read(ROOT/"PRE_FIT_LOCK.json")
    require(m.sha(ROOT/"EXPERIMENT_CONTRACT.md")==lock["contract_sha256"], "EXPERIMENT_CONTRACT_CHANGED")
    sources = {str(ROOT/name):m.sha(ROOT/name) for name in ("meta.py","train_meta.py","replay.py","EXPERIMENT_CONTRACT.md")}
    for p,h in receipt["input_sha256"].items():
        require(m.sha(p)==h, "META_TRAINING_SOURCE_CHANGED")
    panels = {y:load_panel(y) for y in (2024,2025)}
    scaler_checks, model_checks, models = [], [], {}
    with threadpool_limits(limits=2):
        for stage in ("internal","validation","final"):
            data = population(panels,stage)
            main = joblib.load(m.OUT/f"{stage}_main_scaler.joblib")
            interaction = joblib.load(m.OUT/f"{stage}_interaction_scaler.joblib")
            matrix = np.column_stack([data["p"],data["basis"],data["z"]])
            main_error = check_scaler(main,matrix,data["weights"])
            normalized = (matrix-main.mean_)/main.scale_
            products = np.einsum("ni,nj->nij",normalized[:,:12],normalized[:,17:21]).reshape(-1,48)
            interaction_error = check_scaler(interaction,products,data["weights"])
            require(main.feature_order==m.MAIN_FEATURES and interaction.feature_order==m.INTERACTION_FEATURES, "SCALER_FEATURES_OUTSIDE_CONTRACT")
            records = [rec for rec in receipt["fits"] if rec["stage"]==stage]
            require(len(records)==(4 if stage=="internal" else 2), "META_PHASE_COUNT_DRIFT")
            require(len({rec["main_scaler_sha256"] for rec in records})==len({rec["main_scaler_artifact"] for rec in records})==1, "M0_M1_MAIN_SCALER_NOT_SHARED")
            for rec in records:
                require(m.sha(rec["artifact"])==rec["artifact_sha256"], "META_BINARY_DRIFT")
                model = joblib.load(rec["artifact"])
                require(m.scaler_array_sha256(model.main_scaler)==m.scaler_array_sha256(main)==rec["main_scaler_array_sha256"], "EMBEDDED_MAIN_SCALER_MISMATCH")
                require(m.scaler_array_sha256(model.interaction_scaler)==m.scaler_array_sha256(interaction)==rec["interaction_scaler_array_sha256"], "EMBEDDED_INTERACTION_SCALER_MISMATCH")
                require(model.main_scaler.state()==main.state() and model.interaction_scaler.state()==interaction.state(),
                        "EMBEDDED_SCALER_COMPLETE_STATE_MISMATCH")
                model_checks.append(check_fit_model(model,rec,data))
                models[(stage,rec["kind"],rec["interaction_multiplier"])]=model
            scalar_record = dict(stage=stage,train_days=len(np.unique(data["row_dates"])),
                signal_max=str(pd.Timestamp(data["row_dates"].max()).date()),
                label_end_max=str(pd.Timestamp(data["label_end_dates"].max()).date()),
                main_sha256=m.sha(m.OUT/f"{stage}_main_scaler.joblib"),
                interaction_sha256=m.sha(m.OUT/f"{stage}_interaction_scaler.joblib"),
                independent_main_moment_max_errors=main_error,independent_interaction_moment_max_errors=interaction_error,
                no_Q4_2024_in_internal_preprocessing=bool((data["row_dates"]<np.datetime64("2024-10-01")).all()) if stage=="internal" else None,
                embedded_and_external_scaler_complete_state_exact=True)
            scaler_checks.append(scalar_record)
        selection = check_internal_selection(panels,receipt)
        nested = []
        for stage in ("internal","validation","final"):
            data = population(panels,stage)
            static = models[(stage,"M0",0.)]
            conditional = copy.deepcopy(models[(stage,"M1",16.)])
            conditional.coefficients=np.r_[static.coefficients,np.zeros(48)]; conditional.intercept=static.intercept
            take=min(128,len(data["p"]))
            pred0=static.predict(data["p"][:take],data["z"][:take],data["basis"][:take])
            pred1=conditional.predict(data["p"][:take],data["z"][:take],data["basis"][:take])
            error=float(np.max(np.abs(pred0-pred1)))
            require(error<1e-12,"M1_DOES_NOT_NEST_M0")
            nested.append(dict(stage=stage,zero_interaction_equal_main_max_prediction_error=error))
    expected_loads = {}
    actual_loads = []
    for stage in ("validation","final"):
        for kind in ("M0","M1"):
            policy=m.ContextualPolicy(kind,stage)
            expected_loads[(stage,kind)]=policy.loaded_receipt
            require(policy.base.stage==stage and policy.base.hashes==receipt["inference_dependencies"][stage], "EXPERT_META_STAGE_MISMATCH")
            actual_loads.append(dict(stage=stage,kind=kind,base_stage=policy.base.stage,
                model_artifact=policy.loaded_receipt["model_artifact"],actual_loaded_hashes=policy.loaded_receipt["actual_loaded_hashes"],
                base_predictor_clocks=policy.base.predictor_clocks))
    old_before=read(ROOT/"OLD_SOURCE_BEFORE.json")["files"]
    expert_hashes={}
    for stage in receipt["inference_dependencies"]:
        expert_hashes.update(receipt["inference_dependencies"][stage])
    expert_hashes.update(read(ROOT/"panel_artifacts/PANEL_RECEIPT.json")["actual_loaded_experts"]["2024"]["hashes"])
    require(all(old_before.get(p)==h==m.sha(p) for p,h in expert_hashes.items()), "OLD_EXPERT_ARTIFACT_CHANGED")
    new_pt=[str(p) for p in ROOT.rglob("*.pt")]
    allowed_joblib={str(m.OUT/f"{stage}_{name}.joblib") for stage in ("internal","validation","final")
        for name in ("main_scaler","interaction_scaler","M0",*( ["M1_4","M1_16","M1_64"] if stage=="internal" else ["M1"]))}
    unexpected_joblib=[str(p) for p in ROOT.rglob("*.joblib") if str(p) not in allowed_joblib]
    require(not new_pt and not unexpected_joblib, "NEW_BASE_EXPERT_BINARY_APPEARED")
    downstream=check_allocator_and_engine(); glw=check_glw_source()
    runtime=check_runtime_receipts(expected_loads,glw,args.require_all_runtime)
    require(guard["attempts"]==0,"AUDIT_ATTEMPTED_FITTING")
    require(all(m.sha(p)==h for p,h in sources.items()),"SOURCE_CHANGED_DURING_AUDIT")
    result=dict(status="PASS" if runtime["status"]=="PASS" else "PASS_META_PENDING_RUNTIME",
        experiment="A2_CONTEXTUAL_STACKING_R1",scope="independent metadata/scaler/objective/stage/production binding audit; root separately verifies ledgers",
        meta_fit_calls=8,fit_counts={"internal":4,"validation":2,"final":2},new_base_expert_fit_calls=0,
        selected_interaction_multiplier=16.,main_penalty=100.,selected_interaction_penalty=1600.,
        selection=selection,scaler_checks=scaler_checks,model_checks=model_checks,nested_checks=nested,
        fresh_actual_loads=actual_loads,old_expert_hashes_checked=len(expert_hashes),
        old_expert_artifacts_unchanged=True,new_expert_binaries=[],downstream=downstream,glw_source=glw,
        runtime_binding=runtime,source_sha256=sources,contract_differences=[],audit_fit_attempts=0,
        coefficients_are_funding_weights=False,read_2026_return_or_ledger_data=False,
        limitations=["Receipt counters and preserved files support the recorded fit history; this is not a retrospective operating-system fit-call trace.",
            "The seven supervised value experts retain their original three-state training extrapolation limits; direct MLP retains its separately frozen training-state history. This audit proves input and chronology, not predictive validity."])
    write(OUT/"META_CONTRACT_AUDIT.json",result)
    report=["# 新元工件及对照独立核验", "",
        "元层、预处理和生产接口核验通过。未调用任何拟合，也未读取2026收益、比较表或账本。原组合账本由root另行核验。", "",
        "实际8次元拟合：内部M0一次/M1三次，validation与final各两次；倍率16仅由2024第四季度的62个日期选出。内部训练186日期、400动作行标签purge；validation250日期，final498日期。", "",
        "实际joblib中的主标准化器与同阶段外部文件内容/hash相符，并在M0/M1间共享。独立重算训练期加权均值、方差、范围与惩罚目标的一阶条件；内部预处理只含2024-10-01前且标签已成熟的样本。", "",
        "M1只新增12专家语义×4事前状态的48项。其中MLP logit和preference各乘四状态的8项在同股五动作间恒定，最多40项直接影响动作减零效用；完整48项仍按原规格训练。主惩罚100，选定交互惩罚1600；将交互设零并复用M0主项时预测退化为M0。有效系数以有限差分证实为动作效用对专家输入的斜率，不能解释成资金百分比。", "",
        "validation/final元层实际加载对应validation/final专家；旧专家文件hash与实验前封口一致。新目录只出现预定元模型及标准化器joblib，没有新专家pt或额外模型工件。", "",
        "新adapter实调用原allocate_joint_scores，toy调用与旧stack名额/预算/资格规则一致；engine_v2及其默认TOP20/95%/10%规则保持原来源。2026输入继续使用原GLW隔离文件，事件feature行删除、price警告仍在。", "",
        f"运行时绑定已查 {runtime['checked']}/12 个正式method目录；保留失败尝试目录未计为完成回放。", "",
        "未发现实现与冻结合同差异。证据范围为保存工件、源代码、重新加载及公式核对，不能将其称为补造的历史系统级调用日志。"]
    (OUT/"META_CONTRACT_AUDIT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"meta_fit_calls":8,"selected_multiplier":16,"runtime_checked":runtime["checked"],
        "old_expert_hashes_checked":len(expert_hashes),"contract_differences":[],"audit_fit_attempts":0}),flush=True)


if __name__=="__main__":
    try:
        main()
    except Exception as error:
        OUT.mkdir(exist_ok=True)
        write(OUT/"META_CONTRACT_AUDIT_FAILURE.json",dict(status="FAIL",error=repr(error),
            no_core_artifacts_modified=True,no_2026_return_data_read=True))
        raise
