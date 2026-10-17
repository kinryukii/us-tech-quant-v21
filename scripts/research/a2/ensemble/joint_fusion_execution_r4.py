"""R4 Stage B thin runner: fixed native packet, genuine earlier OOF, one ledger.

The native reader, physical cache/budget, writer and source authority remain
their existing owners. No IO on import. Fits require WHOLE_MATRIX_FREEZE.
Predictions have no current-year y projection and retain the original identity.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.ensemble import joint_fusion_breadth_r4 as fusion
from scripts.research.a2.evaluation import joint_r4_runtime as runtime
from scripts.research.a2.evaluation.joint_method_stages import task_writer
from scripts.research.a2.evaluation.joint_native_coverage import _frame_sha
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.training import joint_opportunity_execution_r4 as opportunity
from scripts.research.a2.risk.shared_risk_budget_r2 import (
    StateCache, StateBudget, content_hash, LEARNED_KINDS)

REPO = Path(__file__).resolve().parents[4]
PACKET = ("ridge","hgb","xgb","lgb","extra")
YEARS = (2023,2024,2025)
VALUE_ROLES = ("huber","linear_q")
SCALE_ROLES = ("ngboost","mlp_dist","cat_uncertainty")
SPEC_NAME = "FUSION_SPECIFICATION.json"
SUPPORT_NAME = "FUSION_SUPPORT_R4.json"
KEYS = ["signal_date","ticker"]
IDENTITY = list(fusion.IDENTITY)
NATIVE_ROLE = "GENUINE_ANNUAL_MODEL_OOF"
META_ROLE = "GENUINE_ANNUAL_META_OOF"
FIXED_WEIGHTS = (.30,.25,.20,.15,.10)

class FusionExecutionBlocked(ValueError):
    pass

def _session_clock(value):
    """Existing date-only session coordinates; never an available_at claim."""
    t=pd.Timestamp(value)
    if pd.isna(t):raise FusionExecutionBlocked("VALID_SESSION_COORDINATE_REQUIRED")
    if t.tzinfo is None:
        if t!=t.normalize():raise FusionExecutionBlocked("NAIVE_INTRADAY_CLOCK_FORBIDDEN")
        t=t.tz_localize("UTC")
    t=t.tz_convert("UTC")
    if t>=pd.Timestamp("2026-01-01",tz="UTC"):
        raise FusionExecutionBlocked("PRE2026_SESSION_COORDINATE_REQUIRED")
    return t

def _clocks(frame):
    frame=frame.copy()
    for c in ["signal_date","label_end_date","label_mature_date",
              *[x for x in frame if x.endswith("__source_cutoff") or x.endswith("__source_label_mature_max")]]:
        if c in frame:frame[c]=[_session_clock(v) for v in frame[c]]
    return frame

def code_pins():
    paths=[Path(__file__),Path(fusion.__file__),Path(runtime.__file__),
           Path(opportunity.__file__),Path(opportunity.breadth.__file__),Path(fusion.prior.__file__)]
    # Existing gate/network owner and dependency bootstrap, never a new model copy.
    paths += [fusion.prior._SOURCE, fusion.prior._COOP]
    return [dict(path=str(p.resolve()),sha256=runtime.sha(p)) for p in paths]

def specification():
    return dict(schema="B_R4_FUSION_EXECUTION_SPEC_V1",research_id=runtime.ID,
        fixed_native_packet=list(PACKET),fixed_weighted_weights=list(FIXED_WEIGHTS),
        outer_years=list(YEARS),native_history_start_year=2022,
        methods=list(fusion.METHODS),meta_capacity=deepcopy(fusion.SPEC),
        hgb_phase_seed_rule=dict(row_count_lte=200000,seeds_lte=[20260928],
            seeds_gt=list(fusion.SEEDS),rows_source="QUALIFIED_METADATA_BEFORE_FIT",
            source="sklearn HistGradientBoosting binning default subsample=200000; full features; early_stopping=False"),
        meta_return_calibration=dict(years=[2024,2025],methods=list(fusion.METHODS),
            slots=22,states_per_slot=5,earlier_source="GENUINE_ANNUAL_META_OOF_ONLY",
            year2023="BLOCKED_NO_EARLIER_NEW_META_OOF"),
        native_value_calibration=dict(roles=list(VALUE_ROLES),years=list(YEARS),
            states_per_slot=5,linear_q="ONE_DIMENSIONAL_AFFINE_ON_FIXED_0.3_0.4_0.3_SORTED_QUANTILE_INTEGRAL_PROXY_MU",
            huber="ONE_DIMENSIONAL_AFFINE_ON_NATIVE_ROBUST_LOCATION",
            original_quantiles_changed=False,interval_coverage_claim=False),
        native_scale_proxy=dict(roles=list(SCALE_ROLES),years=list(YEARS),states_per_slot=1,
            estimator="DATE_EQUAL_RMS_OF_GENUINE_EARLIER_NATIVE_OOF_ERROR_DIVIDED_BY_NATIVE_SCALE",
            independent_coverage_validation=False),
        calibration_catalog=dict(return_affine="NEW_FIT_FIXED_ROSTER",
            probability="BLOCKED_B_DERIVED_TARGET_UNBOUND",
            quantile_to_value="NEW_FIT_LINEAR_Q_PROXY_ONLY_OTHER_RAW_QUANTILES_RETAINED",
            quantile_coverage="NOT_APPLICABLE_NO_EXISTING_BOUND_B_ALGORITHM",
            uncertainty_scale="NEW_FIT_FIXED_THREE_DISTRIBUTION_ROLES",
            uncertainty_aware_fusion="NOT_APPLICABLE_NO_INDEPENDENT_BOUND_B_CATALOG",
            residual_correction={"ridge_then_hgb":"EXACT_REUSE_OLD_SCIENTIFIC_TUPLE_ONLY",
                                 "hgb_then_ridge":"EXACT_REUSE_OLD_SCIENTIFIC_TUPLE_ONLY"},
            old_five_member_meta="EXACT_REUSE_OLD_TARGET_MEMBERS_SOURCE_FEATURES_CUTOFF_PARAMETERS_ONLY"),
        budget=fusion.physical_count_recipe(return_calibration_slots=28,scale_proxy_slots=9),
        stage_cap=300,new_global_cap=1800,inherited_B_reservations=1876,
        branch_cumulative_cap=4096,scientific_retry=0,failure_refund=False,
        missing_packet_member="BLOCK_WHOLE_SLOT_NEVER_SHRINK",
        native_base_fits=0,accounts_created=0,workers=1,library_threads=2,
        source_clock_semantics="DATE_ONLY_SESSION_COORDINATE_ASSUMED_UTC_MIDNIGHT_NOT_AVAILABLE_AT",
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        test2026_locked=True,code_pins=code_pins())

def _science(spec):
    copy=deepcopy(spec);copy.pop("code_pins",None)
    return copy

def _pin_map(refs):
    result={}
    for ref in refs:
        path=str(Path(ref["path"]).resolve())
        if path in result or not fusion._sha(ref.get("sha256")):
            raise FusionExecutionBlocked("DUPLICATE_OR_INVALID_DEPENDENCY_PIN")
        result[path]=ref["sha256"]
    return result

def implementation_dependencies(run,matrix,frozen):
    """Only frozen pre-numeric seed correction and wrapper implementation."""
    run=Path(run)
    original=_pin_map(frozen["code_pins"]);current=_pin_map(code_pins())
    self_path=str(Path(__file__).resolve())
    native_path=str(Path(opportunity.__file__).resolve())
    breadth_path=str(Path(opportunity.breadth.__file__).resolve())
    runtime_path=str(Path(runtime.__file__).resolve())
    if set(current)!=set(original)|{breadth_path}:
        raise FusionExecutionBlocked("FUSION_CODE_CLOSURE_MEMBERS_CHANGED")
    changed={p for p in original if original[p]!=current[p]}
    if changed-{self_path,native_path,runtime_path}:
        raise FusionExecutionBlocked("NON_WRAPPER_SCIENTIFIC_SOURCE_CHANGED")
    artifact_pins=_pin_map(matrix.get("pinned_artifacts",()))
    matrix_code=_pin_map(matrix.get("code_pins",()))
    correction_ref=matrix.get("conditional_binning_seed_rule_ref",{})
    correction_path=run/"PRE_NUMERIC_SEED_CORRECTION_R1.json"
    if (str(Path(correction_ref.get("path","")).resolve())!=str(correction_path.resolve())
        or artifact_pins.get(str(correction_path.resolve()))!=correction_ref.get("sha256")):
        raise FusionExecutionBlocked("FROZEN_PRE_NUMERIC_CORRECTION_REQUIRED")
    runtime._pin(correction_path,correction_ref["sha256"],"fusion_seed_correction")
    correction=runtime.read_json(correction_path)
    if (correction.get("schema")!="B_R4_PRE_NUMERIC_SEED_CORRECTION_R1"
        or correction.get("research_id")!=runtime.ID
        or any(correction.get(k)!=0 for k in ("models_added","targets_added","cutoffs_changed",
                     "real_numeric_reads","real_fit_calls","outcome_reads","test2026_rows_read","scientific_retry"))
        or correction.get("data_support_changed") is not False
        or correction.get("source_key_custody_changed") is not False
        or correction.get("stage_caps")!=runtime.CAPS):
        raise FusionExecutionBlocked("PRE_NUMERIC_CORRECTION_SCIENTIFIC_SCOPE_CHANGED")
    deltas={str(Path(x["path"]).resolve()):x for x in correction["code_delta"]}
    for path in (native_path,breadth_path,runtime_path):
        if matrix_code.get(path)!=current[path]:
            raise FusionExecutionBlocked("UPSTREAM_FINAL_SOURCE_NOT_IN_WHOLE_MATRIX")
    for path in (native_path,breadth_path):
        delta=deltas.get(path,{})
        if (delta.get("new_sha256")!=current[path]
            or (path==native_path and delta.get("old_sha256")!=original[path])):
            raise FusionExecutionBlocked("UPSTREAM_SEED_CORRECTION_CODE_CHAIN_CHANGED")
    upstream_refs=[]
    for key,name in (("new_spec_ref",opportunity.SPEC_NAME),("new_support_ref",opportunity.SUPPORT_NAME),
                     ("budget_scope_ref","BUDGET_SCOPE_FREEZE_R1.json")):
        ref=correction.get(key,{})
        if (str(Path(ref.get("path","")).resolve())!=str((run/name).resolve())
            or artifact_pins.get(str((run/name).resolve()))!=ref.get("sha256")):
            raise FusionExecutionBlocked("PRE_NUMERIC_UPSTREAM_ARTIFACT_NOT_PINNED")
        runtime._pin(ref["path"],ref["sha256"],"fusion_upstream")
        upstream_refs.append(deepcopy(ref))
    revisions=[dict(path=p,old_sha256=original[p],new_sha256=current[p],
                    authorization="FROZEN_PRE_NUMERIC_SEED_AND_BUDGET_CORRECTION")
               for p in (native_path,runtime_path) if original[p]!=current[p]]
    revisions.append(dict(path=breadth_path,old_sha256=deltas[breadth_path]["old_sha256"],
        new_sha256=current[breadth_path],authorization="FROZEN_PRE_NUMERIC_SEED_CORRECTION_ADDED_DEPENDENCY"))
    activation_path=run/"OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_R1.json"
    activation_sha=runtime.sha(activation_path)
    state=runtime.read_json(run/"EXECUTION_STATE.json")
    activation_ref=state.get("opportunity_engineering_binding_ref",{})
    if (str(Path(activation_ref.get("path","")).resolve())!=str(activation_path.resolve())
        or activation_ref.get("sha256")!=activation_sha
        or state.get("opportunity_engineering_binding_sha256")!=activation_sha):
        raise FusionExecutionBlocked("ROOT_PINNED_UPSTREAM_ACTIVATION_REQUIRED")
    runtime._pin(activation_path,activation_sha,"fusion_upstream_activation_binding")
    activation=runtime.read_json(activation_path)
    if (activation.get("schema")!="B_R4_OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_V1"
        or activation.get("original_matrix_sha256")!=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json")
        or activation.get("transform")!="JSON_SERIALIZATION_LIST_TUPLE_ONLY"
        or any(activation.get(k) is not True for k in ("no_scientific_change",
            "no_original_frozen_bytes_changed","process_local_only","original_guard_and_runner_unchanged",
            "list_tuple_only","values_number_types_sequence_and_source_changes_rejected",
            "scientific_slots_unchanged","budget_unchanged","input_sources_unchanged"))
        or any(activation.get(k)!=0 for k in ("opportunity_real_numeric_reads_before_activation",
            "opportunity_real_fit_calls_before_activation","test2026_rows_read"))):
        raise FusionExecutionBlocked("UPSTREAM_ACTIVATION_SCOPE_CHANGED")
    activation_pins=_pin_map(activation.get("pinned_artifacts",()))
    wrapper_path=str((REPO/"scripts/research/a2/training/joint_opportunity_activation_r4_r1.py").resolve())
    wrapper_test=str((REPO/"tests/research/a2/training/test_joint_opportunity_activation_r4_r1.py").resolve())
    expected={native_path:current[native_path],breadth_path:current[breadth_path],
        str((run/"WHOLE_MATRIX_FREEZE.json").resolve()):runtime.sha(run/"WHOLE_MATRIX_FREEZE.json"),
        str(correction_path.resolve()):correction_ref["sha256"]}
    expected.update({str(Path(r["path"]).resolve()):r["sha256"] for r in upstream_refs[:2]})
    if set(activation_pins)!=set(expected)|{wrapper_path,wrapper_test} or any(
        activation_pins.get(p)!=v for p,v in expected.items()):
        raise FusionExecutionBlocked("UPSTREAM_ACTIVATION_CLOSURE_CHANGED")
    for pin in activation["pinned_artifacts"]:
        runtime._pin(pin["path"],pin["sha256"],"fusion_upstream_activation")
    return dict(pre_numeric_seed_correction_ref=deepcopy(correction_ref),
        upstream_activation_binding_ref=dict(path=str(activation_path.resolve()),sha256=activation_sha),
        upstream_activation_code_pins=deepcopy(activation["pinned_artifacts"]),
        upstream_artifact_refs=upstream_refs,upstream_code_revisions=revisions,
        original_fusion_code_pins=deepcopy(frozen["code_pins"]),
        replaced_wrapper_sha256=original[self_path],final_wrapper_sha256=current[self_path],
        code_pins=code_pins())

def activated(run, expected_matrix_sha=None):
    matrix=runtime.guard(run,expected_matrix_sha)
    run=Path(run)
    refs=_pin_map(matrix.get("pinned_artifacts",()))
    for name in (SPEC_NAME,SUPPORT_NAME):
        path=run/name
        if refs.get(str(path.resolve()))!=runtime.sha(path):
            raise FusionExecutionBlocked("FUSION_SPEC_SUPPORT_NOT_IN_WHOLE_MATRIX")
    frozen=runtime.read_json(run/SPEC_NAME)
    if _science(frozen)!=_science(specification()):
        raise FusionExecutionBlocked("FROZEN_FUSION_SCIENCE_CHANGED")
    binding_path=run/"FUSION_EXECUTION_BINDING_R1.json"
    state=runtime.read_json(run/"EXECUTION_STATE.json")
    if not fusion._sha(state.get("fusion_execution_binding_sha256")):
        raise FusionExecutionBlocked("INDEPENDENT_FUSION_IMPLEMENTATION_BINDING_REQUIRED")
    runtime._pin(binding_path,state["fusion_execution_binding_sha256"],"fusion_execution_binding")
    binding=runtime.read_json(binding_path)
    if (binding.get("schema")!="B_R4_FUSION_IMPLEMENTATION_BINDING_V1"
        or binding.get("research_id")!=runtime.ID
        or binding.get("matrix_sha256")!=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json")
        or binding.get("specification_sha256")!=runtime.sha(run/SPEC_NAME)
        or binding.get("support_sha256")!=runtime.sha(run/SUPPORT_NAME)
        or binding.get("science_recipe_unchanged") is not True
        or binding.get("scientific_retry")!=0
        or binding.get("stage_fit_units_before_binding")!=0):
        raise FusionExecutionBlocked("FUSION_IMPLEMENTATION_SCOPE_CHANGED")
    dependencies=implementation_dependencies(run,matrix,frozen)
    if any(binding.get(k)!=v for k,v in dependencies.items()):
        raise FusionExecutionBlocked("FINAL_FUSION_CODE_CLOSURE_CHANGED")
    for pin in binding["code_pins"]:runtime._pin(pin["path"],pin["sha256"],"fusion_execution")
    return matrix

def bind_execution(run):
    """Engineering-only receipt; root must independently pin it before fit."""
    run=Path(run);matrix=runtime.guard(run)
    frozen=runtime.read_json(run/SPEC_NAME)
    if _science(frozen)!=_science(specification()):
        raise FusionExecutionBlocked("FROZEN_FUSION_SCIENCE_CHANGED")
    ledger_path=run/"work/FUSION_FIT_STATUS.json"
    if ledger_path.exists() and runtime.read_json(ledger_path).get("new_fit_units")!=0:
        raise FusionExecutionBlocked("BINDING_MUST_PRECEDE_STAGE_B_NUMERIC_FITS")
    dependencies=implementation_dependencies(run,matrix,frozen)
    receipt=dict(schema="B_R4_FUSION_IMPLEMENTATION_BINDING_V1",research_id=runtime.ID,
        matrix_sha256=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json"),
        specification_sha256=runtime.sha(run/SPEC_NAME),support_sha256=runtime.sha(run/SUPPORT_NAME),
        science_recipe_unchanged=True,scientific_retry=0,stage_fit_units_before_binding=0,
        **dependencies,native_base_fits=0,accounts_created=0,numeric_rows_read=0,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        test2026_rows_read=0)
    runtime.write(run,"FUSION_EXECUTION_BINDING_R1.json",receipt,immutable=True)
    return dict(status="FUSION_IMPLEMENTATION_PENDING_INDEPENDENT_ROOT_PIN",
        sha256=runtime.sha(run/"FUSION_EXECUTION_BINDING_R1.json"),new_fit_units=0)

def compact_inputs(inputs):
    """Existing frame hash plus axes/attrs; bounded exact physical identity."""
    if isinstance(inputs,pd.DataFrame):
        return dict(frame_values_sha256=_frame_sha(inputs),
            index_sha256=content_hash(inputs.index.tolist()),rows=len(inputs),
            columns=list(inputs.columns),dtypes=[str(x) for x in inputs.dtypes],
            attrs=deepcopy(inputs.attrs),identity_schema="EXISTING_FRAME_HASH_AXES_ATTRS_V1")
    if isinstance(inputs,np.ndarray):
        if inputs.dtype.hasobject:return dict(array=inputs.tolist(),dtype=str(inputs.dtype))
        return dict(array_bytes_sha256=hashlib.sha256(np.ascontiguousarray(inputs).tobytes()).hexdigest(),
                    dtype=str(inputs.dtype),shape=list(inputs.shape))
    if isinstance(inputs,(list,tuple)):return [compact_inputs(x) for x in inputs]
    if isinstance(inputs,dict):return {k:compact_inputs(v) for k,v in inputs.items()}
    return inputs

class ArtifactLearn:
    """Estimator-object adapter around existing StateCache and StageLedger.

    The cached value is the immutable file proof. Unique models/scalars are saved
    once per physical key; aggregate receipts contain references, not model copies.
    Resume restores only ledger-recorded completed proofs. Interrupted/failed
    reservations are preserved and can never be automatically fitted again.
    """
    def __init__(self,run,ledger,source_sha,*,storage_guard=None):
        self.run,self.ledger=Path(run),ledger
        self.guard=storage_guard or (lambda p:assert_safe_output_path(
            p,kind="backtest",paths=resolve(REPO)))
        self.current_input_projection=None
        self.budget=StateBudget(300,reserve_callback=self._reserve)
        self.source_sha=source_sha
        self.records={}
        for row in ledger.status.get("physical_events",()):
            event=deepcopy(row)
            if row["kind"] not in LEARNED_KINDS:
                raise FusionExecutionBlocked("UNEXPECTED_FUSION_PHYSICAL_KIND")
            if row["key"] in self.budget._keys:
                raise FusionExecutionBlocked("DUPLICATE_PERSISTED_PHYSICAL_KEY")
            self.budget._keys.add(row["key"]);self.budget.counts[row["kind"]]+=1
            event["status"]={"FIT_COMPLETE":"SUCCEEDED","FIT_FAILURE":"FAILED"}.get(row["status"],"FAILED")
            self.budget.events.append(event)
            proof=row.get("state_artifact")
            if event["status"]=="SUCCEEDED" and proof:
                if content_hash(proof)!=row.get("result_sha256"):
                    raise FusionExecutionBlocked("PERSISTED_STATE_PROOF_CHANGED")
                self.records[row["key"]]=dict(status="SUCCEEDED",value=proof,
                                               result_sha256=row["result_sha256"])
            else:self.records[row["key"]]=dict(status="FAILED")
        if self.budget.learned_total!=ledger.status.get("new_fit_units",0):
            raise FusionExecutionBlocked("PERSISTED_FUSION_COUNTER_MISMATCH")
        self.caches={}

    def _reserve(self,event):
        proof=deepcopy(self.current_input_projection)
        if proof is None or content_hash(proof)!=event["inputs_sha256"]:
            raise FusionExecutionBlocked("PHYSICAL_INPUT_PROJECTION_PROOF_REQUIRED")
        self.ledger.reserve(dict(event,input_projection=proof))

    def for_year(self,year):
        if year not in YEARS:raise FusionExecutionBlocked("UNFROZEN_FUSION_YEAR")
        if year not in self.caches:
            self.caches[year]=StateCache(self.budget,source_identity=dict(id=runtime.ID,
                version="R4_FIXED_NATIVE_FUSION_V1",sha256=self.source_sha),
                cutoff=f"{year}-01-01T00:00:00+00:00",assets=PACKET,
                return_coordinate=fusion.UNIT,horizon=5,
                identity_epoch="ORIGINAL_PRODUCER_SECURITY_IDENTITY_PROJECTION",
                synthetic=False,mechanism=True,_records=self.records)
        cache=self.caches[year]
        def learn(kind,name,inputs,compute,parameters=None):
            parameters={} if parameters is None else parameters
            compact=compact_inputs(inputs)
            self.current_input_projection=compact
            key=content_hash(dict(kind=kind,name=name,context=cache.context,
                                  inputs_sha256=content_hash(compact),parameters=parameters))
            relative="models/fusion_states/"+key+".joblib"
            path=self.run/relative
            def create():
                self.guard(path);path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():raise FusionExecutionBlocked("UNREGISTERED_STATE_FILE_PRESERVED")
                result=compute()
                if content_hash(compact_inputs(inputs))!=content_hash(compact):
                    raise FusionExecutionBlocked("PHYSICAL_INPUT_MUTATION")
                tmp=path.with_suffix(".joblib.tmp")
                if tmp.exists():raise FusionExecutionBlocked("UNREGISTERED_STATE_TEMP_PRESERVED")
                joblib.dump(result,tmp,compress=3);tmp.replace(path)
                return dict(path=str(path),sha256=runtime.sha(path))
            try:
                proof=cache.learn(kind,name,compact,create,parameters)
                self.guard(Path(proof["path"]))
                if Path(proof["path"]).resolve()!=path.resolve():
                    raise FusionExecutionBlocked("PHYSICAL_ARTIFACT_PATH_CHANGED")
                runtime._pin(proof["path"],proof["sha256"],"completed_fusion_state")
                row=next(r for r in self.ledger.status["physical_events"] if r["key"]==key)
                row["state_artifact"]=deepcopy(proof)
                # Loading is permitted only inside the activated fitting owner.
                return joblib.load(proof["path"])
            finally:
                self.ledger.sync(self.budget.events)
        learn.cache=cache
        return learn

def _metadata_keys(frame):
    fields=KEYS+[c for c in IDENTITY if c in frame]
    if frame.duplicated(KEYS).any():raise FusionExecutionBlocked("DUPLICATE_PRODUCER_KEY")
    return frame[fields].sort_values(KEYS,kind="stable").reset_index(drop=True)

def check_native_receipt(receipt,year,member,matrix_sha,producer_sha):
    if (receipt.get("schema")!="B_R4_RAW_NATIVE_OPPORTUNITY_OOF_V1"
        or receipt.get("status")!="COMPLETE" or receipt.get("model")!=member
        or receipt.get("cohort")!=f"ANNUAL_{year}"
        or receipt.get("target")!=fusion.UNIT or receipt.get("target_clipped") is not False
        or receipt.get("raw_native_only") is not True
        or receipt.get("genuine_selected_recipe_OOF") is not True
        or receipt.get("whole_matrix_freeze_sha256")!=matrix_sha
        or receipt.get("producer_sha256")!=producer_sha
        or receipt.get("test2026_rows_read")!=0):
        raise FusionExecutionBlocked("NATIVE_OOF_CONTRACT_UNPROVEN:"+member)
    if year not in (2022,*YEARS):raise FusionExecutionBlocked("UNFROZEN_NATIVE_OOF_YEAR")
    train_rows=receipt.get("train_rows")
    if type(train_rows) is not int or train_rows<1:
        raise FusionExecutionBlocked("NATIVE_TRAIN_ROWCOUNT_REQUIRED")
    if receipt.get("seeds")!=list(opportunity.breadth.seeds(member,train_rows)):
        raise FusionExecutionBlocked("NATIVE_COMPLETE_FIXED_SEED_PROOF_REQUIRED")
    cut=_session_clock(receipt["source_fit_cutoff"])
    maturity=_session_clock(receipt["source_label_mature_max"])
    if cut!=pd.Timestamp(f"{year}-01-01",tz="UTC") or maturity>=cut:
        raise FusionExecutionBlocked("NATIVE_OOF_MATURITY_BOUNDARY:"+member)
    if not fusion._sha(receipt.get("selected_capacity_rule_sha256")):
        raise FusionExecutionBlocked("NATIVE_SELECTED_RECIPE_PROOF_REQUIRED")
    return cut,maturity

class SurfaceProvider:
    """Compose existing Stage A reader with hash-bound descendant OOF artifacts."""
    def __init__(self,run,matrix_sha,*,numeric=False):
        self.run,self.matrix_sha=Path(run),matrix_sha
        _,pins,self.binding_ref,_=opportunity.source_binding(run)
        self.reader=opportunity.FoldReader(pins,numeric=numeric)
        self.numeric=numeric
        self.producer_sha=runtime.sha(opportunity.__file__)
        self.loaded={};self.meta_loaded={};self.dependencies={};self.histories={};self.truths={}

    def native(self,members,year,*,values=True):
        members=tuple(members);key=(members,year,values)
        if key in self.loaded:return self.loaded[key].copy()
        reference=None;surface=None;deps=[]
        for member in members:
            receipt_path=self.run/f"receipts/OPPORTUNITY_{member}_{year}.json"
            receipt=runtime.read_json(receipt_path)
            cut,mature=check_native_receipt(receipt,year,member,self.matrix_sha,self.producer_sha)
            if receipt.get("source_binding_sha256")!=self.binding_ref["sha256"]:
                raise FusionExecutionBlocked("NATIVE_B_SOURCE_BINDING_CHANGED")
            for field,relative in (("specification_sha256",opportunity.SPEC_NAME),
                ("support_sha256",opportunity.SUPPORT_NAME),
                ("selected_capacity_rule_sha256","SELECTED_CAPACITY_R4.json")):
                runtime._pin(self.run/relative,receipt.get(field),"native_oof_upstream_contract")
            support=runtime.read_json(self.run/opportunity.SUPPORT_NAME)
            support_node=next((n for n in support["nodes"] if n["cohort"]==f"ANNUAL_{year}"),None)
            if support_node is None or support_node.get("train_rows")!=receipt["train_rows"]:
                raise FusionExecutionBlocked("NATIVE_TRAIN_ROWCOUNT_NOT_FROZEN_SUPPORT")
            selected=runtime.read_json(self.run/"SELECTED_CAPACITY_R4.json")
            if (selected.get("whole_matrix_freeze_sha256")!=self.matrix_sha
                or selected.get("selection_scope")!="2021H1/H2_ONLY"
                or selected.get("capacities",{}).get(member)!=receipt.get("capacity")):
                raise FusionExecutionBlocked("NATIVE_FROZEN_CAPACITY_CHANGED")
            ref=receipt["artifact"];path=self.run/f"OOF/OPPORTUNITY_{member}_{year}.parquet"
            if Path(ref["path"]).resolve()!=path.resolve():
                raise FusionExecutionBlocked("NATIVE_OOF_PATH_CHANGED")
            pf,footer=guard_parquet(path,ref["sha256"],["signal_date","source_fit_cutoff","source_label_mature_max"])
            meta_cols=KEYS+IDENTITY+["source_fit_cutoff","source_label_mature_max"]
            raw=pf.read(columns=meta_cols).to_pandas()
            keys=_metadata_keys(raw)
            if reference is None:reference=keys;surface=raw[KEYS+IDENTITY].copy()
            elif not keys.equals(reference):
                raise FusionExecutionBlocked("COMPLETE_PACKET_KEY_OR_IDENTITY_MISMATCH")
            if (_session_clock(raw.signal_date.min()).year!=year
                or _session_clock(raw.signal_date.max()).year!=year
                or not pd.to_datetime(raw.source_fit_cutoff).eq(pd.Timestamp(receipt["source_fit_cutoff"])).all()
                or not pd.to_datetime(raw.source_label_mature_max).eq(pd.Timestamp(receipt["source_label_mature_max"])).all()):
                raise FusionExecutionBlocked("NATIVE_OOF_ROW_RECEIPT_CLOCK_MISMATCH")
            if values:
                if not self.numeric:raise FusionExecutionBlocked("NUMERIC_ACTIVATION_REQUIRED")
                cols=["native_mu"]+(["native_sigma"] if member in SCALE_ROLES else [])
                projected=pf.read(columns=KEYS+cols).to_pandas()
                if not projected[KEYS].equals(raw[KEYS]):
                    raise FusionExecutionBlocked("NATIVE_NUMERIC_METADATA_KEY_MISMATCH")
                projected=projected.rename(columns={"native_mu":member+"__mu","native_sigma":member+"__scale"})
                surface=surface.merge(projected,on=KEYS,how="left",validate="one_to_one",sort=False)
            surface[member+"__source_cutoff"]=cut
            surface[member+"__source_label_mature_max"]=mature
            surface[member+"__source_sha256"]=ref["sha256"]
            surface[member+"__producer_role"]=NATIVE_ROLE
            deps.append(dict(artifact=ref,receipt=dict(path=str(receipt_path),sha256=runtime.sha(receipt_path)),
                             footer=footer))
        surface.attrs.update(source_inputs_sha256=self.binding_ref["sha256"],
            target_binding_sha256=self.reader.pins["label"]["sha256"],
            qualified_oof_contract_sha256=content_hash(deps),target_coordinate=fusion.UNIT)
        self.dependencies[(members,year)]=deps
        self.loaded[key]=surface
        return surface.copy()

    def history(self,members,year,*,role=NATIVE_ROLE,context=True):
        cache_key=(tuple(members),year,role,context)
        if cache_key in self.histories:return self.histories[cache_key].copy()
        prior=list(range(2022,year))
        if role==META_ROLE:prior=list(range(2023,year))
        if not prior:raise FusionExecutionBlocked("NO_EARLIER_GENUINE_META_OOF")
        truth_key=(year,tuple(prior),context)
        if truth_key not in self.truths:
            self.truths[truth_key]=_clocks(self.reader.read_earlier_truth(f"{year}-01-01",prior,
                context_cols=fusion.CONTEXT if context else ()))
        truth=self.truths[truth_key]
        pieces=[];deps=[]
        for earlier in prior:
            native=self.native(members,earlier) if role==NATIVE_ROLE else self.meta(members[0],earlier)
            native["signal_date"]=[_session_clock(v) for v in native.signal_date]
            expected=truth.loc[truth.signal_date.dt.year.eq(earlier)].copy()
            identity=_metadata_keys(expected)
            subset=native.merge(expected[KEYS],on=KEYS,how="inner",validate="one_to_one",sort=False)
            if not _metadata_keys(subset).equals(identity):
                raise FusionExecutionBlocked("EARLIER_OOF_REQUIRED_TRUTH_IDENTITY_MISMATCH")
            values=[c for c in subset if c.endswith("__mu") or c.endswith("__scale") or "__source_" in c or c.endswith("__producer_role")]
            piece=expected.merge(subset[KEYS+values],on=KEYS,how="left",validate="one_to_one",sort=False)
            pieces.append(piece);deps.append(native.attrs["qualified_oof_contract_sha256"])
        result=pd.concat(pieces,ignore_index=True)
        result.attrs.update(source_inputs_sha256=self.binding_ref["sha256"],
            target_binding_sha256=self.reader.pins["label"]["sha256"],
            qualified_oof_contract_sha256=content_hash(deps),target_coordinate=fusion.UNIT)
        self.histories[cache_key]=result
        return result.copy()

    def current(self,members,year,*,role=NATIVE_ROLE):
        raw=self.native(members,year) if role==NATIVE_ROLE else self.meta(members[0],year)
        context=self.reader.prediction_features(year,list(fusion.CONTEXT))
        if "y_open5" in context:raise FusionExecutionBlocked("CURRENT_Y_FORBIDDEN")
        raw["signal_date"]=[_session_clock(v) for v in raw.signal_date]
        context["signal_date"]=[_session_clock(v) for v in context.signal_date]
        if not _metadata_keys(raw).equals(_metadata_keys(context)):
            raise FusionExecutionBlocked("CURRENT_COMPLETE_PACKET_FEATURE_IDENTITY_MISMATCH")
        context=context.drop(columns=[c for c in IDENTITY if c in context])
        raw["signal_date"]=[_session_clock(v) for v in raw.signal_date]
        context["signal_date"]=[_session_clock(v) for v in context.signal_date]
        raw=raw.merge(context,on=KEYS,how="left",validate="one_to_one",sort=False)
        raw["signal_date"]=[_session_clock(v) for v in raw.signal_date]
        if raw.signal_date.dt.year.ne(year).any():raise FusionExecutionBlocked("CURRENT_YEAR_MISMATCH")
        if not np.isfinite(raw[[m+"__mu" for m in members]+list(fusion.CONTEXT)].to_numpy(float)).all():
            raise FusionExecutionBlocked("CURRENT_NONFINITE_PACKET_NO_ROW_DROP")
        fusion.identity_columns(raw)
        return raw

    def meta(self,method,year):
        key=(method,year)
        if key in self.meta_loaded:return self.meta_loaded[key].copy()
        receipt_path=self.run/f"receipts/FUSION_META_{method}_{year}.json"
        receipt=runtime.read_json(receipt_path)
        if (receipt.get("genuine_chronological_meta_OOF") is not True
            or receipt.get("whole_matrix_freeze_sha256")!=self.matrix_sha
            or receipt.get("producer_sha256")!=runtime.sha(__file__)
            or receipt.get("target")!=fusion.UNIT or receipt.get("method")!=method
            or receipt.get("year")!=year or receipt.get("test2026_rows_read")!=0):
            raise FusionExecutionBlocked("GENUINE_META_OOF_PROOF_REQUIRED")
        ref=receipt["artifact"];path=self.run/f"OOF/FUSION_META_{method}_{year}.parquet"
        if Path(ref["path"]).resolve()!=path.resolve():raise FusionExecutionBlocked("META_OOF_PATH_CHANGED")
        pf,_=guard_parquet(path,ref["sha256"],["signal_date","source_fit_cutoff","source_label_mature_max"])
        cols=KEYS+IDENTITY+["source_fit_cutoff","source_label_mature_max"]
        frame=pf.read(columns=cols).to_pandas()
        _metadata_keys(frame)
        cut=_session_clock(receipt["source_fit_cutoff"])
        mature=_session_clock(receipt["source_label_mature_max"])
        if cut!=pd.Timestamp(f"{year}-01-01",tz="UTC") or mature>=cut:
            raise FusionExecutionBlocked("META_OOF_SOURCE_CLOCK")
        if (_session_clock(frame.signal_date.min()).year!=year
            or _session_clock(frame.signal_date.max()).year!=year
            or not pd.to_datetime(frame.source_fit_cutoff,utc=True).eq(cut).all()
            or not pd.to_datetime(frame.source_label_mature_max,utc=True).eq(mature).all()):
            raise FusionExecutionBlocked("META_OOF_ROW_RECEIPT_CLOCK_MISMATCH")
        if not self.numeric:raise FusionExecutionBlocked("NUMERIC_ACTIVATION_REQUIRED")
        vector=pf.read(columns=KEYS+["mu"]).to_pandas()
        if not frame[KEYS].equals(vector[KEYS]):raise FusionExecutionBlocked("META_OOF_VECTOR_KEYS")
        frame=frame.merge(vector.rename(columns={"mu":method+"__mu"}),on=KEYS,validate="one_to_one",sort=False)
        frame[method+"__source_cutoff"]=cut;frame[method+"__source_label_mature_max"]=mature
        frame[method+"__source_sha256"]=ref["sha256"];frame[method+"__producer_role"]=META_ROLE
        frame.attrs.update(source_inputs_sha256=self.binding_ref["sha256"],
            target_binding_sha256=self.reader.pins["label"]["sha256"],
            qualified_oof_contract_sha256=runtime.sha(receipt_path),target_coordinate=fusion.UNIT)
        self.meta_loaded[key]=frame
        return frame.copy()

    def release(self):
        self.loaded.clear();self.meta_loaded.clear();self.histories.clear();self.truths.clear();gc.collect()

def _apply_meta(current,fit,members):
    block=current[[c for c in KEYS+IDENTITY+["execution_date","label_end_date","label_mature_date",
        "trade_eligible","fit_eligible","label_available"] if c in current]].copy()
    mu=fit["model"].predict(current[[m+"__mu" for m in members]].to_numpy(float),
                            current[list(fusion.CONTEXT)].to_numpy(float))
    if not np.isfinite(mu).all():raise FusionExecutionBlocked("NONFINITE_META_OOF")
    block["mu"]=mu;block["uncertainty_proxy"]=fit["prior_OOF_error_RMS"]
    return block

def _apply_calibration(current,fit,column):
    block=current[[c for c in KEYS+IDENTITY+["execution_date","label_end_date","label_mature_date",
        "trade_eligible","fit_eligible","label_available"] if c in current]].copy()
    mu=fit["model"].predict(fit["scaler"].transform(current[[column]].to_numpy(float)))
    if not np.isfinite(mu).all():raise FusionExecutionBlocked("NONFINITE_CALIBRATED_VALUE")
    block["mu"]=mu;block["uncertainty_proxy"]=fit["prior_OOF_error_RMS"]
    return block

def _summary(fit):
    return {k:v for k,v in fit.items() if k not in ("model","scaler","prior_OOF_error_RMS","multiplier")}

def fit_return_all_phases(history,cutoff,members,columns,learn,*,name,producer_role=META_ROLE):
    """Complete the predeclared full phase after a failed probe; no key retries."""
    start=len(learn.cache.usage_log)
    try:
        return fusion.fit_return_calibration(history,cutoff,members,columns,learn,
            name=name,producer_role=producer_role)
    except Exception:
        # Empty/unmatured/illegal source has no physical callback; it remains 0-fit.
        if len(learn.cache.usage_log)>start:
            h,_,_=fusion.prepare_history(history,cutoff,members,value_columns=columns,
                producer_role=producer_role)
            dates=sorted(h.signal_date.unique());boundary=dates[len(dates)//2]
            first=h.loc[h.signal_date.lt(boundary)&h.label_mature_date.lt(boundary)&h.label_end_date.lt(boundary)]
            held=h.loc[h.signal_date.ge(boundary)]
            if len(first)>=100 and len(held)>=100:
                try:
                    scaler=fusion._scaler(h,columns,"full",learn,"return_calibration:"+name)
                    fusion._learn(learn,"bridge_calibration","r4:return_calibrator:"+name+":full",
                        fusion._frame_inputs(h,columns),lambda:fusion.Ridge(alpha=100.).fit(
                            scaler.transform(h[columns].to_numpy(float)),h.y_open5.to_numpy(float),
                            sample_weight=fusion._weights(h)),
                        dict(name=name,phase="full",alpha=100.,columns=columns))
                except Exception:
                    pass  # The original failure and every reservation remain occupied.
        raise

def execute(provider,learn_for_year,publish):
    """All applicable fixed slots; source failures block, scientific failures retain."""
    records=[]
    for year in YEARS:
        cutoff=f"{year}-01-01T00:00:00+00:00"
        learn=learn_for_year(year)
        for method in fusion.METHODS:
            record=dict(role="meta",method=method,year=year,fit_state_qualified=None,oof_qualified=False)
            start=len(learn.cache.usage_log)
            try:
                history=provider.history(PACKET,year)
                fit=fusion.fit_meta(history,cutoff,method,PACKET,learn,fixed_weights=FIXED_WEIGHTS)
                record.update(_summary(fit))
                record["fit_state_qualified"]=bool(fit["qualified"])
                record["qualified"]=False
                if fit["qualified"]:
                    current=provider.current(PACKET,year)
                    block=_apply_meta(current,fit,PACKET)
                    publish("META",method,year,block,history,learn.cache.usage_log[start:],record)
                    record["qualified"]=record["oof_qualified"]=True
            except Exception as exc:
                record.update(status="BLOCKED_OR_FAILED_RETAINED",failure_type=type(exc).__name__,failure_code=str(exc)[:240])
            record["fit_dependency_ids"]=list(dict.fromkeys(learn.cache.usage_log[start:]))
            records.append(record)
        for method in fusion.METHODS:
            record=dict(role="meta_return_calibration",method=method,year=year,fit_state_qualified=None,oof_qualified=False)
            start=len(learn.cache.usage_log)
            try:
                history=provider.history((method,),year,role=META_ROLE,context=False)
                fit=fit_return_all_phases(history,cutoff,(method,),[method+"__mu"],
                    learn,name="meta:"+method)
                record["fit_state_qualified"]=True
                current=provider.current((method,),year,role=META_ROLE)
                block=_apply_calibration(current,fit,method+"__mu")
                record.update(status="COMPLETE",**_summary(fit))
                publish("META_CAL",method,year,block,history,learn.cache.usage_log[start:],record)
                record["qualified"]=record["oof_qualified"]=True
            except Exception as exc:
                record.update(status="BLOCKED_OR_FAILED_RETAINED",failure_type=type(exc).__name__,failure_code=str(exc)[:240])
            record["fit_dependency_ids"]=list(dict.fromkeys(learn.cache.usage_log[start:]))
            records.append(record)
        for role,roster in (("native_value",VALUE_ROLES),("native_scale",SCALE_ROLES)):
            for member in roster:
                record=dict(role=role,method=member,year=year,fit_state_qualified=None,oof_qualified=False)
                start=len(learn.cache.usage_log)
                try:
                    history=provider.history((member,),year,context=False)
                    column=member+"__mu"
                    if role=="native_value":
                        fit=fit_return_all_phases(history,cutoff,(member,),[column],learn,
                            name="native:"+member,producer_role=NATIVE_ROLE)
                        record["fit_state_qualified"]=True
                        block=_apply_calibration(provider.current((member,),year),fit,column)
                    else:
                        scale=member+"__scale"
                        fit=fusion.fit_native_scale_proxy(history,cutoff,(member,),column,scale,
                                                         learn,name=member)
                        record["fit_state_qualified"]=True
                        current=provider.current((member,),year)
                        if not np.isfinite(current[scale].to_numpy(float)).all() or current[scale].le(0).any():
                            raise FusionExecutionBlocked("CURRENT_POSITIVE_NATIVE_SCALE_REQUIRED")
                        block=current[KEYS+IDENTITY].copy()
                        block["mu"]=current[column];block["uncertainty_proxy"]=current[scale]*fit["multiplier"]
                    record.update(status="COMPLETE",**_summary(fit))
                    publish("NATIVE_VALUE" if role=="native_value" else "NATIVE_SCALE",member,
                            year,block,history,learn.cache.usage_log[start:],record)
                    record["qualified"]=record["oof_qualified"]=True
                except Exception as exc:
                    record.update(status="BLOCKED_OR_FAILED_RETAINED",failure_type=type(exc).__name__,failure_code=str(exc)[:240])
                record["fit_dependency_ids"]=list(dict.fromkeys(learn.cache.usage_log[start:]))
                records.append(record)
        provider.release()
    return records

def publisher(run,matrix_sha):
    def publish(prefix,name,year,block,history,dependencies,record):
        relative=f"OOF/FUSION_{prefix}_{name}_{year}.parquet";path=Path(run)/relative
        receipt_relative=f"receipts/FUSION_{prefix}_{name}_{year}.json"
        receipt_path=Path(run)/receipt_relative
        identity=dict(prefix=prefix,method=name,year=year,whole_matrix_freeze_sha256=matrix_sha,
                      fit_dependency_ids=list(dict.fromkeys(dependencies)),
                      qualified_history_sha256=_frame_sha(history))
        if path.exists() or receipt_path.exists():
            if not path.exists() or not receipt_path.exists():
                raise FusionExecutionBlocked("UNREGISTERED_OUTPUT_PRESERVED")
            old=runtime.read_json(receipt_path)
            if old.get("identity")!=identity:raise FusionExecutionBlocked("OUTPUT_IDENTITY_CHANGED")
            runtime._pin(path,old["artifact"]["sha256"],"fusion_output_reuse")
            record["receipt_ref"]=dict(path=str(receipt_path),sha256=runtime.sha(receipt_path))
            return
        assert_safe_output_path(path,kind="backtest",paths=resolve(REPO))
        path.parent.mkdir(parents=True,exist_ok=True)
        block=block.copy()
        cut=pd.Timestamp(f"{year}-01-01",tz="UTC")
        mature=history.label_mature_date.max()
        if mature>=cut:raise FusionExecutionBlocked("OUTPUT_MATURE_BOUNDARY")
        block["source_fit_cutoff"]=cut;block["source_label_mature_max"]=mature
        block["fold_year"]=year;block["method"]=name
        tmp=path.with_suffix(".parquet.tmp")
        if tmp.exists():raise FusionExecutionBlocked("UNREGISTERED_OUTPUT_TEMP_PRESERVED")
        block.to_parquet(tmp,index=False);tmp.replace(path)
        receipt=dict(schema="B_R4_FUSION_CHRONOLOGICAL_OOF_V1",status="COMPLETE",
            identity=identity,artifact=dict(path=str(path),sha256=runtime.sha(path)),
            method=name,year=year,target=fusion.UNIT,target_clipped=False,
            producer_sha256=runtime.sha(__file__),specification_sha256=runtime.sha(Path(run)/SPEC_NAME),
            whole_matrix_freeze_sha256=matrix_sha,source_fit_cutoff=cut.isoformat(),
            source_label_mature_max=mature.isoformat(),genuine_chronological_meta_OOF=prefix=="META",
            uncertainty_role="EARLIER_OOF_OR_CHRONOLOGICAL_PROBE_HELDOUT_RMS_PROXY",
            certified_coverage=False,strict_PIT_promotion_eligible=False,
            quote_qualified=False,certified_nav_qualified=False,test2026_rows_read=0,
            source_clock_semantics=specification()["source_clock_semantics"],
            rows=len(block),columns=list(block.columns))
        runtime.write(Path(run),receipt_relative,receipt,immutable=True)
        record["receipt_ref"]=dict(path=str(receipt_path),sha256=runtime.sha(receipt_path))
    return publish

def prepare(run):
    """Zero-fit source specification. Descendant OOF support is checked after A."""
    run=Path(run)
    # Canonical original metadata routing only; no native/target numeric projection.
    opportunity.source_binding(run)
    runtime.write(run,SPEC_NAME,specification(),immutable=True)
    runtime.write(run,SUPPORT_NAME,dict(schema="B_R4_FUSION_SUPPORT_PREDECLARATION_V1",
        status="SUPPORT_PENDING_STAGE_A_GENUINE_OOF",numeric_rows_read=0,new_fit_units=0,
        fixed_native_packet=list(PACKET),genuine_oof_years_required=[2022,2023,2024,2025],
        actual_oof_rows=None,actual_finite_support=None,metadata_selection_on_outcomes=False,
        specification_sha256=runtime.sha(run/SPEC_NAME),test2026_locked=True,
        strict_PIT_promotion_eligible=False),immutable=True)
    return dict(status="FUSION_SPEC_PREPARED",specification_sha256=runtime.sha(run/SPEC_NAME),
                hard_upper=296,stage_cap=300,new_fit_units=0,numeric_rows_read=0)

def inspect(run,expected_matrix_sha=None):
    activated(run,expected_matrix_sha)
    matrix_sha=runtime.sha(Path(run)/"WHOLE_MATRIX_FREEZE.json")
    provider=SurfaceProvider(run,matrix_sha,numeric=False)
    records=[]
    for year in (2022,*YEARS):
        for packet in (PACKET,*[(x,) for x in VALUE_ROLES+SCALE_ROLES]):
            try:
                frame=provider.native(packet,year,values=False)
                records.append(dict(year=year,members=list(packet),rows=len(frame),
                    metadata_sha256=_frame_sha(frame),status="OOF_METADATA_PROVEN_VALUES_PENDING"))
            except Exception as exc:
                records.append(dict(year=year,members=list(packet),status="BLOCKED_DEPENDENCY",
                    failure_type=type(exc).__name__,failure_code=str(exc)[:240]))
        provider.release()
    support=dict(schema="B_R4_FUSION_DESCENDANT_OOF_SUPPORT_V1",nodes=records,
        whole_matrix_freeze_sha256=matrix_sha,numeric_rows_read=0,new_fit_units=0,
        budget=specification()["budget"],test2026_rows_read=0)
    runtime.write(Path(run),"derived/FUSION_DESCENDANT_OOF_SUPPORT_R4.json",support)
    return dict(status="FUSION_SUPPORT_INSPECTED",nodes=len(records),new_fit_units=0)

def run_training(run,expected_matrix_sha=None):
    activated(run,expected_matrix_sha)
    run=Path(run);matrix_sha=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json")
    with runtime.stage_writer(run,"calibration_fusion"):
        ledger=runtime.StageLedger(run,"calibration_fusion",expected_matrix_sha=matrix_sha)
        callback=ArtifactLearn(run,ledger,content_hash(dict(
            spec_sha256=runtime.sha(run/SPEC_NAME),matrix_sha256=matrix_sha)))
        provider=SurfaceProvider(run,matrix_sha,numeric=True)
        records=execute(provider,callback.for_year,publisher(run,matrix_sha))
        audit=dict(schema="B_R4_FUSION_EXECUTION_AUDIT_V1",records=records,
            actual_stage_fit_units=ledger.status["new_fit_units"],
            physical_events=len(ledger.status["physical_events"]),stage_cap=300,
            inherited_B_reservations_counted_elsewhere=1876,scientific_retry=0,
            new_base_fits=0,new_account_paths=0,test2026_rows_read=0,
            whole_matrix_freeze_sha256=matrix_sha,producer_sha256=runtime.sha(__file__),
            strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
            source_numeric_projection_audit=provider.reader.audit)
        runtime.write(run,"derived/FUSION_STAGE_AUDIT.json",audit)
        ledger.status["status"]="FROZEN_STAGE_B_ATTEMPTS_COMPLETE";ledger.checkpoint()
        return {k:audit[k] for k in ("actual_stage_fit_units","physical_events","stage_cap","new_base_fits","new_account_paths","test2026_rows_read")}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",required=True);parser.add_argument("--matrix-sha")
    parser.add_argument("phase",choices=("prepare","bind","inspect","fit"))
    args=parser.parse_args()
    result=prepare(args.run) if args.phase=="prepare" else bind_execution(args.run) if args.phase=="bind" else (
        inspect(args.run,args.matrix_sha) if args.phase=="inspect" else run_training(args.run,args.matrix_sha))
    print(json.dumps(result,sort_keys=True),flush=True)
if __name__=="__main__":main()
