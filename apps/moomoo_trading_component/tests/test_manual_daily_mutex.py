"""Real original OS mutex across synthetic actors; no models, providers or runtime."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os,subprocess,sys,threading,unittest
from unittest.mock import patch
from scripts.common.daily_support import single_update
from moomoo_component.cohort import _manual_inference_update
import test_manual_daily_cache as fixtures

ACTOR = """import sys;from pathlib import Path
from scripts.common.daily_support import single_update
with single_update(Path(sys.argv[1])):
 print('LOCKED',flush=True)
 sys.stdin.read(1)
"""

class SharedManualMutexTests(unittest.TestCase):
    def paper(self):
        fixture=fixtures.ManualPaperTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture
    def broker(self):
        fixture=fixtures.ManualBrokerTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture
    @contextmanager
    def actor(self,root):
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[3])+';'+os.environ.get('PYTHONPATH','')}
        child=subprocess.Popen([sys.executable,'-B','-c',ACTOR,str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        ready=threading.Event();lines=[]
        def read():lines.append(child.stdout.readline().strip());ready.set()
        reader=threading.Thread(target=read,daemon=True);reader.start()
        try:
            self.assertTrue(ready.wait(5),'original lock child readiness timeout')
            self.assertEqual(lines,['LOCKED']);yield child
        finally:
            if child.poll() is None:
                try:child.stdin.write('x');child.stdin.flush();child.wait(timeout=5)
                except (BrokenPipeError,subprocess.TimeoutExpired):child.terminate();child.wait(timeout=5)
            reader.join(2)
            child.stdin.close();child.stdout.close();child.stderr.close()
    def test_cross_actor_main_or_daily_mutex_blocks_five_models_then_release_allows_prepare(self):
        f=self.paper();root=f.source.daily_root/'A2_today_recommendation'
        with self.actor(root):
            before=f.counts();out=f.prepare()
            self.assertEqual(out['status'],'PARTIAL');self.assertEqual(f.source.loads,[])
            self.assertEqual(f.counts(),before)
            self.assertTrue(all('已有更新任务' in b['reason'] for b in out['books'].values()))
        result=f.prepare();self.assertEqual(result['status'],'READY');self.assertEqual(len(f.source.loads),1)
        self.assertTrue(f.cohort.stop_event.is_set());self.assertTrue(all(row[0]==0 for row in f.counts().values()))
    def test_cross_actor_mutex_blocks_original_sim_model_then_release_reuses_account(self):
        f=self.broker();root=f.source.daily_root/'A2_today_recommendation'
        account=f.engine._get('best_account',None);capital=f.engine._get('best_capital',None)
        with self.actor(root),self.assertRaisesRegex(RuntimeError,'已有更新任务'):
            f.broker.prepare_published_inputs(expected_signal_date='2026-09-25',now=f.clock)
        f.source.load.assert_not_called()
        out=f.broker.prepare_published_inputs(expected_signal_date='2026-09-25',now=f.clock)
        self.assertTrue(out['prepared']);self.assertEqual(f.source.load.call_count,1)
        self.assertEqual(f.engine._get('best_account',None),account);self.assertEqual(f.engine._get('best_capital',None),capital)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
    def test_parent_owns_exact_os_lock_through_source_load_without_child_nested_mutex(self):
        f=self.paper();load=f.source.load;seen=[]
        def guarded_load(*args,**kwargs):
            with self.assertRaisesRegex(RuntimeError,'已有更新任务'):
                with single_update(f.source.daily_root/'A2_today_recommendation'):raise AssertionError('lock must cover source.load')
            seen.append(True);return load(*args,**kwargs)
        with patch.object(f.source,'load',side_effect=guarded_load):self.assertEqual(f.prepare()['status'],'READY')
        self.assertEqual(seen,[True])
        with single_update(f.source.daily_root/'A2_today_recommendation'):pass
    def test_ordinary_inference_error_releases_os_lock_and_next_explicit_attempt_is_allowed(self):
        f=self.paper()
        with patch.object(f.source,'load',side_effect=ValueError('synthetic model failure')):
            self.assertEqual(f.prepare()['status'],'PARTIAL')
        with single_update(f.source.daily_root/'A2_today_recommendation'):pass
        self.assertEqual(f.prepare()['status'],'READY')
    def test_unverified_owned_cleanup_retains_same_original_lock_until_controlled_owner_recovery(self):
        f=self.paper();held=None
        try:
            with patch('moomoo_component.cohort._worker_quarantine_reason',return_value='CANONICAL_OWNED_CLEANUP_UNVERIFIED'):
                with _manual_inference_update(f.cohort,f.source):pass
            held=f.cohort._manual_inference_quarantine_lock
            with self.assertRaisesRegex(RuntimeError,'已有更新任务'):
                with single_update(f.source.daily_root/'A2_today_recommendation'):pass
            with self.assertRaisesRegex(RuntimeError,'CLEANUP_UNVERIFIED'):
                with _manual_inference_update(f.cohort,f.source):pass
        finally:
            # Synthetic owner recovery only; production never auto-clears quarantine.
            if held is not None:held.__exit__(None,None,None);f.cohort._manual_inference_quarantine_lock=None
        with single_update(f.source.daily_root/'A2_today_recommendation'):pass
    def test_missing_or_conflicting_original_source_root_fails_closed_before_model_load(self):
        f=self.paper();saved=f.source.daily_root
        for scope in ('missing','conflicting'):
            with self.subTest(scope=scope):
                if scope=='missing':del f.source.daily_root
                else:f.source.daily_root=saved;f.source.paths=SimpleNamespace(daily_root=saved/'other')
                with self.assertRaisesRegex(ValueError,'ORIGINAL_DAILY_ROOT_REQUIRED'):
                    with _manual_inference_update(f.cohort,f.source):raise AssertionError('model cannot enter')
        f.source.daily_root=saved

if __name__=='__main__':unittest.main()
