"""Independent descriptive PIT replay; never modifies frozen QFQ artifacts.

The caller supplies hash-qualified prices and recorded feature snapshots. Missing
signals stop the common window instead of silently skipping a session.
"""
from pathlib import Path
import hashlib
import json
import sys
import importlib.util
import ast
import inspect
from types import SimpleNamespace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

IDS = ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
BASIS = "PIT_FORWARD_REHAB_INDEX"
E5_SOURCE_SHA = "005fdbc3a50df5552b4837e2706b7184198c1d1bfcfd7d51d03d3f3b55aabfa6"


class HeldPriceMissing(ValueError):
    def __init__(self, signal, execution, keys):
        self.signal, self.execution, self.keys = signal, execution, keys
        super().__init__("HELD_EXECUTION_PRICE_MISSING:" + json.dumps(keys))


class HeldEventUnresolved(HeldPriceMissing):
    pass


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_extension_manifest(path, manifest):
    """Return the exact JSON object published, including partial gap keys."""
    payload = json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2)
    published = json.loads(payload)
    Path(path).write_text(payload, encoding="utf-8")
    return published


def verify_refs(refs):
    seen = {}
    for ref in refs:
        path = str(Path(ref["path"]).resolve())
        if path in seen and seen[path] != ref["sha256"]:
            raise ValueError("CONFLICTING_SOURCE_HASH:" + path)
        if reference(path)["sha256"] != ref["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH:" + path)
        seen[path] = ref["sha256"]


