"""C R2 source-bound membership dispatch; shared account owns all economics."""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
import hashlib, importlib.util, json, traceback
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve
from scripts.research.a2.evaluation import selector_account_compare as prior
from scripts.research.a2.evaluation import continuous_research_account as common

REPO = Path(__file__).resolve().parents[4]
RUN = Path('D:/us-tech-quant-backtests/V24/20261001T171645+0000_d9382ce0')
RAW = 'RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE'
VALIDATION = Path('D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/receipts/CONTINUOUS_ACCOUNT_ENTITLEMENT_SLIPPAGE_VALIDATION.json')
PINS = {
    Path(prior.__file__): '7a8b27e7beb79473d2f2edf7c7ea5d68da6868c671d36eb3dd6203d529c703a2',
    prior.OLD / 'selector_replay.py': 'b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb',
    prior.OLD / 'replay_accounts.py': '4e32c5adc281295b57f6373a50c742a238e35fc0c6e1a2d3d8b12628ffa79402',
    Path(common.__file__): '57ace7d28e6366fe08fb325aa63aeb7db000eae007172920c82f346122bbd38a',
    REPO / 'scripts/v22/corporate_action_transition_r1.py': 'a5475608419c886cc0340e746e9ee734bfdfe7d675a2f4bfa3493685daf8ea67',
    REPO / 'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py': '200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b',
    VALIDATION: '2c02a85df269250b9f5ebe07d629d3af28a91e6c0f454c2ea52c912dbb698a9a',
}
SPEC = dict(primary_one_way_bps=10, sensitivity_one_way_bps=[0, 5, 20], fee_bps=0,
    max_account_paths=60, max_finalists=3, batch_paths=8, holding='FIXED_G1_TOP20_EQUAL_FRACTIONAL',
    cash_authority='caller-bound; synthetic component PASS never establishes real entitlement authority')
EVENT_KEYS = {'corporate_actions', 'corporate_action_known_at', 'unsupported_events',
    'entitlement_enabled', 'entitlement_events', 'entitlement_security_tickers', 'entitlement_source_binding'}


def source_identity():
    for path, expected in PINS.items():
        if prior.sha(path) != expected:
            raise ValueError('ACCOUNT_SOURCE_CHANGED:' + str(path))
    return {**{str(p): h for p, h in PINS.items()}, str(Path(__file__)): prior.sha(__file__)}


def membership_adapter():
    source_identity()
    path = prior.OLD / 'selector_replay.py'
    spec = importlib.util.spec_from_file_location('_c_r2_membership', path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def event_identity(events):
    if set(events) - EVENT_KEYS:
        raise ValueError('ONLY_COMMON_EVENT_INPUTS_ALLOWED')
    def encode(value):
        return asdict(value) if is_dataclass(value) else str(value)
    return hashlib.sha256(json.dumps(events, sort_keys=True, default=encode, allow_nan=False).encode()).hexdigest()


def replay_membership(market, membership, path_ids, *, one_way_bps, event_inputs=None, ledger_callback=None):
    helper = membership_adapter()
    policy = helper.make_membership_policy(common, membership, path_ids)
    if not pd.DatetimeIndex(market.dates)[np.asarray(market.signal_mask, bool)].equals(policy.signal_dates):
        raise ValueError('MARKET_MEMBERSHIP_SIGNAL_CALENDAR_CHANGED')
    events = {} if event_inputs is None else dict(event_inputs)
    event_identity(events)
    friction = dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE', scenario_id=f'C_R2_ONE_WAY_{one_way_bps}BP',
        one_way_bps=one_way_bps, fee_bps=0, benchmark='NEXT_RAW_OPEN', authority='HYPOTHETICAL_RESEARCH_SCENARIO')
    return common.run_continuous_account(market, tuple(path_ids), policy, dict(prior.CONFIG),
        execution_friction=friction, ledger_callback=ledger_callback, **events)


