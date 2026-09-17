"""Price frontiers sharing the fixed R1 cash arithmetic and one tick search.

For the exact Fees class, order fees depend on quantity, not quote price.
With fixed one-contract fills, CLOSED wealth has slopes +100 in exit bid and
-100 in entry ask. Budget/exit-financing exclusions form a prefix/suffix of
the domain; other unresolved paths are unsupported, never cash successes.
The engine uses float USD (no cent rounding), with cash tolerance <1e-8.
Only the search grid uses integer cents. Observed quote inputs stay unrounded.
The synthetic wrapper retains its execution-shaped fixture; the pure amount
path conveys no identity, clock, liquidity or execution qualification.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

from . import expression
from .contracts import (Contract, Fees, Invalid, Opportunity, Quote, TEMPLATE,
                        clock, finite, require, ts, validate_opportunity, validate_quote)


def _tick(value):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), "PRICE_REQUIRED")
    number = Decimal(str(value)) * 100
    require(number.is_finite() and number == number.to_integral_value(), "INVALID_CENT_PRICE")
    return int(number)


def _fixture(data):
    require(data.get("no_lifecycle_events") is True and data.get("zero_dividends") is True
            and data.get("cash_interest") == 0, "UNSUPPORTED_LIFECYCLE_OR_CASH_RULE")
    o, c = Opportunity(**data["opportunity"]), Contract(**data["contract"])
    quotes = tuple(Quote(**q) for q in data["quotes"])
    require(o.evidence_grade == "SYNTHETIC" and o.underlying_uid.startswith("SYNTHETIC:")
            and o.source_id.startswith("SYNTHETIC") and c.source == "SYNTHETIC"
            and c.contract_id.startswith("SYNTHETIC:") and o.capital == 10000, "SYNTHETIC_FIXED_CAPITAL_ONLY")
    validate_opportunity(o)
    require(expression.select_contract(o, (c,)) == c, "FIXED_CONTRACT_NOT_ELIGIBLE")
    decision = ts(o.decision_at)
    exit_at = clock(str(decision.tz_convert("America/New_York").date()), 5)
    from datetime import timedelta
    expected = {(instrument, at) for instrument in (o.underlying_uid, c.contract_id)
                for at in (decision, decision + timedelta(seconds=1), exit_at + timedelta(seconds=1))}
    require(len(quotes) == 6 and {(q.instrument_id, ts(q.event_at)) for q in quotes} == expected,
            "FIXTURE_CLOCK_OR_QUOTE_SET")
    for q in quotes:
        validate_quote(q, o.underlying_uid, q.instrument_id,
                       option=q.instrument_id == c.contract_id, grade="SYNTHETIC")
        require(q.source == q.feed_kind == "SYNTHETIC", "SYNTHETIC_QUOTES_ONLY")
    return o, c, quotes, exit_at


def conditional_cash_point(entry_ask, exit_bid, fees: Fees, *, capital=10000.,
                           quantity=1, multiplier=100) -> dict:
    """Conditional standard-Call amounts, without manufacturing Quote fields.

    Source/identity, no-deliverable-change and snapshot comparability evidence
    belong to the caller. This function grants none of those qualifications.
    """
    point = {"status": "NOT_OPENED", "reason": "UNKNOWN", "net_wealth": None,
             "cash": capital, "position_quantity": 0., "entry_quote_ask": entry_ask,
             "exit_quote_bid": exit_bid, "entry_fill_price": None, "exit_fill_price": None,
             "entry_cash": None, "entry_fee": 0., "exit_fee": 0.,
             "contracts": None, "multiplier": multiplier}
    try:
        require(type(fees) is Fees, "UNSUPPORTED_FEE_MODEL")
        require(finite(capital, positive=True) and capital == 10000 and
                type(quantity) is int and quantity == 1 and type(multiplier) is int and multiplier == 100,
                "FIXED_ONE_CALL_CAPITAL_REQUIRED")
        require(finite(entry_ask, positive=True),
                "MISSING_ENTRY_ASK" if entry_ask is None else "INVALID_ENTRY_ASK")
        entry = expression.settle_cash_order(capital, quantity, entry_ask,
                                             option=True, fees=fees, side="BUY")
        if entry["reason"] != "OK":
            point["reason"] = entry["reason"]
            return point
        point.update(status="UNRESOLVED", cash=entry["cash_after"], position_quantity=quantity,
                     entry_fill_price=entry["fill_price"], entry_cash=entry["cash_after"],
                     entry_fee=entry["fee"], contracts=quantity)
        if exit_bid is None or not finite(exit_bid) or exit_bid == 0:
            point["reason"] = ("MISSING_EXIT_BID" if exit_bid is None else
                               "INVALID_EXIT_BID" if not finite(exit_bid) else "ZERO_BID_OUTSIDE_AMOUNT_DOMAIN")
            return point
        closing = expression.settle_cash_order(entry["cash_after"], quantity, exit_bid,
                                               option=True, fees=fees, side="SELL")
        if closing["reason"] != "OK":
            point["reason"] = closing["reason"]
            return point
        require(finite(closing["cash_after"]), "NONFINITE_KERNEL_WEALTH")
        point.update(status="CLOSED", reason="CONDITIONAL_CASH_AMOUNT", cash=closing["cash_after"],
                     net_wealth=closing["cash_after"], position_quantity=0.,
                     exit_fill_price=closing["fill_price"], exit_fee=closing["fee"])
    except (Invalid, ValueError, TypeError) as exc:
        point["reason"] = str(exc)
    return point


def solve_price_frontier(probe, *, direction: str, lower_tick: int, upper_tick: int,
                         control_wealth: float, tolerance_usd: float = 1e-8) -> dict:
    """Original bounded integer-cent inversion of a qualified monotone kernel.

    The callback returns the existing point schema and is called at most once
    per tick. Its caller fixes the instrument, amount model and observations.
    """
    record = {"direction": direction, "status": "UNSUPPORTED", "price": None,
              "neighbor_price": None, "root": None, "neighbor": None, "kernel_evaluations": 0}
    cache = {}
    try:
        require(direction in {"required_exit_bid", "max_entry_ask"}, "INVALID_QUERY")
        require(finite(control_wealth), "UNKNOWN_CONTROL_WEALTH")
        require(finite(tolerance_usd) and tolerance_usd <= 1e-8, "UNSUPPORTED_GRID_OR_TOLERANCE")
        lo, hi = lower_tick, upper_tick
        require(type(lo) is int and type(hi) is int and 0 < lo <= hi and
                (hi-lo).bit_length() + 4 <= 64 and hi <= 100_000_000,
                "INVALID_OR_EXCESSIVE_SEARCH_DOMAIN")
        exiting = direction == "required_exit_bid"
        record.update(control_wealth=control_wealth, search_lower=lo/100, search_upper=hi/100, tick=.01)

        def passes(tick):
            if tick not in cache:
                require(len(cache) < 64, "KERNEL_EVALUATION_LIMIT")
                record["kernel_evaluations"] = len(cache) + 1
                cache[tick] = probe(tick)
                record["kernel_evaluations"] = len(cache)
            point = cache[tick]
            if point["status"] != "CLOSED":
                allowed = {"EXIT_FINANCING_REQUIRED"} | ({"FILL_OVER_BUDGET"} if not exiting else set())
                if point["reason"] not in allowed:
                    record["failure_point"] = point
                    raise Invalid(point["reason"])
                return False
            require(finite(point["net_wealth"]), "NONFINITE_KERNEL_WEALTH")
            return point["net_wealth"] + tolerance_usd >= control_wealth

        if not passes(hi if exiting else lo):
            boundary = cache[hi if exiting else lo]
            record.update(status="NO_SOLUTION_IN_DOMAIN" if boundary["status"] == "CLOSED" else "UNSUPPORTED",
                          reason="BEST_BOUND_DOES_NOT_MEET_TARGET" if boundary["status"] == "CLOSED" else boundary["reason"],
                          boundary=boundary)
            return record
        left, right = lo, hi
        while left < right:
            middle = (left+right+(0 if exiting else 1))//2
            passed = passes(middle)
            if exiting:
                if passed: right = middle
                else: left = middle+1
            elif passed: left = middle
            else: right = middle-1
        neighbor = left-1 if exiting else left+1
        require(passes(left), "ROOT_VERIFICATION_FAILED")
        adjacent = lo <= neighbor <= hi
        require(not adjacent or not passes(neighbor), "NEIGHBOR_VERIFICATION_FAILED")
        status = "FRONTIER"
        if exiting and left == lo: status = "LOWEST_LEGAL_EXIT_SATISFIES"
        if not exiting and left == hi: status = "UPPER_DOMAIN_SATISFIES"
        if not exiting and adjacent and cache[neighbor]["reason"] == "FILL_OVER_BUDGET": status = "AFFORDABILITY_BOUNDARY"
        record.update(status=status, price=left/100, neighbor_price=neighbor/100 if adjacent else None,
                      root=cache[left], neighbor=cache.get(neighbor), reason="VERIFIED_ROOT_AND_ADJACENT_TICK")
    except (Invalid, ValueError, TypeError, KeyError) as exc:
        record["reason"] = str(exc)
    return record


def solve_scenario(fixture: dict, scenario: dict, fees: Fees, domain: dict) -> dict:
    """Fix controls once with evaluate; invert only fixed-contract replay_arm."""
    result = {"scenario_id": scenario.get("scenario_id"), "status": "PARTIAL_OR_REJECTED",
              "frontiers": [], "scenario_eval_calls": 0, "scenario_replay_calls": 0}
    try:
        require(scenario.get("source_kind") == "SYNTHETIC_SCENARIO", "SYNTHETIC_SCENARIO_ONLY")
        require(type(fees) is Fees, "UNSUPPORTED_FEE_MODEL")
        fees.order(1, True)
        require(domain["tick"] == .01 and 0 <= domain["tolerance_usd"] <= 1e-8,
                "UNSUPPORTED_GRID_OR_TOLERANCE")
        tolerance = domain["tolerance_usd"]
        spread, stock_spread = _tick(domain["option_spread"]), _tick(domain["stock_spread"])
        require(spread >= 0 and stock_spread >= 0, "NEGATIVE_SPREAD")
        bounds = {name: (_tick(domain[name + "_min"]), _tick(domain[name + "_max"]))
                  for name in ("ask", "bid")}
        for lo, hi in bounds.values():
            require(0 < lo <= hi and (hi-lo).bit_length() + 4 <= 64
                    and hi <= 100_000_000, "INVALID_OR_EXCESSIVE_SEARCH_DOMAIN")
        require(bounds["ask"][0] > spread, "ENTRY_BID_NOT_POSITIVE")
        stock_entry, stock_exit = _tick(scenario["stock_entry_ask"]), _tick(scenario["stock_exit_bid"])
        require(stock_entry > stock_spread and stock_exit > 0, "INVALID_STOCK_PRICE")
        ask, bid = _tick(scenario["call_entry_ask"]), _tick(scenario["call_exit_bid"])
        require(ask > spread and bid > 0, "INVALID_OPTION_PRICE")
        o, c, base_quotes, exit_at = _fixture(fixture)
        require(o.spot == stock_entry / 100, "FIXED_SPOT_REFERENCE_CHANGED")
        o = replace(o, decision_id=scenario["scenario_id"])

        def quotes_at(a, b):
            quotes = []
            for q in base_quotes:
                exiting = ts(q.event_at) > exit_at
                option = q.instrument_id == c.contract_id
                if option and exiting and scenario.get("omit_exit_quote", False):
                    continue
                price = (b if exiting else a) if option else (stock_exit if exiting else stock_entry)
                width = spread if option else stock_spread
                buy, sell = (price+width, price) if exiting else (price, price-width)
                quotes.append(replace(q, ask=buy/100, bid=sell/100,
                    underlying_price=(stock_exit if exiting else stock_entry)/100,
                    delta=None, delta_at=None, delta_source=None, delta_kind=None,
                    delta_unit=None, delta_style=None, iv=None))
            return tuple(quotes)

        # No Call prices enter the control calculation. Stock sizing and cash
        # are the unchanged evaluate implementation, outside both root searches.
        controls = expression.evaluate((o,), (c,), tuple(q for q in quotes_at(ask, bid)
                                       if q.instrument_id == o.underlying_uid),
                                       fees=fees, evaluated_at="2025-12-31T23:00:00Z")
        result["scenario_eval_calls"] = 1
        control_rows = {r["arm"]: r for r in controls["outcomes"]}
        stock_buys = [r for r in controls["ledger"] if r["arm"] == "STOCK" and r["side"] == "BUY"]
        result["stock_quantity"] = stock_buys[0]["shares"] if stock_buys else 0
        result["controls"] = {name: control_rows[name] for name in ("STOCK", "CASH")}
        result["fixed_contract"] = asdict(c)
        queries = scenario.get("queries", [{"direction": d, "control": name}
            for d in ("required_exit_bid", "max_entry_ask") for name in ("STOCK", "CASH")])
        require(0 < len(queries) <= 4 and len({(q["direction"], q["control"]) for q in queries}) == len(queries),
                "INVALID_QUERY_SET")
        for query in queries:
            direction, name = query["direction"], query["control"]
            record = {**query, "status": "UNSUPPORTED", "price": None, "neighbor_price": None,
                      "root": None, "neighbor": None, "kernel_evaluations": 0}
            result["frontiers"].append(record)
            try:
                require(direction in {"required_exit_bid", "max_entry_ask"} and name in {"STOCK", "CASH"}, "INVALID_QUERY")
                control = control_rows[name]
                require(name == "CASH" or control["status"] == "CLOSED", "STOCK_CONTROL_NOT_CLOSED")
                target = control["net_wealth"]
                require(finite(target), "UNKNOWN_CONTROL_WEALTH")
                record["control_wealth"] = target
                exiting = direction == "required_exit_bid"
                lo, hi = bounds["bid" if exiting else "ask"]
                if exiting:
                    # Original sell fill cannot be below zero after slippage.
                    from decimal import ROUND_CEILING
                    lo = max(lo, int((Decimal(str(fees.option_slippage))*100).to_integral_value(rounding=ROUND_CEILING)))
                    require(bounds["ask"][0] <= ask <= bounds["ask"][1], "FIXED_ASK_OUTSIDE_DOMAIN")
                else:
                    require(bounds["bid"][0] <= bid <= bounds["bid"][1], "FIXED_BID_OUTSIDE_DOMAIN")
                require(lo <= hi, "NO_LEGAL_PRICE_IN_DOMAIN")
                record.update(search_lower=lo/100, search_upper=hi/100, tick=.01)

                def replay_point(tick):
                    a, b = (ask, tick) if exiting else (tick, bid)
                    result["scenario_replay_calls"] += 1
                    row, ledger = expression.replay_arm(o, c.contract_id, 1, quotes_at(a, b),
                        option=True, fees=fees, arm="LONG_CALL", evaluated_at="2025-12-31T23:00:00Z")
                    buys = [r for r in ledger if r["side"] == "BUY"]
                    sells = [r for r in ledger if r["side"] == "SELL"]
                    closed = row["status"] == "CLOSED"
                    if closed:
                        require(len(buys) == len(sells) == 1 and all(r["contracts"] == 1
                            and r["multiplier"] == 100 and r["instrument_id"] == c.contract_id for r in ledger), "FIXED_ONE_CALL_REQUIRED")
                    return {"status": row["status"], "reason": row["reason"],
                        "net_wealth": row["net_wealth"] if closed else None,
                        "cash": row["cash"], "position_quantity": row["quantity"],
                        "entry_quote_ask": a/100, "exit_quote_bid": b/100,
                        "entry_fill_price": buys[0]["price"] if buys else None,
                        "exit_fill_price": sells[0]["price"] if sells else None,
                        "entry_cash": buys[0]["post_trade_cash"] if buys else None,
                        "entry_fee": row["entry_fee"], "exit_fee": row["exit_fee"],
                        "contracts": buys[0]["contracts"] if buys else None, "multiplier": c.multiplier,
                        "instrument_id": c.contract_id, "entry_at": row["entry_at"], "exit_at": row["exit_at"]}

                record.update(solve_price_frontier(replay_point, direction=direction,
                    lower_tick=lo, upper_tick=hi, control_wealth=target, tolerance_usd=tolerance))
            except (Invalid, ValueError, TypeError, KeyError) as exc:
                record["reason"] = str(exc)
        if all(r["status"] != "UNSUPPORTED" for r in result["frontiers"]):
            result["status"] = "COMPLETE"
    except (Invalid, ValueError, TypeError, KeyError) as exc:
        result["reason"] = str(exc)
    return result


def run_frontier(scenario_file: Path, output: Path, *, offline=False) -> dict:
    """Explicit CLI mode only. Does not import provider or model task modules."""
    from scripts.common.storage_paths import resolve
    from .cli import _canonical, _write_csv
    from .historical_quotes import _write_json
    require(scenario_file is not None and output is not None, "SCENARIO_FILE_AND_OUTPUT_REQUIRED")
    paths, output = resolve(), output.resolve()
    require(paths.results_root in output.parents or paths.cache_root in output.parents, "OUTPUT_ROOT_NOT_AUTHORIZED")
    require(not output.exists(), "OUTPUT_EXISTS_PRESERVE_PRIOR_RUN")
    raw = scenario_file.read_bytes()
    require(len(raw) <= 1024**2, "SCENARIO_FILE_TOO_LARGE")
    data = json.loads(raw)
    require(data.get("source_kind") == "SYNTHETIC_SCENARIO", "SYNTHETIC_SCENARIO_ONLY")
    require(0 < len(data["scenarios"]) <= 32, "SCENARIO_LIMIT")
    ids = [s["scenario_id"] for s in data["scenarios"]]
    require(len(set(ids)) == len(ids), "DUPLICATE_SCENARIO")
    output.mkdir(parents=True)
    sources = [Path(__file__), Path(expression.__file__), paths.repo_root / "scripts/research/a2/options/contracts.py",
               paths.repo_root / "scripts/research/a2/options/cli.py", paths.repo_root / "scripts/v22/r9a_trade_ledger.py"]
    identity = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest = {"task_id": "OPTIONS_EXPRESSION_PRICE_FRONTIER_R1", "related_research": TEMPLATE,
        "mode": "expression-frontier", "source_kind": data["source_kind"], "status": "RUNNING",
        "input_sha256": hashlib.sha256(raw).hexdigest(), "code_and_contract_sha256": identity,
        "fee_profiles": data["fee_profiles"], "domain": data["domain"], "offline": offline,
        "execution_network_requests": 0, "market_data_reads": 0, "real_historical_eval_calls": 0,
        "real_historical_pairs": 0, "new_scientific_candidates": 0, "historical_daily_candidates": 1,
        "new_model_fits": 0, "new_calibration_runs": 0, "new_parameter_search": 0,
        "commercial_spend": 0, "trades": 0, "kernel": str(Path(expression.__file__).resolve())+"::replay_arm"}
    manifest["run_identity"] = hashlib.sha256(_canonical({"input": manifest["input_sha256"], "code": identity})).hexdigest()
    _write_json(output / "run_manifest.json", manifest)
    results = [solve_scenario(data["fixture"], s, Fees(**data["fee_profiles"][s["fee_profile"]]), data["domain"] | s.get("domain", {}))
               for s in data["scenarios"]]
    rows = []
    for result in results:
        for frontier in result["frontiers"] or [{"status": "UNSUPPORTED", "reason": result.get("reason")}]:
            row = {"scenario_id": result["scenario_id"], "stock_quantity": result.get("stock_quantity")}
            row.update({k: v for k, v in frontier.items() if not isinstance(v, dict)})
            for role in ("root", "neighbor", "failure_point", "boundary"):
                row.update({role+"_"+k: v for k, v in (frontier.get(role) or {}).items()})
            rows.append(row)
    _write_json(output / "scenario_results.json", results)
    _write_csv(output / "frontier_results.csv", rows)
    manifest.update(status="COMPLETE_SYNTHETIC_ENGINEERING", scenario_eval_calls=sum(r["scenario_eval_calls"] for r in results),
        scenario_replay_calls=sum(r["scenario_replay_calls"] for r in results),
        unsupported=sum(r["status"] == "UNSUPPORTED" for r in rows), economic_verdict="HISTORICAL_NOT_IDENTIFIABLE",
        scenario_market_representativeness="NOT_ESTABLISHED", MODEL_TRAINING_AUTHORIZED=False,
        result_content_sha256=hashlib.sha256(_canonical(results)).hexdigest())
    manifest["artifact_sha256"] = {n: hashlib.sha256((output/n).read_bytes()).hexdigest()
                                  for n in ("scenario_results.json", "frontier_results.csv")}
    _write_json(output / "run_manifest.json", manifest)
    return manifest