def capture_full_prices(output_dir, *, repo_root="D:/us-tech-quant", current_report_path=None):
    """Read the existing execution-price qualifier for the entire Top40 union."""
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest
    from scripts.research.a2.evaluation.demo_performance_prices import load_execution_prices
    from scripts.research.a2.evaluation.demo_performance import reviewed_events
    paths = resolve(Path(repo_root))
    historical, _ = canonical_manifest(Path(paths.daily_root) / "A2_historical_top40/latest.json")
    hist = json.loads(historical.read_text(encoding="utf-8"))
    top_ref = hist["outputs"]["top40"]
    verify_refs([top_ref])
    tickers = set(pd.read_parquet(top_ref["path"], columns=["ticker"]).ticker)
    frames, feature_refs = load_sources(paths, selected, selected.DEFAULT_SOURCE_ROOT)
    for frame in frames:
        tickers.update(frame.ticker.astype(str))
    updated, _ = canonical_manifest(Path(paths.daily_root) / "A2_updated_research/latest.json")
    update = json.loads(updated.read_text(encoding="utf-8"))
    rank_ref = update["outputs"]["rankings"]
    verify_refs([rank_ref])
    tickers.update(pd.read_parquet(rank_ref["path"], columns=["ticker"]).ticker.astype(str))
    if current_report_path is None:
        latest = json.loads((Path(paths.daily_root) / "A2_today_recommendation/latest.json").read_text(encoding="utf-8"))
        current_report_path = latest.get("performance_update", {}).get("source_report") or latest["report_path"]
    current_report_path = Path(current_report_path)
    report = json.loads(current_report_path.read_text(encoding="utf-8"))
    result = load_execution_prices(paths, historical, tickers=sorted(tickers),
        current_report_path=current_report_path, start="2023-01-03", end=report["data_date"])
    resolved, audit = reviewed_events(result["events"], result.get("event_review"), result.get("refs", []))
    metadata = {key: value for key, value in result.items() if key not in {"prices", "events"}}
    metadata["refs"].extend([top_ref, rank_ref, reference(updated), reference(historical), reference(current_report_path), *feature_refs])
    verify_refs(metadata["refs"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    price_path, input_path = output / "three_strategy_prices.parquet", output / "three_strategy_price_inputs.json"
    if price_path.exists() or input_path.exists():
        raise ValueError("CAPTURE_ALREADY_EXISTS_USE_FRESH_DIRECTORY")
    result["prices"].to_parquet(price_path, index=False)
    metadata["captured_prices"] = reference(price_path)
    event_path = output / "three_strategy_events.parquet"
    if event_path.exists():
        raise ValueError("EVENT_CAPTURE_ALREADY_EXISTS")
    result["events"].to_parquet(event_path, index=False)
    metadata["events"] = reference(event_path)
    metadata["event_review_resolved"] = bool(resolved)
    input_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return price_path, input_path


def _load_held_reuse(paths, sources, tickers, target):
    """Read real immutable receipts without a provider fallback or qualification."""
    from scripts.storage.storage_r2a import DataStore
    from scripts import daily_recommendation_prices as original
    if set(sources) != {"acquisition", "massive", "rehab"}:
        raise ValueError("HELD_REUSE_RECEIPT_SET_INCOMPLETE")
    guard = DataStore(paths)
    for ref in sources.values():
        guard._check_data_path(Path(ref["path"]))
    refs = list(sources.values())
    verify_refs(refs)
    acquired = json.loads(Path(sources["acquisition"]["path"]).read_text(encoding="utf-8"))
    cached = json.loads(Path(sources["massive"]["path"]).read_text(encoding="utf-8"))
    rehab_source = Path(sources["rehab"]["path"])
    rehab = json.loads(rehab_source.read_text(encoding="utf-8"))
    if (cached.get("summary", {}).get("status") != "COMPLETE"
            or cached.get("contract", {}).get("provider") != "MASSIVE_GROUPED"
            or rehab.get("source") != "MOOMOO_OPEND_GET_REHAB"
            or rehab.get("target_date") != target):
        raise ValueError("HELD_REUSE_SOURCE_CONTRACT_INVALID")
    selected = [row for row in cached["catalog_records"] if row["ticker"] in tickers]
    if len({row["ticker"] for row in selected}) != len(selected):
        raise ValueError("HELD_REUSE_DUPLICATE_PRICE_RECORD")
    records = {row["ticker"]: row for row in selected}
    if any(row.get("max_date") != target for row in selected):
        raise ValueError("HELD_REUSE_TARGET_PRICE_MISSING")
    for ticker in tickers:
        native = [row for row in acquired.get("results", [])
                  if row.get("item", {}).get("ticker") == ticker
                  and row.get("item", {}).get("adjustment") == "raw"
                  and row.get("item", {}).get("planned_end_date") == target
                  and row.get("status") in original.SUCCESS]
        if ticker not in records and len(native) != 1:
            raise ValueError("HELD_REUSE_TICKER_UNAVAILABLE:" + ticker)
    return acquired, records, rehab, rehab_source, refs


def supplement_held_prices(prices_path, inputs_path, output_dir, tickers, *, target="2026-09-29", repo_root="D:/us-tech-quant", reuse_sources=None):
    """Acquire real native tails and qualify against the accepted raw anchor.

    The original raw qualifier, exact-overlap merge, rehab adapter and event
    review remain authoritative. No catalog promotion or canonical data change.
    """
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest, reviewed_events
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    from scripts.research.a2.inference.historical_top40_prices import _append_raw, _rehab_frame
    from scripts.research.a2.inference.historical_top40 import load_sessions
    from scripts.storage import refresh_market_data as acquisition
    from scripts import daily_recommendation_prices as original
    paths = resolve(Path(repo_root))
    historical, _ = canonical_manifest(Path(paths.daily_root) / "A2_historical_top40/latest.json")
    hist = json.loads(historical.read_text(encoding="utf-8"))
    proof = hist["price_manifest"]
    verify_refs([proof])
    accepted = json.loads(Path(proof["path"]).read_text(encoding="utf-8"))["lineage"]
    entries = {entry["ticker"]: entry for entry in accepted if entry["ticker"] in tickers}
    if set(entries) != set(tickers):
        raise ValueError("HELD_NATIVE_ANCHOR_NOT_QUALIFIED")
    sessions, _ = load_sessions(paths)
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions))
    first = min(pd.Timestamp(entry["raw_end"]) for entry in entries.values())
    start = str(calendar[calendar <= first][-6].date())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    members = [{"ticker": ticker, "moomoo_symbol": entries[ticker]["code"]} for ticker in tickers]
    if any(row["moomoo_symbol"] != "US." + row["ticker"] for row in members):
        raise ValueError("EXPLICIT_HELD_NATIVE_MAPPING_REQUIRED")
    args = SimpleNamespace(work_root=output / "acquisition", repo_root=Path(repo_root), tickers=list(tickers),
        universe_csv=None, start=start, end=target, adjustments=["raw"], host=None, port=None,
        max_retries=1, execute=True)
    reused_refs = []
    rehab_source = output / "rehab/rehab_receipt.json"
    massive_records = {}
    if reuse_sources is not None:
        # The original source, raw, rehab, PIT-prefix and event gates below
        # still qualify every reused receipt. Transport is never reopened.
        acquired, massive_records, rehab, rehab_source, reused_refs = _load_held_reuse(
            paths, reuse_sources, tickers, target)
    else:
        acquired = acquisition.run(args)
    if reuse_sources is None and acquired["status"] not in {"ACQUIRED", "ALL_INTERVALS_REUSED"}:
        from scripts.storage import refresh_massive_market as massive
        from scripts.storage.refresh_current_massive import load_api_key, _cached_days
        key = load_api_key(paths)
        if not key:
            raise ValueError("HELD_NATIVE_QUOTA_AND_ALTERNATE_CREDENTIAL_UNAVAILABLE")
        cached = _cached_days([paths.cache_root / "data_acquisition/massive_20260913",
                              paths.cache_root / "daily_recommendation/massive_current"], target)
        days = [str(day.date()) for day in calendar if pd.Timestamp(start) <= day <= pd.Timestamp(target)]
        work = output / "massive/checkpoints"
        for day in days:
            if day in cached:
                source, saved = cached[day]
                destination = work / "days" / day / "checkpoint.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
        summary = massive.acquire(days, tickers, key, work, output_root=output / "massive/normalized")
        if summary["status"] != "COMPLETE":
            raise ValueError("HELD_ALTERNATE_ACQUISITION_INCOMPLETE")
        records = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))["catalog_records"]
        massive_records = {record["ticker"]: record for record in records}
    if reuse_sources is None:
        rehab = original.refresh_rehab(paths, members, output / "rehab", target)
    metadata = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
    refs = list(metadata["refs"]) + reused_refs + [reference(prices_path), reference(inputs_path), proof, reference(historical)]
    captured = {}
    def verify(path, sha):
        ref = {"path": str(Path(path).resolve()), "sha256": sha}
        verify_refs([ref])
        captured[ref["path"]] = ref
        return Path(path)
    coverage = json.loads(original.verify(original.COVERAGE_PATH, original.COVERAGE_SHA).read_text(encoding="utf-8"))
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
            "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    adapter = original._adapter(target)
    prices = pd.read_parquet(prices_path)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    events = pd.read_parquet(original.verify(metadata["events"]["path"], metadata["events"]["sha256"]))
    contracts = []
    from scripts.storage.storage_r2a import DataStore
    store = DataStore(paths)
    for ticker in tickers:
        entry = entries[ticker]
        raw = reader._raw(entry, verify, store, {})
        receipts = [row for row in acquired["results"] if row["item"]["ticker"] == ticker
                    and row.get("status") in original.SUCCESS]
        bridge = None
        if ticker in massive_records:
            from scripts.storage.storage_r2a import DataStore
            record = massive_records[ticker]
            recent, bridge = original._qualified_massive_tail(record, raw, ticker, target, DataStore(paths))
            verify(record["path"], record["source_sha256"])
            for leaf in bridge["raw_inputs"]:
                verify(leaf["path"], leaf["sha256"])
                verify(leaf["checkpoint_path"], leaf["checkpoint_sha256"])
            receipt = {"provider": "MASSIVE_GROUPED", "qualification": bridge}
        else:
            if len(receipts) != 1:
                raise ValueError("HELD_NATIVE_RECEIPT_INCOMPLETE:" + ticker)
            receipt = receipts[0]
            path = verify(receipt["path"], receipt["sha256"])
            native = pd.read_csv(path)
            acquisition.validate_records(native.to_dict("records"), receipt["item"])
            recent = original._raw_frame(native, entry["code"])
        raw = _append_raw(raw, recent, calendar)
        if raw.trade_date.max() != pd.Timestamp(target):
            raise ValueError("HELD_NATIVE_TARGET_DATE_MISSING:" + ticker)
        fresh = [row for row in rehab["results"] if row.get("code") == entry["code"] and row.get("status") == "PASS"]
        if len(fresh) != 1:
            raise ValueError("HELD_REHAB_MISSING:" + ticker)
        factor = fresh[0]
        if pd.Timestamp(factor["fetched_at"]) < pd.Timestamp(target).tz_localize("America/New_York") + pd.Timedelta(hours=16):
            raise ValueError("HELD_REHAB_PREDATES_TARGET_CLOSE")
        factors = _rehab_frame(factor["path"], factor["sha256"], entry["code"], factor["row_count"], verify)
        adjusted, detected = adapter.adjusted_price_frame(entry["code"], ticker, raw, factors, wolf)
        old = prices.loc[prices.ticker.eq(ticker)]
        overlap = old.merge(adjusted, on=["trade_date", "ticker"], suffixes=("_old", "_new"))
        if len(overlap) != len(old) or any(not overlap[field + "_old"].eq(overlap[field + "_new"]).all()
                                            for field in ("open", "close", "high", "low", "volume")):
            raise ValueError("HELD_PIT_PREFIX_CHANGED:" + ticker)
        tail = adjusted.loc[adjusted.trade_date.gt(old.trade_date.max()), prices.columns]
        prices = pd.concat([prices, tail], ignore_index=True)
        if detected:
            fresh_events = pd.DataFrame(detected)
            fresh_events["ticker"] = ticker
            events = pd.concat([events, fresh_events], ignore_index=True).drop_duplicates(["ticker", "event_date", "audit_kind"])
        contracts.append({"ticker": ticker, "accepted_anchor": entry, "acquisition_receipt": receipt,
            "fresh_rehab": factor, "qualification": "ORIGINAL_NATIVE_ANCHOR_EXACT_RAW_OVERLAP_ALL_SESSIONS_UNCHANGED_PIT_PREFIX"})
    refs.extend(captured.values())
    refs.extend([reference(rehab_source),
                 {"path": str(original.ADAPTER_PATH), "sha256": original.ADAPTER_SHA},
                 {"path": str(original.COVERAGE_PATH), "sha256": original.COVERAGE_SHA}])
    verify_refs(refs)
    reviewed_events(events, metadata.get("event_review"), refs)
    price_output, event_output = output / "prices.parquet", output / "events.parquet"
    prices.sort_values(["ticker", "trade_date"]).to_parquet(price_output, index=False)
    events.to_parquet(event_output, index=False)
    metadata.update(refs=refs, events=reference(event_output), captured_prices=reference(price_output), held_tail_contracts=contracts)
    input_output = output / "price_inputs.json"
    input_output.write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return price_output, input_output


