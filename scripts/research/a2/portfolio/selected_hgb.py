"""Publish two user-selected frozen HGB policies; never train or trade.

Imports stay in the standard library until a producer explicitly requests
inference. The DEMO reader consumes the resulting JSON without this runtime.
Account inputs are signal-close weights; recorded backtest positions are never
used as a current account. Frozen research artifacts are strictly read-only.
"""
from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from typing import Any, Mapping


STRATEGY_IDS = ("HGB_DIAG_5", "HGB_FACTOR_5")
LABELS = {"HGB_DIAG_5": "HGB＋对角风险", "HGB_FACTOR_5": "HGB＋因子／收缩风险"}
SELECTION_BASIS = "USER_SELECTED_AFTER_EXPOSURE"
DEFAULT_SOURCE_ROOT = Path(r"D:\us-tech-quant-backtests\a2_research\a2_top20_all_methods_20260925")
HISTORICAL_RUN = "20260924_gap_fill_complete"
A2_MODEL_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
BASE_FEATURES = (
    "ret_1d", "ret_5d", "ret_20d", "realized_vol_20d", "downside_vol_20d",
    "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d",
)
FEATURES = ("raw_rank_strength", "raw_score_z", *BASE_FEATURES,
            *(f"lag_ret_{index:02d}" for index in range(10)))
FROZEN_HASHES = {
    "freeze_manifest.json": "5378905a5e964b49921153e08ed29eb70b6406bddbfc2e3d4e7e41488467c1d8",
    "supervised_manifest.json": "11ee3d44c4789b5a52aea804def91fdb10be952ba3749d0641dd841384621565",
    "models/hgb_2026092501.joblib": "e9edead35d1b0b8f6732d6991238169d2156d3c7d0da7e37ae73533ea2bd3a15",
    "models/q10_2026092501.joblib": "d026dabc895f6307e94c65950f736167a0215afaeb6e41e4f8bc024bcec88608",
    "risk_artifacts/final_pre2026.joblib": "f6d155b0134ae6567dbb51c2519cafd0bf034e22e03077e41dd1b5467a67af60",
    "optimize_route.py": "897531e65089bdf2c50a5d10c7d54d28b03e47f976fd00855f53545d7359a17d",
    "risk_aux.py": "14228e92a92cd747cc289dcac909fd3004f070a2f9d664c6a650b30d04a84622",
    "prepare.py": "5c910bec5b9c29ba50837d8cc385c3011ed612b204ab4d00089df1560ea9c079",
    "../a2_top20_action_nn_20260925/safe_inputs.py": "ce4ed749c6fec2f7b361a3a10d1b705d6ae357ff19427a0cb3280c6c8b6d1dbd",
    "audit_20260926/close_clock.py": "d0662181bbda504a6bcd23c2a12f09d4cef8910627e6c2c28f0d8cda225d02a5",
}
REPLAY_HASHES = {
    "audit_20260926/close_clock_2026_summary.csv": "eca2487bfb8ff02bd887aa5ccc3e3837d4b58e4861f1cc17e31a57c9e6dc97e4",
    "audit_20260926/raw_daily.parquet": "d3551ec6b29880dece1fad85622cfd1cd4e849634e3f765dcae30c82fe05a65d",
    "audit_20260926/raw_targets.parquet": "e041e5ff2e9bbd0f73f5e30d8fa5f0cc7d980241b3bfb60c2c771ce79239f17b",
    "audit_20260926/hgb_diag_5_daily.parquet": "98babd63e7e3d4417c0991d2a46b301cdc2cbdb38efc1ab415641c250858b42d",
    "audit_20260926/hgb_diag_5_targets.parquet": "b387e5e936e10df3a0c1adf81050b2476e3195219e32bed4a43c87bf52a2c81a",
    "audit_20260926/hgb_factor_5_daily.parquet": "668051147cf70d8dfd8c7439200d6a1efba1ae55317ccafcf8d8732ce813d8e7",
    "audit_20260926/hgb_factor_5_targets.parquet": "f49b47c4e35b7546daf5308ac36b74fa7fdd3ae060c46da4979a0dfd043a49f9",
    "test2026/summary.csv": "f47f90516f1ded24092b5683403083724801dbdccd7eacf5a2549fbec4574fd8",
    "test2026/predictions.parquet": "0b4942acac14ecbf16ae103599de69461e3526a6dd375f619a99b535a4f84dff",
}
HISTORY_HASHES = {
    "manifest.json": "ef29fb7b51a01f7e2414afa919d2e9701a2049afa3e2745cab77399790af63bb",
    "top40.parquet": "ae4a6270752d7d255967a61e056c9b3ea11fbf5396b4e7eff3d985e9b7eff108",
    "inference_features.parquet": "92df506f923964c3a7f748cda77976d6c08b7c172b54d4710e04aee33cb05304",
}
LIMITATIONS = [
    "按用户要求选择已观察研究期中的两个策略；不是首次盲测或实盘账户。",
    "历史绩效使用修复后的信号收盘时钟，限2026-08-18以前可核验的QFQ价格代理。",
    "当前方案默认空仓账户；真实账户须传入同一信号日的收盘权重及现金。",
    "收盘生成目标、下一交易日开盘执行；方案不会下单，也不代表已成交持仓。",
]
_RUNTIME: dict[str, Any] = {}
_RUNTIME_LOCK = threading.RLock()
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9./_-]{0,31}\Z")


class SelectedStrategyError(ValueError):
    """A failed source, feature or account contract; never substitute a policy."""


def _get(paths, key, default=None):
    return paths.get(key, default) if isinstance(paths, Mapping) else getattr(paths, key, default)


def _source_root(paths=None, source_root=None):
    value = source_root or _get(paths, "selected_hgb_source_root") or os.environ.get("USTQ_SELECTED_HGB_SOURCE") or DEFAULT_SOURCE_ROOT
    return Path(value).expanduser().resolve()


def _json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise SelectedStrategyError("EXPECTED_JSON_OBJECT:" + str(path))
    return value


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify(path, expected):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SelectedStrategyError("SOURCE_HASH_REQUIRED:" + str(path))
    if digest(path) != expected:
        raise SelectedStrategyError("SOURCE_HASH_MISMATCH:" + str(path))
    return Path(path)


def verify_frozen(source_root=None):
    """Verify bytes before any pickle/joblib load or original-code import."""
    root = _source_root(source_root=source_root)
    for relative, expected in FROZEN_HASHES.items():
        _verify(root / relative, expected)
    manifest = _json(root / "supervised_manifest.json")
    frozen = _json(root / "freeze_manifest.json")
    if (tuple(manifest.get("features", ())) != FEATURES
            or manifest.get("train_cutoff_exclusive") != "2026-01-01"
            or manifest.get("model_selection_uses_2026") is not False
            or frozen.get("status") != "PRE2026_ALL_CANDIDATES_FROZEN"):
        raise SelectedStrategyError("FROZEN_CONTRACT_CHANGED")
    return root


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _isolated_imports(root):
    # Original files use generic sibling names. Restore the host's import state
    # so an existing DEMO/research module called prepare is never replaced.
    missing = object()
    names = ("prepare", "risk_aux", "safe_inputs")
    original = {name: sys.modules.get(name, missing) for name in names}
    old_path = sys.path[:]
    try:
        safe = _load_module("_selected_hgb_safe_inputs", root.parent / "a2_top20_action_nn_20260925/safe_inputs.py")
        sys.modules["safe_inputs"] = safe
        sys.modules["prepare"] = _load_module("_selected_hgb_prepare", root / "prepare.py")
        sys.modules["risk_aux"] = _load_module("_selected_hgb_risk_aux", root / "risk_aux.py")
        yield
    finally:
        sys.path[:] = old_path
        for name, prior in original.items():
            if prior is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _runtime(root):
    verify_frozen(root)  # also verify a previously cached model on every call
    key = str(root)
    if key not in _RUNTIME:
        import joblib
        import numpy as np
        import pandas as pd
        with _RUNTIME_LOCK, _isolated_imports(root):
            optimizer = _load_module("_selected_hgb_optimizer", root / "optimize_route.py")
        expected_specs = {
            "HGB_DIAG_5": ("pred_hgb", "diagonal", 5.0, 0.0),
            "HGB_FACTOR_5": ("pred_hgb", "factor_shrink", 5.0, 0.0),
        }
        if (any(optimizer.SPECS[key] != spec for key, spec in expected_specs.items())
                or (optimizer.COST_ONE_WAY, optimizer.MAX_WEIGHT, optimizer.MAX_GROSS,
                    optimizer.ZERO_CUTOFF) != (0.0005, 0.10, 1.0, 0.0025)):
            raise SelectedStrategyError("ORIGINAL_POLICY_PARAMETERS_CHANGED")
        model = joblib.load(root / "models/hgb_2026092501.joblib")
        q10 = joblib.load(root / "models/q10_2026092501.joblib")
        risk = optimizer.risk_aux.load_bundle(root / "risk_artifacts/final_pre2026.joblib")
        if risk["cutoff"] != "2026-01-01":
            raise SelectedStrategyError("RISK_CUTOFF_CHANGED")
        _RUNTIME[key] = {"np": np, "pd": pd, "model": model, "q10": q10,
                         "risk": risk, "optimizer": optimizer}
    return _RUNTIME[key]


