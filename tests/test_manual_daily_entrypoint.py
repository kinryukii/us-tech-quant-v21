"""Synthetic checks for the original manual daily PS glue; no real HTTP/SDK/model/service."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
import pytest

REPO = Path(__file__).parents[1]
ENTRY = REPO / '更新今日推荐.ps1'
IDS = ('RAW_A2', 'HGB_DIAG_5', 'R10_DIRECT_MEAN4_ELASTICNET_MID',
       'R10_DIRECT_H5_RIDGE_MID', 'R7_GROSS_LINEAR')


def _functions():
    source = ENTRY.read_text(encoding='utf-8-sig')
    return source[source.index('function Invoke-UstqDailyAction {'):source.index('Push-Location $PSScriptRoot')]


def _ps(code, shell=None):
    shell = shell or shutil.which('pwsh') or shutil.which('powershell.exe')
    if not shell:
        pytest.skip('PowerShell unavailable for isolated daily glue')
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command',
        '$ErrorActionPreference="Stop"\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n' + code],
        stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_prepare_case(tmp_path, scenario):
    receipt = {'action': 'PREPARE_CURRENT_PUBLISHED_INPUTS', 'status': 'READY',
               'signal_date': '2026-10-13', 'execution_date': '2026-10-14', 'orders_created': 0, 'running': False,
               'books': {sid: {'status': 'READY', 'reason': '', 'signal_date': '2026-10-13',
                               'execution_date': '2026-10-14'} for sid in IDS},
               'broker': {'action': 'PREPARE_CURRENT_PUBLISHED_INPUTS', 'prepared': True, 'status': 'READY',
                          'strategy_id': IDS[-1], 'signal_date': '2026-10-13', 'execution_date': '2026-10-14',
                          'orders_created': 0, 'running': False}}
    signal = '2026-10-13'
    if scenario == 'partial': receipt['status']='PARTIAL';receipt['books'][IDS[1]]['status']='BLOCKED'
    elif scenario == 'date': signal='2026-02-30'
    elif scenario == 'future_year': signal='2027-01-01'
    elif scenario == 'wrong_signal': receipt['signal_date']='2026-10-12'
    elif scenario == 'wrong_execution': receipt['execution_date']='2026-10-13'
    elif scenario == 'future_execution': receipt['execution_date']='2027-01-01'
    elif scenario == 'missing_sid': del receipt['books'][IDS[0]]
    elif scenario == 'legacy_sid': receipt['books']['HGB_FACTOR_5']=receipt['books'].pop(IDS[1])
    elif scenario == 'extra_sid': receipt['books']['HGB_FACTOR_5']=deepcopy(receipt['books'][IDS[1]])
    elif scenario == 'book_date': receipt['books'][IDS[2]]['signal_date']='2026-10-12'
    elif scenario == 'book_unknown': receipt['books'][IDS[2]]['status']='UNKNOWN'
    elif scenario == 'broker_sid': receipt['broker']['strategy_id']='UNKNOWN'
    elif scenario == 'broker_running': receipt['broker']['running']=True
    elif scenario == 'broker_not_prepared': receipt['broker']['prepared']=False
    elif scenario == 'broker_missing': receipt['broker']=None
    elif scenario == 'orders': receipt['orders_created']=1
    elif scenario == 'orders_boolean': receipt['orders_created']=False
    elif scenario == 'broker_orders': receipt['broker']['orders_created']=1
    elif scenario == 'running_receipt': receipt['running']=True
    elif scenario == 'wrong_action': receipt['action']='STARTED'
    elif scenario == 'inconsistent_ready': receipt['books'][IDS[1]]['status']='BLOCKED'
    control={'schema':'MANUAL_DAILY_MAINTENANCE_V1','maintenance_id':'synthetic_lease','phase':'PAUSED','active':True,
             'original_running':{'cohort':False,'broker':False},'restore_requested':False,
             'operation_active':False,'job_active':False,'workers_drained':True,'cleanup_verified':True,
             'prepared':False,'prepare_receipt':None,'main_status':'UNKNOWN','main_end':None,'reason':''}
    if scenario=='running': control['original_running']={'cohort':True,'broker':True};control['restore_requested']=True
    elif scenario=='half_running': control['original_running']['broker']=True
    elif scenario=='unknown_running': control['original_running']['cohort']=None
    fixture=tmp_path/('manual_'+scenario+'.json')
    fixture.write_text(json.dumps({'control':control,'receipt':receipt,'signal':signal,'scenario':scenario}),encoding='utf-8')
    mocks="""
