"""Consensus eligibility adapter over the single frozen pre-2026 input owners.

Only selected columns are scanned. Labels are projected after signal/maturity
predicates; selectors and model scores never enter the 32-feature representation.
Historical quote publication/revision remains UNKNOWN under the human-authorized
frozen-history mechanism scope. This module does not grant fit or test access.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.research.a2.training.stateful_inputs import FEATURES, ALLOWED_SOURCES, SOURCES
from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.data.full_selector_inputs import SOURCES as C_SOURCES, CLOCKS

BOUNDARY = pd.Timestamp("2026-01-01")
PRIMARY_META = ["signal_date", "ticker", "cusip", "feature_available", "feature_source",
                "label_available", "account_event_unhandled", "label_mature_date", "label_coordinate"]
PRED_META = ["signal_date", "ticker", "feature_available", "feature_source"]


def annual_fold(calendar, year):
    if year not in (2021, 2022, 2023, 2024, 2025, 2026):
        raise ValueError("YEAR_OUTSIDE_FROZEN_PLAN")
    cutoff = pd.Timestamp(f"{year}-01-01")
    if cutoff > BOUNDARY:
        raise ValueError("FIT_CUTOFF_CROSSES_PRE2026")
    prior = pd.DatetimeIndex(calendar)[pd.DatetimeIndex(calendar) < cutoff]
    if len(prior) < 60:
        raise ValueError("CALIBRATION_REQUIRES_60_PRIOR_SESSIONS")
    return dict(year=year, cutoff_exclusive=cutoff, calibration_start=prior[-60],
                calibration_sessions=prior[-60:])


def mature_keys(frame, fold, stage, horizon=5):
    """Metadata eligibility first: every target clock precedes its fit cutoff."""
    if stage not in ("train", "calibration") or horizon not in (3, 5, 10, 20):
        raise ValueError("UNPLANNED_STAGE_OR_HORIZON")
    x = frame.copy()
    x["signal_date"] = pd.to_datetime(x.signal_date)
    x["label_mature_date"] = pd.to_datetime(x.label_mature_date)
    cutoff = fold["calibration_start"] if stage == "train" else fold["cutoff_exclusive"]
    ok = x.feature_available.eq(True) & x.label_available.eq(True)
    ok &= x.account_event_unhandled.eq(False) & x.feature_source.isin(ALLOWED_SOURCES)
    ok &= x.signal_date.lt(cutoff) & x.label_mature_date.lt(cutoff)
    if stage == "calibration":
        ok &= x.signal_date.isin(fold["calibration_sessions"])
    if horizon != 5:
        clock = "target_end_date_" + str(horizon) + "d"
        x[clock] = pd.to_datetime(x[clock])
        ok &= x[clock].lt(cutoff) & x[clock].gt(x.signal_date)
    result = x.loc[ok].copy()
    if result.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("AMBIGUOUS_CONSENSUS_TRAINING_KEYS")
    return result.sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)


def exact_key_filters(keys, entity, common=()):
    """Arrow DNF binds each entity to its already-qualified dates before values."""
    if keys.empty:
        raise ValueError("EMPTY_EXACT_KEYS_MUST_NOT_SCAN")
    return [[(entity, "==", value), ("signal_date", "in", sorted(set(group.signal_date))), *common]
            for value, group in keys.groupby(entity, sort=True)]


class ConsensusInputs:
    def __init__(self, run, membership_path):
        self.run = Path(run).resolve()
        binding_path = self.run / "derived/PHYSICAL_SOURCE_BINDING.json"
        self.binding = json.loads(binding_path.read_text(encoding="utf-8"))
        self.records = self.binding["records"]
        if self.binding["source_policy"] != "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY":
            raise ValueError("UNAUTHORIZED_SOURCE_SCOPE")
        self.membership_path = Path(membership_path).resolve()
        if not self.membership_path.is_relative_to(self.run / "derived"):
            raise ValueError("MEMBERSHIP_MUST_BE_THIS_MANAGED_DERIVED_INPUT")
        self.membership_sha256 = sha256(self.membership_path)
        mpf, _ = guard_parquet(self.membership_path, self.membership_sha256, ["signal_date"])
        self.membership = mpf.read().to_pandas()
        self.membership["signal_date"] = pd.to_datetime(self.membership.signal_date)
        if self.membership.duplicated(["signal_date", "cusip"]).any():
            raise ValueError("AMBIGUOUS_POOL_UID")
        # Hash/footer receipts must exist for every source before any projection.
        for name, ref in self.records.items():
            p = Path(ref["path"]); st = p.stat()
            if {"size":st.st_size,"mtime_ns":st.st_mtime_ns} != ref["file_fingerprint"]:
                raise ValueError("BOUND_SOURCE_CHANGED:" + name)
        self.calendar = pd.DatetimeIndex(pd.to_datetime(self._vectors("calendar", ["trade_date"], []).trade_date))
        if self.calendar.has_duplicates or not self.calendar.is_monotonic_increasing or (self.calendar >= BOUNDARY).any():
            raise ValueError("INVALID_PRE2026_CALENDAR")
        meta = self._vectors("value_training_panel", PRIMARY_META, [])
        meta.signal_date = pd.to_datetime(meta.signal_date)
        meta.label_mature_date = pd.to_datetime(meta.label_mature_date)
        meta.cusip = meta.cusip.astype(str).str.upper().str.strip()
        m = self.membership[["signal_date", "cusip"]].copy()
        m.cusip = m.cusip.astype(str).str.upper().str.strip()
        if meta.duplicated(["signal_date", "cusip"]).any():
            raise ValueError("AMBIGUOUS_SOURCE_UID_HISTORY")
        self.train_flags = m.merge(meta, on=["signal_date", "cusip"], how="left", validate="one_to_one")
        hmeta = self._vectors("multi_horizon_labels", ["signal_date", "security_uid", *CLOCKS], [])
        hmeta.signal_date = pd.to_datetime(hmeta.signal_date)
        hmeta["cusip"] = hmeta.security_uid.astype(str).str.removeprefix("CUSIP:")
        if hmeta.duplicated(["signal_date", "cusip"]).any():
            raise ValueError("AMBIGUOUS_HORIZON_UID")
        self.train_flags = self.train_flags.merge(hmeta.drop(columns="security_uid"), on=["signal_date", "cusip"], how="left", validate="one_to_one")
        self.pred_flags = self._vectors("prediction_feature_panel", PRED_META, [])
        self.pred_flags.signal_date = pd.to_datetime(self.pred_flags.signal_date)
        if self.pred_flags.duplicated(["signal_date", "ticker"]).any():
            raise ValueError("AMBIGUOUS_PREDICTION_KEY")
        if "ticker" not in self.membership:
            raise ValueError("HISTORICAL_IDENTITY_JOIN_REQUIRED")
        known = self.membership.loc[self.membership.ticker.notna(), ["signal_date", "ticker"]]
        self.first_pool_date = known.groupby("ticker").signal_date.min()

    def _vectors(self, name, columns, filters):
        ref = self.records[name]; p = Path(ref["path"]); st = p.stat()
        if {"size":st.st_size,"mtime_ns":st.st_mtime_ns} != ref["file_fingerprint"]:
            raise ValueError("FROZEN_SOURCE_CHANGED_BEFORE_SCAN:" + name)
        if any(c in columns for c in ("raw_a2_prediction", "raw_a2_rank", "a1_raw_score")):
            raise ValueError("MODEL_SCORE_IS_NOT_A_FEATURE")
        # Mandatory predicates precede projection, including clock metadata.
        # A 2025 signal with a 2026-mature target cannot expose that target clock.
        mandatory = [("trade_date", "<", BOUNDARY)] if name in ("calendar", "raw_market_prices") else [("signal_date", "<", BOUNDARY)]
        if name == "value_training_panel":
            mandatory.append(("label_mature_date", "<", BOUNDARY))
        if name == "multi_horizon_labels":
            mandatory.append(("target_end_date_20d", "<", BOUNDARY))
        if filters and isinstance(filters[0], list):
            bounded = [[*branch, *mandatory] for branch in filters]
        else:
            bounded = [*filters, *mandatory]
        f = pq.read_table(p, columns=list(columns), filters=bounded).to_pandas()
        after = p.stat()
        if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("FROZEN_SOURCE_CHANGED_DURING_SCAN")
        return f

    def annual_fold(self, year):
        return annual_fold(self.calendar, year)

    def read_training_fold(self, year, horizon=5):
        fold = self.annual_fold(year); outputs = []
        for stage in ("train", "calibration"):
            keys = mature_keys(self.train_flags, fold, stage, horizon)
            if len(keys) < 2:
                raise ValueError("INSUFFICIENT_LEGAL_CONSENSUS_ROWS")
            cutoff = fold["calibration_start"] if stage == "train" else fold["cutoff_exclusive"]
            common = [("signal_date", "<", cutoff),
                       ("label_mature_date", "<", cutoff),
                       ("feature_available", "==", True), ("label_available", "==", True),
                       ("account_event_unhandled", "==", False), ("feature_source", "in", list(ALLOWED_SOURCES))]
            cols = ["signal_date", "ticker", "y_open5", *FEATURES]
            vectors = self._vectors("value_training_panel", cols, exact_key_filters(keys, "ticker", common))
            vectors.signal_date = pd.to_datetime(vectors.signal_date)
            legal = keys.merge(vectors, on=["signal_date", "ticker"], how="left", validate="one_to_one")
            if horizon != 5:
                clock = "target_end_date_" + str(horizon) + "d"
                label = "ER_" + str(horizon) + "D"
                hkeys = keys.assign(security_uid="CUSIP:" + keys.cusip.astype(str))
                h = self._vectors("multi_horizon_labels", ["signal_date", "security_uid", label],
                                  exact_key_filters(hkeys, "security_uid", [(clock, "<", cutoff)]))
                h.signal_date = pd.to_datetime(h.signal_date)
                h["cusip"] = h.security_uid.astype(str).str.removeprefix("CUSIP:")
                legal = legal.merge(h.drop(columns="security_uid"), on=["signal_date", "cusip"], how="left", validate="one_to_one")
                legal["target"] = legal[label]
            else:
                legal["target"] = legal.y_open5
            if not np.isfinite(legal[[*FEATURES, "target", "y_open5"]].to_numpy(float)).all():
                raise ValueError("NONFINITE_QUALIFIED_INPUTS_NO_SILENT_LABEL_FILTER")
            outputs.append(legal)
        return outputs

    def prediction_keys(self, year):
        start = pd.Timestamp(f"{year}-01-01"); stop = min(pd.Timestamp(f"{year+1}-01-01"), BOUNDARY)
        if start >= BOUNDARY:
            raise ValueError("2026_PREDICTION_REQUIRES_SEPARATE_FROZEN_TEST_READER")
        p = self.pred_flags.loc[self.pred_flags.signal_date.between(start, stop, inclusive="left")].copy()
        first = p.ticker.map(self.first_pool_date)
        p = p.loc[first.notna() & p.signal_date.ge(first)].copy()
        return p.sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)

    def read_prediction_year(self, year):
        keys = self.prediction_keys(year)
        legal = keys.loc[keys.feature_available.eq(True) & keys.feature_source.isin(ALLOWED_SOURCES)].copy()
        if legal.empty:
            return legal.reindex(columns=[*legal.columns, *FEATURES])
        vectors = self._vectors("prediction_feature_panel", ["signal_date", "ticker", *FEATURES],
                                exact_key_filters(legal, "ticker", [
                                 ("feature_available", "==", True), ("feature_source", "in", list(ALLOWED_SOURCES))]))
        vectors.signal_date = pd.to_datetime(vectors.signal_date)
        return legal.merge(vectors, on=["signal_date", "ticker"], how="left", validate="one_to_one")