def _bound_input(activation, name, columns, clocks):
    item = activation['input_bindings'][name]
    if prior.sha(item['path']) != item['sha256']:
        raise ValueError('ACCOUNT_INPUT_CHANGED:' + name)
    return prior.pre2026(item['path'], columns, clocks)


def _activation(directory, path):
    paths = resolve(REPO)
    if directory != RUN.resolve() or not directory.is_relative_to(paths.backtest_root):
        raise ValueError('EXACT_C_R2_RUN_REQUIRED')
    cfg = prior.readj(directory / 'run_config.json')
    if cfg['research_line'] != 'C_SELECTOR' or Path(cfg['results_directory']).resolve() != (paths.results_root / 'V24/C_SELECTOR/R2').resolve():
        raise ValueError('C_R2_CONTROL_IDENTITY_REQUIRED')
    if path.resolve().parent != directory:
        raise ValueError('SAME_RUN_ACCOUNT_ACTIVATION_REQUIRED')
    a = prior.readj(path)
    if a['status'] != 'ACCOUNT_SOURCE_ACTIVATED' or a['design_sha256'] != prior.sha(directory / 'DESIGN_FREEZE.json') or a['score_assembly_sha256'] != prior.sha(directory / 'SCORE_ASSEMBLY.json'):
        raise ValueError('ACCOUNT_SOURCE_ACTIVATION_REQUIRED')
    if a['design_sha256'] != prior.readj(directory / 'DESIGN_FREEZE_SHA.json')['sha256']:
        raise ValueError('ACCOUNT_DESIGN_CHANGED')
    if any(a['sources'].get(p) != h for p, h in source_identity().items()):
        raise ValueError('ACCOUNT_SOURCE_NOT_ACTIVATED')
    design, ready = prior.readj(directory / 'DESIGN_FREEZE.json'), prior.readj(directory / 'SCORE_ASSEMBLY.json')
    expected = dict(initial_cash_usd=3000, top_k=20, target_weight=.05, gross=1., cash_target=0,
        long_only=True, margin=False, fees_bps=0, cash_interest=0, fractional=True,
        execution='NEXT_LEGAL_SESSION_RESEARCH_RAW_OPEN', account='CONTINUOUS_2023_2025_NO_YEAR_RESET_NO_TERMINAL_LIQUIDATION')
    if any(design['controls'].get(k) != v or cfg['controls'].get(k) != v for k, v in expected.items()):
        raise ValueError('FIXED_COMMON_ACCOUNT_CONTROLS_CHANGED')
    family = design['primary_account_candidates']
    if len(family) != len(set(family)) or len(family) != 41 or family[0] != RAW or not {'ridge_stack', 'hgb_stack'}.issubset(family):
        raise ValueError('PRIMARY_ACCOUNT_FAMILY_CHANGED')
    complete = set(ready['complete_candidates']) | {RAW} | set(design.get('score_reuse', {}))
    complete -= set(ready['failed_or_untestable'])
    primary = [cid for cid in family if cid in complete]
    plan = {int(b): ids for b, ids in a['scenario_candidates'].items()}
    if set(plan) - {0, 5, 10, 20} or plan.get(10) != primary:
        raise ValueError('PRIMARY_TEN_BP_PLAN_CHANGED')
    finalists = a.get('finalists', [])
    freeze_path = directory / 'FINALIST_FREEZE.json'
    if prior.sha(freeze_path) != a['finalist_freeze_sha256']:
        raise ValueError('FINALIST_FREEZE_CHANGED')
    frozen = prior.readj(freeze_path)
    evidence = frozen['selection_evidence_binding']
    evidence_path = Path(evidence['path']).resolve()
    if not evidence_path.is_relative_to(directory) or prior.sha(evidence_path) != evidence['sha256']:
        raise ValueError('SAME_RUN_SELECTION_EVIDENCE_REQUIRED')
    identity_binding = a['selection_evidence_identity_binding']
    identity_path = Path(identity_binding['path']).resolve()
    if not identity_path.is_relative_to(directory) or prior.sha(identity_path) != identity_binding['sha256']:
        raise ValueError('SAME_RUN_SELECTION_IDENTITY_REQUIRED')
    selection = prior.readj(identity_path)
    if (selection['design_freeze_sha256'] != a['design_sha256'] or selection['score_assembly_sha256'] != a['score_assembly_sha256']
        or selection['finalists'] != finalists or selection['test2026_rows_read'] != 0
        or Path(selection['source_receipt_path']).resolve() != evidence_path or selection['source_receipt_sha256'] != evidence['sha256']):
        raise ValueError('FINALISTS_SELECTION_IDENTITY_MISMATCH')
    if (frozen['finalists'] != finalists or frozen['design_sha256'] != a['design_sha256']
        or frozen['score_assembly_sha256'] != a['score_assembly_sha256'] or frozen['economic_results_accessed'] is not False):
        raise ValueError('FINALISTS_NOT_FROZEN_FROM_SELECTION_EVIDENCE')
    if len(finalists) > 3 or len(finalists) != len(set(finalists)) or not set(finalists).issubset(primary) or RAW in finalists:
        raise ValueError('FROZEN_FINALIST_IDENTITY_INVALID')
    allowed = {RAW, *finalists} if finalists else {RAW, 'ridge_stack', 'hgb_stack'}
    if any(len(ids) != len(set(ids)) or not set(ids).issubset(allowed & set(primary)) for b, ids in plan.items() if b != 10):
        raise ValueError('SENSITIVITY_PATH_BUDGET_OR_MEMBERS_CHANGED')
    conditional = a['conditional_test_paths']
    if conditional not in (0, 4) or (not finalists and conditional != 0) or sum(map(len, plan.values())) + conditional > min(60, design['budget']['max_full_account_paths']):
        raise ValueError('ALL_SCENARIO_ACCOUNT_PATH_BUDGET')
    if RAW not in primary:
        raise ValueError('RAW_COMMON_CONTROL_MUST_BE_COMPLETE')
    return a, design, ready, plan