def common_clock(sessions, signal_dates, target):
    """Require each prior session signal; report first gap and retain a prefix."""
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().sort_values().unique()
    present = set(pd.DatetimeIndex(pd.to_datetime(signal_dates)).normalize())
    pairs, gap = [], None
    for signal, execution in zip(calendar[:-1], calendar[1:]):
        if signal < pd.Timestamp("2026-01-02") or execution > pd.Timestamp(target):
            continue
        if signal not in present:
            gap = {"signal_date": str(signal.date()), "execution_date": str(execution.date()),
                   "reason": "COMPLETE_FROZEN_SIGNAL_FEATURES_MISSING"}
            break
        pairs.append((signal, execution))
    if not pairs:
        raise ValueError("NO_CONTIGUOUS_EXECUTION_WINDOW")
    return pairs, gap


def event_clock(pairs, audit):
    if "audit_kind" not in audit:
        return pairs, None
    unresolved = audit.loc[audit.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
        & audit.resolution_status.eq("UNREVIEWED")]
    dates = pd.to_datetime(unresolved.event_date)
    active = unresolved.loc[dates.ge(pairs[0][0]) & dates.le(pairs[-1][1])]
    if active.empty:
        return pairs, None
    first = pd.to_datetime(active.event_date).min()
    rows = active.loc[pd.to_datetime(active.event_date).eq(first)]
    gap = {"execution_date": str(first.date()), "reason": "UNRESOLVED_CANDIDATE_CORPORATE_ACTION",
           "tickers": sorted(set(rows.ticker.astype(str)))}
    retained = [(signal, execution) for signal, execution in pairs if execution < first]
    if not retained:
        raise ValueError("NO_EVENT_QUALIFIED_EXECUTION_WINDOW:" + str(gap))
    return retained, gap


