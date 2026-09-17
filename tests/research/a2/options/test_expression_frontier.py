"""Synthetic price-frontier engineering checks, never historical evidence."""
import copy
import inspect
import json
import socket
from dataclasses import asdict

import pytest
import requests

from scripts.research.a2.options import cli, expression, frontier
from scripts.research.a2.options.contracts import Fees, Invalid


ZERO_FEES = Fees(option_per_contract=0., stock_per_share=0., minimum=0.,
                 option_slippage=0., stock_slippage=0.)
DOMAIN = dict(tick=.01, ask_min=.21, ask_max=120., bid_min=.01, bid_max=200.,
              option_spread=.2, stock_spread=.1, tolerance_usd=1e-8)
SUCCESS = {'FRONTIER', 'LOWEST_LEGAL_EXIT_SATISFIES',
           'UPPER_DOMAIN_SATISFIES', 'AFFORDABILITY_BOUNDARY'}


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Synthetic frontier tests must not request external sources')
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


@pytest.fixture
def fixed_fixture():
    # Reuse only the existing pure fixture builder, not cli.run/model_scenario.
    source = cli.synthetic_inputs()
    opportunity = next(item for item in source['opportunities'] if item.decision_id == 'good')
    contract = next(item for item in source['contracts'] if item.underlying_uid == opportunity.underlying_uid)
    quotes = [asdict(item) for item in source['quotes'] if item.underlying_uid == opportunity.underlying_uid]
    assert len(quotes) == 6
    return dict(opportunity=asdict(opportunity), contract=asdict(contract), quotes=quotes,
                no_lifecycle_events=True, zero_dividends=True, cash_interest=0.)


def scenario(**changes):
    return dict(scenario_id='INVENTED_FRONTIER', source_kind='SYNTHETIC_SCENARIO',
                stock_entry_ask=100., stock_exit_bid=105., call_entry_ask=2., call_exit_bid=8.) | changes


def solve_one(fixed_fixture, direction, control, *, fees=ZERO_FEES, domain=None, **changes):
    inputs = scenario(queries=[{'direction': direction, 'control': control}], **changes)
    result = frontier.solve_scenario(fixed_fixture, inputs, fees, dict(DOMAIN if domain is None else domain))
    assert result['scenario_id'] == inputs['scenario_id']
    assert len(result['frontiers']) == 1
    row = result['frontiers'][0]
    assert row['direction'] == direction and row['control'] == control
    assert 0 <= row['kernel_evaluations'] <= 64
    return result, row


def assert_solved_trade(row):
    assert row['status'] in SUCCESS
    assert row['root']['status'] == 'CLOSED'
    assert row['root']['contracts'] == 1
    assert row['root']['multiplier'] == 100
    assert row['root']['entry_cash'] >= 0
    assert row['root']['net_wealth'] + DOMAIN['tolerance_usd'] >= row['control_wealth']


@pytest.mark.parametrize('direction,control,price,neighbor,wealth', [
    ('required_exit_bid', 'STOCK', 7., 6.99, 10500.),
    ('required_exit_bid', 'CASH', 2., 1.99, 10000.),
    ('max_entry_ask', 'STOCK', 3., 3.01, 10500.),
    ('max_entry_ask', 'CASH', 8., 8.01, 10000.),
])
def test_zero_fee_hand_oracles_and_adjacent_tick(fixed_fixture, direction, control, price, neighbor, wealth):
    result, row = solve_one(fixed_fixture, direction, control)
    assert result['status'] == 'COMPLETE' and result['stock_quantity'] == 100
    assert row['status'] == 'FRONTIER'
    assert row['price'] == pytest.approx(price)
    assert row['neighbor_price'] == pytest.approx(neighbor)
    assert row['control_wealth'] == pytest.approx(wealth)
    assert row['root']['net_wealth'] == pytest.approx(wealth)
    assert row['neighbor']['net_wealth'] == pytest.approx(wealth - 1.)
    assert row['neighbor']['status'] == 'CLOSED'
    assert_solved_trade(row)
    if direction == 'required_exit_bid':
        assert row['root']['entry_quote_ask'] == 2.
        assert row['root']['exit_quote_bid'] == pytest.approx(price)
        assert row['root']['entry_cash'] == pytest.approx(9800.)
    else:
        assert row['root']['entry_quote_ask'] == pytest.approx(price)
        assert row['root']['exit_quote_bid'] == 8.
        assert row['root']['entry_cash'] == pytest.approx(10000. - 100. * price)


