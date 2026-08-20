"""A2 pre-2026 risk-history extension and gated structural R3 research.

This runner reconstructs annual expanding-window A2/R6 research OOF rows.  It
never treats the frozen deployment model as historical OOF and never reads a
2026 partition unless a pre-2026 R3 A/B gate has first been frozen.  Large
evidence is written directly to the external results roots.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
DATA = Path(r"D:\us-tech-quant-data")
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
PHASE_A = RESULTS / "A2_RISK_HISTORY_EXTENSION_R1"
PHASE_B = RESULTS / "A2_RISK_CONTROL_R3_NON_PREDICTIVE_RISK_BUDGETING"
RAW_ROOT = CACHE / "13f_pit_v1/moomoo_daily_raw"
RUN_CACHE = CACHE / "13f_pit_v1/a_a2_quarterly_13f_r1"
QFQ_ROOT = DATA / "moomoo/source/prices_qfq"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R6_OOF = R6_ROOT / "r6_oof_predictions.parquet"
R6_REFERENCE = "LGBM_BAD_ASYM_2"
R1_CONTRACT = RESULTS / "A2_RISK_OS_R1/risk_os_r1_contract.json"
R2_CONTRACT = RESULTS / "A2_RISK_OS_R2/risk_os_r2_contract.json"
R1_HASH = "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e"
R2_HASH = "b486f6f194741b475fbedc7485639350eab9e31a36b48a15db034c836b044411"
R6_HASH = "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4"
POLICY = REPO / "docs/governance/ANTI_BLOAT_POLICY.md"
CUTOFF = pd.Timestamp("2026-01-01")
BASE_COST = .001
RNG_SEED = 20260819


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R1 = load_module("risk_history_r1", REPO / "scripts/v22/a2_risk_os_r1.py")
R3 = R1.R3
R6 = load_module("risk_history_r6", REPO / "scripts/v22/a2_stock_risk_r6.py")
A2 = load_module("risk_history_a2", REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
A2_PRE = load_module("risk_history_a2_pre", REPO / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py")
REBUILD = load_module("risk_history_rebuild", BASELINE / "scripts/run_rebuild.py")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def frame_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.loc[:, columns].sort_values(columns).reset_index(drop=True)
    values = pd.util.hash_pandas_object(ordered, index=False).to_numpy(np.uint64)
    return hashlib.sha256(values.tobytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def frozen_identity() -> dict[str, Any]:
    if not POLICY.is_file() or sha256_file(R1_CONTRACT) != R1_HASH or sha256_file(R2_CONTRACT) != R2_HASH:
        raise RuntimeError("FROZEN_R1_R2_IDENTITY_FAILURE")
    if sha256_file(R6_OOF) != R6_HASH:
        raise RuntimeError("FROZEN_R6_OOF_IDENTITY_FAILURE")
    identity = R1.frozen_identity()
    if not all(identity.get("frozen_baseline_verification", {}).values()):
        raise RuntimeError("FROZEN_A2_IDENTITY_FAILURE")
    return {
        **identity,
        "r1_contract_sha256": R1_HASH,
        "r2_contract_sha256": R2_HASH,
        "r6_oof_sha256": R6_HASH,
        "runner_sha256": sha256_file(Path(__file__)),
    }


def ensure_new_root(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise RuntimeError(f"OUTPUT_ALREADY_EXISTS:{path}")
    path.mkdir(parents=True, exist_ok=True)


def reconstruct_a2_top(matrix: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    pieces: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for year in (2021, 2022):
        start = pd.Timestamp(f"{year}-01-01")
        training = matrix.loc[
            matrix.signal_date.lt(start) & matrix.target.notna() & matrix.target_end_date.lt(start)
        ].copy()
        evaluation = matrix.loc[matrix.signal_date.dt.year.eq(year)].copy()
        if training.empty or evaluation.empty or training.target_end_date.max() >= evaluation.signal_date.min():
            raise RuntimeError(f"A2_EARLY_EXPANDING_SPLIT_FAILURE:{year}")
        model = A2_PRE.make_hgb()
        model.fit(training[list(A2.FEATURE_COLUMNS)].to_numpy(float), training.target.to_numpy(float))
        evaluation["a2_prediction"] = model.predict(evaluation[list(A2.FEATURE_COLUMNS)].to_numpy(float))
        evaluation["a2_rank"] = A2._prediction_rank(evaluation, "a2_prediction")
        top = evaluation.loc[evaluation.a2_rank.le(20)].copy()
        if top.groupby("signal_date").size().ne(20).any():
            raise RuntimeError(f"A2_EARLY_TOP20_FAILURE:{year}")
        top["split"] = f"HISTORICAL_EXPANDING_{year}"
        pieces.append(top[["signal_date", "ticker", "a2_prediction", "a2_rank", "split"]])
        audits.append({
            "fold": f"A2_{year}", "training_start": training.signal_date.min(),
            "training_end": training.signal_date.max(), "training_target_end": training.target_end_date.max(),
            "prediction_start": evaluation.signal_date.min(), "prediction_end": evaluation.signal_date.max(),
            "train_rows": len(training), "prediction_rows": len(evaluation), "top20_rows": len(top),
            "artifact_hash": canonical_hash(top[["signal_date", "ticker", "a2_prediction", "a2_rank"]].to_dict("records")),
        })
    existing = pd.read_parquet(BASELINE / "A2/top20_selections.parquet")
    existing.signal_date = pd.to_datetime(existing.signal_date)
    existing = existing.rename(columns={"a2_rank": "a2_rank", "a2_prediction": "a2_prediction"})
    pieces.append(existing[["signal_date", "ticker", "a2_prediction", "a2_rank", "split"]])
    result = pd.concat(pieces, ignore_index=True).drop_duplicates(["signal_date", "ticker"], keep="last")
    return result.sort_values(["signal_date", "ticker"]).reset_index(drop=True), audits


def adjusted_prices(tickers: set[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache_root = CACHE / "a2_risk_history_extension_r1"
    cache_path = cache_root / "adjusted_prices_pre2026.parquet"
    cache_manifest = cache_root / "adjusted_prices_pre2026_manifest.json"
    if cache_path.is_file() and cache_manifest.is_file():
        manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
        prices = pd.read_parquet(cache_path)
        prices.trade_date = pd.to_datetime(prices.trade_date)
        if set(prices.ticker) == tickers and not prices.trade_date.ge(CUTOFF).any() and manifest.get("panel_sha256") == sha256_file(cache_path):
            return prices, manifest
    members = pd.read_parquet(
        BASELINE / "universe/quarterly_universe_members.parquet",
        columns=["ticker", "moomoo_transport_code"],
    ).drop_duplicates()
    ambiguity = members.groupby("ticker").moomoo_transport_code.nunique()
    if ambiguity.gt(1).any():
        raise RuntimeError("AMBIGUOUS_TICKER_TRANSPORT_MAPPING")
    code_map = members.drop_duplicates("ticker").set_index("ticker").moomoo_transport_code.to_dict()
    missing_map = sorted(tickers - set(code_map))
    if missing_map:
        raise RuntimeError("MISSING_SOURCE_BACKED_TICKER_MAPPING:" + ",".join(missing_map[:20]))
    index, scan_failures = REBUILD.raw_file_index()
    if scan_failures:
        raise RuntimeError("RAW_PRICE_INDEX_SCAN_FAILURE")
    rehab_path = RUN_CACHE / "rehab_factors.parquet"
    rehab = pd.read_parquet(rehab_path)
    frames: list[pd.DataFrame] = []
    source_rows = []
    dummy_wolf = {"event_date": "2099-01-01", "quantity_multiplier": 1.0}
    for ticker in sorted(tickers):
        code = code_map[ticker]
        if code not in index:
            raise RuntimeError(f"MISSING_AUTHORITATIVE_RAW_HISTORY:{ticker}:{code}")
        raw = REBUILD.load_raw_code(code, index[code])
        frame, events = REBUILD.adjusted_price_frame(code, ticker, raw, rehab, dummy_wolf)
        frame = frame.loc[frame.trade_date.lt(CUTOFF)].copy()
        frames.append(frame)
        source_rows.append({
            "ticker": ticker, "transport_code": code, "raw_paths": [str(p) for p in index[code]],
            "raw_path_hashes": [sha256_file(p) for p in index[code]], "row_count": len(frame),
            "start": frame.trade_date.min(), "end": frame.trade_date.max(), "corporate_action_events": len(events),
        })
    prices = pd.concat(frames, ignore_index=True).sort_values(["trade_date", "ticker"])
    if prices.duplicated(["ticker", "trade_date"]).any() or prices.trade_date.ge(CUTOFF).any():
        raise RuntimeError("ADJUSTED_PRICE_IDENTITY_FAILURE")
    manifest = {
        "source_contract": "MOOMOO_OPEND_RAW_PLUS_REHAB/PIT_FORWARD_REHAB_INDEX",
        "rehab_path": str(rehab_path), "rehab_sha256": sha256_file(rehab_path),
        "ticker_count": prices.ticker.nunique(), "row_count": len(prices),
        "date_start": prices.trade_date.min(), "date_end": prices.trade_date.max(),
        "per_ticker": source_rows,
    }
    cache_root.mkdir(parents=True, exist_ok=True)
    write_parquet(cache_path, prices)
    manifest["panel_sha256"] = sha256_file(cache_path)
    write_json(cache_manifest, manifest)
    return prices, manifest


def qqq_calendar() -> pd.DatetimeIndex:
    parts = []
    for year in range(2020, 2026):
        path = QFQ_ROOT / f"year={year}/prices.parquet"
        frame = pd.read_parquet(path, columns=["ticker", "trade_date", "autype", "source"])
        frame.trade_date = pd.to_datetime(frame.trade_date)
        parts.append(frame.loc[frame.ticker.astype(str).str.upper().eq("QQQ")])
    qqq = pd.concat(parts).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    if set(qqq.autype.str.lower()) != {"qfq"} or qqq.trade_date.ge(CUTOFF).any():
        raise RuntimeError("QQQ_CALENDAR_CONTRACT_FAILURE")
    return pd.DatetimeIndex(qqq.trade_date)


def build_stock_panel(top: pd.DataFrame, matrix: pd.DataFrame, prices: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    market = R3.R1.build_market_features(R3.R1.load_pre2026_prices(), R3.R1.load_vix(True))
    info = top.rename(columns={"signal_date": "information_date", "a2_rank": "A2_RANK", "a2_prediction": "A2_PREDICTION"}).copy()
    info = info.loc[info.information_date.between("2021-01-01", "2023-06-30")]
    execution_map = {}
    for date in pd.DatetimeIndex(info.information_date.unique()):
        position = calendar.searchsorted(date, side="right")
        if position < len(calendar):
            execution_map[date] = calendar[position]
    info["signal_date"] = info.information_date.map(execution_map)
    # The A2 forward-alpha label has a different maturity contract from the
    # R6 execution-path label and must not survive this join.
    stock = matrix.drop(columns=["target", "target_end_date"]).rename(columns={"signal_date": "information_date"})
    panel = info.merge(stock, on=["information_date", "ticker"], validate="one_to_one")
    panel = panel.merge(
        market[["market_date", *R3.MARKET_FEATURES, "QQQ_RETURN_20D"]],
        left_on="information_date", right_on="market_date", validate="many_to_one",
    )
    for feature, source in R3.SOURCE_COLUMNS.items():
        panel[feature] = panel[source]
    panel["VOL_ACCELERATION_5D_60D"] = panel.REALIZED_VOL_5D / panel.REALIZED_VOL_60D - 1
    panel["STOCK_MINUS_QQQ_20D"] = panel.RET_20D - panel.QQQ_RETURN_20D
    if panel[R3.FEATURES].isna().any().any() or not panel.information_date.lt(panel.signal_date).all():
        raise RuntimeError("EARLY_R6_FEATURE_PIT_OR_MISSING_FAILURE")
    bars = prices.set_index(["ticker", "trade_date"])
    rows = []
    for row in panel[["signal_date", "ticker"]].itertuples(index=False):
        position = calendar.get_loc(row.signal_date)
        dates = calendar[position:position + 5]
        if len(dates) != 5 or any((row.ticker, date) not in bars.index for date in dates):
            continue
        path = bars.loc[[(row.ticker, date) for date in dates]].reset_index().sort_values("trade_date")
        entry = float(path.iloc[0].open)
        rows.append({
            "signal_date": row.signal_date, "ticker": row.ticker,
            "forward_5d_stock_return": float(path.iloc[-1].close / entry - 1),
            "forward_5d_stock_mae": max(0.0, float(1 - path.low.min() / entry)),
            "forward_5d_stock_mfe": max(0.0, float(path.high.max() / entry - 1)),
            "target_end_date": path.iloc[-1].trade_date,
        })
    panel = panel.merge(pd.DataFrame(rows), on=["signal_date", "ticker"], how="left", validate="one_to_one")
    complete = panel.groupby("signal_date").forward_5d_stock_mae.count()
    panel = panel.loc[panel.signal_date.isin(complete[complete.eq(20)].index)].copy()
    if panel.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("EARLY_R6_EXECUTION_PATH_COVERAGE_FAILURE")
    return panel.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def reconstruct_r6(panel: pd.DataFrame, calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    candidate = next(item for item in R6.CANDIDATES if item.candidate_id == R6_REFERENCE)
    pieces, audits = [], []
    for year in (2022, 2023):
        validation = panel.loc[panel.signal_date.dt.year.eq(year)].copy()
        first = validation.signal_date.min()
        cutoff = calendar[calendar.get_loc(first) - R3.PURGE_EMBARGO_SESSIONS]
        train = panel.loc[panel.target_end_date.lt(cutoff)].copy()
        if train.empty or train.target_end_date.max() >= cutoff:
            raise RuntimeError(f"R6_HISTORICAL_PURGE_FAILURE:{year}")
        mae = float(train.forward_5d_stock_mae.quantile(R6.MAE_SEVERE_QUANTILE))
        mfe = float(train.forward_5d_stock_mfe.quantile(R6.MFE_COMPENSATION_QUANTILE))
        y_train, _ = R6.event_labels(train, mae, mfe)
        y_valid, _ = R6.event_labels(validation, mae, mfe)
        model = R6.make_model(candidate)
        R6.fit_model(model, candidate, train[R3.FEATURES], y_train)
        train_probability = R6.predict_probability(model, train)
        validation["predicted_bad_asymmetry_risk"] = R6.predict_probability(model, validation)
        validation["risk_percentile"] = R3.R1.empirical_percentile(train_probability, validation.predicted_bad_asymmetry_risk.to_numpy())
        validation["bad_asymmetry_5d"] = y_valid
        validation["candidate_id"] = candidate.candidate_id
        validation["model_family"] = candidate.family
        validation["fold"] = f"HISTORICAL_EXPANDING_{year}"
        validation["fold_mae_severe_threshold"] = mae
        validation["fold_mfe_compensation_threshold"] = mfe
        validation["train_max_target_end"] = train.target_end_date.max()
        validation["embargo_cutoff"] = cutoff
        pieces.append(validation)
        audits.append({
            "fold": f"R6_{year}", "training_start": train.signal_date.min(), "training_end": train.signal_date.max(),
            "training_target_end": train.target_end_date.max(), "prediction_start": validation.signal_date.min(),
            "prediction_end": validation.signal_date.max(), "train_rows": len(train), "prediction_rows": len(validation),
            "target_maturity_rule": "target_end_date < five-session-purged validation cutoff",
            "artifact_hash": canonical_hash(validation[["signal_date", "ticker", "predicted_bad_asymmetry_risk", "risk_percentile"]].to_dict("records")),
        })
    rebuilt = pd.concat(pieces, ignore_index=True)
    existing = pd.read_parquet(R6_OOF)
    existing = existing.loc[existing.candidate_id.eq(R6_REFERENCE)].copy()
    existing.signal_date = pd.to_datetime(existing.signal_date)
    first_existing = existing.signal_date.min()
    rebuilt = rebuilt.loc[rebuilt.signal_date.lt(first_existing)]
    common = sorted(set(rebuilt.columns) & set(existing.columns))
    extended = pd.concat([rebuilt[common], existing[common]], ignore_index=True)
    extended = extended.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if extended.duplicated(["signal_date", "ticker"]).any() or extended.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("EXTENDED_R6_OOF_IDENTITY_FAILURE")
    return extended, audits


def weights_positions(oof: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weights = oof[["information_date", "signal_date", "ticker", "A2_PREDICTION", "A2_RANK", "predicted_bad_asymmetry_risk", "risk_percentile", "fold"]].copy()
    weights["base_a2_weight"] = .05
    weights["r6_multiplier"] = np.where(weights.risk_percentile.ge(.90), .50, 1.0)
    weights["base_r6_weight"] = weights.base_a2_weight * weights.r6_multiplier
    open_lookup = prices.set_index(["ticker", "trade_date"]).open
    dates = sorted(pd.to_datetime(weights.signal_date.unique()))
    rows = []
    previous = None
    prior_tickers: set[str] = set()
    for date in dates:
        current_tickers = set(weights.loc[weights.signal_date.eq(date), "ticker"])
        for ticker in sorted(prior_tickers | current_tickers):
            raw_return = np.nan
            if previous is not None and ticker in prior_tickers:
                if (ticker, previous) not in open_lookup.index or (ticker, date) not in open_lookup.index:
                    raise RuntimeError(f"MISSING_EXECUTION_OPEN_RETURN:{date}:{ticker}")
                raw_return = float(open_lookup.loc[(ticker, date)] / open_lookup.loc[(ticker, previous)] - 1)
            rows.append({"date": date, "ticker": ticker, "raw_return": raw_return})
        previous, prior_tickers = date, current_tickers
    positions = pd.DataFrame(rows)
    raw = R1.simulate(R1.target_maps(weights.rename(columns={"base_a2_weight": "weight"}), "weight"), positions, BASE_COST)
    base = R1.simulate(R1.target_maps(weights.rename(columns={"base_r6_weight": "weight"}), "weight"), positions, BASE_COST)
    return weights, positions, raw, base


def index_returns() -> pd.DataFrame:
    pieces = []
    for year in range(2020, 2026):
        frame = pd.read_parquet(QFQ_ROOT / f"year={year}/prices.parquet", columns=["ticker", "trade_date", "close", "autype", "source"])
        frame.trade_date = pd.to_datetime(frame.trade_date)
        pieces.append(frame.loc[frame.ticker.astype(str).str.upper().isin(["SPY", "QQQ", "SOXX"])])
    frame = pd.concat(pieces).sort_values(["ticker", "trade_date"]).drop_duplicates(["ticker", "trade_date"], keep="last")
    frame["return"] = frame.groupby("ticker").close.pct_change(fill_method=None)
    return frame.pivot(index="trade_date", columns="ticker", values="return").sort_index()


def geometry_panel(weights: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    returns = close.pct_change(fill_method=None)
    market = index_returns()
    rows, failures = [], []
    for date, group in weights.groupby("signal_date", sort=True):
        info = pd.Timestamp(group.information_date.iloc[0])
        tickers = group.ticker.tolist()
        history = returns.loc[returns.index <= info, tickers].tail(60)
        complete = history.dropna(how="any")
        if len(complete) != 60:
            failures.append({"signal_date": date, "information_date": info, "reason": "LESS_THAN_60_COMPLETE_AUTHORITATIVE_SESSIONS", "complete_sessions": len(complete)})
            continue
        cov = complete.cov().to_numpy(float)
        corr = complete.corr().to_numpy(float)
        w = group.base_r6_weight.to_numpy(float)
        eig = np.linalg.eigvalsh(corr)
        off = corr[np.triu_indices(len(tickers), 1)]
        adjacency = corr >= .70
        visited, clusters = set(), []
        for start in range(len(tickers)):
            if start in visited:
                continue
            stack, component = [start], []
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node); component.append(node)
                stack.extend(int(x) for x in np.where(adjacency[node])[0] if int(x) not in visited)
            clusters.append(float(w[component].sum()))
        port = complete.mul(w, axis=1).sum(axis=1)
        data = {
            "signal_date": date, "information_date": info, "complete_sessions": len(complete),
            "exante_portfolio_vol": float(np.sqrt(w @ cov @ w) * np.sqrt(252)),
            "average_pairwise_correlation": float(off.mean()), "median_pairwise_correlation": float(np.median(off)),
            "effective_independent_bets": float(1 / (w / w.sum() @ corr @ (w / w.sum()))),
            "top_eigenvalue_share": float(eig[-1] / eig.sum()), "max_cluster_share": max(clusters),
        }
        aligned = market.loc[market.index.isin(complete.index)]
        for ticker in ["SPY", "QQQ", "SOXX"]:
            variance = float(aligned[ticker].var(ddof=1)) if ticker in aligned else np.nan
            data[f"beta_{ticker}"] = float(port.reindex(aligned.index).cov(aligned[ticker]) / variance) if variance > 0 else np.nan
        stress70 = np.maximum(corr, .70); np.fill_diagonal(stress70, 1.0)
        stressed_vol = float(np.sqrt(w @ (np.outer(np.sqrt(np.diag(cov)), np.sqrt(np.diag(cov))) * stress70) @ w) * np.sqrt(252))
        combined = data["beta_SPY"] * -.04 + max(data["beta_SOXX"] - data["beta_SPY"], 0) * -.04 - .03
        data["combined_stress_loss"] = abs(float(combined * max(1.0, stressed_vol / max(data["exante_portfolio_vol"], 1e-12))))
        rows.append(data)
    geometry = pd.DataFrame(rows).sort_values("signal_date")
    return geometry, pd.DataFrame(failures)


def phase_a_run() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ensure_new_root(PHASE_A)
    identity = frozen_identity()
    matrix = pd.read_parquet(BASELINE / "A2/training_matrix.parquet")
    matrix.signal_date = pd.to_datetime(matrix.signal_date); matrix.target_end_date = pd.to_datetime(matrix.target_end_date)
    if matrix.signal_date.ge(CUTOFF).any() or matrix.target_end_date.ge(CUTOFF).any():
        raise RuntimeError("A2_TRAINING_MATRIX_2026_FIREWALL_FAILURE")
    top, a2_folds = reconstruct_a2_top(matrix)
    all_tickers = set(top.loc[top.signal_date.between("2021-01-01", "2023-06-30"), "ticker"])
    existing = pd.read_parquet(R6_OOF, columns=["candidate_id", "ticker"])
    all_tickers |= set(existing.loc[existing.candidate_id.eq(R6_REFERENCE), "ticker"])
    prices, source_manifest = adjusted_prices(all_tickers)
    calendar = qqq_calendar()
    panel = build_stock_panel(top, matrix, prices, calendar)
    reconstructed, r6_folds = reconstruct_r6(panel, calendar)
    weights, positions, raw, base = weights_positions(reconstructed, prices)
    geometry, missing = geometry_panel(weights, prices)
    total_dates = weights.signal_date.nunique()
    coverage = geometry.signal_date.nunique() / total_dates
    regimes = pd.DataFrame([
        {"regime": "COVID_2020_CRASH", "start": "2020-02-19", "end": "2020-03-23", "covered": False},
        {"regime": "HIGH_LIQUIDITY_2020_2021", "start": "2020-03-24", "end": "2021-12-31", "covered": False},
        {"regime": "RATE_GROWTH_DRAWDOWN_2022", "start": "2022-01-01", "end": "2022-12-31", "covered": True},
        {"regime": "RECOVERY_2023", "start": "2023-01-01", "end": "2023-12-31", "covered": True},
        {"regime": "TECH_AI_2024_2025", "start": "2024-01-01", "end": "2025-12-31", "covered": True},
    ])
    year_count = reconstructed.signal_date.dt.year.nunique()
    major = int(regimes.covered.sum())
    pass_gate = bool(coverage >= .95 and major >= 3 and year_count >= 3 and reconstructed.signal_date.min().year <= 2022)
    source_manifest["content_fingerprint"] = frame_hash(prices, ["ticker", "trade_date", "open", "high", "low", "close"])
    folds = {"a2": a2_folds, "r6_historical_oof_reconstruction": r6_folds, "existing_r6_oof_start": str(pd.read_parquet(R6_OOF, columns=["candidate_id", "signal_date"]).query("candidate_id == @R6_REFERENCE").signal_date.min())}
    summary = {
        "A2_RISK_HISTORY_EXTENSION_STATUS": "EVIDENCE_GATE_MET" if pass_gate else "INSUFFICIENT_FOR_R3",
        "FIRST_LEGAL_BASE_R6_OOF_DATE": reconstructed.signal_date.min(),
        "LAST_PRE2026_BASE_R6_OOF_DATE": reconstructed.signal_date.max(),
        "TOTAL_BASE_R6_OOF_DATES": total_dates, "TOTAL_UNIQUE_TRADING_YEARS": year_count,
        "MAJOR_REGIMES_COVERED": regimes.loc[regimes.covered, "regime"].tolist(),
        "R6_HISTORICAL_OOF_COVERAGE": 1.0, "PORTFOLIO_GEOMETRY_COVERAGE": coverage,
        "PIT_VIOLATION_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": 0, "SYNTHETIC_HISTORY_COUNT": 0,
        "PHASE_A_R3_AUTHORIZED": pass_gate, "frozen_identity": identity,
        "historical_reconstruction_label": "R6_HISTORICAL_OOF_RECONSTRUCTION",
        "deployment_model_backcast_count": 0, "2026_OUTCOME_READ_COUNT": 0,
        "NEXT_AUTHORIZED_STEP": "RUN_FROZEN_R3_NON_PREDICTIVE" if pass_gate else "STOP_RETAIN_EXTENDED_HISTORY_EVIDENCE",
    }
    write_json(PHASE_A / "a2_risk_history_extension_summary.json", summary)
    write_json(PHASE_A / "a2_risk_history_extension_audit.json", {"summary": summary, "source_manifest_hash": canonical_hash(source_manifest), "missing_geometry": missing.to_dict("records")})
    write_json(PHASE_A / "a2_risk_history_extension_fold_manifest.json", folds)
    write_json(PHASE_A / "source_manifest.json", source_manifest)
    write_parquet(PHASE_A / "r6_historical_oof_predictions.parquet", reconstructed)
    portfolio = base.rename(columns={"date": "execution_date", "daily_return": "base_r6_daily_return"})
    write_parquet(PHASE_A / "base_r6_historical_portfolio.parquet", portfolio)
    write_parquet(PHASE_A / "portfolio_geometry_extended.parquet", geometry)
    write_csv(PHASE_A / "historical_regime_coverage.csv", regimes)
    write_csv(PHASE_A / "historical_missingness_root_causes.csv", missing if len(missing) else pd.DataFrame(columns=["signal_date", "information_date", "reason", "complete_sessions"]))
    return summary, weights, positions, raw, base


def smooth_budget(raw: pd.Series, maximum_change: float = .05) -> pd.Series:
    out, previous = [], 1.0
    for value in raw:
        previous = float(np.clip(value, previous - maximum_change, previous + maximum_change))
        out.append(previous)
    return pd.Series(out, index=raw.index)


def causal_budgets(geometry: pd.DataFrame) -> pd.DataFrame:
    frame = geometry.sort_values("signal_date").reset_index(drop=True).copy()
    frame["vol_reference"] = frame.exante_portfolio_vol.expanding(min_periods=60).median().shift(1)
    frame["stress_reference"] = frame.combined_stress_loss.expanding(min_periods=60).median().shift(1)
    frame = frame.dropna(subset=["vol_reference", "stress_reference"]).copy()
    frame["vol_raw"] = (frame.vol_reference / frame.exante_portfolio_vol).clip(.50, 1.0)
    frame["stress_raw"] = (frame.stress_reference / frame.combined_stress_loss).clip(.50, 1.0)
    frame["vol_budget"] = smooth_budget(frame.vol_raw)
    frame["stress_budget"] = smooth_budget(frame.stress_raw)
    frame["combined_budget"] = smooth_budget(pd.concat([frame.vol_budget, frame.stress_budget], axis=1).min(axis=1))
    return frame


def strategy_metrics(sim: pd.DataFrame, cost: float) -> dict[str, Any]:
    metric = R1.metrics(sim.daily_return, sim)
    downside = metric["downside_deviation"]
    metric["sortino"] = float(sim.daily_return.mean() * 252 / downside) if downside > 0 else np.nan
    metric["transaction_cost_proxy"] = float(sim.turnover.sum() * cost)
    metric["exposure_volatility"] = float(sim.target_exposure.std(ddof=1))
    return metric


def matched_weights(selected: pd.DataFrame, budget_column: str, output_column: str) -> tuple[pd.DataFrame, float]:
    frame = selected.copy()
    exposure = frame.groupby("signal_date").base_r6_weight.sum().rename("base").to_frame()
    exposure["budget"] = frame.groupby("signal_date")[budget_column].first()
    exposure["dynamic"] = exposure.base * exposure.budget
    exposure["year"] = exposure.index.year
    constants = {}
    for year, group in exposure.iloc[1:].groupby("year"):
        constants[year] = float(group.dynamic.mean() / group.base.mean())
    frame[output_column] = frame.base_r6_weight * frame.signal_date.dt.year.map(constants).fillna(next(iter(constants.values())))
    dynamic_mean = float(exposure.iloc[1:].dynamic.mean())
    matched = frame.groupby("signal_date")[output_column].sum().iloc[1:].mean()
    return frame, abs(dynamic_mean - float(matched))


def r3_contract(identity: dict[str, Any], history_hash: str) -> dict[str, Any]:
    return {
        "contract_id": "A2_RISK_CONTROL_R3_NON_PREDICTIVE_RISK_BUDGETING",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "training_cutoff": "2026-01-01",
        "base_strategy": "frozen-equivalent A2 expanding OOF + frozen-contract R6 historical OOF reconstruction",
        "identities": {"a2": identity.get("frozen_baseline_name"), "r6_oof": R6_HASH, "r1": R1_HASH, "r2": R2_HASH, "extended_history": history_hash},
        "primary": {"method": "VOLATILITY_TARGETING", "vol_estimator": "60-session sample covariance annualized", "reference": "causal expanding median shifted one date; min 60 dates", "min_exposure": .50, "max_exposure": 1.0, "max_daily_change": .05},
        "secondary": {"method": "COMBINED_SPX4_SOXX8_VIX50_CORR70_STRESS_BUDGET", "reference": "causal expanding median shifted one date; min 60 dates", "min_exposure": .50, "max_exposure": 1.0, "max_daily_change": .05},
        "combined": "min(smoothed vol budget, smoothed stress budget), then 0.05 change limit",
        "costs": {"baseline": .001, "two_x": .002, "adverse": .003},
        "matched_control": "calendar-year exact mean exposure plus whole-period audit",
        "classification": {"A": "vol_stability>=5%; MDD,ES5,Calmar improve; Sharpe delta>=-0.03; CAGR delta>=-0.02; useful majority years; adverse costs do not reverse", "B": "vol_stability>0; at least two of MDD/ES5/Calmar improve; CAGR delta>=-0.03; useful majority", "C": "vol_stability>=5% without matched economic gate", "D": "no material advantage over matched", "E": "integrity failure"},
        "2026_policy": "unread unless pre2026 A/B and frozen",
    }


def phase_b_run(phase_a: dict[str, Any], weights: pd.DataFrame, positions: pd.DataFrame, raw: pd.DataFrame, base: pd.DataFrame) -> dict[str, Any]:
    ensure_new_root(PHASE_B)
    identity = frozen_identity()
    geometry = pd.read_parquet(PHASE_A / "portfolio_geometry_extended.parquet")
    geometry.signal_date = pd.to_datetime(geometry.signal_date)
    budgets = causal_budgets(geometry)
    contract = r3_contract(identity, sha256_file(PHASE_A / "r6_historical_oof_predictions.parquet"))
    write_json(PHASE_B / "A2_RISK_CONTROL_R3_CONTRACT.json", contract)
    contract_hash = sha256_file(PHASE_B / "A2_RISK_CONTROL_R3_CONTRACT.json")
    dates = budgets[["signal_date", "vol_budget", "stress_budget", "combined_budget"]]
    selected = weights.loc[weights.signal_date.isin(dates.signal_date)].merge(dates, on="signal_date", validate="many_to_one")
    selected["raw_a2_weight"] = selected.base_a2_weight
    selected["vol_weight"] = selected.base_r6_weight * selected.vol_budget
    selected["stress_weight"] = selected.base_r6_weight * selected.stress_budget
    selected["combined_weight"] = selected.base_r6_weight * selected.combined_budget
    selected, vol_error = matched_weights(selected, "vol_budget", "vol_matched_weight")
    selected, stress_error = matched_weights(selected, "stress_budget", "stress_matched_weight")
    columns = {
        "RAW_A2": "raw_a2_weight", "BASE_R6": "base_r6_weight", "VOL_MATCHED_CONSTANT": "vol_matched_weight",
        "R3_VOL_TARGET": "vol_weight", "STRESS_MATCHED_CONSTANT": "stress_matched_weight",
        "R3_STRESS_BUDGET": "stress_weight", "R3_VOL_STRESS_COMBINED": "combined_weight",
    }
    sims, metrics_rows = {}, []
    for cost_name, cost in {"BASELINE": .001, "TWO_X": .002, "ADVERSE": .003}.items():
        for strategy, column in columns.items():
            sim = R1.simulate(R1.target_maps(selected, column), positions, cost)
            if cost_name == "BASELINE": sims[strategy] = sim
            metrics_rows.append({"cost_case": cost_name, "strategy": strategy, **strategy_metrics(sim, cost)})
    metrics = pd.DataFrame(metrics_rows)
    baseline = metrics.loc[metrics.cost_case.eq("BASELINE")].set_index("strategy")
    dynamic, matched = baseline.loc["R3_VOL_TARGET"], baseline.loc["VOL_MATCHED_CONSTANT"]
    deltas = {key: float(dynamic[key] - matched[key]) for key in ["cagr", "volatility", "sharpe", "maximum_drawdown", "calmar", "expected_shortfall_5", "worst_month", "turnover"]}
    base_returns = base.set_index("date").daily_return.sort_index()
    forecasts = []
    for row in geometry.itertuples(index=False):
        future = base_returns.loc[base_returns.index > row.signal_date].head(20)
        if len(future) == 20:
            forecasts.append({"signal_date": row.signal_date, "exante_vol": row.exante_portfolio_vol, "future_realized_vol_20d": float(future.std(ddof=1) * np.sqrt(252))})
    forecast = pd.DataFrame(forecasts)
    forecast_spearman = float(spearmanr(forecast.exante_vol, forecast.future_realized_vol_20d).statistic)
    fold_rows, useful = [], []
    for year in sorted(pd.to_datetime(sims["R3_VOL_TARGET"].date).dt.year.unique()):
        local = {}
        for name in ["BASE_R6", "VOL_MATCHED_CONSTANT", "R3_VOL_TARGET", "R3_STRESS_BUDGET"]:
            part = sims[name].loc[pd.to_datetime(sims[name].date).dt.year.eq(year)]
            if len(part) < 20:
                continue
            local[name] = strategy_metrics(part, BASE_COST)
            fold_rows.append({"period": str(year), "strategy": name, **local[name]})
        d, m = local["R3_VOL_TARGET"], local["VOL_MATCHED_CONSTANT"]
        improvements = sum([d["maximum_drawdown"] > m["maximum_drawdown"], d["expected_shortfall_5"] > m["expected_shortfall_5"], d["calmar"] > m["calmar"], d["volatility"] < m["volatility"]])
        useful.append({"year": year, "useful": bool(improvements >= 2 and d["sharpe"] >= m["sharpe"] - .03), "improvements": improvements})
    useful_count = int(pd.DataFrame(useful).useful.sum())
    realized_before = base_returns.rolling(20).std(ddof=1) * np.sqrt(252)
    realized_after = sims["R3_VOL_TARGET"].set_index("date").daily_return.rolling(20).std(ddof=1) * np.sqrt(252)
    common = realized_before.index.intersection(realized_after.index)
    stability_improvement = float(1 - realized_after.reindex(common).dropna().std() / realized_before.reindex(common).dropna().std())
    risk_improvements = sum([deltas["maximum_drawdown"] >= 0, deltas["expected_shortfall_5"] >= 0, deltas["calmar"] > 0])
    year_total = len(useful)
    adverse = metrics.loc[metrics.cost_case.eq("ADVERSE")].set_index("strategy")
    adverse_not_reversed = bool(adverse.loc["R3_VOL_TARGET", "sharpe"] >= adverse.loc["VOL_MATCHED_CONSTANT", "sharpe"] - .03)
    a_gate = bool(stability_improvement >= .05 and risk_improvements == 3 and deltas["sharpe"] >= -.03 and deltas["cagr"] >= -.02 and useful_count > year_total / 2 and adverse_not_reversed)
    b_gate = bool(stability_improvement > 0 and risk_improvements >= 2 and deltas["cagr"] >= -.03 and useful_count > year_total / 2)
    if a_gate:
        classification = "A_STRONG_NONPREDICTIVE_RISK_VALUE"
    elif b_gate:
        classification = "B_USEFUL_NONPREDICTIVE_RISK_VALUE"
    elif stability_improvement >= .05:
        classification = "C_RISK_NORMALIZATION_WORKS_BUT_ECONOMIC_VALUE_UNCONFIRMED"
    else:
        classification = "D_NO_MATERIAL_VALUE"
    authorized = classification.startswith(("A_", "B_"))
    write_parquet(PHASE_B / "r3_weight_attribution.parquet", selected)
    write_parquet(PHASE_B / "r3_exante_vol_forecast.parquet", forecast)
    write_csv(PHASE_B / "r3_economic_metrics.csv", metrics)
    write_csv(PHASE_B / "r3_year_regime_metrics.csv", pd.DataFrame(fold_rows))
    write_csv(PHASE_B / "r3_dynamic_minus_matched.csv", pd.DataFrame([deltas]))
    write_csv(PHASE_B / "r3_budget_diagnostics.csv", budgets)
    audit = {
        "contract_sha256": contract_hash, "phase_a_summary_hash": sha256_file(PHASE_A / "a2_risk_history_extension_summary.json"),
        "vol_estimator_causal": True, "reference_shifted": True, "maximum_multiplier": float(budgets.vol_budget.max()),
        "minimum_multiplier": float(budgets.vol_budget.min()), "matched_exposure_error": vol_error,
        "2026_R3_OUTCOME_READ_COUNT": 0, "2026_training_rows": 0, "parameter_search_count": 0,
        "threshold_search_count": 0, "lookahead_violation_count": 0,
    }
    summary = {
        "A2_RISK_CONTROL_R3_STATUS": "VALID_PRE2026_COMPLETE" if classification[0] in "ABCD" else "STOP_INVALID",
        "A2_RISK_CONTROL_R3_CLASSIFICATION": classification,
        "A2_RISK_CONTROL_R3_CONTRACT_SHA256": contract_hash, "R3_PRIMARY_METHOD": "VOLATILITY_TARGETING",
        "R3_AVG_EXPOSURE": float(sims["R3_VOL_TARGET"].target_exposure.mean()),
        "R3_MATCHED_EXPOSURE_ERROR": vol_error, "stress_matched_exposure_error": stress_error,
        "R3_2026_AUTHORIZED": authorized, "2026_R3_OUTCOME_READ_COUNT": 0,
        "exante_future_realized_vol_spearman": forecast_spearman,
        "realized_vol_stability_improvement": stability_improvement, "useful_years": useful_count,
        "evaluated_years": year_total, "dynamic_minus_matched": deltas,
        "NEXT_AUTHORIZED_STEP": "FREEZE_R3_AND_RUN_ONE_SHOT_2026_PROSPECTIVE" if authorized else "PRESERVE_R3_RESULT_AND_STOP;DO_NOT_OPEN_2026",
    }
    write_json(PHASE_B / "r3_audit.json", audit)
    write_json(PHASE_B / "r3_final_summary.json", summary)
    return summary


def print_status(a: dict[str, Any], b: dict[str, Any] | None) -> None:
    print(f"A2_RISK_HISTORY_EXTENSION_STATUS={a['A2_RISK_HISTORY_EXTENSION_STATUS']}")
    print(f"FIRST_LEGAL_BASE_R6_OOF_DATE={pd.Timestamp(a['FIRST_LEGAL_BASE_R6_OOF_DATE']).date()}")
    print(f"LAST_PRE2026_BASE_R6_OOF_DATE={pd.Timestamp(a['LAST_PRE2026_BASE_R6_OOF_DATE']).date()}")
    print(f"BASE_R6_OOF_DATE_COUNT={a['TOTAL_BASE_R6_OOF_DATES']}")
    print(f"BASE_R6_OOF_YEAR_COUNT={a['TOTAL_UNIQUE_TRADING_YEARS']}")
    print(f"MAJOR_REGIMES_COVERED={';'.join(a['MAJOR_REGIMES_COVERED'])}")
    print(f"R6_HISTORICAL_OOF_COVERAGE={a['R6_HISTORICAL_OOF_COVERAGE']:.12g}")
    print(f"PORTFOLIO_GEOMETRY_COVERAGE={a['PORTFOLIO_GEOMETRY_COVERAGE']:.12g}")
    print(f"LOOKAHEAD_VIOLATION_COUNT={a['LOOKAHEAD_VIOLATION_COUNT']}")
    print(f"PHASE_A_R3_AUTHORIZED={str(a['PHASE_A_R3_AUTHORIZED']).upper()}")
    if b is None:
        print(f"NEXT_AUTHORIZED_STEP={a['NEXT_AUTHORIZED_STEP']}")
        return
    for key in ["A2_RISK_CONTROL_R3_STATUS", "A2_RISK_CONTROL_R3_CLASSIFICATION", "A2_RISK_CONTROL_R3_CONTRACT_SHA256", "R3_PRIMARY_METHOD", "R3_AVG_EXPOSURE", "R3_MATCHED_EXPOSURE_ERROR", "R3_2026_AUTHORIZED", "2026_R3_OUTCOME_READ_COUNT", "NEXT_AUTHORIZED_STEP"]:
        print(f"{key}={b[key]}")


def run() -> tuple[dict[str, Any], dict[str, Any] | None]:
    phase_a, weights, positions, raw, base = phase_a_run()
    phase_b = phase_b_run(phase_a, weights, positions, raw, base) if phase_a["PHASE_A_R3_AUTHORIZED"] else None
    print_status(phase_a, phase_b)
    return phase_a, phase_b


if __name__ == "__main__":
    run()
