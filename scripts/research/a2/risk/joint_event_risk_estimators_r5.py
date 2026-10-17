"""Pure R5 event-risk descendants over pinned native estimator bodies.

No readers, ledger, account, provider or model-selection system. Known-current
UID N=0 HP is explicitly new prior-predictive science; old min10/min30 parents
retain their bytes and eligibility. Missing observations stay absent.
"""
from __future__ import annotations
import copy
from dataclasses import replace
import numpy as np
import pandas as pd
from . import short_history_risk_r4 as shr
from . import shared_risk_engine_r2 as engine
from .shared_risk_budget_r2 import content_hash
from .event_risk_contract_r5 import (FAMILIES, event_calendar, bind_pinned_kernel,
    structural_identity, conditional_prior_completion)

SHORT_SHA = "f1037f576d443861733a24713105437035d515fa4e591c31010f514b6a6a9752"
ENGINE_SHA = "db89f65d22dbd300973cfba8f11de1a3b758365f5a8067706b48ee2ee1a16647"
PRIMARY_PROOF_FIELDS = ("assets","asset_uids","asset_epochs","security_coordinate",
                        "source_support_identity","source_qualified","maturity_qualified")
CLASSIC = {"LW":"LW","OAS":"OAS","EWMA":"EWMA",
           "CONSTANT_CORRELATION":"CONSTANT_CORR","PCA_FACTOR":"PCA"}
EXTENSIONS = {"QQQ_RESIDUAL":"RB","FF48_HIERARCHICAL":"RH",
    "DOWNSIDE_SEMIVARIANCE":"RT","REGIME_COVARIANCE":"RR",
    "UNCERTAINTY_JACKKNIFE":"RU","DISAGREEMENT_ENSEMBLE":"RE"}