$case=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8 | ConvertFrom-Json
$script:calls=[Collections.Generic.List[string]]::new();$script:control=$case.control
function Get-UstqActiveStrategyIds { return @('__IDS__') }
function Invoke-UstqComponentRequest {
 param($Path,$Method='GET',$Body,$Token)
 $script:calls.Add($Method+':'+$Path)
 if($Path -eq '/api/applied/maintenance-status'){return @{ok=$true;data=$script:control}}
 if($Token -cne 'synthetic-token' -or $Method -cne 'POST'){throw 'bad boundary'}
 if($Path -eq '/api/applied/reconcile'){
  if($Body.Count -ne 0){throw 'arbitrary reconcile body'}
  if($case.scenario -eq 'reconcile_reject'){throw 'ORIGINAL_RECONCILE_REJECTED'}
  return @{ok=$true;data=@{running=$false}}
 }
 if($Path -ne '/api/applied/prepare-current' -or $Body.Count -ne 2 -or
  $Body.expected_signal_date -cne $case.signal -or $Body.maintenance_id -cne 'synthetic_lease'){throw 'arbitrary prepare body'}
 if($case.scenario -eq 'owner_reject'){$script:control.phase='FAILED';$script:control.reason='ORIGINAL_SOURCE_GUARD_REJECTED';throw 'ORIGINAL_SOURCE_GUARD_REJECTED'}
 $script:control.prepare_receipt=$case.receipt;$script:control.prepared=$true
 return @{ok=$true;data=$case.receipt}
}
$context=[pscustomobject]@{maintenance_id='synthetic_lease';token='synthetic-token';end_submitted=$false}
$accepted=$false;$failure='';$result=$null
try{$result=Prepare-UstqSimulationCurrent -SignalDate $case.signal -Context $context;$accepted=$true}
catch{$failure=[string]$_.Exception.Message}
@{accepted=$accepted;ready=($result.status -ceq 'READY');status=$result.status;failure=$failure;calls=@($script:calls.ToArray())}|ConvertTo-Json -Compress -Depth 5
""".replace('__INPUT__',str(fixture).replace("'","''")).replace('__IDS__',"','".join(IDS))
    return _ps(_functions()+mocks)


@pytest.mark.parametrize('scenario', ['book_date','book_unknown','broker_sid','broker_running','broker_not_prepared',
    'broker_missing','orders','orders_boolean','broker_orders','running_receipt','wrong_action','inconsistent_ready',
    'future_execution','extra_sid','unknown_running','reconcile_reject'])
def test_preparation_strict_receipt_and_owner_rejections(tmp_path, scenario):
    result = run_prepare_case(tmp_path, scenario)
    assert not result['accepted'] and result['failure']
    assert not any('start' in call or 'order' in call for call in result['calls'])
    if scenario == 'reconcile_reject': assert 'POST:/api/applied/prepare-current' not in result['calls']


@pytest.mark.parametrize('scenario', ['ready', 'stale', 'unknown_capture', 'nonmanual', 'broker_nonmanual', 'wrong_health', 'live', 'old_health_mode', 'unknown_health_mode'])
def test_view_never_promotes_stale_or_other_mode(tmp_path, scenario):
    view = {'ok': True, 'display': {'status': 'CURRENT', 'owner_busy': False},
            'data': {'manual_data_updates': True, 'broker': {'manual_data_updates': True}}}
    health = {'data': {'component': 'moomoo-trading-component', 'live_execution_enabled': False, 'manual_data_updates': True}}
    if scenario == 'stale': view['display'].update(status='STALE', owner_busy=True)
    elif scenario == 'unknown_capture': view['display'] = {}
    elif scenario == 'nonmanual': view['data']['manual_data_updates'] = False
    elif scenario == 'broker_nonmanual': view['data']['broker']['manual_data_updates'] = False
    elif scenario == 'wrong_health': health['data']['component'] = 'other-service'
    elif scenario == 'live': health['data']['live_execution_enabled'] = True
    elif scenario == 'old_health_mode': health['data']['manual_data_updates'] = False
    elif scenario == 'unknown_health_mode': del health['data']['manual_data_updates']
    fixture = tmp_path/'view.json'; fixture.write_text(json.dumps({'view':view,'health':health}),encoding='utf-8')
    code = _functions() + """
