"""Metadata-only per-candidate source checks; no fitted objects are decoded."""
import unittest
from unittest.mock import patch
from scripts.research.a2.inference import consensus_paper as owner


class CandidateSourceRefsTests(unittest.TestCase):
    def fixture(self):
        doc=dict(signal_date="2026-10-12",strategy_status={sid:{"status":"READY"} for sid in owner.NEW_IDS},
                 flags_ref={"path":"flags","sha256":"f"},source_bundle_ref={"path":"pool","sha256":"p"},
                 input_refs={"current":{"path":"current","sha256":"c"},"ENTRY":{"path":"entry","sha256":"e"},"INCUMBENT":{"path":"incumbent","sha256":"i"},"GROSS":{"path":"gross","sha256":"g"}})
        return doc,{"path":"publication","sha256":"u"}

    def test_r7_current_refs_match_frozen_plan_without_loading_model(self):
        doc,ref=self.fixture();model={"path":"model","sha256":"m"};verified=[]
        with patch.object(owner,"load_publication",return_value=(doc,ref)),patch.object(owner,"frozen_states",return_value={"R7_GROSS_LINEAR":{"model_ref":model}}),patch.object(owner,"verify",side_effect=lambda ref:verified.append(ref)):
            result=owner.candidate_source_refs(None,owner.NEW_IDS[2],doc,ref,as_of="2026-10-13T12:00:00Z")
        self.assertEqual(result["model/R7_GROSS_LINEAR"],model)
        self.assertEqual(result["consensus/publication"],ref)
        self.assertEqual(set(doc["input_refs"])-set(result),set())
        self.assertEqual(len(verified),len(result))
        self.assertFalse(any(key.startswith("RAW_A2/") for key in result))

    def test_r10_refs_cover_exact_two_heads_and_shared_scalers(self):
        doc,ref=self.fixture();states={}
        for group in ("ENTRY","INCUMBENT"):
            key="ACTION_VALUE_"+group+"_MEAN4_ELASTICNET_MID"
            states[key]={"model_ref":{"path":key,"sha256":"m"},"metadata_row":{"group":group},"state_type":"new_model"}
            key="SCALER_ACTION_VALUE_"+group+"_MEAN4"
            states[key]={"model_ref":{"path":key,"sha256":"s"},"metadata_row":{"group":group},"state_type":"new_scaler"}
        with patch.object(owner,"load_publication",return_value=(doc,ref)),patch.object(owner,"frozen_states",return_value=states),patch.object(owner,"verify"):
            result=owner.candidate_source_refs(None,owner.NEW_IDS[0],doc,ref)
        self.assertEqual(len([key for key in result if key.startswith("model/")]),4)
        self.assertIn("model/ENTRY_SCALER",result)
        self.assertIn("model/INCUMBENT_SCALER",result)

    def test_changed_current_publication_blocks_before_closure_access(self):
        doc,ref=self.fixture()
        with patch.object(owner,"load_publication",return_value=(dict(doc,signal_date="2026-10-09"),ref)),patch.object(owner,"frozen_states",side_effect=AssertionError("closure was accessed")):
            with self.assertRaisesRegex(ValueError,"PUBLICATION_CHANGED"):
                owner.candidate_source_refs(None,owner.NEW_IDS[2],doc,ref)


    def test_duration_real_plan_and_status_share_complete_frozen_identity(self):
        from copy import deepcopy
        from datetime import datetime, timezone
        from pathlib import Path
        from types import SimpleNamespace
        import pandas as pd
        from moomoo_component.applied_source import _CanonicalSource
        from moomoo_component.cohort import Cohort
        sid = "R6_DURATION_TREE"
        def ref(name): return {"path": name, "sha256": name.encode().hex().ljust(64, "0")[:64]}
        member = dict(model_ref=ref("model"), receipt_ref=ref("receipt"),
            r6_contract_ref=ref("contract"), closure_ref=ref("closure"))
        doc = dict(signal_date="2025-12-30", strategy_status={sid: {"status": "READY"}},
            flags_ref=ref("flags"), source_bundle_ref=ref("pool"),
            input_refs={"current": ref("current"), "R6_DURATION": ref("duration")},
            base_publication_ref=ref("base"), duration_publication_ref=ref("publication"),
            duration_qualification_ref=ref("qualification"),
            r6_probe_source=dict(probe_ref=ref("probe"), qualification_ref=ref("probe-proof")))
        pub = doc["duration_publication_ref"]
        frame = pd.DataFrame([dict(signal_date=pd.Timestamp(doc["signal_date"]), ticker="T%02d" % j,
            security_id="S%02d" % j, is_raw_top20=True, raw_a2_rank=j+1, raw_a2_prediction=.2-j*.001,
            feature_available=True, new_buy_eligible=True) for j in range(20)])
        state = dict(signal_date=doc["signal_date"], valuation_basis="SIGNAL_CLOSE",
            weights={}, units={}, security_ids={}, cash_weight=1.)
        source = _CanonicalSource.__new__(_CanonicalSource)
        source.paths, source.close_hours = SimpleNamespace(), {}
        source._calendar = lambda now: (None, [])
        now = datetime(2025, 12, 31, 12, tzinfo=timezone.utc)
        verified = []
        with patch.object(owner, "load_publication", return_value=(doc, pub)), \
                patch.object(owner, "frozen_states", return_value={"duration_tree_2025": member}), \
                patch.object(owner, "verify", side_effect=lambda value: verified.append(value) or Path("synthetic")), \
                patch.object(owner, "duration_actions", return_value=([], {"duration_tree_2025": member["model_ref"]})), \
                patch.object(owner, "_qualified_duration_frame", return_value=frame), \
                patch.object(pd, "read_parquet", return_value=frame), \
                patch("moomoo_component.applied_source._clock_status", return_value={}), \
                patch("joblib.load", side_effect=AssertionError("no real model IO")):
            loaded = source._new_plans(dict(signal_date=doc["signal_date"], execution_date="2025-12-31"),
                {sid: state}, now)
            self.assertEqual(loaded["strategy_status"][sid]["status"], "READY", loaded)
            frozen = loaded["plans"][sid]["source_refs"]
            current = owner.candidate_source_refs(source.paths, sid, doc, pub, as_of=now.isoformat())
        self.assertEqual(current, frozen)
        self.assertEqual(len(frozen), 14)
        self.assertEqual(loaded["plans"][sid]["model_refs"], {"duration_tree_2025": member["model_ref"]})
        self.assertTrue(all(item in verified for item in frozen.values()))
        status = dict(signal_date=doc["signal_date"], candidate_source_scope="PAPER_CANDIDATE_REFS_V1",
            strategy_status=loaded["strategy_status"], source_refs={sid+"/"+key: value for key,value in current.items()})
        self.assertEqual(Cohort._match_source_refs(frozen, Cohort._book_source_data(sid,status), "changed"), frozen)
        for key in current:
            changed = deepcopy(status)
            changed["source_refs"][sid+"/"+key]["sha256"] = "0"*64
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "changed"):
                Cohort._match_source_refs(frozen, Cohort._book_source_data(sid,changed), "changed")
        for key in ("model_receipt/duration_tree_2025", "model_contract/R6", "model_closure/R6"):
            incomplete = {name: value for name,value in frozen.items() if name != key}
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, "changed"):
                Cohort._match_source_refs(incomplete, Cohort._book_source_data(sid,status), "changed")



if __name__=="__main__":unittest.main()