@pytest.mark.parametrize('per_contract,minimum,expected', [(.65, 1., 2.02), (1.01, 1., 2.03)])
def test_existing_minimum_fee_branch_changes_the_grid_threshold(fixed_fixture, per_contract, minimum, expected):
    # Fees currently has per-unit charges and a minimum, not an ad-valorem fee.
    fees = Fees(option_per_contract=per_contract, stock_per_share=0., minimum=minimum)
    _, row = solve_one(fixed_fixture, 'required_exit_bid', 'CASH', fees=fees)
    assert row['price'] == pytest.approx(expected)
    assert row['neighbor_price'] == pytest.approx(expected - .01)
    assert_solved_trade(row)
    assert row['neighbor']['net_wealth'] + DOMAIN['tolerance_usd'] < row['control_wealth']


def test_slippage_separates_input_quote_from_actual_fill_without_double_spread(fixed_fixture):
    _, row = solve_one(fixed_fixture, 'required_exit_bid', 'CASH',
                       fees=Fees(option_slippage=.1))
    assert row['price'] == pytest.approx(2.22)
    root = row['root']
    assert root['entry_quote_ask'] == 2. and root['exit_quote_bid'] == pytest.approx(2.22)
    assert root['entry_fill_price'] == pytest.approx(2.1)
    assert root['exit_fill_price'] == pytest.approx(2.12)
    assert root['entry_cash'] == pytest.approx(9789.)
    assert root['net_wealth'] == pytest.approx(10000.)
    assert row['neighbor']['net_wealth'] == pytest.approx(9999.)
    assert_solved_trade(row)


def test_affordability_boundary_requires_a_real_one_contract_entry(fixed_fixture):
    _, row = solve_one(fixed_fixture, 'max_entry_ask', 'CASH', call_exit_bid=200.)
    assert row['status'] == 'AFFORDABILITY_BOUNDARY'
    assert row['price'] == pytest.approx(100.)
    assert row['root']['entry_cash'] == pytest.approx(0.)
    assert_solved_trade(row)
    assert row['neighbor_price'] == pytest.approx(100.01)
    assert row['neighbor']['status'] != 'CLOSED'
    assert 'BUDGET' in row['neighbor']['reason']


def test_over_budget_cash_branch_cannot_satisfy_a_call_frontier(fixed_fixture):
    result, row = solve_one(fixed_fixture, 'required_exit_bid', 'CASH', call_entry_ask=101.)
    assert result['status'] == 'PARTIAL_OR_REJECTED'
    assert row['status'] == 'UNSUPPORTED'
    assert row.get('reason')
    assert row.get('price') is None
    assert not row.get('root') or row['root']['status'] != 'CLOSED'


@pytest.mark.parametrize('direction,domain', [
    ('required_exit_bid', DOMAIN | {'bid_max': 1.99}),
    ('max_entry_ask', DOMAIN | {'ask_min': 8.01}),
])
def test_no_solution_is_limited_to_the_given_search_domain(fixed_fixture, direction, domain):
    _, row = solve_one(fixed_fixture, direction, 'CASH', domain=domain)
    assert row['status'] == 'NO_SOLUTION_IN_DOMAIN'
    assert row.get('price') is None


def test_lowest_legal_exit_already_satisfies_the_fixed_stock_scenario(fixed_fixture):
    _, row = solve_one(fixed_fixture, 'required_exit_bid', 'STOCK', stock_exit_bid=90.)
    assert row['status'] == 'LOWEST_LEGAL_EXIT_SATISFIES'
    assert row['price'] == DOMAIN['bid_min']
    assert row.get('neighbor_price') is None
    assert_solved_trade(row)


def test_upper_search_bound_can_satisfy_without_claiming_global_maximum(fixed_fixture):
    _, row = solve_one(fixed_fixture, 'max_entry_ask', 'STOCK', domain=DOMAIN | {'ask_max': 2.5})
    assert row['status'] == 'UPPER_DOMAIN_SATISFIES'
    assert row['price'] == 2.5
    assert_solved_trade(row)


