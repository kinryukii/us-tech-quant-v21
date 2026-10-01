"""Fixed saved-score mapping; no estimator, score threshold or parameter search."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ENGINE_ROOT = Path(__file__).resolve().parent.parent / "a2_buy_sell_cash_multimodel_20260928"
sys.path.insert(0, str(ENGINE_ROOT))

import numpy as np
import pandas as pd
from engine_v2 import HoldingAwareDecision


class OriginalA2ScorePolicy:
    """TOP20 saved OOF, explicit zeros, 4.75% cap, only downward budget scaling."""

    def __init__(self, scores):
        required = {"signal_date", "ticker", "a2_prediction"}
        if not required.issubset(scores.columns):
            raise ValueError(f"SCORE_FIELDS_MISSING:{sorted(required-set(scores.columns))}")
        data = scores[list(sorted(required))].copy()
        data["signal_date"] = pd.to_datetime(data.signal_date)
        if data.duplicated(["signal_date", "ticker"]).any():
            raise ValueError("DUPLICATE_SAVED_OOF_KEY")
        if not np.isfinite(data.a2_prediction.to_numpy(float)).all():
            raise ValueError("NONFINITE_SAVED_OOF_SCORE")
        if not data.ticker.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError("INVALID_SAVED_OOF_TICKER")
        self.bydate = {date: frame.set_index("ticker").a2_prediction.to_dict()
                       for date, frame in data.groupby("signal_date", sort=False)}
        self.calls = 0
        self.score_rows_consumed = 0

    def __call__(self, day, ctx):
        names = list(day.ticker)
        if len(names) != len(set(names)):
            raise ValueError("DUPLICATE_DECISION_DAY_KEY")
        if set(names) != set(ctx.decision_tickers):
            raise ValueError("DECISION_DAY_CONTEXT_MISMATCH")
        saved = self.bydate.get(pd.Timestamp(ctx.signal_date), {})
        missing = sorted(set(names) - set(saved))
        if missing:
            raise ValueError(f"SAVED_OOF_MISSING:{ctx.signal_date}:{missing}")
        ordered = sorted(names, key=lambda ticker: (-saved[ticker], ticker))
        count = min(20, ctx.available_slots, len(ordered))
        weight = min(.0475, max(0., ctx.available_weight) / count) if count else 0.
        chosen = set(ordered[:count])
        decisions = {ticker: weight if ticker in chosen else 0. for ticker in names}
        rank = {ticker: position for position, ticker in enumerate(ordered, 1)}
        raw = {ticker: {"saved_a2_oof_score": float(saved[ticker]), "decision_pool_rank": rank[ticker],
                        "selected_before_execution_gate": ticker in chosen,
                        "fixed_single_name_cap": .0475, "mapped_weight": decisions[ticker]}
               for ticker in names}
        self.calls += 1
        self.score_rows_consumed += len(names)
        return HoldingAwareDecision(model_decisions=decisions, raw_model_outputs=raw)