def _date(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise SelectedStrategyError("INVALID_SIGNAL_DATE")
    return date.fromisoformat(value).isoformat()


def _number(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise SelectedStrategyError("INVALID_NUMBER:" + label)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SelectedStrategyError("INVALID_NUMBER:" + label) from exc
    if (not math.isfinite(number) or (minimum is not None and number < minimum)
            or (maximum is not None and number > maximum)):
        raise SelectedStrategyError("INVALID_NUMBER:" + label)
    return number


def _ticker(value):
    if not isinstance(value, str) or not _TICKER.fullmatch(value):
        raise SelectedStrategyError("INVALID_TICKER")
    return value


def _normalise_day(day, runtime):
    pd, np = runtime["pd"], runtime["np"]
    frame = day.copy(deep=True) if isinstance(day, pd.DataFrame) else pd.DataFrame(day)
    for target, alternatives in (("signal_date", ("trade_date", "target_date")),
                                 ("raw_rank", ("rank",)), ("raw_score", ("score",))):
        if target not in frame:
            for alternative in alternatives:
                if alternative in frame:
                    frame = frame.rename(columns={alternative: target})
                    break
    if not {"signal_date", "ticker", "raw_rank", "raw_score"}.issubset(frame):
        raise SelectedStrategyError("SIGNAL_IDENTITY_COLUMNS_MISSING")
    if len(frame) != 40 or frame.ticker.nunique() != 40:
        raise SelectedStrategyError("COMPLETE_RAW_TOP40_REQUIRED")
    for value in frame.ticker:
        _ticker(value)
    try:
        frame["signal_date"] = pd.to_datetime(frame.signal_date, errors="raise").dt.normalize()
    except (ValueError, TypeError, AttributeError) as exc:
        raise SelectedStrategyError("INVALID_SIGNAL_DATE") from exc
    if frame.signal_date.isna().any() or frame.signal_date.nunique() != 1:
        raise SelectedStrategyError("SINGLE_SIGNAL_DATE_REQUIRED")
    signal = _date(frame.signal_date.iloc[0].date())
    if signal < "2026-01-01":
        raise SelectedStrategyError("FINAL_MODEL_REQUIRES_2026_OR_LATER")
    if (not np.isfinite(frame[["raw_rank", "raw_score"]].to_numpy(float)).all()
            or set(frame.raw_rank) != set(range(1, 41))):
        raise SelectedStrategyError("RAW_TOP40_RANK_OR_SCORE_INVALID")
    std = float(frame.raw_score.astype(float).std(ddof=0))
    if std <= 0:
        raise SelectedStrategyError("RAW_TOP40_SCORE_VARIANCE_ZERO")
    derived = {
        "raw_rank_strength": 1.0 - (frame.raw_rank.astype(float) - 1.0) / 39.0,
        "raw_score_z": (frame.raw_score.astype(float) - frame.raw_score.astype(float).mean()) / std,
    }
    for name, values in derived.items():
        if name in frame and not np.allclose(frame[name].to_numpy(float), values.to_numpy(float), rtol=0, atol=1e-10):
            raise SelectedStrategyError("RANK_FEATURE_COORDINATE_MISMATCH:" + name)
        frame[name] = values
    missing = sorted(set(FEATURES) - set(frame))
    if missing:
        raise SelectedStrategyError("COMPLETE_FROZEN_FEATURES_REQUIRED:" + ",".join(missing))
    if not np.isfinite(frame[list(FEATURES)].to_numpy(float)).all():
        raise SelectedStrategyError("INCOMPLETE_OR_NONFINITE_FROZEN_FEATURES")
    # Labels or an execution opening carried alongside a saved table are never
    # projected into inference or optimization.
    identity = ["signal_date", "ticker", "raw_rank", "raw_score"]
    if "security_id" in frame:
        if (frame.security_id.isna().any() or frame.security_id.astype(str).str.strip().eq("").any()
                or frame.security_id.astype(str).nunique() != 40):
            raise SelectedStrategyError("INVALID_SIGNAL_SECURITY_IDENTITY")
        identity.append("security_id")
    return frame[[*identity, *FEATURES]].sort_values("raw_rank"), signal


def _state(state, signal):
    if state is None:
        return {}, 1.0, "CASH_START", "空仓账户目标方案"
    if not isinstance(state, Mapping):
        raise SelectedStrategyError("ACCOUNT_STATE_REQUIRED")
    if (state.get("valuation_basis") != "SIGNAL_CLOSE" or _date(state.get("signal_date")) != signal
            or any(key in state for key in ("execution_open", "next_open", "open_prices", "execution_date", "future_prices"))):
        raise SelectedStrategyError("ACCOUNT_MUST_USE_SAME_SIGNAL_CLOSE")
    raw_weights = state.get("weights")
    if not isinstance(raw_weights, Mapping):
        raise SelectedStrategyError("ACCOUNT_WEIGHTS_REQUIRED")
    weights = {_ticker(ticker): _number(weight, "account_weight", minimum=0, maximum=1)
               for ticker, weight in raw_weights.items()}
    weights = {ticker: weight for ticker, weight in weights.items() if weight > 0}
    cash = _number(state.get("cash_weight"), "cash_weight", minimum=0, maximum=1)
    if not math.isclose(sum(weights.values()) + cash, 1.0, rel_tol=0, abs_tol=1e-8):
        raise SelectedStrategyError("ACCOUNT_CASH_WEIGHT_IDENTITY")
    return weights, cash, "USER_SUPPLIED_SIGNAL_CLOSE_STATE", "用户收盘账户目标方案"


def _action(target, old):
    delta = target - old
    return "BUY" if delta > 1e-10 else "SELL" if delta < -1e-10 else "HOLD"


def infer_targets(day, state=None, *, source_root=None):
    """Infer both frozen strategies from complete Raw Top40 + signal-close state.

    ``state=None`` means 100% cash. For a real account supply ``signal_date``,
    ``valuation_basis='SIGNAL_CLOSE'``, ``weights`` and ``cash_weight``. The solver
    needs actual old weights, not quantities or a following opening price.
    """
    applications, _ = _infer_with_scores(day, state, source_root=source_root)
    return applications


def _score_rows(frame, *, signal_date=None):
    """Order the existing shared prediction within its fixed Raw Top40 input."""
    if len(frame) != 40 or frame.ticker.nunique() != 40 or set(frame.raw_rank) != set(range(1, 41)):
        raise SelectedStrategyError("SHARED_SCORES_REQUIRE_RAW_TOP40")
    if "security_id" in frame and (frame.security_id.isna().any()
            or frame.security_id.astype(str).str.strip().eq("").any()
            or frame.security_id.astype(str).nunique() != 40):
        raise SelectedStrategyError("INVALID_SHARED_SCORE_SECURITY_IDENTITY")
    ordered = frame.sort_values(["pred_hgb", "ticker"], ascending=[False, True], kind="mergesort")
    rows = []
    for rank, item in enumerate(ordered.itertuples(index=False), 1):
        security = getattr(item, "security_id", None)
        row = {"ticker": _ticker(item.ticker), "security_id": str(security) if security is not None else None,
               "raw_rank": int(item.raw_rank), "raw_score": _number(item.raw_score, "raw_score"),
               "pred_hgb": _number(item.pred_hgb, "pred_hgb"), "hgb_rank": rank}
        if signal_date is not None:
            row["signal_date"] = signal_date
        rows.append(row)
    return rows


def _infer_with_scores(day, state=None, *, source_root=None):
    """Capture the same 40 predictions used by the unchanged two solves."""
    root = _source_root(source_root=source_root)
    runtime = _runtime(root)
    frame, signal = _normalise_day(day, runtime)
    weights, cash, basis, label = _state(state, signal)
    frame["pred_hgb"] = runtime["model"].predict(frame[list(FEATURES)])
    frame["pred_q10"] = runtime["q10"].predict(frame[list(FEATURES)])
    score_snapshot = {"status": "READY", "signal_date": signal, "requested_signal_date": signal,
                      "rows": _score_rows(frame), "reason": ""}
    optimizer, applications = runtime["optimizer"], {}
    for strategy_id in STRATEGY_IDS:
        # In the original solve(), quantities only identify positive holdings;
        # pre_values/nav supply the real signal-close weights. Unit NAV is exact
        # for an input already expressed as normalized account weights.
        target, diagnostic = optimizer.solve(
            frame, {ticker: 1.0 for ticker in weights}, weights, 1.0,
            runtime["risk"], optimizer.SPECS[strategy_id], runtime["pd"].Timestamp(signal),
        )
        if diagnostic["solver_failed"]:
            raise SelectedStrategyError("SOLVER_FAILED_RETAIN_ACCOUNT:" + strategy_id)
        if (any(not math.isfinite(value) or value < 0 or value > .10 + 1e-7 for value in target.values())
                or sum(target.values()) > 1.0 + 1e-7):
            raise SelectedStrategyError("TARGET_CONSTRAINT_VIOLATION:" + strategy_id)
        rows = [{"ticker": ticker, "target_weight": float(target.get(ticker, 0.0)),
                 "weight_before": float(weights.get(ticker, 0.0)),
                 "action": _action(target.get(ticker, 0.0), weights.get(ticker, 0.0))}
                for ticker in sorted(set(target) | set(weights))]
        applications[strategy_id] = {
            "status": "READY", "signal_date": signal, "account_basis": basis,
            "account_label": label, "rows": rows,
            "target_cash_weight": max(0.0, 1.0 - sum(target.values())),
            "cash_weight_before": cash, "solver_failed": False,
            "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN", "broker_action_allowed": False,
            "reason": "", "model_fit_calls": 0,
        }
    return applications, score_snapshot


def _register(refs, key, path, expected=None):
    path = Path(path).resolve()
    actual = digest(path)
    if expected is not None and actual != expected:
        raise SelectedStrategyError("SOURCE_HASH_MISMATCH:" + str(path))
    refs[key] = {"path": str(path), "sha256": actual}
    return path


def _csv_records(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        return {row["candidate"]: row for row in csv.DictReader(stream)}


def _daily_rows(ledger):
    fields = {"net_return": "net_return", "gross_return": "gross_return", "pretrade_nav": "pretrade_nav",
        "turnover": "turnover", "transaction_cost_amount": "transaction_cost_amount",
        "transaction_cost_fraction": "transaction_cost_fraction", "gross_exposure": "gross_exposure",
        "holding_count": "actual_name_count", "buy_cash_scale": "buy_cash_scale",
        "skipped_buy_count": "skipped_buy_count", "blocked_sell_count": "blocked_sell_count",
        "stale_mark_count": "stale_mark_count", "blocked_rebalance_count": "blocked_rebalance_count"}
    counts = {"holding_count", "skipped_buy_count", "blocked_sell_count", "stale_mark_count", "blocked_rebalance_count"}
    rows = []
    for item in ledger.sort_values("execution_date").to_dict("records"):
        row = {"date": _date(item["execution_date"].date()), "nav": _number(item["nav"], "nav", minimum=0),
               "cash_weight": _number(item["cash_weight"], "cash_weight", minimum=0, maximum=1)}
        for name, source in fields.items():
            value = item.get(source)
            row[name] = None if value is None else _number(value, name)
            if name in counts and value is not None:
                if row[name] < 0 or row[name] != int(row[name]):
                    raise SelectedStrategyError("INVALID_RECORDED_COUNT:" + name)
                row[name] = int(row[name])
        rows.append(row)
    return rows


def _projection(root, refs):
    import pandas as pd
    for relative, expected in REPLAY_HASHES.items():
        _register(refs, "frozen/" + relative, root / relative, expected)
    summaries = _csv_records(root / "audit_20260926/close_clock_2026_summary.csv")
    original = _csv_records(root / "test2026/summary.csv")
    strategies = {}
    period = None
    for strategy_id in ("RAW", *STRATEGY_IDS):
        prefix = "audit_20260926/" + strategy_id.lower()
        ledger = pd.read_parquet(root / (prefix + "_daily.parquet"))
        ledger = ledger.sort_values("execution_date")
        if not ledger.candidate.eq(strategy_id).all():
            raise SelectedStrategyError("REPLAY_CANDIDATE_MISMATCH:" + strategy_id)
        daily = _daily_rows(ledger)
        saved = summaries[strategy_id]
        nav = _number(saved["close_clock_nav"], "end_nav", minimum=0)
        mean_cash = _number(saved["mean_cash"], "mean_cash", minimum=0, maximum=1)
        if (len(daily) != int(saved["days"]) or not math.isclose(daily[-1]["nav"], nav, abs_tol=1e-12)
                or not math.isclose(sum(item["cash_weight"] for item in daily) / len(daily), mean_cash, abs_tol=1e-12)):
            raise SelectedStrategyError("REPLAY_SUMMARY_MISMATCH:" + strategy_id)
        targets = pd.read_parquet(root / (prefix + "_targets.parquet"))
        grouped = []
        for signal, part in targets.groupby("signal_date", sort=True):
            rows = []
            for item in part.sort_values("ticker").itertuples(index=False):
                wanted = _number(item.target_weight, "target_weight", minimum=0, maximum=.10 + 1e-7)
                old = _number(item.signal_close_weight, "weight_before", minimum=0, maximum=1)
                row = {"ticker": _ticker(item.ticker), "target_weight": wanted,
                       "weight_before": old, "action": _action(wanted, old)}
                if strategy_id != "RAW":
                    row["pre_cutoff_weight"] = _number(item.raw_target_weight, "pre_cutoff_weight", minimum=0, maximum=.10 + 1e-7)
                rows.append(row)
            if sum(item["target_weight"] for item in rows) > 1 + 1e-7:
                raise SelectedStrategyError("HISTORICAL_TARGET_GROSS_CONSTRAINT")
            grouped.append({"signal_date": _date(signal.date()), "rows": rows})
        strategies[strategy_id] = {
            "label": "Raw A2" if strategy_id == "RAW" else LABELS[strategy_id],
            "summary": {"end_nav": nav, "cumulative_return": nav - 1.0,
                        "max_drawdown": _number(saved["max_drawdown"], "drawdown", minimum=-1, maximum=0),
                        "mean_cash": mean_cash, "days": len(daily),
                        "turnover": _number(saved["turnover"], "turnover", minimum=0)},
            "daily": daily, "targets": grouped,
        }
        if strategy_id != "RAW":
            ref = original[strategy_id]
            ref_nav = _number(ref["end_nav"], "reference_nav", minimum=0)
            strategies[strategy_id]["reference_summary"] = {
                "end_nav": ref_nav, "cumulative_return": ref_nav - 1.0,
                "max_drawdown": float(ref["max_drawdown"]), "mean_cash": float(ref["mean_cash"]),
                "decision_clock": "ORIGINAL_EXECUTION_OPEN_STATE_DEFECT"}
        candidate_period = {"start": daily[0]["date"], "end": daily[-1]["date"], "days": len(daily),
                            "price_basis": "QFQ_PRICE_COORDINATE_PROXY",
                            "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"}
        if period is not None and candidate_period != period:
            raise SelectedStrategyError("REPLAY_PERIOD_MISMATCH")
        period = candidate_period
    raw_reference = strategies.pop("RAW")
    raw_reference.update(strategy_id="RAW_A2", performance_period=period.copy())
    # Only already-published inference fields are read, never outcome labels.
    saved_scores = pd.read_parquet(root / "test2026/predictions.parquet",
        columns=["signal_date", "ticker", "security_id", "raw_rank", "raw_score", "pred_hgb"])
    historical = []
    for signal, part in saved_scores.groupby("signal_date", sort=True):
        historical.extend(_score_rows(part, signal_date=_date(signal.date())))
    return strategies, raw_reference, period, historical


def _historical_day(paths, root, refs):
    """Reuse the exact saved feature projection and verify its upstream sources."""
    import pandas as pd
    import numpy as np
    import pyarrow.dataset as ds
    history = Path(_get(paths, "daily_root", r"D:\us-tech-quant-daily")) / "A2_historical_top40/runs" / HISTORICAL_RUN
    for relative, expected in HISTORY_HASHES.items():
        _register(refs, "history/" + relative, history / relative, expected)
    manifest = _json(history / "manifest.json")
    if manifest.get("outputs", {}).get("top40", {}).get("sha256") != HISTORY_HASHES["top40.parquet"]:
        raise SelectedStrategyError("HISTORICAL_TOP40_BINDING_MISMATCH")
    saved = pd.read_parquet(root / "test2026/predictions.parquet",
        columns=["signal_date", "ticker", "security_id", "raw_rank", "raw_score", *FEATURES])
    finite = pd.Series(np.isfinite(saved[list(FEATURES)].to_numpy(float)).all(axis=1), index=saved.index)
    complete = finite.groupby(saved.signal_date).all() & saved.groupby("signal_date").size().eq(40)
    available = complete.loc[complete].index
    if available.empty:
        raise SelectedStrategyError("NO_COMPLETE_HISTORICAL_FROZEN_SIGNAL")
    latest = available.max()
    day = saved.loc[saved.signal_date.eq(latest), ["signal_date", "ticker", "security_id", "raw_rank", "raw_score", *FEATURES]].copy()
    rank = ds.dataset(history / "top40.parquet", format="parquet").to_table(
        columns=["ticker", "rank", "score", "model_year", "model_sha256"],
        filter=ds.field("target_date") == latest.strftime("%Y-%m-%d"),
    ).to_pandas()
    features = ds.dataset(history / "inference_features.parquet", format="parquet").to_table(
        columns=["ticker", *BASE_FEATURES], filter=ds.field("trade_date") == latest.to_pydatetime(),
    ).to_pandas()
    merged = day.merge(rank, on="ticker", validate="one_to_one").merge(features, on="ticker", validate="one_to_one", suffixes=("", "_source"))
    if (len(merged) != 40 or not merged.model_year.eq(2026).all()
            or not merged.model_sha256.eq(A2_MODEL_SHA256).all()
            or not merged.raw_rank.eq(merged["rank"]).all()
            or not merged.raw_score.eq(merged["score"]).all()
            or any(not merged[name].eq(merged[name + "_source"]).all() for name in BASE_FEATURES)):
        raise SelectedStrategyError("SAVED_FEATURE_UPSTREAM_MISMATCH")
    return day


def _current_day(paths, current_report_path, refs):
    import pandas as pd
    path = Path(current_report_path) if current_report_path is not None else Path(_get(paths, "daily_root", r"D:\us-tech-quant-daily")) / "A2_today_recommendation/latest.json"
    if not path.is_file():
        return None, None, "CURRENT_RECOMMENDATION_MISSING"
    _register(refs, "current/report.json", path)
    report = _json(path)
    requested = _date(report.get("data_date"))
    if (report.get("status") != "READY" or report.get("model_id") != "A2_HGB"
            or report.get("model_sha256") != A2_MODEL_SHA256):
        raise SelectedStrategyError("CURRENT_RECOMMENDATION_NOT_FROZEN_READY_A2")
    for key in ("selected_hgb_original_report", "original_report"):
        ref = report.get(key)
        if isinstance(ref, Mapping):
            _register(refs, "current/original_report.json", ref["path"], ref["sha256"])
    binding = report.get("selected_hgb_features")
    if binding is None:
        return None, requested, "CURRENT_FROZEN_FEATURE_SNAPSHOT_MISSING"
    if not isinstance(binding, Mapping):
        raise SelectedStrategyError("CURRENT_FEATURE_BINDING_INVALID")
    feature_date = binding.get("signal_date", binding.get("date", binding.get("data_date")))
    if _date(feature_date) != requested:
        raise SelectedStrategyError("CURRENT_FEATURE_SNAPSHOT_DATE_MISMATCH")
    snapshot = _register(refs, "current/selected_hgb_features.parquet", binding["path"], binding["sha256"])
    frame = pd.read_parquet(snapshot)
    if "signal_date" not in frame:
        if "trade_date" in frame:
            frame = frame.rename(columns={"trade_date": "signal_date"})
        elif "target_date" in frame:
            frame = frame.rename(columns={"target_date": "signal_date"})
        else:
            raise SelectedStrategyError("CURRENT_FEATURE_SIGNAL_DATE_MISSING")
    if not pd.to_datetime(frame.signal_date).dt.strftime("%Y-%m-%d").eq(requested).all():
        raise SelectedStrategyError("CURRENT_FEATURE_ROWS_DATE_MISMATCH")
    # Rank/score may be attached by the recommendation producer, or joined from
    # that same report. They never come from a later historical signal.
    records = report.get("ranked_rows", report.get("rows", []))
    ranking = pd.DataFrame([{ "ticker": row["ticker"], "security_id": row.get("security_id"),
                             "raw_rank": row["rank"], "raw_score": row["score"]}
                            for row in records if int(row["rank"]) <= 40])
    if len(ranking) != 40 or ranking.ticker.nunique() != 40:
        raise SelectedStrategyError("CURRENT_RECOMMENDATION_COMPLETE_TOP40_REQUIRED")
    for target, alternative in (("raw_rank", "rank"), ("raw_score", "score")):
        if target not in frame and alternative in frame:
            frame = frame.rename(columns={alternative: target})
    if "raw_rank" not in frame or "raw_score" not in frame:
        frame = frame.drop(columns=[name for name in ("raw_rank", "raw_score") if name in frame]).merge(
            ranking[["ticker", "raw_rank", "raw_score"]], on="ticker", validate="one_to_one")
    else:
        comparison = frame.merge(ranking, on="ticker", validate="one_to_one", suffixes=("", "_report"))
        if (len(comparison) != 40 or not comparison.raw_rank.eq(comparison.raw_rank_report).all()
                or not comparison.raw_score.eq(comparison.raw_score_report).all()):
            raise SelectedStrategyError("CURRENT_FEATURE_RANKING_MISMATCH")
    if "security_id" not in frame:
        frame = frame.merge(ranking[["ticker", "security_id"]], on="ticker", validate="one_to_one")
    elif ranking.security_id.notna().all():
        identity = frame.merge(ranking[["ticker", "security_id"]], on="ticker", validate="one_to_one", suffixes=("", "_report"))
        if not identity.security_id.astype(str).eq(identity.security_id_report.astype(str)).all():
            raise SelectedStrategyError("CURRENT_FEATURE_SECURITY_IDENTITY_MISMATCH")
    if (frame.security_id.isna().any() or frame.security_id.astype(str).str.strip().eq("").any()
            or frame.security_id.astype(str).nunique() != 40):
        raise SelectedStrategyError("CURRENT_FEATURE_SECURITY_IDENTITY_REQUIRED")
    return frame, requested, ""


def _blocked(reason, requested=None):
    return {"status": "BLOCKED", "signal_date": None, "requested_signal_date": requested,
            "account_basis": "CASH_START", "account_label": "空仓账户目标方案", "rows": [],
            "target_cash_weight": None, "reason": reason, "broker_action_allowed": False,
            "model_fit_calls": 0, "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"}


def _snapshot_hash(snapshot):
    # Origin/timestamp identify the import, not the date's immutable decision.
    core = {key: value for key, value in snapshot.items()
            if key not in ("snapshot_sha256", "origin_package_sha256", "generated_at")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_snapshot(snapshot):
    """Validate a captured cash-start decision without inference or execution."""
    if (set(snapshot) != {"schema_version", "selection_basis", "signal_date", "generated_at", "origin_package_sha256",
                         "shared_scores", "applications", "source_refs", "source_hashes",
                         "observation_only_source_refs", "report_binding", "snapshot_sha256"}
            or snapshot.get("schema_version") != 1 or snapshot.get("selection_basis") != SELECTION_BASIS
            or snapshot.get("snapshot_sha256") != _snapshot_hash(snapshot)):
        raise SelectedStrategyError("HISTORY_SNAPSHOT_HASH_OR_IDENTITY_INVALID")
    signal = _date(snapshot.get("signal_date"))
    scores = snapshot["shared_scores"]
    if (set(scores) != {"model_id", "model_sha256", "scoring_scope", "ranking_basis", "rows"}
            or scores.get("model_id") != "HGB_2026092501"
            or scores.get("model_sha256") != FROZEN_HASHES["models/hgb_2026092501.joblib"]
            or scores.get("scoring_scope") != "RAW_TOP40"
            or scores.get("ranking_basis") != "PRED_HGB_DESC_TICKER_ASC"):
        raise SelectedStrategyError("HISTORY_FROZEN_MODEL_IDENTITY_INVALID")
    rows = scores.get("rows")
    keys = {"ticker", "security_id", "raw_rank", "raw_score", "pred_hgb", "hgb_rank"}
    if (not isinstance(rows, list) or len(rows) != 40 or any(set(row) != keys for row in rows)
            or len({_ticker(row["ticker"]) for row in rows}) != 40
            or len({row["security_id"] for row in rows}) != 40
            or any(not isinstance(row["security_id"], str) or not row["security_id"].strip() for row in rows)
            or any(type(row["raw_rank"]) is not int for row in rows)
            or {row["raw_rank"] for row in rows} != set(range(1, 41))):
        raise SelectedStrategyError("HISTORY_COMPLETE_SHARED_TOP40_REQUIRED")
    for rank, row in enumerate(sorted(rows, key=lambda item: (-_number(item["pred_hgb"], "pred_hgb"), item["ticker"])), 1):
        _number(row["raw_score"], "raw_score")
        if type(row["hgb_rank"]) is not int or row["hgb_rank"] != rank:
            raise SelectedStrategyError("HISTORY_SHARED_MODEL_RANK_MISMATCH")
    refs, hashes = snapshot["source_refs"], snapshot["source_hashes"]
    if set(refs) != set(hashes):
        raise SelectedStrategyError("HISTORY_SOURCE_BINDING_MISMATCH")
    observed = snapshot.get("observation_only_source_refs", [])
    if (not isinstance(observed, list) or len(observed) != len(set(observed))
            or set(observed) - {"current/report.json", "current/original_report.json"}):
        raise SelectedStrategyError("HISTORY_OBSERVATION_SOURCE_INVALID")
    for name, ref in refs.items():
        if (not isinstance(ref.get("path"), str) or not ref["path"] or ref.get("sha256") != hashes[name]
                or not re.fullmatch(r"[0-9a-f]{64}", hashes[name])):
            raise SelectedStrategyError("HISTORY_SOURCE_BINDING_MISMATCH")
        if name in observed:
            if Path(ref["path"]).name.lower() != "latest.json":
                raise SelectedStrategyError("HISTORY_OBSERVATION_SOURCE_INVALID")
        else:
            _verify(ref["path"], ref["sha256"])
    for relative, expected in FROZEN_HASHES.items():
        if hashes.get("frozen/" + relative) != expected:
            raise SelectedStrategyError("HISTORY_FROZEN_SOURCE_REQUIRED:" + relative)
    for name in ("current/report.json", "current/selected_hgb_features.parquet"):
        if name not in refs:
            raise SelectedStrategyError("HISTORY_CURRENT_SOURCE_REQUIRED:" + name)
    binding = snapshot["report_binding"]
    if (binding.get("data_date") != signal or binding.get("status") != "READY"
            or binding.get("model_id") != "A2_HGB" or binding.get("model_sha256") != A2_MODEL_SHA256
            or binding.get("selected_hgb_features") != refs["current/selected_hgb_features.parquet"]
            or binding.get("raw_top40") != [{key: row[key] for key in ("ticker", "security_id", "raw_rank", "raw_score")}
                for row in sorted(rows, key=lambda item: item["raw_rank"])]):
        raise SelectedStrategyError("HISTORY_REPORT_SCORE_BINDING_MISMATCH")
    if set(snapshot.get("applications", {})) != set(STRATEGY_IDS):
        raise SelectedStrategyError("HISTORY_STRATEGY_IDENTITY_INVALID")
    eligible = {row["ticker"] for row in rows if row["raw_rank"] <= 20}
    for app in snapshot["applications"].values():
        if (app.get("status") != "READY" or app.get("signal_date") != signal
                or app.get("requested_signal_date") != signal or app.get("account_basis") != "CASH_START"
                or app.get("execution_status") != "TARGET_ONLY" or app.get("kind") != "ARCHIVED_CASH_START_TARGET"
                or app.get("decision_clock") != "SIGNAL_CLOSE_NEXT_SESSION_OPEN"
                or app.get("cash_weight_before") != 1.0 or app.get("broker_action_allowed") is not False
                or app.get("model_fit_calls") != 0 or not isinstance(app.get("rows"), list)):
            raise SelectedStrategyError("HISTORY_CASH_START_TARGET_REQUIRED")
        seen, total = set(), 0.0
        for row in app["rows"]:
            ticker = _ticker(row["ticker"])
            weight = _number(row["target_weight"], "target_weight")
            if (set(row) != {"ticker", "target_weight", "weight_before", "action"}
                    or ticker in seen or ticker not in eligible or not 0 <= weight <= .10 + 1e-7
                    or row["weight_before"] != 0 or row["action"] != _action(weight, 0)):
                raise SelectedStrategyError("HISTORY_CASH_START_WEIGHT_INVALID")
            seen.add(ticker)
            total += weight
        cash = _number(app["target_cash_weight"], "target_cash_weight")
        if not 0 <= cash <= 1 or not math.isclose(total + cash, 1., abs_tol=1e-7):
            raise SelectedStrategyError("HISTORY_CASH_START_CASH_IDENTITY")
    return snapshot


def _capture_snapshot(package, origin_sha, report_binding=None):
    scores = package.get("shared_scores", {})
    current = scores.get("current", {})
    signal = _date(current.get("signal_date"))
    if (current.get("status") != "READY" or current.get("requested_signal_date") != signal
            or package.get("selection_basis") != SELECTION_BASIS
            or package.get("model_fit_calls") != 0 or package.get("broker_action_allowed") is not False):
        raise SelectedStrategyError("HISTORY_CURRENT_READY_CASH_START_REQUIRED")
    refs = {key: dict(ref) for key, ref in package.get("source_refs", {}).items()
            if key.startswith(("frozen/", "current/"))}
    hashes = package.get("source_hashes", {})
    for name, ref in refs.items():
        if ref.get("sha256") != hashes.get(name):
            raise SelectedStrategyError("HISTORY_SOURCE_BINDING_MISMATCH")
    report_ref = refs.get("current/report.json")
    if report_ref is None:
        raise SelectedStrategyError("HISTORY_CURRENT_SOURCE_REQUIRED:current/report.json")
    if report_binding is None:
        report = _json(_verify(report_ref["path"], report_ref["sha256"]))
        feature = report.get("selected_hgb_features", {})
        if _date(feature.get("signal_date", feature.get("date", feature.get("data_date")))) != signal:
            raise SelectedStrategyError("HISTORY_FEATURE_DATE_MISMATCH")
        top40 = [{"ticker": row["ticker"], "security_id": row.get("security_id"),
                  "raw_rank": row["rank"], "raw_score": row["score"]}
                 for row in report.get("ranked_rows", report.get("rows", [])) if int(row["rank"]) <= 40]
        report_binding = {"status": report.get("status"), "data_date": report.get("data_date"),
            "model_id": report.get("model_id"), "model_sha256": report.get("model_sha256"),
            "selected_hgb_features": {"path": feature.get("path"), "sha256": feature.get("sha256")},
            "raw_top40": sorted(top40, key=lambda row: row["raw_rank"])}
    applications = {}
    for sid in STRATEGY_IDS:
        original = package["strategies"][sid]["application"]
        applications[sid] = {key: original.get(key) for key in (
            "status", "signal_date", "requested_signal_date", "account_basis", "rows", "target_cash_weight",
            "cash_weight_before", "decision_clock", "broker_action_allowed", "model_fit_calls")}
        applications[sid].update(execution_status="TARGET_ONLY", kind="ARCHIVED_CASH_START_TARGET",
            reason="", account_label="空仓账户目标方案")
    snapshot = {"schema_version": 1, "selection_basis": SELECTION_BASIS, "signal_date": signal,
        "generated_at": package.get("generated_at"), "origin_package_sha256": origin_sha,
        "shared_scores": {**{key: scores.get(key) for key in ("model_id", "model_sha256", "scoring_scope", "ranking_basis")},
                          "rows": current["rows"]},
        "applications": applications, "source_refs": refs,
        "source_hashes": {key: hashes[key] for key in refs},
        "observation_only_source_refs": [key for key, ref in refs.items()
            if key in ("current/report.json", "current/original_report.json") and Path(ref["path"]).name.lower() == "latest.json"],
        "report_binding": report_binding}
    snapshot["snapshot_sha256"] = _snapshot_hash(snapshot)
    return _validate_snapshot(snapshot)


def _history_key(day):
    return "history/" + day + ".json"


def _repair_key(day):
    return "history_revision/" + day + ".json"


def _ref_identity(ref):
    return Path(ref["path"]).resolve(), ref["sha256"]


def _validate_input_repair(snapshot, previous, repair_ref):
    if (not isinstance(repair_ref, Mapping) or set(repair_ref) != {"path", "sha256"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(repair_ref.get("sha256", "")))):
        raise SelectedStrategyError("HISTORY_INPUT_REPAIR_REFERENCE_REQUIRED")
    audit = _json(_verify(repair_ref["path"], repair_ref["sha256"]))
    new_ref = snapshot["source_refs"]["current/report.json"]
    old_ref = previous["source_refs"]["current/report.json"]
    report = _json(_verify(new_ref["path"], new_ref["sha256"]))
    bound = report.get("repair_lineage") or {}
    if (set(bound) != {"path", "sha256"} or _ref_identity(bound) != _ref_identity(repair_ref)
            or audit.get("status") != "INPUTS_VERIFIED"
            or audit.get("target_date") != snapshot["signal_date"]
            or audit.get("run_id") != report.get("run_id") or not audit.get("run_id")
            or audit.get("model_fit_count") != 0 or audit.get("parameter_search_count") != 0
            or any(audit.get(key) is not True for key in (
                "old_date_keys_retained", "old_rows_unchanged", "unrelated_current_keys_unchanged"))
            or not isinstance(audit.get("reason"), str) or not audit["reason"]
            or not any(_ref_identity(ref) == _ref_identity(old_ref) for ref in audit.get("parent_inputs", []))):
        raise SelectedStrategyError("HISTORY_INPUT_REPAIR_LINEAGE_INVALID")
    names = ("current/report.json", "current/selected_hgb_features.parquet")
    if all(_ref_identity(snapshot["source_refs"][name]) == _ref_identity(previous["source_refs"][name])
           for name in names):
        raise SelectedStrategyError("HISTORY_SAME_SOURCE_REPAIR_FORBIDDEN")
    return audit


def _revision_selection(owner, folder, day):
    refs, hashes = owner.get("source_refs", {}), owner.get("source_hashes", {})
    key = _history_key(day)
    if key not in refs:
        path = folder / (day + ".json")
        return path, digest(path) if path.exists() else None, None
    ref = refs[key]
    if ref.get("sha256") != hashes.get(key):
        raise SelectedStrategyError("HISTORY_SOURCE_BINDING_MISMATCH")
    path = _verify(ref["path"], ref["sha256"]).resolve()
    base = (folder / (day + ".json")).resolve()
    if path == base:
        return path, ref["sha256"], None
    snapshot = _validate_snapshot(_json(path))
    expected = (folder / "revisions" / day / (snapshot["snapshot_sha256"] + ".json")).resolve()
    receipt_key = _repair_key(day)
    receipt_ref = refs.get(receipt_key, {})
    if (path != expected or snapshot["signal_date"] != day
            or receipt_ref.get("sha256") != hashes.get(receipt_key)):
        raise SelectedStrategyError("HISTORY_REVISION_SELECTION_INVALID")
    receipt_path = _verify(receipt_ref["path"], receipt_ref["sha256"]).resolve()
    if receipt_path != expected.with_suffix(".receipt.json"):
        raise SelectedStrategyError("HISTORY_REVISION_RECEIPT_PATH_INVALID")
    receipt = _json(receipt_path)
    if (set(receipt) != {"schema_version", "kind", "signal_date", "supersedes", "replacement", "repair_lineage"}
            or receipt["schema_version"] != 1 or receipt["kind"] != "INPUT_REPAIR"
            or receipt["signal_date"] != day or _ref_identity(receipt["replacement"]) != _ref_identity(ref)):
        raise SelectedStrategyError("HISTORY_REVISION_RECEIPT_INVALID")
    old_path = _verify(receipt["supersedes"]["path"], receipt["supersedes"]["sha256"]).resolve()
    if old_path != base and not old_path.is_relative_to((folder / "revisions" / day).resolve()):
        raise SelectedStrategyError("HISTORY_REVISION_PARENT_PATH_INVALID")
    old = _validate_snapshot(_json(old_path))
    if old["signal_date"] != day:
        raise SelectedStrategyError("HISTORY_REVISION_PARENT_DATE_INVALID")
    _validate_input_repair(snapshot, old, receipt["repair_lineage"])
    return path, ref["sha256"], receipt_ref


def _write_immutable_json(value, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _json(path) != value:
            raise SelectedStrategyError("HISTORY_IMMUTABLE_FILE_CONFLICT:" + path.name)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _json(path) != value:
                raise SelectedStrategyError("HISTORY_IMMUTABLE_FILE_CONFLICT:" + path.name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def archive_current_snapshot(package_or_path, history_root, expected_sha256=None, *, snapshot_repair=None):
    """Archive a date immutably; explicit hash-bound input repairs create versions."""
    if isinstance(package_or_path, Mapping):
        package = package_or_path
        origin = hashlib.sha256(json.dumps(package, sort_keys=True, allow_nan=False).encode()).hexdigest()
    else:
        source = _verify(package_or_path, expected_sha256)
        package, origin = _json(source), expected_sha256
    folder = Path(history_root).expanduser().resolve()
    if package.get("source_root") and folder.is_relative_to(Path(package["source_root"]).resolve()):
        raise SelectedStrategyError("OUTPUT_MUST_NOT_MUTATE_FROZEN_SOURCE")
    signal = _date(package.get("shared_scores", {}).get("current", {}).get("signal_date"))
    path, expected, receipt_ref = _revision_selection(package, folder, signal)
    previous = _validate_snapshot(_json(_verify(path, expected))) if path.exists() else None
    snapshot = _capture_snapshot(package, origin,
        previous["report_binding"] if previous and snapshot_repair is None else None)
    if previous and previous["snapshot_sha256"] != snapshot["snapshot_sha256"]:
        if snapshot_repair is None:
            raise SelectedStrategyError("HISTORY_SAME_DATE_CONFLICT:" + signal)
        _validate_input_repair(snapshot, previous, snapshot_repair)
        old_ref = {"path": str(path), "sha256": digest(path)}
        path = folder / "revisions" / signal / (snapshot["snapshot_sha256"] + ".json")
        # Origin/timestamp are observation metadata: a repeat must retain the
        # first immutable bytes while comparing the complete decision hash.
        if path.exists():
            stored = _validate_snapshot(_json(path))
            if stored["snapshot_sha256"] != snapshot["snapshot_sha256"]:
                raise SelectedStrategyError("HISTORY_SAME_DATE_CONFLICT:" + signal)
        else:
            _write_immutable_json(snapshot, path)
        replacement = {"path": str(path), "sha256": digest(path)}
        receipt_path = path.with_suffix(".receipt.json")
        receipt = {"schema_version": 1, "kind": "INPUT_REPAIR", "signal_date": signal,
            "supersedes": old_ref, "replacement": replacement, "repair_lineage": dict(snapshot_repair)}
        _write_immutable_json(receipt, receipt_path)
        receipt_ref = {"path": str(receipt_path), "sha256": digest(receipt_path)}
    elif previous is None:
        _write_immutable_json(snapshot, path)
    result = {"path": str(path), "sha256": digest(path), "signal_date": signal}
    if receipt_ref is not None:
        result["revision_receipt"] = dict(receipt_ref)
    return result


def _bind_archive(package, ref):
    day = ref["signal_date"]
    key, receipt_key = _history_key(day), _repair_key(day)
    package["source_refs"][key] = {name: ref[name] for name in ("path", "sha256")}
    package["source_hashes"][key] = ref["sha256"]
    if "revision_receipt" in ref:
        package["source_refs"][receipt_key] = dict(ref["revision_receipt"])
        package["source_hashes"][receipt_key] = ref["revision_receipt"]["sha256"]
    else:
        package["source_refs"].pop(receipt_key, None)
        package["source_hashes"].pop(receipt_key, None)


def _merge_archived_snapshots(package, history_root, previous=None):
    scores = package.get("shared_scores")
    if not scores:
        return package  # backwards-compatible minimal publishers
    folder = Path(history_root).expanduser().resolve()
    if isinstance(previous, (str, os.PathLike)):
        previous = _json(previous)
    elif previous is None and (folder.parent / "latest.json").is_file():
        # build_package(output_path=None) must inherit the canonical selection
        # before it adds historical scores, rather than first taking old bases.
        previous = _json(folder.parent / "latest.json")
    current = scores["current"]
    cutoff = current.get("requested_signal_date") or current.get("signal_date")
    if not cutoff:
        return package
    cutoff = _date(cutoff)
    grouped = {}
    for row in scores["historical"]:
        grouped.setdefault(row["signal_date"], []).append(row)
    refs, hashes = package["source_refs"], package["source_hashes"]
    old_hashes = (previous or {}).get("source_hashes", {})
    applications = {sid: {} for sid in STRATEGY_IDS}
    for path in sorted(Path(history_root).glob("????-??-??.json")):
        day = _date(path.stem)
        if day >= cutoff:
            continue
        key = "history/" + path.name
        owner = previous if key in (previous or {}).get("source_refs", {}) else package
        path, expected, receipt_ref = _revision_selection(owner, folder, day)
        if expected:
            _verify(path, expected)
        snapshot = _validate_snapshot(_json(path))
        if snapshot["signal_date"] != day:
            raise SelectedStrategyError("HISTORY_FILENAME_DATE_MISMATCH")
        archived = [{**row, "signal_date": day} for row in snapshot["shared_scores"]["rows"]]
        if day in grouped and sorted(grouped[day], key=lambda r: r["ticker"]) != sorted(archived, key=lambda r: r["ticker"]):
            raise SelectedStrategyError("HISTORY_SHARED_SCORE_DATE_CONFLICT:" + day)
        grouped[day] = archived
        _register(refs, key, path, expected)
        hashes[key] = refs[key]["sha256"]
        if receipt_ref is not None:
            refs[_repair_key(day)] = dict(receipt_ref)
            hashes[_repair_key(day)] = receipt_ref["sha256"]
        for sid in STRATEGY_IDS:
            applications[sid][day] = {**snapshot["applications"][sid], "source_ref": key}
    scores["historical"] = [row for day in sorted(grouped) for row in grouped[day]]
    for sid in STRATEGY_IDS:
        package["strategies"][sid]["application_history"] = [applications[sid][day] for day in sorted(applications[sid])]
    return package


def build_package(paths, current_report_path=None, output_path=None, progress=None):
    """Project repaired ledgers and actually infer today's cash-start targets.

    No backtest is rerun. Missing/unverified current features produce an explicit
    latest-available signal or a blocked application, never fabricated lags.
    Frozen hash changes reject the entire build before loading model bytes.
    """
    root = verify_frozen(_source_root(paths))
    refs = {}
    for relative, expected in FROZEN_HASHES.items():
        _register(refs, "frozen/" + relative, root / relative, expected)
    if progress:
        progress("读取已修复时钟的三策略同批次历史账本与共享评分")
    strategies, raw_reference, period, historical_scores = _projection(root, refs)
    requested, applications, note = None, None, ""
    current_scores = None
    try:
        day, requested, note = _current_day(paths, current_report_path, refs)
        if day is not None:
            applications, current_scores = _infer_with_scores(day, source_root=root)
            if any(item["signal_date"] != requested for item in applications.values()):
                raise SelectedStrategyError("CURRENT_APPLICATION_SIGNAL_DATE_MISMATCH")
        else:
            day = _historical_day(paths, root, refs)
            applications, current_scores = _infer_with_scores(day, source_root=root)
            for application in applications.values():
                application["status"] = "LATEST_AVAILABLE_SIGNAL"
                application["reason"] = note + ";LATEST_COMPLETE_VERIFIED_HISTORICAL_FEATURES"
    except (SelectedStrategyError, FileNotFoundError, KeyError, ValueError, TypeError) as exc:
        note = str(exc)
        if requested is None and "current/report.json" in refs:
            # Preserve the attempted observation date even when later feature
            # validation fails. Recheck the captured report bytes before use.
            reference = refs["current/report.json"]
            try:
                report_path = _verify(reference["path"], reference["sha256"])
                requested = _date(_json(report_path).get("data_date"))
            except (SelectedStrategyError, OSError, KeyError, ValueError, TypeError):
                pass
        # A malformed/hash-mismatched current snapshot is explicitly blocked.
        # Fallback is only for a missing snapshot, never for failed integrity.
        applications = {key: _blocked(note, requested) for key in STRATEGY_IDS}
        current_scores = {"status": "BLOCKED", "signal_date": None,
                          "requested_signal_date": requested, "rows": [], "reason": note}
    current_scores["requested_signal_date"] = requested
    if note and current_scores["status"] == "READY":
        current_scores["reason"] = note
    for strategy_id in STRATEGY_IDS:
        applications[strategy_id]["requested_signal_date"] = requested
        strategies[strategy_id]["application"] = applications[strategy_id]
    package = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_basis": SELECTION_BASIS, "performance_period": period,
        "strategies": strategies, "source_hashes": {key: value["sha256"] for key, value in refs.items()},
        "raw_reference": raw_reference,
        "shared_scores": {"model_id": "HGB_2026092501",
            "model_sha256": FROZEN_HASHES.get("models/hgb_2026092501.joblib"),
            "scoring_scope": "RAW_TOP40", "ranking_basis": "PRED_HGB_DESC_TICKER_ASC",
            "historical": historical_scores, "current": current_scores},
        "source_refs": refs, "limitations": LIMITATIONS[:], "model_fit_calls": 0,
        "broker_action_allowed": False, "source_root": str(root),
    }
    if progress:
        states = ", ".join(f"{key}: {value['status']} {value['signal_date'] or ''}" for key, value in applications.items())
        progress("冻结推理完成：" + states)
    if output_path is not None:
        publish(package, output_path)
    else:
        _merge_archived_snapshots(package, Path(_get(paths, "daily_root", r"D:\us-tech-quant-daily")) / "A2_selected_hgb/history")
    return package


def publish(package, output_path, *, snapshot_repair=None):
    """Atomically publish a completed JSON package, with no model mutation."""
    if (package.get("schema_version") != 1 or package.get("selection_basis") != SELECTION_BASIS
            or set(package.get("strategies", {})) != set(STRATEGY_IDS)):
        raise SelectedStrategyError("PACKAGE_IDENTITY_INVALID")
    path = Path(output_path).expanduser().resolve()
    if package.get("source_root") and path.is_relative_to(Path(package["source_root"]).resolve()):
        raise SelectedStrategyError("OUTPUT_MUST_NOT_MUTATE_FROZEN_SOURCE")
    if any(path == Path(ref["path"]).resolve() for ref in package.get("source_refs", {}).values()):
        raise SelectedStrategyError("OUTPUT_MUST_NOT_MUTATE_INPUT_SOURCE")
    path.parent.mkdir(parents=True, exist_ok=True)
    history = path.parent / "history"
    previous = _json(path) if path.is_file() else None
    if previous and previous.get("shared_scores", {}).get("current", {}).get("status") == "READY":
        if all(previous["strategies"][sid]["application"].get("status") == "READY" for sid in STRATEGY_IDS):
            prior_ref = archive_current_snapshot(previous, history)
            # The published selection wins over any stale caller-supplied ref.
            if previous["shared_scores"]["current"].get("signal_date") == package.get("shared_scores", {}).get("current", {}).get("signal_date"):
                _bind_archive(package, prior_ref)
    if package.get("shared_scores", {}).get("current", {}).get("status") == "READY":
        if all(package["strategies"][sid]["application"].get("status") == "READY" for sid in STRATEGY_IDS):
            current_ref = archive_current_snapshot(package, history, snapshot_repair=snapshot_repair)
            _bind_archive(package, current_ref)
    _merge_archived_snapshots(package, history, previous)
    encoded = json.dumps(package, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def refresh_selected_strategies(paths, current_report_path=None, output_path=None, progress=None):
    output = output_path or os.environ.get("USTQ_SELECTED_HGB_PACKAGE") or Path(_get(paths, "daily_root", r"D:\us-tech-quant-daily")) / "A2_selected_hgb/latest.json"
    return build_package(paths, current_report_path, output, progress)


def complete_close_inputs(prices, lineage, tickers, target, sessions):
    """Read verified native/expanded closes absent from today's main price frame.

    All raw/rehab references come from the completed current input lineage. An
    unsupported bridge or incomplete real session history blocks the HGB signal;
    this helper never fills a date or writes a provider artifact.
    """
    import pandas as pd
    from scripts import daily_recommendation_prices as price_api
    from scripts.research.a2.inference.historical_top40_prices import _append_raw, _merge_raw
    target = _date(target)
    needed = [_date(day) for day in sessions if _date(day) <= target][-121:]
    if len(needed) != 121 or needed[-1] != target or needed != sorted(set(needed)):
        raise SelectedStrategyError("SELECTED_HGB_CLOSE_SESSION_CONTRACT")
    wanted = {_ticker(ticker) for ticker in tickers}
    present = set(prices.ticker) if not prices.empty else set()
    missing = wanted - present
    if not missing:
        return prices
    selected_lineage = [row for row in lineage if row["ticker"] in missing]
    if len(selected_lineage) != len(missing) or {row["ticker"] for row in selected_lineage} != missing:
        raise SelectedStrategyError("SELECTED_HGB_MISSING_CLOSE_LINEAGE")
    coverage = _json(price_api.verify(price_api.COVERAGE_PATH, price_api.COVERAGE_SHA))
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
            "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    adapter = price_api._adapter(target)
    added = []
    for saved in selected_lineage:
        ticker, code = saved["ticker"], saved["code"]
        parts = []
        for ref in saved["raw_sources"]:
            path = price_api.verify(ref["path"], ref["sha256"])
            frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
            if "code" in frame:
                frame = frame.loc[frame.code.astype(str).eq(code)]
            if "ticker" in frame:
                frame = frame.loc[frame.ticker.astype(str).eq(ticker)]
            parts.append(price_api._raw_frame(frame, code))
        raw = _merge_raw(parts)
        raw = raw.loc[raw.trade_date.le(pd.Timestamp(target))]
        if raw.empty or raw.trade_date.min().strftime("%Y-%m-%d") != saved["anchor_date"]:
            raise SelectedStrategyError("SELECTED_HGB_CLOSE_ANCHOR_MISMATCH:" + ticker)
        bridge = saved.get("alternate_bridge")
        if bridge is not None:
            if (not isinstance(bridge, Mapping) or bridge.get("provider") != "MASSIVE_GROUPED"
                    or bridge.get("qualification") != "UNADJUSTED_RAW_WITH_FIVE_SESSION_MOOMOO_OVERLAP"
                    or bridge.get("provider_symbol") != ticker or bridge.get("transport_alias_proof") is not None
                    or bridge.get("tail_end") != target):
                raise SelectedStrategyError("SELECTED_HGB_MISSING_CLOSE_BRIDGE_UNSUPPORTED:" + ticker)
            from scripts.storage.storage_r2a import DataStore
            # Rebuild an immutable reader record from this day's saved proof,
            # rather than selecting a possibly newer mutable catalog pointer.
            # The existing parser rechecks every raw response/checkpoint, exact
            # normalized value, five-session overlap and whole-share volume rule.
            record = {"dataset": "prices_daily_massive", "ticker": ticker,
                "source": "MASSIVE_GROUPED", "adjustment": "raw", "format": "parquet",
                "path": bridge["normalized_path"], "source_sha256": bridge["normalized_sha256"],
                "max_date": target, "lineage": {"schema_version": 1,
                    "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": "MASSIVE_GROUPED",
                    "date_column": "date", "price_basis": "RAW", "currency": "USD",
                    "exchange_timezone": "America/New_York",
                    "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
                    "provider_symbol": bridge["provider_symbol"],
                    "provider_mapping": bridge["provider_mapping"], "inputs": bridge["raw_inputs"]}}
            raw_dates = set(raw.trade_date)
            gaps = [day for day in needed if raw.trade_date.min() <= pd.Timestamp(day) <= raw.trade_date.max()
                    and pd.Timestamp(day) not in raw_dates]
            options = {"gap_dates": gaps} if gaps else {}
            tail, checked = price_api._qualified_massive_tail(record, raw, ticker, target, DataStore(), **options)
            if checked != bridge:
                raise SelectedStrategyError("SELECTED_HGB_CLOSE_BRIDGE_PROOF_MISMATCH:" + ticker)
            raw = _append_raw(raw, tail, pd.to_datetime(sessions))
        ref = saved["rehab"]
        factors = pd.read_parquet(price_api.verify(ref["path"], ref["sha256"]))
        if not factors.empty and not factors.code.eq(code).all():
            raise SelectedStrategyError("SELECTED_HGB_CLOSE_REHAB_IDENTITY:" + ticker)
        adjusted, _ = adapter.adjusted_price_frame(code, ticker, raw, factors, wolf)
        selected = adjusted.loc[adjusted.trade_date.dt.strftime("%Y-%m-%d").isin(needed),
                                ["ticker", "trade_date", "close", "volume"]]
        if (len(selected) != 121 or selected.trade_date.dt.strftime("%Y-%m-%d").tolist() != needed
                or selected.close.isna().any() or not selected.close.gt(0).all()):
            raise SelectedStrategyError("SELECTED_HGB_CLOSE_CONTIGUITY_INCOMPLETE:" + ticker)
        added.append(selected)
    return pd.concat([prices, *added], ignore_index=True)