$case=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8 | ConvertFrom-Json
function Invoke-UstqComponentRequest { param($Path) if($Path -eq '/api/health'){return $case.health}; return $case.view }
$accepted=$false;try{$null=Get-UstqSimulationView;$accepted=$true}catch{}
@{accepted=$accepted}|ConvertTo-Json -Compress
""".replace('__INPUT__',str(fixture).replace("'","''"))
    assert _ps(code)['accepted'] is (scenario == 'ready')


@pytest.mark.parametrize('kind', ['limit', 'oversize', 'malformed', 'invalid_utf8'])
def test_json_reader_enforces_four_mib_before_decode(kind):
    code = _functions() + """
$limit=4*1024*1024
$bytes=if('__KIND__' -eq 'limit'){[Text.Encoding]::UTF8.GetBytes('{"ok":true}'+(' '*($limit-11)))}
 elseif('__KIND__' -eq 'oversize'){[Text.Encoding]::UTF8.GetBytes('{"ok":true}'+(' '*($limit-10)))}
 elseif('__KIND__' -eq 'malformed'){[Text.Encoding]::UTF8.GetBytes('{bad')}
 else{[byte[]]@(255,254,255)}
$stream=[IO.MemoryStream]::new($bytes);$accepted=$false;$ok=$false
try{$value=Read-UstqBoundedJson -Stream $stream;$ok=$value.ok;$accepted=$true}catch{}finally{$stream.Dispose()}
@{accepted=$accepted;ok=$ok;size=$bytes.Length}|ConvertTo-Json -Compress
""".replace('__KIND__',kind)
    result = _ps(code)
    assert result['accepted'] is (kind == 'limit')
    if kind == 'limit': assert result['ok'] and result['size'] == 4*1024*1024


def test_original_entry_only_fixed_routes_and_owner_maintenance():
    source=ENTRY.read_text(encoding='utf-8-sig')
    assert '/api/applied/state' not in source and 'Get-UstqSelectedHgbPolicy' not in source
    assert 'Get-Content -LiteralPath $selected.report_path' not in source
    launcher=source[source.index('    $launchArgs = @('):source.index('    $started = Start-Process')]
    assert '-ManualDataUpdates' in launcher and '-WithMoomooBest' in launcher and '-ActivateStrategies' not in launcher
    assert 'AllowAutoRedirect = $false' in source and 'ResponseHeadersRead' in source
    assert "default { 15 }" in source and '$deadline.Token' in source
    assert '/broker-start' not in source and '/api/applied/start' not in source
    assert 'DailySource' not in source and 'consensus_paper_performance' not in source
    assert '$code = @"' not in source and 'start_execution_charts(' not in source
    assert 'validate_state_projection' in source and '/api/applied/showcase-roster' in source
    assert 'ACTIVE_PAPER_STRATEGY_IDS' not in source and 'HGB_FACTOR_5' not in source
    assert source.index('Begin-UstqDailyMaintenance\n')<source.index("'-m', 'scripts.daily_recommendation'")
    final=source.split('} finally {')[-1]
    assert 'maintenance-end' not in final and 'End-UstqDailyMaintenance' not in final
    opened=(REPO/'打开DEMO.ps1').read_text(encoding='utf-8-sig')
    assert 'apps/demo_console/start.ps1' in opened
    assert all(value not in opened for value in ('daily_recommendation','run_provider','prepare-current','RefreshData','maintenance'))


@pytest.mark.parametrize('scenario', ['ready','cached_main','post_timeout','wrong_id','wrong_schema','dirty_cleanup',
    'workers_busy','failed_chart','wrong_end','operation_unknown','stop_override','generated_waiting_owner'])
def test_main_uses_fresh_same_owner_status_and_submits_once(tmp_path, scenario):
    phase='READY' if scenario not in {'failed_chart','operation_unknown'} else 'FAILED'
    state={'schema':'MANUAL_DAILY_MAINTENANCE_V1','maintenance_id':'synthetic_lease','phase':phase,'active':True,
        'original_running':{'cohort':True,'broker':True},'restore_requested':scenario!='stop_override',
        'operation_active':False,'job_active':False,'workers_drained':True,'cleanup_verified':True,
        'prepared':True,'prepare_receipt':None,'main_status':'READY','main_end':'2026-10-13','reason':'ORIGINAL_GUARD'}
    if scenario=='generated_waiting_owner':state['phase']='CHARTS_FINISHED';state['main_status']='AWAITING_OWNER_RECEIPT';state['main_end']=None
    elif scenario=='wrong_id':state['maintenance_id']='other_lease'
    elif scenario=='wrong_schema':state['schema']='OTHER'
    elif scenario=='dirty_cleanup':state['cleanup_verified']=False
    elif scenario=='workers_busy':state['workers_drained']=False
    elif scenario=='failed_chart':state['main_status']='BLOCKED'
    elif scenario=='wrong_end':state['main_end']='2026-10-12'
    elif scenario=='operation_unknown':state['main_status']='UNKNOWN'
    fixture=tmp_path/'chart.json';fixture.write_text(json.dumps(state),encoding='utf-8')
    code=_functions()+"""
