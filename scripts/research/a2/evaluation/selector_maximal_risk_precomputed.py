"""Read only C14 published summaries; never recompute or reselect old history.

The original incremental owner lacks an artifact reader. This module supplies
only that custody boundary. collect_published_legacy returns an exact projection
for a runner to persist; load_precomputed subsequently requires that artifact
to be independently included in a PASS source review. No writer lives here.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pyarrow.parquet as pq

from scripts.research.a2.data import selector_maximal_risk_binding as binding
from scripts.research.a2.evaluation import selector_maximal_risk_incremental as incremental

owner = incremental.owner
need = owner._require
ID = owner.RESEARCH_ID
RUN = binding.RUN
DESIGN_SHA = binding.DESIGN_SHA
OLD_ML_GATE_SHA = "7d68b43b9ee7d63b35f80fa8515f19dc007a167c5e7eba53e2dcde905be52fed"
ROOTS = (Path("D:/us-tech-quant-backtests"), Path("D:/us-tech-quant-results"))
LEGACY_SCHEMA = "C14_EXACT_PUBLISHED_LEGACY_SUMMARIES_V1"
FIELDS = ("pooled_edge", "bootstrap_se", "year_edges")
COLLECTIONS = ("tests", "candidates", "fixed_mechanism_contrasts")
BASE = Path("D:/us-tech-quant-backtests/V24")

# These are immutable publication identities, not newly accepted experiments.
# Publication SHA pins below were discovered from the already exposed chain;
# each must also appear in the independently signed-off runtime source review.
CHAIN = (
    ("C12", "20261003T184731+0000_4ad5a591", "d9fa7c34eae12a407152f94cd4ca75268be5c587cbf623b6663d506df43e737f", "c668e05881921e1fd4db5e98a282f61a9446a646c9ac0e8f0221f084c6031d9a"),
    ("C11", "20261003T173443+0000_ed37eea6", "3a9e24914e7329da83e9d768cdd584519f75607c6e1793d0e92fabacb5edf70d", "f4b7280c9e6ea823b2cd3afd2e5b31c88d33dcc20121e0b85fbc5bd88b4316a2"),
    ("C10", "20261003T123028+0000_156d33ee", "1baa80121cead1856515310fa06ab86083b432a6de73c53d4020c4999bb264ec", "0c05656c2660e620c0bca40eb67f9d33567ddbc29d028228ebc3d6f4802a63fb"),
    ("HORIZON", "20261003T092314+0000_4d0ba1cd", "cf7c9d403b07aaf1940aee626d6de7c4fdbc87bf45d52d2a87b315101b8db50f", "7759112ac061ad250d9022666f96531da8096ea56995ab026cf19e9f0482563a"),
    ("C5", "20261003T063407+0000_92021749", "a55f9e0eabefcf51cd599382da4b2dfc4d7be6548442029487233ab357654c47", "febddb4132ca9c3e9697015a92935a1aaf18b2b78bb254a193f4f3583a8f2205"),
    ("R4", "20261002T195155+0000_fef68b59", "f22b8d93299ba34521aa9ec1b836a49828f15e08f6c9a467227c9d02150bb070", "e5347bd0ce395c322a8c75c537584c60fb8b8ecc54eee234603d5664903a6d92"),
    ("R2", "20261001T171645+0000_d9382ce0", "1d810db4724454f7769b21b55441590c9a7fb07a86d128b044c2b3aa65952c9d", "e353c846c532cf22bd8a4b7c91c66891c628937842ef3d70a8162aeaf4884d53"),
)
C14_EVIDENCE = dict(path=str(RUN/"diagnostics/selector_evidence/SELECTION_EVIDENCE.json"),
    sha256="807bbdbacf9f0a26ac9b066e19331ffd61baad5b2ec1384dd567c33368dc1028")
C14_MAXIMA = dict(path=str(RUN/"diagnostics/selector_evidence/BOOTSTRAP_MAXT.parquet"),
    sha256="6d15273dcb118136c249945c150b7dd39667448b265e3f187ce6bfb89f07f505")
CLOCK = dict(path=str(BASE/CHAIN[0][1]/"diagnostics/selector_evidence/COMMON_DATE_MATURITY.parquet"),
    sha256="78d9a14347dfcb961c2fb24e782fc506f8ab1b845945a71304a243ff6225866a")


def chain_refs():
    return {name: dict(design=dict(path=str(BASE/run/"DESIGN_FREEZE.json"),sha256=dsha),
        evidence=dict(path=str(BASE/run/"diagnostics/selector_evidence/SELECTION_EVIDENCE.json"),sha256=esha))
        for name,run,dsha,esha in CHAIN}


def required_source_pins():
    """Discovery only: the independent review must separately approve these."""
    modules = (sys.modules[__name__], binding, incremental, owner, owner.shared,
               owner.prior, owner.risk_metrics, owner.pairs_owner)
    return {str(Path(m.__file__).resolve()):binding.sha(m.__file__) for m in modules}


def _pin(ref, *, root=None):
    need(isinstance(ref,dict) and set(ref)=={"path","sha256"} and owner._sha(ref.get("sha256")),
         "EXACT_PUBLISHED_ARTIFACT_REF_REQUIRED")
    path=Path(ref["path"])
    need(path.is_absolute() and path.drive.upper()=="D:" and ".." not in path.parts
         and any(path.resolve().is_relative_to(r.resolve()) for r in ROOTS),
         "EXTERNAL_PUBLISHED_ARTIFACT_CUSTODY_REQUIRED")
    need(root is None or path.resolve().is_relative_to(Path(root).resolve()),"C14_RUN_OWNED_REVIEW_REQUIRED")
    need(binding.sha(path)==ref["sha256"],"PUBLISHED_ARTIFACT_PHYSICAL_SHA_CHANGED:"+path.name)
    return path


def _json(ref, *, root=None):
    return json.loads(_pin(ref,root=root).read_text(encoding="utf-8"))


def _same_ref(a,b):
    return isinstance(a,dict) and isinstance(b,dict) and set(a)==set(b)=={"path","sha256"} \
        and Path(a["path"]).resolve()==Path(b["path"]).resolve() and a["sha256"]==b["sha256"]


def _admit(design_ref, review_ref, legacy_summary_ref=None):
    review=_json(review_ref,root=RUN)
    need(review.get("status")=="PASS" and review.get("research_id")==ID,
         "INDEPENDENT_PRECOMPUTED_SOURCE_REVIEW_REQUIRED")
    pins=review.get("source_pins",{})
    need(all(pins.get(p)==h for p,h in required_source_pins().items()),
         "COMPLETE_PHYSICAL_PRECOMPUTED_SOURCE_REVIEW_REQUIRED")
    for p,h in pins.items():
        path=Path(p)
        need(path.is_absolute() and path.resolve().is_relative_to(Path(__file__).resolve().parents[4])
             and path.suffix==".py" and binding.sha(path)==h,"PRECOMPUTED_SOURCE_CLOSURE_CHANGED")
    need(_same_ref(design_ref,dict(path=str(RUN/"DESIGN_FREEZE.json"),sha256=DESIGN_SHA)),
         "ORIGINAL_C14_PRECOMPUTED_DESIGN_REQUIRED")
    refs=chain_refs()
    wanted={"c14_evidence":C14_EVIDENCE,"c14_maxima":C14_MAXIMA,"clock":CLOCK}
    for name,pair in refs.items():
        wanted[name+"_design"]=pair["design"]; wanted[name+"_evidence"]=pair["evidence"]
    if legacy_summary_ref is not None:
        _pin(legacy_summary_ref,root=RUN)
        wanted["legacy_summaries"]=legacy_summary_ref
    reviewed=review.get("artifact_refs",{})
    need(all(_same_ref(reviewed.get(k),v) for k,v in wanted.items()),
         "INDEPENDENT_EXACT_PUBLISHED_ARTIFACT_REVIEW_REQUIRED")
    # All physical pins are checked before any old outcome/statistical row.
    for ref in wanted.values(): _pin(ref)
    design=_json(design_ref,root=RUN)
    ev=owner.validate_design(design)
    frozen=(owner,owner.shared,owner.prior,owner.risk_metrics,owner.pairs_owner)
    need(all(design["sources"].get(str(Path(m.__file__).resolve()))==
             pins.get(str(Path(m.__file__).resolve()))==binding.sha(m.__file__) for m in frozen),
         "FROZEN_EVIDENCE_DEPENDENCY_SOURCE_CHANGED")
    need(_same_ref(ev["legacy"]["old_design"],refs["C12"]["design"])
         and _same_ref(ev["legacy"]["evidence"],refs["C12"]["evidence"])
         and _same_ref(ev["legacy"]["clock"],CLOCK),"ORIGINAL_PARENT_LEGACY_CUSTODY_REQUIRED")
    return design,review,refs


def _published_rows(design,refs):
    ids=design["evaluation"]["legacy"]["numeric_ids"]
    found={}; parents=[]
    for i,(name,*_) in enumerate(CHAIN):
        pair=refs[name]; ancestor=_json(pair["design"]); doc=_json(pair["evidence"])
        need(doc.get("design_freeze_sha256")==pair["design"]["sha256"],
             "PUBLISHED_EVIDENCE_DESIGN_PIN_CHANGED:"+name)
        need(doc.get("common_mature_dates",doc.get("common_mature_date_count"))==732
             and doc.get("common_year_dates",doc.get("year_counts"))==owner.YEAR_COUNTS,
             "PUBLISHED_FULL732_YEAR_CLOCK_REQUIRED:"+name)
        need(all(doc.get(k,0)==0 for k in ("test2026_rows_read","test2026_rows_read_by_this_runner",
             "fit2026_rows","evaluation2026_rows","outcome2026_reads","new2026_state_estimations")),
             "PUBLISHED_2026_COUNTER_MUST_REMAIN_ZERO:"+name)
        need(doc.get("economic_promotion_allowed",False) is False
             and doc.get("strict_PIT_promotion_eligible",False) is False,
             "PUBLISHED_HISTORY_IS_NOT_PROMOTABLE:"+name)
        if i+1<len(CHAIN):
            target=refs[CHAIN[i+1][0]]; legacy=ancestor["evaluation"]["legacy"]
            need(_same_ref(legacy.get("design"),target["design"]),
                 "FROZEN_ANCESTOR_DESIGN_CHAIN_CHANGED:"+name)
            if "evidence" in legacy:
                need(_same_ref(legacy["evidence"],target["evidence"]),
                     "FROZEN_ANCESTOR_EVIDENCE_CHAIN_CHANGED:"+name)
        local={}
        for collection in COLLECTIONS:
            rows=doc.get(collection,[])
            need(isinstance(rows,list),"PUBLISHED_ROW_COLLECTION_REQUIRED:"+name)
            for index,row in enumerate(rows):
                need(isinstance(row,dict),"PUBLISHED_ROW_OBJECT_REQUIRED:"+name)
                cid=row.get("test_id",row.get("candidate_id"))
                if cid not in ids: continue
                absent="status" not in row
                if absent:
                    need(name=="R4" and doc.get("schema")=="C_FROZEN_HISTORY_SELECTION_EVIDENCE_V1"
                         and doc.get("status")=="MECHANISM_EVIDENCE_COMPLETE"
                         and not doc.get("failed_or_untestable") and not doc.get("failed_contrasts"),
                         "NO_IMPLICIT_COMPLETE_OUTSIDE_EXACT_R4_PUBLICATION:"+str(cid))
                elif row["status"]!="COMPLETE":
                    continue
                values={k:deepcopy(row.get(k)) for k in FIELDS}
                mean,se,years=(values[k] for k in FIELDS)
                need(incremental._finite(mean) and incremental._finite(se) and se>=0
                     and isinstance(years,dict) and set(years)=={"2023","2024","2025"}
                     and all(incremental._finite(v) for v in years.values()),
                     "MISSING_FINITE_PUBLISHED_MEAN_SE_YEAR:"+str(cid))
                origin=dict(evidence_ref=deepcopy(pair["evidence"]),collection=collection,row_index=index,
                    id_field="test_id" if "test_id" in row else "candidate_id",
                    original_status="ABSENT_NATIVE_R4_SCHEMA" if absent else row["status"])
                if cid in local:
                    need(local[cid]["values"]==values,"CONFLICTING_DUPLICATE_PUBLISHED_SUMMARY:"+str(cid))
                    local[cid]["provenance"].append(origin)
                else: local[cid]=dict(values=values,provenance=[origin])
        for cid,entry in local.items():
            need(cid not in found,"CROSS_PUBLICATION_LEGACY_ID_COLLISION:"+cid)
            found[cid]=dict(candidate_id=cid,status="COMPLETE",**entry["values"],provenance=entry["provenance"])
        parents.append(dict(name=name,**deepcopy(pair)))
    missing=[cid for cid in ids if cid not in found]
    need(not missing,"MISSING_PUBLISHED_LEGACY_SUMMARIES:"+",".join(missing))
    return dict(schema=LEGACY_SCHEMA,research_id=ID,legacy_ids=list(ids),
        summaries=[found[cid] for cid in ids],published_sources=parents,
        old_statistics_recomputed=False,old_bootstrap_calls=0,legacy_reselected=False,
        independent_holdout=False,strict_PIT_promotion_eligible=False)


def collect_published_legacy(design_ref,source_review_ref):
    """Return only original published scalars/provenance, never an execution grant."""
    design,_,refs=_admit(design_ref,source_review_ref)
    return _published_rows(design,refs)


def _project(ref,columns):
    path=_pin(ref)
    table=pq.read_table(path,columns=list(columns))
    need(table.column_names==list(columns),"EXACT_PUBLISHED_COLUMN_PROJECTION_REQUIRED")
    _pin(ref)
    return table.to_pandas()


def load_precomputed(design_ref,source_review_ref,legacy_summary_ref):
    """Load after independent source/artifact review; return payload, clock, receipt.

    The runner persists collect_published_legacy's result under this run and gets
    the independent review to pin that exact file before calling this function.
    No edge, label, candidate prediction, fitting, solver or bootstrap is read.
    """
    design,review,refs=_admit(design_ref,source_review_ref,legacy_summary_ref)
    expected=_published_rows(design,refs)
    published=_json(legacy_summary_ref,root=RUN)
    need(published==expected,"LEGACY_SUMMARY_ARTIFACT_MUST_EQUAL_EXACT_PUBLISHED_PROJECTION")
    evidence=_json(C14_EVIDENCE)
    need(evidence.get("research_id")==ID and evidence.get("strict_PIT_promotion_eligible") is False
         and evidence.get("independent_holdout") is False and evidence.get("2026_locked") is True
         and evidence.get("new2026_reads")==0
         and _same_ref(evidence.get("design"),design_ref)
         and _same_ref(evidence.get("final_pipeline"),dict(path=str(RUN/"FINAL_PIPELINES_FREEZE.json"),
             sha256=OLD_ML_GATE_SHA)),"EXACT_ORIGINAL_C14_PUBLISHED_EVIDENCE_REQUIRED")
    maxref=evidence.get("diagnostics",{}).get("BOOTSTRAP_MAXT",{})
    need(maxref.get("rows")==5000 and _same_ref({k:maxref.get(k) for k in ("path","sha256")},C14_MAXIMA),
         "ORIGINAL_C14_MAX5000_PUBLICATION_PIN_REQUIRED")
    clock=_project(CLOCK,("signal_date","included"))
    owner._clock(clock)
    maxima=_project(C14_MAXIMA,("max_t",))
    need(len(maxima)==5000,"ALL_ORIGINAL5000_MAXIMA_REQUIRED")
    bootstrap=deepcopy(evidence["bootstrap"])
    need(owner._sha(bootstrap.get("shared_draw_sha256")) and
         bootstrap["shared_draw_sha256"]==bootstrap.get("legacy_shared_draw_sha256"),
         "ORIGINAL_SHARED_DRAW_RECEIPT_REQUIRED")
    payload=dict(schema=incremental.SCHEMA,research_id=ID,strict_PIT_promotion_eligible=False,
        clock_sha256=incremental.content_hash(clock),legacy_ids=expected["legacy_ids"],
        legacy_summaries=deepcopy(published["summaries"]),summaries=deepcopy(evidence["tests"]),
        bootstrap=bootstrap,maxima=maxima.max_t.to_numpy(float),
        source_custody=dict(status="PHYSICAL_FROZEN_EVIDENCE_VERIFIED",physical_sha256_verified=True,
            artifact_refs=dict(c14_evidence=deepcopy(C14_EVIDENCE),c14_maxima=deepcopy(C14_MAXIMA),
                legacy_summaries=deepcopy(legacy_summary_ref))))
    digest=incremental.content_hash(payload)
    ev=design["evaluation"]
    incremental._precomputed(payload,digest,clock,owner.bootstrap_rule(ev["bootstrap"]),
        ev["legacy"]["numeric_ids"],ev["new_specs"])
    # Recheck custody after projections; a replacement during the read is blocked.
    _admit(design_ref,source_review_ref,legacy_summary_ref)
    receipt=dict(status="PASS",research_id=ID,schema="C14_PUBLISHED_PRECOMPUTED_CUSTODY_V1",
        expected_precomputed_sha256=digest,source_review_ref=deepcopy(source_review_ref),
        artifact_refs=deepcopy(payload["source_custody"]["artifact_refs"]),clock_ref=deepcopy(CLOCK),
        legacy_published_count=147,c14_summary_count=75,original_maxima_count=5000,
        old_statistics_recomputed=False,old147_bootstrap_calls=0,old_ml_bootstrap_calls=0,
        legacy_reselected=False,test2026_rows_read=0,independent_holdout=False,
        strict_PIT_promotion_eligible=False)
    return payload,clock,receipt

