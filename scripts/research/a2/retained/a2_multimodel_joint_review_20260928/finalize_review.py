"""Validate review receipts and create explicit result labels and delivery seal."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    source = read('FROZEN_SOURCE_AFTER.json')
    stack = read('stack_evidence/RESULT.json')
    cash = read('cash_attribution/CHECKS.json')
    comp = read('complementarity/FINAL_VERIFICATION.json')
    independent = read('INDEPENDENT_CHECKS.json')
    assert source['status'] == cash['status'] == comp['status'] == independent['status'] == 'PASS'
    assert stack['status'] == 'PASS_POSTHOC_FULL_2025_RECONSTRUCTION'
    assert stack['no_fit_attempts'] == 0 and stack['original_input_hashes_unchanged']
    assert comp['trained_models'] == comp['new_replays'] == comp['new_fusions'] == 0
    assert comp['used_2026'] is False
    fingerprint = stack['posthoc_verification']
    assert fingerprint['validation_exact_cells'] == fingerprint['action_values'] == 552190
    assert fingerprint['validation_target_mismatches'] == 0
    checks = []
    for name in ['complementarity/PREDICTION_AUDIT.json', 'complementarity/COMMON_ACCOUNT_AUDIT.json',
                 'complementarity/FINAL_VERIFICATION.json']:
        record = read(name)
        for group in ('input_sha256', 'output_sha256'):
            for path, expected in record.get(group, {}).items():
                actual = sha(path)
                assert actual == expected, (name, group, path, expected, actual)
                checks.append((name, group, path))
    labels = dict(
        scope='Qualifies existing frozen results; does not overwrite original reports or reselect models',
        stack_2025=dict(
            label='2025 冻结 validation 堆叠的回溯价格指数结果；原预测与目标经事后全量重现；非盲测，缺原始逐策略运行时加载记录。',
            validation_meta_label_end='2024-12-31', final_meta_label_end='2025-12-31',
            observed_return_retained=True,
            original_runtime_load_receipt_present=False,
            posthoc_full_output_reconstruction=True,
            unsupported_claims=['原始运行时加载日志齐全', '独立盲测冠军', '已认证完整13F历史池和所有未来泄漏风险']),
        equal_weight_2025=dict(
            label='原冻结价格指数账本的描述性现金和损益分解；已逐日、逐股对账，不是删除成员或取消约束后的因果收益。',
            mean_member_cash=cash['mean_cash_stages']['mean_member_cash_weight'],
            top20_cash_added=cash['mean_cash_stages']['top20_cash_added_weight'],
            matched_close_cash=cash['paired_248_close_cash_mean'],
            full_period_cash=cash['all_250_day_cash_mean'],
            gross_pnl=cash['gross_pnl'], fees=cash['fees'], net_pnl=cash['net_pnl']),
        complementarity=dict(
            label='存在局部事后误差补足和动作分歧；尚未证明固定集成具有稳定、可事先利用的增益。',
            prediction_comparisons='Only compatible reward utility outputs; classification and quantile scores evaluated separately',
            portfolio_action_comparisons='Same frozen equal-weight account state',
            single_step_diagnostics='POSTHOC_NONCAUSAL_NOT_A_PORTFOLIO_REPLAY',
            pre_top20_average_is_feasible_portfolio=False,
            total_target_turnover_increase_supported=False,
            new_champion_selected=False),
        evaluation_2026=dict(
            changed=False, used_for_model_selection=False,
            inherited_limitations='Original retrospective subpool, valuation and nonblind limitations remain; this review does not certify or upgrade them.'),
        unresolved_evidence=['Original per-policy runtime load hashes were not recorded.',
                             'No causal marginal-member path effect was estimated.',
                             'Stable prospective benefit of the fixed ensemble remains unproved.'])
    write('RESULT_LABELS.json', labels)
    required = ['REPORT.md', 'stack_evidence/REPORT.md', 'cash_attribution/REPORT.md',
                'complementarity/REPORT.md', 'cash_and_pnl.png', 'cash_and_pnl.svg']
    for name in required:
        assert (ROOT / name).is_file(), name
    links = []
    for name in required[:4]:
        content = (ROOT / name).read_text(encoding='utf-8')
        for target in re.findall(r'\]\((C:/[^)]+)\)', content):
            target = re.sub(r':\d+$', '', target)
            if Path(target).resolve() != (ROOT / 'COMPLETION.json').resolve():
                assert Path(target).is_file(), (name, target)
            links.append(target)
    completion = dict(status='REVIEW_COMPLETE_WITH_EXPLICIT_EVIDENCE_LIMITS',
                      finalized_utc=datetime.now(timezone.utc).isoformat(),
                      frozen_source_files_checked=source['files_checked'],
                      frozen_source_unchanged=True,
                      model_fits=0, added_models=0, added_seeds=0, added_fusions=0,
                      portfolio_replays=0, new_2026_based_selection=False,
                      agent_receipt_hash_checks=len(checks), local_links_checked=len(links),
                      independent_checks=independent,
                      evidence_limits=labels['unresolved_evidence'])
    # Do not include this self-referential manifest in its own hashes.
    files = [p for p in ROOT.rglob('*') if p.is_file() and p.name != 'COMPLETION.json'
             and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')]
    completion['delivery_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in sorted(files)}
    write('COMPLETION.json', completion)
    assert all(Path(target).is_file() for target in links)
    print(json.dumps({k: v for k, v in completion.items() if k not in ('delivery_sha256', 'independent_checks')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