def specification(*, industry_mode="MARKET_ONLY"):
    if industry_mode not in {"MARKET_ONLY","FF48_IF_ASOF_QUALIFIED"}:
        raise ValueError("FROZEN_INDUSTRY_MODE_REQUIRED")
    recipe = shr.specification()
    recipe.update(schema="B_R5_EVENT_RISK_PRIOR_AND_CONDITIONAL_COMPLETION_V1",
        methods=list(FAMILIES),
        cadence="current Close structural event; previous legal Close exclusive cutoff",
        industry_mode=industry_mode, minimum_nominal_n=0, minimum_structural_n=0,
        HP_minimum_history="N0 allowed only with independently qualified current UID/epoch/source",
        EB_FACTOR_minimum_nominal_n=10, classical_minimum_nominal_n=30,
        no_unknown_identity_prior=True, no_observations_created=True,
        native_parent_min10_qualification_changed=False,
        native_parent_min30_qualification_changed=False,
        parent_short_history_sha256=SHORT_SHA,parent_engine_sha256=ENGINE_SHA,
        method_ids={f:"R5::"+f+"::"+("KNOWN_UID_PRIOR_PREDICTIVE_N0" if f in {"SHR_HP","SHR_CC"}
            else "MIN10_PLUS_HP_CONDITIONAL_COMPLETION" if f in {"SHR_EB","SHR_FACTOR"}
            else "EXPLICIT_SCENARIO_SOURCE_REQUIRED" if f=="TAIL_CVAR"
            else "MIN30_PLUS_HP_CONDITIONAL_COMPLETION") for f in FAMILIES},
        tail_CVaR="BLOCKED_SOURCE_NO_INDEPENDENT_SCENARIO_RECEIPT_OR_PRODUCER",
        native_classical_missing_policy="existing observed-column mean / absent centered=0; not price fill",
        completion="preserve fitted long block and original HP prior conditional law",
        FF48_extension="native pinned RH uses original independently qualified as-of industry mapping on min30 cohort; full HP conditional completion prior remains MARKET_ONLY core HP; no second FF HP prior",
        family_source_binding="HP/CC and all shared full HP dependencies hash only the seven PRIMARY proof fields; FF48_HIERARCHICAL output uses family_source_support_identity.FF48_HIERARCHICAL with exact industry receipt and FF48 local event/source pins; other fifteen outputs use PRIMARY",
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    recipe.pop("dynamic_status",None)
    recipe.pop("robust_status",None)
    recipe["parent_SHR_maximum_learned_states_per_refresh"]=recipe.pop("maximum_learned_states_per_refresh")
    return recipe


class EventRiskEstimator:
    """One event-owned cache; primitive sharing remains the canonical StateCache."""
    def __init__(self, recipe=None):
        self.recipe=copy.deepcopy(recipe if recipe is not None else specification())
        expected=specification(industry_mode=self.recipe.get("industry_mode"))
        if self.recipe != expected:
            raise ValueError("EXACT_LITERAL_R5_RECIPE_REQUIRED")
        self.recipe_sha256=content_hash(self.recipe)
        self._parent_state=bind_pinned_kernel(shr._state,physical_path=shr.__file__,
            expected_sha256=SHORT_SHA,dependencies={"RECIPE":self.recipe})
        self._donor_qualification=bind_pinned_kernel(shr.qualify_metadata,physical_path=shr.__file__,
            expected_sha256=SHORT_SHA,dependencies={"_calendar":event_calendar,"RECIPE":self.recipe})
        self._cache=bind_pinned_kernel(shr.make_cache,physical_path=shr.__file__,
            expected_sha256=SHORT_SHA,dependencies={"_calendar":event_calendar})
        self._engine_fit=bind_pinned_kernel(engine.SharedRiskEngine.fit,physical_path=engine.__file__,
            expected_sha256=ENGINE_SHA,dependencies={"_calendar":event_calendar})

    def make_cache(self,inputs,*,as_of,budget=None):
        return self._cache(inputs,as_of=as_of,budget=budget)

    def _mode_input(self,inputs):
        if self.recipe["industry_mode"]=="MARKET_ONLY":
            return replace(inputs,industry_mapping=None,industry_receipt=None)
        return inputs

    def _current(self,inputs,proof):
        required=set(PRIMARY_PROOF_FIELDS)
        if not isinstance(proof,dict) or not required.issubset(proof):
            raise ValueError("INDEPENDENT_CURRENT_IDENTITY_SOURCE_PROOF_REQUIRED")
        if (tuple(proof["assets"])!=tuple(inputs.assets) or proof["asset_uids"]!=dict(inputs.asset_uids)
            or proof["source_qualified"] is not True or proof["maturity_qualified"] is not True):
            raise ValueError("CURRENT_FULL_DOMAIN_SOURCE_OR_MATURITY_UNQUALIFIED")
        for mapping in (proof["asset_uids"],proof["asset_epochs"]):
            if any(not isinstance(v,str) or not v.strip() or v.upper().startswith("UNKNOWN") for v in mapping.values()):
                raise ValueError("UNKNOWN_CURRENT_UID_EPOCH_FORBIDDEN")
        return structural_identity(assets=tuple(inputs.assets),uids=proof["asset_uids"],
            epochs=proof["asset_epochs"],security_coordinate=proof["security_coordinate"],
            source_support_identity=proof["source_support_identity"])

    def _family_support(self,inputs,family,current,cutoff):
        source=current["source_support_identity"]
        if family=="FF48_HIERARCHICAL":
            source=current.get("family_source_support_identity",{}).get(family)
            required={"dependency","dependency_local_event_id","dependency_local_signature_sha256",
                      "source_pins","industry_source"}
            receipt=inputs.industry_receipt
            if not isinstance(source,dict) or not required.issubset(source) or receipt is None:
                raise ValueError("FF48_FAMILY_SOURCE_SUPPORT_PROOF_REQUIRED")
            signature=source["dependency_local_signature_sha256"]
            pins=source["source_pins"]
            if (source["dependency"]!="FF48" or not isinstance(source["dependency_local_event_id"],str)
                    or not source["dependency_local_event_id"].strip()
                    or not isinstance(signature,str) or len(signature)!=64
                    or any(c not in "0123456789abcdef" for c in signature)
                    or not isinstance(pins,dict) or pins.get("FF48")!=receipt.source_sha256
                    or source["industry_source"]!=receipt.cache_identity()):
                raise ValueError("FF48_FAMILY_SOURCE_RECEIPT_OR_LOCAL_EVENT_MISMATCH")
            receipt.validate(cutoff,role="industry",primary=inputs.source_receipt)
        structural_identity(assets=tuple(current["assets"]),uids=current["asset_uids"],
            epochs=current["asset_epochs"],security_coordinate=current["security_coordinate"],
            source_support_identity=source)
        return source

    @staticmethod
    def _cohort_input(inputs,assets):
        assets=tuple(assets)
        obs=inputs.observations.loc[inputs.observations.asset.isin(assets)].copy()
        industry=None if inputs.industry_mapping is None else inputs.industry_mapping.loc[inputs.industry_mapping.asset.isin(assets)].copy()
        return replace(inputs,assets=assets,asset_uids={a:inputs.asset_uids[a] for a in assets},
                       observations=obs,industry_mapping=industry)

    @staticmethod
    def _cohort_identity(proof,assets):
        return {**proof,"assets":list(assets),"asset_uids":{a:proof["asset_uids"][a] for a in assets},
                "asset_epochs":{a:proof["asset_epochs"][a] for a in assets}}

    def qualify(self,inputs,*,as_of,support_metadata,current_identity_proof):
        """Metadata only; N0 has zero rows, not artificial support observations."""
        inputs=self._mode_input(inputs)
        structural=self._current(inputs,current_identity_proof)
        as_of,cutoff,sessions=event_calendar(inputs,as_of)
        inputs.source_receipt.validate(cutoff)
        legal=shr._metadata(inputs,cutoff,sessions)
        origins=pd.DatetimeIndex(legal.origin_at.unique()).sort_values()[-252:]
        if len(origins)!=252:
            raise ValueError("INSUFFICIENT_252_LEGAL_PARENT_METADATA_ORIGINS")
        if (not isinstance(support_metadata,pd.DataFrame) or
                not {"asset","origin_at","qualified"}.issubset(support_metadata)):
            raise ValueError("SOURCE_QUALIFIED_METADATA_KEYS_REQUIRED")
        support=support_metadata.loc[:,["asset","origin_at","qualified"]].copy()
        support["origin_at"]=support.origin_at.map(engine._time)
        support=support.loc[support.origin_at.isin(origins)]
        if (not support.asset.isin(inputs.assets).all() or support.duplicated(["asset","origin_at"]).any()
            or not support.qualified.map(lambda v:isinstance(v,(bool,np.bool_))).all()):
            raise ValueError("EXACT_BOOLEAN_FULL_DOMAIN_SUPPORT_REQUIRED")
        if not set(zip(support.asset,support.origin_at)).issubset(set(zip(legal.asset,legal.origin_at))):
            raise ValueError("SOURCE_SUPPORT_WITHOUT_LEGAL_UID_MATURITY_METADATA")
        matrix=support.pivot(index="origin_at",columns="asset",values="qualified").reindex(
            index=origins,columns=inputs.assets).fillna(False).astype(bool)
        counts=matrix.sum().astype(int)
        donors=tuple(a for a in inputs.assets if counts[a]>=60)
        if len(donors)<5:
            raise ValueError("FEWER_THAN_5_METADATA_DONORS_N60")
        donor_input=self._cohort_input(inputs,donors)
        donor_support=support.loc[support.asset.isin(donors)]
        baseline=self._donor_qualification(donor_input,as_of=as_of,support_metadata=donor_support)
        if baseline["origins"] != [o.isoformat() for o in origins]:
            raise ValueError("DONOR_AND_FULL_PARENT_ORIGIN_WINDOW_CONFLICT")
        groups=shr._groups(inputs,cutoff)
        result={**baseline,"schema":"B_R5_KNOWN_CURRENT_UID_N0_METADATA_SUPPORT",
            "assets":list(inputs.assets),"uids":dict(inputs.asset_uids),
            "asset_epochs":dict(current_identity_proof["asset_epochs"]),
            "nominal_n":counts.to_dict(),"structural_n":{a:int(counts[a]//5) for a in inputs.assets},
            "industry_groups":groups,"donors":list(donors),
            "qualified_keys":[[a,o.isoformat()] for o in origins for a in inputs.assets if matrix.loc[o,a]],
            "source_support_sha256":content_hash(matrix),"recipe_sha256":self.recipe_sha256,
            "current_identity_proof_sha256":content_hash({k:current_identity_proof[k] for k in PRIMARY_PROOF_FIELDS}),
            "structural_identity":structural,"n0_prior_only_assets":[a for a in inputs.assets if counts[a]==0],
            "below_native_min10_assets":[a for a in inputs.assets if counts[a]<10],
            "native_min10_cohort":[a for a in inputs.assets if counts[a]>=10],
            "native_min30_cohort":[a for a in inputs.assets if counts[a]>=30],
            "method_block_reasons":{
                "SHR_HP":[],"SHR_CC":[] if baseline["cc_pairs"] else ["CC_NO_METADATA_QUALIFIED_DONOR_PAIRS"],
                "SHR_EB":[] if counts.ge(10).all() else ["NATIVE_EB_MIN10_COHORT_REQUIRED"],
                "SHR_FACTOR":[] if counts.ge(10).all() else ["NATIVE_FACTOR_MIN10_COHORT_REQUIRED"]},
            "observations_created":0,"original_R4_min10_qualification_claim":False}
        result.pop("metadata_proof_sha256",None)
        result["metadata_proof_sha256"]=content_hash(result)
        return result

    def _lineage(self,family,current):
        source=current["source_support_identity"] if family!="FF48_HIERARCHICAL" else current["family_source_support_identity"][family]
        return dict(family=family,method_id=self.recipe["method_ids"][family],
            recipe_sha256=self.recipe_sha256,parent_short_history_sha256=SHORT_SHA,parent_engine_sha256=ENGINE_SHA,
            structural_identity=self._current_lineage(current,source),
            source_support_identity_sha256=content_hash(source),
            asset_uid_epoch_sha256=content_hash(dict(uids=current["asset_uids"],epochs=current["asset_epochs"])))

    @staticmethod
    def _current_lineage(current,source):
        return structural_identity(assets=tuple(current["assets"]),uids=current["asset_uids"],
            epochs=current["asset_epochs"],security_coordinate=current["security_coordinate"],
            source_support_identity=source)

    def _state(self,family,inputs,asof,cutoff,*,current,status,notes,covariance=None,
               coverage=None,uncertainty=None,dependencies=()):
        coverage=copy.deepcopy(coverage or {})
        for a,v in coverage.items():
            v.update(uid=inputs.asset_uids[a],identity_epoch=current["asset_epochs"][a],
                     pooled_identity_epoch=inputs.identity_epoch)
        notes={**notes,"estimator_lineage":self._lineage(family,current),
            "strict_PIT_promotion_eligible":False,"quote_qualified":False,"certified_nav_qualified":False}
        if covariance is not None:
            status="PASS_SYNTHETIC" if inputs.source_receipt.synthetic else "PASS_FROZEN_HISTORY_MECHANISM"
        return self._parent_state(self.recipe["method_ids"][family],inputs,asof,cutoff,status=status,
            notes=notes,covariance=covariance,coverage=coverage,uncertainty=uncertainty,
            dependency_ids=tuple(sorted(set(dependencies))))

    def _native_for(self,family,current):
        def qualification(inputs,*,as_of,support_metadata):
            return self.qualify(inputs,as_of=as_of,support_metadata=support_metadata,current_identity_proof=current)
        def state(method,inputs,asof,cutoff,**kwargs):
            deps=kwargs.pop("dependency_ids",())
            return self._state(family,inputs,asof,cutoff,current=current,dependencies=deps,**kwargs)
        return bind_pinned_kernel(shr.fit_risk,physical_path=shr.__file__,expected_sha256=SHORT_SHA,
            dependencies={"_calendar":event_calendar,"qualify_metadata":qualification,"_state":state,
                "RECIPE":self.recipe,"specification":lambda:copy.deepcopy(self.recipe),"make_cache":self.make_cache})

    def fit_family(self,family,inputs,*,as_of,support_metadata,current_identity_proof,
                   cache=None,budget=None,expected_qualification=None,expected_recipe_sha256=None):
        """Real use requires outer freeze guard plus exact recipe/support pins."""
        if family not in FAMILIES:
            raise ValueError("UNKNOWN_R5_EVENT_RISK_FAMILY")
        asof,cutoff,_=event_calendar(inputs,as_of)
        start=0 if cache is None else len(cache.usage_log)
        try:
            self._current(inputs,current_identity_proof)
            if not inputs.source_receipt.synthetic and (expected_recipe_sha256!=self.recipe_sha256
                    or expected_qualification is None):
                raise ValueError("R5_RECIPE_AND_METADATA_FREEZE_REQUIRED_BEFORE_REAL_FIT")
            self._family_support(inputs,family,current_identity_proof,cutoff)
            proof=self.qualify(inputs,as_of=asof,support_metadata=support_metadata,current_identity_proof=current_identity_proof)
            if expected_qualification is not None and proof!=expected_qualification:
                raise ValueError("FROZEN_R5_METADATA_QUALIFICATION_CHANGED")
            if family=="TAIL_CVAR":
                raise ValueError(self.recipe["tail_CVaR"])
            if cache is None:
                cache=self.make_cache(inputs,as_of=asof,budget=budget)
                start=len(cache.usage_log)
            mode_inputs=self._mode_input(inputs)
            if family in {"SHR_HP","SHR_CC"}:
                native=self._native_for(family,current_identity_proof)
                return native(family,mode_inputs,as_of=asof,support_metadata=support_metadata,cache=cache,
                              expected_qualification=proof)
            hp=self._native_for("SHR_HP",current_identity_proof)("SHR_HP",mode_inputs,as_of=asof,
                support_metadata=support_metadata,cache=cache,expected_qualification=proof)
            if hp.covariance is None:
                raise ValueError("FULL_HP_PRIOR_DEPENDENCY_BLOCKED:"+str(hp.notes.get("block_reason")))
            minimum=10 if family in {"SHR_EB","SHR_FACTOR"} else 30
            assets=tuple(a for a in inputs.assets if proof["nominal_n"][a]>=minimum)
            if not assets:
                raise ValueError("NO_NATIVE_METADATA_QUALIFIED_COHORT")
            cohort=self._cohort_input(inputs,assets)
            cohort_current=self._cohort_identity(current_identity_proof,assets)
            subset_cache=cache.bind(**shr._context(cohort,cutoff))
            subset_support=support_metadata.loc[support_metadata.asset.isin(assets)].copy()
            native_state=None
            native_dependencies=()
            if family in {"SHR_EB","SHR_FACTOR"}:
                native_state=self._native_for(family,cohort_current)(family,self._mode_input(cohort),
                    as_of=asof,support_metadata=subset_support,cache=subset_cache)
                covariance=None if native_state.covariance is None else native_state.covariance
                native_dependencies=native_state.fit_dependency_ids
            elif family in CLASSIC:
                sessions=event_calendar(cohort,asof)[2]
                selected=cohort.observations.loc[cohort.observations.origin_at.map(engine._time).isin(pd.DatetimeIndex(proof["origins"]))]
                frame=engine._panel(selected,assets,cohort.asset_uids,cohort.identity_epoch,
                    cohort.source_receipt,sessions,cutoff,5).reindex(index=pd.DatetimeIndex(proof["origins"]),columns=assets)
                qualified=set((a,pd.Timestamp(o)) for a,o in proof["qualified_keys"])
                mask=pd.DataFrame([[(a,o) in qualified for a in assets] for o in frame.index],index=frame.index,columns=assets)
                if not np.isfinite(frame.to_numpy(float)[mask.to_numpy(bool)]).all():
                    raise ValueError("NONFINITE_REQUIRED_COHORT_SOURCE_NO_REMOVAL")
                frame=frame.where(mask)
                bundle=engine.SharedRiskEngine._primitive(subset_cache,CLASSIC[family],frame)
                covariance=bundle.covariance
            else:
                worker=engine.SharedRiskEngine(budget=cache.budget);worker.cache=subset_cache
                native_state=self._engine_fit(worker,EXTENSIONS[family],cohort,as_of=asof)
                covariance=None if native_state.covariance is None else native_state.covariance
                native_dependencies=native_state.fit_dependency_ids
            if covariance is None:
                raise ValueError("NATIVE_COHORT_BLOCKED:"+str(None if native_state is None else native_state.notes.get("block_reason")))
            positions=tuple(inputs.assets.index(a) for a in assets)
            completed,completion=cache.learn("deterministic_transform","R5:conditional_completion:"+family,
                (hp.covariance,covariance,positions),lambda:conditional_prior_completion(hp.covariance,covariance,positions),
                parameters={"recipe_sha256":self.recipe_sha256,"family":family})
            if not np.isfinite(np.linalg.cond(completed)) or np.linalg.cond(completed)>1e12:
                raise ValueError("ILL_CONDITIONED_R5_COMPLETED_COVARIANCE")
            coverage=copy.deepcopy(hp.coverage)
            for a in inputs.assets:
                coverage[a].update(native_estimator_qualified=a in assets,native_estimator_minimum_n=minimum,
                    n0_prior_only=proof["nominal_n"][a]==0,observations_fabricated=False)
            dependencies=set(hp.fit_dependency_ids)|set(native_dependencies)|set(shr._closure(cache,cache.usage_log[start:]))
            return self._state(family,inputs,asof,cutoff,current=current_identity_proof,status="PASS",
                covariance=completed,coverage=coverage,dependencies=dependencies,
                notes={"metadata_proof":proof,"recipe":copy.deepcopy(self.recipe),"completion":completion,
                    "native_cohort_assets":list(assets),"native_parent_minimum_n":minimum,
                    "native_cohort_state_id":None if native_state is None else native_state.risk_state_id,
                    "full_HP_prior_state_id":hp.risk_state_id,"new_scientific_descendant":True,
                    "original_native_full_domain_qualification_claim":False})
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError) as error:
            # Unknown current identity cannot produce an admitted prior or state.
            safe=current_identity_proof if isinstance(current_identity_proof,dict) else {}
            try:
                if not {"assets","asset_uids","asset_epochs","security_coordinate","source_support_identity"}.issubset(safe):
                    raise ValueError("CURRENT_IDENTITY_BLOCK_BEFORE_STATE_CONSTRUCTION")
                return self._state(family,inputs,asof,cutoff,current=safe,status="BLOCKED",
                    notes={"block_reason":str(error)},dependencies=() if cache is None else shr._closure(cache,cache.usage_log[start:]))
            except (ValueError,KeyError,TypeError):
                # Typed native block retains full requested assets even if identity is unknown.
                return self._parent_state(self.recipe["method_ids"][family],inputs,asof,cutoff,status="BLOCKED",
                    notes={"block_reason":str(error),"strict_PIT_promotion_eligible":False,
                        "new_scientific_descendant":True},dependency_ids=())
