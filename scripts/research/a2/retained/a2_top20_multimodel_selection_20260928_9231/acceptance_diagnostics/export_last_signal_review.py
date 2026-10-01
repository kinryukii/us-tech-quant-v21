"""Join the existing diagnostic and bridge exports for one readable review file."""
from pathlib import Path
import json

import pandas as pd

HERE = Path(__file__).resolve().parent
POLICIES = ['ensemble_equal', 'ensemble_disagreement', 'ensemble_stacking', 'joint_hgb']
DATE = pd.Timestamp('2026-09-22')
KEYS = ['policy', 'signal_date', 'ticker']


def main():
    assert (HERE / 'bridge/COMPLETE.json').exists()
    assert (HERE / 'selection/COMPLETE_2026.json').exists()
    frames = []
    for policy in POLICIES:
        bridge = pd.read_parquet(HERE / f'bridge/actual_account_bridge_2026_{policy}.parquet',
                                 filters=[('signal_date', '=', DATE)])
        reference = pd.read_parquet(HERE / 'selection/scores_2026.parquet',
                                    filters=[('signal_date', '=', DATE), ('policy', '=', policy)])
        assert not reference.duplicated(KEYS).any() and not bridge.duplicated(KEYS).any()
        frame = bridge.merge(reference, on=KEYS, how='outer', validate='one_to_one')
        contributions = pd.read_parquet(HERE / 'selection/ensemble_contributions_2026.parquet',
                                       filters=[('signal_date', '=', DATE), ('policy', '=', policy)])
        if len(contributions):
            contributions = contributions.drop(columns=['reference_score'])
            contributions = contributions.rename(columns={c: 'reference_' + c for c in contributions if c not in KEYS})
            frame = frame.merge(contributions, on=KEYS, how='left', validate='one_to_one')
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    selected = combined.loc[combined.reference_top20.fillna(False) | combined.actual_state_top20.fillna(False)
                            | combined.target_weight.gt(0) | combined.post_units.gt(0)].copy()
    selected = selected.sort_values(['policy', 'reference_rank', 'actual_state_rank', 'ticker'], kind='stable')
    columns = KEYS + ['reference_rank', 'reference_score', 'reference_top20', 'rank_tie_group_size',
                     'actual_state_rank', 'actual_score_5pct_vs_exit', 'new_buy_eligible',
                     'known_glw_input_conflict', 'raw_chosen_weight', 'target_weight',
                     'target_order_type', 'signal_cash_weight', 'signal_implied_cash_weight',
                     'available_slots', 'available_weight', 'zero_target_explanation',
                     'target_adaptation_reasons', 'execution_date', 'execution_explanation',
                     'execution_reasons', 'buy_notional', 'sell_notional', 'recorded_cost',
                     'reconstructed_capacity_limited', 'post_units', 'post_weight', 'post_price_status',
                     'execution_cash_weight', 'label_status', 'forward_return']
    columns += [c for c in selected if c.startswith('reference_contribution_')]
    columns += [c for c in selected if c.startswith('base_') and c.endswith('_contribution_5pct')]
    columns += ['reference_disagreement_penalty', 'reference_downside_penalty',
                'base_rank_std_5pct', 'disagreement_penalty_5pct', 'downside_penalty_5pct']
    selected[columns].to_csv(HERE / 'LAST_SIGNAL_THREE_LAYER.csv', index=False, encoding='utf-8-sig')
    notes = []
    for policy, group in selected.groupby('policy', sort=False):
        top = group[group.reference_top20.fillna(False)]
        notes.append({'policy': policy, 'reference_top20': len(top),
                      'also_actual_state_top20': int(top.actual_state_top20.fillna(False).sum()),
                      'positive_actual_target': int(top.target_weight.gt(0).sum()),
                      'held_after_execution': int(top.post_units.gt(0).sum()),
                      'actual_trade_rows': int((top.buy_notional.gt(0) | top.sell_notional.gt(0)).sum())})
    (HERE / 'LAST_SIGNAL_REVIEW.json').write_text(json.dumps({
        'signal_date': str(DATE.date()), 'rows': len(selected), 'policies': notes,
        'scope': 'Last original signal only. Reference scores are new fixed-state historical diagnostics; '
                 'actual-state scores and decisions come from the original account records. '
                 'Neither ranking constitutes a new buy recommendation.',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(notes, ensure_ascii=False))


if __name__ == '__main__':
    main()