def score_panel(frames, selected, runtime):
    """Project only model inputs and call predict, never any fitting API."""
    days = {}
    for frame in frames:
        column = next((c for c in ("signal_date", "trade_date", "target_date") if c in frame), None)
        if column is None:
            raise ValueError("FEATURE_DATE_MISSING")
        frame = frame.rename(columns={column: "signal_date"})
        for _, group in frame.groupby("signal_date"):
            if {"pred_hgb", "pred_q10"}.issubset(group):
                # The immutable original panel includes valid pre-recorded
                # predictions for a few short-return-history members. Reuse
                # those qualified scores; never impute missing lag inputs.
                day = str(pd.Timestamp(group.signal_date.iloc[0]).date())
                if len(group) != 40 or group.ticker.nunique() != 40 or set(group.raw_rank) != set(range(1, 41)):
                    raise ValueError("RECORDED_TOP40_INCOMPLETE:" + day)
                if not np.isfinite(group[["raw_rank", "raw_score", "pred_hgb", "pred_q10"]].to_numpy(float)).all():
                    raise ValueError("RECORDED_PREDICTIONS_NONFINITE:" + day)
                identity = ["signal_date", "ticker", "raw_rank", "raw_score"]
                if "security_id" in group:
                    identity.append("security_id")
                normal = group[[*identity, *selected.FEATURES, "pred_hgb", "pred_q10"]].copy()
            else:
                normal, day = selected._normalise_day(group, runtime)
                normal["pred_hgb"] = runtime["model"].predict(normal[list(selected.FEATURES)])
                normal["pred_q10"] = runtime["q10"].predict(normal[list(selected.FEATURES)])
            if day in days:
                old = days[day].sort_values("ticker").reset_index(drop=True)
                new = normal.sort_values("ticker").reset_index(drop=True)
                pd.testing.assert_frame_equal(old, new, check_exact=True, check_dtype=False)
            else:
                days[day] = normal
    panel = pd.concat(days.values(), ignore_index=True).sort_values(["signal_date", "raw_rank"])
    return panel


