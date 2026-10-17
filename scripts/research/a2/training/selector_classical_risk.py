"""C11 deterministic selector orchestration; reuse readers/statistics, no risk engine."""
from __future__ import annotations
import argparse, json, os, stat
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.factors import selector_classical_rules as rules
from scripts.research.a2.evaluation import selector_classical_evidence as ev
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation.selector_account_compare import pre2026, sha, readj, score_panel
from scripts.research.a2.training.selector_challenge import now

REPO = Path(__file__).resolve().parents[4]
KEYS = shared.KEY + ["ticker", "U_t_fingerprint"]
FEATURES = ["ret_20d","ret_40d","ret_60d","ret_120d","price_vs_ma20","price_vs_ma50",
            "price_vs_ma120","ma20_vs_ma50","ma50_vs_ma120","realized_vol_20d",
            "downside_vol_20d","max_drawdown_60d","avg_dollar_volume_20d"]


def safe_d(path):
    p = Path(path)
    if not p.is_absolute() or p.drive.upper() != "D:": raise ValueError("ONLY_D_PATH_ALLOWED")
    for a in reversed((p, *p.parents)):
        try: s = os.lstat(a)
        except FileNotFoundError: continue
        if getattr(s, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("UNREVIEWED_REPARSE_FORBIDDEN:" + str(a))
    return p


def pin(item):
    p = safe_d(item["path"])
    if sha(p) != item["sha256"]: raise ValueError("PIN_CHANGED:" + str(p))
    return p


def put(path, value):
    p = safe_d(path)
    assert_safe_output_path(p)
    if p.exists(): raise FileExistsError("PRESERVE_EXISTING_ARTIFACT:" + str(p))
    shared.putj(p, value)


def new_outputs(paths, stage):
    paths = [safe_d(p) for p in paths]
    if any(p.exists() for p in paths):
        raise FileExistsError("NO_DUPLICATE_" + stage + ":PRESERVE_PARTIAL_ARTIFACTS")
    for p in paths:
        safe_d(p.parent).mkdir(parents=True, exist_ok=True)
    return paths


def checked(root):
    root = safe_d(root)
    assert_safe_output_path(root, kind="backtest")
    cfg, d = readj(root/"run_config.json"), readj(root/"DESIGN_FREEZE.json")
    if sha(root/"DESIGN_FREEZE.json") != readj(root/"DESIGN_FREEZE_SHA.json")["sha256"]:
        raise ValueError("FREEZE_CHANGED")
    ev.validate_design(d)
    for p, h in d["sources"].items(): pin(dict(path=p, sha256=h))
    for k in ("features","raw_score","risk_review","completion_dag","input_qualification"):
        pin(d[k])
    if (d["risk_eligible_families"] or set(d["blocked_roles"]) != set(ev.B_ROLES)
        or readj(pin(d["completion_dag"]))["active_physical_estimators"] != []):
        raise ValueError("THIS_FREEZE_REQUIRES_BLOCKED_SHARED_BANK_NO_FIT")
    manifest = readj(root/"DESIGN_FREEZE_SHA.json")
    review_path = root/"FORMAL_FREEZE_REVIEW.json"
    review = readj(review_path)
    if (manifest.get("formal_review_sha256") != sha(review_path)
        or review.get("status") != "PASS" or review.get("research_id") != ev.RESEARCH_ID
        or review.get("design_sha256") != sha(root/"DESIGN_FREEZE.json")
        or review.get("source_pins") != d["sources"]
        or review.get("pre_execution_counters") != dict(fits=0, risk_state_attempts=0, outcome_reads=0)):
        raise ValueError("FORMAL_REVIEW_REQUIRED")
    return cfg, d


def input_frame(d):
    raw = pre2026(pin(d["raw_score"]), KEYS + ["score","rank"], "signal_date")
    f = pre2026(pin(d["features"]), ["signal_date","ticker",*FEATURES], "signal_date")
    raw["signal_date"], f["signal_date"] = pd.to_datetime(raw.signal_date), pd.to_datetime(f.signal_date)
    if raw.duplicated(shared.KEY).any() or f.duplicated(["signal_date","ticker"]).any():
        raise ValueError("DUPLICATE_FEATURE_OR_UID_KEYS")
    raw = raw.sort_values(shared.KEY).reset_index(drop=True)
    frame = raw.rename(columns={"score":"raw_score","rank":"raw_rank"}).merge(
        f, on=["signal_date","ticker"], how="left", validate="one_to_one")
    if (len(frame) != 313668 or frame.signal_date.nunique() != 752
        or frame[FEATURES].isna().any().any() or not np.isfinite(frame[FEATURES].to_numpy(float)).all()
        or frame.max_drawdown_60d.gt(1e-12).any()):
        raise ValueError("FULL_U_FINITE_BASE32_NATIVE_INPUT_REQUIRED")
    if not frame[KEYS].equals(raw[KEYS]): raise ValueError("DO_NOT_SHRINK_FULL_U")
    return frame


def assemble(root):
    cfg, d = checked(root)
    new_outputs([root/"SCORE_ASSEMBLY.json", root/"RISK_FIT_LEDGER.json",
        *[root/f"predictions/scores_{cid}_pre2026.parquet" for cid in (*ev.A_ROLES,*ev.SANITY_ROLES)]], "ASSEMBLY")
    frame = input_frame(d)
    panels = rules.base_rules(frame)
    if set(panels) != set((*ev.A_ROLES,*ev.SANITY_ROLES)): raise ValueError("FIXED_TEN_RULES")
    bindings = {ev.RAW:d["raw_score"]}
    for cid, panel in panels.items():
        shared.align(frame, panel)
        p = root/f"predictions/scores_{cid}_pre2026.parquet"
        panel[KEYS+["candidate_id","score","rank"]].to_parquet(safe_d(p),index=False)
        bindings[cid] = dict(path=str(p),sha256=sha(p))
    assembly = dict(status="SCORE_ASSEMBLY_COMPLETE", design_freeze_sha256=sha(root/"DESIGN_FREEZE.json"),
        complete_candidates=list((*ev.A_ROLES,*ev.SANITY_ROLES)),
        failed_or_untestable=d["blocked_roles"], score_paths=bindings, common_rows=len(frame),
        common_dates=752, forecast2026_rows=0, deterministic_new_rules=9, exact_Raw_sanity=1)
    put(root/"SCORE_ASSEMBLY.json",assembly)
    put(root/"RISK_FIT_LEDGER.json",dict(design_freeze_sha256=sha(root/"DESIGN_FREEZE.json"),logical_slots=50, blocked_before_fit=50, attempted_states=0,
        physical_fits=0, failed_fits=0, charged_reservations=0, scientific_retry=0, events=[],
        prior_50_FITTED_records_preserved=True))
    del panels
    print(json.dumps(dict(phase="ASSEMBLY",status="COMPLETE",roles=10,fit_calls=0)),flush=True)


def mechanism_rows(frame, panel, cid, common):
    coordinates = rules.coordinates(frame)
    risk3 = coordinates[["VOL_RISK","DOWNSIDE_RISK","DD_RISK"]].mean(axis=1)
    high = risk3.groupby(frame.signal_date).rank(pct=True,method="average").ge(.8)
    rows, previous = [], None
    for date, ix in frame.groupby("signal_date",sort=True).indices.items():
        group, p = frame.iloc[ix], panel.iloc[ix]
        mask, rawmask = p["rank"].le(20).to_numpy(), group.raw_rank.le(20).to_numpy()
        selected = set(group.loc[mask,"security_uid"]); rawset = set(group.loc[rawmask,"security_uid"])
        h = high.iloc[ix].to_numpy(); denom = int((rawmask & h).sum())
        rows.append(dict(candidate_id=cid,signal_date=date,common_mature_date=bool(common.loc[date]),
            raw_overlap=len(selected & rawset)/20, membership_turnover=None if previous is None else len(previous^selected)/40,
            excluded_high_risk_raw_fraction=None if denom==0 else int((rawmask & ~mask & h).sum())/denom,
            selected_high_risk_fraction=float(h[mask].mean()),
            selected_realized_vol_native_mean=float(group.loc[mask,"realized_vol_20d"].mean()),
            raw_realized_vol_native_mean=float(group.loc[rawmask,"realized_vol_20d"].mean()),
            selected_downside_native_mean=float(group.loc[mask,"downside_vol_20d"].mean()),
            raw_downside_native_mean=float(group.loc[rawmask,"downside_vol_20d"].mean()),
            selected_drawdown_magnitude_mean=float(-group.loc[mask,"max_drawdown_60d"].mean()),
            raw_drawdown_magnitude_mean=float(-group.loc[rawmask,"max_drawdown_60d"].mean()),
            selected_liquidity_native_mean=float(group.loc[mask,"avg_dollar_volume_20d"].mean()),
            raw_liquidity_native_mean=float(group.loc[rawmask,"avg_dollar_volume_20d"].mean()),
            selected_from_raw_1_10=int((mask & group.raw_rank.le(10).to_numpy()).sum()),
            selected_from_raw_11_20=int((mask & group.raw_rank.between(11,20).to_numpy()).sum()),
            selected_from_raw_21_40=int((mask & group.raw_rank.between(21,40).to_numpy()).sum()),
            selected_from_raw_over40=int((mask & group.raw_rank.gt(40).to_numpy()).sum()),
            portfolio_exante_volatility=None, covariance_condition_number=None, shrinkage_intensity=None,
            sector_concentration=None))
        previous = selected
    return rows


def evaluate(root):
    cfg, d = checked(root)
    out = safe_d(root/"diagnostics/selector_evidence")
    results = safe_d(cfg["results_directory"]); assert_safe_output_path(results,kind="results")
    names = ("COMMON_DATE_MATURITY.parquet","PRIMARY_DAILY_EDGE.parquet","DAILY_DIAGNOSTICS.parquet",
        "MECHANISM_DIAGNOSTICS.parquet","MECHANISM_YEAR.parquet","BOOTSTRAP_MAXT.parquet")
    new_outputs([*[out/name for name in names],out/"SELECTION_EVIDENCE.json",results/"SELECTION_EVIDENCE.json"],"EVALUATION")
    ev.validate_legacy(d["evaluation"]["legacy"], resolve(REPO))
    assembly = readj(root/"SCORE_ASSEMBLY.json")
    if (assembly["design_freeze_sha256"] != sha(root/"DESIGN_FREEZE.json")
        or assembly["complete_candidates"] != list((*ev.A_ROLES,*ev.SANITY_ROLES))
        or assembly["failed_or_untestable"] != d["blocked_roles"]):
        raise ValueError("EXACT_ASSEMBLY_REQUIRED")
    legacy = d["evaluation"]["legacy"]
    clock = pre2026(pin(legacy["clock"]),["signal_date","included"],"signal_date")
    clock["signal_date"] = pd.to_datetime(clock.signal_date)
    old_edges = pre2026(pin(legacy["edge"]),["signal_date",*legacy["numeric_ids"]],"signal_date").set_index("signal_date")
    old_edges.index = pd.DatetimeIndex(old_edges.index)
    raw, _ = score_panel(root, ev.RAW)
    shared.prove_label_boundary(pin(d["raw_score"]),"label_end_date",allow_null=True)
    labels = pre2026(pin(d["raw_score"]),shared.KEY+["target","label_end_date"],"signal_date")
    reference = raw.merge(labels,on=shared.KEY,how="left",validate="one_to_one")
    if not reference.loc[reference.label_end_date.isna(),"target"].isna().all():
        raise ValueError("UNKNOWN_MATURITY_TARGET")
    frame, common = input_frame(d), clock.set_index("signal_date").included
    new, summaries_daily, mechanical, failures = pd.DataFrame(index=old_edges.index), [], [], dict(d["blocked_roles"])
    for cid in assembly["complete_candidates"]:
        try: panel, digest = ev.bound_panel(root,cid,assembly,reference,clock)
        except ValueError as exc:
            if str(exc)!="SELECTED_LABELS_IMMATURE_NO_COMMON_DATE_SHRINK": raise
            failures[cid]=str(exc); continue
        mature,_ = shared.maturity(reference,raw["rank"].le(20).to_numpy() | panel["rank"].le(20).to_numpy())
        rows = shared.diagnose(cid,reference,panel.score.to_numpy(),panel["rank"].to_numpy(),
                               raw["rank"].to_numpy(),mature,common)
        daily = pd.DataFrame(rows); summaries_daily.extend(rows)
        new[cid] = daily.loc[daily.common_mature_date].set_index("signal_date").replacement_edge.reindex(old_edges.index)
        mechanical.extend(mechanism_rows(frame,panel,cid,common))
    matrix, tests, bootstrap, maxima = ev.statistics(old_edges,new,np.flatnonzero(clock.included.to_numpy(bool)),
        pd.DatetimeIndex(clock.signal_date),d["evaluation"]["bootstrap"],legacy["numeric_ids"],failures)
    clock.to_parquet(out/"COMMON_DATE_MATURITY.parquet",index=False)
    matrix.rename_axis("signal_date").reset_index().to_parquet(out/"PRIMARY_DAILY_EDGE.parquet",index=False)
    pd.DataFrame(summaries_daily).to_parquet(out/"DAILY_DIAGNOSTICS.parquet",index=False)
    mechanics = pd.DataFrame(mechanical);mechanics.to_parquet(out/"MECHANISM_DIAGNOSTICS.parquet",index=False)
    numeric_cols = mechanics.select_dtypes(include=[np.number]).columns
    yearly = mechanics.loc[mechanics.common_mature_date].assign(year=lambda f:f.signal_date.dt.year).groupby(
        ["candidate_id","year"])[numeric_cols].mean().reset_index()
    yearly.to_parquet(out/"MECHANISM_YEAR.parquet",index=False)
    pd.DataFrame(dict(replicate=np.arange(len(maxima)),centered_standardized_max_t=maxima)).to_parquet(
        out/"BOOTSTRAP_MAXT.parquet",index=False)
    supported=[t["candidate_id"] for t in tests if t["supported"]]
    status="C11_PARTIAL_SHARED_RISK_BLOCKED" if d["blocked_roles"] else (
        "C11_COMPLETE_SUPPORTED_MECHANISM" if supported else "C11_COMPLETE_NO_SUPPORT")
    if any(cid not in new for cid in ev.A_ROLES):
        status="C11_BLOCKED_REQUIRED_INPUT" if not set(ev.A_ROLES)&set(new) else "C11_PARTIAL_SHARED_RISK_BLOCKED"
    receipt=dict(status=status,research_id=ev.RESEARCH_ID,tests=tests,bootstrap=bootstrap,
        research_supported_roles=supported,failed_or_untestable={**legacy["failed_or_untestable"],**failures},
        new_failed_or_untestable=failures,exposure_roles=[*legacy["exposure_ids"],*ev.ROLES],
        legacy_numeric_ids=legacy["numeric_ids"],legacy_exposure_roles=legacy["exposure_ids"],
        numeric_count=len(matrix.columns),exposure_count=169,common_mature_dates=732,
        common_year_dates=ev.YEAR_COUNTS,calendar_positions=752,design_freeze_sha256=sha(root/"DESIGN_FREEZE.json"),
        score_assembly_sha256=sha(root/"SCORE_ASSEMBLY.json"),evaluation_source_sha256=sha(Path(ev.__file__)),
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,economic_promotion_allowed=False,
        finalists=[],test2026_locked=True,test2026_rows_read=0,new2026_estimation_authorized=False,
        diagnostic_only_roles=list(ev.SANITY_ROLES),risk_models_consumed=[],new_risk_estimations=0,
        source_limitation="Frozen-history BASE32 authority; vintage/revision not proved. No production promotion.",
        unavailable_mechanism_diagnostics={"portfolio_exante_volatility":"NO_QUALIFIED_FULL_U_COVARIANCE",
            "condition_number_and_shrinkage":"NO_CONSUMED_RISK_STATE",
            "sector_concentration":"NO_C11_SOURCE_QUALIFIED_FULL_U_SECTOR_BINDING"},
        legacy_evidence_opaque_pin=legacy["evidence"],legacy_reselection=False,
        diagnostics={p.name:dict(path=str(p),sha256=sha(p)) for p in (safe_d(out/name) for name in names)})
    put(out/"SELECTION_EVIDENCE.json",receipt);put(Path(cfg["results_directory"])/"SELECTION_EVIDENCE.json",receipt)
    print(json.dumps(dict(phase="EVIDENCE",status=status,supported=supported)),flush=True)
    return receipt


def report(root):
    cfg,d=checked(root);results=safe_d(cfg["results_directory"])
    assert_safe_output_path(results,kind="results")
    new_outputs([*[results/name for name in ("FINAL_REPORT.md","MODEL_UPDATE_GATE.json","EXECUTION_RECEIPT.json","STORAGE_AUDIT.json")],root/"DELIVERY_COMPLETE.json"],"REPORT")
    e=readj(results/"SELECTION_EVIDENCE.json");ledger=readj(root/"RISK_FIT_LEDGER.json")
    if (e["design_freeze_sha256"]!=sha(root/"DESIGN_FREEZE.json") or e["test2026_locked"] is not True
        or e["strict_PIT_promotion_eligible"] is not False or ledger["physical_fits"]!=0
        or ledger["design_freeze_sha256"]!=sha(root/"DESIGN_FREEZE.json")) :
        raise ValueError("DELIVERY_IDENTITY_OR_BUDGET_CHANGED")
    lines=["# V24 C11 传统风险与统计选择广度：完整报告","",
        f"研究身份：{ev.RESEARCH_ID}；完成UTC：{now()}；run：{root}。","",
        f"真实终态：**{e['status']}**。Block A 已执行，Block B 十族输入/consumer authority 阻塞。",
        f"机制支持：{e['research_supported_roles']}；strict-PIT/生产/经济晋级仍禁止。","",
        "## 科学问题与固定条件","",
        "在相同信息、Raw A2 benchmark、BASE32、UID、full U_t、共同标签与下游equal/reference policy下，检验经典风险调整/趋势/Pareto的Top20选择。没有新ML、权重训练、lambda/grid或账户/Gross/Cash/持仓行动改变。",
        "2023/24/25均为已暴露开发窗口；target=MEAN_ER_3D_5D_10D_20D。2026与2027读取/推断禁止。BASE32历史revision/vintage仍未证明，本轮是授权的frozen-history机制研究。",
        "只读registry preflight仍为BLOCKED_CLOSED_BRANCH（相同信息身份匹配旧R4/R5），原accepted head与关闭记录没有修改。本轮科学执行依据是用户当前明确授权的独立C11传统规则/Pareto/marginal membership机制与独立审查；不宣称accepted-registry PASS，不重开旧实验。","",
        "## 执行、复用与风险补齐预算","",
        "8个正式deterministic A角色＋1 MIN_VOL diagnostic＋1 exact Raw diagnostic；新增实际规则9，Raw值/排序精确复用1。模型训练0，风险模型消费0，新风险估计0，新physical fits0，failed fits0，scientific retry0。",
        "共享completion DAG预登记10families×5years=50个logical dependency slots（上限60）。50个全部在拟合前BLOCKED_SOURCE，真实risk-state attempts0、reservation0；physical硬cap180，active physical DAG为空，没有隐含可执行fit。",
        "旧B已有50个FITTED＋5个HISTVOL alias记录全部保留；无UID/epoch/continuity/available_at/full-U消费绑定，不能当C exact reuse，也没有重复训练。当前旧caller冻结SHA不匹配；新producer原schedule只2023–25和5D，不合法补齐早年。","",
        "## 预冻结规则","",
        "ALPHA=全U Raw score平均ties百分位；TREND=用户指定9列百分位均值；风险坐标VOL/DOWNSIDE/DD/ILLIQ，DD=负号转换原非正max_drawdown_60d，ILLIQ=1-美元成交额百分位。A1–A7严格沿用任务书无lambda公式，A8按五维non-dominated fronts。",
        "全部排序tie固定Raw rank数值升序→UID。MIN_VOL仅Raw top40按原realized_vol_20d选20；两个sanity不可晋级。B机制源码/合成验证固定Raw1–10+11–40贪心10步，signed equal-weight组合std增量，不优化权重；无合格state，因此本轮没有执行B。","",
        "## 逐年标签replacement edge（bp）","",
        "| role | 2023 | 2024 | 2025 | pooled | simultaneous lower95 | 状态/机制支持 |",
        "|---|---:|---:|---:|---:|---:|---|"]
    def bp(v):return "—" if v is None else f"{v*10000:+.2f}"
    for t in e["tests"]:
        lines.append("| "+" | ".join([t["candidate_id"],*[bp(t["year_edges"].get(str(y))) for y in ev.YEARS],
            bp(t["pooled_edge"]),bp(t["simultaneous_lower_95"]),t["status"]+"/"+str(t["supported"])])+" |")
    lines+=["","## 累计评价与支持条件","",
        f"累计numeric={e['numeric_count']}；exposure={e['exposure_count']}；maxT critical={e['bootstrap']['critical_max_t']:.8f}。旧137numeric/149exposure/12 failed保留；新20命名角色（18科学＋2diagnostic）均登记，缺失不填零，Raw sanity实际零且zeroSE不能获支持。",
        "原752calendar/732成熟日期（250/252/230）、date-equal replacement edge、20session noncircular shared5000draw/seed20260928不变。逐draw maxima与critical不得低于旧C10；没有重挑旧finalist。",
        "正式支持需要pooled>0、2025>0、至少两年正、nonzero SE、完整OOF及simultaneous lower95>0；正点估计不等于winner。","",
        "## 机制诊断（共同成熟日期）","",
        "| role/年 | Raw overlap | membership turnover | vol proxy均值 | downside均值 | DD幅度 | dollar-volume均值 | raw11–20数 | raw21–40数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    import pyarrow as pa
    import pyarrow.parquet as pq
    mp=safe_d(root/"diagnostics/selector_evidence/MECHANISM_YEAR.parquet")
    if pin(e["diagnostics"][mp.name])!=mp:raise ValueError("MECHANISM_SUMMARY_PATH_CHANGED")
    footer=pq.ParquetFile(mp); col=footer.schema_arrow.get_field_index("year")
    if col<0:raise ValueError("MECHANISM_SUMMARY_YEAR_MISSING")
    if not pa.types.is_integer(footer.schema_arrow.field(col).type):raise ValueError("MECHANISM_SUMMARY_INTEGER_YEAR_REQUIRED")
    for rg in range(footer.num_row_groups):
        st=footer.metadata.row_group(rg).column(col).statistics
        if st is None or not st.has_min_max or st.null_count!=0 or st.min<2023 or st.max>2025:
            raise ValueError("MECHANISM_SUMMARY_YEAR_CHANGED_BEFORE_READ")
    mech=pd.read_parquet(mp)
    if not mech.year.isin(ev.YEARS).all():raise ValueError("MECHANISM_SUMMARY_YEAR_CHANGED")
    for _,row in mech.iterrows():
        fields=["raw_overlap","membership_turnover","selected_realized_vol_native_mean","selected_downside_native_mean",
                "selected_drawdown_magnitude_mean","selected_liquidity_native_mean","selected_from_raw_11_20","selected_from_raw_21_40"]
        lines.append("| "+row.candidate_id+"/"+str(int(row.year))+" | "+" | ".join(
            "—" if pd.isna(row[k]) else f"{float(row[k]):.5g}" for k in fields)+" |")
    lines+=["","逐日完整诊断包括每年overlap、跨年连续membership turnover、高风险Raw股票排除率、downside/DD/流动性特征、Raw排名区间贡献。高风险定义为全U risk3百分位≥0.8；无分母记missing，不伪造0。",
        "Vol/downside是BASE32原生描述性代理，不是组合ex-ante volatility。没有合格full-U covariance，因此组合ex-ante波动、condition number和shrinkage无法识别；行业source-qualified full-U绑定未在本轮闭合，sector concentration未计算。不用IID/任意相关性填补缺失，也不能声称哪个风险模型降低组合风险而损失alpha；MIN_VOL只是原生vol特征sanity。",
        "","## 逐family阻塞与后续",""]
    for cid,reason in d["blocked_roles"].items():lines.append(f"- {cid}：{reason}。")
    lines+=["","C8保持原独立身份与BLOCKED_DEPENDENCY。本轮completion没有新产物，2021/22/multi-horizon/full-U/independent substate/typed authority缺口未消失。C6A保持BLOCKED_INPUT；未重启Form4考古。",
        "C9没有启动；只有正式supported main effect才允许另行评审。没有自动生成C12，也没有2026推断/评价、账户NAV、Gross/Cash或downstream改变。",
        "","## 验证、故障与存储","",
        "合成、默认测试、独立审查和正式freeze见SYNTHETIC_VALIDATION.json/FORMAL_FREEZE_REVIEW.json。首轮rules测试夹具Arrow字符串numeric注入失败，保留原日志；仅修夹具，没有科研重试。正式freeze前修复summary字段、报告年份footer、半途产物保存和审查绑定；没有读取outcome。registry初稿中的风险特征/角色名称被解析器误判为收益数值，原失败保留；仅以相同身份的计数/原件引用作metadata重提。风险review family/canonical字段拼写映射与Raw常量查询的准备脚本错误在0fit/0outcome阶段解决。真实deterministic运行故障如有保留在logs；没有risk fit失败或失败预算退款。",
        f"源码在{REPO}；score/账本/diagnostics在唯一{root}；报告在{results}；测试cache在外部配置根。输入不复制、canonical只读，旧冻结/其他任务修改和进程保留。"]
    rp=safe_d(results/"FINAL_REPORT.md")
    if rp.exists():raise FileExistsError("PRESERVE_EXISTING_REPORT")
    rp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    gate=dict(status=e["status"],mechanism_supported=e["research_supported_roles"],production_finalists=[],
        production_promotion_allowed=False,strict_PIT_promotion_eligible=False,economic_promotion_allowed=False,
        test2026_locked=True,C8="BLOCKED_DEPENDENCY",C6A="BLOCKED_INPUT",C9_started=False,C12_created=False)
    put(results/"MODEL_UPDATE_GATE.json",gate)
    receipt=dict(status="DELIVERY_AUDIT_PASS",research_id=ev.RESEARCH_ID,final_report=dict(path=str(rp),sha256=sha(rp)),
        design_sha256=sha(root/"DESIGN_FREEZE.json"),selection_evidence_sha256=sha(results/"SELECTION_EVIDENCE.json"),
        completion_dag=d["completion_dag"],source_pins_match=True,old_137_numeric_preserved=True,
        counters=ledger,numeric_count=e["numeric_count"],exposure_count=169,risk_models_consumed=[],
        deterministic_scientific_roles=8,new_rules=9,exact_raw_diagnostic=1,true2026_reads=0,E_F_accesses=0,
        canonical_writes=0,chat_business_outputs=0)
    put(results/"EXECUTION_RECEIPT.json",receipt)
    from scripts.maintenance.audit_repo_size_r1 import audit
    storage=audit(REPO);put(results/"STORAGE_AUDIT.json",storage)
    if storage["violations"] or not storage["accounting_complete"] or not storage["hard_limit_passed"]:
        raise ValueError("ANTI_BLOAT_AUDIT_FAILED")
    put(root/"DELIVERY_COMPLETE.json",dict(status=e["status"],research_id=ev.RESEARCH_ID,
        final_report=receipt["final_report"],execution_receipt=dict(path=str(results/"EXECUTION_RECEIPT.json"),
        sha256=sha(results/"EXECUTION_RECEIPT.json")),completed_at=now(),test2026_locked=True))
    cfg.update(status=e["status"],run_end=now());shared.putj(root/"run_config.json",cfg)
    plan=readj(results/"EXEC_PLAN.json");plan.update(status=e["status"],delivery_complete=True,final_report=receipt["final_report"])
    shared.putj(results/"EXEC_PLAN.json",plan)
    print(json.dumps(dict(phase="DELIVERY",status=e["status"])),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument("--run",required=True);p.add_argument("--phase",
        choices=("assemble","evidence","report","all"),default="all");args=p.parse_args();root=Path(args.run)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        if args.phase in ("assemble","all"):assemble(root)
        if args.phase in ("evidence","all"):evaluate(root)
        if args.phase in ("report","all"):report(root)


if __name__=="__main__":main()
