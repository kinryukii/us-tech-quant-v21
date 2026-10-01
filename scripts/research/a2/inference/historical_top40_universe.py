"""Read-only, filing-versioned historical 13F pools for A2 inference.

The registry cohort includes a manager only in quarters with actual filings.
Membership revisions never replace an earlier effective version. Today's
identity enrichment is deliberately not evidence for historical ticker names.
Unproven identities remain in the denominator and in the returned gap ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from scripts.daily_recommendation_inputs import _verified, sha256_file
from scripts.v22 import pit_13f_reconstruction_r1 as pit


MODES = {"registry25", "original24"}
COHORT_POLICIES = {"ALL_APPLICABLE", "DISCLOSED_ONLY"}
SA_MANAGER = "situational_awareness"


# Negative identity evidence only; this does not authorize a DTE replacement.
DTP_IDENTITY_REJECTION = {
    "rule_id": "DTE_COMMON_VS_DTP_UNITS_V1",
    "source_url": "https://www.sec.gov/Archives/edgar/data/936340/000093634019000267/ex11dm-6056137xv5xdtee.htm",
    "source_sha256": "0cb9765fc9993073dfeb24e8f9ae2dc10345bf767c13900aca65d291f6b033fa",
    "common_source_url": "https://www.sec.gov/Archives/edgar/data/93751/000009375125000449/xslSCHEDULE_13G_X01/primary_doc.xml",
    "common_source_sha256": "4c35fd2ef5858bc84dbf6c4ec4e7dce5adcf1d0587cd45fa553d2691edfcf608",
}


def _read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("HISTORICAL_UNIVERSE_EXPECTED_JSON_OBJECT")
    return value


def _ref(path):
    return {"path": str(path), "sha256": sha256_file(Path(path))}


def _frame(reference):
    return pd.read_parquet(_verified(reference))


def _load_inputs(paths, current_report_path, mode):
    config_path = paths.repo_root / "config/research_governance/a2_forward_shadow_unified_r1.json"
    config = _read_json(config_path)
    binding_ref = {"path": config["production_binding_manifest"],
                   "sha256": config["production_binding_sha256"]}
    binding = _read_json(_verified(binding_ref))
    refs = binding["readiness_sources"]
    result = {"frozen_schedule": _frame(refs["universe_manifest"]),
              "frozen_members": _frame(refs["universe_members"]),
              "lineage": {"binding": binding_ref, "config": _ref(config_path),
                          "frozen_schedule": refs["universe_manifest"],
                          "frozen_members": refs["universe_members"]}}
    if mode == "original24":
        return result
    recovery_path = paths.data_root / "13f/recovery_20260913/quarter_manifest.json"
    recovery = _read_json(recovery_path)
    files = recovery["files"]
    result.update(dynamic=_frame(files["dynamic_universe"]),
                  historical_selected=_frame(files["historical_selected_top100_units"]),
                  initial_filings=_frame(files["filings"]),
                  registry=pd.read_csv(_verified(recovery["sources"]["registry"]), keep_default_na=False))
    result["lineage"].update(recovery_manifest=_ref(recovery_path),
        dynamic_universe=files["dynamic_universe"],
        historical_selected=files["historical_selected_top100_units"],
        initial_filings=files["filings"], registry=recovery["sources"]["registry"])
    if current_report_path is not None:
        report_path = Path(current_report_path)
        report = _read_json(report_path)
        if report.get("status") != "READY" or report.get("registry", {}).get("sha256") != recovery["sources"]["registry"]["sha256"]:
            raise ValueError("HISTORICAL_UNIVERSE_CURRENT_REPORT_CONTRACT_MISMATCH")
        revision_ref = {"path": str(report_path.parent / "quarter_universe.parquet"),
                        "sha256": report["universe_manifest_sha256"]}
        result.update(revision=_frame(revision_ref), current_report=report)
        evidence_path = report_path.parent / "filing_evidence.json"
        if not evidence_path.is_file() and report.get("identity_recovery"):
            original = report["identity_recovery"].get("source_report", {})
            if original:
                evidence_path = _verified(original).parent / "filing_evidence.json"
        if not evidence_path.is_file():
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_FILING_EVIDENCE_MISSING")
        result["revision_filings"] = pd.DataFrame(_read_json(evidence_path)["filings"])
        result["lineage"].update(current_report=_ref(report_path), revision=revision_ref,
                                 revision_filings=_ref(evidence_path))
        current_members_ref = {"path": str(report_path.parent / "mapped_members.parquet"),
                               "sha256": report["universe_members_sha256"]}
        result["current_members"] = _frame(current_members_ref)
        result["lineage"]["current_members"] = current_members_ref
    return result


def _day(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is not None:
        raise ValueError("HISTORICAL_UNIVERSE_INVALID_SESSION")
    return stamp.normalize()


def _quarter(value):
    text = str(value)
    if not re.fullmatch(r"\d{4}Q[1-4]", text):
        raise ValueError("HISTORICAL_UNIVERSE_INVALID_QUARTER")
    return text


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _validate_frozen(schedule, members):
    required = {"quarter", "institution_count", "effective_date", "post_cap_universe_count", "universe_fingerprint"}
    if not required.issubset(schedule) or not {"quarter", "cusip", "ticker", "moomoo_transport_code",
            "effective_date", "quarter_universe_fingerprint"}.issubset(members):
        raise ValueError("HISTORICAL_UNIVERSE_FROZEN_COLUMNS_MISSING")
    if schedule.quarter.duplicated().any() or members.duplicated(["quarter", "cusip"]).any():
        raise ValueError("HISTORICAL_UNIVERSE_FROZEN_DUPLICATE_IDENTITY")
    for row in schedule.itertuples(index=False):
        group = members.loc[members.quarter.eq(row.quarter)]
        if (int(row.institution_count) != 24 or len(group) != int(row.post_cap_universe_count)
                or not group.quarter_universe_fingerprint.eq(row.universe_fingerprint).all()
                or not pd.to_datetime(group.effective_date).eq(pd.Timestamp(row.effective_date)).all()):
            raise ValueError("HISTORICAL_UNIVERSE_FROZEN_MANIFEST_MISMATCH")
    if not set(members.quarter).issubset(set(schedule.quarter)):
        raise ValueError("HISTORICAL_UNIVERSE_FROZEN_QUARTER_MISSING")


def _filing_groups(inputs):
    historical = inputs["historical_selected"]
    current = inputs["initial_filings"]
    if "status" in current:
        # Intake plans retain missing registered managers as non-filing rows.
        # Only identified filings enter a disclosed snapshot; malformed identified
        # evidence remains subject to the complete-field validation below.
        current = current.loc[current.status.eq("INITIAL_FILING_IDENTIFIED")]
    required = {"quarter", "manager_id", "filing_date", "accession_key"}
    if not required.issubset(historical) or not {"quarter", "manager_id", "filed_date", "accession"}.issubset(current):
        raise ValueError("HISTORICAL_UNIVERSE_FILING_COLUMNS_MISSING")
    old = historical[list(required)].rename(columns={"filing_date": "filed_date", "accession_key": "accession"})
    combined = pd.concat([old, current[["quarter", "manager_id", "filed_date", "accession"]]], ignore_index=True)
    if combined[["quarter", "manager_id", "filed_date", "accession"]].isna().any().any():
        raise ValueError("HISTORICAL_UNIVERSE_FILING_EVIDENCE_INCOMPLETE")
    combined = combined.drop_duplicates()
    if combined.duplicated(["quarter", "manager_id"], keep=False).any():
        raise ValueError("HISTORICAL_UNIVERSE_INITIAL_FILING_AMBIGUOUS")
    return {str(q): frame for q, frame in combined.groupby("quarter", sort=True)}


def _registered_managers(registry, quarter, actual, cohort_policy="ALL_APPLICABLE"):
    if cohort_policy not in COHORT_POLICIES:
        raise ValueError("HISTORICAL_UNIVERSE_COHORT_POLICY_INVALID")
    actual = list(map(str, actual))
    if not actual or len(actual) != len(set(actual)):
        raise ValueError(f"HISTORICAL_UNIVERSE_ACTUAL_FILERS_INVALID:{quarter}")
    actual = set(actual)
    required = {"manager_id", "enabled", "active_from_quarter", "active_to_quarter"}
    if not required.issubset(registry) or registry.manager_id.duplicated().any():
        raise ValueError("HISTORICAL_UNIVERSE_REGISTRY_INVALID")
    enabled = registry.enabled.astype(str).str.lower().isin({"1", "true", "yes"})
    end = registry.active_to_quarter.fillna("").astype(str)
    mask = enabled & registry.active_from_quarter.le(quarter) & (end.eq("") | end.ge(quarter))
    allowed = set(registry.loc[mask, "manager_id"].astype(str))
    if not actual.issubset(allowed):
        raise ValueError(f"HISTORICAL_UNIVERSE_UNREGISTERED_OR_INACTIVE_ACTUAL_FILER:{quarter}")
    # Preserve the legacy SA applicability rule: configuration alone cannot
    # invent a filing. Other applicable managers remain required by default.
    applicable = allowed - ({SA_MANAGER} if SA_MANAGER not in actual else set())
    if cohort_policy == "ALL_APPLICABLE" and actual != applicable:
        raise ValueError(f"HISTORICAL_UNIVERSE_ACTUAL_FILERS_INCOMPLETE:{quarter}")
    return actual


def _check_activation(effective, latest_filing, sessions):
    latest = _day(latest_filing)
    if effective <= latest:
        raise ValueError("HISTORICAL_UNIVERSE_EFFECTIVE_BEFORE_FILING")
    # The frozen/recovery source covers earlier dates than a caller may request.
    # When the supplied calendar covers that activation, verify its five sessions.
    if sessions[0] <= latest and sessions[-1] >= effective:
        later = sessions[sessions > latest]
        if len(later) < 5 or later[4] != effective:
            raise ValueError("HISTORICAL_UNIVERSE_FIVE_SESSION_RULE_MISMATCH")


def _registry_versions(inputs, sessions, cohort_policy="ALL_APPLICABLE"):
    dynamic = inputs["dynamic"].copy()
    if not {"quarter", "cusip", "effective_date", "manager_ids"}.issubset(dynamic):
        raise ValueError("HISTORICAL_UNIVERSE_DYNAMIC_COLUMNS_MISSING")
    if dynamic.duplicated(["quarter", "cusip"]).any():
        raise ValueError("HISTORICAL_UNIVERSE_DYNAMIC_DUPLICATE_CUSIP")
    filings = _filing_groups(inputs)
    versions = []
    for quarter, group in dynamic.groupby("quarter", sort=True):
        quarter = _quarter(quarter)
        actual = filings.get(quarter)
        if actual is None or actual.empty:
            raise ValueError(f"HISTORICAL_UNIVERSE_NO_ACTUAL_FILINGS:{quarter}")
        managers = _registered_managers(inputs["registry"], quarter, actual.manager_id, cohort_policy)
        effective = pd.to_datetime(group.effective_date).map(_day).unique()
        if len(effective) != 1:
            raise ValueError("HISTORICAL_UNIVERSE_AMBIGUOUS_INITIAL_ACTIVATION")
        effective = _day(effective[0])
        for names in group.manager_ids:
            if not set(str(names).split(";")).issubset(managers):
                raise ValueError("HISTORICAL_UNIVERSE_HOLDING_WITHOUT_FILING")
        _check_activation(effective, pd.to_datetime(actual.filed_date).max(), sessions)
        versions.append({"quarter": quarter, "effective_date": effective,
            "institution_count": len(managers), "manager_ids": ";".join(sorted(managers)),
            "latest_filing_date": str(pd.to_datetime(actual.filed_date).max().date()),
            "version_kind": "INITIAL", "frame": group,
            "source_sha256": inputs["lineage"]["dynamic_universe"]["sha256"]})
    if "revision" in inputs:
        group, report = inputs["revision"], inputs["current_report"]
        quarter = _quarter(report["quarter"])
        effective = _day(report["effective_date"])
        if group.empty or not group.quarter.eq(quarter).all() or group.cusip.duplicated().any():
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_IDENTITY_INVALID")
        if not pd.to_datetime(group.effective_date).eq(effective).all():
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_EFFECTIVE_MISMATCH")
        initial = [row for row in versions if row["quarter"] == quarter]
        if len(initial) != 1 or effective < initial[0]["effective_date"]:
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_WITHOUT_INITIAL")
        evidence = inputs["revision_filings"]
        if not {"manager_id", "filed_date", "accession"}.issubset(evidence) or evidence.empty:
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_FILINGS_INVALID")
        managers = _registered_managers(inputs["registry"], quarter, evidence.manager_id.unique(), cohort_policy)
        if "manager_ids" not in group:
            raise ValueError("HISTORICAL_UNIVERSE_REVISION_MANAGER_IDS_MISSING")
        for names in group.manager_ids:
            if not set(str(names).split(";")).issubset(managers):
                raise ValueError("HISTORICAL_UNIVERSE_HOLDING_WITHOUT_FILING")
        _check_activation(effective, pd.to_datetime(evidence.filed_date).max(), sessions)
        if effective == initial[0]["effective_date"]:
            # Different bytes at the same activation are not silently a new vintage.
            columns = sorted(set(group.columns) & set(initial[0]["frame"].columns))
            left = group[columns].sort_values("cusip").reset_index(drop=True)
            right = initial[0]["frame"][columns].sort_values("cusip").reset_index(drop=True)
            if not left.equals(right):
                raise ValueError("HISTORICAL_UNIVERSE_SAME_DATE_VERSION_CONFLICT")
        else:
            versions.append({"quarter": quarter, "effective_date": effective,
                "institution_count": len(managers), "manager_ids": ";".join(sorted(managers)),
                "latest_filing_date": str(pd.to_datetime(evidence.filed_date).max().date()),
                "version_kind": "REVISION", "frame": group,
                "source_sha256": inputs["lineage"]["revision"]["sha256"]})
    return versions


def _assemble(versions, frozen, target_sessions, mode, lineage):
    schedule, members, gaps = [], [], []
    for version in versions:
        quarter = _quarter(version["quarter"])
        frame = version["frame"].copy()
        if frame.cusip.isna().any() or frame.cusip.astype(str).str.strip().eq("").any():
            raise ValueError("HISTORICAL_UNIVERSE_CUSIP_MISSING")
        universe_id = version.get("universe_id") or _digest({"quarter": quarter,
            "cusips": sorted(frame.cusip.astype(str)), "source": version["source_sha256"]})
        activation = version.get("snapshot_effective_date", version["effective_date"])
        snapshot = _digest({"mode": mode, "quarter": quarter, "effective": version["effective_date"],
                            "activation": activation, "universe_id": universe_id,
                            "current_identity": version.get("identity_source_sha256")})
        # Pool expiry is not a corporate identity event. Carry a previously
        # proved identical CUSIP forward, but never a future quarter backward.
        available = frozen.loc[frozen.quarter.le(quarter) & pd.to_datetime(frozen.effective_date).le(activation)]
        identity = available.sort_values(["effective_date", "quarter"]).drop_duplicates("cusip", keep="last").set_index("cusip")
        current_identity = version.get("current_identity")
        if current_identity is not None:
            if current_identity.security_id.duplicated().any() or not set(current_identity.security_id).issubset(set(frame.cusip)):
                raise ValueError("HISTORICAL_UNIVERSE_CURRENT_IDENTITY_INVALID")
            current_identity = current_identity.set_index("security_id")
        current = []
        for record in frame.to_dict("records"):
            security = str(record["cusip"])
            row = {**record, "snapshot_id": snapshot, "security_id": security,
                   "ticker": None, "moomoo_symbol": None, "moomoo_transport_code": None,
                   "mapping_status": "UNPROVEN", "mapping_verified": False,
                   "mapping_reason": "PIT_IDENTITY_UNPROVEN", "identity_source_sha256": None}
            if security in identity.index:
                known = identity.loc[security]
                ticker, code = str(known.ticker).strip(), str(known.moomoo_transport_code).strip()
                if (not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", ticker)
                        or not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]*", code)):
                    raise ValueError("HISTORICAL_UNIVERSE_FROZEN_PROVIDER_MAPPING_INVALID")
                row.update(ticker=ticker, moomoo_symbol=code, moomoo_transport_code=code,
                    mapping_status="VERIFIED_FROZEN_SAME_QUARTER" if str(known.quarter) == quarter else "VERIFIED_PRIOR_CUSIP_CARRIED_FORWARD",
                    mapping_verified=True, mapping_reason="", identity_evidence_quarter=str(known.quarter),
                    identity_evidence_effective_date=_day(known.effective_date),
                    identity_source_sha256=lineage["frozen_members"]["sha256"])
            if current_identity is not None:
                if security in current_identity.index:
                    known = current_identity.loc[security]
                    interval = {key: _day(known[key]) for key in ("identity_valid_from", "identity_valid_to")
                                if key in known and pd.notna(known[key]) and str(known[key]).strip()}
                    if (("identity_valid_from" in interval and activation < interval["identity_valid_from"])
                            or ("identity_valid_to" in interval and activation > interval["identity_valid_to"])):
                        row.update(ticker=None, moomoo_symbol=None, moomoo_transport_code=None,
                            mapping_status="UNPROVEN", mapping_verified=False,
                            mapping_reason="IDENTITY_OUTSIDE_VERIFIED_INTERVAL", identity_source_sha256=None)
                        current.append(row)
                        continue
                    ticker, code = str(known.ticker).strip(), str(known.moomoo_symbol).strip()
                    if (not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", ticker)
                            or not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]*", code)):
                        raise ValueError("HISTORICAL_UNIVERSE_CURRENT_PROVIDER_MAPPING_INVALID")
                    row.update(ticker=ticker, moomoo_symbol=code, moomoo_transport_code=code,
                        mapping_status="VERIFIED_CURRENT_REPORT_AT_TARGET_ONLY", mapping_verified=True,
                        mapping_reason="", identity_evidence_quarter=quarter,
                        identity_evidence_effective_date=activation,
                        identity_source_sha256=version["identity_source_sha256"])
                else:
                    # An explicit current gap takes precedence over older evidence.
                    row.update(ticker=None, moomoo_symbol=None, moomoo_transport_code=None,
                        mapping_status="UNPROVEN", mapping_verified=False,
                        mapping_reason="CURRENT_REPORT_IDENTITY_GAP", identity_source_sha256=None)
            if (str(row.get("cusip", "")) == "233331107"
                    and (row.get("ticker") == "DTP" or row.get("moomoo_symbol") == "US.DTP"
                         or row.get("moomoo_transport_code") == "US.DTP")):
                row.update(identity_rejected_ticker=row.get("ticker"),
                    identity_rejected_transport=row.get("moomoo_symbol"),
                    identity_rejection_evidence=json.dumps(DTP_IDENTITY_REJECTION, sort_keys=True),
                    ticker=None, moomoo_symbol=None, moomoo_transport_code=None,
                    mapping_status="UNPROVEN", mapping_verified=False,
                    mapping_reason="IDENTITY_MISMATCH_DTE_COMMON_VS_DTP_UNITS")
            current.append(row)
        current_frame = pd.DataFrame(current)
        proven = current_frame.loc[current_frame.mapping_verified]
        conflict = set()
        for field in ("ticker", "moomoo_symbol"):
            duplicates = proven.loc[proven[field].duplicated(keep=False)]
            for _, collision in duplicates.groupby(field):
                same_quarter = collision.mapping_status.eq("VERIFIED_FROZEN_SAME_QUARTER")
                # A known same-quarter security owns this symbol. An older
                # CUSIP carry must stop at that explicit successor boundary.
                if int(same_quarter.sum()) == 1:
                    conflict.update(collision.loc[~same_quarter, "security_id"])
                else:
                    conflict.update(collision.security_id)
        if conflict:
            for row in current:
                if row["security_id"] in conflict:
                    row.update(ticker=None, moomoo_symbol=None, moomoo_transport_code=None,
                        mapping_status="UNPROVEN", mapping_verified=False,
                        mapping_reason="PIT_IDENTITY_PROVIDER_COLLISION", identity_source_sha256=None)
        mapped_count = sum(row["mapping_verified"] for row in current)
        for row in current:
            if not row["mapping_verified"]:
                gaps.append({"snapshot_id": snapshot, "quarter": quarter, "security_id": row["security_id"],
                             "reason": row["mapping_reason"], "issuer_name": row.get("issuer_name", "")})
        schedule.append({key: value for key, value in version.items() if key not in {"frame", "universe_id", "current_identity"}} | {
            "snapshot_effective_date": activation,
            "snapshot_id": snapshot, "universe_id": universe_id, "universe_member_count": len(current),
            "mapped_count": mapped_count, "mapping_gap_count": len(current)-mapped_count,
            "identity_ready": len(current) == mapped_count})
        members.extend(current)
    schedule = pd.DataFrame(schedule).sort_values(["snapshot_effective_date", "quarter", "snapshot_id"]).reset_index(drop=True)
    if schedule.duplicated(["quarter", "snapshot_effective_date"]).any():
        raise ValueError("HISTORICAL_UNIVERSE_AMBIGUOUS_VERSION")
    initial = schedule.sort_values("effective_date").drop_duplicates("quarter", keep="first")
    active = pit.active_quarter_ledger(target_sessions, initial)
    ledger = []
    for item in active.itertuples(index=False):
        day = _day(item.signal_date)
        if item.active_quarter is None:
            ledger.append({"target_date": day, "snapshot_id": None, "quarter": None,
                           "identity_ready": False, "status": "NO_EFFECTIVE_UNIVERSE"})
            continue
        if pd.Period(item.active_quarter, freq="Q") >= day.to_period("Q"):
            raise ValueError("HISTORICAL_UNIVERSE_SAME_OR_FUTURE_QUARTER")
        eligible = schedule.loc[schedule.quarter.eq(item.active_quarter) & schedule.snapshot_effective_date.le(day)]
        latest = eligible.sort_values("snapshot_effective_date").iloc[-1].to_dict()
        ledger.append({**latest, "target_date": day,
            "status": "READY" if latest["identity_ready"] else "PARTIAL_IDENTITY_COVERAGE"})
    ledger = pd.DataFrame(ledger)
    quarters = set(ledger.quarter.dropna())
    schedule = schedule.loc[schedule.quarter.isin(quarters) & schedule.snapshot_effective_date.le(target_sessions[-1])].reset_index(drop=True)
    snapshots = set(schedule.snapshot_id)
    members = pd.DataFrame(members)
    members = members.loc[members.snapshot_id.isin(snapshots)].reset_index(drop=True)
    for column in ("report_date", "effective_date", "expiry_date", "identity_evidence_effective_date"):
        if column in members:
            members[column] = pd.to_datetime(members[column], errors="raise")
    return {"schedule": schedule, "members": members, "ledger": ledger,
            "gaps": [row for row in gaps if row["snapshot_id"] in snapshots],
            "lineage": {**lineage, "mode": mode, "activation_rule": "ALL_ACTUAL_FILERS_PLUS_5_US_SESSIONS",
                "identity_rule": "HASH_BOUND_PRIOR_CUSIP_FORWARD_ONLY_CURRENT_REPORT_TARGET_ONLY",
                "current_identity_backfilled": False, "writes_performed": False,
                "calendar_sha256": _digest([str(day.date()) for day in target_sessions])}}


def build_universe_schedule(paths, start, end, sessions, current_report_path=None, mode="registry25",
                            cohort_policy="ALL_APPLICABLE"):
    """Return schedule/members/ledger DataFrames plus gaps and hashed lineage.

    ``members`` contains every holding, including rows with no proven ticker.
    A caller can rank the mapped subset with an explicit partial coverage label;
    ledger.identity_ready is required only to claim a complete-pool Top40.
    This function never fetches data, writes a file, or changes catalog pointers.
    """
    if mode not in MODES:
        raise ValueError("HISTORICAL_UNIVERSE_MODE_INVALID")
    if cohort_policy not in COHORT_POLICIES:
        raise ValueError("HISTORICAL_UNIVERSE_COHORT_POLICY_INVALID")
    first, last = _day(start), _day(end)
    calendar = pd.DatetimeIndex([_day(value) for value in sessions]).sort_values().unique()
    if first > last or calendar.empty:
        raise ValueError("HISTORICAL_UNIVERSE_DATE_RANGE_INVALID")
    target = calendar[(calendar >= first) & (calendar <= last)]
    if target.empty or first < calendar[0] or last > calendar[-1]:
        raise ValueError("HISTORICAL_UNIVERSE_CALENDAR_COVERAGE_MISSING")
    inputs = _load_inputs(paths, current_report_path, mode)
    _validate_frozen(inputs["frozen_schedule"], inputs["frozen_members"])
    if mode == "registry25":
        versions = _registry_versions(inputs, calendar, cohort_policy)
        report = inputs.get("current_report", {})
        if report.get("target_date") == str(last.date()) and "current_members" in inputs:
            candidates = [row for row in versions if row["quarter"] == report["quarter"] and row["effective_date"] <= last]
            if not candidates:
                raise ValueError("HISTORICAL_UNIVERSE_CURRENT_IDENTITY_WITHOUT_MEMBERSHIP")
            latest = max(candidates, key=lambda row: row["effective_date"])
            identity_version = {**latest, "version_kind": "CURRENT_IDENTITY_ASOF", "snapshot_effective_date": last,
                "current_identity": inputs["current_members"],
                "identity_source_sha256": inputs["lineage"]["current_members"]["sha256"]}
            if latest["effective_date"] == last:
                versions.remove(latest)
            versions.append(identity_version)
    else:
        versions = [{"quarter": _quarter(row.quarter), "effective_date": _day(row.effective_date),
            "institution_count": int(row.institution_count), "version_kind": "INITIAL",
            "universe_id": str(row.universe_fingerprint),
            "source_sha256": inputs["lineage"]["frozen_members"]["sha256"],
            "frame": inputs["frozen_members"].loc[inputs["frozen_members"].quarter.eq(row.quarter)]}
            for row in inputs["frozen_schedule"].itertuples(index=False)]
    lineage = {**inputs["lineage"], "supplied_calendar_sha256": _digest([str(day.date()) for day in calendar]),
        "cohort_policy": cohort_policy,
        "cohort_coverage": "FROZEN_ORIGINAL24_MANIFEST" if mode == "original24" else
            "COMPLETE_APPLICABLE_ROSTER_SA_REQUIRES_ACTUAL_FILING" if cohort_policy == "ALL_APPLICABLE"
            else "NONEMPTY_DISCLOSED_REGISTERED_SUBSET_NO_OLD_QUARTER_FILL"}
    return _assemble(versions, inputs["frozen_members"], target, mode, lineage)


class WholeSnapshotQualificationError(ValueError):
    """Missing or inconsistent authority prevents whole-snapshot selection."""


def select_whole_qualified_snapshot(schedule, members, decision_at,
                                   allowed_manager_ids_by_quarter, cohort_policy="ALL_APPLICABLE"):
    """Select one whole, qualified 13F snapshot from legally isolated inputs.

    This pure selector performs no I/O and does not establish cohort authority.
    Its caller must supply an already-authorized quarterly registered-manager mapping and
    isolated schedule/member frames. All timestamps require an explicit timezone.
    ALL_APPLICABLE requires the supplied applicable cohort to be complete.
    DISCLOSED_ONLY permits its nonempty registered disclosed subset. Neither
    policy fills undisclosed managers from an older quarter. SA applicability
    must already be resolved in the supplied quarterly authority mapping.
    Revision zero is the initial snapshot; later revisions cannot move either
    activation or qualification availability backward. Existing Top40 callers
    and their partial-coverage behavior are unchanged.
    """
    from collections.abc import Mapping

    def fail(reason):
        raise WholeSnapshotQualificationError(reason)

    def timestamp(value, field):
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            fail("WHOLE_SNAPSHOT_INVALID_TIMESTAMP:" + field)
        if pd.isna(stamp) or stamp.tzinfo is None:
            fail("WHOLE_SNAPSHOT_TIMEZONE_REQUIRED:" + field)
        return stamp.tz_convert("UTC")

    def identifiers(value, field):
        if not isinstance(value, (list, tuple)) or not value:
            fail("WHOLE_SNAPSHOT_EXPLICIT_MANAGER_SEQUENCE_REQUIRED:" + field)
        if any(not isinstance(item, str) or not item.strip() or item != item.strip()
               for item in value):
            fail("WHOLE_SNAPSHOT_INVALID_MANAGER_ID:" + field)
        if len(value) != len(set(value)):
            fail("WHOLE_SNAPSHOT_DUPLICATE_MANAGER:" + field)
        return tuple(sorted(value))

    required_schedule = {"snapshot_id", "quarter", "revision", "effective_at",
        "qualification_available_at", "qualification_status", "manager_ids",
        "universe_member_count", "mapping_qualified", "pit_qualified"}
    required_members = {"snapshot_id", "quarter", "security_id", "ticker",
        "moomoo_transport_code", "mapping_verified", "pit_qualified"}
    for frame, required, label in ((schedule, required_schedule, "schedule"),
                                   (members, required_members, "members")):
        if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
            fail("WHOLE_SNAPSHOT_REQUIRED_COLUMNS_MISSING:" + label)
    if cohort_policy not in COHORT_POLICIES:
        fail("WHOLE_SNAPSHOT_COHORT_POLICY_INVALID")
    decision = timestamp(decision_at, "decision_at")
    decision_quarter = decision.tz_convert("America/New_York").tz_localize(None).to_period("Q")
    if not isinstance(allowed_manager_ids_by_quarter, Mapping) or not allowed_manager_ids_by_quarter:
        fail("WHOLE_SNAPSHOT_QUARTERLY_COHORT_AUTHORITY_REQUIRED")
    allowed = {}
    for quarter, names in allowed_manager_ids_by_quarter.items():
        if not isinstance(quarter, str) or not re.fullmatch(r"\d{4}Q[1-4]", quarter):
            fail("WHOLE_SNAPSHOT_INVALID_COHORT_QUARTER")
        allowed[quarter] = identifiers(names, quarter)
    work, holdings = schedule.copy(deep=True), members.copy(deep=True)
    for frame, fields in ((work, ("snapshot_id", "quarter")),
                          (holdings, ("snapshot_id", "quarter", "security_id"))):
        for field in fields:
            if any(not isinstance(value, str) or not value.strip() or value != value.strip()
                   for value in frame[field]):
                fail("WHOLE_SNAPSHOT_INVALID_IDENTITY:" + field)
    if work.snapshot_id.duplicated().any() or work.duplicated(["quarter", "revision"]).any():
        fail("WHOLE_SNAPSHOT_DUPLICATE_VERSION")
    if holdings.duplicated(["snapshot_id", "security_id"]).any():
        fail("WHOLE_SNAPSHOT_DUPLICATE_SECURITY_IDENTITY")
    if not set(holdings.snapshot_id).issubset(set(work.snapshot_id)):
        fail("WHOLE_SNAPSHOT_UNDECLARED_MEMBER_SNAPSHOT")
    if not work.quarter.str.fullmatch(r"\d{4}Q[1-4]").all():
        fail("WHOLE_SNAPSHOT_INVALID_QUARTER")
    for field in ("revision", "universe_member_count"):
        if any(type(value) is not int or value < 0 for value in work[field].tolist()):
            fail("WHOLE_SNAPSHOT_INVALID_NONNEGATIVE_INTEGER:" + field)
    for frame, fields in ((work, ("mapping_qualified", "pit_qualified")),
                          (holdings, ("mapping_verified", "pit_qualified"))):
        for field in fields:
            if any(type(value) is not bool for value in frame[field].tolist()):
                fail("WHOLE_SNAPSHOT_EXPLICIT_BOOLEAN_REQUIRED:" + field)
    if any(not isinstance(value, str) or not value.strip() for value in work.qualification_status):
        fail("WHOLE_SNAPSHOT_QUALIFICATION_STATUS_REQUIRED")
    work["effective_at"] = [timestamp(value, "effective_at") for value in work.effective_at]
    work["qualification_available_at"] = [timestamp(value, "qualification_available_at")
                                          for value in work.qualification_available_at]
    work["manager_ids"] = [identifiers(value, "manager_ids") for value in work.manager_ids]
    for _, group in work.loc[work.qualification_available_at.le(decision)].groupby("quarter"):
        ordered = group.sort_values("revision")
        if (not ordered.effective_at.is_monotonic_increasing
                or not ordered.qualification_available_at.is_monotonic_increasing):
            fail("WHOLE_SNAPSHOT_REVISION_TIME_REGRESSION:" + str(ordered.iloc[0].quarter))
    eligible, excluded = [], []
    for row in work.to_dict("records"):
        reasons = []
        if pd.Period(row["quarter"], freq="Q") >= decision_quarter:
            reasons.append("SAME_OR_FUTURE_REPORT_QUARTER")
        if row["effective_at"] > decision:
            reasons.append("SNAPSHOT_NOT_EFFECTIVE")
        if row["qualification_available_at"] > decision:
            reasons.append("QUALIFICATION_NOT_AVAILABLE")
        if row["quarter"] not in allowed:
            fail("WHOLE_SNAPSHOT_COHORT_AUTHORITY_MISSING:" + row["quarter"])
        if not set(row["manager_ids"]).issubset(set(allowed[row["quarter"]])):
            fail("WHOLE_SNAPSHOT_UNREGISTERED_OR_INACTIVE_ACTUAL_FILER:" + row["snapshot_id"])
        if cohort_policy == "ALL_APPLICABLE" and row["manager_ids"] != allowed[row["quarter"]]:
            reasons.append("APPLICABLE_MANAGER_COHORT_INCOMPLETE")
        if row["qualification_status"] != "COMPLETE_AND_QUALIFIED":
            reasons.append("SNAPSHOT_NOT_COMPLETE_AND_QUALIFIED")
        if not row["mapping_qualified"] or not row["pit_qualified"]:
            reasons.append("SNAPSHOT_MAPPING_OR_PIT_UNQUALIFIED")
        group = holdings.loc[holdings.snapshot_id.eq(row["snapshot_id"])]
        if group.empty or len(group) != row["universe_member_count"]:
            reasons.append("WHOLE_MEMBER_COUNT_MISMATCH")
        if not group.quarter.eq(row["quarter"]).all():
            fail("WHOLE_SNAPSHOT_MEMBER_QUARTER_CONFLICT:" + row["snapshot_id"])
        mapped = (group.mapping_verified.all() and group.pit_qualified.all()
            and group.ticker.map(lambda value: isinstance(value, str)
                and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", value))).all()
            and group.moomoo_transport_code.map(lambda value: isinstance(value, str)
                and bool(re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]*", value))).all())
        if not mapped:
            reasons.append("WHOLE_MEMBER_MAPPING_OR_PIT_UNQUALIFIED")
        if group.ticker.dropna().duplicated().any() or group.moomoo_transport_code.dropna().duplicated().any():
            fail("WHOLE_SNAPSHOT_PROVIDER_IDENTITY_COLLISION:" + row["snapshot_id"])
        if reasons:
            excluded.append({"snapshot_id": row["snapshot_id"], "quarter": row["quarter"],
                             "revision": row["revision"], "reasons": reasons})
        else:
            eligible.append(row)
    if not eligible:
        fail("NO_PREVIOUS_COMPLETE_AND_QUALIFIED_SNAPSHOT")
    selected = max(eligible, key=lambda row: (row["quarter"], row["revision"]))
    newer = [row for row in excluded if (row["quarter"], row["revision"])
             > (selected["quarter"], selected["revision"])]
    newer.sort(key=lambda row: (row["quarter"], row["revision"]), reverse=True)
    return {"snapshot": selected,
            "members": holdings.loc[holdings.snapshot_id.eq(selected["snapshot_id"])].copy(),
            "fallback_used": bool(newer), "fallback_reasons": newer,
            "cohort_policy": cohort_policy,
            "cohort_coverage": "COMPLETE_SUPPLIED_APPLICABLE_COHORT" if cohort_policy == "ALL_APPLICABLE"
                else "NONEMPTY_DISCLOSED_REGISTERED_SUBSET_NO_OLD_QUARTER_FILL",
            "cohort_validation_scope": "SUPPLIED_QUARTERLY_COHORT_CHECK_ONLY_NOT_AUTHORITY_ESTABLISHMENT"}
