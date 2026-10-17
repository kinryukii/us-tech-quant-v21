"""C12 production delivery: frozen pipelines, existing evidence, auditable partials.

No learner, account, risk estimator or model selection is implemented here.
Label values and oracles are consumed only after terminal pipeline verification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import assert_safe_output_path
from scripts.research.a2.training import selector_boundary_decision as controller
from scripts.research.a2.training.selector_classical_risk import safe_d, pin, put, new_outputs
from scripts.research.a2.training.selector_challenge import sha, readj, putj, now
from scripts.research.a2.evaluation.selector_account_compare import pre2026
from scripts.research.a2.evaluation import selector_boundary_evidence as ev
from scripts.research.a2.evaluation import selector_evidence as shared

DIAGNOSTICS = ('COMMON_DATE_MATURITY.parquet','PRIMARY_DAILY_EDGE.parquet','BOOTSTRAP_MAXT.parquet',
    'PARTIAL_DAILY_DIAGNOSTICS.parquet','PAIR_DIAGNOSTICS.parquet','PAIR_CALIBRATION.parquet',
    'REPLACEMENT_RANK_DISTRIBUTION.parquet','PARTIAL_YEAR_DIAGNOSTICS.parquet',
    'REPLACEMENT_COUNT_DISTRIBUTION.parquet','BOUNDARY_ORACLE_DIAGNOSTIC.parquet')
REPORT_FILES = ('SELECTION_EVIDENCE.json','FINAL_REPORT.md','MODEL_UPDATE_GATE.json',
                'EXECUTION_RECEIPT.json','STORAGE_AUDIT.json')
KEY = controller.KEY


def _require(condition, message):
    if not condition: raise ValueError(message)


def terminal_receipts(root, d):
    """Metadata/pins only; this gate must precede every outcome projection."""
    _require(d['sources'].get(str(Path(__file__))) == sha(Path(__file__)), 'DELIVERY_SOURCE_NOT_FROZEN')
    a = readj(root/'SCORE_ASSEMBLY.json')
    fpath = pin(a['final_pipelines_freeze'])
    _require(fpath == root/'FINAL_PIPELINES_FREEZE.json', 'EXACT_FINAL_PIPELINE_PATH_REQUIRED')
    f = readj(fpath); design_sha = sha(root/'DESIGN_FREEZE.json')
    _require(f.get('status') == 'FINAL_PIPELINES_FROZEN' and f.get('research_id') == ev.RESEARCH_ID
        and f.get('design_sha256') == design_sha and f.get('all_training_terminal') is True
        and f.get('capacity_selection_complete') is True and tuple(f.get('roles', ())) == ev.ROLES
        and set(f.get('role_statuses', {})) == set(ev.ROLES)
        and all(v in ('PARTIAL_INPUT_BLOCKED','FAILED') for v in f['role_statuses'].values())
        and f.get('outer_labels_read') == 0, 'FINAL_PIPELINES_FREEZE_REQUIRED_BEFORE_OUTCOMES')
    _require(a.get('status') == 'C12_PARTIAL_2025_ASSEMBLY'
        and a.get('design_freeze_sha256') == design_sha
        and a.get('outer_pipeline_status') == f.get('outer_pipeline_status')
        and set(a.get('outer_pipeline_status', {})) == set(ev.ROLES)
        and a.get('complete_common_732_candidates') == [] and a.get('forecast2026_rows') == 0
        and set(a.get('failed_or_untestable', {})) == set(ev.ROLES), 'EXACT_PARTIAL_ASSEMBLY_REQUIRED')
    ids = a.get('complete_2025_candidates', [])
    _require(len(ids) == len(set(ids)) and set(ids).issubset(ev.ROLES)
        and set(a['score_paths']) == set(a['diagnostic_paths']) == set(ids), 'EXACT_2025_BINDINGS_REQUIRED')
    _require(sha(root/'FIT_LEDGER.json') == f['fit_ledger_sha256'], 'FINAL_LEDGER_PIN_CHANGED')
    ledger = readj(root/'FIT_LEDGER.json')
    controller.validate_ledger(ledger, design_sha, readj(pin(d['physical_dag'])))
    _require(all(s['status'] in ('COMPLETE','FAILED','BLOCKED') for s in ledger['slots'].values()),
             'ALL_FIT_SLOTS_TERMINAL_REQUIRED')
    for slot in ledger['slots'].values():
        if slot['status']=='COMPLETE': pin(slot['model'])
    _require(set(f['capacity_receipts']) == set(controller.est.PARADIGMS), 'ALL_NINE_CAPACITY_RECEIPTS_REQUIRED')
    caps = {}
    for paradigm, cid in zip(controller.est.PARADIGMS, ev.ROLES):
        cp = readj(pin(f['capacity_receipts'][paradigm])); caps[paradigm] = cp
        _require(cp.get('candidate_id') == cid and cp.get('outer_year') == 2025
            and cp.get('outer_y_values_read') == 0, 'PAST_ONLY_CAPACITY_RECEIPT_REQUIRED')
        status = a['outer_pipeline_status'][cid]
        completed = cid in ids
        _require(completed == (status.get('status') == 'COMPLETE_2025_ONLY')
            and f['role_statuses'][cid] == ('PARTIAL_INPUT_BLOCKED' if completed else 'FAILED'),
            'TERMINAL_ROLE_STATUS_BINDING_REQUIRED')
        if completed:
            _require(cp.get('selected_capacity') in controller.est.CAPACITIES
                and cp['selected_capacity'] == status.get('selected_capacity'), 'EXACT_SELECTED_PAST_CAPACITY_REQUIRED')
            expected = {q if paradigm=='QUANTILE_HGB' else seed for seed,q in controller.components(paradigm)}
            _require(set(status.get('complete_components', ())) == expected, 'ALL_REQUIRED_SEEDS_QUANTILES_REQUIRED')
            for seed,q in controller.components(paradigm):
                slot=ledger['slots'][f'OUTER_{paradigm}_{seed}_{q}']
                _require(slot['status']=='COMPLETE' and slot.get('selected_capacity')==cp['selected_capacity'],
                         'COMPLETE_ROLE_REQUIRES_EVERY_OUTER_FIT')
            _require(ledger['slots']['SCALER_2025-01-01']['status']=='COMPLETE', 'COMPLETE_ROLE_REQUIRES_OUTER_SCALER')
            pin(a['score_paths'][cid])
            for field in ('pairs','matched'): pin(a['diagnostic_paths'][cid][field])
    return a, f, ledger, caps


def ledger_counts(ledger):
    """Separate backend entry from reservation and pre-entry engineering failure."""
    slots = list(ledger['slots'].values())
    result = dict(actual_backend_calls=sum(bool(s.get('backend_entered')) for s in slots),
        estimator_calls=sum(s['kind']=='estimator' and bool(s.get('backend_entered')) for s in slots),
        scaler_calls=sum(s['kind']=='scaler' and bool(s.get('backend_entered')) for s in slots),
        charged_reservations=sum(bool(s.get('charged')) for s in slots),
        completed_slots=sum(s['status']=='COMPLETE' for s in slots),
        failed_fit_calls=sum(s['status']=='FAILED' and bool(s.get('backend_entered')) for s in slots),
        failed_slots=sum(s['status']=='FAILED' for s in slots),
        blocked_active_slots=sum(s['status']=='BLOCKED' for s in slots),
        active_ceiling=122, hard_cap=380, scientific_retry=0,
        blocked_outer_head_years=18, blocked_nominal_estimator_slots=238,
        blocked_nominal_scaler_slots=6, blocked_nominal_slots_are_not_reservations=True)
    result['by_paradigm'] = {}
    for paradigm in controller.est.PARADIGMS:
        items = [s for s in slots if s.get('paradigm')==paradigm]
        result['by_paradigm'][paradigm] = dict(actual_backend_calls=sum(bool(s.get('backend_entered')) for s in items),
            complete=sum(s['status']=='COMPLETE' for s in items), failed=sum(s['status']=='FAILED' for s in items),
            blocked=sum(s['status']=='BLOCKED' for s in items), charged=sum(bool(s.get('charged')) for s in items))
    return result


def reference_labels(d):
    path = pin(d['raw_score'])
    shared.prove_label_boundary(path, 'label_end_date', allow_null=True)
    ref = pre2026(path, KEY+['ticker','U_t_fingerprint','score','rank','target','label_end_date'], 'signal_date')
    ref = ref.rename(columns={'score':'raw_score','rank':'raw_rank'})
    ref['signal_date'] = pd.to_datetime(ref.signal_date); ref['label_end_date'] = pd.to_datetime(ref.label_end_date)
    _require(len(ref)==313668 and ref.signal_date.nunique()==752 and not ref.duplicated(KEY).any()
        and ref.signal_date.dt.year.isin(ev.YEARS).all(), 'EXACT_752_FULL_U_EVALUATION_REFERENCE_REQUIRED')
    _require(ref.loc[ref.label_end_date.isna(),'target'].isna().all(), 'UNKNOWN_TAIL_LABEL_MUST_REMAIN_UNKNOWN')
    return ref.sort_values(KEY,kind='stable').reset_index(drop=True)


def bound_2025_panel(ref, item, cid):
    panel = pre2026(pin(item), KEY+['ticker','U_t_fingerprint','rank','candidate_id','score'], 'signal_date')
    panel['signal_date'] = pd.to_datetime(panel.signal_date)
    panel = panel.sort_values(KEY,kind='stable').reset_index(drop=True)
    _require(panel.signal_date.dt.year.eq(2025).all() and panel.candidate_id.eq(cid).all()
        and panel[KEY+['ticker','U_t_fingerprint']].equals(ref[KEY+['ticker','U_t_fingerprint']]),
        'EXACT_2025_FULL_U_IDENTITY_REQUIRED')
    _require(np.isfinite(panel[['rank','score']].to_numpy(float)).all(), 'FINITE_BOUNDARY_MEMBERSHIP_REQUIRED')
    return panel


def matched_reader(item):
    """A proven physical zero-row matched table cannot expose a future row."""
    path=pin(item);columns=list(controller.pairs.PAIR_KEYS)+['predicted_edge']
    footer=pq.ParquetFile(path)
    if footer.metadata.num_rows==0:
        _require(set(columns).issubset(footer.schema_arrow.names), 'EMPTY_MATCHED_SCHEMA_REQUIRED')
        out=pq.read_table(path,columns=columns).to_pandas()
        _require(len(out)==0, 'PHYSICAL_EMPTY_MATCHED_REQUIRED')
        out['signal_date']=pd.to_datetime(out.signal_date)
        return out
    return pre2026(path,columns,'signal_date')


def pair_truth(reference, geometry):
    truth=[]
    for uid in ('challenger_uid','incumbent_uid'):
        merged=geometry[['signal_date',uid]].merge(reference[KEY+['target']],
            left_on=['signal_date',uid],right_on=KEY,how='left',validate='many_to_one',indicator=True)
        _require(merged._merge.eq('both').all(), 'PAIR_UID_MUST_BE_IN_FULL_U_REFERENCE')
        truth.append(merged.target.to_numpy(float))
    return truth[0]-truth[1]


def _concat(tables, columns):
    available=[t for t in tables if len(t)]
    return pd.concat(available,ignore_index=True) if available else pd.DataFrame(columns=columns)


def _number(value, scale=1., digits=3):
    return '—' if value is None or pd.isna(value) else f'{float(value)*scale:.{digits}f}'


def report_text(root, d, evidence, pairreceipt, caps, daily, pairdaily, yearly, histogram, oracle):
    count=evidence['fit_counts']; lines=[
        '# C12 Raw 锚定边界决策学习：完整交付报告', '',
        '**最终状态：`C12_PARTIAL_INPUT_BLOCKED`。2025 可用路径已完成训练终态与描述性评价；2023/2024 缺少合法的早年 full-U Raw tie 身份，九个新角色都没有完整共同 OOF。**',
        '因此本轮不能作出“九个范式没有效”或“已找到胜出模型”的统计结论。新角色的 pooled / simultaneous lower bound 均为空，支持条件未具备。', '',
        '## 目标、限制与实际过程', '',
        '目标是在冻结 Raw A2 Top10 核心和 Top40 边界、BASE32 信息及原 mean ER target 的条件下，学习 Raw21–40 challenger 对 Raw11–20 incumbent 的替换边。它研究边界决策 objective，不是重训 Raw A2、修改风险表示或配置账户。',
        '每个日期固定 20×10=200 条 pair，date 总权重 1，两侧股票等权；没有 abs-edge 权重。保持完整 U_t，保留原始 security UID、Raw ordinal rank、缺失旗标和上次合法交易日历史。正边执行至多十对一对一匹配，未匹配 incumbent 留下；所有下游交易规则保持冻结。',
        '开发、scaler、容量选择和拟合严格早于 2026；outer 2025 容量只来自 2024 两个 chronological inner fold。2023/24 被阻塞，不删除年份或改变共同 732 日。2025、历史研究窗口已经暴露，不能称为独立 holdout。',
        '本研究是用户授权的新 C12 科学问题；canonical registry 的 `BLOCKED_CLOSED_BRANCH` 自动记录保留，未伪造 registry PASS，未重开旧 R4/R5/C7/C10/C11。冻结历史 source 可做 mechanism research，`strict_PIT_promotion_eligible=false`，不能晋级严格 PIT 生产策略。',
        '九范式为 Logit、Ridge、Huber、HGB、XGB、CatBoost、MLP、四 horizon Multi-task MLP 和 q10/q50/q90 Quantile HGB。每范式只有预冻结 LOW/MID/HIGH 三档；Cat/MLP/Multi-task 全部三个固定 seed 必须完成并等权，Quantile 三个模型必须完成，失败不补模型、不加时、不重试。', '',
        '## 按任务书逐项回答', '',
        f"1. **pair 总量与 SHA**：{pairreceipt['pairs_count']:,} 行、752 日期、每日期 200 条。冻结 key SHA `{pairreceipt['pair_key_sha256']}`；构造时 target 值读取 0。",
        '2. **各年 training pair 数**：2023、2024 outer 为输入阻塞，未虚构训练量；2025 outer cutoff 2025-01-01 为 96,400。两个 inner cutoff 分别 46,000 / 70,800，所有训练 pair 和四 horizon 均共同成熟。',
        '3. **training dates**：对应三个可用 cutoff 为 230 / 354 / 482；inner validation 为 104 / 128 日期，容量 utility 是实际匹配后、日期等权的收益边。原主评价依然 2023/24/25 的 250 / 252 / 230 = 732 共同成熟日期，原位置日历 752。',
        '4. **每个范式的真实 backend 数量与容量**：下表计 backend_entered，不把 reservation 或未调用 slots 算成实际训练。', '',
        '| 范式 | entered | COMPLETE | FAILED slots | BLOCKED slots | 2025 选定容量 | 必须组件 |',
        '|---|---:|---:|---:|---:|---|---|']
    for p in controller.est.PARADIGMS:
        item=count['by_paradigm'][p];cp=caps[p]
        required=', '.join(f'{s}:{q}' for s,q in controller.components(p))
        lines.append(f"| {p} | {item['actual_backend_calls']} | {item['complete']} | {item['failed']} | {item['blocked']} | {cp.get('selected_capacity') or 'BLOCKED'} | {required} |")
    lines += ['', f"5. **actual estimator fits**：{count['estimator_calls']}。",
        f"6. **actual scaler fits**：{count['scaler_calls']}；仅三个 cutoff 的共享 weighted scaler，每个一次，跨容量/范式/seed 不重复拟合。",
        f"7. **failed fits**：进入 backend 后失败 {count['failed_fit_calls']} 次；全部 FAILED slot {count['failed_slots']} 个，两者分别披露。",
        f"8. **blocked slots / budget**：active BLOCKED {count['blocked_active_slots']}；charged reservation {count['charged_reservations']}，实际 backend {count['actual_backend_calls']}。active cap 122 = 119 estimator + 3 scaler，hard cap 380，retry 0。早年阻塞的 18 head-year / 238 estimator / 6 scaler 是 nominal 缺失依赖，未登记虚假 reservation/fit。",
        '9. **各年选定容量**：2023/24 为 null / 输入阻塞；2025 各范式上表。LOW/MID/HIGH 一律仅按两个过去 inner fold 的日期等权 utility，1e-12 tie 依 LOW→MID→HIGH；没有 outer outcome 倒流。',
        '10. **seed 完整性**：Cat、MLP、Multi-task 使用 20260928/20260929/20260930 全部 required；其余固定 20260928。Quantile 的 q10/q50/q90 全部 required，各算一个 backend；不挑 seed/quantile、不静默丢弃失败组件。',
        '11. **九范式各年 edge**：2023/24 均为 null；以下 2025 数字仅是 partial 描述性结果，不能进入共同 OOF 主检验。2025 全 250 个实际日期诊断保留，尾部未知 label 保留 null；原共同成熟 230 日期才计 replacement edge。', '',
        '| 角色 | 2023 | 2024 | 2025 描述性 edge(bp) | 共同成熟日期 | Raw overlap | 日均替换数 | 实际替换 pair均值(bp) | pair regret(bp) |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for cid in ev.ROLES:
        yd=yearly.loc[yearly.candidate_id.eq(cid)] if len(yearly) else yearly
        dd=daily.loc[daily.candidate_id.eq(cid)] if len(daily) else daily
        pp=pairdaily.loc[pairdaily.candidate_id.eq(cid)] if len(pairdaily) else pairdaily
        row=yd.iloc[0] if len(yd) else {}
        lines.append(f"| {cid} | — | — | {_number(row.get('replacement_edge'),10000)} | {int(dd.common_mature_date.sum()) if len(dd) else 0} | {_number(row.get('raw_overlap'))} | {_number(row.get('replacement_count'))} | {_number(row.get('selected_replacement_realized_edge'),10000)} | {_number(pp.pair_regret.mean() if len(pp) else None,10000)} |")
    lines += ['', '12. **pooled edge**：九个新角色均为 null。没有将 2025 的 partial mean 命名为 pooled 2023–25，也未填补阻塞年份。',
        '13. **simultaneous lower bound**：九个新角色均为 null / FAILED_UNTESTABLE，supported 全 false；这是不具备共同检验输入，不能解释为统计上的负结果。',
        f"14. **累计 multiple testing**：147 条真实完整 numeric series；178 exposure = 原 169 + 新 9，旧 22 failed / blocked 继续保留。5000 次共享 block=20 bootstrap、seed=20260928；critical maxT {_number(evidence['bootstrap']['critical_max_t'],digits=6)}，原 147 的 critical {_number(evidence['bootstrap']['legacy_critical_max_t'],digits=6)}。缺失新 series 不填零、不缩成 2025；每次抽样的旧最大统计量不下降。",
        '15. **Raw overlap**：见第 11 项，按完整 U_t 的 Raw Top20 与冻结匹配 Top20 交集 /20；Raw Top10 始终保留。',
        '16. **替换数量、来源 Raw rank 与边界贡献**：0–10 完整 histogram 见 REPLACEMENT_COUNT_DISTRIBUTION；matched 两侧 Raw rank 见 REPLACEMENT_RANK_DISTRIBUTION。PARTIAL_DAILY 中另外记录 challenger Raw35–40、incumbent Raw19–20 计数、双方平均 Raw rank 和未匹配 incumbent 数。',
        '17. **实际替换 pair 的 realized mean edge**：见第 11 项及逐日文件。单对均值与主 replacement edge 的总边 /20 分开，不用替换次数变化冒充主指标改善。',
        '18. **pair decision regret**：mean(max(realized_pair_edge,0) − realized_pair_edge × predicted_eligible)，仅 isolated-pair 描述性诊断，不是 matching/account regret，不作 selection。',
        '19. **boundary oracle headroom**：以下只在全部训练终态、容量选择与 FINAL_PIPELINES_FREEZE 核验之后计算。固定 RawTop10，Raw11–40 事后最佳10；不能用于 inner、调参、挑新模型或下一轮设计。', '',
        '| 年 | 实际诊断日期 | labels成熟日期 | oracle平均 headroom(bp) |', '|---|---:|---:|---:|']
    for year in ev.YEARS:
        take=oracle.loc[oracle.year.eq(year)]
        lines.append(f"| {year} | {len(take)} | {int(take.common_boundary_labels_mature.sum())} | {_number(take.boundary_oracle_headroom.mean(),10000)} |")
    lines += ['', '20. **是否找到统计支持**：共同 732 OOF 中没有可检验的新 C12 series，supported=[]。不能说“九范式全部被统计否定”，也没有 finalist / promotion。',
        '21. **依赖状态**：C6A=BLOCKED_INPUT；C8=BLOCKED_DEPENDENCY；C11-B=BLOCKED_SHARED_RISK。没有补造新闻、收益历史或共享风险 bank；无新 source archaeology。',
        '22. **2026 锁**：fit / evaluation / outcome read / 新 state estimation 均为 0；不解锁 2026，不读 2027+，不把旧暴露窗口重新称独立留出。',
        '23. **C13**：没有启动、预注册或训练 C13；本交付不以 oracle 或 partial 2025 的结果选择下一轮模型。', '',
        '## 额外诊断、故障与未完成项', '',
        'PAIR_DIAGNOSTICS / PAIR_CALIBRATION 提供预冻结固定 bins 的概率/边校准、sign accuracy、Brier、pair regret；P8 四 horizon disagreement、P9 原生 quantile crossing 均保留。这里只是结果描述，没有追加 calibration fit。',
        'member turnover 指前一个可用 policy 日的成员变化，既不是 persistent-account turnover，也不是滑点或交易净收益。未执行账户引擎，不能据这些数值声明扣费后赚钱或 strict-PIT production upgrade。',
        '首个 delivery source 写入遇到 Windows stdin Unicode 编码失败，仅任务自有空文件；在正式 freeze / y 读取之前以 UTF-8 修复，未消耗 fit、未改科学参数。训练故障和工程故障分别保存在 FIT_LEDGER、各组件元信息与日志；以下逐项保留 FAILED，不退款、不重试：']
    failures=evidence['failed_fit_records']
    lines += [f"- `{s['id']}`：entered={s.get('backend_entered',False)}；{s.get('error',s.get('reason','FAILED'))}" for s in failures] if failures else ['- 没有 FAILED slot。']
    lines += ['', '计划的完整三年九范式 OOF 未完成；缺的是合法早年 full-U Raw tie 身份及可恢复原状态。没有以 UID 重排、Top40 局部 checkpoint 或重新训练 Raw 补造 authority；2023/24 的缺失并不自动授权未来修复运行。',
        '下一步只应在取得合法早年 authority 后，另行明确授权并冻结补全路径；本次保留目前 partial 结果和闭合账本，不能用 2025/Oracle 结果追调容量或赢家。', '',
        '## 存储、复用与审计', '',
        f"- 唯一实验、model、prediction、ledger：`{root}`。",
        f"- 报告与审计：`{evidence['results_directory']}`。",
        '- 源码在 D:/us-tech-quant；缓存通过共享 resolver 落 D 外部 cache；无 C 聊天目录业务产物、无 E/F/provider 读取、无 canonical 数据写入。',
        '- 源码、pair geometry、input qualification、DAG、正式 freeze、终态 ledger、assembly、final pipelines 与每个输出 SHA 都进入交付 receipt；已有失败、旧研究 closed 状态和其他任务产物保留。',
        '- 复用现有 weighted scaler/native learner、pair matching、maturity/replacement edge 和 shared maxT；没有第二 learner/risk/account/statistics 平台。']
    return '\n'.join(lines)+'\n'


def run(root):
    root=safe_d(root);cfg,d,pairreceipt=controller.checked(root)
    out=safe_d(root/'diagnostics'/'selector_evidence');results=safe_d(cfg['results_directory'])
    assert_safe_output_path(results,kind='results')
    new_outputs([*[out/name for name in DIAGNOSTICS],out/'SELECTION_EVIDENCE.json',
        *[results/name for name in REPORT_FILES],root/'DELIVERY_COMPLETE.json'], 'C12_DELIVERY')
    assembly, final, ledger, caps=terminal_receipts(root,d)
    evaluation=d['evaluation'];legacy=evaluation['legacy']
    ev.validate_legacy_metadata(readj(pin(legacy['design'])),readj(pin(legacy['assembly'])),legacy)
    pin(legacy['evidence'])  # historical evidence body remains opaque; no reselection
    clock=pre2026(pin(legacy['clock']),['signal_date','included'],'signal_date')
    clock['signal_date']=pd.to_datetime(clock.signal_date)
    _require(len(clock)==752 and clock.signal_date.is_unique and clock.signal_date.is_monotonic_increasing
        and clock.included.notna().all() and pd.api.types.is_bool_dtype(clock.included), 'ORIGINAL_CLOCK_REQUIRED')
    old=pre2026(pin(legacy['edge']),['signal_date',*legacy['numeric_ids']],'signal_date')
    old['signal_date']=pd.to_datetime(old.signal_date);old=old.set_index('signal_date')
    matrix, tests, boot, maxima=ev.statistics(old,pd.DataFrame(index=old.index),
        np.flatnonzero(clock.included.to_numpy()),pd.DatetimeIndex(clock.signal_date),
        evaluation['bootstrap'],legacy['numeric_ids'],assembly['failed_or_untestable'])
    ref=reference_labels(d);ref2025=ref.loc[ref.signal_date.dt.year.eq(2025)].reset_index(drop=True)
    common=clock.set_index('signal_date').included
    geometry=pre2026(pin(pairreceipt['pairs']),list(controller.pairs.PAIR_KEYS),'signal_date')
    geometry['signal_date']=pd.to_datetime(geometry.signal_date)
    _require(controller.pairs.pair_key_sha256(geometry)==d['pair_key_sha256'], 'FROZEN_PAIR_KEYS_CHANGED')
    expected=geometry.loc[geometry.signal_date.dt.year.eq(2025)].reset_index(drop=True)
    _require(len(expected)==50000 and expected.signal_date.nunique()==250, 'FULL_250_DAY_2025_PAIR_GEOMETRY_REQUIRED')
    daily=[];pairdaily=[];bins=[];ranks=[]
    for cid in assembly['complete_2025_candidates']:
        panel=bound_2025_panel(ref2025,assembly['score_paths'][cid],cid)
        daily.append(ev.daily_diagnostics(cid,ref2025,panel,common))
        binding=assembly['diagnostic_paths'][cid]
        columns=list(controller.pairs.PAIR_KEYS)+['prediction_0']
        if cid==ev.ROLES[8]:columns+=['prediction_1','prediction_2']
        hcols=[f'horizon_prediction_{h}d' for h in (3,5,10,20)] if cid==ev.ROLES[7] else []
        pp=pre2026(pin(binding['pairs']),columns+hcols,'signal_date');pp['signal_date']=pd.to_datetime(pp.signal_date)
        _require(pp[list(controller.pairs.PAIR_KEYS)].equals(expected), 'EXACT_FULL_2025_PAIR_KEYS_REQUIRED')
        matched=matched_reader(binding['matched'])
        prediction=pp[['prediction_0','prediction_1','prediction_2']].to_numpy(float) if cid==ev.ROLES[8] else pp.prediction_0.to_numpy(float)
        pdaily,calibration,rank=ev.pair_diagnostics(cid,pp,prediction,pair_truth(ref2025,pp),matched,
            pp[hcols].to_numpy(float) if hcols else None)
        pairdaily.append(pdaily);bins.append(calibration);ranks.append(rank)
    dd=_concat(daily,['candidate_id','signal_date','year','replacement_count','common_mature_date','replacement_edge'])
    pdd=_concat(pairdaily,['candidate_id','signal_date','year','pair_regret'])
    cb=_concat(bins,['candidate_id','signal_date','year','bin_id'])
    rk=_concat(ranks,['candidate_id','signal_date','year','side','raw_rank'])
    yearly,hist=ev.summarize_diagnostics(dd) if len(dd) else (pd.DataFrame(columns=['candidate_id','year']),pd.DataFrame(columns=['candidate_id','year','replacement_count','dates']))
    oracle=ev.oracle_headroom(ref,final)
    outputs=[clock,matrix.rename_axis('signal_date').reset_index(),pd.DataFrame({'draw':np.arange(len(maxima)),'max_t':maxima}),dd,pdd,cb,rk,yearly,hist,oracle]
    artifacts={}
    for name,value in zip(DIAGNOSTICS,outputs):
        path=safe_d(out/name);assert_safe_output_path(path);value.attrs={};value.to_parquet(path,index=False)
        artifacts[name]=dict(path=str(path),sha256=sha(path))
    evidence=dict(status='C12_PARTIAL_INPUT_BLOCKED',research_id=ev.RESEARCH_ID,primary=ev.PRIMARY,
        tests=tests,bootstrap=boot,numeric_complete_series=len(matrix.columns),exposure_namespace=178,
        common_mature_date_count=732,original_calendar_dates=752,year_counts=ev.YEAR_COUNTS,
        complete_common_732_candidates=[],supported=[],complete_2025_candidates=assembly['complete_2025_candidates'],
        outer_pipeline_status=assembly['outer_pipeline_status'],
        failed_or_untestable={**legacy['failed_or_untestable'],**assembly['failed_or_untestable']},
        exposure_ids=[*legacy['exposure_ids'],*ev.ROLES],numeric_ids=list(matrix),
        descriptive_partial_2025=True,mechanisms_testable=False,
        design_freeze_sha256=sha(root/'DESIGN_FREEZE.json'),score_assembly_sha256=sha(root/'SCORE_ASSEMBLY.json'),
        final_pipelines_freeze_sha256=sha(root/'FINAL_PIPELINES_FREEZE.json'),fit_ledger_sha256=sha(root/'FIT_LEDGER.json'),
        fit_counts=ledger_counts(ledger),failed_fit_records=[s for s in ledger['slots'].values() if s['status']=='FAILED'],
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,economic_promotion_allowed=False,
        test2026_locked=True,fit2026_rows=0,evaluation2026_rows=0,outcome2026_reads=0,new2026_state_estimations=0,
        new2026_estimation_authorized=False,C13_started=False,C6A='BLOCKED_INPUT',C8='BLOCKED_DEPENDENCY',C11_B='BLOCKED_SHARED_RISK',
        results_directory=str(results),artifacts=artifacts)
    _require(len(matrix.columns)==147 and all(not t['supported'] and t['pooled_edge'] is None for t in tests), 'NO_PARTIAL_NUMERIC_OR_SUPPORT_ALLOWED')
    put(out/'SELECTION_EVIDENCE.json',evidence);put(results/'SELECTION_EVIDENCE.json',evidence)
    report=report_text(root,d,evidence,pairreceipt,caps,dd,pdd,yearly,hist,oracle)
    (results/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    put(results/'MODEL_UPDATE_GATE.json',dict(status='PARTIAL_INPUT_BLOCKED',supported=[],production_finalists=[],
        strict_PIT_promotion_eligible=False,economic_promotion_allowed=False,test2026_locked=True,
        new2026_estimation_authorized=False,C13_started=False,blocked_dependencies=['C6A','C8','C11_B','EARLY_FULL_U_RAW_TIE_IDENTITY']))
    for path,digest in d['sources'].items():pin(dict(path=path,sha256=digest))
    _require(sha(root/'FIT_LEDGER.json')==evidence['fit_ledger_sha256']
        and sha(root/'FINAL_PIPELINES_FREEZE.json')==evidence['final_pipelines_freeze_sha256']
        and sha(root/'SCORE_ASSEMBLY.json')==evidence['score_assembly_sha256'], 'TERMINAL_RECEIPTS_CHANGED_DURING_DELIVERY')
    from scripts.maintenance.audit_repo_size_r1 import audit
    storage=audit(controller.REPO);put(results/'STORAGE_AUDIT.json',storage)
    _require(not storage['violations'] and storage['accounting_complete'] and storage['hard_limit_passed'], 'REPOSITORY_STORAGE_AUDIT_REQUIRED')
    execution=dict(status=evidence['status'],research_id=ev.RESEARCH_ID,
        report=dict(path=str(results/'FINAL_REPORT.md'),sha256=sha(results/'FINAL_REPORT.md')),
        selection_evidence=dict(path=str(results/'SELECTION_EVIDENCE.json'),sha256=sha(results/'SELECTION_EVIDENCE.json')),
        model_update_gate=dict(path=str(results/'MODEL_UPDATE_GATE.json'),sha256=sha(results/'MODEL_UPDATE_GATE.json')),
        storage_audit=dict(path=str(results/'STORAGE_AUDIT.json'),sha256=sha(results/'STORAGE_AUDIT.json')),
        design_freeze_sha256=evidence['design_freeze_sha256'],fit_ledger_sha256=evidence['fit_ledger_sha256'],
        final_pipelines_freeze_sha256=evidence['final_pipelines_freeze_sha256'],score_assembly_sha256=evidence['score_assembly_sha256'],
        numeric_complete_series=147,exposure_namespace=178,fit_counts=evidence['fit_counts'],artifacts=artifacts,
        source_pins_preserved=True,strict_PIT_promotion_eligible=False,test2026_locked=True,outcome2026_reads=0,
        E_F_provider_reads=0,canonical_writes=0,chat_business_artifacts=0,C13_started=False)
    put(results/'EXECUTION_RECEIPT.json',execution)
    put(root/'DELIVERY_COMPLETE.json',dict(status=evidence['status'],research_id=ev.RESEARCH_ID,
        report=execution['report'],execution_receipt=dict(path=str(results/'EXECUTION_RECEIPT.json'),sha256=sha(results/'EXECUTION_RECEIPT.json')),
        selection_evidence=execution['selection_evidence'],completed_at=now(),test2026_locked=True))
    putj(root/'PIPELINE_STATE.json',dict(status=evidence['status'],delivery_complete=True,at=now(),fit_counts=evidence['fit_counts']))
    cfg.update(status=evidence['status'],completed_at=now(),run_end=now(),design_freeze_sha256=evidence['design_freeze_sha256']);putj(root/'run_config.json',cfg)
    print(json.dumps(dict(phase='DELIVERY',status=evidence['status'],numeric=147,exposure=178,supported=[])),flush=True)
    return evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True)
    run(safe_d(parser.parse_args().run))