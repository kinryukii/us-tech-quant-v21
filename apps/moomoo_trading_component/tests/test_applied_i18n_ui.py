"""Isolated multilingual applied-UI checks with synthetic state; no HTTP or SDK."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

STATIC = Path(__file__).parents[1] / "moomoo_component/static"
HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const fixture=JSON.parse(process.argv[2]),copies=JSON.parse(process.argv[3]),query=process.argv[4],nodes=new Map();
function make(copy={}){return {innerHTML:'',textContent:copy.text||'',value:'',clientWidth:640,disabled:false,attrs:copy.attrs||{},before(){},remove(){},addEventListener(){},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];}};}
for(const copy of copies){const n=make(copy);copy.node=n;if(copy.attrs.id)nodes.set(copy.attrs.id,n);}
function node(id){if(!nodes.has(id))nodes.set(id,make());return nodes.get(id);}
const document={documentElement:{},body:{classList:{toggle(k,v){this[k]=v;}}},getElementById:node,createElement:()=>make(),
 querySelectorAll(selector){return copies.filter(c=>selector==='[data-ui]'?'data-ui' in c.attrs:selector==='[aria-label]'?'aria-label' in c.attrs:selector==='[placeholder]'?'placeholder' in c.attrs:false).map(c=>c.node);}};
const source=fs.readFileSync(process.argv[1],'utf8'),cut=source.indexOf("\n$('refresh').addEventListener");
if(cut<0)throw Error('Missing isolated bootstrap boundary');
const context={fixture,nodes,document,Intl,Date,URLSearchParams,location:{search:query}};
const before=JSON.stringify(fixture);
const result=vm.runInNewContext(source.slice(0,cut)+`\nrender(fixture);lastSuccessAt=Date.now();lastReadFailed=false;renderReadFreshness();
const initial={start:$('start').disabled,stop:$('stop').disabled,halt:$('halt').disabled};
busy=true;renderControls();const busyHalt=$('halt').disabled;busy=false;renderReadFreshness(lastSuccessAt+STALE_AFTER_MS);
({language:document.documentElement.lang,title:document.title,embedded:document.body.classList.embedded,presentation:document.body.classList.presentation,
 nodes:Object.fromEntries([...nodes].map(([id,n])=>[id,{text:n.textContent,html:n.innerHTML,disabled:n.disabled}])),
 initial,busyHalt,unknownLabel:label('UNRECOGNIZED_BACKEND'),rawNotes:notes(fixture.broker?.reason,fixture.broker?.last_error)})`,context);
result.static=copies.map(c=>({text:c.node.textContent,attrs:c.node.attrs}));
if(before!==JSON.stringify(fixture))throw Error('Renderer mutated source state');
process.stdout.write(JSON.stringify(result));
"""


class StaticCopies(HTMLParser):
    def __init__(self):
        super().__init__(); self.copies=[]; self.active=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if any(key in attrs for key in ("data-ui", "aria-label", "placeholder", "id")):
            self.active={"attrs":attrs,"text":""}; self.copies.append(self.active)
    def handle_data(self, data):
        if self.active is not None: self.active["text"]+=data
    def handle_endtag(self, tag):
        self.active=None


def synthetic_state():
    return {"running":False,"status":"STOPPED","books":[{"strategy_id":"R10_DIRECT_H5_RIDGE_MID",
        "account_id":"paper-synthetic","status":"WAITING_SOURCE","positions":[],"cash":0.,"equity":0.}],
        "broker":{"strategy_id":"R10_DIRECT_H5_RIDGE_MID","account_id":"synthetic-account",
        "status":"MISSED_OPEN","positions":None,"cash":None,"equity":None,
        "reason":"原始资金不足 SOURCE_REASON <raw>","last_error":"等待计划执行 RAW_LAST_ERROR",
        "plan":{"rows":[{"code":"US.SYNTHETIC_ID","target_weight":0.5,"action":"BUY"}]},
        "orders":[{"order_id":"historical-order-id","code":"US.OLD_SYMBOL_ID","side":"BUY",
            "status":"FILLED_ALL","qty":7,"filled_qty":7,"fill_price":10.} ]},
        "legacy_history":{"books":{"RETIRED_MODEL_ID":{"strategy_id":"RETIRED_MODEL_ID",
            "account_id":"retired-account","positions":[],"cash":0.,"equity":0.}}}}


