"""Run fixed D1/D2 paths only; no V25 or 2026 result is read here."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from policy_engine import Account, PriceStore, HERE, qp_target, selected_prediction

FOLDS = {"D1": ("2024-01-01", "2024-06-30"),
         "D2": ("2024-07-01", "2024-12-31"),
         "V25": ("2025-01-01", "2025-12-31"),
         "FINAL": ("2023-01-03", "2025-12-31")}
FAMILIES = {"P1": "RIDGE", "P2": "ELASTIC", "P3": "LOGISTIC",
            "P4": "HGB", "P5": "MLP", "P6": "HGB_NO13F",
            "P7": "HGB", "P8": "HGB", "P9": "HGB"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prediction_map(fold: str) -> dict:
    maps = {}
    selection = json.loads((HERE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"]
    from fit_supervised import model_key
    for family in ("RIDGE", "ELASTIC", "LOGISTIC", "HGB", "MLP", "HGB_NO13F", "QUANTILE"):
        p = selected_prediction(fold, family)
        if family == "LOGISTIC":
            meta = json.loads((HERE / "models" / f"{model_key(fold, family, selection[family])}.json").read_text(encoding="utf-8"))
            p["prediction"] = (p.prediction * meta["m_positive_decimal"] +
                               (1 - p.prediction) * meta["m_nonpositive_decimal"])
        maps[family] = p.set_index(["signal_date", "experiment_security_key"])
    return maps


def risk_matrix(fold: str, name: str, keys: list[str], sigma20: np.ndarray) -> tuple[np.ndarray, bool]:
    if name == "DIAG":
        return np.diag(sigma20**2), False
    artifact = joblib.load(HERE / "models" / f"{name}_{fold}.joblib")
    known = {str(k): i for i, k in enumerate(artifact["security_keys"])}
    if any(str(k) not in known for k in keys):
        return np.diag(sigma20**2), True
    indices = [known[str(k)] for k in keys]
    corr = artifact["correlation"][np.ix_(indices, indices)]
    return sigma20[:, None] * corr * sigma20[None, :], False


def run_fold(fold: str) -> None:
    if fold in ("V25", "FINAL") and not (HERE / "PRIMARY_SELECTION.json").exists():
        raise RuntimeError("PRIMARY_SELECTION_REQUIRED_BEFORE_V25_OR_FINAL")
    prefix = f"DEVELOPMENT_{fold}" if fold in ("D1", "D2") else "V25" if fold == "V25" else "FINAL_INSAMPLE"
    out = HERE / f"{prefix}_POLICY_DAILY.parquet"
    if out.exists():
        raise RuntimeError(f"DEV_PATH_ALREADY_EXISTS:{out}")
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["execution_date"] = pd.to_datetime(panel.execution_date)
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    start, end = FOLDS[fold]
    # End-of-fold labels must mature inside that fold, even for B0 paths.
    use = panel.signal_date.between(start, end) & panel.label_end_date.le(pd.Timestamp(end))
    section = panel.loc[use].sort_values(["signal_date", "raw_a2_rank"])
    assert section.groupby("signal_date").size().eq(20).all()
    predictions = prediction_map(fold)
    price = pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet")
    store = PriceStore(price)
    accounts = {name: Account(store) for name in ("B0", *FAMILIES)}
    daily = []
    weights_rows = []
    trades_rows = []
    fallback = {name: 0 for name in FAMILIES}
    risk_fallback = {"P7": 0, "P8": 0}
    solver_count = 0
    solver_failed = 0
    groups = list(section.groupby("signal_date", sort=True))
    for day, block in groups:
        tickers = block.ticker.astype(str).tolist()
        keys = block.experiment_security_key.astype(str).tolist()
        assert len(set(keys)) == 20 and len(set(tickers)) == 20
        qualified = bool(block.base_usable_day.all())
        sigma20 = np.exp(block.log_sigma20.to_numpy(float)) if qualified else None
        execution = pd.Timestamp(block.execution_date.iloc[0])
        for policy, account in accounts.items():
            state = account.signal_state(day, tickers)
            desired = np.full(20, .05)
            why = "B0" if policy == "B0" else ""
            if policy != "B0" and not qualified:
                fallback[policy] += 1
                why = "BASE_INPUT_FALLBACK"
            elif policy != "B0":
                family = FAMILIES[policy]
                try:
                    p = predictions[family].loc[[(day, key) for key in keys]]
                    mu = p.prediction.to_numpy(float)
                    if not np.isfinite(mu).all():
                        raise RuntimeError("NONFINITE_PREDICTION")
                    risk_kind = "LW" if policy == "P7" else "PCA" if policy == "P8" else "DIAG"
                    risk, used_fallback = risk_matrix(fold, risk_kind, keys, sigma20)
                    if used_fallback:
                        risk_fallback[policy] += 1
                        why = "RISK_TO_DIAG"
                    q10 = None
                    if policy == "P9":
                        q = predictions["QUANTILE"].loc[[(day, key) for key in keys]]
                        q10 = np.sort(q[["q10", "q50", "q90"]].to_numpy(float), axis=1)[:, 0]
                    desired, status = qp_target(mu, risk, state["weights"], q10)
                    solver_count += 1
                    if not status["solver_success"]:
                        solver_failed += 1
                        fallback[policy] += 1
                        why = "QP_TO_B0"
                except KeyError as exc:
                    raise RuntimeError(f"MISSING_FROZEN_PREDICTION:{fold}:{day.date()}:{family}") from exc
            transaction = account.execute(day, execution, tickers, desired)
            daily.append({"fold": fold, "policy": policy, "signal_date": day,
                          "execution_date": execution, "qualification": qualified,
                          "fallback": why, "net_nav_at_execution": transaction["net_nav"],
                          "cash_at_execution": transaction["cash"],
                          "fee": transaction["fee"], "traded_notional": transaction["traded_notional"],
                          "stock_target_sum": float(desired.sum()),
                          "signal_close_nav": state["nav"]})
            for i, (key, ticker) in enumerate(zip(keys, tickers)):
                weights_rows.append({"fold": fold, "policy": policy, "signal_date": day,
                                     "ticker": ticker, "security_key": key,
                                     "signal_weight": state["weights"][i],
                                     "target_weight": desired[i], "target_over_5pct": desired[i] / .05,
                                     "cash_target": 1 - desired.sum()})
            for trade in transaction["trades"]:
                trades_rows.append({"fold": fold, "policy": policy, "signal_date": day,
                                    "execution_date": execution, **trade})
    # Original two-session endpoint: liquidate at last signal's following rebalance open.
    terminal = pd.Timestamp(groups[-1][1].label_end_date.iloc[0])
    for policy, account in accounts.items():
        end = account.liquidate(terminal)
        daily.append({"fold": fold, "policy": policy, "signal_date": pd.NaT,
                      "execution_date": terminal, "qualification": False,
                      "fallback": "TERMINAL_LIQUIDATION", "net_nav_at_execution": end["net_nav"],
                      "cash_at_execution": end["cash"], "fee": end["fee"],
                      "traded_notional": end["traded_notional"],
                      "stock_target_sum": 0., "signal_close_nav": np.nan})
    pd.DataFrame(daily).to_parquet(out, index=False)
    pd.DataFrame(weights_rows).to_parquet(HERE / f"{prefix}_WEIGHTS.parquet", index=False)
    pd.DataFrame(trades_rows).to_parquet(HERE / f"{prefix}_TRADES.parquet", index=False)
    report = {"fold": fold, "scientific_status": "FINAL_FITTED_IN_NOT_OOF" if fold == "FINAL" else "HISTORICAL_VALIDATION",
              "signal_days": len(groups), "usable_days": int(section.groupby("signal_date").base_usable_day.first().sum()),
              "solver_calls": solver_count, "solver_failed": solver_failed,
              "input_fallback_days": fallback, "risk_fallback_days": risk_fallback,
              "terminal_date": str(terminal.date()),
              "source_panel_sha256": digest(HERE / "PRE2026_SHARED_PANEL.parquet"),
              "terminal_nav": {policy: account.cash for policy, account in accounts.items()}}
    (HERE / f"{prefix}_POLICY_MANIFEST.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fold", choices=["D1", "D2", "V25", "FINAL"])
    run_fold(parser.parse_args().fold)
