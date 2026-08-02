"""Development-only nested chronological splitter with 24-hour purge/embargo."""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from ..common.contracts import ContractViolation, assert_confirmation_forbidden


@dataclass(frozen=True)
class Fold:
    train_index: list[int]
    test_index: list[int]
    test_start: object
    test_end: object


class NestedPurgedWalkForward:
    def __init__(self, purge_minutes: int = 1440, embargo_minutes: int = 1440, confirmation_start_et: str = "2025-02-08T00:00:00-05:00"):
        self.purge_minutes = purge_minutes
        self.embargo_minutes = embargo_minutes
        self.confirmation_start_et = confirmation_start_et

    def split_outer(self, events: pd.DataFrame, n_splits: int = 3):
        x = events.copy()
        x["decision_timestamp_et"] = pd.to_datetime(x.decision_timestamp_et)
        assert_confirmation_forbidden(x.decision_timestamp_et, self.confirmation_start_et)
        x = x.sort_values("decision_timestamp_et", kind="mergesort").reset_index().rename(columns={"index": "source_index"})
        blocks = [x.iloc[index].copy() for index in __import__("numpy").array_split(__import__("numpy").arange(len(x)), n_splits + 1) if len(index)]
        for block_no in range(1, len(blocks)):
            test = blocks[block_no]
            test_start, test_end = test.decision_timestamp_et.min(), test.decision_timestamp_et.max()
            train = x.iloc[:test.index.min()].copy()
            label_end = pd.to_datetime(train.get("label_end_timestamp_et", train.decision_timestamp_et + pd.Timedelta(minutes=self.purge_minutes)))
            allowed = label_end < test_start - pd.Timedelta(minutes=self.embargo_minutes)
            yield Fold(train.loc[allowed, "source_index"].astype(int).tolist(), test.source_index.astype(int).tolist(), test_start, test_end)

    def inner_splits(self, outer_train: pd.DataFrame, n_splits: int = 2):
        yield from self.split_outer(outer_train, n_splits=n_splits)

    def fit_scaler_train_only(self, scaler, x_train, x_test):
        scaler.fit(x_train)
        return scaler.transform(x_train), scaler.transform(x_test)

    def assert_development_only(self, events: pd.DataFrame) -> None:
        assert_confirmation_forbidden(events.decision_timestamp_et, self.confirmation_start_et)
        if "split" in events and events.split.astype(str).str.contains("CONFIRM", case=False).any():
            raise ContractViolation("CONFIRMATION_PATH_FORBIDDEN")
