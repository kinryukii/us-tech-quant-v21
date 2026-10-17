"""Pure synthetic lifetime checks: stdlib-only temporary modules and sentinels.

No provider SDK, credentials, model, research input or existing service is loaded.
Windows parent-death tests terminate only Popen instances created by this file.
"""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import time

import pytest
from scripts.common import daily_support as owner

CHILD = r"""
import json, os, subprocess, sys, time
from pathlib import Path
ready, published, mode = sys.argv[1:]
if mode == 'inherit_echo':
    print(json.dumps({'literal':os.environ.get('SYNTHETIC_INHERITED_LITERAL'),'numerical':{key:os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')}},ensure_ascii=True)); raise SystemExit(0)
if mode == 'file_utf8':
    print(json.dumps({'text': Path(ready).read_text(), 'utf8_mode': sys.flags.utf8_mode}, ensure_ascii=True)); raise SystemExit(0)
if mode == 'stdin_echo':
    print(json.dumps({'request': json.load(sys.stdin), 'utf8_mode': sys.flags.utf8_mode}, ensure_ascii=False)); raise SystemExit(0)
if mode == 'stdin_tree':
    request = json.load(sys.stdin); assert request['literal'] == '中文 $(inert) `literal`'; mode = request['mode']
if mode == 'echo':
    sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
    print(json.dumps(sys.argv[1:], ensure_ascii=False)); print('synthetic stderr', file=sys.stderr)
    raise SystemExit(3)
if mode == 'parent_death':
    subprocess.Popen([sys.executable, '-B', __file__, ready, published, 'parent_death_grand'])
if mode in {'parent_death', 'parent_death_grand'}:
    suffix = '.grand' if mode == 'parent_death_grand' else ''
    Path(ready + suffix).write_text(str(os.getpid()))
    deadline = time.monotonic() + 10
    while not Path(ready + '.release').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('SYNTHETIC_ROOT_RELEASE_TIMEOUT')
        time.sleep(.01)
    Path(published + suffix).write_text('BAD')
    raise SystemExit(0)
if mode in {'tree', 'fork_exit', 'timeout_tree'}:
    # Only the timeout-startup probe has a larger real startup/sentinel margin.
    # Other tree and normal-return contracts retain their original timing.
    delay = 5 if mode == 'timeout_tree' else 1.8
    grand = 'import time; from pathlib import Path; Path(' + repr(ready + '.grand') + ').write_text("ready"); time.sleep(' + repr(delay) + '); Path(' + repr(published + '.grand') + ').write_text("BAD")'
    subprocess.Popen([sys.executable, '-B', '-c', grand])
Path(ready).write_text(str(os.getpid()))
if mode == 'fork_exit':
    deadline = time.monotonic() + 4
    while not Path(ready + '.grand').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('SYNTHETIC_GRAND_READY_TIMEOUT')
        time.sleep(.01)
    raise SystemExit(0)
time.sleep(5 if mode == 'timeout_tree' else 1.8)
Path(published).write_text('BAD')
"""

@pytest.fixture
def synthetic(tmp_path):
    (tmp_path / 'probe.py').write_text(CHILD, encoding='utf-8')
    return SimpleNamespace(python_exe=Path(sys.executable), repo_root=tmp_path)

