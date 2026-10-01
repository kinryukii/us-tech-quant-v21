"""Signal-close decisions and next-open accounting for this isolated experiment."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
FEE = 0.0005  # Original R0F: 5 bps on each one-sided traded notional.
UPPER = 0.10


def project_capped_simplex(action: np.ndarray) -> np.ndarray:
    """Euclidean projection onto 20 stock caps plus a cash coordinate."""
    z = np.asarray(action, dtype=float)
    if z.shape != (21,) or not np.isfinite(z).all():
        raise ValueError("INVALID_21_ACTION")
    upper = np.r_[np.full(20, UPPER), 1.0]
    lo, hi = float(np.min(z - upper)), float(np.max(z))
    for _ in range(80):
        mid = (lo + hi) / 2
        if np.clip(z - mid, 0, upper).sum() > 1:
            lo = mid
        else:
            hi = mid
    out = np.clip(z - (lo + hi) / 2, 0, upper)
    if abs(out.sum() - 1) > 1e-10:
        raise ArithmeticError("PROJECTION_SUM")
    return out


def qp_target(mu: np.ndarray, sigma: np.ndarray, w_signal: np.ndarray,
              downside: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    mu = np.asarray(mu, float)
    sig = np.asarray(sigma, float)
    prev = np.asarray(w_signal, float)
    assert mu.shape == (20,) and sig.shape == (20, 20) and prev.shape == (20,)
    assert np.isfinite(mu).all() and np.isfinite(sig).all() and np.isfinite(prev).all()
    risk = (sig + sig.T) / 2
    penalty = np.zeros(20) if downside is None else .10 * np.maximum(-np.asarray(downside, float), 0)
    # 20 auxiliary coordinates express absolute target turnover with linear constraints.
    x0 = np.r_[np.minimum(np.maximum(prev, 0), UPPER), np.zeros(20)]
    x0[20:] = np.abs(x0[:20] - prev)
    bounds = [(0, UPPER)] * 20 + [(0, None)] * 20

    def fun(x):
        w, u = x[:20], x[20:]
        return -float((mu - penalty) @ w) + 2.5 * float(w @ risk @ w) + FEE * float(u.sum())

    def jac(x):
        return np.r_[-mu + penalty + 5.0 * risk @ x[:20], np.full(20, FEE)]

    constraints = [
        {"type": "ineq", "fun": lambda x: 1 - x[:20].sum(),
         "jac": lambda x: np.r_[-np.ones(20), np.zeros(20)]},
        {"type": "ineq", "fun": lambda x: x[20:] - x[:20] + prev,
         "jac": lambda x: np.c_[-np.eye(20), np.eye(20)]},
        {"type": "ineq", "fun": lambda x: x[20:] + x[:20] - prev,
         "jac": lambda x: np.c_[np.eye(20), np.eye(20)]},
    ]
    res = minimize(fun, x0, jac=jac, bounds=bounds, constraints=constraints,
                   method="SLSQP", options={"ftol": 1e-10, "maxiter": 200})
    w = np.clip(res.x[:20], 0, UPPER)
    feasible = bool(res.success and np.isfinite(w).all() and w.sum() <= 1 + 1e-7
                    and np.max(np.abs(res.x[20:]) - (res.x[20:])) <= 1e-7)
    if not feasible:
        return np.full(20, .05), {"solver_success": False, "message": str(res.message)}
    return w, {"solver_success": True, "message": str(res.message),
               "estimated_in_list_cost_fraction": float(FEE * np.abs(w - prev).sum())}


class PriceStore:
    def __init__(self, prices: pd.DataFrame):
        p = prices.copy()
        p["trade_date"] = pd.to_datetime(p.trade_date)
        self.close = p.set_index(["trade_date", "ticker"]).close.to_dict()
        self.open = p.set_index(["trade_date", "ticker"]).open.to_dict()


class Account:
    """One policy's own shares and cash; no opening price is exposed at decision time."""
    def __init__(self, prices: pd.DataFrame | PriceStore):
        store = prices if isinstance(prices, PriceStore) else PriceStore(prices)
        self.close = store.close
        self.open = store.open
        self.shares: dict[str, float] = {}
        self.cash = 1.0
        self.last_mark = 1.0
        self.fees = 0.0
        self.turnover = 0.0

    def _price(self, field: dict, date: pd.Timestamp, ticker: str) -> float:
        try:
            value = float(field[(pd.Timestamp(date), ticker)])
        except KeyError as exc:
            raise RuntimeError(f"MISSING_PRICE:{date.date()}:{ticker}") from exc
        if not np.isfinite(value) or value <= 0:
            raise RuntimeError(f"INVALID_PRICE:{date.date()}:{ticker}")
        return value

    def signal_state(self, date: pd.Timestamp, tickers: list[str]) -> dict:
        held_value = {t: q * self._price(self.close, date, t)
                      for t, q in self.shares.items() if q > 1e-14}
        nav = self.cash + sum(held_value.values())
        if nav <= 0:
            raise RuntimeError("NONPOSITIVE_NAV")
        weights = np.array([held_value.get(t, 0) / nav for t in tickers])
        out = float(sum(v for t, v in held_value.items() if t not in set(tickers)) / nav)
        return {"nav": nav, "weights": weights, "cash_weight": self.cash / nav,
                "out_of_list_weight": out, "held_values": held_value}

    def execute(self, signal_date: pd.Timestamp, execution_date: pd.Timestamp,
                tickers: list[str], weights: np.ndarray) -> dict:
        w = np.asarray(weights, float)
        if w.shape != (20,) or np.any(w < -1e-9) or np.any(w > UPPER + 1e-9) or w.sum() > 1 + 1e-9:
            raise RuntimeError("INVALID_TARGET")
        price = {t: self._price(self.open, execution_date, t)
                 for t in set(self.shares) | set(tickers)}
        pre = self.cash + sum(q * price[t] for t, q in self.shares.items())
        desired = {t: float(v * pre) for t, v in zip(tickers, w)}
        sell = {t: max(0., q * price[t] - desired.get(t, 0.)) for t, q in self.shares.items()}
        sell = {t: v for t, v in sell.items() if v > 1e-14}
        before = self.shares.copy()
        for t, amount in sell.items():
            self.shares[t] -= amount / price[t]
            if self.shares[t] <= 1e-14:
                del self.shares[t]
        cash_after_sells = self.cash + sum(sell.values())
        sell_fee = FEE * sum(sell.values())
        remaining = {t: q * price[t] for t, q in self.shares.items()}
        buy = {t: max(0., desired.get(t, 0.) - remaining.get(t, 0.)) for t in tickers}
        need = sum(buy.values()) * (1 + FEE)
        scale = min(1., max(0., cash_after_sells - sell_fee) / need) if need else 1.
        buy = {t: v * scale for t, v in buy.items() if v * scale > 1e-14}
        for t, amount in buy.items():
            self.shares[t] = self.shares.get(t, 0.) + amount / price[t]
        fee = sell_fee + FEE * sum(buy.values())
        self.cash = cash_after_sells - sum(buy.values()) - fee
        if self.cash < -1e-10:
            raise RuntimeError("NEGATIVE_CASH")
        self.cash = max(0., self.cash)
        nav = self.cash + sum(q * price[t] for t, q in self.shares.items())
        if abs(nav - (pre - fee)) > 1e-10:
            raise RuntimeError("ACCOUNT_IDENTITY")
        traded = sum(sell.values()) + sum(buy.values())
        self.fees += fee
        self.turnover += traded / pre
        trades = ([{"ticker": t, "side": "SELL", "quantity": v / price[t], "notional": v}
                   for t, v in sell.items()] +
                  [{"ticker": t, "side": "BUY", "quantity": v / price[t], "notional": v}
                   for t, v in buy.items()])
        return {"signal_date": str(signal_date.date()), "execution_date": str(execution_date.date()),
                "pretrade_nav": pre, "net_nav": nav, "cash": self.cash,
                "fee": fee, "traded_notional": traded, "trades": trades,
                "shares_before": before, "shares_after": self.shares.copy()}

    def liquidate(self, date: pd.Timestamp) -> dict:
        tickers = list(self.shares)
        price = {t: self._price(self.open, date, t) for t in tickers}
        pre = self.cash + sum(self.shares[t] * price[t] for t in tickers)
        sold = sum(self.shares[t] * price[t] for t in tickers)
        fee = FEE * sold
        self.cash = pre - fee
        self.shares = {}
        self.fees += fee
        self.turnover += sold / pre if pre else 0.
        return {"execution_date": str(date.date()), "pretrade_nav": pre,
                "net_nav": self.cash, "cash": self.cash, "fee": fee,
                "traded_notional": sold}


def selected_prediction(fold: str, family: str) -> pd.DataFrame:
    selection = json.loads((HERE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"]
    from fit_supervised import model_key
    prediction_dir = HERE / ("final_insample_predictions" if fold == "FINAL" else "predictions")
    cfg = selection[family]
    if family == "MLP":
        cfg = {"hidden": tuple(cfg["hidden"])} if fold in ("D1", "D2") else cfg
        pieces = [pd.read_parquet(prediction_dir / f"{model_key(fold, family, cfg, seed=s)}.parquet")
                  for s in (11, 29, 47)]
        result = pieces[0].drop(columns=["model_key"]).copy()
        result["prediction"] = np.mean([p.prediction.to_numpy(float) for p in pieces], axis=0)
        return result
    if family == "QUANTILE":
        pieces = [pd.read_parquet(prediction_dir / f"{model_key(fold, family, cfg, quantile=q)}.parquet")
                  for q in (.1, .5, .9)]
        result = pieces[0].drop(columns=["prediction", "model_key"]).copy()
        for q, part in zip((10, 50, 90), pieces):
            result[f"q{q}"] = part.prediction.to_numpy(float)
        return result
    return pd.read_parquet(prediction_dir / f"{model_key(fold, family, cfg)}.parquet")
