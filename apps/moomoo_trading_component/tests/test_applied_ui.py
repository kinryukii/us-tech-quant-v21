"""Render synthetic applied state in Node; no HTTP, broker, SDK or runtime reads."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

SCRIPT = Path(__file__).parents[1] / "moomoo_component/static/applied.js"
HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',clientWidth:640,before(){},remove(){},addEventListener(){}});return nodes.get(id);}
const source=fs.readFileSync(process.argv[1],'utf8'),cut=source.indexOf("\n$('refresh').addEventListener");
if(cut<0)throw Error('Missing bootstrap boundary');
const fixture=JSON.parse(process.argv[2]),before=JSON.stringify(fixture);
const context={fixture,document:{getElementById:node,createElement:()=>node('created'),querySelectorAll:()=>[]},Intl,Date};
vm.runInNewContext(source.slice(0,cut)+'\nrender(fixture);',context);
if(before!==JSON.stringify(fixture))throw Error('Renderer mutated input state');
process.stdout.write(JSON.stringify({books:node('books').innerHTML,positions:node('positions').innerHTML,broker:node('broker-panel').innerHTML,trades:node('trades').innerHTML,nav:node('nav-chart').innerHTML,legend:node('strategy-legend').innerHTML,filters:node('trade-strategy').innerHTML,legacy:node('legacy-books').innerHTML,title:node('workspace-title').textContent,policy:node('execution-policy').textContent,subtitle:node('workspace-subtitle').textContent}));
"""