def wait_for(path, process=None, seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if path.exists(): return
        if process is not None and process.poll() is not None:
            raise AssertionError('Synthetic parent stopped before handshake: ' + str(process.returncode))
        time.sleep(.02)
    raise AssertionError('Synthetic handshake timed out: ' + str(path))

@pytest.mark.parametrize('argument', ['spaces and 中文', 'literal $(never) `never` & ; |', 'quote" and slash\\'])
def test_literal_argv_exit_and_utf8_logs(synthetic, argument):
    log=synthetic.repo_root/'output.log'
    result=owner.run_provider(synthetic,'probe',[argument,'unused','echo'],log,timeout=8)
    assert result['exit_code']==3 and 'error' not in result
    text=log.read_text(encoding='utf-8')
    assert json.loads(next(line for line in text.splitlines() if line.startswith('[')))==[argument,'unused','echo']
    assert 'synthetic stderr' in text
    assert result['lifecycle']==('WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE' if os.name=='nt' else 'POSIX_OWNED_PROCESS_GROUP')

@pytest.mark.parametrize('bad', [0,-1,float('nan'),float('inf'),3601])
def test_invalid_deadline_never_starts_child(synthetic,monkeypatch,bad):
    monkeypatch.setattr(owner,'_windows_provider',lambda *a: pytest.fail('unexpected child'))
    monkeypatch.setattr(owner,'_posix_provider',lambda *a: pytest.fail('unexpected child'))
    result=owner.run_provider(synthetic,'probe',[],synthetic.repo_root/'log',timeout=bad)
    assert result['exit_code']==-1 and 'PROVIDER_TIMEOUT_INVALID' in result['error']

@pytest.mark.parametrize('module,args', [('bad;command',[]),('probe',['a\0b'])])
def test_invalid_fixed_argv_never_starts_child(synthetic,monkeypatch,module,args):
    monkeypatch.setattr(owner,'_windows_provider',lambda *a: pytest.fail('unexpected child'))
    monkeypatch.setattr(owner,'_posix_provider',lambda *a: pytest.fail('unexpected child'))
    result=owner.run_provider(synthetic,module,args,synthetic.repo_root/'log')
    assert result['exit_code']==-1 and 'PROVIDER_' in result['error']

def test_log_io_failure_is_explicit_and_precedes_start(synthetic,monkeypatch):
    blocked=synthetic.repo_root/'not_a_directory'; blocked.write_text('file')
    monkeypatch.setattr(owner,'_windows_provider',lambda *a: pytest.fail('unexpected child'))
    monkeypatch.setattr(owner,'_posix_provider',lambda *a: pytest.fail('unexpected child'))
    result=owner.run_provider(synthetic,'probe',[],blocked/'log')
    assert result['exit_code']==-1 and 'error' in result

@pytest.mark.parametrize('with_input',[False,True])
@pytest.mark.parametrize('mode',['tree','fork_exit'])
def test_timeout_and_normal_return_kill_residual_owned_descendants(synthetic,mode,with_input):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    request=synthetic.repo_root/'request.json'
    probe_mode='timeout_tree' if mode=='tree' else mode
    if with_input: request.write_text(json.dumps({'mode':probe_mode,'literal':'中文 $(inert) `literal`'},ensure_ascii=False),encoding='utf-8')
    result=owner.run_provider(synthetic,'probe',[ready,published,'stdin_tree' if with_input else probe_mode],
                              synthetic.repo_root/'log',timeout=2 if mode=='tree' else 8,
                              input_path=request if with_input else None)
    if mode=='tree':
        assert result['exit_code']==-1 and 'TimeoutExpired' in result['error']
    else:
        assert result['exit_code']==0
    assert ready.exists() and Path(str(ready)+'.grand').exists()
    # Observe beyond both original five-second BAD publication deadlines.
    time.sleep(5.1 if mode=='tree' else 2)
    assert not published.exists() and not Path(str(published)+'.grand').exists()


def test_fork_exit_reports_grand_handshake_timeout(synthetic,monkeypatch):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    attempted,sleeps=[],[]
    monkeypatch.setattr(subprocess,'Popen',lambda *args,**kwargs: attempted.append((args,kwargs)))
    stamps=iter((0.,3.99,4.))
    monkeypatch.setattr(time,'monotonic',lambda: next(stamps))
    monkeypatch.setattr(time,'sleep',sleeps.append)
    monkeypatch.setattr(sys,'argv',['probe',str(ready),str(published),'fork_exit'])
    with pytest.raises(TimeoutError,match='SYNTHETIC_GRAND_READY_TIMEOUT'):
        exec(compile(CHILD,'synthetic_probe','exec'),{})
    assert len(attempted)==1 and sleeps==[.01]
    assert ready.exists() and not Path(str(ready)+'.grand').exists()
    assert not published.exists() and not Path(str(published)+'.grand').exists()

@pytest.mark.skipif(os.name!='nt',reason='Windows atomic JobList parent-death contract')
@pytest.mark.parametrize('with_input',[False,True])
@pytest.mark.parametrize('at_startup',[False,True])
def test_abrupt_parent_death_cannot_publish_or_leave_running_descendants(synthetic,at_startup,with_input):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    handshake=synthetic.repo_root/'contained_handshake'
    request=synthetic.repo_root/'request.json'
    if with_input: request.write_text(json.dumps({'mode':'parent_death','literal':'中文 $(inert) `literal`'},ensure_ascii=False),encoding='utf-8')
    repo=Path(owner.__file__).resolve().parents[2]
    parent=r"""
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from scripts.common import daily_support as owner
paths=SimpleNamespace(python_exe=Path(sys.executable),repo_root=Path(sys.argv[2]))
if sys.argv[5]=='startup':
    original=owner._wincheck
    def crash(success,operation):
        original(success,operation)
        if operation=='CONTAINMENT_VERIFIED':
            Path(sys.argv[6]).write_text('contained, never resumed')
            os._exit(71)
    owner._wincheck=crash
owner.run_provider(paths,'probe',[sys.argv[3],sys.argv[4],'stdin_tree' if sys.argv[7] else 'parent_death'],
                   paths.repo_root/'parent.log',timeout=15,input_path=Path(sys.argv[7]) if sys.argv[7] else None)
"""
    process=subprocess.Popen([sys.executable,'-B','-c',parent,str(repo),str(synthetic.repo_root),str(ready),str(published),
                              'startup' if at_startup else 'running',str(handshake),str(request) if with_input else ''],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        wait_for(handshake if at_startup else Path(str(ready)+'.grand'),process)
        if not at_startup:
            wait_for(ready,process)
            process.kill()
        process.communicate(timeout=8)
        if not at_startup:
            # Release only after the owned parent has died; a surviving grandchild
            # would now publish BAD instead of depending on a fixed sleep race.
            Path(str(ready)+'.release').write_text('root confirmed parent death')
        if at_startup:
            assert process.returncode==71 and not ready.exists()
        else:
            assert process.returncode!=0 and ready.exists()
        time.sleep(2)
        assert not published.exists() and not Path(str(published)+'.grand').exists()
    finally:
        if process.poll() is None: process.kill(); process.communicate(timeout=8)
        if not at_startup:
            Path(str(ready)+'.release').write_text('root confirmed parent death')

@pytest.mark.parametrize('mode',['parent_death','parent_death_grand'])
@pytest.mark.parametrize('released',[False,True])
def test_parent_death_probe_requires_bounded_root_release(synthetic,monkeypatch,mode,released):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    suffix='.grand' if mode=='parent_death_grand' else ''
    sentinel=Path(str(published)+suffix)
    attempted,sleeps=[],[]
    monkeypatch.setattr(subprocess,'Popen',lambda *args,**kwargs: attempted.append((args,kwargs)))
    stamps=iter((0.,9.99,10.))
    monkeypatch.setattr(time,'monotonic',lambda: next(stamps))
    def root_step(delay):
        assert Path(str(ready)+suffix).exists() and not sentinel.exists()
        sleeps.append(delay)
        if released: Path(str(ready)+'.release').write_text('synthetic root release')
    monkeypatch.setattr(time,'sleep',root_step)
    monkeypatch.setattr(sys,'argv',['probe',str(ready),str(published),mode])
    namespace={'__file__':str(synthetic.repo_root/'probe.py')}
    if released:
        with pytest.raises(SystemExit) as completed:
            exec(compile(CHILD,'synthetic_probe','exec'),namespace)
        assert completed.value.code==0 and sentinel.read_text()=='BAD'
    else:
        with pytest.raises(TimeoutError,match='SYNTHETIC_ROOT_RELEASE_TIMEOUT'):
            exec(compile(CHILD,'synthetic_probe','exec'),namespace)
        assert not sentinel.exists()
    assert sleeps==[.01]
    assert len(attempted)==(1 if mode=='parent_death' else 0)
    if attempted:
        assert attempted[0][0][0][-1]=='parent_death_grand'

@pytest.mark.skipif(os.name!='nt',reason='Windows startup failure contract')
@pytest.mark.parametrize('stage',['SET_KILL_ON_JOB_CLOSE','ATOMIC_JOB_LIST','ONLY_LOG_HANDLES','CONTAINMENT_VERIFIED','BEFORE_RESUME'])
def test_unavailable_containment_never_falls_back_to_running_child(synthetic,monkeypatch,stage):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    original=owner._wincheck
    def denied(success,operation):
        if operation==stage: raise OSError('SYNTHETIC_CONTAINMENT_DENIED:'+stage)
        original(success,operation)
    monkeypatch.setattr(owner,'_wincheck',denied)
    result=owner.run_provider(synthetic,'probe',[ready,published,'tree'],synthetic.repo_root/'log',timeout=3)
    assert result['exit_code']==-1 and 'SYNTHETIC_CONTAINMENT_DENIED' in result['error']
    time.sleep(.05)
    assert not ready.exists() and not published.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows owned job cancellation contract')
def test_cancellation_terminates_already_running_owned_tree(synthetic,monkeypatch):
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    def cancel(handle,argv,timeout):
        wait_for(Path(str(ready)+'.grand'))
        raise KeyboardInterrupt('synthetic cancellation')
    monkeypatch.setattr(owner,'_windows_wait',cancel)
    with pytest.raises(KeyboardInterrupt,match='synthetic cancellation'):
        owner.run_provider(synthetic,'probe',[ready,published,'tree'],synthetic.repo_root/'log',timeout=8)
    time.sleep(2)
    assert not published.exists() and not Path(str(published)+'.grand').exists()


def test_log_close_failure_cannot_be_reported_as_success(synthetic,monkeypatch):
    log=synthetic.repo_root/'log'
    class BrokenClose:
        def __enter__(self): return object()
        def __exit__(self,*args): raise OSError('SYNTHETIC_LOG_CLOSE_FAILED')
    original=Path.open
    monkeypatch.setattr(Path,'open',lambda path,*a,**kw: BrokenClose() if path==log else original(path,*a,**kw))
    monkeypatch.setattr(owner,'_windows_provider',lambda *a: 0)
    monkeypatch.setattr(owner,'_posix_provider',lambda *a: 0)
    result=owner.run_provider(synthetic,'probe',[],log)
    assert result['exit_code']==-1 and 'SYNTHETIC_LOG_CLOSE_FAILED' in result['error']

@pytest.mark.parametrize('with_input',[False,True])
@pytest.mark.parametrize('failure',[None,'timeout','cancel'])
def test_posix_compatibility_group_cleanup_and_literal_spawn(monkeypatch,failure,with_input):
    calls=[]
    class Process:
        pid=123456789
        def wait(self,timeout):
            calls.append(('wait',timeout))
            if len([x for x in calls if x[0]=='wait'])==1:
                if failure=='timeout': raise subprocess.TimeoutExpired(['literal'],timeout)
                if failure=='cancel': raise KeyboardInterrupt('synthetic')
            return 0
    def spawn(argv,**kwargs):
        calls.append(('spawn',argv,kwargs)); return Process()
    monkeypatch.setattr(owner.subprocess,'Popen',spawn)
    import signal
    monkeypatch.setattr(signal,'SIGKILL',9,raising=False)
    monkeypatch.setattr(owner.os,'killpg',lambda pid,sig: calls.append(('owned_group',pid)),raising=False)
    stdin=object() if with_input else None
    if failure:
        with pytest.raises(subprocess.TimeoutExpired if failure=='timeout' else KeyboardInterrupt):
            owner._posix_provider(['literal',';$(inert)'],Path('.'),object(),.5,input_stream=stdin)
    else:
        assert owner._posix_provider(['literal',';$(inert)'],Path('.'),object(),.5,input_stream=stdin)==0
    assert calls[0][1]==['literal',';$(inert)']
    assert calls[0][2]['start_new_session'] is True and 'shell' not in calls[0][2]
    assert calls[0][2]['stdin'] is (stdin if with_input else subprocess.DEVNULL)
    assert ('owned_group',123456789) in calls and calls[-1]==('wait',10)


def test_literal_utf8_json_stdin_uses_original_contained_runner(synthetic):
    request=synthetic.repo_root/'request.json';log=synthetic.repo_root/'log'
    payload={'literal':'中文 $(inert) `literal`','nested':['UTF-8',42], 'path':'C:\\literal\\file'}
    request.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    before=request.read_bytes()
    result=owner.run_provider(synthetic,'probe',['unused','unused','stdin_echo'],log,input_path=request,timeout=8)
    assert result['exit_code']==0 and 'error' not in result
    echoed=json.loads(log.read_text(encoding='utf-8'))
    assert echoed=={'request':payload,'utf8_mode':1}
    assert request.read_bytes()==before
    assert sorted(p.name for p in synthetic.repo_root.iterdir())==['log','probe.py','request.json']

@pytest.mark.parametrize('failure',['missing','directory','too_large','not_utf8','relative','network'])
def test_bad_stdin_request_never_starts_worker(synthetic,monkeypatch,failure):
    request=synthetic.repo_root/'request.json'
    if failure=='directory': request.mkdir()
    elif failure=='too_large': request.write_bytes(b'0'*(owner.MAX_PROVIDER_INPUT_BYTES+1))
    elif failure=='not_utf8': request.write_bytes(b'\xff\xfe')
    elif failure=='relative': request=Path('relative-request.json')
    elif failure=='network': request=Path(r'\\unavailable\share\request.json')
    monkeypatch.setattr(owner,'_windows_provider',lambda *a,**kw: pytest.fail('unexpected child'))
    monkeypatch.setattr(owner,'_posix_provider',lambda *a,**kw: pytest.fail('unexpected child'))
    result=owner.run_provider(synthetic,'probe',[],synthetic.repo_root/'log',input_path=request)
    assert result['exit_code']==-1 and 'error' in result
    assert not (synthetic.repo_root/'log').exists()


def test_stdin_snapshot_is_bounded_and_independent_of_request_revision(synthetic,monkeypatch):
    request=synthetic.repo_root/'request.json';request.write_text('{"original":true}',encoding='utf-8')
    def inspect(argv,cwd,stream,timeout,*,input_stream):
        request.write_bytes(b'x'*(owner.MAX_PROVIDER_INPUT_BYTES+1))
        assert input_stream.read()==b'{"original":true}'
        assert argv[1:5]==['-X','utf8','-B','-m']
        return 0
    monkeypatch.setattr(owner,'_windows_provider',inspect)
    monkeypatch.setattr(owner,'_posix_provider',inspect)
    result=owner.run_provider(synthetic,'probe',[],synthetic.repo_root/'log',input_path=request)
    assert result['exit_code']==0
    assert sorted(p.name for p in synthetic.repo_root.iterdir())==['log','probe.py','request.json']


def test_no_stdin_worker_utf8_reads_original_utf8_file_even_when_environment_disables_utf8(synthetic, monkeypatch):
    monkeypatch.setenv('PYTHONUTF8', '0')
    payload = '中文消息：量化更新✓📈'
    source = synthetic.repo_root/'source.json'
    source.write_text(payload, encoding='utf-8')
    log = synthetic.repo_root/'no_stdin_utf8.log'
    result = owner.run_provider(synthetic, 'probe', [source, 'unused', 'file_utf8'], log, timeout=8)
    assert result['exit_code'] == 0, log.read_text(encoding='utf-8', errors='replace')
    assert json.loads(log.read_text(encoding='utf-8')) == {'text': payload, 'utf8_mode': 1}


@pytest.mark.parametrize('mode,expected_delay',[('tree',1.8),('timeout_tree',5)])
def test_timeout_probe_sentinels_are_real_and_other_tree_timing_is_unchanged(synthetic,monkeypatch,mode,expected_delay):
    """Without containment, both probes really publish BAD after their delays."""
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    delays,attempted=[],[]
    monkeypatch.setattr(time,'sleep',delays.append)
    def uncontained_grand(argv,**kwargs):
        attempted.append(argv)
        exec(compile(argv[-1],'synthetic_uncontained_grand','exec'),{})
    monkeypatch.setattr(subprocess,'Popen',uncontained_grand)
    monkeypatch.setattr(sys,'argv',['probe',str(ready),str(published),mode])
    exec(compile(CHILD,'synthetic_uncontained_parent','exec'),{})
    assert len(attempted)==1 and delays==[expected_delay,expected_delay]
    assert ready.exists() and Path(str(ready)+'.grand').exists()
    assert published.read_text()=='BAD' and Path(str(published)+'.grand').read_text()=='BAD'


def test_already_cancelled_event_never_launches_owned_tree(synthetic,monkeypatch):
    import threading
    cancelled=threading.Event(); cancelled.set()
    monkeypatch.setattr(owner,'_windows_provider',lambda *a,**kw: pytest.fail('no child'))
    monkeypatch.setattr(owner,'_posix_provider',lambda *a,**kw: pytest.fail('no child'))
    result=owner.run_provider(synthetic,'probe',[],synthetic.repo_root/'log',cancel_event=cancelled)
    assert result['exit_code']==-1 and 'PROVIDER_CANCELLED' in result['error']
    assert not (synthetic.repo_root/'log').exists()






@pytest.mark.skipif(os.name!='nt',reason='Windows owned job event-cancel contract')
def test_event_cancellation_waits_for_entire_owned_tree_and_keeps_bystander(synthetic):
    import threading
    import _winapi
    ready,published=synthetic.repo_root/'ready',synthetic.repo_root/'published'
    bystander=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(15)'])
    cancel=threading.Event(); results=[]
    thread=threading.Thread(target=lambda:results.append(owner.run_provider(synthetic,'probe',
        [ready,published,'parent_death'],synthetic.repo_root/'log',timeout=8,cancel_event=cancel)))
    handles=[]
    try:
        thread.start(); wait_for(ready); wait_for(Path(str(ready)+'.grand'))
        for path in (ready,Path(str(ready)+'.grand')):
            handles.append(_winapi.OpenProcess(0x100000,False,int(path.read_text())))
        cancel.set(); thread.join(12)
        assert not thread.is_alive() and results[0]['exit_code']==-1
        assert 'PROVIDER_CANCELLED' in results[0]['error']
        assert all(_winapi.WaitForSingleObject(handle,10000)==_winapi.WAIT_OBJECT_0 for handle in handles)
        assert bystander.poll() is None
        assert not published.exists() and not Path(str(published)+'.grand').exists()
    finally:
        cancel.set(); thread.join(12)
        for handle in handles: _winapi.CloseHandle(handle)
        if bystander.poll() is None: bystander.kill()
        bystander.wait(timeout=8)






def test_original_environment_inheritance_and_parent_remain_unchanged(synthetic,monkeypatch):
    import threading
    parent=dict(os.environ); seen=[]
    def runner(*args,**kwargs): seen.append(kwargs); return 0
    monkeypatch.setattr(owner,'_windows_provider',runner); monkeypatch.setattr(owner,'_posix_provider',runner)
    for event in (None,threading.Event()):
        assert owner.run_provider(synthetic,'probe',[],synthetic.repo_root/'log',cancel_event=event)['exit_code']==0
        assert 'child_env' not in seen[-1] and 'env' not in seen[-1]
    assert dict(os.environ)==parent
    assert not hasattr(owner,'daily_numerical_child_env')


def test_native_worker_inherits_original_numerical_environment_and_literal(synthetic,monkeypatch):
    literal='spaces 中文 $(inert) `literal` & = value'
    monkeypatch.setenv('SYNTHETIC_INHERITED_LITERAL',literal)
    parent=dict(os.environ); log=synthetic.repo_root/'inherit.log'
    numerical={key:os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')}
    result=owner.run_provider(synthetic,'probe',['unused','unused','inherit_echo'],log,timeout=8)
    assert result['exit_code']==0 and 'error' not in result
    assert json.loads(log.read_text(encoding='utf-8'))=={'literal':literal,'numerical':numerical}
    assert dict(os.environ)==parent