def _coverage_bound(activation):
    if activation.get('event_coverage_status') != 'FULL_FROZEN_848_CODE_APPLIED_EVENT_COVERAGE_BOUND':
        return False
    binding = activation['event_coverage_binding']
    if prior.sha(binding['path']) != binding['sha256']:
        raise ValueError('EVENT_COVERAGE_AUTHORITY_CHANGED')
    proof = prior.readj(binding['path'])
    if proof['status'] != activation['event_coverage_status'] or proof['design_sha256'] != activation['design_sha256']:
        raise ValueError('EVENT_COVERAGE_AUTHORITY_NOT_BOUND')
    expected = activation.get('event_inputs_sha256') or activation['input_bindings']['corporate_actions']['sha256']
    if proof['event_input_sha256'] != expected:
        raise ValueError('EVENT_COVERAGE_INPUT_NOT_BOUND')
    return True


def _qualification_overlay(frame, name, coverage_bound, quote_gap_count):
    if name not in {'daily', 'positions'}:
        return frame
    frame = frame.copy()
    frame['shared_engine_accounting_qualified'] = frame.accounting_qualified
    frame['source_coverage_qualified'] = coverage_bound
    frame['accounting_qualified'] &= coverage_bound & frame.path_id.map(lambda cid: quote_gap_count[cid] == 0)
    if name == 'daily':
        for field in ('certified_nav', 'net_return'):
            frame['shared_engine_' + field] = frame[field]
            frame.loc[~frame.accounting_qualified, field] = np.nan
    return frame