@pytest.mark.parametrize('direction,changes', [
    ('required_exit_bid', {'call_entry_ask': None}),
    ('required_exit_bid', {'call_entry_ask': 0.}),
    ('required_exit_bid', {'call_entry_ask': float('nan')}),
    ('required_exit_bid', {'call_entry_ask': float('inf')}),
    ('max_entry_ask', {'call_exit_bid': None}),
    ('max_entry_ask', {'call_exit_bid': 0.}),
    ('max_entry_ask', {'call_exit_bid': -1.}),
    ('max_entry_ask', {'call_exit_bid': float('-inf')}),
    ('required_exit_bid', {'omit_exit_quote': True}),
])
def test_invalid_and_unresolved_quotes_are_not_zero_return_solutions(fixed_fixture, direction, changes):
    inputs = scenario(queries=[{'direction': direction, 'control': 'CASH'}], **changes)
    result = frontier.solve_scenario(fixed_fixture, inputs, ZERO_FEES, copy.deepcopy(DOMAIN))
    assert result['status'] == 'PARTIAL_OR_REJECTED'
    # Rejection before the search exists can live at scenario level. A path
    # rejected during a valid query must retain its own UNSUPPORTED result.
    if not result['frontiers']:
        assert result.get('reason')
    for row in result['frontiers']:
        assert row['status'] == 'UNSUPPORTED' and row.get('reason')
        assert row.get('price') is None


def test_missing_delta_does_not_prevent_same_funds_frontiers(fixed_fixture):
    for quote in fixed_fixture['quotes']:
        for name in ('delta', 'delta_at', 'delta_source', 'delta_kind', 'delta_unit', 'delta_style'):
            quote[name] = None
    _, row = solve_one(fixed_fixture, 'required_exit_bid', 'STOCK')
    assert row['price'] == pytest.approx(7.)
    assert_solved_trade(row)