class AppliedI18nUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launcher=shutil.which("node")
        if not launcher: raise unittest.SkipTest("Node is required for isolated UI validation")
        cls.node=subprocess.run([launcher,"-p","process.execPath"],check=True,capture_output=True,
            encoding="utf-8",timeout=10).stdout.strip()
        parser=StaticCopies(); parser.feed((STATIC/"applied.html").read_text(encoding="utf-8")); cls.copies=parser.copies

    def render(self,query,state=None):
        proc=subprocess.run([self.node,"-e",HARNESS,str(STATIC/"applied.js"),json.dumps(state or synthetic_state()),
            json.dumps(self.copies),query],check=False,capture_output=True,encoding="utf-8",timeout=10)
        if proc.returncode: raise AssertionError(proc.stderr[:2000])
        return json.loads(proc.stdout)

    def test_languages_cover_static_dynamic_and_preserve_original_sources(self):
        for lang,locale,title,refresh,unknown in (("zh","zh-CN","模拟盘","刷新","当前账户资金与持仓尚未核验"),
                ("en","en-US","Simulation","Refresh","Current account funds and positions are unverified"),
                ("ja","ja-JP","シミュレーション","更新","現在の口座資金・保有は未確認")):
            with self.subTest(lang=lang):
                result=self.render("?lang="+lang+"&embed=1")
                self.assertEqual(result["language"],locale); self.assertIn(title,result["title"])
                self.assertEqual(result["nodes"]["refresh"]["text"],refresh); self.assertTrue(result["embedded"])
                broker=result["nodes"]["broker-panel"]["html"]
                for text in (unknown,"原始资金不足 SOURCE_REASON &lt;raw&gt;","等待计划执行 RAW_LAST_ERROR",
                        "Ridge H5 MID","SYNTHETIC_ID","OLD_SYMBOL_ID","historical-order-id"):
                    self.assertIn(text,broker)
                self.assertEqual(result["unknownLabel"],"UNRECOGNIZED_BACKEND")
                self.assertIn("RETIRED_MODEL_ID",result["nodes"]["legacy-books"]["html"])
                self.assertTrue(result["initial"]["start"]); self.assertFalse(result["initial"]["halt"]); self.assertFalse(result["busyHalt"])
                self.assertIn('class="account-unknown"',broker)

    def test_fixed_strategy_ids_use_one_localized_label_across_every_display(self):
        ids=("RAW_A2","HGB_DIAG_5","R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR")
        raw_names={sid:"OWNER_RAW_"+sid+" HGB + 对角风险" for sid in ids}
        for lang,hgb in (("zh","HGB＋对角风险"),("en","HGB＋Diagonal risk"),("ja","HGB＋対角リスク")):
            with self.subTest(lang=lang):
                state=synthetic_state()
                state["books"]=[{"strategy_id":sid,"name":raw_names[sid],"account_id":"synthetic-"+sid,
                    "positions":[],"cash":10000.,"equity":10000.,"status":"STOPPED",
                    "nav_history":[{"asof":"2025-12-02T15:00:00Z","nav":1.0}]} for sid in ids]
                state["broker"].update(strategy_id="HGB_DIAG_5",name=raw_names["HGB_DIAG_5"])
                state["trades"]=[{"strategy_id":sid,"code":"US.SYN_LABEL_"+str(i),"side":"BUY",
                    "status":"FILLED","qty":1,"fill_price":10.,"filled_at":"2025-12-02T15:00:00Z"}
                    for i,sid in enumerate(ids)]
                result=self.render("?lang="+lang,state)
                expected=("Raw A2",hgb,"ElasticNet MID","Ridge H5 MID","R7 LINEAR")
                for field in ("books","positions","strategy-legend","trade-strategy","nav-chart","trades"):
                    html=result["nodes"][field]["html"]
                    for label in expected: self.assertIn(label,html,(lang,field,label))
                    for raw in raw_names.values(): self.assertNotIn(raw,html)
                self.assertIn(hgb,result["nodes"]["broker-panel"]["html"])
                self.assertIn(hgb,result["nodes"]["workspace-subtitle"]["text"])
                for sid in ids: self.assertIn('value="'+sid+'"',result["nodes"]["trade-strategy"]["html"])

    def test_unrecognized_strategy_preserves_its_owner_name_and_identifier(self):
        state=synthetic_state();sid="UNLISTED_OWNER_STRATEGY";name="保留原名 CUSTOM_OWNER_NAME"
        state["books"][0].update(strategy_id=sid,name=name,
            nav_history=[{"asof":"2025-12-02T15:00:00Z","nav":1.0}])
        state["broker"].update(strategy_id=sid,name=name)
        state["trades"]=[{"strategy_id":sid,"name":name,"code":"US.SYN_CUSTOM","status":"FILLED"}]
        for lang in ("zh","en","ja"):
            result=self.render("?lang="+lang,state)
            for field in ("books","positions","strategy-legend","trade-strategy","nav-chart","trades","broker-panel"):
                self.assertIn(name,result["nodes"][field]["html"],(lang,field))
            self.assertIn('value="'+sid+'"',result["nodes"]["trade-strategy"]["html"])

    def test_broker_plan_summary_and_sizing_note_are_localized_without_changing_controls(self):
        state=synthetic_state();b=state["broker"]
        b.update(status="STOPPED",running=False,cash=9000.,equity=10000.,positions={},
            execution_date="2026-01-08",orders=[])
        b["plan"].update(signal_date="2026-01-07",execution_date="2026-01-08")
        b["published_target_manual_completion"]={"schema":"OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1",
            "strategy_id":b["strategy_id"],"status":"COMPLETED","manual_id":"synthetic_manual",
            "signal_date":"2026-01-07","execution_date":"2026-01-08",
            "authorized_at_utc":"2026-01-08T15:00:00Z","deadline_utc":"2026-01-08T15:10:00Z"}
        for lang,completed,unfinished,sizing in (
                ("zh","本期计划已完成","未完成委托","部分正权重目标可能不足一股"),
                ("en","Current plan completed","Unfinished orders","A positive target may be below one share"),
                ("ja","当期計画は完了","未完了の注文","正の目標でも1株未満になる場合があります")):
            with self.subTest(lang=lang):
                result=self.render("?lang="+lang,state)
                html=result["nodes"]["broker-panel"]["html"]
                summary=html.split('id="broker-plan-summary"',1)[1].split('<p class="note broker-boundary"',1)[0]
                self.assertIn(completed,summary);self.assertIn(unfinished,summary)
                self.assertIn("2026-01-07",summary);self.assertIn(sizing,html)
                self.assertFalse(result["initial"]["start"])
                self.assertTrue(result["initial"]["stop"])
                self.assertFalse(result["initial"]["halt"])
                self.assertNotIn("<button",html)

    def test_missing_and_unsupported_language_preserve_default_chinese(self):
        for query in ("","?lang=fr","?lang=EN"):
            result=self.render(query)
            self.assertEqual(result["language"],"zh-CN"); self.assertEqual(result["nodes"]["refresh"]["text"],"刷新")
            self.assertFalse(result["embedded"])

    def test_verified_zero_account_can_start_but_stale_snapshot_cannot(self):
        state=synthetic_state(); state["broker"].update(positions={},cash=0.,equity=0.,status="STOPPED")
        result=self.render("?lang=en",state)
        self.assertFalse(result["initial"]["start"]); self.assertTrue(result["nodes"]["start"]["disabled"])
        self.assertNotIn('account-unknown',result["nodes"]["broker-panel"]["html"])
        self.assertIn('class="broker-compare"',result["nodes"]["broker-panel"]["html"])
        self.assertTrue(result["initial"]["stop"]); self.assertFalse(result["initial"]["halt"]); self.assertFalse(result["busyHalt"])

    def test_unknown_and_explicit_zero_exit_scope_use_selected_language(self):
        for lang,unknown,zero in (("zh","目标计划尚未核验","退出目标 <span>0 只"),
                ("en","Target plan is unverified","Exit targets <span>0 symbols"),
                ("ja","目標計画は未確認です","退出目標 <span>0 銘柄")):
            with self.subTest(lang=lang):
                state=synthetic_state();state["broker"]["plan"]=None
                html=self.render("?lang="+lang,state)["nodes"]["broker-panel"]["html"]
                self.assertIn(unknown,html);self.assertNotIn(zero,html)
                self.assertNotIn('id="broker-positive-table"',html)
                self.assertNotIn('id="broker-exit-table"',html)
                state["broker"]["plan"]={"rows":[]}
                html=self.render("?lang="+lang,state)["nodes"]["broker-panel"]["html"]
                self.assertIn(zero,html)

    def test_compact_unknown_and_grouped_source_details_in_all_languages(self):
        for lang,unknown,target,budget,history,raw_label in (
                ("zh","当前账户资金与持仓尚未核验","目标计划尚未核验","预算，不代表实际现金","历史委托 / 已确认成交","原始状态说明"),
                ("en","Current account funds and positions are unverified","Target plan is unverified","Budget; not actual cash","Historical orders / confirmed fills","Original status details"),
                ("ja","現在の口座資金・保有は未確認","目標計画は未確認です","予算であり、実際の現金残高ではありません","過去の注文 / 確認済み約定","元の状態説明")):
            with self.subTest(lang=lang):
                state=synthetic_state();b=state["broker"]
                b.update(running=False,status="STOPPED",budget=10000.,plan=None,
                    strategy_binding={"previous_strategy_id":"RAW_A2"},reason="原始资金不足 SOURCE_REASON <raw>",last_error="")
                html=self.render("?lang="+lang,state)["nodes"]["broker-panel"]["html"]
                before,detail=html.split('<details id="broker-rules"',1)
                detail,after=detail.split('</details>',1)
                for text in (unknown,target,budget,history): self.assertIn(text,before)
                self.assertNotIn('class="broker-compare"',html)
                self.assertNotIn('id="broker-positive-table"',html)
                self.assertIn(raw_label,detail)
                self.assertIn("原始资金不足 SOURCE_REASON &lt;raw&gt;",detail)
                self.assertNotIn("SOURCE_REASON",before+after)
                self.assertEqual(html.count("SOURCE_REASON"),1)
                binding={"zh":"原模拟账户已绑定","en":"Original simulation account bound to ","ja":"元のシミュレーション口座の連携先 "}[lang]
                self.assertIn(binding,detail)
                self.assertNotIn(binding,before+after)
                self.assertIn('id="broker-conversion"',detail)
                self.assertNotIn('id="broker-conversion"',before+after)
                self.assertNotIn(' open',detail.split('>',1)[0])
                window={"zh":"执行窗口待核验","en":"Execution window unverified","ja":"執行時間枠は未確認"}[lang]
                self.assertEqual(html.count(window),1)

    def test_view_whitelist_changes_density_and_default_details_only(self):
        state=synthetic_state();state["broker"].update(running=False,status="STOPPED",positions={},cash=0.,equity=0.)
        results={view:self.render("?lang=en&view="+view,state) for view in ("presentation","research","invalid")}
        self.assertTrue(results["presentation"]["presentation"])
        for view in ("research","invalid"):
            self.assertFalse(results[view]["presentation"])
            self.assertIn('id="broker-positive-targets" class="targets-details" open',results[view]["nodes"]["broker-panel"]["html"])
        present=results["presentation"]["nodes"]["broker-panel"]["html"]
        self.assertNotIn('id="broker-positive-targets" class="targets-details" open',present)
        for key in ("start","stop","halt"):
            self.assertEqual(results["presentation"]["initial"][key],results["research"]["initial"][key])
        state["broker"].update(cash=None,equity=None,plan=None)
        for view in ("presentation","research"):
            result=self.render("?lang=en&view="+view,state)
            before=result["nodes"]["broker-panel"]["html"].split('<details id="broker-rules"',1)[0]
            self.assertIn("Current account funds and positions are unverified",before)
            self.assertIn("live execution is locked",before)
            self.assertTrue(result["initial"]["start"])

    def test_localized_fixed_text_never_translates_backend_lookalikes(self):
        result=self.render("?lang=en")
        self.assertEqual(result["rawNotes"],"原始资金不足 SOURCE_REASON <raw> · Last check: 等待计划执行 RAW_LAST_ERROR")
        self.assertIn("Target positions",result["nodes"]["broker-panel"]["html"])
        self.assertIn("Trade records",[c["text"] for c in result["static"]])
        for copy in result["static"]:
            for text in (copy["text"],copy["attrs"].get("aria-label") or "",copy["attrs"].get("placeholder") or ""):
                self.assertIsNone(re.search("[\u3400-\u9fff]",text),text)


    def test_exact_waiting_reason_translates_three_languages_and_retains_raw_notes(self):
        fixed="等待启动；仅本地纸面记录"
        raw_last="SOURCE_LAST_ERROR <raw>"
        for lang,known,prefix,floor in (
                ("zh",fixed,"上次检查：","可用内存不足；保留现仓，等待资源恢复后核验新目标。"),
                ("en","Waiting to start; local paper records only","Last check: ","Insufficient available memory; keep current positions and verify new targets after resources recover."),
                ("ja","開始待ち。ローカルのペーパー記録のみ","前回の確認：","利用可能メモリが不足しています。現在の保有を維持し、回復後に新目標を確認します。")):
            with self.subTest(lang=lang):
                state=synthetic_state();state.update(reason=fixed,status="MISSED_OPEN",last_error=raw_last)
                result=self.render("?lang="+lang,state)
                self.assertEqual(result["nodes"]["reason"]["text"],known+" · "+prefix+raw_last)
                self.assertEqual(result["rawNotes"],"原始资金不足 SOURCE_REASON <raw> · "+prefix+"等待计划执行 RAW_LAST_ERROR")
                state["reason"]=fixed+" RAW_SUFFIX"
                self.assertEqual(self.render("?lang="+lang,state)["nodes"]["reason"]["text"],state["reason"]+" · "+prefix+raw_last)
                state["reason"]="CONSENSUS_RESOURCE_FLOOR"
                self.assertEqual(self.render("?lang="+lang,state)["nodes"]["reason"]["text"],floor+" · "+prefix+raw_last)


if __name__ == "__main__": unittest.main()
