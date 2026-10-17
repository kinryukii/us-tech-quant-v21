"""Real cache-object release and candidate source scoping; entirely synthetic."""
from copy import deepcopy
import gc
from pathlib import Path
import unittest
import weakref
from unittest.mock import Mock, patch

from moomoo_component.cohort import Cohort
from moomoo_component.applied_source import _CanonicalSource
from scripts.research.a2.portfolio import selected_hgb
from test_applied_source import PlanTests, modules, application, package, report, state, SIGNAL, NOW

R7="R7_GROSS_LINEAR"
RIDGE="R10_DIRECT_H5_RIDGE_MID"
SCOPE="PAPER_CANDIDATE_REFS_V1"

class Heavy:
    pass

class HeavyDict(dict):
    pass

class WorkerReleaseTests(unittest.TestCase):
    def test_owner_release_drops_actual_strong_references_and_scopes_other_root(self):
        before=dict(selected_hgb._RUNTIME)
        selected_hgb._RUNTIME.clear()
        try:
            first,second=Heavy(),Heavy()
            a,b=weakref.ref(first),weakref.ref(second)
            root=Path("D:/us-tech-quant-cache/synthetic_hgb_release/a").resolve()
            other=Path("D:/us-tech-quant-cache/synthetic_hgb_release/b").resolve()
            selected_hgb._RUNTIME[str(root)]={"model":first}
            selected_hgb._RUNTIME[str(other)]={"model":second}
            del first,second
            self.assertEqual(selected_hgb.release_runtime(source_root=root),1)
            gc.collect()
            self.assertIsNone(a())
            self.assertIsNotNone(b())
            self.assertEqual(selected_hgb.release_runtime(),1)
            gc.collect()
            self.assertIsNone(b())
            self.assertEqual(selected_hgb.release_runtime(),0)
        finally:
            selected_hgb._RUNTIME.clear();selected_hgb._RUNTIME.update(before)

    def test_all_legacy_objects_are_released_before_new_stage_even_after_inference_failure(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                source=PlanTests.backend(self)
                # Mock.call_args would itself retain the heavy report object.
                source._identities=lambda report:{"T"+str(i):str(i) for i in range(1,41)}
                source._closes=lambda *args:{"US.T1":20,"US.T2":50}
                tracked=[]
                def bundle(full=False):
                    values=(HeavyDict(report()),HeavyDict(package()),Heavy())
                    tracked.extend(weakref.ref(x) for x in values)
                    return values
                source._bundle=bundle
                def infer(*args,**kwargs):
                    model,q10,risk=Heavy(),Heavy(),Heavy()
                    tracked.extend(weakref.ref(x) for x in (model,q10,risk))
                    selected_hgb._RUNTIME["synthetic_worker"]={"model":model,"q10":q10,"risk":risk}
                    if fail:raise ValueError("synthetic inference failure")
                    return {"HGB_DIAG_5":application()}
                def new_stage(result,states,now):
                    self.assertFalse(selected_hgb._RUNTIME)
                    self.assertTrue(tracked)
                    self.assertTrue(all(ref() is None for ref in tracked))
                    return result
                source._new_plans=new_stage
                with modules({"scripts.research.a2.portfolio.selected_hgb":{
                        "infer_targets":infer,"release_runtime":selected_hgb.release_runtime}}):
                    result=source.load({"HGB_DIAG_5":state({"T1":.2},.8)},NOW)
                self.assertEqual(bool(result["plans"]),not fail)

    def test_existing_package_reader_cache_is_cleared_before_new_stage(self):
        from functools import lru_cache
        from apps.demo_console.adapters import selected_strategies_reader as reader
        source=PlanTests.backend(self)
        source._identities=lambda report:{"T"+str(i):str(i) for i in range(1,41)}
        refs=[]
        @lru_cache(maxsize=1)
        def decode(raw):
            item=HeavyDict(package());refs.append(weakref.ref(item));return item
        source._bundle=lambda full=False:(report(),decode(b"synthetic-package"),object())
        def next_stage(result,states,now):
            self.assertEqual(decode.cache_info().currsize,0)
            self.assertTrue(all(ref() is None for ref in refs))
            return result
        source._new_plans=next_stage
        with patch.object(reader,"_decode",decode), modules({"scripts.research.a2.portfolio.selected_hgb":{
                "infer_targets":Mock(side_effect=AssertionError("cash target needs no model")),
                "release_runtime":selected_hgb.release_runtime}}):
            source.load({"HGB_DIAG_5":state()},NOW)

class CandidateSourceScopeTests(unittest.TestCase):
    def data(self):
        return {"signal_date":SIGNAL,"candidate_source_scope":SCOPE,
            "strategy_status":{R7:{"status":"READY","signal_date":SIGNAL},RIDGE:{"status":"BLOCKED","reason":"missing own input","signal_date":SIGNAL}},
            "source_refs":{"frozen_calendar":{"path":"calendar","sha256":"a"*64},
                R7+"/consensus/publication":{"path":"publication","sha256":"b"*64},
                R7+"/model/R7_GROSS_LINEAR":{"path":"model","sha256":"c"*64}}}

    def test_new_immutable_scope_matches_without_unrelated_legacy_keys_or_peer_gap(self):
        data=self.data();before=deepcopy(data)
        scoped=Cohort._book_source_data(R7,data)
        self.assertEqual(set(scoped["source_refs"]),{"consensus/publication","model/R7_GROSS_LINEAR"})
        frozen=deepcopy(scoped["source_refs"])
        self.assertEqual(Cohort._match_source_refs(frozen,scoped,"changed"),frozen)
        self.assertEqual(data,before)
        legacy=Cohort._book_source_data("HGB_DIAG_5",data)
        self.assertEqual(set(legacy["source_refs"]),{"frozen_calendar"})
        with self.assertRaisesRegex(ValueError,"missing own input"):
            Cohort._book_source_data(RIDGE,data)

    def test_real_publication_or_model_hash_changes_still_fail(self):
        for key in ("consensus/publication","model/R7_GROSS_LINEAR"):
            data=self.data();frozen=deepcopy(Cohort._book_source_data(R7,data)["source_refs"])
            data["source_refs"][R7+"/"+key]["sha256"]="d"*64
            with self.assertRaisesRegex(ValueError,"changed"):
                Cohort._match_source_refs(frozen,Cohort._book_source_data(R7,data),"changed")

    def test_missing_ready_proof_or_wrong_signal_is_rejected(self):
        for case in ("missing_refs","blocked","wrong_signal"):
            data=self.data()
            if case=="missing_refs":data["source_refs"]={"frozen_calendar":{"path":"calendar","sha256":"a"*64}}
            if case=="blocked":data["strategy_status"][R7]["status"]="BLOCKED"
            if case=="wrong_signal":data["strategy_status"][R7]["signal_date"]="2026-09-24"
            with self.assertRaises(ValueError):Cohort._book_source_data(R7,data)

    def test_canonical_metadata_calls_only_lightweight_proof_owner(self):
        source=_CanonicalSource.__new__(_CanonicalSource);source.paths=object()
        owner=Mock();owner.NEW_IDS=(R7,RIDGE)
        owner.load_publication.return_value=({"signal_date":SIGNAL},{"path":"publication","sha256":"a"*64})
        owner.candidate_source_refs.side_effect=lambda paths,sid,doc,ref,**kw:({"consensus/publication":ref} if sid==R7 else (_ for _ in ()).throw(ValueError("missing own input")))
        with modules({"scripts.research.a2.inference.consensus_paper":{
                "NEW_IDS":owner.NEW_IDS,"load_publication":owner.load_publication,"candidate_source_refs":owner.candidate_source_refs}}):
            result=source._candidate_status_refs({"signal_date":SIGNAL,"source_refs":{}},NOW)
        self.assertEqual(result["strategy_status"][R7]["status"],"READY")
        self.assertEqual(result["strategy_status"][RIDGE]["status"],"BLOCKED")
        self.assertEqual(set(result["source_refs"]),{R7+"/consensus/publication"})
        self.assertEqual(owner.load_publication.call_count,1)

if __name__=="__main__":unittest.main()