def test_replays_use_original_kernel_and_keep_identity_quantity_clocks_fixed(fixed_fixture, monkeypatch):
    original = expression.replay_arm
    signature = inspect.signature(original)
    calls = []
    def record_replay(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append(bound.arguments.copy())
        return original(*args, **kwargs)
    monkeypatch.setattr(expression, 'replay_arm', record_replay)
    monkeypatch.setattr(frontier, 'replay_arm', record_replay, raising=False)
    inputs = scenario()
    before = copy.deepcopy((fixed_fixture, inputs, DOMAIN))
    result = frontier.solve_scenario(fixed_fixture, inputs, ZERO_FEES, copy.deepcopy(DOMAIN))
    assert result['status'] == 'COMPLETE' and calls
    assert (fixed_fixture, inputs, DOMAIN) == before
    assert result['scenario_eval_calls'] >= 0
    assert all(0 < row['kernel_evaluations'] <= 64 for row in result['frontiers'])
    # evaluate establishes controls and also visits its zero-quantity arms;
    # the solver counter describes its direct one-contract kernel calls.
    option_calls = [call for call in calls if call['option'] and call['quantity'] > 0]
    assert result['scenario_replay_calls'] == len(option_calls)
    assert len(option_calls) == sum(row['kernel_evaluations'] for row in result['frontiers'])
    stock_calls = [call for call in calls if call['arm'] == 'STOCK']
    assert option_calls and stock_calls
    offset = 0
    for row in result['frontiers']:
        count = row['kernel_evaluations']
        points = []
        for call in option_calls[offset:offset + count]:
            quotes = sorted((quote for quote in call['quotes']
                             if quote.instrument_id == fixed_fixture['contract']['contract_id']),
                            key=lambda quote: quote.event_at)
            points.append((quotes[0].ask, quotes[-1].bid))
        assert len(points) == len(set(points))  # Root/neighbor reverification uses cached probes.
        offset += count
    quote_clocks = {(quote['instrument_id'], quote['event_at'], quote['available_at']) for quote in fixed_fixture['quotes']}
    for call in option_calls:
        assert call['instrument'] == fixed_fixture['contract']['contract_id']
        assert call['quantity'] == 1
        assert asdict(call['o']) == fixed_fixture['opportunity'] | {'decision_id': inputs['scenario_id']}
        assert {(quote.instrument_id, quote.event_at, quote.available_at) for quote in call['quotes']} == quote_clocks
    assert {call['quantity'] for call in stock_calls} == {100}
    stock_prices = [{(quote.event_at, quote.bid, quote.ask) for quote in call['quotes']
                     if quote.instrument_id == fixed_fixture['opportunity']['underlying_uid']}
                    for call in calls]
    assert all(prices == stock_prices[0] for prices in stock_prices)


def test_repeated_same_scenario_is_deterministic_and_stock_change_does_not_mutate_input(fixed_fixture):
    inputs, domain = scenario(), copy.deepcopy(DOMAIN)
    before = copy.deepcopy((fixed_fixture, inputs, domain))
    first = frontier.solve_scenario(fixed_fixture, inputs, ZERO_FEES, domain)
    second = frontier.solve_scenario(fixed_fixture, inputs, ZERO_FEES, domain)
    assert first == second
    changed = frontier.solve_scenario(fixed_fixture, inputs | {'stock_exit_bid': 110.}, ZERO_FEES, domain)
    stock = lambda result: next(row for row in result['frontiers']
        if row['direction'] == 'required_exit_bid' and row['control'] == 'STOCK')
    cash = lambda result: next(row for row in result['frontiers']
        if row['direction'] == 'required_exit_bid' and row['control'] == 'CASH')
    assert stock(first)['price'] == pytest.approx(7.) and stock(changed)['price'] == pytest.approx(12.)
    assert cash(first)['price'] == cash(changed)['price']
    assert (fixed_fixture, inputs, domain) == before


def test_real_history_label_is_rejected_by_pure_synthetic_interface(fixed_fixture):
    result = frontier.solve_scenario(fixed_fixture, scenario(source_kind='REAL_HISTORICAL_QUOTES'),
                                     ZERO_FEES, copy.deepcopy(DOMAIN))
    assert result['status'] == 'PARTIAL_OR_REJECTED'
    assert result.get('reason') or all(row['status'] == 'UNSUPPORTED' and row.get('reason')
                                      for row in result['frontiers'])


def test_cli_routes_scenario_file_output_and_offline_to_the_frontier_module(tmp_path, monkeypatch, capsys):
    source, output = tmp_path / 'invented-scenarios.json', tmp_path / 'invented-output'
    calls = []
    def run_frontier(scenario_file, output_path, *, offline=False):
        calls.append((scenario_file, output_path, offline))
        return {'run_identity': 'MOCK_ROUTE_ONLY', 'status': 'COMPLETE', 'source_kind': 'SYNTHETIC_SCENARIO',
                'scenario_eval_calls': 0, 'scenario_replay_calls': 0, 'real_historical_eval_calls': 0, 'execution_network_requests': 0}
    def forbidden(*args, **kwargs):
        pytest.fail('Expression-frontier CLI must not enter the old all/economic-data task')
    monkeypatch.setattr(frontier, 'run_frontier', run_frontier)
    monkeypatch.setattr(cli, 'run', forbidden)
    monkeypatch.setattr(cli, 'run_historical_quotes', forbidden)
    code = cli.main(['--mode', 'expression-frontier', '--scenario-file', str(source),
                     '--output', str(output), '--offline'])
    assert code == 0 and calls == [(source, output, True)]
    assert json.loads(capsys.readouterr().out)['source_kind'] == 'SYNTHETIC_SCENARIO'
    assert not source.exists() and not output.exists()


def test_actual_file_runner_consumes_scenarios_and_keeps_rejections_across_zero_network_rerun(fixed_fixture, tmp_path):
    # The parent invokes pytest with an authorized external --basetemp; do not
    # bypass run_frontier's real results/cache-root check in this test.
    source = tmp_path / 'invented-file-input.json'
    valid = scenario(scenario_id='FILE_VALID', stock_exit_bid=110., fee_profile='ZERO',
                     queries=[{'direction': 'required_exit_bid', 'control': 'STOCK'}])
    invalid = scenario(scenario_id='FILE_MISSING_EXIT', omit_exit_quote=True, fee_profile='ZERO',
                       queries=[{'direction': 'required_exit_bid', 'control': 'CASH'}])
    payload = dict(source_kind='SYNTHETIC_SCENARIO', fixture=fixed_fixture, domain=DOMAIN,
                   fee_profiles={'ZERO': asdict(ZERO_FEES)}, scenarios=[valid, invalid])
    source.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
    first_output, second_output = tmp_path / 'first-new-run', tmp_path / 'second-new-run'
    first = frontier.run_frontier(source, first_output, offline=True)
    second = frontier.run_frontier(source, second_output, offline=True)
    rows = json.loads((first_output / 'scenario_results.json').read_text(encoding='utf-8'))
    assert [row['scenario_id'] for row in rows] == ['FILE_VALID', 'FILE_MISSING_EXIT']
    assert rows[0]['frontiers'][0]['price'] == pytest.approx(12.)
    assert rows[1]['frontiers'][0]['status'] == 'UNSUPPORTED'
    assert rows[1]['frontiers'][0]['reason']
    assert first['result_content_sha256'] == second['result_content_sha256']
    assert (first_output / 'scenario_results.json').read_bytes() == (second_output / 'scenario_results.json').read_bytes()
    for output, manifest in ((first_output, first), (second_output, second)):
        assert (output / 'frontier_results.csv').is_file()
        stored = json.loads((output / 'run_manifest.json').read_text(encoding='utf-8'))
        assert stored == manifest
        assert manifest['source_kind'] == 'SYNTHETIC_SCENARIO'
        assert manifest['execution_network_requests'] == manifest['market_data_reads'] == 0
        assert manifest['real_historical_eval_calls'] == manifest['real_historical_pairs'] == 0
        assert manifest['scenario_eval_calls'] > 0 and manifest['scenario_replay_calls'] > 0
        assert manifest['code_and_contract_sha256'] and manifest['fee_profiles'] == payload['fee_profiles']
    before = {path.name: path.read_bytes() for path in first_output.iterdir() if path.is_file()}
    with pytest.raises(Invalid, match='OUTPUT_EXISTS_PRESERVE_PRIOR_RUN'):
        frontier.run_frontier(source, first_output, offline=True)
    assert before == {path.name: path.read_bytes() for path in first_output.iterdir() if path.is_file()}


def test_file_runner_rejects_real_history_claim_before_creating_run(fixed_fixture, tmp_path):
    source, output = tmp_path / 'invented-unbound-input.json', tmp_path / 'rejected-run'
    source.write_text(json.dumps({'source_kind': 'REAL_HISTORICAL_QUOTES', 'fixture': fixed_fixture}), encoding='utf-8')
    with pytest.raises(Invalid, match='SYNTHETIC_SCENARIO_ONLY'):
        frontier.run_frontier(source, output, offline=True)
    assert not output.exists()


@pytest.mark.parametrize('change', ['exit_2026', 'multiplier', 'non_synthetic_quote'])
def test_fixed_fixture_cutoff_identity_and_source_rejected_before_economic_call(fixed_fixture, change):
    if change == 'exit_2026':
        fixed_fixture['quotes'][-1]['event_at'] = '2026-01-02T14:45:01Z'
        fixed_fixture['quotes'][-1]['available_at'] = '2026-01-02T14:45:01Z'
    elif change == 'multiplier':
        fixed_fixture['contract']['multiplier'] = 10
    else:
        fixed_fixture['quotes'][0]['evidence_grade'] = 'REAL_HISTORICAL_QUOTES'
    result = frontier.solve_scenario(fixed_fixture, scenario(), ZERO_FEES, DOMAIN)
    assert result['status'] == 'PARTIAL_OR_REJECTED' and result.get('reason')
    assert result['scenario_eval_calls'] == result['scenario_replay_calls'] == 0


def test_unproved_fee_extension_is_not_searched(fixed_fixture):
    class OtherFee(Fees):
        pass
    result = frontier.solve_scenario(fixed_fixture, scenario(), OtherFee(), DOMAIN)
    assert result['status'] == 'PARTIAL_OR_REJECTED'
    assert result['reason'] == 'UNSUPPORTED_FEE_MODEL'
    assert result['scenario_eval_calls'] == result['scenario_replay_calls'] == 0