def _batch_attempt(parent, identity, checkpoints):
    parent.mkdir(exist_ok=True)
    attempts = sorted(p for p in parent.iterdir() if p.is_dir())
    for folder in attempts:
        checkpoint = folder / 'CHECKPOINT.json'
        if not checkpoint.exists() or str(checkpoint) not in checkpoints:
            continue
        if prior.sha(checkpoint) != checkpoints[str(checkpoint)]:
            raise ValueError('ACCOUNT_BATCH_CHECKPOINT_CHANGED')
        receipt = prior.readj(checkpoint)
        if receipt['status'] != 'ACCOUNT_BATCH_COMPLETE' or receipt['identity'] != identity:
            raise ValueError('ACCOUNT_BATCH_IDENTITY_CHANGED')
        actual = {p.name: prior.sha(p) for p in folder.iterdir() if p.is_file() and p.name != 'CHECKPOINT.json'}
        if actual != receipt['files']:
            raise ValueError('ACCOUNT_BATCH_OUTPUT_CHANGED')
        return folder, receipt
    folder = parent / ('attempt000' if not attempts else f'repair{len(attempts):03d}')
    folder.mkdir()
    return folder, None


def run(run_directory, *, activation_path=None, event_inputs=None):
    directory = Path(run_directory).resolve()
    a, design, ready, plan = _activation(directory, Path(activation_path) if activation_path else directory / 'ACCOUNT_SOURCE_ACTIVATION.json')
    helper = membership_adapter()
    raw, raw_sha = prior.score_panel(directory, RAW)
    key = ['signal_date', 'security_uid', 'ticker', 'U_t_fingerprint']
    if len(raw) != ready['common_rows'] or raw.signal_date.nunique() != ready['common_dates'] or set(raw.signal_date.dt.year) != {2023, 2024, 2025}:
        raise ValueError('COMMON_ACCOUNT_PANEL_CHANGED')
    panels, hashes = {}, {RAW: raw_sha}
    for cid in dict.fromkeys(cid for ids in plan.values() for cid in ids):
        frame, digest = (raw, raw_sha) if cid == RAW else prior.score_panel(directory, cid)
        if not frame[key].equals(raw[key]):
            raise ValueError('COMMON_UID_POOL_CHANGED:' + cid)
        panels[cid] = frame.loc[frame['rank'].le(20), ['signal_date', 'ticker', 'rank']].assign(path_id=cid)
        hashes[cid] = digest
        if a['score_sha256'].get(cid) != digest:
            raise ValueError('SCORE_NOT_ACTIVATED:' + cid)
    calendar = pd.DatetimeIndex(sorted(raw.signal_date.unique()))
    prices = _bound_input(a, 'prices', ['ticker', 'trade_date', 'open', 'close'], 'trade_date')
    prices = prices.loc[prices.trade_date.isin(calendar)].copy()
    next_day = dict(zip(calendar[:-1], calendar[1:]))
    usable = prices.loc[np.isfinite(prices.open) & prices.open.gt(0)]
    quoted = set(zip(usable.trade_date, usable.ticker))
    quote_gap_count = {cid: sum(r.signal_date in next_day and (next_day[r.signal_date], r.ticker) not in quoted for r in panel.itertuples()) for cid, panel in panels.items()}
    if event_inputs is None:
        ca = _bound_input(a, 'corporate_actions', ['code', 'ticker', 'event_date', 'source_event_date', 'factor_a', 'factor_b', 'share_event', 'source_order'], ('event_date', 'source_event_date'))
        ca = ca.loc[ca.event_date.isin(calendar)].sort_values(['code', 'event_date', 'source_order'], kind='stable')
        events, known, unsupported = prior.source_events(ca)
        event_inputs = dict(corporate_actions=events, corporate_action_known_at=known, unsupported_events=unsupported)
    elif event_identity(event_inputs) != a['event_inputs_sha256']:
        raise ValueError('CALLER_EVENT_CATALOGUE_NOT_ACTIVATED')
    if event_inputs.get('entitlement_enabled') is True:
        receipt = a['input_bindings']['entitlement_source_receipt']
        if prior.sha(receipt['path']) != receipt['sha256'] or event_inputs['entitlement_source_binding']['source_fingerprint'] != receipt['sha256']:
            raise ValueError('ENTITLEMENT_AUTHORITY_RECEIPT_NOT_BOUND')
    coverage_bound = _coverage_bound(a)
    activation_sha = prior.sha(Path(activation_path) if activation_path else directory / 'ACCOUNT_SOURCE_ACTIVATION.json')
    out = directory / 'accounting_r2'
    out.mkdir(exist_ok=True)
    market = helper.make_market(common, prices, raw[['signal_date', 'ticker']], calendar, signal_dates=calendar)
    index_path = out / 'BATCH_COMPLETION_INDEX.json'
    index = prior.readj(index_path) if index_path.exists() else dict(activation_sha256=activation_sha, checkpoints={})
    if index['activation_sha256'] != activation_sha:
        raise ValueError('ACCOUNT_COMPLETION_INDEX_IDENTITY_CHANGED')
    failed_charge=sum(len(prior.readj(f)['identity']['path_ids']) for f in out.glob('*/ */FAILURE.json'.replace(' ','')))
    if sum(map(len,plan.values()))+failed_charge+a['conditional_test_paths']>design['budget']['max_full_account_paths']:
        raise ValueError('FAILED_ACCOUNT_ATTEMPTS_CHARGED_BUDGET_EXCEEDED')
    groups, qualification = [], {}
    for bps in (10, 0, 5, 20):
        ids = plan.get(bps, [])
        for start in range(0, len(ids), SPEC['batch_paths']):
            batch = ids[start:start + SPEC['batch_paths']]
            identity = dict(activation_sha256=activation_sha, sources=source_identity(), one_way_bps=bps, path_ids=batch,
                score_sha256={cid: hashes[cid] for cid in batch}, event_inputs_sha256=event_identity(event_inputs))
            folder, saved = _batch_attempt(out / f'bps{bps}_batch{start // SPEC["batch_paths"]:03d}', identity, index['checkpoints'])
            if saved is not None:
                qualified = {cid: bool(value and coverage_bound and quote_gap_count[cid] == 0) for cid, value in saved['accounting_qualified'].items()}
                if set(qualified) != set(batch):
                    raise ValueError('ACCOUNT_RESUME_PATHS_INCOMPLETE')
                qualification[str(bps)] = {**qualification.get(str(bps), {}), **qualified}
                groups.append(dict(one_way_bps=bps, path_ids=batch, directory=str(folder), row_counts=saved['row_counts'], resumed=True))
                print(json.dumps(dict(phase='ACCOUNT_BATCH_RESUMED', bps=bps, path_ids=batch, batch=start // SPEC['batch_paths'], attempt=folder.name)), flush=True)
                continue
            print(json.dumps(dict(phase='ACCOUNT_BATCH_STARTED', bps=bps, path_ids=batch, batch=start // SPEC['batch_paths'], attempt=folder.name)), flush=True)
            writers, counts = {}, {}
            def callback(name, frame):
                if name not in {'daily', 'positions', 'fills', 'orders', 'execution_results', 'entitlements'} or frame.empty:
                    return
                frame = _qualification_overlay(frame, name, coverage_bound, quote_gap_count)
                table = pa.Table.from_pandas(frame, preserve_index=False)
                table = table.cast(pa.schema([pa.field(f.name, pa.timestamp("ns", tz=f.type.tz), nullable=f.nullable) if pa.types.is_timestamp(f.type) else f for f in table.schema]))
                if name not in writers:
                    writers[name] = pq.ParquetWriter(folder / f'{name}.parquet', table.schema)
                writers[name].write_table(table); counts[name] = counts.get(name, 0) + len(frame)
            try:
                replay = replay_membership(market, pd.concat([panels[c] for c in batch]), batch,
                    one_way_bps=bps, event_inputs=event_inputs, ledger_callback=callback)
            except Exception as exc:
                prior.putj(folder / 'FAILURE.json', dict(status='ACCOUNT_BATCH_FAILED', identity=identity, error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc()))
                raise
            finally:
                for writer in writers.values(): writer.close()
            qualified = {cid: bool(coverage_bound and day.accounting_qualified.all() and np.isfinite(day.certified_nav).all() and quote_gap_count[cid] == 0) for cid, day in replay.daily.groupby('path_id')}
            if set(qualified) != set(batch):
                raise ValueError('ACCOUNT_BATCH_PATHS_INCOMPLETE')
            qualification[str(bps)] = {**qualification.get(str(bps), {}), **qualified}
            replay.final_state['shared_engine_accounting_qualified'] = replay.final_state['accounting_qualified'].copy()
            replay.final_state['accounting_qualified'] = np.asarray([qualified[cid] for cid in batch], dtype=bool)
            np.savez_compressed(folder / 'final_state_arrays.npz', **{k: v for k, v in replay.final_state.items() if isinstance(v, np.ndarray)}, tickers=market.tickers, path_ids=np.asarray(batch))
            prior.putj(folder / 'FINAL_STATE_TERMS.json', {k: v for k, v in replay.final_state.items() if not isinstance(v, np.ndarray)})
            if hasattr(replay, 'entitlements') and not replay.entitlements.empty and 'entitlements' not in counts:
                replay.entitlements.to_parquet(folder / 'entitlements.parquet', index=False)
                counts['entitlements'] = len(replay.entitlements)
            prior.putj(folder / 'ACCOUNT_METADATA.json', replay.metadata)
            prior.putj(folder / 'PREFIX_IDENTITY.json', replay.prefix_identity)
            replay.accounting_exceptions.to_json(folder / 'accounting_exceptions.json', orient='records', indent=2)
            checkpoint = dict(status='ACCOUNT_BATCH_COMPLETE', identity=identity, accounting_qualified=qualified, row_counts=counts,
                files={p.name: prior.sha(p) for p in folder.iterdir() if p.is_file()})
            prior.putj(folder / 'CHECKPOINT.json', checkpoint)
            index['checkpoints'][str(folder / 'CHECKPOINT.json')] = prior.sha(folder / 'CHECKPOINT.json')
            temporary_index = index_path.with_suffix('.json.tmp')
            prior.putj(temporary_index, index); temporary_index.replace(index_path)
            print(json.dumps(dict(phase='ACCOUNT_BATCH_COMPLETE', bps=bps, path_ids=batch, batch=start // SPEC['batch_paths'], attempt=folder.name)), flush=True)
            groups.append(dict(one_way_bps=bps, path_ids=batch, directory=str(folder), row_counts=counts, resumed=False))
    receipt = dict(status='RESEARCH_DIAGNOSTIC_NO_ECONOMIC_QUALIFICATION' if not all(qualification.get('10', {}).values()) else 'SOURCE_QUALIFIED_ACCOUNT_REPLAY',
        economic_promotion_allowed=False, economic_metrics=None, primary_one_way_bps=10, fee_bps=0,
        accounting_qualified=qualification, event_coverage_status=a.get('event_coverage_status', 'UNKNOWN'), event_coverage_bound=coverage_bound,
        activation_sha256=activation_sha, next_open_quote_gap_count=quote_gap_count, groups=groups, actual_account_path_count=sum(map(len, plan.values())),
        failed_attempt_path_charge=failed_charge, charged_account_path_ceiling=sum(map(len,plan.values()))+failed_charge, conditional_test_paths_reserved=a['conditional_test_paths'], design_sha256=a['design_sha256'], sources=source_identity(),
        score_sha256=hashes, event_inputs_sha256=event_identity(event_inputs), spec=SPEC,
        annual_reset=False, terminal_liquidation=False, test2026_read=False,
        availability='accepted research raw Open; hypothetical friction; real entitlement authority requires bound source terms')
    prior.putj(out / 'ACCOUNT_RECEIPT.json', receipt)
    return receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--activation')
    args = parser.parse_args()
    receipt = run(args.run, activation_path=args.activation)
    print(json.dumps(dict(status=receipt['status'], path_count=receipt['actual_account_path_count'],
        test2026_read=receipt['test2026_read'])), flush=True)
