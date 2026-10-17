"""C13 metadata-only delivery over its own frozen execution/evidence receipts.

No Raw, covariance, label, account or prior-result reader is introduced. Figures
consume only supplied role summaries; sparse diagnostics never become primary.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from scripts.common.storage_paths import assert_safe_output_path
from scripts.research.a2.training.selector_classical_risk import safe_d, pin, new_outputs
from scripts.research.a2.training.selector_challenge import sha, readj, putj, now
from scripts.research.a2.evaluation import selector_constrained_evidence as ev

STATUS = "C13_PARTIAL_SHARED_RISK_BLOCKED"
RESULT_INPUTS = ("SELECTION_EVIDENCE.json", "ROLE_DESCRIPTIVE_SUMMARY.json", "CONTROL_REUSE.json", "SOURCE_PRESERVATION.json")
RUN_INPUTS = ("FIT_LEDGER.json", "SOLVE_LEDGER.json", "SCORE_ASSEMBLY.json", "FINAL_DECISIONS_FREEZE.json", "EXECUTION_RECEIPT.json")
COUNTERS_2026 = ("fit2026_rows", "evaluation2026_rows", "outcome2026_reads", "new2026_state_estimations")


def require(ok, message):
    if not ok: raise ValueError(message)


def number(value):
    if isinstance(value, bool): return None
    try: x=float(value)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None


def fmt(value,digits=3):
    x=number(value)
    return "null（不能判定）" if x is None else f"{x:.{digits}f}"


def rows(summaries):
    if isinstance(summaries,list): return summaries
    if isinstance(summaries,dict) and isinstance(summaries.get("roles"),list): return summaries["roles"]
    raise ValueError("ROLE_SUMMARY_LIST_REQUIRED")


def slots(ledger):
    value=ledger.get("slots")
    if isinstance(value,dict): return list(value.values())
    if isinstance(value,list): return value
    return None


def actual_count(ledger,field="actual_backend_calls"):
    aliases={"actual_backend_calls":("actual_backend_calls","new_backend_fit_calls"),
             "actual_solver_calls":("actual_solver_calls","backend_entered_count")}
    for name in aliases.get(field,(field,)):
        explicit=ledger.get(name)
        if type(explicit) is int and explicit>=0: return explicit
    items=slots(ledger) if field=="actual_backend_calls" else ledger.get("events",slots(ledger))
    if isinstance(items,list):
        key="backend_entered"
        if all(type(item.get(key)) is bool for item in items): return sum(item[key] for item in items)
    return None


def by_family(fit,family):
    values=fit.get("by_family",{}).get(family)
    if isinstance(values,dict): return values.get("actual_backend_calls")
    if type(values) is int: return values
    items=slots(fit)
    if items is not None and all(type(s.get("backend_entered")) is bool for s in items):
        return sum(s["backend_entered"] for s in items if s.get("family",s.get("risk_family"))==family)
    if actual_count(fit)==0: return 0
    return None


def pooled_realized(row):
    value=row.get("realized_summary")
    if isinstance(value,list): return next((x for x in value if str(x.get("year"))=="POOLED"),{})
    if isinstance(value,dict):
        if isinstance(value.get("POOLED"),dict): return value["POOLED"]
        if value.get("year") in (None,"POOLED"): return value
    return {}


def realized_ratio(row):
    r=pooled_realized(row)
    selected=number(r.get("selected",{}).get("std_ddof1")); raw=number(r.get("raw",{}).get("std_ddof1"))
    return selected/raw if selected is not None and raw is not None and raw>0 else None


def short_history(q):
    states={s["record"]["as_of"]:s for s in q.get("state_refs",[]) if s.get("record",{}).get("method")=="SHR_HP"}
    per_refresh=[];uidset=set();total=0
    for at,s in sorted(states.items()):
        n=s.get("nominal_n");r=s["record"]
        if not isinstance(n,dict): continue
        short=[a for a,value in n.items() if type(value) is int and 10<=value<30]
        uidset.update(r["asset_uids"][a] for a in short);total+=len(short)
        finite=[value for value in n.values() if type(value) is int]
        per_refresh.append(dict(as_of=at,short_assets=len(short),min_nominal_n=min(finite) if finite else None,
            min_n_div5_proxy=min(s.get("overlap_n_div5_proxy",{}).values()) if isinstance(s.get("overlap_n_div5_proxy"),dict) else None))
    return dict(unique_uids=len(uidset) if per_refresh else None,state_asset_pairs=total if per_refresh else None,refreshes=per_refresh)


def render_report(design,q,ledger,assembly,evidence,summaries,controls,preservation,execution):
    """Pure rendering of supplied summaries. Missing evidence stays typed null."""
    rr=rows(summaries);items={r["candidate_id"]:r for r in rr};fit=ledger.get("fit",{});solve=ledger.get("solve",{})
    stat=evidence.get("bootstrap",{});short=short_history(q)
    groups={"alpha_decline":[],"pred_risk_lower_alpha_kept":[],"both_pred_improved":[],"both_realized_improved":[]}
    for r in rr:
        edge=number(r.get("mean_edge_bp"));risk=number(r.get("mean_predicted_variance_ratio"));real=realized_ratio(r);cid=r["candidate_id"]
        if edge is not None and edge<0: groups["alpha_decline"].append(cid)
        if risk is not None and risk<1 and edge is not None and edge>=0: groups["pred_risk_lower_alpha_kept"].append(cid)
        if risk is not None and risk<1 and edge is not None and edge>0: groups["both_pred_improved"].append(cid)
        if real is not None and real<1 and edge is not None and edge>0: groups["both_realized_improved"].append(cid)
    listing=lambda key: ", ".join(groups[key]) or "null（没有足够描述性字段，或未满足该点估计条件）"
    lines=["# C13 Raw 锚定经典风险与约束选股：详细交付报告","",
        f"**终态：`{STATUS}`。新 C13 primary numeric=0；累计 numeric=147、exposure=226。没有完整共同 OOF，不能宣称 selector 或风险效率获得正式支持，也不能将不完整实验解释成统计负结论。**","",
        "本轮保留 Raw A2 为 alpha anchor，Raw1–10 固定，Raw11–20 是 incumbent，Raw21–40 是 challenger，只改变最后10个 membership slots。最终始终20只、下游 equal/reference policy 不变；不学习 q、Gross、Cash、持有动作、执行、账户或 RL。",
        "风险矩阵由 B 既有 owner 所有。C 只消费带 source/version/SHA、UID/epoch、资产原始顺序、cutoff、H5 与原生 cadence 的 exact state；没有第二风险平台，没有无证据 prior padding、矩阵缩放伪造 H3/H10/H20 或新数据管线。",
        "所有开发、source qualification、拟合状态及评价严格 pre2026。2023/2024/2025 全部保留，原752日历和732共同成熟日期不缩短。2025及旧研究已经暴露，不重新称独立 holdout；冻结历史研究仍是 mechanism-only，strict_PIT_promotion_eligible=false。","",
        "## 一、按任务书30个问题逐项回答","",
        f"1. **本次真正训练/估计的风险状态**：实际新 backend 调用 {fmt(actual_count(fit),0)}。既有 bank 的 metadata 状态引用 {len(q.get('state_refs',[]))} 条不是本次 fit。实际反序列化/消费次数：{fmt(execution.get('state_artifact_deserializations',execution.get('reused_state_count')),0)}；charged reservation：{fmt(fit.get('charged_reservations',fit.get('charged_learned_reservations')),0)}。不把 solves、已有模型或未调用计划算成训练。",
        "2. **DIAG/Sample/LW/OAS/CC/EWMA 数量**：见下方18族表，分别报告本次实际调用和 exact-reuse 资格；不能用 bank 中相近模型冒充对应方法。",
        "3. **PCA/factor/QQQ/FF48 数量**：见18族表。R08可用部分日期；R09不能用原生 SHR_FACTOR 冒充 QQQ+FF48 hierarchical：recipe不同，Jan2023全部FF48缺失，后续仍有缺失和 market-only fallback。",
        "4. **GARCH/GJR 数量**：见18族表。本次没有可供 C 完整消费的 exact full-U 记录时保留 BLOCKED_INPUT，不换成低阶波动率代理。",
        "5. **downside/CVaR 数量**：见18族表。没有合格完整 scenario/tail 输入的规则不运行；未安装新的 EVT 大依赖。",
        "6. **regime 状态数量**：见18族表。未从本轮结果挑高/低波动阈值、状态数或新的 cadence。",
        "7. **jackknife/disagreement 数量**：见18族表。R3 RU 的 sigma SE 不是完整 replica covariance uncertainty set；R3 RE 的 LW/OAS/PCA/RB 组合也不是本轮固定 LW/OAS/Factor/EWMA，不能悄悄替代。",
        "8. **hierarchical posterior/EB 数量**：R17/R18 native whole-state exact reuse；见18族表和覆盖表。posterior风险遵循原 owner predictive covariance，参数不由本轮收益调整。",
        f"9. **full-U覆盖**：{q.get('rows','null')}行 / {q.get('dates','null')}日期；资格按当天全部 U_t、UID与原始 bank 顺序验证。R06/R08 115日；R17/R18 194日。不同风险族日期不拼成完整732主序列，不给缺失日期填 Raw/零收益。",
        f"10. **short-history从经典min30阻塞到可估的范围**：原 R4 qualified HP 元信息中，10≤nominal N<30 的 unique CUSIP={short['unique_uids']}，refresh×asset={short['state_asset_pairs']}。这是已证明 native predictive-state 支持的身份范围，不是新增训练人数，也不证明每个日期都可消费。逐refresh数量见下表。floor(N/5)仅重叠观测上界/proxy，独立 effective N=UNKNOWN。",
        "11. **仍blocked的 risk families**：见18族资格表。真正输入/方法语义缺口保留；已有 producer 可做的工程接入不会被伪称不可解决，但本轮没有合格输入就不调用。",
        f"12. **optimizer实际solve**：{fmt(actual_count(solve,'actual_solver_calls'),0)}；charged solve reservation={fmt(solve.get('charged_reservations'),0)}，unique solve identity=date×rule×risk representation。hard cap12000不是额度目标，solver不是模型 fit。",
        f"13. **48正式roles可评价多少**：有描述性汇总的角色 {sum(number(r.get('applicable_dates')) is not None and number(r.get('applicable_dates'))>0 for r in rr)}；完整共同732主评价=0。48 exposure全部追加，不丢 blocked角色。各role状态/日期见全表。",
        f"14. **哪些方法牺牲alpha**：部分日期 mean edge<0 的点估计：{listing('alpha_decline')}。‘明显’或统计显著牺牲不能从稀疏日期均值判定。",
        f"15. **降低风险并保持alpha**：预测 variance ratio<1 且描述性 edge≥0：{listing('pred_risk_lower_alpha_kept')}。它只描述已给点估计，尚不是 RISK_EFFICIENCY_SUPPORTED。",
        f"16. **alpha与risk均改善**：预测风险与edge同时改善的点估计：{listing('both_pred_improved')}；若有合法H5已实现std，二者同时改善：{listing('both_realized_improved')}。两种risk坐标分开，不用预测风险冒充已实现风险。",
        "17. **C11简单risk penalty负结论是否仍成立**：旧C11结论保留、不重开、不调lambda。只复用指定Raw/Pareto/MinVol controls；C13局部覆盖不能推翻或重写旧完整实验。controls摘要见下表，缺值不补读旧economic结果。",
        "18. **covariance-aware与C11是否明显不同**：机制上不同：固定RawTop10、风险约束/结构决定边界membership，而非alpha−lambda risk全池排序。收益或风险改善是否明显仍不能从不完整共同 OOF 确认。",
        "19. **Bayesian/EB是否优于裸sample covariance**：null（不能判定）。本轮没有匹配完整full-U sample covariance比较路径；不能用不匹配资产域、日期或H5窗口比较。",
        "20. **tail/CVaR在高风险年份增量**：null（不能判定），相关风险输入/角色未得到完整资格。未用已暴露年份挑tail模型。",
        "21. **regime是否有conditional改善**：null（不能判定），未形成合格完整regime比较。不得把2023剔除或根据本轮收益定义regime。",
        "22. **uncertainty-aware是否减少错误replacement**：null（不能判定），完整 jackknife/固定ensemble covariance set未齐。原生posterior有参数不确定性不等于已取得独立 robust-selection增量证据。",
        "23. **HRP/cluster是否有价值**：相应D10/D11的部分日期结果见全表；最终仍equal20，不产出HRP权重。缺共同 OOF，无法确认统计价值。",
        "24. **bootstrap stability是否只是更保守**：null（不能判定）。没有完整合格历史样本/500×20 native bootstrap依赖，就保留D12阻塞；不把未运行bootstrap算成风险fit或solve。",
        "25. **风险-alpha frontier**：图只画预注册role的已给点估计。预测图x=mean predicted variance ratio−1，y=mean selection edge(bp)；若有合法H5已实现汇总，另图x=selected/raw H5 std−1。两图均部分日期、描述性，不从frontier挑参数或再训练。缺字段时不造点。",
        "26. **2023/24/25差异**：下方逐年edge与覆盖均保留。各族日期不同，年均值反映已可用日期，不能推断整年的经济/风险表现，也不跨族拼接。",
        f"27. **simultaneous支持**：新支持=[]，新pooled/lower95为null；累计147numeric/226exposure，原shared5000draw/block20/seed20260928 exact reuse；critical maxT={fmt(stat.get('critical_max_t'),6)}。没有新增 bootstrap draw，没有稀疏series进入numeric，没有降低threshold。",
        "28. **C12保持不变**：九ML boundary roles、训练状态、早年身份阻塞、原结果与freeze不修改、不重训。本轮不使用C12 partial数字挑风险族/约束/ensemble，也不融合C12/C13。",
        "29. **C6/C8状态**：C6A=BLOCKED_INPUT；C8=BLOCKED_DEPENDENCY；C11-B=BLOCKED_SHARED_RISK。未重新考古F源或补造事件输入。本轮C13合法局部消费不自动宣称旧C8/C11-B已全面完成。",
        "30. **2026锁定**：read=0、fit=0、risk state=0、evaluation=0。没有2027+读取，没有生产晋级；source historical revision/vintage authority仍UNKNOWN。","",
        "## 二、18个风险信息族与实际计账","",
        "| 信息族 | 本次新backend | 资格状态 | 原生state数 | 全U可用日 | 主要限制 |",
        "|---|---:|---|---:|---:|---|"]
    for family,info in q.get("families",{}).items():
        prefix=family.split('_')[0]
        lines.append(f"| {family} | {fmt(by_family(fit,prefix),0)} | {info.get('status','UNKNOWN')} | {fmt(info.get('state_count'),0)} | {fmt(info.get('eligible_date_count'),0)} | {info.get('reason',info.get('qualification','null'))} |")
    lines += ["","风险 learned-state hard cap2400，optimizer solve cap12000，formal role cap48；不是quota。covariance/factor/GARCH/posterior/EB/uncertainty/bootstrap、deterministic transforms、solver和selector role必须分别计账。原风险bank fit历史保留，未重新记成本次训练。", f"membership deterministic transform calls={fmt(solve.get('membership_deterministic_transform_calls'),0)}；bootstrap estimations={fmt(solve.get('bootstrap_estimations'),0)}（冻结计划为0，未调用不计作fit）。","",
        "| refresh | 10≤N<30股票数 | 最小nominal N | 最小floor(N/5) proxy |",
        "|---|---:|---:|---:|"]
    for r in short["refreshes"]:
        lines.append(f"| {r['as_of']} | {r['short_assets']} | {fmt(r['min_nominal_n'],0)} | {fmt(r['min_n_div5_proxy'],0)} |")
    lines += ["","## 三、48角色覆盖与逐年描述","",
        "以下mean edge仅在该role合法可用且label成熟日期计算，不是完整2023–25 pooled。Raw overlap为共同持有只数或输入摘要明示定义；替换数和rank sacrifice不能转成交易成本/账户利润。缺失格是typed null。","",
        "| Role | 状态 | 可用日 | 共同成熟日 | edge bp | 2023 bp | 2024 bp | 2025 bp | predicted var ratio | Raw overlap | 替换数 | rank sacrifice |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    failures={**design.get("blocked_roles",{}),**assembly.get("failed_or_untestable",{}),**evidence.get("failed_or_untestable",evidence.get("bootstrap",{}).get("failed_or_untestable",{}))}
    for cid in design.get("roles",ev.ROLES):
        r=items.get(cid,{});year=r.get("edge_by_year_bp",{})
        state=r.get("status",assembly.get("role_statuses",{}).get(cid,"FAILED_UNTESTABLE"))
        lines.append(f"| {cid} | {state} | {fmt(r.get('applicable_dates'),0)} | {fmt(r.get('common_mature_dates'),0)} | {fmt(r.get('mean_edge_bp'))} | {fmt(year.get('2023',year.get(2023)))} | {fmt(year.get('2024',year.get(2024)))} | {fmt(year.get('2025',year.get(2025)))} | {fmt(r.get('mean_predicted_variance_ratio'),6)} | {fmt(r.get('mean_raw_overlap'))} | {fmt(r.get('mean_replacements'))} | {fmt(r.get('mean_raw_rank_sacrifice'))} |")
    lines += ["","## 四、已实现风险与控制组","",
        "H5已实现风险是qualified shareholder Open basket return的重叠五日序列，非mean-ER target分布、非账户收益。严格CVaR采用既有empirical_cvar(-basket, alpha=.95)：固定5%尾部质量、边界fractional weighting，表格读取cvar_loss_alpha95。原cvar_loss_q05/q05/exceedance为proxy，不能冒充严格CVaR。下表仅复制风险owner汇总；未做IID显著性、年化或补造tail。","",
        "| Role | 合法H5日 | selected std | Raw std | selected downside | Raw downside | selected CVaR α=.95 loss | Raw CVaR α=.95 loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rr:
        z=pooled_realized(r);selected=z.get("selected",{});raw=z.get("raw",{})
        lines.append(f"| {r['candidate_id']} | {fmt(z.get('valid_h5_dates'),0)} | {fmt(selected.get('std_ddof1'),6)} | {fmt(raw.get('std_ddof1'),6)} | {fmt(selected.get('downside_uncentered'),6)} | {fmt(raw.get('downside_uncentered'),6)} | {fmt(selected.get('cvar_loss_alpha95'),6)} | {fmt(raw.get('cvar_loss_alpha95'),6)} |")
    lines += ["","Control只消费当前controller提供的exact-reuse摘要，不读旧收益文件：","","```json",json.dumps(controls,ensure_ascii=False,indent=2,default=str),"```","",
        "## 五、故障、未完成项与后续边界","",
        "本轮已完成可执行部分的资格核验、有限约束选股、实际solve账本、稀疏日期诊断、原统计receipt复用与详细报告。没有完整共同OOF的风险族/role仍是依赖阻塞，未完成的独立高维比较不伪造成完成。失败solve不退款、不换参数继续赛马。",
        "source frozen-history可用于机制研究，但historical publication/revision/vintage未证明；QQQ qfq proxy与未完整FF48语义逐源保留。SHR_CC不自动等价classical constant-correlation，SHR_FACTOR不自动等价R09。",
        "下一步只可在新授权、独立冻结和预算下，由既有风险owner补齐合格full-U/native-history/scenario/uncertainty依赖；不自动产生C14，不因本轮描述性正点估计改约束、cadence、seed、risk family或bootstrap。",
        "当前各role失败/不可检验原因：","","```json",json.dumps(failures,ensure_ascii=False,indent=2,default=str),"```","",
        "源码/冻结保留审计：","","```json",json.dumps(preservation,ensure_ascii=False,indent=2,default=str),"```","",
        "本run execution计数（只复制本次receipt，未新增评价）：","","```json",json.dumps(execution,ensure_ascii=False,indent=2,default=str),"```","",
        "## 六、路径与可复核证据","",
        f"research_id：`{ev.RESEARCH_ID}`。正式输入与SHA以DESIGN_FREEZE、C13_SHARED_RISK_QUALIFICATION、FINAL_DECISIONS_FREEZE和EXECUTION_RECEIPT为准；报告/图的最终SHA由DELIVERY_COMPLETE绑定。",
        "源码/测试在D权威repo，状态/模型引用/账本在本run，报告/图在run_config指定results，临时测试在指定cache；无C聊天业务产物、无canonical data写入、无E/F/provider请求。",""]
    return "\n".join(lines)


def frontier_points(summaries,realized=False):
    result=[]
    for r in rows(summaries):
        edge=number(r.get("mean_edge_bp"));risk=realized_ratio(r) if realized else number(r.get("mean_predicted_variance_ratio"))
        if edge is not None and risk is not None: result.append((r["candidate_id"],risk-1,edge))
    return result


def frontier_chart(points,path,realized=False):
    if not points: return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure,ax=plt.subplots(figsize=(10,6))
    ax.axhline(0,color="gray",linewidth=.8);ax.axvline(0,color="gray",linewidth=.8)
    for cid,risk,edge in points:
        ax.scatter(100*risk,edge,s=27)
        ax.annotate(cid.removeprefix("C13_"),(100*risk,edge),xytext=(4,3),textcoords="offset points",fontsize=7)
    ax.set_xlabel("Realized H5 std ratio minus 1 (%)" if realized else "Predicted H5 variance ratio minus 1 (%)")
    ax.set_ylabel("Descriptive selection edge (bp)")
    ax.set_title("C13 partial-date descriptive risk-alpha points; no support / no model selection")
    ax.grid(alpha=.2);figure.tight_layout();figure.savefig(path,dpi=150);plt.close(figure)
    return dict(path=str(path),sha256=sha(path),coordinate="REALIZED_H5_STD" if realized else "PREDICTED_H5_VARIANCE",descriptive_only=True)


def validate_terminal(design,evidence,final,execution,bindings):
    ev.validate_design(design)
    require(final.get("status")=="PASS" and final.get("decision_frozen") is True
        and final.get("all_decisions_terminal") is True and type(final.get("outcome_reads_before_gate")) is int
        and final["outcome_reads_before_gate"]==0 and final.get("research_id")==ev.RESEARCH_ID,"FINAL_DECISIONS_REQUIRED")
    require(final.get("design_sha256")==bindings["DESIGN_FREEZE.json"]["sha256"]
        and final.get("review_sha256")==bindings["FORMAL_FREEZE_REVIEW.json"]["sha256"],"FINAL_DESIGN_REVIEW_PIN")
    pairs=((final,"score_assembly_ref","SCORE_ASSEMBLY.json"),(final,"solve_ledger_ref","SOLVE_LEDGER.json"),
        (final,"fit_ledger_ref","FIT_LEDGER.json"),(execution,"design","DESIGN_FREEZE.json"),
        (execution,"final_gate","FINAL_DECISIONS_FREEZE.json"),(execution,"ledger","SOLVE_LEDGER.json"),
        (execution,"assembly","SCORE_ASSEMBLY.json"),(execution,"evaluation","SELECTION_EVIDENCE.json"),
        (execution,"summary","ROLE_DESCRIPTIVE_SUMMARY.json"))
    for obj,key,name in pairs:
        item=obj.get(key,{})
        require(isinstance(item,dict) and item.get("sha256")==bindings[name]["sha256"]
            and safe_d(item.get("path",""))==safe_d(bindings[name]["path"]),"TERMINAL_TYPED_REF_PIN:"+key)
    require(evidence.get("status")==execution.get("status")==STATUS
        and evidence.get("numeric_complete_series")==147 and evidence.get("new_numeric_complete_series")==0
        and evidence.get("exposure_namespace")==226 and evidence.get("supported")==[]
        and evidence.get("complete_common_732_candidates")==[]
        and evidence.get("strict_PIT_promotion_eligible") is False and evidence.get("test2026_locked") is True
        and execution.get("strict_PIT_promotion_eligible") is False,"PARTIAL_147_226_NO_PRIMARY_REQUIRED")
    for key in COUNTERS_2026:
        require(type(evidence.get(key)) is int and evidence[key]==0,"NO_2026_READ_FIT_STATE_EVALUATION")
    for key in ("read2026","fit2026","state2026","evaluation2026"):
        require(type(execution.get(key)) is int and execution[key]==0,"NO_2026_EXECUTION")
    require(not evidence.get("risk_efficiency_supported") and not evidence.get("selector_supported"),"PARTIAL_DATES_CANNOT_SUPPORT")
    tests=evidence.get("tests",[])
    require(isinstance(tests,list) and len(tests)==len(ev.ROLES)
        and {t.get("candidate_id") for t in tests}==set(ev.ROLES)
        and all(t.get("supported") is False and t.get("pooled_edge") is None
                and t.get("simultaneous_lower_95") is None for t in tests),"ALL_48_UNTESTABLE_PRIMARY_RECEIPTS_REQUIRED")
    boot=evidence.get("bootstrap",{})
    require(boot.get("exact_legacy_maxT_reuse") is True and boot.get("new_bootstrap_draws")==0
        and boot.get("numeric_complete_series")==147 and boot.get("exposure_namespace")==226
        and boot.get("repeats")==5000 and boot.get("block_sessions")==20
        and boot.get("seed")==20260928,"EXACT_LEGACY_STATISTICS_RECEIPT_REQUIRED")


def run(root):
    root=safe_d(root);assert_safe_output_path(root,kind="backtest")
    cfg=readj(root/"run_config.json");results=safe_d(cfg["results"]);assert_safe_output_path(results,kind="results")
    paths={name:root/name for name in (*RUN_INPUTS,"DESIGN_FREEZE.json","DESIGN_FREEZE_SHA.json","FORMAL_FREEZE_REVIEW.json")}
    paths.update({name:results/name for name in RESULT_INPUTS})
    if not paths["EXECUTION_RECEIPT.json"].exists(): paths["EXECUTION_RECEIPT.json"]=results/"EXECUTION_RECEIPT.json"
    bindings={name:dict(path=str(safe_d(p)),sha256=sha(p)) for name,p in paths.items()}
    data={name:readj(p) for name,p in paths.items()};d=data["DESIGN_FREEZE.json"]
    manifest=data["DESIGN_FREEZE_SHA.json"];review=data["FORMAL_FREEZE_REVIEW.json"]
    require(manifest.get("sha256")==bindings["DESIGN_FREEZE.json"]["sha256"]
        and manifest.get("formal_review_sha256")==bindings["FORMAL_FREEZE_REVIEW.json"]["sha256"]
        and review.get("status")=="PASS" and review.get("research_id")==ev.RESEARCH_ID
        and review.get("design_sha256")==manifest["sha256"] and review.get("source_pins")==d.get("sources"),"FORMAL_FREEZE_REVIEW_PIN_REQUIRED")
    own=str(Path(__file__).resolve());require(d.get("sources",{}).get(own)==sha(__file__),"DELIVERY_SOURCE_NOT_FROZEN")
    for p,h in d["sources"].items(): pin(dict(path=p,sha256=h))
    q=readj(pin(d["risk_qualification"]))
    require(q.get("research_id")==ev.RESEARCH_ID and q.get("status")=="METADATA_QUALIFIED_PARTIAL"
        and q.get("strict_PIT_promotion_eligible") is False,"EXACT_C13_RISK_QUALIFICATION_REQUIRED")
    bindings["risk_qualification"]=d["risk_qualification"]
    validate_terminal(d,data["SELECTION_EVIDENCE.json"],data["FINAL_DECISIONS_FREEZE.json"],data["EXECUTION_RECEIPT.json"],bindings)
    summaries=data["ROLE_DESCRIPTIVE_SUMMARY.json"]
    ids=[x["candidate_id"] for x in rows(summaries)]
    require(all(x.get("selector_supported") is False and x.get("risk_efficiency_supported") is False for x in rows(summaries)),
            "DESCRIPTIVE_SUMMARY_CANNOT_CLAIM_SUPPORT")
    preservation=data["SOURCE_PRESERVATION.json"];controls=data["CONTROL_REUSE.json"]
    require(preservation.get("status")=="PASS" and preservation.get("C12_unchanged") is True
        and all(x.get("unchanged") is True for x in preservation.get("checks",[])),"SOURCE_PRESERVATION_REQUIRED")
    require(controls.get("C11_reselected") is False and len(controls.get("controls",[]))==3
        and all(x.get("exact_reuse") is True and x.get("new_fit")==0 and x.get("new_exposure") is False
                for x in controls["controls"]),"THREE_EXACT_REUSE_CONTROLS_REQUIRED")
    require(len(ids)==len(set(ids)) and set(ids).issubset(ev.ROLES),"REGISTERED_UNIQUE_SUMMARIES_REQUIRED")
    report=results/"FINAL_REPORT.md";marker=root/"DELIVERY_COMPLETE.json"
    chart_specs=[(frontier_points(summaries),results/"charts/C13_PREDICTED_RISK_ALPHA_FRONTIER.png",False),
                 (frontier_points(summaries,True),results/"charts/C13_REALIZED_H5_RISK_ALPHA_FRONTIER.png",True)]
    new_outputs([report,marker,*[p for points,p,_ in chart_specs if points]],"C13_DELIVERY")
    charts=[frontier_chart(points,p,realized) for points,p,realized in chart_specs if points]
    text=render_report(d,q,dict(fit=data["FIT_LEDGER.json"],solve=data["SOLVE_LEDGER.json"]),data["SCORE_ASSEMBLY.json"],
        data["SELECTION_EVIDENCE.json"],summaries,data["CONTROL_REUSE.json"],data["SOURCE_PRESERVATION.json"],data["EXECUTION_RECEIPT.json"])
    if charts:
        text += "\n预测风险与已实现H5风险图分别如下（仅描述，不用于选择）：\n\n"+"\n\n".join(f"![{x['coordinate']} partial descriptive points]({x['path']})" for x in charts)+"\n"
    report.write_text(text,encoding="utf-8")
    for ref in bindings.values(): pin(ref)
    for p,h in d["sources"].items(): pin(dict(path=p,sha256=h))
    complete=dict(status=STATUS,research_id=ev.RESEARCH_ID,report=dict(path=str(report),sha256=sha(report)),
        charts=charts,input_artifact_bindings=bindings,completed_at=now(),numeric_complete_series=147,
        new_numeric_complete_series=0,exposure_namespace=226,supported=[],primary_test_performed=False,
        strict_PIT_promotion_eligible=False,test2026_locked=True,fit2026_rows=0,evaluation2026_rows=0,
        outcome2026_reads=0,new2026_state_estimations=0,source_pins_preserved=True,C12_unchanged=True,
        C6A="BLOCKED_INPUT",C8="BLOCKED_DEPENDENCY",C11_B="BLOCKED_SHARED_RISK",delivery_only_no_new_evaluation=True)
    putj(marker,complete)
    cfg.update(status=STATUS,run_end=now(),delivery_complete=True,design_freeze_sha256=manifest["sha256"]);putj(root/"run_config.json",cfg)
    state=readj(root/"PIPELINE_STATE.json") if (root/"PIPELINE_STATE.json").exists() else {}
    state.update(status=STATUS,delivery_complete=True,at=now());putj(root/"PIPELINE_STATE.json",state)
    print(json.dumps(dict(phase="DELIVERY",status=STATUS,numeric=147,exposure=226,report_sha256=complete["report"]["sha256"])),flush=True)
    return complete


delivery=run


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",required=True);run(parser.parse_args().run)