$state=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8|ConvertFrom-Json
$script:posts=0;$script:gets=0
function Invoke-UstqComponentRequest {param($Path,$Method='GET',$Body,$Token)
 if($Method -eq 'POST'){
  if($Path -cne '/api/applied/charts-update' -or $Body.Count -ne 2 -or $Body.maintenance_id -cne 'synthetic_lease' -or $Body.expected_signal_date -cne '2026-10-13'){throw 'wrong chart command'}
  $script:posts++;if('__SCENARIO__' -eq 'post_timeout'){throw 'TRANSPORT_TIMEOUT_AFTER_ACCEPTANCE'}
 }else{if($Path -cne '/api/applied/maintenance-status'){throw 'cachedview used for controls'};$script:gets++}
 return @{ok=$true;data=$state}
}
$context=[pscustomobject]@{maintenance_id='synthetic_lease';token='synthetic-token';end_submitted=$false}
$accepted=$false;$failure='';try{$result=Update-UstqMainCharts -SignalDate '2026-10-13' -Context $context;$accepted=$true}catch{$failure=[string]$_.Exception.Message}
@{accepted=$accepted;failure=$failure;posts=$script:posts;gets=$script:gets}|ConvertTo-Json -Compress
""".replace('__INPUT__',str(fixture).replace("'","''")).replace('__SCENARIO__',scenario)
    result=_ps(code)
    assert result['posts']==1 and result['gets']==1
    assert result['accepted'] is (scenario in {'ready','cached_main','post_timeout','stop_override','generated_waiting_owner'})
    if not result['accepted']: assert result['failure']


@pytest.mark.parametrize('scenario', ['ready_running','ready_paused','half_running','wrong_id','not_drained','cleanup_unknown','begin_timeout'])
def test_begin_uses_owner_control_and_no_financial_start(tmp_path, scenario):
    running=scenario not in {'ready_paused'}
    state={'schema':'MANUAL_DAILY_MAINTENANCE_V1','maintenance_id':'FILL_FROM_REQUEST','phase':'PAUSED','active':True,
       'original_running':{'cohort':running,'broker':running},'restore_requested':running,
       'operation_active':False,'job_active':False,'workers_drained':scenario!='not_drained',
       'cleanup_verified':scenario!='cleanup_unknown'}
    if scenario=='half_running':state['original_running']['broker']=False
    fixture=tmp_path/'begin.json';fixture.write_text(json.dumps(state),encoding='utf-8')
    code=_functions()+"""