def load_sources(paths, selected, root, feature_paths=()):
    refs = []
    original = root / "test2026/predictions.parquet"
    original_ref = {"path": str(original), "sha256": selected.REPLAY_HASHES["test2026/predictions.parquet"]}
    verify_refs([original_ref])
    refs.append(original_ref)
    frames = [pd.read_parquet(original)]
    for report_path in sorted((Path(paths.daily_root) / "A2_today_recommendation/runs").glob("*/report.json")):
        immutable = report_path.with_name("recommendation_source.json")
        if immutable.is_file():
            candidate = json.loads(immutable.read_text(encoding="utf-8"))
            if candidate.get("status") == "READY" and candidate.get("selected_hgb_features"):
                report_path = immutable
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "READY" or not report.get("selected_hgb_features"):
            continue
        binding = report["selected_hgb_features"]
        if not isinstance(binding, dict) or not binding.get("path") or not binding.get("sha256"):
            # Daily A2 can be READY while the independent HGB snapshot records
            # BLOCKED/INCOMPLETE. That is not a qualified inference snapshot.
            continue
        captured = {}
        day, _, _ = selected._current_day(paths, report_path, captured)
        if day is not None:
            frames.append(day)
            refs.extend(captured.values())
    for path in feature_paths:
        refs.append(reference(path))
        frames.append(pd.read_parquet(path))
    return frames, refs


