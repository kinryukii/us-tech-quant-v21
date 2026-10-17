"""Owned five-strategy chart queue: metadata and providers are synthetic only."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from moomoo_component import applied_source as source_module
from moomoo_component.applied_source import DailySource, DailySourceError
from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, timestamp
import test_applied_source as source_tests
import test_cohort as cohort_tests
NOW, OPEN = source_tests.NOW, cohort_tests.OPEN


class MainMetadataTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root=Path(tmp); folder=root/'A2_consensus_paper'; folder.mkdir()
            pub=root/'publication.json'; pub.write_text('{}')
            pub_ref=dict(path=str(pub),sha256=hashlib.sha256(pub.read_bytes()).hexdigest())
            (folder/'latest.json').write_text(json.dumps(pub_ref))
            driver=root/'driver.py'; driver.write_text('# synthetic owner')
            mapping=root/'run'/'universe'/'mapped_members.parquet'; mapping.parent.mkdir(parents=True); mapping.write_text('synthetic')
            report=root/'run'/'report.json'; report.write_text('{}')
            owner=ModuleType('scripts.research.a2.evaluation.consensus_paper_performance'); owner.__file__=str(driver)
            owner.completed_calendar=Mock(return_value=dict(target_session='2026-09-28'))
            owner.already_current=Mock(return_value=None)
            owner.run_qualified_main=Mock(return_value=dict(status='METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION',
                end='2026-09-28', publication_ref=pub_ref, capture_ref=dict(path='synthetic-capture.json',sha256='c'*64)))
            owner.projected_metadata=Mock(side_effect=[dict(source_extension_ref={'path':'synthetic-extension','sha256':'e'*64}),
                dict(current_day_proofs=[dict(signal_date='2026-09-28',mapping_ref={'path':str(mapping),'sha256':'m'*64})])])
            owner.verified=Mock(return_value=mapping)
            owner.reference=Mock(return_value=dict(path=str(report),sha256=hashlib.sha256(report.read_bytes()).hexdigest()))
            owner.resolve_supplemental_ca_receipts=Mock(return_value=dict(locator_ref=None,ca_receipt_refs=[]))
            consumer=ModuleType('scripts.research.a2.inference.consensus_paper'); consumer.resource_check=Mock()
            from scripts.research.a2 import evaluation, inference
            stack.enter_context(patch.object(evaluation,'consensus_paper_performance',owner,create=True))
            stack.enter_context(patch.object(inference,'consensus_paper',consumer,create=True))
            stack.enter_context(patch.dict(sys.modules,{owner.__name__:owner,consumer.__name__:consumer}))
            stack.enter_context(patch('scripts.common.storage_paths.resolve',return_value=SimpleNamespace(daily_root=root)))
            yield root, owner, consumer

    def test_current_owner_proof_skips_preflight_resources_and_all_model_work(self):
        with self.fixture() as (root,owner,consumer):
            owner.already_current.return_value=dict(end='2026-09-28',manifest_ref=dict(path='manifest',sha256='f'*64))
            out=source_module._main_charts_metadata(root,NOW)
            self.assertEqual(out['status'],'READY'); self.assertEqual(out['models_loaded'],0); self.assertEqual(out['ledger_values_decoded'],0)
            owner.run_qualified_main.assert_not_called(); owner.projected_metadata.assert_not_called(); consumer.resource_check.assert_not_called()

    def test_preflight_binds_exact_capture_publication_driver_and_report_no_ca_inheritance(self):
        with self.fixture() as (root,owner,consumer):
            out=source_module._main_charts_metadata(root,NOW)
            self.assertEqual(out['status'],'PREFLIGHT')
            self.assertEqual(out['request']['context'],out['context']); self.assertEqual(out['request']['capture_ref'],out['context']['capture_ref'])
            self.assertEqual(set(out['context']),{'target_session','driver_ref','publication_ref','capture_ref','daily_report_ref'})
            self.assertNotIn('ca_receipt_refs',out['request']); self.assertEqual(out['source_qualification'],'ORIGINAL_DRIVER_REQUIRED')
            owner.run_qualified_main.assert_called_once_with(unittest.mock.ANY,as_of=source_module._iso(NOW),auto=True,execute=False)
            consumer.resource_check.assert_called_once_with()

    def test_floor_blocks_before_any_replay_admission_with_same_source_identity(self):
        with self.fixture() as (root,owner,consumer):
            consumer.resource_check.side_effect=ValueError('CONSENSUS_RESOURCE_FLOOR')
            out=source_module._main_charts_metadata(root,NOW)
            self.assertEqual(out['status'],'BLOCKED'); self.assertTrue(out['resource_blocked']); self.assertNotIn('request',out)
            self.assertIn('daily_report_ref',out['context']); self.assertEqual(out['ledger_values_decoded'],0)
            self.assertFalse(owner.run_qualified_main.call_args.kwargs['execute'])

    def test_unproven_preflight_or_ambiguous_mapping_cannot_launch(self):
        for case in ('preflight','mapping'):
            with self.subTest(case=case), self.fixture() as (root,owner,consumer):
                if case=='preflight':owner.run_qualified_main.return_value['status']='READY'
                else:owner.projected_metadata.side_effect=[dict(source_extension_ref={'path':'e','sha256':'e'*64}),dict(current_day_proofs=[])]
                out=source_module._main_charts_metadata(root,NOW)
                self.assertEqual(out['status'],'BLOCKED'); self.assertNotIn('request',out); consumer.resource_check.assert_not_called()

    def test_supplemental_locator_is_bound_before_resource_gate_without_ca_qualification(self):
        locator=dict(path='dated-locator.json',sha256='a'*64)
        extras=[dict(path='native-ca.json',sha256='b'*64)]
        for blocked in (False,True):
            with self.subTest(blocked=blocked),self.fixture() as (root,owner,consumer):
                owner.resolve_supplemental_ca_receipts.return_value=dict(locator_ref=locator,ca_receipt_refs=extras)
                if blocked:consumer.resource_check.side_effect=ValueError('CONSENSUS_RESOURCE_FLOOR')
                out=source_module._main_charts_metadata(root,NOW)
                self.assertEqual(out['context']['supplemental_ca_locator_ref'],locator)
                self.assertEqual(out['context']['ca_receipt_refs'],extras)
                self.assertEqual(out['ledger_values_decoded'],0)
                self.assertEqual(out['status'],'BLOCKED' if blocked else 'PREFLIGHT')
                if not blocked:self.assertEqual(out['request']['ca_receipt_refs'],extras)
                else:self.assertNotIn('request',out)
                owner.resolve_supplemental_ca_receipts.assert_called_once_with(unittest.mock.ANY,
                    target_session='2026-09-28',publication_ref=out['context']['publication_ref'],
                    capture_ref=out['context']['capture_ref'],daily_report_ref=out['context']['daily_report_ref'],
                    as_of=source_module._iso(NOW))

    def test_invalid_locator_fails_before_original_resource_admission(self):
        with self.fixture() as (root,owner,consumer):
            owner.resolve_supplemental_ca_receipts.side_effect=ValueError('PAPER_EXTENSION_CA_LOCATOR_SOURCE_BINDING_CHANGED')
            out=source_module._main_charts_metadata(root,NOW)
            self.assertEqual(out['status'],'BLOCKED');self.assertNotIn('request',out)
            self.assertFalse(out['resource_blocked']);consumer.resource_check.assert_not_called()

    def test_worker_metadata_branch_never_constructs_inference_source(self):
        result=dict(status='READY',models_loaded=0,ledger_values_decoded=0)
        request=dict(action='main_charts_status',repo_root='synthetic',now=NOW.isoformat())
        with patch.object(sys,'stdin',io.StringIO(json.dumps(request))), patch.object(source_module,'_main_charts_metadata',return_value=result) as meta, \
                patch.object(source_module,'_CanonicalSource',side_effect=AssertionError('no inference owner')):
            self.assertEqual(source_module._worker(),result); meta.assert_called_once_with('synthetic',NOW.isoformat())

    def test_facade_uses_owned_protocol_without_heavy_import_or_worker_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=source_tests.FacadeTests.facade(self,Path(tmp)); original_import=__import__; seen=[]
            def importing(name,*args,**kwargs):
                if 'consensus_paper_performance' in name:raise AssertionError('performance cannot import in parent')
                return original_import(name,*args,**kwargs)
            def provider(paths,module,args,log,**kwargs):
                request=json.loads(kwargs['input_path'].read_text());seen.append(request)
                log.write_text(json.dumps(dict(ok=True,result=dict(status='BLOCKED',reason='synthetic metadata'))))
                return dict(exit_code=0)
            with patch('builtins.__import__',side_effect=importing), patch('scripts.common.daily_support.run_provider',side_effect=provider), \
                    patch.object(source_module.subprocess,'Popen',side_effect=AssertionError('no raw spawn')):
                self.assertTrue(source_module._WORKER_LOCK.acquire(False))
                try:self.assertEqual(facade.main_execution_charts_status(NOW)['status'],'BLOCKED')
                finally:source_module._WORKER_LOCK.release()
            self.assertEqual(seen[0]['action'],'main_charts_status')


class MainOwnedJobTests(unittest.TestCase):
    def setUp(self):
        def reset_synthetic_quarantine():
            if source_module._worker_quarantine_reason():
                source_module._WORKER_QUARANTINE_REASON=None
                if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()
        self.addCleanup(reset_synthetic_quarantine)
    def fixture(self,tmp):
        return source_tests.FacadeTests.facade(self,Path(tmp))
    def request(self):
        return dict(as_of=NOW.isoformat(),capture_ref=dict(path='synthetic-capture',sha256='c'*64),context=dict(target_session='2026-09-28'))
    def joined(self,job):
        if job is not None:
            job._cancel_event.set(); job._thread.join(3)
            if job._thread.is_alive():job.cancel()

    def test_two_stages_share_one_slot_and_recheck_metadata_before_original_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp); request=self.request(); calls=[]; job=None
            current=dict(status='PREFLIGHT',context=request['context'],request=request)
            def provider(paths,module,args,log,**kwargs):
                self.assertFalse(source_module._WORKER_LOCK.acquire(False)); calls.append((module,args,kwargs))
                with patch.object(source_module,'_WORKER_LOCK_TIMEOUT_SECONDS',.001):
                    with self.assertRaisesRegex(DailySourceError,'WORKER_BUSY'):facade._call('load')
                return dict(exit_code=0)
            with patch.object(facade,'main_execution_charts_status',return_value=current) as meta, \
                    patch('scripts.common.daily_support.run_provider',side_effect=provider), patch.object(source_module.subprocess,'Popen',side_effect=AssertionError('no raw spawn')):
                try:job=facade.start_execution_charts(main_request=request);job._thread.join(3);self.assertFalse(job._thread.is_alive())
                finally:
                    if sys.exc_info()[0] is not None:self.joined(job)
            self.assertEqual(job.poll(),0);self.assertEqual([c[0] for c in calls],['scripts.daily_recommendation','scripts.research.a2.evaluation.consensus_paper_performance'])
            self.assertEqual(calls[0][1],['--execution-charts']);self.assertEqual(calls[1][1][:4],['--auto','--execute','--as-of',NOW.isoformat()])
            self.assertNotIn('--ca-receipt-ref',calls[1][1]);meta.assert_called_once_with(now=NOW,cancel_event=job._cancel_event)
            self.assertTrue(source_module._WORKER_LOCK.acquire(False));source_module._WORKER_LOCK.release()

    def test_supplemental_refs_rechecked_and_passed_as_original_cli_arguments(self):
        refs=[dict(path='exact-native-ca.json',sha256='b'*64)]
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);request=self.request();request['ca_receipt_refs']=refs
            request['context'].update(ca_receipt_refs=refs,supplemental_ca_locator_ref=dict(path='dated-locator.json',sha256='a'*64))
            current=dict(status='PREFLIGHT',context=deepcopy(request['context']),request=deepcopy(request))
            calls=[]
            def provider(paths,module,args,log,**kwargs):
                calls.append((module,args));return dict(exit_code=0)
            with patch.object(facade,'main_execution_charts_status',return_value=current),patch('scripts.common.daily_support.run_provider',side_effect=provider):
                job=facade.start_execution_charts(legacy=False,main_request=request)
                try:job._thread.join(3);self.assertFalse(job._thread.is_alive())
                finally:
                    if sys.exc_info()[0] is not None:self.joined(job)
            self.assertEqual(job.poll(),0);self.assertEqual(len(calls),1)
            args=calls[0][1];index=args.index('--ca-receipt-ref')
            self.assertEqual(json.loads(args[index+1]),refs[0])

    def test_supplemental_refs_cannot_differ_from_context_or_rechecked_request(self):
        refs=[dict(path='exact-native-ca.json',sha256='b'*64)]
        for mismatch in ('context','rechecked-request'):
            with self.subTest(mismatch=mismatch),tempfile.TemporaryDirectory() as tmp:
                facade=self.fixture(tmp);request=self.request();request['ca_receipt_refs']=deepcopy(refs)
                request['context']['ca_receipt_refs']=deepcopy(refs)
                current=dict(status='PREFLIGHT',context=deepcopy(request['context']),request=deepcopy(request))
                if mismatch=='context':request['context']['ca_receipt_refs']=[];current['context']=deepcopy(request['context'])
                else:current['request']['ca_receipt_refs']=[]
                with patch.object(facade,'main_execution_charts_status',return_value=current),patch('scripts.common.daily_support.run_provider') as provider:
                    job=facade.start_execution_charts(legacy=False,main_request=request)
                    try:job._thread.join(3);self.assertFalse(job._thread.is_alive())
                    finally:
                        if sys.exc_info()[0] is not None:self.joined(job)
                provider.assert_not_called();self.assertEqual(job.poll(),2)

    def test_metadata_change_or_resource_floor_never_starts_main_stage(self):
        for change in (dict(status='BLOCKED',reason='CONSENSUS_RESOURCE_FLOOR',resource_blocked=True),dict(status='PREFLIGHT',context={'changed':True})):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                facade=self.fixture(tmp);job=None
                with patch.object(facade,'main_execution_charts_status',return_value=change), patch('scripts.common.daily_support.run_provider',return_value=dict(exit_code=0)) as provider:
                    try:job=facade.start_execution_charts(main_request=self.request());job._thread.join(3);self.assertFalse(job._thread.is_alive())
                    finally:
                        if sys.exc_info()[0] is not None:self.joined(job)
                self.assertEqual(provider.call_count,1);self.assertEqual(job.poll(),2)
                self.assertEqual(job.result()['stages']['legacy']['exit_code'],0)

    def test_cancel_between_stages_skips_main_and_waits_for_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);job=None;entered=threading.Event();release=threading.Event()
            def provider(paths,module,args,log,**kwargs):
                entered.set();kwargs['cancel_event'].wait(2);self.assertTrue(release.wait(2));return dict(exit_code=-1)
            with patch.object(facade,'main_execution_charts_status') as meta, patch('scripts.common.daily_support.run_provider',side_effect=provider):
                cancel=None
                try:
                    job=facade.start_execution_charts(main_request=self.request());self.assertTrue(entered.wait(2))
                    cancel=threading.Thread(target=job.cancel);cancel.start();self.assertTrue(job._cancel_event.wait(2))
                    self.assertIsNone(job.poll());self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                finally:
                    release.set()
                    if cancel:cancel.join(3)
                    self.joined(job)
            meta.assert_not_called();self.assertTrue(job.result()['cancelled'])
            self.assertTrue(source_module._WORKER_LOCK.acquire(False));source_module._WORKER_LOCK.release()

    def test_current_receipt_found_after_slot_wait_skips_main_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);job=None
            with patch.object(facade,'main_execution_charts_status',return_value=dict(status='READY')), patch('scripts.common.daily_support.run_provider') as provider:
                try:job=facade.start_execution_charts(legacy=False,main_request=self.request());job._thread.join(3);self.assertFalse(job._thread.is_alive())
                finally:
                    if sys.exc_info()[0] is not None:self.joined(job)
            provider.assert_not_called();self.assertEqual(job.poll(),0);self.assertEqual(job.result()['stages']['main']['action'],'ALREADY_CURRENT_PREFIX_VERIFIED')

    def test_cancel_propagates_to_owned_metadata_process_before_model_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);job=None;entered=threading.Event()
            def provider(paths,module,args,log,**kwargs):
                self.assertEqual(module,'apps.moomoo_trading_component.moomoo_component.applied_source')
                entered.set();self.assertTrue(kwargs['cancel_event'].wait(2))
                return dict(exit_code=-1,error='InterruptedError:PROVIDER_CANCELLED')
            with patch('scripts.common.daily_support.run_provider',side_effect=provider):
                try:job=facade.start_execution_charts(legacy=False,main_request=self.request());self.assertTrue(entered.wait(2));job.cancel()
                finally:self.joined(job)
            self.assertTrue(job.result()['cancelled']);self.assertEqual(job.poll(),-1)
            self.assertTrue(source_module._WORKER_LOCK.acquire(False));source_module._WORKER_LOCK.release()

    def test_explicit_windows_cleanup_failures_quarantine_even_after_thread_exits(self):
        for stage in ('legacy','main'):
            for operation in ('CLOSE_OWNED_JOB','OWNED_PROCESS_TERMINATION'):
                with self.subTest(stage=stage,operation=operation),tempfile.TemporaryDirectory() as tmp:
                    facade=self.fixture(tmp);job=None;request=self.request()
                    failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:'+operation+':synthetic OS failure')
                    current=dict(status='PREFLIGHT',context=request['context'],request=request)
                    with patch.object(facade,'main_execution_charts_status',return_value=current) as meta,patch('scripts.common.daily_support.run_provider',return_value=failure) as provider:
                        try:
                            job=facade.start_execution_charts(legacy=stage=='legacy',main_request=request);job._thread.join(3)
                            self.assertFalse(job._thread.is_alive());self.assertTrue(job._done.is_set());self.assertIsNone(job.poll())
                            self.assertEqual(job.result()['status'],'QUARANTINED');self.assertFalse(job.result()['cleanup_verified'])
                            self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                            with self.assertRaisesRegex(RuntimeError,'CLEANUP_UNVERIFIED'):job.cancel()
                            with patch.object(source_module,'_WORKER_LOCK_TIMEOUT_SECONDS',.001):
                                with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call('load')
                            self.assertEqual(provider.call_count,1)
                            if stage=='legacy':meta.assert_not_called()
                            else:meta.assert_called_once()
                        finally:
                            # Entire providers are mocked; this is test isolation,
                            # never an application recovery/unquarantine method.
                            if job and job.quarantine_reason():
                                source_module._WORKER_QUARANTINE_REASON=None
                                source_module._WORKER_LOCK.release()
                            else:self.joined(job)

    def test_owned_metadata_cleanup_failure_also_retains_the_shared_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);job=None
            failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:CLOSE_OWNED_JOB:synthetic')
            with patch('scripts.common.daily_support.run_provider',return_value=failure) as provider:
                try:
                    job=facade.start_execution_charts(legacy=False,main_request=self.request());job._thread.join(3)
                    self.assertFalse(job._thread.is_alive());self.assertIsNone(job.poll())
                    self.assertEqual(job.result()['status'],'QUARANTINED');self.assertEqual(provider.call_count,1)
                    self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                finally:
                    if job and job.quarantine_reason():
                        source_module._WORKER_QUARANTINE_REASON=None
                        source_module._WORKER_LOCK.release()
                    else:self.joined(job)

    def test_canonical_heavy_worker_cleanup_failure_cannot_start_a_second_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:OWNED_PROCESS_TERMINATION:synthetic')
            with patch('scripts.common.daily_support.run_provider',return_value=failure) as provider:
                try:
                    with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call('load')
                    self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                    with patch.object(source_module,'_WORKER_LOCK_TIMEOUT_SECONDS',.001):
                        with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call('load')
                    self.assertEqual(provider.call_count,1)
                finally:
                    # Only a synthetic returned failure exists; no actual child tree.
                    source_module._WORKER_QUARANTINE_REASON=None
                    if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_unowned_preflight_metadata_failure_quarantines_all_new_worker_admissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:CLOSE_OWNED_JOB:synthetic')
            with patch('scripts.common.daily_support.run_provider',return_value=failure) as provider:
                try:
                    with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade.main_execution_charts_status(NOW)
                    self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                    for action in ('status','load','main_charts_status'):
                        with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call(action)
                    with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade.start_execution_charts(main_request=self.request())
                    self.assertEqual(provider.call_count,1)
                finally:
                    source_module._WORKER_QUARANTINE_REASON=None
                    if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_metadata_failure_during_existing_heavy_holder_prevents_release_or_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);entered=threading.Event();release=threading.Event();errors=[]
            failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:OWNED_PROCESS_TERMINATION:synthetic')
            def provider(paths,module,args,log,**kwargs):
                request=json.loads(kwargs['input_path'].read_text())
                if request['action']=='load':
                    entered.set();self.assertTrue(release.wait(2));log.write_text(json.dumps(dict(ok=True,result={'synthetic':True})));return {'exit_code':0}
                return failure
            def heavy():
                try:facade._call('load')
                except Exception as exc:errors.append(type(exc).__name__)
            with patch('scripts.common.daily_support.run_provider',side_effect=provider) as calls:
                worker=None
                try:
                    worker=threading.Thread(target=heavy);worker.start();self.assertTrue(entered.wait(2))
                    with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade.main_execution_charts_status(NOW)
                    release.set();worker.join(3);self.assertFalse(worker.is_alive())
                    self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                    with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call('load')
                    self.assertEqual(calls.call_count,2)
                finally:
                    release.set()
                    if worker:worker.join(3)
                    source_module._WORKER_QUARANTINE_REASON=None
                    if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_late_quarantine_at_release_reacquires_original_slot(self):
        lock=Mock();state={'locked':True}
        def release():
            state['locked']=False;source_module._WORKER_QUARANTINE_REASON='EXECUTION_CHART_CLEANUP_UNVERIFIED:CLOSE_OWNED_JOB'
        def acquire(blocking=False):
            if state['locked']:return False
            state['locked']=True;return True
        lock.release.side_effect=release;lock.acquire.side_effect=acquire
        with patch.object(source_module,'_WORKER_LOCK',lock),patch.object(source_module,'_WORKER_QUARANTINE_REASON',None):
            source_module._release_worker_lock_if_verified()
            self.assertTrue(state['locked']);lock.acquire.assert_called_once_with(blocking=False)

    def test_filesystem_cleanup_error_cannot_replace_returned_owned_tree_failure(self):
        for action in ('chart','metadata'):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as tmp:
                facade=self.fixture(tmp);job=None;original=source_module.tempfile.TemporaryDirectory
                @contextmanager
                def broken_exit(*args,**kwargs):
                    with original(*args,**kwargs) as folder:
                        try:yield folder
                        finally:raise PermissionError('synthetic child still holds log handle')
                failure=dict(exit_code=-1,lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='OSError:CLOSE_OWNED_JOB:synthetic')
                with patch.object(source_module.tempfile,'TemporaryDirectory',side_effect=broken_exit),patch('scripts.common.daily_support.run_provider',return_value=failure) as provider:
                    try:
                        if action=='chart':
                            job=facade.start_execution_charts(main_request=self.request());job._thread.join(3)
                            self.assertFalse(job._thread.is_alive());self.assertEqual(job.result()['status'],'QUARANTINED');self.assertIsNone(job.poll())
                        else:
                            with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED:CLOSE_OWNED_JOB'):facade.main_execution_charts_status(NOW)
                        self.assertFalse(source_module._WORKER_LOCK.acquire(False));self.assertEqual(provider.call_count,1)
                        with self.assertRaisesRegex(DailySourceError,'CLEANUP_UNVERIFIED'):facade._call('load')
                    finally:
                        source_module._WORKER_QUARANTINE_REASON=None
                        if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_ordinary_qualified_driver_error_releases_resources_and_can_continue_other_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);job=None;request=self.request()
            def provider(paths,module,args,log,**kwargs):
                return dict(exit_code=2 if module=='scripts.daily_recommendation' else 0,
                    lifecycle='WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE',error='ValueError:MODEL_INPUT_NOT_QUALIFIED')
            with patch.object(facade,'main_execution_charts_status',return_value=dict(status='PREFLIGHT',context=request['context'],request=request)),patch('scripts.common.daily_support.run_provider',side_effect=provider) as call:
                try:job=facade.start_execution_charts(main_request=request);job._thread.join(3);self.assertFalse(job._thread.is_alive())
                finally:
                    if sys.exc_info()[0] is not None:self.joined(job)
            self.assertEqual(job.poll(),2);self.assertIsNone(job.quarantine_reason());self.assertEqual(call.call_count,2)
            self.assertTrue(source_module._WORKER_LOCK.acquire(False));source_module._WORKER_LOCK.release()

    def test_main_failure_is_bounded_typed_and_preserves_legacy_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=self.fixture(tmp);request=self.request();job=None
            def provider(paths,module,args,log,**kwargs):
                if module=='scripts.daily_recommendation':return dict(exit_code=0)
                log.write_text('x'*10000+'\n'+json.dumps(dict(status='BLOCKED',reason='CURRENT_CA_MISSING'))+'\n')
                return dict(exit_code=2)
            with patch.object(facade,'main_execution_charts_status',return_value=dict(status='PREFLIGHT',context=request['context'],request=request)), \
                    patch('scripts.common.daily_support.run_provider',side_effect=provider):
                try:job=facade.start_execution_charts(main_request=request);job._thread.join(3);self.assertFalse(job._thread.is_alive())
                finally:
                    if sys.exc_info()[0] is not None:self.joined(job)
            self.assertEqual(job.result()['stages']['legacy']['exit_code'],0)
            self.assertEqual(job.result()['stages']['main']['reason'],'CURRENT_CA_MISSING');self.assertFalse(job.result()['stages']['main']['resource_blocked'])


class FiveChartQueueTests(unittest.TestCase):
    def setUp(self):
        cohort_tests.ExecutionChartsHookTests.setUp(self)
        from moomoo_component.core import Engine
        for sid in ACTIVE_PAPER_STRATEGY_IDS:
            if sid not in self.cohort.engines:
                self.cohort.engines[sid]=Engine(self.cohort.path/'books'/sid,quote_provider=self.quotes.quotes,paper_account_id='paper-'+sid,paper_only=True)
        active=patch.object(self.cohort,'_active_ids',return_value=ACTIVE_PAPER_STRATEGY_IDS);active.start();self.addCleanup(active.stop)
        self.source.execution_charts_status.return_value=deepcopy(self.ready)
        self.context=dict(target_session='2026-09-28',publication_ref=dict(path='synthetic-pub',sha256='a'*64),
            driver_ref=dict(path='synthetic-driver',sha256='d'*64),capture_ref=dict(path='synthetic-capture',sha256='c'*64),
            daily_report_ref=dict(path='synthetic-report',sha256='b'*64))
        self.main=dict(status='PREFLIGHT',context=deepcopy(self.context),end='2026-09-28',models_loaded=0,ledger_values_decoded=0,
            broker_action_allowed=False,request=dict(as_of=self.clock.isoformat(),capture_ref=self.context['capture_ref'],context=deepcopy(self.context)))
        def metadata(now=None):
            value=deepcopy(self.main)
            if isinstance(value.get('request'),dict):value['request']['as_of']=now.isoformat()
            return value
        self.source.main_execution_charts_status=Mock(side_effect=metadata)
    call=cohort_tests.ExecutionChartsHookTests.call
    def complete(self,code=0,reason=None,resource=False):
        self.job.poll.return_value=code
        self.job.result.return_value=dict(exit_code=code,stages=dict(main=dict(exit_code=code,reason=reason,resource_blocked=resource)))
        self.call()

    def test_legacy_ready_main_stale_only_queues_main_no_trading_changes(self):
        before={sid:e.paper_book() for sid,e in self.cohort.engines.items()}
        with patch.object(self.source,'load',side_effect=AssertionError('no inference')),patch.object(self.source,'refresh',side_effect=AssertionError('no refresh')):
            self.call();self.call()
        self.source.start_execution_charts.assert_called_once_with(legacy=False,main_request=self.main['request'])
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['legacy']['status'],'READY')
        self.assertEqual({sid:e.paper_book() for sid,e in self.cohort.engines.items()},before)

    def test_both_owner_receipts_current_skip_even_after_handle_restart(self):
        self.main.update(status='READY',manifest_ref=dict(path='manifest',sha256='f'*64))
        self.call();self.cohort._execution_charts_job=None;self.call()
        self.source.start_execution_charts.assert_not_called();self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'READY')
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['main']['manifest_ref'],self.main['manifest_ref'])

    def test_main_ready_legacy_stale_only_queues_original_daily_stage(self):
        self.main['status']='READY';self.source.execution_charts_status.return_value={'status':'UNAVAILABLE'}
        self.call();self.source.start_execution_charts.assert_called_once_with(legacy=True,main_request=None)
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['main']['status'],'READY')

    def test_nonresource_main_failure_keeps_ready_legacy_and_waits_for_changed_exact_source(self):
        self.call();self.complete(2,'CURRENT_CA_MISSING')
        update=self.cohort.meta['execution_charts_update'];self.assertEqual(update['status'],'BLOCKED');self.assertEqual(update['stages']['legacy']['status'],'READY')
        self.call(clock=self.clock+timedelta(minutes=15));self.assertEqual(self.source.start_execution_charts.call_count,1)
        self.main['context']['daily_report_ref']['sha256']='e'*64;self.main['request']['context']=deepcopy(self.main['context'])
        self.job.poll.return_value=None;self.call(clock=self.clock+timedelta(minutes=30))
        self.assertEqual(self.source.start_execution_charts.call_count,2)

    def test_resource_floor_never_starts_main_and_recovery_obeys_fifteen_minute_backoff(self):
        self.main.update(status='BLOCKED',reason='CONSENSUS_RESOURCE_FLOOR',resource_blocked=True)
        self.call();self.source.start_execution_charts.assert_not_called()
        self.main.update(status='PREFLIGHT',reason='',resource_blocked=False)
        self.call(clock=self.clock+timedelta(minutes=14));self.source.start_execution_charts.assert_not_called()
        self.call(clock=self.clock+timedelta(minutes=15));self.source.start_execution_charts.assert_called_once()

    def test_main_floor_does_not_silently_replace_legacy_resource_rules(self):
        self.source.execution_charts_status.return_value={'status':'UNAVAILABLE'}
        self.main.update(status='BLOCKED',reason='CONSENSUS_RESOURCE_FLOOR',resource_blocked=True)
        self.call();self.source.start_execution_charts.assert_called_once_with(legacy=True,main_request=None)
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['main']['status'],'BLOCKED')

    def test_runner_resource_failure_is_retryable_after_recovery_not_permanent_failure_identity(self):
        self.call();self.complete(2,'CONSENSUS_RESOURCE_FLOOR',True)
        self.assertNotIn('failed_main_context',self.cohort.meta['execution_charts_update'])
        self.job.poll.return_value=None;self.call(clock=self.clock+timedelta(minutes=15))
        self.assertEqual(self.source.start_execution_charts.call_count,2)

    def test_success_exit_still_requires_current_authoritative_main_proof(self):
        self.call();self.complete(0)
        self.assertNotEqual(self.cohort.meta['execution_charts_update']['status'],'READY')
        self.main['status']='READY';self.call(clock=self.clock+timedelta(minutes=15))
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'READY');self.assertEqual(self.source.start_execution_charts.call_count,1)

    def test_running_job_cancelled_by_pending_halt_new_window_source_gap_or_changed_package(self):
        for case in ('pending','halt','window','gap','package'):
            with self.subTest(case=case):
                self.cohort._execution_charts_job=None;self.cohort.meta.pop('execution_charts_update',None);self.job.reset_mock();self.job.poll.return_value=None
                self.call();data=deepcopy(self.data);clock=self.clock;engine=self.cohort.engines['RAW_A2']
                with ExitStack() as stack:
                    if case=='pending':stack.enter_context(patch.object(engine,'_pending',return_value=[{'id':'unknown'}]))
                    if case=='halt':engine.halt_event.set()
                    if case=='window':clock=OPEN+timedelta(seconds=1)
                    if case=='gap':data['data_gaps']=['synthetic gap']
                    if case=='package':data['source_refs']['selected/package.json']['sha256']='b'*64
                    try:self.call(clock=clock,data=data)
                    finally:engine.halt_event.clear()
                self.job.cancel.assert_called_once_with();self.assertIsNone(self.cohort._execution_charts_job)

    def test_missing_source_cancels_running_owner_before_any_metadata_or_date_read(self):
        self.call()
        self.cohort._execution_charts_tick(None,self.clock)
        self.job.cancel.assert_called_once_with();self.assertIsNone(self.cohort._execution_charts_job)
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'CANCELLED')

    def test_source_status_exception_finally_cancels_owned_chart_job(self):
        self.call()
        with patch.object(self.source,'status',side_effect=ValueError('synthetic source unavailable')):
            self.cohort.tick(now=self.clock)
        self.job.cancel.assert_called_once_with();self.assertIsNone(self.cohort._execution_charts_job)
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'CANCELLED')

    def test_quarantined_job_is_never_cleared_by_poll_cancel_stop_or_close(self):
        self.call();reason='EXECUTION_CHART_CLEANUP_UNVERIFIED:CLOSE_OWNED_JOB'
        self.job.quarantine_reason.return_value=reason;self.job.cancel.side_effect=RuntimeError(reason)
        try:
            self.cohort._execution_charts_tick(None,self.clock)
            self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'QUARANTINED')
            with self.assertRaisesRegex(RuntimeError,'CLEANUP_UNVERIFIED'):self.cohort.close()
            self.assertFalse(self.cohort.closed);self.assertTrue(self.cohort.stop_event.is_set())
            self.assertIs(self.cohort._execution_charts_job,self.job)
            self.assertEqual(json.loads(self.cohort.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])['status'],'STOPPED')
            self.assertEqual(self.source.start_execution_charts.call_count,1)
        finally:self.job.cancel.side_effect=None;self.job.quarantine_reason.return_value=None

    def test_direct_preflight_cleanup_failure_keeps_quarantine_with_no_job_handle(self):
        self.source.main_execution_charts_status.side_effect=source_module._OwnedCleanupUnverified('CLOSE_OWNED_JOB')
        # Model the actual facade's immediate sticky publication before raising.
        def fail(now=None):
            source_module._quarantine_owned_worker('CLOSE_OWNED_JOB');raise source_module._OwnedCleanupUnverified('CLOSE_OWNED_JOB')
        self.source.main_execution_charts_status.side_effect=fail
        try:
            self.call();self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'QUARANTINED')
            self.call(clock=self.clock+timedelta(minutes=16));self.source.start_execution_charts.assert_not_called()
            self.assertIsNone(getattr(self.cohort,'_execution_charts_job',None));self.assertFalse(source_module._WORKER_LOCK.acquire(False))
        finally:
            source_module._WORKER_QUARANTINE_REASON=None
            if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_global_metadata_quarantine_cancels_running_owned_holder_and_retains_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade=source_tests.FacadeTests.facade(self,Path(tmp));entered=threading.Event();cancelled=threading.Event();job=None
            request=dict(as_of=self.clock.isoformat(),capture_ref=self.context['capture_ref'],context=self.context)
            def provider(paths,module,args,log,**kwargs):
                entered.set();self.assertTrue(kwargs['cancel_event'].wait(2));cancelled.set();return dict(exit_code=-1)
            with patch('scripts.common.daily_support.run_provider',side_effect=provider),patch.object(facade,'main_execution_charts_status') as metadata:
                try:
                    job=facade.start_execution_charts(main_request=request);self.assertTrue(entered.wait(2))
                    self.cohort._execution_charts_job=job
                    self.cohort.meta['execution_charts_update']={'status':'RUNNING','context':dict(signal_date=self.data['signal_date'],execution_date=self.data['execution_date'],package_sha256='a'*64)}
                    source_module._quarantine_owned_worker('CLOSE_OWNED_JOB')
                    self.cohort._execution_charts_tick(None,self.clock)
                    self.assertTrue(cancelled.is_set());self.assertFalse(job._thread.is_alive());metadata.assert_not_called()
                    self.assertIs(self.cohort._execution_charts_job,job);self.assertIsNone(job.poll())
                    self.assertFalse(source_module._WORKER_LOCK.acquire(False))
                    self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'QUARANTINED')
                finally:
                    if job:
                        job._cancel_event.set();job._thread.join(3)
                    source_module._WORKER_QUARANTINE_REASON=None
                    if source_module._WORKER_LOCK.locked():source_module._WORKER_LOCK.release()

    def test_future_open_legacy_waits_while_main_current_without_any_cli_retry(self):
        data=deepcopy(self.data);close=timestamp(data['signal_close_utc'])
        self.main['status']='READY';self.source.execution_charts_status.return_value={'status':'UNAVAILABLE'}
        for minutes in (0,16,32):self.call(data=data,clock=close+timedelta(minutes=minutes,seconds=1))
        self.source.start_execution_charts.assert_not_called()
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'WAITING_OPEN')
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['legacy']['status'],'WAITING_OPEN')
        self.assertEqual(self.cohort.meta['execution_charts_update']['stages']['main']['status'],'READY')

    def test_close_queues_main_only_then_original_open_maturity_can_queue_legacy(self):
        data=deepcopy(self.data);close=timestamp(data['signal_close_utc']);self.source.execution_charts_status.return_value={'status':'UNAVAILABLE'}
        self.call(data=data,clock=close+timedelta(seconds=1))
        self.assertFalse(self.source.start_execution_charts.call_args.kwargs['legacy'])
        self.job.poll.return_value=0;self.job.result.return_value={'exit_code':0,'stages':{'main':{'exit_code':0}}};self.main['status']='READY'
        self.call(data=data,clock=close+timedelta(seconds=2))
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'WAITING_OPEN')
        self.job.poll.return_value=None;self.call()
        self.assertEqual(self.source.start_execution_charts.call_count,2)
        self.assertEqual(self.source.start_execution_charts.call_args.kwargs,dict(legacy=True,main_request=None))

    def test_new_manual_window_cancels_and_cleanup_pending_retains_same_owner(self):
        self.call();self.job.cancel.side_effect=RuntimeError('EXECUTION_CHART_CLEANUP_PENDING')
        broker=SimpleNamespace(lock=threading.RLock(),engine=SimpleNamespace(halt_event=threading.Event(),_pending=lambda:[]),
            execution_window_seconds=600,metadata={'execution_date':self.data['execution_date']},plan={'owner':'synthetic'},
            _scheduled_open=timestamp,_execution_end=lambda:self.clock+timedelta(minutes=10))
        self.cohort.best_broker=broker
        try:
            with self.assertRaisesRegex(RuntimeError,'CLEANUP_PENDING'):self.call()
            self.assertIs(self.cohort._execution_charts_job,self.job);self.assertEqual(self.source.start_execution_charts.call_count,1)
        finally:self.job.cancel.side_effect=None;self.cohort.best_broker=None

    def test_null_or_changed_request_asof_capture_and_context_never_admit_main(self):
        original=deepcopy(self.main)
        for case in ('null','asof','capture','context','end'):
            with self.subTest(case=case):
                self.cohort.meta.pop('execution_charts_update',None);self.main=deepcopy(original)
                if case=='null':self.main['request']=None
                if case=='asof':self.main['request']['as_of']=None
                if case=='capture':self.main['request']['capture_ref']={'path':'wrong','sha256':'w'*64}
                if case=='context':self.main['request']['context']={}
                if case=='end':self.main['end']='2026-09-25'
                self.source.main_execution_charts_status.side_effect=None;self.source.main_execution_charts_status.return_value=deepcopy(self.main)
                self.call();self.source.start_execution_charts.assert_not_called()
                self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'RETRY_WAIT')

    def test_successful_metadata_must_include_exact_identity_refs_and_numeric_zero(self):
        original=deepcopy(self.main)
        for case in ('missing_capture','bad_sha','boolean_zero','null_context'):
            with self.subTest(case=case):
                self.cohort.meta.pop('execution_charts_update',None);self.main=deepcopy(original)
                if case=='missing_capture':self.main['context'].pop('capture_ref')
                if case=='bad_sha':self.main['context']['daily_report_ref']['sha256']='bad'
                if case=='boolean_zero':self.main['models_loaded']=False
                if case=='null_context':self.main['context']=None
                self.call();self.source.start_execution_charts.assert_not_called()
                self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'RETRY_WAIT')

    def test_microsecond_aware_clock_survives_canonical_protocol_lexeme(self):
        clock=self.clock.replace(microsecond=123456)
        self.call(clock=clock)
        self.source.start_execution_charts.assert_called_once()
        self.assertEqual(timestamp(self.source.start_execution_charts.call_args.kwargs['main_request']['as_of']),clock)

    def test_untyped_main_process_failure_not_restarted_on_same_identity(self):
        self.call();self.job.poll.return_value=-1;self.job.result.return_value=dict(exit_code=-1,error='SyntheticCrash',stages={})
        self.call();self.call(clock=self.clock+timedelta(minutes=15))
        self.assertEqual(self.source.start_execution_charts.call_count,1)
        self.assertEqual(self.cohort.meta['execution_charts_update']['failed_main_context'],self.context)

    def test_metadata_requires_model_free_schema_and_never_reads_research_values(self):
        self.main['ledger_values_decoded']=1
        self.call();self.source.start_execution_charts.assert_not_called()
        self.assertIn('MAIN_CHART_METADATA_RESPONSE_INVALID',self.cohort.meta['execution_charts_update']['error'])


if __name__=='__main__':
    unittest.main()


class FiniteMainMetadataTests(unittest.TestCase):
    fixture = MainMetadataTests.fixture

    def test_explicit_ref_selects_finite_metadata_owner_and_preserves_context(self):
        with self.fixture() as (root, owner, consumer):
            finite = ModuleType('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
            finite_path = root / 'finite.py'; finite_path.write_text('# synthetic finite adapter')
            finite.__file__ = str(finite_path)
            finite.already_current = Mock(return_value=None)
            finite.run_qualified_main = Mock(return_value=owner.run_qualified_main.return_value)
            admission = {'path': 'finite-admission.json', 'sha256': 'a' * 64}
            from scripts.research.a2 import evaluation
            with patch.dict(sys.modules, {finite.__name__: finite}), patch.object(evaluation, 'consensus_paper_ca_continuation', finite, create=True):
                result = source_module._main_charts_metadata(root, NOW, finite_ca_admission_ref=admission)
            self.assertEqual(result['status'], 'PREFLIGHT')
            self.assertEqual(result['context']['finite_ca_admission_ref'], admission)
            self.assertEqual(result['request']['finite_ca_admission_ref'], admission)
            self.assertEqual(result['request']['context'], result['context'])
            self.assertEqual(result['context']['original_driver_ref']['path'], str(Path(owner.__file__).resolve()))
            self.assertEqual(result['context']['driver_ref']['path'], str(finite_path.resolve()))
            owner.already_current.assert_not_called(); owner.run_qualified_main.assert_not_called()
            self.assertEqual(finite.run_qualified_main.call_args.kwargs['finite_ca_admission_ref'], admission)
            self.assertFalse(finite.run_qualified_main.call_args.kwargs['execute'])

    def test_finite_metadata_worker_forwards_ref_without_constructing_inference_source(self):
        admission = {'path': 'finite.json', 'sha256': 'a' * 64}
        request = dict(action='main_charts_status', repo_root='synthetic', now=NOW.isoformat(), finite_ca_admission_ref=admission)
        result = {'status': 'BLOCKED', 'reason': 'synthetic'}
        with patch.object(sys, 'stdin', io.StringIO(json.dumps(request))), \
             patch.object(source_module, '_main_charts_metadata', return_value=result) as metadata, \
             patch.object(source_module, '_CanonicalSource', side_effect=AssertionError('no inference owner')):
            self.assertEqual(source_module._worker(), result)
        metadata.assert_called_once_with('synthetic', NOW.isoformat(), finite_ca_admission_ref=admission)


class FiniteMainOwnedJobTests(unittest.TestCase):
    setUp = MainOwnedJobTests.setUp
    fixture = MainOwnedJobTests.fixture
    request = MainOwnedJobTests.request
    joined = MainOwnedJobTests.joined

    def test_ref_is_rechecked_and_only_explicit_finite_worker_receives_it(self):
        for mismatch in ('none', 'context', 'request', 'ready-context'):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                facade = self.fixture(tmp); request = self.request()
                admission = {'path': 'finite.json', 'sha256': 'a' * 64}
                request['finite_ca_admission_ref'] = deepcopy(admission)
                request['context'].update(finite_ca_admission_ref=deepcopy(admission),
                    driver_ref={'path': 'finite.py', 'sha256': 'f' * 64},
                    original_driver_ref={'path': 'old.py', 'sha256': 'd' * 64})
                current = dict(status='PREFLIGHT', context=deepcopy(request['context']), request=deepcopy(request))
                if mismatch == 'context': request['context']['finite_ca_admission_ref'] = {'path': 'changed', 'sha256': 'b' * 64}; current['context'] = deepcopy(request['context'])
                if mismatch == 'request': current['request']['finite_ca_admission_ref'] = None
                if mismatch == 'ready-context': current.update(status='READY'); current['context']['finite_ca_admission_ref'] = None
                calls = []
                def provider(paths, owner, args, log, **kwargs):
                    calls.append((owner, args)); return {'exit_code': 0}
                with patch.object(facade, 'main_execution_charts_status', return_value=current) as reader, \
                     patch('scripts.common.daily_support.run_provider', side_effect=provider):
                    job = facade.start_execution_charts(legacy=False, main_request=request)
                    try: job._thread.join(3); self.assertFalse(job._thread.is_alive())
                    finally:
                        if sys.exc_info()[0] is not None: self.joined(job)
                self.assertEqual(reader.call_args.kwargs['finite_ca_admission_ref'], admission)
                if mismatch != 'none':
                    self.assertEqual(calls, []); self.assertEqual(job.poll(), 2)
                else:
                    self.assertEqual(job.poll(), 0)
                    self.assertEqual(calls[0][0], 'scripts.research.a2.evaluation.consensus_paper_ca_continuation')
                    args = calls[0][1]; self.assertEqual(json.loads(args[args.index('--finite-ca-admission-ref') + 1]), admission)
