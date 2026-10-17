"""R4 Stage A orchestration over canonical native helpers and durable ledger.

Metadata support precedes numeric projections. No IO occurs on import.
The common WHOLE_MATRIX_FREEZE owns activation, source and budget authority.
This adapter owns neither a target producer, registry, account nor estimators.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import warnings
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.joint_input_binding import (
    FEATURES, ACCEPTED_FEATURE_TAGS, guard_parquet)
from scripts.research.a2.training import joint_opportunity_breadth_r4 as breadth
from scripts.research.a2.evaluation import joint_r4_runtime as runtime
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

REPO = Path(__file__).resolve().parents[4]
BOUNDARY = pd.Timestamp("2026-01-01")
SPEC_NAME = "OPPORTUNITY_SPECIFICATION_R2.json"
SUPPORT_NAME = "OPPORTUNITY_SUPPORT_R4_R2.json"
ID = runtime.ID
KEYS = ["signal_date", "ticker"]
CLOCKS = ["signal_date", "execution_date", "label_end_date", "label_mature_date"]
IDENTITY = ["security_id", "security_id_type", "cusip", "active_13f_quarter",
            "quarter_universe_fingerprint"]
PANEL_META = KEYS + IDENTITY + ["moomoo_transport_code", "is_max_group",
    "feature_available", "all_features_finite", "feature_source",
    "feature_coordinate", "feature_pit_status"]
LABEL_META = ["execution_date", "label_end_date", "label_mature_date",
    "endpoint_pair_available", "label_available", "label_coordinate",
    "label_unsupported_common_event"]
NUMERIC = set(FEATURES) | {"y_open5", "label_quantity_multiplier"}
OLD_BINDING_SHA = "a9ff56bd5feb2b90fb836fde3258102a4893a8abdecbb780a9864961867e0fc2"
OLD_PARAMETERS_SHA = "5bde1a5474ee183bb02785b27cf1807fbd630625e3a8850b65c6a0275287f368"
OLD_LEDGER_SHA = "7f4731990033fb35f8d304b79ab540eff74564419c81a2b9c3a83667aa6aa179"
# Safe, immutable metadata projection; never whole-decode the mixed old ledger.
OLD_REFS = {
  2021: (0,1,36445,"55739a419297d45d92264e11e90b26208f8a2dd1809e12eb1f1e46e419f2028d",
    "d4af93db10b2b73d1b38f3008648836dc3b0a77bdeb92441dc5eadfc09129e5a",
    "48df6c828da4b741bb6b982538ed9a872bfdd1853cd5b025cc926a4627c8ab30"),
  2022: (2,4,114190,"588f28daa88c65cdd8aebd05ed30f242464879dbb477d0ef9118dd4489449940",
    "c38c9dab9bb04a54b4cfdae089f8aa280e8dcc54f9a339b42036c3b83d69fa73",
    "7da953dc1dfe891af31f2372d88604da2033bfda876703b2a8c8d42c1c6322b0"),
  2023: (6,8,207645,"c47e406e2bdb2125dff77b5c15d595159a2de46f544e6f1a634ca5cfa21fa748",
    "16d0870189073d6b8a68f684cc4629e5372e5185e8e2dc6a3b19963ad521a45f",
    "dc2480dce313ebeb0ac6ecb3af7f1656b6cdb4716788adf1b137df6355283229"),
  2024: (10,12,301556,"0d22f03d0846d6b368fdd2e852e11badf9cb5ea67382c7488aeadd66d0194b27",
    "35e159fae13012f40e509465f69b4fdaf4feb2ace93aa5408c5fb0e0bb160d53",
    "9667d0882864faa778a05d0b45fe03e0d6301dad5a9394389a97fb614688b474"),
  2025: (14,16,402740,"156d71166f64fc19b230b74ce5ec67eef998c7d73d9e9a2e39ed59a20c935c20",
    "5789236c8187e94418cac306572ff61d94afbb9053edff1981536d006f86ca62",
    "eb091ad5e25696466e4c3ca4b7c0e2aa391c069cf8cfc5927e8ac2f21bdbf97f")}
class OpportunityBlocked(ValueError):
    """Typed dependency/source/engineering failure, not a scientific fit retry."""


def _safe_path(path):
    path = Path(path).resolve()
    if path.drive.upper() in ("E:", "F:"):
        raise OpportunityBlocked("EF_SOURCE_FORBIDDEN")
    return path


def source_binding(run):
    """Resolve only the established original B chain, without disk searching."""
    run = _safe_path(run)
    roots = resolve(REPO)
    if not run.is_relative_to(roots.backtest_root.resolve()):
        raise OpportunityBlocked("CANONICAL_BACKTEST_RUN_REQUIRED")
    state = runtime.read_json(run / "EXECUTION_STATE.json")
    parent = _safe_path(state["parent_run"])
    if not parent.is_relative_to(roots.backtest_root.resolve()):
        raise OpportunityBlocked("PARENT_RUN_OUTSIDE_CANONICAL_ROOT")
    original = roots.results_root / "JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1" / "V24"
    path = original / "INPUT_BINDING.json"
    runtime._pin(path, OLD_BINDING_SHA, "original_B_binding")
    runtime._pin(original/"RUN_CONFIG.json",OLD_PARAMETERS_SHA,"original_B_target_config")
    binding = runtime.read_json(path)
    if binding.get("target") != breadth.TARGET or not binding.get("extended_five_day_labels"):
        raise OpportunityBlocked("EXISTING_B5D_EXTENDED_TARGET_REQUIRED")
    pins = dict(panel=binding["sources"]["accepted_five_day_panel"],
        label=binding["extended_five_day_labels"], raw_keys=binding["sources"]["raw_prices"],
        held=binding["sources"]["accepted_features"])
    if binding.get("own_held_feature_extension"):
        pins["held_extension"] = binding["own_held_feature_extension"]
    return binding, pins, dict(path=str(path), sha256=OLD_BINDING_SHA), original


class FoldReader:
    """Physical guards, metadata selection, then predicate/column numeric reads.

    Reuses joint_input_binding guard and the R3 ProjectedReader predicate pattern.
    Never reads full feature/target tables before a fold restriction.
    """
    def __init__(self, pins, *, numeric=False):
        self.pins, self.numeric, self.datasets, self.audit, self.footers = pins, numeric, {}, [], {}
        for name, pin in pins.items():
            path = _safe_path(pin["path"])
            fields = CLOCKS if name in ("panel", "label") else (
                ["trade_date"] if name == "raw_keys" else ["signal_date"])
            _, footer = guard_parquet(path, pin["sha256"], fields)
            self.datasets[name] = ds.dataset(path, format="parquet")
            self.footers[name] = footer

    def read(self, name, columns, *, start=None, stop="2026-01-01", mature_before=None):
        columns = list(columns)
        if not self.numeric and NUMERIC.intersection(columns):
            raise OpportunityBlocked("METADATA_ONLY_SUPPORT_REQUIRED")
        stop = pd.Timestamp(stop)
        if stop > BOUNDARY:
            raise OpportunityBlocked("PRE2026_PROJECTION_REQUIRED")
        dataset = self.datasets[name]
        field = "trade_date" if name == "raw_keys" else "signal_date"
        scalar = lambda f, d: pa.scalar(pd.Timestamp(d).to_pydatetime(),
                                      type=dataset.schema.field(f).type)
        predicate = ds.field(field) < scalar(field, stop)
        if start is not None:
            predicate &= ds.field(field) >= scalar(field, start)
        if mature_before is not None:
            if pd.Timestamp(mature_before) > BOUNDARY:
                raise OpportunityBlocked("PRE2026_MATURITY_REQUIRED")
            for c in ("execution_date", "label_end_date", "label_mature_date"):
                predicate &= ds.field(c) < scalar(c, mature_before)
        frame = dataset.to_table(columns=columns, filter=predicate).to_pandas()
        if field == "trade_date":
            frame = frame.rename(columns={field: "signal_date"})
        for c in CLOCKS:
            if c in frame:
                frame[c] = pd.to_datetime(frame[c])
        self.audit.append(dict(source=name, columns=columns, start=str(start),
            stop=str(stop), mature_before=str(mature_before), rows=len(frame)))
        return frame

    def metadata(self, *, stop="2026-01-01", start=None):
        panel = self.read("panel", PANEL_META, start=start, stop=stop)
        labels = self.read("label", KEYS + LABEL_META, start=start, stop=stop)
        if panel.duplicated(KEYS).any() or labels.duplicated(KEYS).any():
            raise OpportunityBlocked("DUPLICATE_SOURCE_KEY")
        panel = panel.merge(labels, on=KEYS, how="left", validate="one_to_one", sort=False)
        raw = self.read("raw_keys", ["ticker", "trade_date"], start=start, stop=stop)
        raw = raw.drop_duplicates(KEYS)
        raw["signal_raw_key_present"] = True
        panel = panel.merge(raw, on=KEYS, how="left", validate="one_to_one", sort=False)
        panel["trade_eligible"] = (panel.is_max_group.eq(True)
            & panel.feature_available.eq(True) & panel.all_features_finite.eq(True)
            & panel.feature_source.isin(ACCEPTED_FEATURE_TAGS)
            & panel.signal_raw_key_present.eq(True))
        panel["fit_eligible"] = (panel.trade_eligible & panel.label_available.eq(True)
            & panel.label_unsupported_common_event.eq(False)
            & panel.label_end_date.lt(BOUNDARY) & panel.label_mature_date.lt(BOUNDARY)
            & panel.execution_date.gt(panel.signal_date)
            & panel.label_end_date.gt(panel.execution_date))
        return panel

    def held_metadata(self, *, start=None, stop="2026-01-01"):
        held = self.read("held", KEYS + ["lookback_121_eligible", "all_features_available"],
                         start=start, stop=stop)
        held = held.loc[held.lookback_121_eligible.eq(True)
                        & held.all_features_available.eq(True), KEYS].copy()
        if "held_extension" in self.pins:
            extra = self.read("held_extension", KEYS + ["feature_source"], start=start, stop=stop)
            held = pd.concat([held, extra[KEYS]], ignore_index=True)
        if held.duplicated(KEYS).any():
            raise OpportunityBlocked("DUPLICATE_HELD_FEATURE_AUTHORITY")
        return held.sort_values(KEYS, kind="stable").reset_index(drop=True)

    def training(self, cutoff):
        if not self.numeric:
            raise OpportunityBlocked("FULL_FREEZE_REQUIRED_FOR_NUMERIC")
        meta = self.metadata(stop=cutoff)
        meta = meta.loc[breadth.training_mask(meta, cutoff)].copy()
        x = self.read("panel", KEYS + FEATURES, stop=cutoff)
        y = self.read("label", KEYS + ["y_open5"], stop=cutoff, mature_before=cutoff)
        frame = meta.merge(x, on=KEYS, how="left", validate="one_to_one", sort=False)
        frame = frame.merge(y, on=KEYS, how="left", validate="one_to_one", sort=False)
        if frame.empty or not np.isfinite(frame[FEATURES + ["y_open5"]].to_numpy(float)).all():
            raise OpportunityBlocked("WHOLE_FOLD_NUMERIC_SUPPORT_FAILURE_NO_ROW_FILTER")
        return frame

    def inner_validation(self, cohort):
        rule = next(x for x in breadth.INNER if x["id"] == cohort)
        meta = self.metadata(start=rule["validation_start"], stop=rule["validation_end"])
        meta = meta.loc[breadth.validation_mask(meta, cohort)].copy()
        x = self.read("panel", KEYS + FEATURES, start=rule["validation_start"],
                      stop=rule["validation_end"])
        y = self.read("label", KEYS + ["y_open5"], start=rule["validation_start"],
                      stop=rule["validation_end"], mature_before=rule["validation_end"])
        frame = meta.merge(x, on=KEYS, how="left", validate="one_to_one", sort=False)
        frame = frame.merge(y, on=KEYS, how="left", validate="one_to_one", sort=False)
        if frame.empty or not np.isfinite(frame[FEATURES + ["y_open5"]].to_numpy(float)).all():
            raise OpportunityBlocked("INNER_NUMERIC_SUPPORT_FAILURE_NO_ROW_FILTER")
        return frame

    def annual_prediction(self, year, columns=FEATURES):
        if year not in breadth.ANNUAL or not self.numeric:
            raise OpportunityBlocked("FROZEN_ANNUAL_INFERENCE_REQUIRED")
        columns=list(columns)
        if not columns or not set(columns).issubset(FEATURES):
            raise OpportunityBlocked("EXISTING_CONTEXT_FEATURES_ONLY")
        start, stop = f"{year}-01-01", f"{year+1}-01-01"
        keys = self.held_metadata(start=start, stop=stop)
        held = self.read("held", KEYS + columns, start=start, stop=stop)
        if "held_extension" in self.pins:
            extra = self.read("held_extension", KEYS + columns, start=start, stop=stop)
            held = pd.concat([held, extra], ignore_index=True)
        # Original accepted held rows may contain ineligible rows; keep the fixed metadata keys.
        frame = keys.merge(held, on=KEYS, how="left", validate="one_to_one", sort=False)
        meta = self.metadata(start=start, stop=stop)
        frame = frame.merge(meta.drop(columns=["feature_available", "all_features_finite"],
                            errors="ignore"), on=KEYS, how="left", validate="one_to_one", sort=False)
        frame["identity_qualified"] = frame.security_id.notna()
        if frame.empty or not np.isfinite(frame[columns].to_numpy(float)).all():
            raise OpportunityBlocked("ANNUAL_FEATURE_SUPPORT_FAILURE_NO_ROW_FILTER")
        return frame

    def read_earlier_truth(self, cutoff, signal_years, context_cols=()):
        """Stage B hydrate only earlier mature truth; preserves original identity."""
        if not self.numeric or pd.Timestamp(cutoff)>BOUNDARY:
            raise OpportunityBlocked("FROZEN_EARLIER_TRUTH_REQUIRED")
        years=sorted(set(signal_years));columns=list(context_cols)
        if not years or any(y not in breadth.ANNUAL or y>=pd.Timestamp(cutoff).year for y in years):
            raise OpportunityBlocked("EARLIER_GENUINE_OOF_YEARS_ONLY")
        if not set(columns).issubset(FEATURES):
            raise OpportunityBlocked("EXISTING_CONTEXT_FEATURES_ONLY")
        pieces=[]
        for year in years:
            start,stop=f"{year}-01-01",f"{year+1}-01-01"
            meta=self.metadata(start=start,stop=stop)
            meta=meta.loc[breadth.training_mask(meta,cutoff)].copy()
            label=self.read("label",KEYS+["y_open5"],start=start,stop=stop,mature_before=cutoff)
            frame=meta.merge(label,on=KEYS,how="left",validate="one_to_one",sort=False)
            if columns:
                features=self.read("panel",KEYS+columns,start=start,stop=stop)
                frame=frame.merge(features,on=KEYS,how="left",validate="one_to_one",sort=False)
            if not np.isfinite(frame[["y_open5",*columns]].to_numpy(float)).all():
                raise OpportunityBlocked("EARLIER_TRUTH_NUMERIC_SUPPORT_FAILURE_NO_ROW_FILTER")
            pieces.append(frame)
        return pd.concat(pieces,ignore_index=True)

    def prediction_features(self, year, columns):
        return self.annual_prediction(year,columns=columns)


def frame_digest(frame):
    fields = ["signal_date", "ticker", "label_end_date", "label_mature_date",
              "y_open5", *FEATURES]
    return hashlib.sha256(pd.util.hash_pandas_object(
        frame[fields], index=False).values.tobytes()).hexdigest()


def metadata_digest(frame):
    columns = [c for c in KEYS + IDENTITY + CLOCKS[1:] + [
        "trade_eligible", "fit_eligible"] if c in frame]
    return hashlib.sha256(pd.util.hash_pandas_object(
        frame[columns], index=False).values.tobytes()).hexdigest()


def code_pins():
    import scripts.research.a2.data.joint_input_binding as binding_owner
    paths = [Path(__file__), Path(breadth.__file__), Path(runtime.__file__),
        Path(binding_owner.__file__), Path(breadth.values.__file__), breadth.values.NATIVE,
        REPO/"scripts/research/a2/evaluation/joint_frozen_history_risk_r3.py",
        REPO/"scripts/research/a2/evaluation/joint_method_stages.py",
        REPO/"scripts/research/a2/risk/shared_risk_budget_r2.py",
        REPO/"scripts/common/storage_paths.py"]
    return [dict(path=str(p.resolve()), sha256=runtime.sha(p)) for p in paths]


def specification(run):
    binding, pins, bind_ref, original = source_binding(run)
    return dict(schema="B_R4_OPPORTUNITY_EXECUTION_SPEC_V1", research_id=ID,
        native=breadth.specs(), slots=breadth.slot_matrix(), source_binding=bind_ref,
        sources={n: dict(path=str(_safe_path(v["path"])), sha256=v["sha256"])
                 for n,v in pins.items()}, code_pins=code_pins(),
        original_root=str(original), old_ledger_sha256=OLD_LEDGER_SHA,
        potential_exact_reuse={str(y): list(ref) for y,ref in OLD_REFS.items()},
        exact_reuse_policy="MEDIUM_ONLY_ALL_FRAME_TARGET_WEIGHT_CONFIG_SOURCE_VERSION_PROVEN",
        runtime_reuse_authority="FROZEN_LEGAL_COHORT_SERIALIZATION_VERSION_WARNING_OR_EXISTING_RECEIPT",
        annual_output="RAW_NATIVE_ONLY_NO_ANNUAL_TARGET_READ",
        selected_inner_predictions_are_OOF=False, annual_genuine_OOF=[2022,2023,2024,2025],
        scientific_retry=0, strict_PIT_promotion_eligible=False, test2026_rows_read=0)


def prepare(run):
    """Zero-fit support discovery using only declared metadata columns."""
    spec = specification(run)
    _, pins, _, _ = source_binding(run)
    reader = FoldReader(pins)
    nodes = []
    for cohort, cutoff, phase in [(x["id"],x["cutoff"],"INNER") for x in breadth.INNER] + [
            (f"ANNUAL_{y}",f"{y}-01-01","ANNUAL") for y in breadth.ANNUAL]:
        meta = reader.metadata(stop=cutoff)
        train = meta.loc[breadth.training_mask(meta,cutoff)]
        if phase == "INNER":
            rule = next(x for x in breadth.INNER if x["id"]==cohort)
            valid_meta = reader.metadata(start=rule["validation_start"],stop=rule["validation_end"])
            valid = valid_meta.loc[breadth.validation_mask(valid_meta,cohort)]
        else:
            year = int(cohort[-4:])
            valid = reader.held_metadata(start=f"{year}-01-01",stop=f"{year+1}-01-01")
        nodes.append(dict(cohort=cohort, cutoff=cutoff, train_rows=len(train),
            train_metadata_sha256=metadata_digest(train), prediction_rows=len(valid),
            prediction_key_sha256=metadata_digest(valid),
            max_train_maturity=str(train.label_mature_date.max()),
            status="METADATA_SUPPORTED_NUMERIC_FINITE_GATE_PENDING" if len(train) and len(valid)
                   else "BLOCKED_SOURCE_EMPTY_SUPPORT"))
    support = dict(schema="B_R4_OPPORTUNITY_SUPPORT_V1", research_id=ID,
        source_binding=spec["source_binding"], physical_footers=reader.footers,
        nodes=nodes, metadata_projection_audit=reader.audit,
        native_numeric_read=0, new_fit=0, outcome_read=0, test2026_rows_read=0,
        selection_by_performance=False, support_never_shrunk_on_outcomes=True)
    runtime.write(Path(run), SPEC_NAME, spec, immutable=True)
    runtime.write(Path(run), SUPPORT_NAME, support, immutable=True)
    return spec, support


def activated(run, expected_matrix_sha=None):
    matrix = runtime.guard(run, expected_matrix_sha)
    refs = {str(Path(p["path"]).resolve()):p["sha256"]
            for p in matrix.get("pinned_artifacts",())}
    for name in (SPEC_NAME,SUPPORT_NAME):
        path = Path(run)/name
        if refs.get(str(path.resolve())) != runtime.sha(path):
            raise OpportunityBlocked("OPPORTUNITY_SPEC_SUPPORT_NOT_IN_WHOLE_MATRIX")
    spec = runtime.read_json(Path(run)/SPEC_NAME)
    if spec != specification(run):
        raise OpportunityBlocked("OPPORTUNITY_FROZEN_SPEC_CHANGED")
    return matrix, spec


def _event_callback(ledger, identity, events):
    """One learned view per event; joint views share one physical optimizer call."""
    def callback(component):
        states = component.get("learned_states", ["weighted_scaler"])
        call_id = content_hash(dict(identity=identity, component=component))
        for state in states:
            event = dict(key=content_hash(dict(call_id=call_id,state=state)),
                kind="scaler" if component["component"]=="SHARED_SCALER" else "model_fit",
                name=state, context=identity, inputs_sha256=identity["train_values_sha256"],
                parameters=dict(component=component, physical_optimizer_call_id=call_id))
            ledger.reserve(event)  # fsync checkpoint before any backend fit.
            events.append(dict(event,status="STARTED"))
    return callback


def exact_reuse(run, spec, frame, cohort, name, capacity, seed):
    """No old ledger/model deserialization until all frozen evidence matches."""
    if name not in ("ridge","hgb") or capacity!="MEDIUM" or seed!=breadth.SEEDS[0]:
        return None, "NOT_AN_EXACT_REUSE_SLOT"
    cutoff = next((x["cutoff"] for x in breadth.INNER if x["id"]==cohort), None)
    if cutoff is None:
        cutoff = cohort.replace("ANNUAL_","")+"-01-01"
    if not cutoff.endswith("-01-01"):
        return None, "NO_EXISTING_SEMIANNUAL_MODEL"
    year = int(cutoff[:4])
    if year not in OLD_REFS:
        return None, "NO_EXISTING_ANNUAL_MODEL"
    ref = OLD_REFS[year]
    if len(frame)!=ref[2] or frame_digest(frame)!=ref[3]:
        return None, "NON_EQUIVALENT_TRAINING_FRAME"
    cap_name = "Ridge" if name=="ridge" else "HGB"
    path = Path(spec["original_root"])/f"models/five_day_{cap_name}_{year}.joblib"
    expected = ref[4 if name=="ridge" else 5]
    runtime._pin(Path(spec["original_root"])/"work/FIT_STATUS.json",OLD_LEDGER_SHA,"original_B_exact_record_ledger")
    runtime._pin(path,expected,"exact_legacy_native_model")
    # Legal current cohort only, after frame/source/config equivalence and activation.
    # sklearn's documented serialized _sklearn_version check is not effect-based inference.
    from sklearn.exceptions import InconsistentVersionWarning
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always",InconsistentVersionWarning)
        obj = joblib.load(path)
    if any(isinstance(w.message,InconsistentVersionWarning) for w in caught):
        return None, "NON_EQUIVALENT_SERIALIZED_SKLEARN_VERSION"
    model,scaler = obj["model"],obj["scaler"]
    expected_config=breadth.capacity_config(name,"MEDIUM")
    if name=="hgb":expected_config=dict(expected_config,random_state=seed)
    if any(model.get_params(deep=False).get(k)!=v for k,v in expected_config.items()):
        return None, "NON_EQUIVALENT_NATIVE_PARAMETERS"
    if name=="ridge" and scaler is None:
        return None, "MISSING_EXACT_WEIGHTED_SCALER"
    return breadth.NativeFit(name,capacity,seed,(model,),scaler,
        dict(exact_reuse=True, source_artifact=str(path), source_sha256=expected,
             runtime_version_evidence="LEGAL_COHORT_SKLEARN_SERIALIZED_VERSION_CHECK_NO_MISMATCH",
             runtime_version=breadth.RUNTIME_VERSIONS["sklearn"])), "EXACT_REUSE"


def _artifact(run, relative, obj):
    path = Path(run)/relative
    assert_safe_output_path(path,kind="backtest",paths=resolve(REPO))
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        raise OpportunityBlocked("UNREGISTERED_ARTIFACT_PRESERVED")
    joblib.dump(obj,path,compress=3)
    return dict(path=str(path),sha256=runtime.sha(path))


def _output(run, name, cohort, frame, fields, receipt):
    relative = ("OOF/" if cohort.startswith("ANNUAL_") else "inner/") + (
        f"OPPORTUNITY_{name}_{cohort[-4:]}.parquet" if cohort.startswith("ANNUAL_")
        else f"OPPORTUNITY_{name}_{cohort}_{receipt['capacity']}.parquet")
    path=Path(run)/relative
    assert_safe_output_path(path,kind="backtest",paths=resolve(REPO))
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        raise OpportunityBlocked("UNREGISTERED_PREDICTION_ARTIFACT_PRESERVED")
    columns = [c for c in KEYS+IDENTITY+CLOCKS[1:]+[
        "trade_eligible","fit_eligible","label_available","identity_qualified"] if c in frame]
    out=frame[columns].copy()
    for field,array in fields.items():out[field]=array
    out["source_fit_cutoff"]=pd.Timestamp(receipt["source_fit_cutoff"])
    out["source_label_mature_max"]=pd.Timestamp(receipt["source_label_mature_max"])
    out["model"]=name;out["capacity"]=receipt["capacity"]
    out["fold_year"]=int(cohort[-4:]) if cohort.startswith("ANNUAL_") else 2021
    out.to_parquet(path,index=False)
    receipt.update(artifact=dict(path=str(path),sha256=runtime.sha(path)),rows=len(out),
                   columns=list(out.columns))
    receipt_path=(f"receipts/OPPORTUNITY_{name}_{cohort[-4:]}.json"
                  if cohort.startswith("ANNUAL_")
                  else f"receipts/OPPORTUNITY_{name}_{cohort}_{receipt['capacity']}.json")
    runtime.write(Path(run),receipt_path,receipt,immutable=True)
    return receipt


def _group(run, ledger, spec, train, prediction, name, cohort, cutoff, capacity,
           matrix_sha, scaler, native):
    group_key=content_hash(dict(cohort=cohort,model=name,capacity=capacity))
    existing=next((r for r in ledger.status["records"] if r.get("key")==group_key),None)
    if existing:
        if existing["status"]=="COMPLETE":
            runtime._pin(existing["receipt_ref"]["path"],existing["receipt_ref"]["sha256"],"group_receipt")
            receipt=runtime.read_json(existing["receipt_ref"]["path"])
            runtime._pin(receipt["artifact"]["path"],receipt["artifact"]["sha256"],"group_prediction")
            for ref in receipt["model_artifacts"]:
                runtime._pin(ref["path"],ref["sha256"],"group_model")
            return receipt
        return dict(status="FAILED_PRESERVED",model=name,cohort=cohort,capacity=capacity)
    group=dict(key=group_key,status="STARTED",model=name,cohort=cohort,capacity=capacity,
               artifact_refs=[],seed_results=[],learned_states=0)
    ledger.status["records"].append(group);ledger.checkpoint()
    x,y=train[FEATURES].to_numpy(float),train.y_open5.to_numpy(float)
    weight=breadth.date_weights(train.signal_date)
    train_sha=frame_digest(train)
    fields_by_seed={}; events=[]; failure=False
    for seed in breadth.seeds(name,len(train)):
        identity=dict(cohort=cohort,cutoff=cutoff,model=name,capacity=capacity,seed=seed,
                      train_values_sha256=train_sha,source_binding_sha256=OLD_BINDING_SHA)
        try:
            fit,reuse_status=exact_reuse(run,spec,train,cohort,name,capacity,seed)
            if fit is None:
                fit=breadth.fit_model(name,capacity,seed,x,y,weight,
                    scaler=scaler if name in breadth.values.SCALED else None,
                    on_fit_started=_event_callback(ledger,identity,events),native=native)
                relative=f"models/opportunity/{cohort}/{name}_{capacity}_{seed}.joblib"
                artifact=_artifact(run,relative,fit)
            else:
                artifact=dict(path=fit.metadata["source_artifact"],sha256=fit.metadata["source_sha256"])
            fields_by_seed[seed]=fit.predict(prediction[FEATURES].to_numpy(float))
            group["artifact_refs"].append(artifact)
            group["seed_results"].append(dict(seed=seed,status="COMPLETE",reuse_status=reuse_status))
        except Exception as exc:
            failure=True
            group["seed_results"].append(dict(seed=seed,status="FAILURE",failure_type=type(exc).__name__,
                failure_code=str(exc)[:200]))
        # All fixed seeds still attempted. Nothing gets refunded or repeated.
        for event in events:
            if event["status"]=="STARTED":
                event["status"]="FAILED" if failure and seed not in fields_by_seed else "SUCCEEDED"
        ledger.sync(events);ledger.checkpoint()
        gc.collect()
    group["learned_states"]=sum(e["kind"] in ("model_fit","scaler") for e in events)
    if failure:
        group["status"]="FAILURE";ledger.checkpoint()
        return dict(status="FAILURE",model=name,cohort=cohort,capacity=capacity)
    try:
        fields=breadth.aggregate(name,fields_by_seed,training_rows=len(train))
        receipt=dict(schema="B_R4_RAW_NATIVE_OPPORTUNITY_OOF_V1",status="COMPLETE",
            model=name,cohort=cohort,capacity=capacity,seed_aggregation="ALL_FIXED_SEEDS_EQUAL",
            seeds=list(breadth.seeds(name,len(train))),source_fit_cutoff=cutoff,
            source_label_mature_max=str(train.label_mature_date.max()),
            train_values_sha256=train_sha,train_rows=len(train),
            feature_order=list(FEATURES),target=breadth.TARGET,target_clipped=False,
            target_cash_complete=False,raw_native_only=True,source_binding_sha256=OLD_BINDING_SHA,
            whole_matrix_freeze_sha256=matrix_sha,producer_sha256=runtime.sha(__file__),
            specification_sha256=runtime.sha(Path(run)/SPEC_NAME),
            support_sha256=runtime.sha(Path(run)/SUPPORT_NAME),
            selected_capacity_rule_sha256=runtime.sha(Path(run)/"SELECTED_CAPACITY_R4.json")
                if cohort.startswith("ANNUAL_") else None,
            model_artifacts=group["artifact_refs"],new_learned_units=group["learned_states"],
            genuine_selected_recipe_OOF=cohort.startswith("ANNUAL_"),
            strict_PIT_promotion_eligible=False,test2026_rows_read=0)
        if not cohort.startswith("ANNUAL_"):
            receipt["loss"]=breadth.validation_loss(name,prediction.y_open5.to_numpy(float),
                                                    fields,prediction.signal_date)
        receipt=_output(run,name,cohort,prediction,fields,receipt)
        receipt_name=(f"OPPORTUNITY_{name}_{cohort[-4:]}.json" if cohort.startswith("ANNUAL_")
                      else f"OPPORTUNITY_{name}_{cohort}_{capacity}.json")
        group.update(status="COMPLETE",receipt_ref=dict(
            path=str(Path(run)/"receipts"/receipt_name),
            sha256=runtime.sha(Path(run)/"receipts"/receipt_name)))
    except Exception as exc:
        group.update(status="FAILURE",failure_type=type(exc).__name__,failure_code=str(exc)[:200])
        receipt=dict(status="FAILURE",model=name,cohort=cohort,capacity=capacity)
    ledger.checkpoint()
    return receipt


def run_training(run, *, phase="all", expected_matrix_sha=None):
    """Activated worker; preserve failures, continue independent frozen families."""
    if phase not in ("inner","annual","all"):
        raise OpportunityBlocked("UNKNOWN_PHASE")
    run=Path(run); matrix,spec=activated(run,expected_matrix_sha)
    matrix_sha=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json")
    _,pins,_,_=source_binding(run)
    (run/"work").mkdir(parents=True,exist_ok=True)
    with runtime.stage_writer(run,"opportunity"):
        ledger=runtime.StageLedger(run,"opportunity",expected_matrix_sha=matrix_sha)
        reader=FoldReader(pins,numeric=True)
        native=breadth.bind_native()
        cohorts=list(breadth.INNER) if phase in ("inner","all") else []
        selected=None
        if phase=="annual":
            selected=runtime.read_json(run/"SELECTED_CAPACITY_R4.json")
            if selected["whole_matrix_freeze_sha256"]!=matrix_sha:
                raise OpportunityBlocked("SELECTED_CAPACITY_FREEZE_CHANGED")
        for rule in cohorts + [dict(id="ANNUAL_"+str(y),cutoff=f"{y}-01-01")
                               for y in breadth.ANNUAL if phase in ("annual","all")]:
            cohort,cutoff=rule["id"],rule["cutoff"]
            if cohort.startswith("ANNUAL_") and selected is None:
                selected=freeze_selected_capacities(run,ledger,matrix_sha)
            try:
                train=reader.training(cutoff)
                prediction=(reader.inner_validation(cohort) if cohort.startswith("INNER_")
                            else reader.annual_prediction(int(cohort[-4:])))
            except Exception as exc:
                ledger.status["records"].append(dict(key="source:"+cohort,cohort=cohort,
                    status="BLOCKED_SOURCE",failure_type=type(exc).__name__,failure_code=str(exc)[:200]))
                ledger.checkpoint();continue
            scaler_key="scaler:"+cohort
            scaler_record=next((r for r in ledger.status["records"] if r.get("key")==scaler_key),None)
            scaler=None
            try:
                if scaler_record:
                    if scaler_record["status"]!="COMPLETE":
                        raise OpportunityBlocked("FAILED_SCALER_PRESERVED_NO_RETRY")
                    runtime._pin(scaler_record["artifact"]["path"],scaler_record["artifact"]["sha256"],"scaler")
                    saved=joblib.load(scaler_record["artifact"]["path"])
                    scaler=saved["scaler"] if scaler_record["artifact"].get("component")=="scaler_in_original_bundle" else saved
                else:
                    events=[]
                    identity=dict(cohort=cohort,cutoff=cutoff,train_values_sha256=frame_digest(train))
                    old_fit,reuse_status=exact_reuse(run,spec,train,cohort,"ridge","MEDIUM",breadth.SEEDS[0])
                    if old_fit is not None:
                        scaler=old_fit.scaler
                        artifact=dict(path=old_fit.metadata["source_artifact"],
                            sha256=old_fit.metadata["source_sha256"],component="scaler_in_original_bundle")
                    else:
                        scaler=breadth.fit_scaler(train[FEATURES].to_numpy(float),
                            breadth.date_weights(train.signal_date),
                            on_fit_started=_event_callback(ledger,identity,events))
                        artifact=_artifact(run,f"models/opportunity/{cohort}/shared_scaler.joblib",scaler)
                    ledger.status["records"].append(dict(key=scaler_key,status="COMPLETE",
                        artifact=artifact,reuse_status=reuse_status))
                    for e in events:e["status"]="SUCCEEDED"
                    ledger.sync(events)
            except Exception as exc:
                if not scaler_record:
                    ledger.status["records"].append(dict(key=scaler_key,status="FAILURE",
                        failure_type=type(exc).__name__,failure_code=str(exc)[:200]))
                    if 'events' in locals():
                        for e in events:e["status"]="FAILED"
                        ledger.sync(events)
                ledger.checkpoint()
            for name in breadth.applicable_models():
                tiers=(breadth.CAPACITIES if cohort.startswith("INNER_") else
                       (selected["capacities"].get(name),))
                for capacity in tiers:
                    if capacity is None or (name in breadth.values.SCALED and scaler is None):
                        ledger.status["records"].append(dict(key=content_hash(dict(
                            cohort=cohort,model=name,capacity=capacity)),
                            status="BLOCKED_DEPENDENCY",model=name,cohort=cohort,capacity=capacity))
                        ledger.checkpoint();continue
                    _group(run,ledger,spec,train,prediction,name,cohort,cutoff,capacity,
                           matrix_sha,scaler,native)
            del train,prediction;gc.collect()
        if phase in ("inner","all"):
            selected=freeze_selected_capacities(run,ledger,matrix_sha)
        ledger.status["status"]="STAGE_A_COMPLETE_WITH_RETAINED_FAILURES"
        ledger.checkpoint()
        runtime.write(run,"OPPORTUNITY_EXECUTION_RECEIPT.json",dict(status=ledger.status["status"],
            stage_new_learned_units=ledger.status["new_fit_units"],stage_upper=864,
            inherited_reserved_reported_once=1876,test2026_rows_read=0,
            whole_matrix_freeze_sha256=matrix_sha,
            physical_fit_events=len({e["parameters"]["physical_optimizer_call_id"]
                                     for e in ledger.status["physical_events"]}),
            source_projection_audit=reader.audit,strict_PIT_promotion_eligible=False))
        return ledger.status


def freeze_selected_capacities(run, ledger, matrix_sha):
    capacities,failures={},{}
    for name in breadth.applicable_models():
        records=[]
        for r in ledger.status["records"]:
            if r.get("model")==name and r.get("cohort") in {x["id"] for x in breadth.INNER}:
                record=dict(model=name,cohort=r["cohort"],capacity=r["capacity"],status=r["status"])
                if r["status"]=="COMPLETE":
                    ref=r["receipt_ref"];runtime._pin(ref["path"],ref["sha256"],"inner_loss_receipt")
                    receipt=runtime.read_json(ref["path"])
                    record["loss"]=receipt["loss"]
                records.append(record)
        try:capacities[name]=breadth.select_capacity(records)
        except Exception as exc:failures[name]=dict(status="BLOCKED_DEPENDENCY",failure_type=type(exc).__name__)
    result=dict(schema="B_R4_SELECTED_CAPACITY_V1",capacities=capacities,blocked_models=failures,
        whole_matrix_freeze_sha256=matrix_sha,selection_scope="2021H1/H2_ONLY",
        equal_seed_ensemble=True,annual_outcomes_read=0,scientific_retry=0)
    runtime.write(Path(run),"SELECTED_CAPACITY_R4.json",result,immutable=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",required=True)
    parser.add_argument("--phase",choices=("prepare","inner","annual","all"),default="prepare")
    parser.add_argument("--expected-matrix-sha")
    args=parser.parse_args()
    if args.phase=="prepare":
        spec,support=prepare(args.run)
        print(json.dumps(dict(status="OPPORTUNITY_METADATA_PREPARED",nodes=len(support["nodes"]),
            matrix_slots=len(spec["slots"]),learned_upper=864,new_fit=0,numeric_read=0)))
    else:
        status=run_training(args.run,phase=args.phase,expected_matrix_sha=args.expected_matrix_sha)
        print(json.dumps(dict(status=status["status"],stage_new_units=status["new_fit_units"],test2026_reads=0)))

if __name__=="__main__":
    main()
