"""Pinned frozen-history return reader for mechanism research, never strict PIT.

Reuses the existing immutable feature producer, pre2026 parquet guard and UID
panel qualifier. Declared observation clocks permit chronology within one frozen
snapshot; they do not prove historical publication, vintage or revision.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.training import selector_risk_preflight as preflight
from scripts.research.a2.training.selector_risk_features import UNIT

SCHEMA = "C_FROZEN_HISTORY_SOURCE_AUTHORITY_V1"
RESEARCH_ID = "V24_C_SELECTOR_FROZEN_HISTORY_MONTHLY_RISK_R4"
POLICY_CLOCK = "DECLARED_NY_1600_OBSERVATION_CLOCK_NOT_HISTORICAL_AVAILABLE_AT"
IDENTITY_BASIS = "OBSERVED_CUSIP_CONTIGUOUS_MEMBERSHIP_SEGMENT_NOT_ECONOMIC_CONTINUITY"
COORDINATE = "DIMENSIONLESS_FRACTIONAL_PIT_FORWARD_REHAB_INDEX_PROXY"
PROJECTIONS = {"features": ["signal_date", "ticker", "ret_1d"],
               "members": ["signal_date", "ticker", "cusip"]}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _source_files(inputs):
    """Hash and complete physical pre2026 boundary BEFORE any projected body."""
    files, metadata = {}, {}
    for kind, columns in PROJECTIONS.items():
        pin = inputs[kind]
        file, proof = guard_parquet(pin["path"], pin["sha256"], ["signal_date"])
        if not set(columns).issubset(file.schema_arrow.names):
            raise ValueError("FROZEN_HISTORY_REQUIRED_PROJECTION_MISSING")
        index = file.schema_arrow.names.index("signal_date")
        for group in range(file.num_row_groups):
            stat = file.metadata.row_group(group).column(index).statistics
            if stat.null_count != 0:
                raise ValueError("FROZEN_HISTORY_DATE_NULL_BOUNDARY_UNPROVED")
            for value in (stat.min, stat.max):
                day = pd.Timestamp(value)
                if day.tzinfo is not None or day != day.normalize():
                    raise ValueError("FROZEN_HISTORY_DATE_UNIT_INVALID")
        files[kind], metadata[kind] = file, {**proof, "projection_columns": columns}
    return files, metadata


def build_source_contract(inputs, *, research_id, human_authorization_ref):
    """Prepare the human-authorized snapshot contract; no fit/outcome reads.

    A caller must bind this actual object into its new research identity and
    formal freeze. This function does not grant a registry or execution PASS.
    """
    if research_id != RESEARCH_ID or not isinstance(human_authorization_ref, dict):
        raise ValueError("FROZEN_HISTORY_NEW_ID_AND_HUMAN_RECEIPT_REQUIRED")
    reference = human_authorization_ref
    if (not reference.get("path") or not reference.get("sha256")
            or sha256(reference["path"]) != reference["sha256"]):
        raise ValueError("FROZEN_HISTORY_HUMAN_RECEIPT_HASH_REQUIRED")
    files, metadata = _source_files(inputs)
    dates = files["features"].read(columns=["signal_date"]).to_pandas().signal_date
    sessions = pd.DatetimeIndex(sorted(dates.unique()))
    preflight._calendar(sessions)
    if sessions.max() >= preflight.BOUNDARY:
        raise ValueError("FROZEN_HISTORY_CALENDAR_AFTER_BOUNDARY")
    return dict(schema_id=SCHEMA, artifact_kind="C_FROZEN_HISTORY_SOURCE_AUTHORITY_METADATA",
        research_id=research_id, source_id=research_id+":FROZEN_PIT32_RET1D_SNAPSHOT",
        metadata_only=True, observation_scope_end_exclusive="2026-01-01",
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        source_policy="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        historical_available_at_proved=False, historical_revision_vintage_proved=False,
        human_authorization_ref=copy.deepcopy(reference), sources=metadata,
        accepted_sessions=[day.isoformat() for day in sessions],
        accepted_calendar_sha256=_digest([day.isoformat() for day in sessions]),
        session_timezone="America/New_York",
        calendar_authority="EXACT_ACCEPTED_FROZEN_FEATURE_SESSION_CLOCK",
        observation_clock=POLICY_CLOCK, identity_basis=IDENTITY_BASIS,
        identity_policy=preflight.NO_CROSS_IDENTITY_STITCHING,
        membership_clock="STRICTLY_PRIOR_ACCEPTED_SESSION_SNAPSHOT_FOR_BOTH_CADENCES",
        first_crossing_or_gap_return="QUARANTINED",
        predecessor_authority="DECLARED_PRIOR_ACCEPTED_SESSION_MEMBERSHIP_GUARD_NOT_RAW_PRICE_ENDPOINT_PROOF",
        gap_policy="Any missing accepted-session membership breaks the observed UID segment; no return borrowing across the gap",
        return_coordinate=COORDINATE, return_unit=UNIT, return_horizon_sessions=1,
        unit_semantics="Legacy UNIT token retained for exact numerical reuse; PIT in its name grants no strict historical authority",
        frozen_history_limitation="Current pinned historical version; late revisions and delayed identity mappings may contaminate historical semantics",
        base_calibration_refits_authorized=False, test2026_locked=True,
        reader_source={"path": str(Path(__file__).resolve()), "sha256": sha256(__file__)})


def _clock(dates):
    return (pd.DatetimeIndex(dates) + pd.Timedelta(hours=16)).tz_localize("America/New_York").tz_convert("UTC")


def _records(features, members, contract):
    """Observed contiguous epochs only. No event discovery or ticker stitching."""
    features, members = features.copy(), members.copy()
    for frame in (features, members):
        frame["signal_date"] = pd.to_datetime(frame.signal_date, errors="raise")
        if (frame.signal_date.isna().any() or frame.signal_date.dt.tz is not None
                or not frame.signal_date.eq(frame.signal_date.dt.normalize()).all()
                or frame.signal_date.ge(preflight.BOUNDARY).any()
                or frame.duplicated(["signal_date", "ticker"]).any()
                or not frame.ticker.map(lambda v: isinstance(v, str) and bool(v.strip())).all()):
            raise ValueError("FROZEN_HISTORY_KEYS_INVALID")
    if not members.cusip.map(lambda v: isinstance(v, str) and bool(v.strip())).all():
        raise ValueError("FROZEN_HISTORY_MEMBER_UID_UNPROVED")
    features_keys = features[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    members_keys = members[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if not features_keys.equals(members_keys):
        raise ValueError("FROZEN_HISTORY_FULL_U_INPUT_KEYS_DIFFER")
    frame = features.merge(members, on=["signal_date", "ticker"], validate="one_to_one")
    frame = frame.sort_values(["ticker", "signal_date"], kind="stable").reset_index(drop=True)
    frame["security_uid"] = "CUSIP:" + frame.cusip.str.strip().str.upper()
    if frame.duplicated(["signal_date", "security_uid"]).any():
        raise ValueError("FROZEN_HISTORY_AMBIGUOUS_UID_SESSION")
    calendar = pd.DatetimeIndex(contract["accepted_sessions"])
    position = pd.Series(calendar.get_indexer(frame.signal_date), index=frame.index)
    if position.lt(0).any():
        raise ValueError("FROZEN_HISTORY_NONCALENDAR_SESSION")
    grouped = frame.groupby("ticker", sort=False)
    prior_uid = grouped.security_uid.shift()
    prior_position = position.groupby(frame.ticker, sort=False).shift()
    consecutive = position.sub(prior_position).eq(1)
    new_segment = ~consecutive | frame.security_uid.ne(prior_uid)
    start = frame.signal_date.where(new_segment).groupby(frame.ticker, sort=False).ffill()
    frame["identity_epoch"] = ("OBSERVED_SEGMENT:" + frame.security_uid + ":" + start.dt.strftime("%Y-%m-%d"))
    frame["predecessor_uid"] = prior_uid.where(consecutive, None)
    predecessor = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    good = position.gt(0)
    predecessor.loc[good] = calendar.to_numpy()[position.loc[good].to_numpy()-1]
    frame["predecessor_date"] = predecessor
    frame["source_hash"] = contract["sources"]["features"]["sha256"]
    frame["return_unit"] = UNIT
    # These are policy clocks. The contract expressly refuses a strict-PIT claim.
    frame["available_at"] = _clock(frame.signal_date)
    frame["epoch_available_at"] = _clock(start)
    frame["observation_clock_basis"] = POLICY_CLOCK
    frame["identity_basis"] = IDENTITY_BASIS
    if np.isinf(pd.to_numeric(frame.ret_1d, errors="raise").to_numpy()).any():
        raise ValueError("FROZEN_HISTORY_INFINITE_RETURN")
    return frame.sort_values(["signal_date", "security_uid"], kind="stable").reset_index(drop=True)


class FrozenHistoryReader:
    """Read exact, immutable pre2026 projections once; supply qualified slots.

    Qualification means the declared frozen-history mechanism contract only.
    It never establishes historical vintage, availability or production promotion.
    """
    def __init__(self, contract_path, expected_sha256):
        self.path = Path(contract_path)
        if sha256(self.path) != expected_sha256:
            raise ValueError("FROZEN_HISTORY_CONTRACT_HASH_MISMATCH")
        self._contract = json.loads(self.path.read_text(encoding="utf-8"))
        c = self._contract
        if (c.get("schema_id") != SCHEMA or c.get("research_id") != RESEARCH_ID
                or c.get("mechanism_research_eligible") is not True
                or c.get("strict_PIT_promotion_eligible") is not False
                or c.get("historical_available_at_proved") is not False
                or c.get("historical_revision_vintage_proved") is not False
                or c.get("identity_policy") != preflight.NO_CROSS_IDENTITY_STITCHING
                or c.get("observation_clock") != POLICY_CLOCK
                or c.get("identity_basis") != IDENTITY_BASIS
                or c.get("source_policy") != "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"
                or c.get("membership_clock") != "STRICTLY_PRIOR_ACCEPTED_SESSION_SNAPSHOT_FOR_BOTH_CADENCES"
                or c.get("first_crossing_or_gap_return") != "QUARANTINED"
                or c.get("session_timezone") != "America/New_York"
                or c.get("accepted_calendar_sha256") != _digest(c.get("accepted_sessions"))
                or c.get("source_id") != RESEARCH_ID+":FROZEN_PIT32_RET1D_SNAPSHOT"
                or c.get("return_unit") != UNIT or c.get("return_coordinate") != COORDINATE
                or c.get("return_horizon_sessions") != 1 or c.get("test2026_locked") is not True
                or c.get("reader_source", {}).get("sha256") != sha256(__file__)):
            raise ValueError("FROZEN_HISTORY_CONTRACT_SEMANTICS_INVALID")
        reference = c["human_authorization_ref"]
        if sha256(reference["path"]) != reference["sha256"]:
            raise ValueError("FROZEN_HISTORY_AUTHORIZATION_RECEIPT_CHANGED")
        files, metadata = _source_files(c["sources"])
        for kind in PROJECTIONS:
            if metadata[kind] != c["sources"][kind]:
                raise ValueError("FROZEN_HISTORY_SOURCE_METADATA_CHANGED")
        frames = {kind: file.read(columns=PROJECTIONS[kind]).to_pandas() for kind, file in files.items()}
        self._history = _records(frames["features"], frames["members"], c)
        sessions = sorted(self._history.signal_date.unique())
        if [pd.Timestamp(day).isoformat() for day in sessions] != c["accepted_sessions"]:
            raise ValueError("FROZEN_HISTORY_ACCEPTED_CALENDAR_CHANGED")
        self.accepted_sessions = list(c["accepted_sessions"])
        self.source_proof_sha256 = expected_sha256

    @property
    def contract(self):
        return copy.deepcopy(self._contract)

    @property
    def history(self):
        return self._history.copy(deep=True)

    def __call__(self, slot):
        if sha256(self.path) != self.source_proof_sha256:
            raise ValueError("FROZEN_HISTORY_CONTRACT_CHANGED_AFTER_LOAD")
        c = self._contract
        calendar = pd.DatetimeIndex(self.accepted_sessions)
        cutoff = pd.Timestamp(slot["cutoff"])
        decision_at = cutoff.tz_localize("America/New_York").tz_convert("UTC")
        preflight._cutoff_clock(calendar, cutoff, slot["cadence"], decision_at)
        prior = calendar[calendar < cutoff]
        if len(prior) < preflight.WINDOW + 1:
            raise ValueError("FROZEN_HISTORY_REQUIRES63_PLUS_PREDECESSOR")
        roster_date = prior[-1]
        roster = self._history.loc[self._history.signal_date.eq(roster_date)]
        universe = roster[["security_uid", "ticker", "identity_epoch", "source_hash", "epoch_available_at"]].copy()
        universe = universe.rename(columns={"epoch_available_at": "identity_available_at"})
        universe["membership_date"] = roster_date
        universe["membership_available_at"] = _clock([roster_date])[0]
        universe = universe.reset_index(drop=True)
        history = self._history.loc[self._history.signal_date.isin(prior[-(preflight.WINDOW+1):])].copy()
        proof_fields = ["ret_1d", "identity_epoch", "available_at", "epoch_available_at", "source_hash",
                        "predecessor_uid", "predecessor_date", "return_unit"]
        proofs = history.set_index(["signal_date", "security_uid"])[proof_fields]
        expected_universe = universe.copy(deep=True)
        expected_cutoff, expected_proof = cutoff, self.source_proof_sha256

        def authority(value, *, cutoff, decision_at, proof_kind=None, source_proof_sha256=None):
            if pd.Timestamp(cutoff) != expected_cutoff or pd.Timestamp(decision_at) != decision_at_expected:
                return False
            if proof_kind == "CUTOFF_KNOWN_UNIVERSE":
                return (source_proof_sha256 == expected_proof
                        and isinstance(value, pd.DataFrame) and value.equals(expected_universe))
            if not isinstance(value, (dict, pd.Series)):
                return False
            try:
                day, uid = pd.Timestamp(value["signal_date"]), value["security_uid"]
                expected = proofs.loc[(day, uid)]
                if day >= pd.Timestamp(cutoff) or pd.Timestamp(value["available_at"]) >= pd.Timestamp(decision_at):
                    return False
                for field in proof_fields:
                    actual, wanted = value.get(field), expected[field]
                    if pd.isna(actual) or pd.isna(wanted):
                        if not (pd.isna(actual) and pd.isna(wanted)):
                            return False
                    elif actual != wanted:
                        return False
                return True
            except (KeyError, TypeError, ValueError):
                return False

        decision_at_expected = decision_at
        return dict(history=history, accepted_sessions=self.accepted_sessions.copy(),
            universe=universe, decision_at=decision_at, source_authority=authority,
            source_id=c["source_id"], source_proof_sha256=self.source_proof_sha256,
            source_identity={"source_id": c["source_id"], "features_sha256": c["sources"]["features"]["sha256"],
                             "members_sha256": c["sources"]["members"]["sha256"]},
            accepted_calendar_sha256=c["accepted_calendar_sha256"],
            authority_scope="FROZEN_HISTORY_MECHANISM_ONLY_NOT_STRICT_PIT",
            mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
            history_window_sessions=preflight.WINDOW+1, roster_date=roster_date.isoformat())

    def epoch_keys(self, keys):
        """Daily full-U projection uses epoch tokens, preventing UID reversion reuse."""
        wanted = keys[["signal_date", "security_uid"]].copy()
        wanted["signal_date"] = pd.to_datetime(wanted.signal_date, errors="raise")
        if wanted.signal_date.ge(preflight.BOUNDARY).any():
            raise ValueError("FROZEN_HISTORY_2026_EPOCH_LOOKUP_LOCKED")
        out = wanted.merge(self._history[["signal_date", "security_uid", "identity_epoch"]],
                           on=["signal_date", "security_uid"], how="left", validate="many_to_one")
        if out.identity_epoch.isna().any():
            raise ValueError("FROZEN_HISTORY_DAILY_FULL_U_IDENTITY_MISSING")
        return out.identity_epoch.tolist()