ASYNC_HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const nodes=new Map(),timers=new Map(),requests=[],responses=[];
let nextTimer=1,inFlight=0,maxInFlight=0;
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',clientWidth:640,before(){},remove(){},addEventListener(){}});return nodes.get(id);}
const source=fs.readFileSync(process.argv[1],'utf8'),cut=source.indexOf("\n$('refresh').addEventListener");
if(cut<0)throw Error('Missing bootstrap boundary');
const fixture=JSON.parse(process.argv[3]);
const context={fixture,nodes,timers,requests,responses,document:{getElementById:node,createElement:()=>node('created'),querySelectorAll:()=>[]},Intl,Date,AbortController,
 setTimeout(fn,ms){const id=nextTimer++;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
 flush:()=>new Promise(resolve=>setImmediate(resolve)),
 response:data=>({ok:true,status:200,json:async()=>({ok:true,data})}),
 fetch(path,opt){requests.push({path,method:opt.method||'GET',hasSignal:!!opt.signal});inFlight++;maxInFlight=Math.max(maxInFlight,inFlight);
   return new Promise((resolve,reject)=>{responses.push({resolve,reject});opt.signal?.addEventListener('abort',()=>reject(Error('Aborted')));}).finally(()=>{inFlight--;});},
 getMaxInFlight:()=>maxInFlight};
Promise.resolve(vm.runInNewContext(source.slice(0,cut)+'\n'+process.argv[2],context)).then(result=>process.stdout.write(JSON.stringify(result))).catch(error=>{process.stderr.write(String(error));process.exitCode=1;});
"""


def fixture():
    return {"running": True, "status": "WAITING_OPEN", "signal_date": "2026-01-07",
        "execution_date": "2026-01-08", "books": [{"strategy_id": "RAW_A2", "status": "WAITING_OPEN",
        "plan": {"signal_date": "2026-01-07", "rows": [{"code": "US.ALPHA", "target_weight": .5}]},
        "plan_metadata": {"signal_date": "2026-01-07", "execution_date": "2026-01-08"},
        "planned_actions": [{"code": "US.ALPHA", "side": "BUY", "current_qty": 0}],
        "execution": {"signal_date": "2026-01-07", "execution_date": "2026-01-08",
            "processed_codes": ["US.ALPHA"], "execution_decisions": [{"code": "US.ALPHA", "qty_before": 0,
                "qty_after": 5, "target_qty": 5, "reason": "FILLED"}], "skipped": []}}]}


class AppliedUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node is needed for the isolated renderer test")
        # Resolve launchers such as Volta before passing the multi-line VM harness.
        probe = subprocess.run([cls.node, "-p", "process.execPath"], check=True,
            capture_output=True, encoding="utf-8", timeout=10)
        cls.node = probe.stdout.strip()
        if not Path(cls.node).is_file():
            raise RuntimeError("Node launcher did not resolve an executable")

    def render(self, state):
        result = subprocess.run([self.node, "-e", HARNESS, str(SCRIPT), json.dumps(state)],
            check=True, capture_output=True, encoding="utf-8", timeout=10)
        return json.loads(result.stdout)

    def run_async(self, code):
        result=subprocess.run([self.node,"-e",ASYNC_HARNESS,str(SCRIPT),code,json.dumps(fixture())],
            check=True,capture_output=True,encoding="utf-8",timeout=10)
        return json.loads(result.stdout)

    def test_refresh_is_single_flight_and_schedules_after_completion(self):
        result=self.run_async("""(async()=>{
          const first=refresh(),joined=refresh();await flush();
          const before={calls:requests.length,timers:timers.size};
          responses.shift().resolve(response({...fixture,version:1}));await first;
          return {same:first===joined,before,calls:requests.length,max:getMaxInFlight(),
            timers:[...timers.values()].map(t=>t.ms),version:snapshot.version,text:nodes.get('snapshot-sync').textContent};
        })()""")
        assert result["same"] and result["before"]["calls"]==1
        assert result["before"]["timers"]==1  # Only the bounded GET deadline is pending.
        assert result["calls"]==result["max"]==1
        assert result["timers"]==[15000] and result["version"]==1
        assert "最近成功读取" in result["text"]

    def test_forced_read_discards_older_response_without_parallel_gets(self):
        result=self.run_async("""(async()=>{
          const first=refresh();await flush();const forced=refresh(true);
          responses.shift().resolve(response({...fixture,version:1}));await flush();
          const discarded=snapshot===null,calls=requests.length;
          responses.shift().resolve(response({...fixture,version:2}));await forced;
          return {discarded,calls,max:getMaxInFlight(),version:snapshot.version};
        })()""")
        assert result=={"discarded":True,"calls":2,"max":1,"version":2}

    def test_failed_read_keeps_snapshot_and_marks_last_success_stale_in_chinese(self):
        result=self.run_async("""(async()=>{
          const first=refresh();responses.shift().resolve(response({...fixture,version:1}));await first;
          const second=refresh();responses.shift().reject(Error('Failed to fetch'));await second;
          return {version:snapshot.version,text:nodes.get('snapshot-sync').textContent,
            error:nodes.get('error').textContent,timers:[...timers.values()].map(t=>t.ms)};
        })()""")
        assert result["version"]==1 and result["timers"]==[15000]
        assert "最近成功读取" in result["text"] and "数据待更新" in result["text"]
        assert "上次成功读取" in result["text"]
        assert "暂时无法连接模拟盘服务" in result["error"] and "Failed to fetch" not in result["error"]

    def test_get_deadline_aborts_once_and_post_failure_never_retries(self):
        result=self.run_async("""(async()=>{
          const get=api('/api/applied/view').catch(e=>e.message);
          [...timers.values()][0].fn();const message=await get;
          token='synthetic-token';const post=api('/api/applied/mark',{}).catch(e=>e.message);
          const pendingPost=requests.at(-1),postTimers=timers.size;
          responses.at(-1).reject(Error('Failed to fetch'));await post;
          return {message,pendingPost,postTimers,requests:requests.length,timers:timers.size};
        })()""")
        assert "超过 15 秒" in result["message"]
        assert result["pendingPost"]=={"path":"/api/applied/mark","method":"POST","hasSignal":False}
        assert result["postTimers"]==0 and result["requests"]==2 and result["timers"]==0

    def test_successful_snapshot_becomes_explicitly_stale_without_new_data(self):
        result=self.run_async("""(async()=>{
          const first=refresh();responses.shift().resolve(response(fixture));await first;
          renderReadFreshness(lastSuccessAt+STALE_AFTER_MS);
          return {text:nodes.get('snapshot-sync').textContent,calls:requests.length};
        })()""")
        assert "数据待更新" in result["text"] and result["calls"]==1

    def test_server_busy_snapshot_uses_original_capture_time_and_recovers_fresh(self):
        result=self.run_async("""(async()=>{
          const captured='2026-01-07T20:01:00+00:00';
          const first=refresh();responses.shift().resolve({ok:true,status:200,json:async()=>({ok:true,data:fixture,
            display:{status:'STALE',owner_busy:true,captured_at_utc:captured}})});await first;
          const old={at:lastSuccessAt,stale:lastReadFailed,text:nodes.get('snapshot-sync').textContent};
          const next=refresh();responses.shift().resolve({ok:true,status:200,json:async()=>({ok:true,data:fixture,
            display:{status:'CURRENT',owner_busy:false,captured_at_utc:new Date().toISOString()}})});await next;
          return {old,currentFailed:lastReadFailed,text:nodes.get('snapshot-sync').textContent};
        })()""")
        assert result["old"]["at"]==1767816060000 and result["old"]["stale"] is True
        assert "后台状态读取暂忙" in result["old"]["text"] and "上次成功读取" in result["old"]["text"]
        assert result["currentFailed"] is False and "账户状态已成功读取" in result["text"]

    def test_resource_floor_exact_code_has_plain_display_note_without_mutating_reason(self):
        state=fixture();state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"BLOCKED",
            "reason":"CONSENSUS_RESOURCE_FLOOR","last_error":"CONSENSUS_RESOURCE_FLOOR"}
        html=self.render(state)["broker"]
        self.assertIn("可用内存不足；保留现仓，等待资源恢复后核验新目标。",html)
        self.assertIn("原始状态说明",html)
        self.assertIn("CONSENSUS_RESOURCE_FLOOR",html)
        self.assertEqual(state["broker"]["reason"],"CONSENSUS_RESOURCE_FLOOR")
        self.assertEqual(state["broker"]["last_error"],"CONSENSUS_RESOURCE_FLOOR")
    def test_resource_floor_prefix_and_other_error_text_are_not_translated(self):
        state=fixture();state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"BLOCKED",
            "reason":"CONSENSUS_RESOURCE_FLOOR:DETAIL","last_error":"OTHER_SOURCE_CODE"}
        html=self.render(state)["broker"]
        self.assertIn("CONSENSUS_RESOURCE_FLOOR:DETAIL",html)
        note=self.run_async("notes('CONSENSUS_RESOURCE_FLOOR:DETAIL','OTHER_SOURCE_CODE')")
        self.assertEqual(note,"CONSENSUS_RESOURCE_FLOOR:DETAIL · 上次检查：OTHER_SOURCE_CODE")
        self.assertNotIn("可用内存不足",html)

    def test_five_books_all_visible_and_retired_history_separate(self):
        state = fixture()
        ids = ("RAW_A2", "HGB_DIAG_5", "R10_DIRECT_MEAN4_ELASTICNET_MID",
            "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
        state["books"] = [{**state["books"][0], "strategy_id": sid, "account_id": "paper-" + sid,
            "nav_history": [{"asof": "2026-01-08T14:31:00+00:00", "nav": 1.01}]} for sid in ids]
        state["legacy_history"] = {"books": {"HGB_FACTOR_5": {"strategy_id": "HGB_FACTOR_5",
            "account_id": "paper-HGB_FACTOR_5", "cash": 321, "equity": 9999, "positions": []}}}
        state["broker"] = {"strategy_id": "R7_GROSS_LINEAR", "account_id": "original-sim",
            "strategy_binding": {"previous_strategy_id": "HGB_DIAG_5"}}
        result = self.render(state)
        for name in ("ElasticNet MID", "Ridge H5 MID", "R7 LINEAR"):
            for field in ("positions", "legend", "filters", "nav"):
                self.assertIn(name, result[field])
        self.assertEqual(result["title"], "模拟盘")
        self.assertIn("5 套独立纸面账户", result["subtitle"])
        self.assertIn("HGB＋因子／收缩风险", result["legacy"])
        self.assertNotIn("HGB＋因子／收缩风险", result["positions"])
        self.assertIn("HGB_FACTOR_5", result["filters"])
        self.assertIn("MOOMOO 模拟账户 · R7 LINEAR", result["broker"])
        self.assertIn("original-sim", result["broker"])
        self.assertIn("既有持仓按新目标做差额调整", result["broker"])

    def test_original_broker_primary_target_current_and_exit_are_distinct(self):
        state = fixture()
        state["broker"] = {"strategy_id":"R7_GROSS_LINEAR", "account_id":"original-sim", "budget":10000,
            "status":"WAITING_OPEN", "running":True, "cash":250., "equity":1000.,
            "execution_time_utc":"2026-01-08T14:30:00+00:00", "execution_delay_minutes":0, "execution_window_seconds":600,
            "plan":{"signal_date":"2026-01-07", "target_cash_weight":.25, "rows":[
                {"code":"US.ALPHA", "target_weight":.25, "action":"BUY"},
                {"code":"US.BETA", "target_weight":.25, "action":"BUY"},
                {"code":"US.GAMMA", "target_weight":.25, "action":"BUY"},
                {"code":"US.EXITONE", "target_weight":0., "action":"SELL"},
                {"code":"US.EXITTWO", "target_weight":0., "action":"SELL"}]},
            "positions":{"US.ALPHA":{"qty":2,"market_value":150.},"US.EXITONE":{"qty":5,"market_value":350.},
                "US.ORPHAN":{"qty":3,"market_value":250.}}, "orders":[], "order_count":0}
        result=self.render(state);html=result["broker"]
        self.assertIn("original-sim",html)
        self.assertIn('3 <span class="metric-divider">/</span> 3',html)
        self.assertIn('href="#broker-exit-targets">2 只</a>；1 只仍有持仓',html)
        self.assertIn("+10.00%",html)
        self.assertEqual(html.count("SELL · 退出目标"),2)
        self.assertIn("其他持仓或目标",html)
        self.assertIn("ORPHAN",html)
        self.assertNotIn("HOLD · 保持",html)
        self.assertLess(html.index("目标股票 / 已持有"),html.index("常规开盘窗口"))
        self.assertIn('id="broker-positive-targets" class="targets-details" open',html)
        self.assertNotIn('id="broker-orders" class="orders-details" open',html)
        shell=SCRIPT.with_name("applied.html").read_text(encoding="utf-8")
        self.assertLess(shell.index('id="broker-panel"'),shell.index('id="paper-overview"'))
        self.assertLess(shell.index('id="paper-overview"'),shell.index('id="execution-policy"'))
        self.assertLess(shell.index('id="broker-panel"'),shell.index('class="clock"'))

    def test_order_confirmation_and_status_remain_separate_from_target(self):
        for status,running in (("WAITING_OPEN",True),("WAITING_QUOTES",True),("PARTIALLY_EXECUTED",True),("STOPPED",False)):
            with self.subTest(status=status):
                state=fixture()
                state["broker"]={"strategy_id":"R7_GROSS_LINEAR", "status":status, "running":running,
                    "positions":[], "plan":{"signal_date":"2026-01-07", "target_cash_weight":1.,"rows":[]},
                    "orders":[{"code":"US.ALPHA","side":"BUY","qty":5,"status":"SUBMITTED","order_type":"MARKET"}],"order_count":1}
                html=self.render(state)["broker"]
                self.assertIn('class="broker-history-count">1 / 0',html)
                self.assertIn("待确认 1 笔",html)
                self.assertIn("待券商确认",html)
                self.assertIn("只计入已确认的成交数量",html)
                self.assertNotIn("券商模拟已成交",html)
                if not running:
                    self.assertIn("自动执行暂停",html)

    def test_waiting_source_keeps_verified_target_and_is_not_quote_wait_or_execution(self):
        state=fixture()
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"WAITING_SOURCE","running":True,
            "reason":"SOURCE_REFRESH_BUSY","positions":[], "cash":10000.,"equity":10000.,
            "plan":{"signal_date":"2026-01-07","target_cash_weight":.5,"rows":[
                {"code":"US.ALPHA","target_weight":.5,"action":"TARGET"}]}}
        html=self.render(state)["broker"]
        self.assertIn("等待数据源核验",html)
        self.assertIn("ALPHA",html)
        self.assertIn("50.00%",html)
        self.assertIn("SOURCE_REFRESH_BUSY",html)
        self.assertNotIn("等待合格报价",html)
        self.assertNotIn("本期计划已执行",html)
        self.assertNotIn("券商模拟已成交",html)

    def manual_fixture(self, status="ACTIVE"):
        state=fixture()
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"STOPPED","running":False,
            "execution_date":"2026-07-06","execution_delay_minutes":0,"execution_window_seconds":600,
            "execution_time_utc":"2026-07-06T13:30:00+00:00",
            "execution_deadline_utc":"2026-07-06T15:45:00+00:00",
            "ordinary_execution_time_utc":"2026-07-06T13:30:00+00:00",
            "ordinary_execution_deadline_utc":"2026-07-06T13:40:00+00:00",
            "cash":10000.,"equity":10000.,"positions":[],"plan":{"signal_date":"2026-07-02","rows":[
                {"code":"US.ALPHA","target_weight":1.,"action":"TARGET"}]},
            "published_target_manual_completion":{"schema":"OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1",
                "status":status,"strategy_id":"R7_GROSS_LINEAR","manual_id":"manual_fixture_1","signal_date":"2026-07-02",
                "execution_date":"2026-07-06","authorized_at_utc":"2026-07-06T15:30:00+00:00",
                "deadline_utc":"2026-07-06T15:45:00+00:00"}}
        return state

    def test_manual_window_and_regular_open_window_are_independent(self):
        html=self.render(self.manual_fixture())["broker"]
        regular=html.split('<div class="broker-session">',1)[1].split('</div></div>',1)[0]
        manual=html.split('<p id="broker-manual-completion"',1)[1].split('</p>',1)[0]
        self.assertIn("常规开盘窗口 · 纽约",regular)
        self.assertIn("美东 07/06 09:30:00 → 07/06 09:40:00",regular)
        self.assertIn("日本 07/06 22:30:00 → 07/06 22:40:00",regular)
        self.assertIn("常规执行规则",regular)
        self.assertIn("开盘后 0–10 分钟严格窗口",regular)
        self.assertNotIn("11:45:00",regular)
        self.assertIn("本次手动补单 · 授权有效",manual)
        self.assertIn("美东 07/06 11:30:00 → 07/06 11:45:00",manual)
        self.assertIn("日本 07/07 00:30:00 → 07/07 00:45:00",manual)
        self.assertIn("补单记录 manual_fixture_1",manual)
        self.assertNotIn("开盘",manual)
        self.assertNotIn("严格窗口",manual)
        self.assertIn("已暂停",html)
        self.assertIn("ALPHA",html)
        self.assertNotIn("券商模拟已成交",html)
        self.assertNotIn("<button",html)

    def test_manual_status_is_owner_record_and_never_predicted_from_fixture_date(self):
        for status, text in (("ACTIVE","授权有效"),("EXPIRED","已截止"),("COMPLETED","本次补单已执行")):
            with self.subTest(status=status):
                html=self.render(self.manual_fixture(status))["broker"]
                self.assertIn("本次手动补单 · "+text,html)
                if status=="EXPIRED":
                    main=html.split('<details id="broker-rules"',1)[0]
                    self.assertIn("补单授权已截止；旧窗口不授予本期补单权限",main)
                self.assertIn("实际成交以券商对账为准",html)
                self.assertNotIn("持仓转换 · 已完成",html)
                self.assertNotIn("全部成交",html)
                self.assertNotIn("预计",html)

    def test_missing_or_invalid_manual_record_does_not_imply_permission(self):
        for update in ({"schema":"UNKNOWN"},{"status":"UNKNOWN"},{"strategy_id":"RAW_A2"},{"signal_date":"2026-01-01"},
                {"execution_date":"2026-07-07"},{"deadline_utc":"2026-07-06T15:29:00+00:00"},
                {"authorized_at_utc":"2026-07-06T15:30:00"},{"manual_id":""}):
            with self.subTest(update=update):
                state=self.manual_fixture();state["broker"]["published_target_manual_completion"].update(update)
                html=self.render(state)["broker"]
                self.assertIn("本次手动补单 · 待核验",html)
                self.assertNotIn("本次手动补单 · 授权有效",html)
                self.assertIn("美东 07/06 09:30:00 → 07/06 09:40:00",html)
        for absent in (None, {}):
            state=self.manual_fixture();state["broker"]["published_target_manual_completion"]=absent
            html=self.render(state)["broker"]
            self.assertNotIn('id="broker-manual-completion"',html)
            self.assertNotIn("本次手动补单 · 授权有效",html)

    def previous_manual_fixture(self):
        state=self.manual_fixture("COMPLETED")
        state.update(status="REFRESHING",signal_date="2026-07-06",execution_date="2026-07-07")
        b=state["broker"]
        b.update(status="BLOCKED",execution_date="2026-07-07",plan=None,
            last_error="CONSENSUS_CURRENT_PUBLICATION_REQUIRED",positions={"US.OLD":{"qty":2,"market_value":50.}})
        r=b["published_target_manual_completion"]
        r.update(deadline_utc="2026-07-06T15:40:00+00:00",session_close_utc="2026-07-06T20:00:00+00:00",
            published_target_sha256="a"*64,receipt_sha256="b"*64,alignment_id="alignment_fixture_1")
        b["published_target_alignment"]={"schema":"PUBLISHED_TARGET_ALIGNMENT_R1","strategy_id":"R7_GROSS_LINEAR",
            "signal_date":"2026-07-02","execution_date":"2026-07-06","published_target_sha256":"a"*64,
            "request":{"alignment_id":"alignment_fixture_1","expected_strategy_id":"R7_GROSS_LINEAR",
                "signal_date":"2026-07-02","expected_target_sha256":"a"*64}}
        b["published_target_conversion"]={"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1",
            "strategy_id":"R7_GROSS_LINEAR","status":"COMPLETED",
            "last_signal_date":"2026-07-02","last_execution_date":"2026-07-06"}
        return state

    def test_previous_manual_completion_is_history_and_never_current_completion(self):
        html=self.render(self.previous_manual_fixture())["broker"]
        note=html.split('<p id="broker-manual-completion"',1)[1].split('</p>',1)[0]
        self.assertIn("上期补单已完成（信号07/02→执行07/06）",note)
        self.assertIn("当前下期目标待发布",note)
        self.assertIn("旧窗口不授予本期补单权限",note)
        self.assertNotIn("待核验",note)
        self.assertNotIn("授权有效",note)
        self.assertNotIn("本次补单已执行",note)
        self.assertNotIn("本期计划已执行",html)
        self.assertNotIn("整数股与资金规则产生的余款保留在账户",html)
        self.assertIn("剩余现金保留在账户",html)
        self.assertIn("目标计划尚未核验",html)
        self.assertNotIn('id="broker-positive-table"',html)
        self.assertIn("OLD",html)
        self.assertNotIn("<button",html)

    def test_previous_manual_completion_rejects_mismatched_or_malformed_bindings(self):
        updates=[("manual",{"status":"ACTIVE"}),("manual",{"status":"EXPIRED"}),
            ("manual",{"strategy_id":"RAW_A2"}),("manual",{"alignment_id":"other"}),
            ("manual",{"published_target_sha256":"c"*64}),("manual",{"receipt_sha256":"bad"}),
            ("manual",{"signal_date":"2026-07-01"}),("manual",{"execution_date":"2026-07-07"}),
            ("manual",{"signal_date":"2026-02-30"}),("manual",{"manual_id":""}),
            ("manual",{"authorized_at_utc":"2026-07-06T15:30:00"}),
            ("manual",{"deadline_utc":"2026-07-06T15:30:00+00:00"}),
            ("manual",{"deadline_utc":"2026-07-06T15:40:01+00:00"}),
            ("manual",{"authorized_at_utc":"2026-07-05T15:30:00+00:00","deadline_utc":"2026-07-05T15:40:00+00:00"}),
            ("manual",{"session_close_utc":"2026-07-06T15:39:00+00:00"}),
            ("manual",{"session_close_utc":None}),("alignment",{"schema":"UNKNOWN"}),
            ("alignment",{"strategy_id":"RAW_A2"}),("alignment",{"published_target_sha256":"c"*64}),
            ("alignment",{"signal_date":"2026-07-01"}),("alignment",{"execution_date":"2026-07-07"}),
            ("request",{"expected_strategy_id":"RAW_A2"}),("request",{"alignment_id":"other"}),
            ("request",{"signal_date":"2026-07-01"}),("request",{"expected_target_sha256":"c"*64})]
        for kind,update in updates:
            with self.subTest(kind=kind,update=update):
                state=self.previous_manual_fixture();b=state["broker"]
                target=(b["published_target_manual_completion"] if kind=="manual" else
                    b["published_target_alignment"] if kind=="alignment" else b["published_target_alignment"]["request"])
                target.update(update)
                html=self.render(state)["broker"]
                self.assertIn("本次手动补单 · 待核验",html)
                self.assertNotIn("上期补单已完成",html)
                self.assertNotIn("本期计划已执行",html)
                self.assertNotIn("本次手动补单 · 授权有效",html)

    def test_previous_manual_completion_with_later_plan_does_not_claim_unpublished_or_current_done(self):
        state=self.previous_manual_fixture();b=state["broker"]
        b.update(status="WAITING_OPEN",plan={"signal_date":state["signal_date"],"execution_date":state["execution_date"],
            "rows":[{"code":"US.NEXT","target_weight":.5,"action":"TARGET"}]})
        html=self.render(state)["broker"]
        note=html.split('<p id="broker-manual-completion"',1)[1].split('</p>',1)[0]
        self.assertIn("上期补单已完成（信号07/02→执行07/06）",note)
        self.assertIn("本记录不代表本期执行状态",note)
        self.assertIn("旧窗口不授予本期补单权限",note)
        self.assertNotIn("目标待发布",note)
        self.assertNotIn("本次补单已执行",note)
        self.assertNotIn("授权有效",note)
        self.assertNotIn("本期计划已执行",html)
        self.assertNotIn("整数股与资金规则产生的余款保留在账户",html)
        self.assertIn("目标持仓 <span>1 只",html)
        self.assertIn("NEXT",html)
        self.assertIn("50.00%",html)
        self.assertNotIn("<button",html)

    def test_previous_manual_completion_requires_known_later_owner_cycle(self):
        for signal,execution in ((None,None),("2026-07-02","2026-07-06"),("2026-07-01","2026-07-07"),
                ("2026-07-06","2026-07-06"),("2026-02-30","2026-07-07")):
            with self.subTest(signal=signal,execution=execution):
                state=self.previous_manual_fixture();state.update(signal_date=signal,execution_date=execution)
                html=self.render(state)["broker"]
                self.assertIn("本次手动补单 · 待核验",html)
                self.assertNotIn("上期补单已完成",html)

    def test_current_manual_completion_is_visible_with_weight_and_integer_counts(self):
        state=self.manual_fixture("COMPLETED");b=state["broker"]
        b["strategy_id"]="R10_DIRECT_H5_RIDGE_MID"
        b["published_target_manual_completion"]["strategy_id"]=b["strategy_id"]
        b["plan"].update(status="READY",execution_status="TARGET_ONLY",target_cash_weight=.43,
            rows=[{"code":f"US.SYN{i}","target_weight":.03,"action":"TARGET"} for i in range(19)])
        b.update(cash=4285.,equity=10000.,positions={f"US.SYN{i}":{"qty":1,"market_value":350.} for i in range(16)},
            orders=[{"code":f"US.SYN{i}","side":"BUY","qty":1,"dealt_qty":1,"dealt_avg_price":350.,
                     "status":"FILLED_ALL"} for i in range(11)])
        html=self.render(state)["broker"]
        summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
        self.assertIn("2026-07-02",summary)
        self.assertIn("本期计划已完成",summary)
        self.assertIn('未完成委托</span><strong>0 <small>笔</small>',summary)
        self.assertIn("仅统计最近返回的委托",summary)
        self.assertLess(html.index('id="broker-plan-summary"'),html.index('class="broker-compare"'))
        self.assertIn('19 <span class="metric-divider">/</span> 16',html)
        self.assertIn("目标内未持有 3 只",html)
        self.assertIn("部分正权重目标可能不足一股",html)
        self.assertIn("未持有项保留原目标",html)
        self.assertNotIn("全部目标已买齐",html)
        self.assertNotIn("本期目标待执行",summary)

    def test_native_manual_owner_completion_uses_source_plan_execution_date(self):
        state=self.manual_fixture("COMPLETED");b=state["broker"]
        b["strategy_id"]="R10_DIRECT_H5_RIDGE_MID"
        b["plan"].update(execution_date=b.pop("execution_date"),status="READY",execution_status="TARGET_ONLY")
        b["published_target_manual_completion"].update(schema="OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1",
            strategy_id=b["strategy_id"],authorized_at_utc="2026-07-07T00:30:00+09:00",
            deadline_utc="2026-07-07T00:39:55+09:00")
        b["orders"]=[]
        html=self.render(state)["broker"]
        summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
        self.assertIn("本期计划已完成",summary)
        self.assertIn("2026-07-02",summary)
        self.assertIn('未完成委托</span><strong>0 <small>笔</small>',summary)
        self.assertIn("本次手动补单 · 本次补单已执行",html)
        self.assertIn("整数股与资金规则产生的余款保留在账户",html)
        self.assertNotIn("计划待处理",summary)
        self.assertNotIn("当前记录缺少可确认的授权窗口或身份",html)

    def test_native_manual_active_and_expired_keep_existing_window_display(self):
        for status,text in (("ACTIVE","本次手动补单 · 授权有效"),("EXPIRED","补单授权已截止")):
            with self.subTest(status=status):
                state=self.manual_fixture(status);b=state["broker"]
                b["plan"]["execution_date"]=b.pop("execution_date")
                b["published_target_manual_completion"]["schema"]="OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1"
                html=self.render(state)["broker"]
                self.assertIn(text,html)
                self.assertNotIn("本期计划已完成",html)
                self.assertNotIn("当前记录缺少可确认的授权窗口或身份",html)

    def test_both_manual_owner_schemas_require_current_plan_and_strategy(self):
        for schema in ("OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1","OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1"):
            for mismatch in ("plan_execution","signal","strategy","schema","invalid_date","top_execution"):
                with self.subTest(schema=schema,mismatch=mismatch):
                    state=self.manual_fixture("COMPLETED");b=state["broker"];r=b["published_target_manual_completion"]
                    b["plan"]["execution_date"]=b.pop("execution_date");r["schema"]=schema
                    if mismatch=="plan_execution": b["plan"]["execution_date"]="2026-07-07"
                    elif mismatch=="signal": r["signal_date"]="2026-07-01"
                    elif mismatch=="strategy": r["strategy_id"]="RAW_A2"
                    elif mismatch=="schema": r["schema"]="UNKNOWN_OWNER_COMPLETION_R1"
                    elif mismatch=="invalid_date": r["execution_date"]="2026-02-30"
                    else: b["execution_date"]="2026-07-07"
                    html=self.render(state)["broker"]
                    summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
                    self.assertNotIn("本期计划已完成",summary)
                    self.assertNotIn("整数股与资金规则产生的余款保留在账户",html)
                    self.assertIn("当前记录缺少可确认的授权窗口或身份",html)

    def test_done_or_stale_manual_record_cannot_establish_current_completion(self):
        for mode in ("done_only","stale_manual","other_strategy"):
            with self.subTest(mode=mode):
                state=self.manual_fixture("COMPLETED");b=state["broker"];b["orders"]=[]
                if mode=="done_only":
                    b["status"]="DONE";b.pop("published_target_manual_completion")
                elif mode=="stale_manual":
                    b["published_target_manual_completion"]["signal_date"]="2026-07-01"
                else:
                    b["published_target_manual_completion"]["strategy_id"]="RAW_A2"
                html=self.render(state)["broker"]
                summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
                self.assertIn("计划待处理",summary)
                self.assertNotIn("本期计划已完成",summary)

    def test_unfinished_order_takes_priority_over_completed_record(self):
        for status in ("SUBMITTED","PENDING_RECONCILE","UNKNOWN","FILLED_PART"):
            with self.subTest(status=status):
                state=self.manual_fixture("COMPLETED");b=state["broker"]
                b["orders"]=[{"code":"US.ALPHA","side":"BUY","qty":5,"dealt_qty":2,"status":status},
                    {"code":"US.BETA","side":"BUY","qty":1,"status":"CANCELLED_ALL"}]
                html=self.render(state)["broker"]
                summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
                self.assertIn("等待券商对账",summary)
                self.assertIn('未完成委托</span><strong>1 <small>笔</small>',summary)
                self.assertNotIn("本期计划已完成",summary)

    def test_missing_or_unknown_order_records_do_not_claim_zero_unfinished(self):
        for records in (None,[{"code":"US.ALPHA","status":"UNRECOGNIZED_STATUS"}]):
            with self.subTest(records=records):
                state=self.manual_fixture("COMPLETED");state["broker"]["orders"]=records
                html=self.render(state)["broker"]
                summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
                self.assertIn('未完成委托</span><strong>— <small>笔</small>',summary)

    def test_completed_cash_note_uses_current_owner_evidence(self):
        for evidence in ("manual","conversion","broker"):
            with self.subTest(evidence=evidence):
                state=self.manual_fixture("COMPLETED");b=state["broker"]
                if evidence!="manual":
                    b["published_target_manual_completion"]={}
                if evidence=="conversion":
                    b["published_target_conversion"]={"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1",
                        "strategy_id":"R7_GROSS_LINEAR","status":"COMPLETED",
                        "last_signal_date":"2026-07-02","last_execution_date":"2026-07-06"}
                if evidence=="broker":
                    b["status"]="EXECUTED"
                html=self.render(state)["broker"]
                self.assertIn("整数股与资金规则产生的余款保留在账户",html)
                self.assertNotIn("未完成买入的资金仍留在账户",html)
                self.assertIn("ALPHA",html)

    def test_incomplete_or_stale_owner_evidence_does_not_explain_cash_as_completed(self):
        for stale in (False,True):
            with self.subTest(stale=stale):
                state=self.manual_fixture();b=state["broker"]
                b["published_target_conversion"]={"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1",
                    "strategy_id":"R7_GROSS_LINEAR","status":"COMPLETED" if stale else "ACTIVE",
                    "last_signal_date":"2026-01-01" if stale else "2026-07-02",
                    "last_execution_date":"2026-01-02" if stale else "2026-07-06"}
                html=self.render(state)["broker"]
                self.assertIn("剩余现金保留在账户",html)
                self.assertNotIn("整数股与资金规则产生的余款保留在账户",html)

    def test_cash_summary_only_uses_recorded_current_unfilled_buy(self):
        for status in ("SUBMITTED","PENDING_RECONCILE","FILLED_PART"):
            with self.subTest(status=status):
                state=self.manual_fixture();b=state["broker"]
                b["orders"]=[{"code":"US.ALPHA","side":"BUY","qty":5,"dealt_qty":2,"status":status,
                    "signal_date":"2026-07-02","execution_date":"2026-07-06"}]
                html=self.render(state)["broker"]
                self.assertIn("未完成买入的资金仍留在账户",html)
                self.assertNotIn("整数股与资金规则产生的余款保留在账户",html)

    def test_cash_summary_does_not_infer_pending_buy_from_old_or_incomplete_evidence(self):
        updates=({"side":"SELL"},{"strategy_id":"RAW_A2"},{"signal_date":"2026-07-01"},
            {"execution_date":"2026-07-07"},{"signal_date":None},{"execution_date":None},
            {"status":"FILLED_ALL"},{"status":"FAILED"},{"status":"UNKNOWN"},
            {"qty":0},{"dealt_qty":5},{"dealt_qty":None},{"qty":"5"})
        for update in updates:
            with self.subTest(update=update):
                state=self.manual_fixture();b=state["broker"]
                order={"code":"US.ALPHA","side":"BUY","qty":5,"dealt_qty":2,"status":"SUBMITTED",
                    "signal_date":"2026-07-02","execution_date":"2026-07-06"};order.update(update);b["orders"]=[order]
                html=self.render(state)["broker"]
                self.assertIn("剩余现金保留在账户",html)
                self.assertNotIn("未完成买入的资金仍留在账户",html)
        state=self.previous_manual_fixture();state["broker"]["orders"]=[{"code":"US.ALPHA","side":"BUY","qty":5,"dealt_qty":2,
            "status":"SUBMITTED","signal_date":"2026-07-02","execution_date":"2026-07-06"}]
        html=self.render(state)["broker"]
        self.assertIn("上期补单已完成",html)
        self.assertIn("剩余现金保留在账户",html)
        self.assertNotIn("未完成买入的资金仍留在账户",html)

    def test_book_completion_labels_bind_to_current_or_previous_plan_clock(self):
        ids=("RAW_A2","HGB_DIAG_5","R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR")
        for previous in (False,True):
            with self.subTest(previous=previous):
                state=fixture();base=state["books"][0]
                state["books"]=[{**base,"strategy_id":sid,"status":"PARTIALLY_EXECUTED" if i==0 else "EXECUTED",
                    "execution":{**base["execution"],"status":"PARTIALLY_EXECUTED" if i==0 else "EXECUTED"}} for i,sid in enumerate(ids)]
                if previous:state.update(signal_date="2026-01-08",execution_date="2026-01-09")
                output=self.render(state);prefix="上期" if previous else "本期"
                for scope in ("books","positions"):
                    html=output[scope]
                    self.assertEqual(html.count(prefix+"部分执行"),1)
                    self.assertEqual(html.count(prefix+"计划已执行"),4)
                    self.assertIn("信号 2026-01-07 · 执行 2026-01-08",html)
                    self.assertNotIn(("本期" if previous else "上期")+"计划已执行",html)

    def test_book_completion_does_not_label_missing_invalid_or_future_targets_done(self):
        for invalid in ("missing","empty","bad_weight","bad_date","future","unknown_view"):
            with self.subTest(invalid=invalid):
                state=fixture();b=state["books"][0];b["status"]="EXECUTED";b["execution"]["status"]="EXECUTED"
                if invalid=="missing":b["plan"]=None
                elif invalid=="empty":b["plan"]={**b["plan"],"rows":[]}
                elif invalid=="bad_weight":b["plan"]={**b["plan"],"rows":[{"code":"US.ALPHA","target_weight":None}]}
                elif invalid=="bad_date":b["plan"]={**b["plan"],"signal_date":"2026-02-30"}
                elif invalid=="future":b["plan"]={**b["plan"],"signal_date":"2026-01-08","execution_date":"2026-01-09"}
                else:state["signal_date"]=None
                output=self.render(state)
                for scope in ("books","positions"):
                    self.assertIn("执行批次待核验",output[scope])
                    self.assertNotIn("计划已执行",output[scope])
                    self.assertNotIn("部分执行",output[scope])

    def test_new_targets_and_previous_execution_have_independent_dates_even_when_paused(self):
        ids=("RAW_A2","HGB_DIAG_5","R7_GROSS_LINEAR")
        for projected in (False,True):
            with self.subTest(projected=projected):
                state=fixture();base=state["books"][0]
                state.update(running=False,status="STOPPED",signal_date="2026-01-08",execution_date="2026-01-09")
                state["books"]=[{**base,"strategy_id":sid,"status":"TARGET_ONLY" if projected else ("PARTIALLY_EXECUTED" if i==0 else "EXECUTED"),
                    "plan":{**base["plan"],"signal_date":"2026-01-08"},
                    "plan_metadata":{"signal_date":"2026-01-08","execution_date":"2026-01-09"},
                    "execution":{**base["execution"],"status":"PARTIALLY_EXECUTED" if i==0 else "EXECUTED"}}
                    for i,sid in enumerate(ids)]
                output=self.render(state)
                for scope in ("books","positions"):
                    html=output[scope]
                    self.assertNotIn("本期计划已执行",html);self.assertNotIn("本期部分执行",html)
                    self.assertEqual(html.count("上期计划已执行"),2);self.assertEqual(html.count("上期部分执行"),1)
                    self.assertIn("信号 2026-01-07 · 执行 2026-01-08",html)
                    if projected:
                        self.assertEqual(html.count("本期目标待执行"),3)
                        self.assertIn("信号 2026-01-08 · 执行 2026-01-09",html)

    def test_completion_label_requires_actual_batch_status_and_dates(self):
        for invalid in ("missing_batch","missing_status","wrong_status","missing_signal","missing_execution","invalid_date","future_batch"):
            with self.subTest(invalid=invalid):
                state=fixture();b=state["books"][0];b["status"]="EXECUTED";b["execution"]["status"]="EXECUTED"
                if invalid=="missing_batch":b["execution"]=None
                elif invalid=="missing_status":b["execution"].pop("status")
                elif invalid=="wrong_status":b["execution"]["status"]="WAITING_OPEN"
                elif invalid=="missing_signal":b["execution"].pop("signal_date")
                elif invalid=="missing_execution":b["execution"].pop("execution_date")
                elif invalid=="invalid_date":b["execution"]["execution_date"]="2026-02-30"
                else:b["execution"].update(signal_date="2026-01-08",execution_date="2026-01-09")
                output=self.render(state)
                for scope in ("books","positions"):
                    self.assertIn("执行批次待核验",output[scope])
                    self.assertNotIn("计划已执行",output[scope]);self.assertNotIn("部分执行",output[scope])

    def test_owner_conversion_active_retains_current_target_and_execution_state(self):
        state=fixture()
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"STOPPED","running":False,
            "positions":{"US.OLD":{"qty":9,"market_value":90.}}, "cash":910., "equity":1000.,
            "plan":{"signal_date":"2026-01-07","rows":[
                {"code":"US.ALPHA","target_weight":1.,"action":"TARGET"},
                {"code":"US.OLD","target_weight":0.,"action":"SELL"}]},
            "published_target_conversion":{"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1",
                "strategy_id":"R7_GROSS_LINEAR","status":"ACTIVE"}}
        html=self.render(state)["broker"]
        self.assertIn("持仓转换 · 尚未完成",html)
        self.assertIn("后续合格信号在正常执行窗口按当期已冻结目标继续差额调仓",html)
        self.assertIn("已暂停",html)
        self.assertIn("ALPHA",html)
        self.assertIn("SELL · 退出目标",html)
        self.assertIn("目标外剩余 1 只",html)
        self.assertNotIn("持仓转换 · 已完成",html)
        self.assertNotIn("恢复当前所选策略的常规调仓",html)
        self.assertNotIn("预计",html)
        self.assertNotIn("<button",html)

    def test_owner_conversion_completed_describes_normal_strategy_without_claiming_all_fills(self):
        state=fixture()
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"WAITING_OPEN","positions":[],
            "plan":{"rows":[{"code":"US.ALPHA","target_weight":1.,"action":"TARGET"}]},
            "published_target_conversion":{"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1",
                "strategy_id":"R7_GROSS_LINEAR","status":"COMPLETED"}}
        html=self.render(state)["broker"]
        self.assertIn("持仓转换 · 已完成",html)
        self.assertIn("恢复当前所选策略的常规调仓",html)
        self.assertIn("等待计划执行",html)
        self.assertIn("ALPHA",html)
        self.assertNotIn("尚未完成",html)
        self.assertNotIn("全部成交",html)
        self.assertNotIn("本期计划已执行",html)

    def test_missing_or_unrecognized_conversion_does_not_upgrade_old_alignment(self):
        for conversion in (None, {}, {"status":"ACTIVE"},
                {"schema":"UNKNOWN","strategy_id":"R7_GROSS_LINEAR","status":"ACTIVE"},
                {"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1","strategy_id":"R7_GROSS_LINEAR","status":"UNKNOWN"},
                {"schema":"OWNER_PUBLISHED_TARGET_CONVERSION_R1","strategy_id":"RAW_A2","status":"ACTIVE"}):
            with self.subTest(conversion=conversion):
                state=fixture()
                state["broker"]={"strategy_id":"R7_GROSS_LINEAR","positions":[],
                    "plan":{"rows":[{"code":"US.ALPHA","target_weight":1.,"action":"TARGET"}]},
                    "published_target_alignment":{"schema":"PUBLISHED_TARGET_ALIGNMENT_R1"}}
                if conversion is not None:
                    state["broker"]["published_target_conversion"]=conversion
                html=self.render(state)["broker"]
                self.assertIn("持仓转换 · 待核验",html)
                self.assertIn("ALPHA",html)
                self.assertNotIn("后续合格信号",html)
                self.assertNotIn("持仓转换 · 已完成",html)

    def test_remaining_target_scope_is_broader_than_recorded_quote_failures(self):
        state=fixture()
        targets=[{"code":f"US.TARGET{i}","target_weight":.05,"action":"TARGET"} for i in range(20)]
        exits=[{"code":f"US.EXIT{i}","target_weight":0.,"action":"SELL"} for i in range(15)]
        positions={**{f"US.TARGET{i}":{"qty":2,"market_value":10.} for i in range(2)},
            **{f"US.EXIT{i}":{"qty":3,"market_value":20.} for i in range(9)}}
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"STOPPED","running":False,
            "cash":800.,"equity":1000.,"positions":positions,
            "plan":{"signal_date":"2026-01-07","execution_date":"2026-01-08","rows":targets+exits},
            "skipped_source":{"signal_date":"2026-01-07","execution_date":"2026-01-08"},
            "skipped":[{"code":f"US.EXIT{i}","reason":"quote_error"} for i in range(5)]}
        html=self.render(state)["broker"]
        self.assertIn('20 <span class="metric-divider">/</span> 11',html)
        self.assertIn("目标内持有 2 只 · 目标外剩余 9 只",html)
        self.assertIn("本期行情检查未通过项",html)
        self.assertNotIn("本期未执行股票",html)
        self.assertIn("完整计划与已返回的持仓范围",html)
        self.assertIn("EXIT8",html)
        self.assertIn("TARGET19",html)
        self.assertIn('TARGET19</td><td>0</td><td>—</td><td>5.00%</td><td>—</td>',html)
        self.assertIn("未记录市值的权重及差值保持未知",html)
        self.assertNotIn("可以买入",html)

    def test_recent_order_counts_and_same_window_tokyo_time_do_not_claim_total_history(self):
        state=fixture()
        state["broker"]={"strategy_id":"R7_GROSS_LINEAR","status":"WAITING_OPEN","order_count":174,
            "execution_time_utc":"2026-07-06T13:30:00+00:00","execution_window_seconds":600,
            "execution_deadline_utc":"2026-07-06T13:40:00+00:00","positions":[],
            "plan":{"signal_date":"2026-07-02","rows":[]}, "orders":[
                {"code":"US.ALPHA","side":"BUY","qty":1,"status":"FILLED_ALL"},
                {"code":"US.BETA","side":"BUY","qty":1,"status":"SUBMITTED"}]}
        html=self.render(state)["broker"]
        self.assertIn("历史委托 / 已确认成交",html)
        self.assertIn('class="broker-history-count">2 / 1',html)
        self.assertIn("显示最近 2 笔",html)
        self.assertIn("原账户完整历史保留在账本中",html)
        self.assertNotIn("174",html)
        self.assertNotIn("笔历史",html)
        self.assertIn("美东 07/06 09:30:00 → 07/06 09:40:00",html)
        self.assertIn("日本 07/06 22:30:00 → 07/06 22:40:00",html)
        state["broker"]["execution_time_utc"]="2026-01-08T14:30:00+00:00"
        state["broker"]["execution_deadline_utc"]="2026-01-08T14:40:00+00:00"
        self.assertIn("日本 01/08 23:30:00 → 01/08 23:40:00",self.render(state)["broker"])

    def test_automatic_completion_is_scoped_to_active_policy_members(self):
        state = fixture()
        ids = ("RAW_A2", "HGB_DIAG_5", "R10_DIRECT_MEAN4_ELASTICNET_MID",
            "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
        book = state["books"][0]
        book["execution"]["skipped"] = [{"code": "US.ALPHA", "reason": "current quote stale"}]
        state["books"] = [{**book, "strategy_id": sid} for sid in ids]
        state.update(execution_delay_minutes=0, execution_window_seconds=600,
            strategies=[{"strategy_id": sid, "active": True} for sid in ids],
            automatic_completion_policy={"enabled": True, "active_strategy_ids": ["HGB_DIAG_5", "HGB_FACTOR_5"],
                "effective_execution_date": "2026-01-08", "one_tick_spread": True})
        state["broker"] = {"strategy_id": "R7_GROSS_LINEAR", "automatic_completion_policy": None,
            "execution_delay_minutes": 0, "execution_window_seconds": 600,
            "execution_time_utc": "2026-01-08T14:30:00+00:00"}
        result = self.render(state)
        policy = result["policy"]
        self.assertIn("HGB＋对角风险 · 每日自动接续", policy)
        self.assertIn("一档最小价差总计≤200bp", policy.split("；", 1)[0])
        strict = policy.split("；", 1)[1]
        for name in ("Raw A2", "ElasticNet MID", "Ridge H5 MID", "R7 LINEAR"):
            self.assertIn(name, strict)
        self.assertIn("开盘后 0–10 分钟严格窗口", strict)
        self.assertNotIn("200bp", strict)
        self.assertNotIn("因子", policy)
        self.assertEqual(result["positions"].count("等待 · 行情不合格"), 1)
        self.assertEqual(result["positions"].count("跳过 · 行情不合格"), 4)
        rules=result["broker"].split('<details id="broker-rules"',1)[1].split('</details>',1)[0]
        self.assertIn("券商模拟独立执行规则 · R7 LINEAR",rules)
        self.assertIn("常规执行规则",rules)
        self.assertIn("开盘后 0–10 分钟严格窗口",rules)
        self.assertEqual(rules.count("开盘后 0–10 分钟严格窗口"),1)
        self.assertNotIn("自动接续", result["broker"])
        self.assertNotIn("200bp", result["broker"])

    def test_retired_or_unverified_policy_members_do_not_enable_automatic_labels(self):
        state = fixture()
        state.update(execution_delay_minutes=0, execution_window_seconds=600,
            strategies=[{"strategy_id": "RAW_A2", "active": False}],
            automatic_completion_policy={"enabled": True, "active_strategy_ids": ["RAW_A2"]})
        state["books"][0]["execution"]["skipped"] = [{"code": "US.ALPHA", "reason": "current quote stale"}]
        result = self.render(state)
        self.assertNotIn("自动接续", result["policy"])
        self.assertIn("跳过 · 行情不合格", result["positions"])
        state["strategies"][0]["active"] = True
        state["automatic_completion_policy"].pop("active_strategy_ids")
        result = self.render(state)
        self.assertNotIn("自动接续", result["policy"])
        self.assertIn("开盘后 0–10 分钟严格窗口", result["policy"])

    def test_mixed_nav_label_shows_observation_source_times_and_failed_code(self):
        state = fixture()
        state["books"][0]["nav_history"] = [{"date": "2026-01-08", "nav": 1.01,
            "asof": "2026-01-08T14:31:00+00:00", "held_asof_min": "2026-01-08T14:31:00+00:00",
            "held_asof_max": "2026-01-08T15:29:58+00:00", "observed_at_utc": "2026-01-08T15:30:00+00:00",
            "basis": "OBSERVED_MIXED_MARKS", "complete_live_coverage": False,
            "held_count": 2, "fresh_held_count": 1,
            "failed_quotes": [{"code": "US.ALPHA", "reason": "source stale <30s>"}]}]
        html = self.render(state)["nav"]
        for text in ("混合标价", "观测", "实际标价最早", "最晚", "1/2", "ALPHA", "source stale &lt;30s&gt;"):
            self.assertIn(text, html)
        self.assertNotIn("持仓报价全部通过本次检查", html)

    def test_all_failed_latest_attempt_does_not_relabel_old_nav_as_fresh(self):
        state = fixture()
        state["books"][0]["nav_history"] = [{"date": "2026-01-08", "nav": 1,
            "asof": "2026-01-08T14:31:00+00:00"}]
        state["books"][0]["valuation"] = {"observed_at_utc": "2026-01-08T15:30:00+00:00",
            "held_asof_min": "2026-01-08T14:31:00+00:00", "held_asof_max": "2026-01-08T14:31:00+00:00",
            "complete_live_coverage": False, "nav_recorded": False, "held_count": 1,
            "fresh_held_count": 0, "failed_quotes": [{"code": "US.ALPHA", "reason": "all source clocks stale"}]}
        html = self.render(state)["nav"]
        self.assertIn("本次未更新净值", html)
        self.assertIn("all source clocks stale", html)
        self.assertIn("0/1", html)
        self.assertIn("标价时间", html)

    def test_restart_without_account_snapshot_does_not_turn_unknown_positions_into_zero(self):
        state=fixture()
        state["broker"]={"strategy_id":"R10_DIRECT_H5_RIDGE_MID", "status":"STOPPED", "running":False,
            "cash":None,"equity":None,"positions":{},
            "plan":{"rows":[{"code":"US.SYN_TARGET","target_weight":.5,"action":"BUY"},
                            {"code":"US.SYN_EXIT","target_weight":0.,"action":"SELL"}]},
            "orders":[{"code":"US.SYN_HISTORY","status":"FILLED_ALL","side":"BUY","qty":3,
                       "dealt_qty":3,"dealt_avg_price":12.5}]}
        html=self.render(state)["broker"]
        self.assertIn("当前账户资金与持仓尚未核验",html)
        self.assertNotIn('class="broker-compare"',html)
        self.assertIn("预算，不代表实际现金",html)
        self.assertIn("历史委托 / 已确认成交",html)
        self.assertIn("SYN_TARGET</td><td>—</td>",html)
        self.assertNotIn("SYN_TARGET</td><td>0</td>",html)
        self.assertIn("SYN_HISTORY",html)
        self.assertIn("券商模拟已成交",html)

    def test_verified_empty_snapshot_remains_explicit_zero(self):
        state=fixture()
        state["broker"]={"strategy_id":"R10_DIRECT_H5_RIDGE_MID", "status":"STOPPED", "running":False,
            "cash":10000.,"equity":10000.,"positions":{},"orders":[],
            "plan":{"rows":[{"code":"US.SYN_TARGET","target_weight":.5,"action":"BUY"}]}}
        html=self.render(state)["broker"]
        self.assertNotIn("当前账户资金与持仓尚未核验",html)
        self.assertIn('1 <span class="metric-divider">/</span> 0',html)
        self.assertIn("SYN_TARGET</td><td>0</td>",html)

    def test_unknown_target_scope_keeps_exit_count_unknown_and_eight_history_orders(self):
        for plan in (None,{}, {"rows":None}):
            with self.subTest(plan=plan):
                state=fixture()
                state["broker"]={"strategy_id":"R10_DIRECT_H5_RIDGE_MID", "status":"STOPPED", "running":False,
                    "cash":10000.,"equity":10000.,"positions":{},"plan":plan,
                    "orders":[{"order_id":f"synthetic-history-{i}","code":f"US.SYN_HISTORY_{i}",
                        "status":"FILLED_ALL","side":"BUY","qty":1,"dealt_qty":1,"dealt_avg_price":10.}
                        for i in range(8)]}
                html=self.render(state)["broker"]
                self.assertIn('href="#broker-exit-targets">— 只</a>；— 只仍有持仓',html)
                self.assertIn("目标计划尚未核验",html)
                self.assertNotIn('id="broker-positive-table"',html)
                self.assertNotIn('id="broker-exit-table"',html)
                self.assertIn('8 <span class="metric-divider">/</span> 8',html)
                for i in range(8): self.assertIn(f"synthetic-history-{i}",html)

    def test_explicit_empty_target_scope_confirms_zero_exit_targets(self):
        for plan in ({"rows":[]},{"targets":{}}):
            with self.subTest(plan=plan):
                state=fixture()
                state["broker"]={"strategy_id":"R10_DIRECT_H5_RIDGE_MID", "status":"STOPPED", "running":False,
                    "cash":10000.,"equity":10000.,"positions":{},"orders":[],"plan":plan}
                html=self.render(state)["broker"]
                self.assertIn('href="#broker-exit-targets">0 只</a>；0 只仍有持仓',html)
                self.assertIn('退出目标 <span>0 只 · 原目标记录 SELL / 0%',html)

    def test_partial_native_snapshots_use_compact_state_and_preserve_eight_history_fills(self):
        for missing in ("cash","equity","positions"):
            with self.subTest(missing=missing):
                state=fixture();broker={"strategy_id":"R10_DIRECT_H5_RIDGE_MID","running":False,"status":"STOPPED",
                    "budget":10000.,"cash":0.,"equity":0.,"positions":{},"plan":None,
                    "orders":[{"order_id":f"compact-history-{i}","code":f"US.SYN_COMPACT_{i}","qty":1,
                        "dealt_qty":1,"dealt_avg_price":10.,"status":"FILLED_ALL","side":"BUY"} for i in range(8)]}
                broker.pop(missing);state["broker"]=broker
                html=self.render(state)["broker"]
                self.assertIn('class="account-unknown"',html)
                self.assertNotIn('class="broker-compare"',html)
                self.assertNotIn('class="account-metric"',html)
                self.assertIn("当前账户资金与持仓尚未核验",html)
                self.assertIn("策略预算",html);self.assertIn("$10,000",html)
                self.assertIn("预算，不代表实际现金",html)
                self.assertIn('class="broker-history-count">8 / 8',html)
                self.assertIn("历史委托 / 已确认成交",html)
                self.assertIn("历史记录不代表当前持仓",html)
                self.assertIn("已暂停",html);self.assertIn("实盘执行已锁定",html)
                self.assertIn("目标计划尚未核验",html)
                self.assertNotIn('id="broker-positive-table"',html)
                self.assertNotIn('id="broker-exit-table"',html)
                for i in range(8): self.assertIn(f"compact-history-{i}",html)

    def test_refresh_control_reads_existing_cache_without_mark_or_reconcile(self):
        script = SCRIPT.read_text(encoding="utf-8")
        control = script.split("async function refreshBroker()", 1)[1].split("async function action", 1)[0]
        self.assertIn("await refresh(true)", control)
        self.assertNotIn("/api/", control)
        self.assertNotIn("reconcile", control)

    def test_matching_batch_keeps_fill_satisfied_and_current_skip(self):
        state = fixture()
        self.assertIn("已成交", self.render(state)["positions"])
        state["books"][0]["execution"]["execution_decisions"][0]["reason"] = "TARGET_SATISFIED"
        self.assertIn("持仓已符合", self.render(state)["positions"])
        state["books"][0]["execution"]["skipped"] = [{"code": "US.ALPHA", "reason": "current quote stale"}]
        html = self.render(state)["positions"]
        self.assertIn("跳过 · 行情不合格", html)
        self.assertIn("current quote stale", html)

    def test_both_batch_dates_must_match_and_exist(self):
        for field, value in (("signal_date", "2026-01-06"), ("execution_date", "2026-01-09"),
                             ("signal_date", None), ("execution_date", None)):
            with self.subTest(field=field, value=value):
                state = fixture()
                state["books"][0]["execution"][field] = value
                html = self.render(state)["positions"]
                self.assertNotIn("已成交", html)
                self.assertNotIn("持仓已符合", html)
                self.assertIn(">BUY<", html)

    def test_historical_skip_cannot_override_new_action_and_retains_dates(self):
        state = fixture()
        old = state["books"][0]["execution"]
        old.update(signal_date="2026-01-05", execution_date="2026-01-06",
            skipped=[{"code": "US.ALPHA", "reason": "old quote stale"}])
        html = self.render(state)["positions"]
        self.assertIn(">BUY<", html)
        self.assertNotIn("跳过 · 行情不合格", html)
        self.assertIn("历史执行检查 · 信号 2026-01-05 · 执行 2026-01-06", html)
        self.assertIn("old quote stale", html)

    def test_missing_plan_clock_never_treats_execution_as_current(self):
        state = fixture()
        state["books"][0].pop("plan_metadata")
        self.assertNotIn("已成交", self.render(state)["positions"])

    def test_broker_undated_checks_remain_visible_without_current_cooldown(self):
        state = fixture()
        state["broker"] = {"strategy_id": "HGB_DIAG_5", "status": "WAITING_OPEN", "running": True,
            "plan": {"signal_date": "2026-01-07", "rows": []},
            "execution_time_utc": "2026-01-08T14:30:00+00:00", "execution_window_seconds": 600,
            "execution_deadline_utc": "2026-01-08T14:40:00+00:00",
            "skipped": [{"code": "US.ALPHA", "reason": "old/current origin unknown quote error",
                "retry_after_utc": "2026-01-06T14:35:00+00:00"}]}
        html = self.render(state)["broker"]
        self.assertIn("批次日期待核验", html)
        self.assertIn("origin unknown quote error", html)
        self.assertNotIn("本期行情检查未通过项", html)
        self.assertNotIn("data-retry-at", html)

    def test_broker_dated_current_and_history_checks_stay_distinct(self):
        state = fixture()
        state["broker"] = {"strategy_id": "HGB_DIAG_5", "status": "WAITING_OPEN", "running": True,
            "plan": {"signal_date": "2026-01-07", "execution_date": "2026-01-08", "rows": []},
            "execution_time_utc": "2026-01-08T14:30:00+00:00", "execution_window_seconds": 600,
            "execution_deadline_utc": "2026-01-08T14:40:00+00:00", "skipped": [
                {"code": "US.ALPHA", "reason": "historical quote failure", "signal_date": "2026-01-05",
                 "execution_date": "2026-01-06", "retry_after_utc": "2026-01-06T14:35:00+00:00"},
                {"code": "US.BETA", "reason": "current quote failure", "signal_date": "2026-01-07",
                 "execution_date": "2026-01-08", "retry_after_utc": "2026-01-08T14:35:00+00:00"}]}
        html = self.render(state)["broker"]
        self.assertIn("历史执行检查 · 信号 2026-01-05 · 执行 2026-01-06", html)
        self.assertIn("本期行情检查未通过项 · 信号 2026-01-07 · 执行 2026-01-08", html)
        self.assertIn("historical quote failure", html)
        self.assertIn("current quote failure", html)
        self.assertEqual(html.count("data-retry-at"), 1)

    def test_broker_skipped_source_binds_unmodified_rows_to_original_batch(self):
        state = fixture()
        state["broker"] = {"strategy_id": "HGB_DIAG_5", "status": "WAITING_OPEN", "running": True,
            "plan": {"signal_date": "2026-01-07", "rows": []},
            "execution_time_utc": "2026-01-08T14:30:00+00:00", "execution_window_seconds": 600,
            "execution_deadline_utc": "2026-01-08T14:40:00+00:00",
            "skipped_source": {"signal_date": "2026-01-05", "execution_date": "2026-01-06"},
            "skipped": [{"code": "US.ALPHA", "reason": "original batch quote failure",
                "retry_after_utc": "2026-01-06T14:35:00+00:00"}]}
        html = self.render(state)["broker"]
        self.assertIn("历史执行检查 · 信号 2026-01-05 · 执行 2026-01-06", html)
        self.assertNotIn("本期行情检查未通过项", html)
        self.assertNotIn("data-retry-at", html)
        state["broker"]["skipped_source"] = {"signal_date": "2026-01-07", "execution_date": "2026-01-08"}
        html = self.render(state)["broker"]
        self.assertIn("本期行情检查未通过项 · 信号 2026-01-07 · 执行 2026-01-08", html)
        self.assertIn("original batch quote failure", html)
        self.assertIn("data-retry-at", html)
