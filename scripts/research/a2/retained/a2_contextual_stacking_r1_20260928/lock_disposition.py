"""Record the predeclared disposition from 2025 only, before 2026 analysis."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    destination = ROOT / 'RESEARCH_DISPOSITION.json'
    assert not destination.exists(), 'Disposition is write-once'
    fit = read(ROOT / 'meta_artifacts/FIT_RECEIPT.json')
    selected = read(ROOT / 'meta_artifacts/INTERNAL_SELECTION.json')
    paths = [ROOT / f'evaluation_2025/cost_10/{m}/DONE.json' for m in ('M0', 'M1')]
    m0, m1 = map(read, paths)
    assert selected['selection_year'] == 2024 and selected['selected_multiplier'] == 16
    assert m0['year'] == m1['year'] == 2025 and m0['cost_bps'] == m1['cost_bps'] == 10
    assert m1['indicative_return'] < m0['indicative_return']
    metrics = fit['validation_panel_prediction']['metrics']
    raw = {(r['kind'], r['output']): r for r in metrics if r['target'] == 'target_unclipped'}
    assert raw['M1', 'absolute_utility']['date_equal_mse'] > raw['M0', 'absolute_utility']['date_equal_mse']
    assert raw['M1', 'action_minus_zero_utility']['date_equal_mse'] > raw['M0', 'action_minus_zero_utility']['date_equal_mse']
    result = dict(status='FROZEN_R1_NOT_ADOPTED', experiment='A2_CONTEXTUAL_STACKING_R1',
        locked_utc=datetime.now(timezone.utc).isoformat(),
        disposition='M1不优；冻结本规格。保留全部研究工件，不追加状态、种子、窗口或成员直到获胜。',
        primary_economic_year=2025, primary_cost_bps=10,
        M0_indicative_return=m0['indicative_return'], M1_indicative_return=m1['indicative_return'],
        return_delta=m1['indicative_return']-m0['indicative_return'],
        M0_mean_cash=m0['mean_cash_weight'], M1_mean_cash=m1['mean_cash_weight'],
        raw_prediction_metrics=list(raw.values()),
        selection_year=2024, selected_interaction_multiplier=16,
        uses_2026_results=False, champions_reselected=False, promoted_to_main_strategy=False,
        M0_promoted=False,
        M0_note='静态对照本身未超过旧堆叠／HGB／MLP的既有2025主口径净收益；这些是整体参照，不能当成严格嵌套归因。',
        required_remaining_work='仍须完成固定5/25bp敏感性、2026仅推理诊断、独立核验和交付封口；它们不改变本处置。',
        result_identity='RETROSPECTIVE_NONBLIND_RESEARCH; ORIGINAL_PRICE_COORDINATE; ORIGINAL_DATA_COVERAGE_LIMITS_RETAINED',
        evidence_sha256={str(p): sha(p) for p in [*paths, ROOT/'EXPERIMENT_CONTRACT.md',
            ROOT/'meta_artifacts/FIT_RECEIPT.json', ROOT/'meta_artifacts/INTERNAL_SELECTION.json']})
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], uses_2026_results=False,
        return_delta=result['return_delta']), ensure_ascii=False))


if __name__ == '__main__': main()