def recover_missing_features(paths, frames, prices, sessions, selected):
    """Use recorded Top40 and the original, hash-bound feature function only."""
    pointer = Path(paths.daily_root) / "A2_updated_research/latest.json"
    captured_bytes = pointer.read_bytes()
    old = json.loads(captured_bytes)
    canonical = Path(old["report_path"])
    if canonical.read_bytes() != captured_bytes:
        raise ValueError("PERFORMANCE_POINTER_CANONICAL_MISMATCH")
    rank_ref = old["outputs"]["rankings"]
    verify_refs([rank_ref])
    ranked = pd.read_parquet(rank_ref["path"])
    known = {pd.Timestamp(day).normalize() for frame in frames for day in
             frame[next(c for c in ("signal_date", "trade_date", "target_date") if c in frame)].unique()}
    missing = sorted(day for day in set(pd.to_datetime(ranked.target_date)) - known
                     if day >= pd.Timestamp("2026-01-02") and day <= prices.trade_date.max())
    if not missing:
        return [], []
    source = Path(paths.repo_root) / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
    ref = {"path": str(source), "sha256": "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"}
    verify_refs([ref])
    module = selected._load_module("_independent_original_features", source)
    features = module.build_stock_state_features(prices[["ticker", "trade_date", "close", "volume"]])
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().sort_values().unique()
    recovered = []
    for day in missing:
        top = ranked.loc[pd.to_datetime(ranked.target_date).eq(day)].copy()
        if len(top) != 40:
            continue
        top = top.rename(columns={"target_date": "signal_date", "rank": "raw_rank", "score": "raw_score"})
        base = features.loc[pd.to_datetime(features.trade_date).eq(day), ["ticker", *selected.BASE_FEATURES]]
        snapshot = top[["signal_date", "ticker", "security_id", "raw_rank", "raw_score"]].merge(base, on="ticker", how="left", validate="one_to_one")
        slots = calendar[calendar <= day][-11:]
        if len(slots) != 11 or slots[-1] != day:
            continue
        for index in range(10):
            snapshot[f"lag_ret_{index:02d}"] = np.nan
        for ticker in snapshot.ticker:
            group = prices.loc[prices.ticker.eq(ticker)].set_index("trade_date").close.reindex(slots)
            returns = group.pct_change(fill_method=None)
            for index in range(10):
                snapshot.loc[snapshot.ticker.eq(ticker), f"lag_ret_{index:02d}"] = returns.iloc[-1-index]
        if np.isfinite(snapshot[[*selected.BASE_FEATURES, *(f"lag_ret_{i:02d}" for i in range(10))]].to_numpy(float)).all():
            recovered.append(snapshot)
    return recovered, [rank_ref, reference(canonical), ref]


def replay_common(replay, name, spec, panel, prices, runtime, pairs):
    """Same frozen target callback, with the validated official session clock.

    E5's original dates_for derives sessions from QQQ prices. QQQ is only a
    calendar proxy, not a strategy holding; this producer uses the verified
    official calendar directly and requires every signal in that calendar.
    """
    days = {pd.Timestamp(day): group for day, group in panel.groupby("signal_date")}
    price_keys = set(zip(pd.to_datetime(prices.trade_date), prices.ticker))
    execution_by_signal = dict(pairs)
    decisions = []
    def target(signal, shares, values, nav):
        exceptional = [(str(execution_by_signal[signal].date()), ticker) for ticker, qty in shares.items()
            if qty > 0 and (execution_by_signal[signal], ticker) in runtime.get("unresolved_events", set())]
        if exceptional:
            raise HeldEventUnresolved(signal, execution_by_signal[signal], exceptional)
        missing = [(str(day.date()), ticker) for day in (signal, execution_by_signal[signal])
                   for ticker, qty in shares.items() if qty > 0 and (day, ticker) not in price_keys]
        if missing:
            raise HeldPriceMissing(signal, execution_by_signal[signal], missing)
        group = days[signal]
        if spec is None:
            wanted = {str(ticker): .05 for ticker in group.loc[group.raw_rank.le(20), "ticker"]}
            diagnostic = {"raw_targets": wanted.copy(), "solver_failed": False}
        else:
            wanted, diagnostic = runtime["optimizer"].solve(group, shares, values, nav,
                runtime["risk"], spec, signal)
        for ticker in sorted(set(shares) | set(wanted) | set(diagnostic["raw_targets"])):
            decisions.append({"candidate": name, "signal_date": signal, "ticker": ticker,
                "signal_close_shares": shares.get(ticker, 0.), "signal_close_weight": values.get(ticker, 0.) / nav,
                "raw_target_weight": diagnostic["raw_targets"].get(ticker, 0.),
                "target_weight": wanted.get(ticker, 0.), "solver_failed": diagnostic["solver_failed"]})
        return wanted
    result = replay(name, target, prices, [execution for _, execution in pairs],
                    {execution: signal for signal, execution in pairs})
    return result, pd.DataFrame(decisions)