$script:state=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8|ConvertFrom-Json
$script:posts=[Collections.Generic.List[string]]::new();$script:begins=0
function Ensure-UstqSimulationService{return @{data=@{running=__RUNNING__;broker=@{running=__RUNNING__}}}}
function Invoke-UstqComponentRequest {param($Path,$Method='GET',$Body,$Token)
 if($Path -eq '/api/token'){return @{data=@{token='synthetic-token'}}}
 if($Method -eq 'POST'){
  $script:posts.Add($Path)
  if($Path -eq '/api/applied/reconcile'){return @{data=@{running=$false}}}
  if($Path -cne '/api/applied/maintenance-begin' -or $Body.Count -ne 1){throw 'not owner begin'}
  $script:begins++;$script:state.maintenance_id=$Body.maintenance_id
  if('__SCENARIO__' -eq 'wrong_id'){$script:state.maintenance_id='other_lease'}
  if('__SCENARIO__' -eq 'begin_timeout'){throw 'TIMEOUT_AFTER_ACCEPTANCE'}
 }elseif($Path -cne '/api/applied/maintenance-status'){throw 'view used for fresh controls'}
 return @{data=$script:state}
}
$accepted=$false;$failure='';try{$result=Begin-UstqDailyMaintenance;$accepted=$true}catch{$failure=[string]$_.Exception.Message}
@{accepted=$accepted;failure=$failure;begins=$script:begins;posts=@($script:posts.ToArray())}|ConvertTo-Json -Compress
""".replace('__INPUT__',str(fixture).replace("'","''")).replace('__RUNNING__','$true' if running else '$false').replace('__SCENARIO__',scenario)
    result=_ps(code)
    assert result['begins']==1
    assert result['accepted'] is (scenario in {'ready_running','ready_paused','begin_timeout'})
    assert result['posts']==(['/api/applied/reconcile'] if not running else [])+['/api/applied/maintenance-begin']


@pytest.mark.parametrize('scenario', ['running','paused','stop_override','abort','post_timeout','wrong_id','dirty_cleanup','duplicate_end','not_restored','paused_resumed','current_half','missing_completion_proof','wrong_final_end','unqualified_final_main','later_user_stop','later_user_start'])
def test_end_has_one_submit_and_no_guess_restore(tmp_path, scenario):
    state={'schema':'MANUAL_DAILY_MAINTENANCE_V1','maintenance_id':'synthetic_lease','phase':'FINISHED','active':False,
        'original_running':{'cohort':True,'broker':True},'restore_requested':scenario not in {'stop_override','abort'},
        'operation_active':False,'job_active':False,'workers_drained':True,'cleanup_verified':scenario!='dirty_cleanup'}
    state['main_status']='READY';state['main_end']='2026-10-13'
    state['cleanup_verified_before_resume']=scenario!='dirty_cleanup'
    state['resumed']=scenario in {'running','post_timeout'}
    state['current_running']={'cohort':state['resumed'],'broker':state['resumed']}
    if scenario=='paused':state['original_running']={'cohort':False,'broker':False};state['restore_requested']=False
    if scenario=='wrong_id':state['maintenance_id']='another_lease'
    elif scenario=='not_restored':state['resumed']=False;state['current_running']={'cohort':False,'broker':False}
    elif scenario=='paused_resumed':state['original_running']={'cohort':False,'broker':False};state['resumed']=True;state['current_running']={'cohort':True,'broker':True}
    elif scenario=='current_half':state['current_running']={'cohort':True,'broker':False}
    elif scenario=='missing_completion_proof':del state['cleanup_verified_before_resume']
    elif scenario=='wrong_final_end':state['main_end']='2026-10-12'
    elif scenario=='unqualified_final_main':state['main_status']='AWAITING_OWNER_RECEIPT'
    elif scenario=='later_user_stop':state['resumed']=True;state['current_running']={'cohort':False,'broker':False}
    elif scenario=='later_user_start':state['original_running']={'cohort':False,'broker':False};state['restore_requested']=False;state['resumed']=False;state['current_running']={'cohort':True,'broker':True}
    fixture=tmp_path/'end.json';fixture.write_text(json.dumps(state),encoding='utf-8')
    code=_functions()+"""