def run_extension(prices_path, price_inputs_path, output_dir, *, repo_root="D:/us-tech-quant",
                  feature_paths=(), target_date=None, sessions=None):
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.inference.historical_top40 import load_sessions
    paths = resolve(Path(repo_root))
    root = selected.DEFAULT_SOURCE_ROOT
    selected.verify_frozen(root)
    runtime = selected._runtime(root)
    inputs = json.loads(Path(price_inputs_path).read_text(encoding="utf-8"))
    if inputs.get("price_basis") != BASIS:
        raise ValueError("QUALIFIED_PIT_PRICE_BASIS_REQUIRED")
    producer_ref = reference(__file__)
    refs = list(inputs["refs"]) + [reference(prices_path), reference(price_inputs_path), producer_ref]
    if not inputs.get("events"):
        raise ValueError("QUALIFIED_EVENT_CAPTURE_REQUIRED")
    refs.append(inputs["events"])
    verify_refs(refs)
    from scripts.research.a2.evaluation.demo_performance import reviewed_events
    events = pd.read_parquet(inputs["events"]["path"])
    resolved_events, event_audit = reviewed_events(events, inputs.get("event_review"), refs)
    prices = pd.read_parquet(prices_path)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("DUPLICATE_PRICE_IDENTITY")
    if not np.isfinite(prices[["open", "close"]].to_numpy(float)).all() or not prices[["open", "close"]].gt(0).all().all():
        raise ValueError("INVALID_EXECUTION_PRICE")
    target = target_date or str(prices.trade_date.max().date())
    frames, feature_refs = load_sources(paths, selected, root, feature_paths)
    refs.extend(feature_refs)
    refs.extend({"path": str(root / name), "sha256": sha} for name, sha in selected.FROZEN_HASHES.items())
    if sessions is None:
        sessions, calendar_ref = load_sessions(paths)
        # The calendar reader validates its immutable source bindings itself.
    recovered, recovered_refs = recover_missing_features(paths, frames, prices, sessions, selected)
    frames.extend(recovered)
    refs.extend(recovered_refs)
    panel = score_panel(frames, selected, runtime)
    pairs, gap = common_clock(sessions, panel.signal_date.unique(), target)
    # Conservative: any unresolved event in the complete candidate universe
    # stops all three books. A later signal never fabricates event resolution.
    unreviewed = event_audit.loc[event_audit.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
        & event_audit.resolution_status.eq("UNREVIEWED")] if "audit_kind" in event_audit else event_audit.iloc[:0]
    runtime = {**runtime, "unresolved_events": set(zip(pd.to_datetime(unreviewed.event_date), unreviewed.ticker))}
    # Require genuine prices for all eligible names at close and next open.
    indexed = prices.set_index(["trade_date", "ticker"])
    qualified = []
    for signal, execution in pairs:
        names = panel.loc[panel.signal_date.eq(signal) & panel.raw_rank.le(20), "ticker"]
        missing = [(str(day.date()), name) for day in (signal, execution) for name in names
                   if (day, name) not in indexed.index]
        if missing:
            gap = {"signal_date": str(signal.date()), "execution_date": str(execution.date()),
                   "reason": "ELIGIBLE_EXECUTION_PRICES_MISSING", "keys": missing}
            break
        qualified.append((signal, execution))
    if not qualified:
        raise ValueError("NO_QUALIFIED_EXECUTION_WINDOW:" + str(gap))
    pairs = qualified
    output = Path(output_dir).resolve()
    if output.is_relative_to(root.resolve()):
        raise ValueError("OUTPUT_MUST_NOT_MUTATE_FROZEN_SOURCE")
    output.mkdir(parents=True, exist_ok=False)
    close_path = root / "audit_20260926/close_clock.py"
    with selected._isolated_imports(root):
        # Read only the hash-qualified supervised close-clock function. The
        # legacy module imports unrelated RL training dependencies (torch).
        # No RL function or training entry point is imported or executed.
        tree = ast.parse(close_path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "close_clock_replay")
        e5_path = Path("D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/run_a2_execution_efficiency_r2.py")
        e5_ref = {"path": str(e5_path), "sha256": E5_SOURCE_SHA}
        verify_refs([e5_ref])
        refs.append(e5_ref)
        namespace = {"inspect": inspect, "rl_policy": SimpleNamespace(E5=e5_path)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(close_path), "exec"), namespace)
        e5 = selected._load_module("_independent_pit_e5", e5_path)
        if e5.COST_RATE != .001:
            raise ValueError("FROZEN_ONE_WAY_COST_CHANGED")
        replay = namespace["close_clock_replay"](e5)
        strategy_data = {}
        while True:
            completed = {}
            try:
                for sid in IDS:
                    name = "RAW" if sid == "RAW_A2" else sid
                    spec = None if sid == "RAW_A2" else runtime["optimizer"].SPECS[sid]
                    completed[sid] = replay_common(replay, name, spec, panel, prices, runtime, pairs)
                break
            except HeldPriceMissing as exc:
                gap = {"signal_date": str(exc.signal.date()), "execution_date": str(exc.execution.date()),
                       "reason": "HELD_CORPORATE_ACTION_UNRESOLVED" if isinstance(exc, HeldEventUnresolved)
                           else "HELD_EXECUTION_PRICE_MISSING", "keys": exc.keys}
                pairs = [(signal, execution) for signal, execution in pairs if execution < exc.execution]
                if not pairs:
                    raise ValueError("NO_QUALIFIED_EXECUTION_WINDOW:" + str(gap)) from exc
        for sid in IDS:
            result, decisions = completed[sid]
            ledger = result.daily
            expected = pd.DatetimeIndex([execution for _, execution in pairs])
            if not pd.DatetimeIndex(ledger.execution_date).equals(expected):
                raise ValueError("COMMON_EXECUTION_CLOCK_CHANGED:" + sid)
            daily_path, targets_path = output / (sid.lower() + "_daily.parquet"), output / (sid.lower() + "_targets.parquet")
            ledger.to_parquet(daily_path, index=False)
            decisions.to_parquet(targets_path, index=False)
            daily = selected._daily_rows(ledger)
            targets = []
            for day, rows in decisions.groupby("signal_date"):
                records = [{"ticker": row.ticker, "target_weight": float(row.target_weight),
                            "weight_before": float(row.signal_close_weight),
                            "action": selected._action(row.target_weight, row.signal_close_weight)}
                           for row in rows.itertuples()]
                targets.append({"signal_date": str(day.date()), "rows": records})
            strategy_data[sid] = {"label": "Raw A2" if sid == "RAW_A2" else selected.LABELS[sid],
                "daily": daily, "targets": targets,
                "summary": {"end_nav": daily[-1]["nav"], "cumulative_return": daily[-1]["nav"] - 1,
                    "max_drawdown": float((ledger.nav / ledger.nav.cummax() - 1).min()),
                    "turnover": float(ledger.turnover.sum()),
                    "mean_cash": float(ledger.cash_weight.mean()), "days": len(daily)},
                "outputs": {"daily": reference(daily_path), "targets": reference(targets_path)}}
    verify_refs(refs)
    period = {"start": str(pairs[0][1].date()), "end": str(pairs[-1][1].date()), "days": len(pairs),
              "price_basis": BASIS, "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"}
    manifest = {"schema_version": 1, "source_id": "NEW_PIT_COMPARISON", "status": "PARTIAL" if gap else "READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "performance_period": period, "requested_end_date": target, "blocked_next": gap,
        "strategies": strategy_data, "source_refs": refs, "model_fit_calls": 0,
        "preserved_frozen_qfq_root": str(root),
        "producer_ref": producer_ref,
        "initial_cash_coordinate": 1.0,
        "shared_scores_historical": [record for day, group in panel.groupby("signal_date")
            for record in selected._score_rows(group, signal_date=str(day.date()))],
        "broker_action_allowed": False, "cost_one_way": .0005,
        "limitations": ["Independent descriptive PIT comparison; original frozen QFQ replay is unchanged.",
                        "Same frozen strategy parameters and cash-start share/cash engine; price coordinates differ."]}
    return _write_extension_manifest(output / "manifest.json", manifest)