$state=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8|ConvertFrom-Json
$script:posts=0;$script:gets=0;$script:abort=$false
function Invoke-UstqComponentRequest{param($Path,$Method='GET',$Body,$Token)
 if($Method -eq 'POST'){
  if($Path -cne '/api/applied/maintenance-end' -or $Body.maintenance_id -cne 'synthetic_lease' -or @($Body.Keys|Where-Object{$_ -notin @('maintenance_id','abort')}).Count){throw 'arbitrary finish success/control field'}
  $script:posts++;$script:abort=($Body.abort -eq $true)
  if('__SCENARIO__' -eq 'post_timeout'){throw 'TIMEOUT_AFTER_ACCEPTANCE'}
 }else{$script:gets++;if($Path -cne '/api/applied/maintenance-status'){throw 'cachedview used to finish'}}
 return @{data=$state}
}
$context=[pscustomobject]@{maintenance_id='synthetic_lease';token='synthetic-token';end_submitted=('__SCENARIO__' -eq 'duplicate_end')}
$accepted=$false;$failure='';try{$result=End-UstqDailyMaintenance -Context $context -Abort:('__SCENARIO__' -eq 'abort') -SignalDate '2026-10-13';$accepted=$true}catch{$failure=[string]$_.Exception.Message}
@{accepted=$accepted;failure=$failure;posts=$script:posts;gets=$script:gets;abort=$script:abort;submitted=$context.end_submitted}|ConvertTo-Json -Compress
""".replace('__INPUT__',str(fixture).replace("'","''")).replace('__SCENARIO__',scenario)
    result=_ps(code)
    assert result['posts']==(0 if scenario=='duplicate_end' else 1)
    assert result['submitted']
    assert result['accepted'] is (scenario not in {'wrong_id','dirty_cleanup','duplicate_end','not_restored','paused_resumed','current_half','missing_completion_proof','wrong_final_end','unqualified_final_main'})
    if scenario=='abort':assert result['abort']


def test_mutation_budgets_are_finite_and_get_budget_unchanged():
    source=ENTRY.read_text(encoding='utf-8-sig')
    assert "'/api/applied/maintenance-begin' { 330 }" in source
    assert "'/api/applied/prepare-current' { 4500 }" in source
    assert "'/api/applied/charts-update' { 660 }" in source
    assert "'/api/applied/maintenance-end' { 660 }" in source
    assert 'default { 15 }' in source
    assert '4 * 1024 * 1024' in source
    assert 'maintenance_id=$Context.maintenance_id;expected_signal_date=$SignalDate' in source


@pytest.mark.parametrize("scenario", ["accepted", "v1", "old_books", "missing_binding", "ids_drift", "active_drift", "binding_drift", "unavailable"])
def test_prepared_receipt_uses_real_accepted_roster_reader(tmp_path, scenario):
    """Keep the real PS reader/validator; fake only the fixed metadata GET."""
    selected = ["RAW_A2", "HGB_DIAG_5", "R7_GROSS_LINEAR", "R6_DURATION_TREE", "R10_DIRECT_H5_RIDGE_MID"]
    manifest = dict(schema_version=1, kind="SHOWCASE_PAPER_ROSTER_V1", revision_id="synthetic-R1",
        created_at_utc="2026-10-01T01:00:00Z", effective_at_utc="2026-10-01T02:00:00Z",
        showcase_ids=list(selected), source_ref={"path":str((tmp_path/"metrics.json").resolve()),"sha256":"a"*64},
        evaluation_window=dict(sample="test_2026", initialization_signal_date="2026-01-02",
            first_execution_date="2026-01-05", end="2026-09-25", selection_status="POST_EXPOSURE_DISPLAY_SELECTION"),
        ranking_rule=dict(primary="annualized_sharpe_desc", comparisons=["total_return","max_drawdown"], fixed_ids_excluded=True),
        new_book_policy="INDEPENDENT_CASH_10000_FROM_ACCEPTANCE", retired_book_policy="PAUSE_PRESERVE_HISTORY", broker_permission_granted=False)
    ref={"path":str((tmp_path/"roster.json").resolve()),"sha256":"b"*64}
    binding=dict(schema_version=1,revision_number=1,roster_ref=ref,manifest=manifest,accepted_at_utc="2026-10-01T03:00:00Z",
        previous_binding_sha256=None,legacy_membership_binding_sha256="c"*64,legacy_active_strategy_ids=list(IDS),
        retained_book_ids=list(dict.fromkeys((*IDS,"R6_DURATION_TREE"))),created_book_ids=["R6_DURATION_TREE"])
    roster=dict(books={},metadata_only=True,active_strategy_ids=list(selected),showcase_ids=list(selected),
        roster_ref=ref,showcase_roster_binding=binding)
    receipt_ids = list(IDS) if scenario in ("v1", "old_books") else selected
    if scenario == "v1": roster=dict(books={},metadata_only=True,active_strategy_ids=list(IDS),showcase_ids=list(IDS),roster_ref=None)
    elif scenario == "missing_binding": del roster["showcase_roster_binding"]
    elif scenario == "ids_drift": roster["showcase_ids"]=list(IDS)
    elif scenario == "active_drift": roster["active_strategy_ids"]=list(IDS)
    elif scenario == "binding_drift": roster["showcase_roster_binding"]["manifest"]["broker_permission_granted"]=True
    receipt=dict(action="PREPARE_CURRENT_PUBLISHED_INPUTS",status="READY",signal_date="2026-10-13",execution_date="2026-10-14",
        orders_created=0,running=False,books={sid:dict(status="READY",signal_date="2026-10-13",execution_date="2026-10-14") for sid in receipt_ids},
        broker=dict(action="PREPARE_CURRENT_PUBLISHED_INPUTS",prepared=True,status="READY",strategy_id="R10_DIRECT_H5_RIDGE_MID",
            signal_date="2026-10-13",execution_date="2026-10-14",orders_created=0,running=False))
    fixture=tmp_path/"roster_metadata.json";fixture.write_text(json.dumps(dict(roster=roster,receipt=receipt,scenario=scenario)),encoding="utf8")
    code=_functions()+"""
$case=Get-Content -LiteralPath '__INPUT__' -Raw -Encoding UTF8 | ConvertFrom-Json
$paths=[pscustomobject]@{python_exe='__PYTHON__'}
$script:calls=[Collections.Generic.List[string]]::new()
function Invoke-UstqComponentRequest {
 param($Path,$Method='GET',$Body,$Token)
 $script:calls.Add($Method+':'+$Path)
 if($Path -cne '/api/applied/showcase-roster' -or $Method -cne 'GET'){throw 'unexpected read or mutation'}
 if($case.scenario -ceq 'unavailable'){throw 'SYNTHETIC_OWNER_UNAVAILABLE'}
 return @{ok=$true;data=$case.roster}
}
$accepted=$false;$failure=''
try{Assert-UstqPreparedReceipt -Receipt $case.receipt -SignalDate '2026-10-13';$accepted=$true}catch{$failure=[string]$_.Exception.Message}
@{accepted=$accepted;failure=$failure;calls=@($script:calls.ToArray())}|ConvertTo-Json -Compress
""".replace('__INPUT__',str(fixture).replace("'","''")).replace('__PYTHON__',sys.executable.replace("'","''"))
    result=_ps(code)
    assert result['accepted'] is (scenario in ('accepted','v1'))
    assert result['calls']==['GET:/api/applied/showcase-roster']
    if not result['accepted']: assert result['failure']


@pytest.mark.parametrize('mode,code,expected_status', [
    ('ready', 0, 'READY'), ('blocked', 7, 'BLOCKED'),
    ('missing', 0, None), ('multi', 0, 'READY')])
def test_daily_action_stream_preserves_progress_terminal_results_and_native_exit(tmp_path, mode, code, expected_status):
    emitter = tmp_path / 'synthetic action.py'
    counter = tmp_path / 'calls.txt'
    emitter.write_text("""import json,sys
from pathlib import Path
counter=Path(sys.argv[3])
counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')
print('synthetic non-JSON progress',flush=True)
print('{broken',flush=True)
print(json.dumps({'event':'progress','message':'synthetic progress'}),flush=True)
if sys.argv[1]=='multi':
 print(json.dumps({'event':'result','result':{'status':'OLD','marker':1}}),flush=True)
if sys.argv[1]!='missing':
 print(json.dumps({'event':'result','result':{'status':'BLOCKED' if sys.argv[1]=='blocked' else 'READY','marker':2,'nested':{'unchanged':True}}}),flush=True)
sys.exit(int(sys.argv[2]))
""", encoding='utf-8')
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    arguments = ','.join(quote(value) for value in ('-X', 'utf8', '-B', emitter, mode, code, counter))
    script = _functions() + "\n$paths=@{python_exe=" + quote(sys.executable) + "}\n"
    script += "$action=Invoke-UstqDailyAction -Arguments @(" + arguments + ")\n"
    script += "@{result=$action.result;exit_code=$action.exit_code;objects=@($action).Count}|ConvertTo-Json -Compress -Depth 8"
    result = _ps(script)
    assert result['exit_code'] == code and result['objects'] == 1
    assert counter.read_text() == '1'
    if expected_status is None:
        assert result['result'] is None
    else:
        assert result['result'] == {'status': expected_status, 'marker': 2, 'nested': {'unchanged': True}}
