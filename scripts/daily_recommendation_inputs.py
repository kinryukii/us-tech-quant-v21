"""Read the frozen A2 identities and date-bounded recommendation inputs.

No price acquisition, fitting, outcome reads or canonical writes occur here.
The replay is usable only for the explicitly authorized acquisition priority.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pandas as pd
import pyarrow.parquet as pq

MODEL_ID = "A2_HGB"
MODEL_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
REPLAY_HASHES = {
    "contract.json": "3d6f6411b2f3e22a8af9e1e34f32c31c4cefec38ec3fcf7ead39c34721664b26",
    "predictions.parquet": "391c71017bfcd3cd33c1e7efec51057034ff29e26d8d88d9b43b4fbe35aa00ab",
    "source_resolution.json": "21d246c614ca71ae713f49904066b43647e2f9d0b2d6deea0c39230a2a8f8f76",
    "input_coverage.json": "4c979486b983108d41631f93244cbb2d991d730e6c707c23b7986a24f9d034f3",
}


class InputError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise InputError("EXPECTED_JSON_OBJECT")
    return value


def _verified(reference: dict) -> Path:
    path = Path(reference["path"])
    if not path.is_file() or sha256_file(path) != reference.get("sha256"):
        raise InputError(f"SOURCE_HASH_MISMATCH:{path.name}")
    return path


def load_frozen_binding(repo_root: Path) -> dict:
    config = _json(Path(repo_root) / "config/research_governance/a2_forward_shadow_unified_r1.json")
    path = _verified({"path": config["production_binding_manifest"], "sha256": config["production_binding_sha256"]})
    binding = _json(path)
    component = binding["components"]["ALPHA"]
    if component.get("model_id") != MODEL_ID:
        raise InputError("A2_MODEL_ID_MISMATCH")
    artifacts = {item["artifact_id"]: item for item in component["artifacts"]}
    if artifacts.get("model", {}).get("sha256") != MODEL_SHA256:
        raise InputError("A2_FROZEN_MODEL_MISMATCH")
    for name in ("model", "source", "frozen_contracts", "pre_final_freeze"):
        _verified(artifacts[name])
    return binding


def latest_completed_session(binding: dict, now: datetime | None = None) -> dict:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise InputError("ASOF_TIMEZONE_REQUIRED")
    contract_path = _verified(binding["readiness_sources"]["trading_calendar"])
    # The calendar module checks the frozen rule source and generated sessions.
    module_path = contract_path.parents[2] / "scripts/v22/forward_shadow/trading_calendar.py"
    spec = importlib.util.spec_from_file_location("a2_recommendation_calendar", module_path)
    if spec is None or spec.loader is None:
        raise InputError("CALENDAR_MODULE_NOT_LOADABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    provider = module.ForwardShadowTradingCalendarProvider(contract_path)
    if stamp.astimezone(provider.timezone).date() > provider.end:
        raise InputError("ASOF_OUTSIDE_BOUND_CALENDAR")
    completion = provider.completed_session_metadata(provider.sessions[-1], stamp.isoformat(), "UTC")
    target = completion["latest_completed_us_session"]
    if target is None:
        raise InputError("NO_COMPLETED_SESSION")
    return {"target_date": target, "sessions": list(provider.sessions), "calendar_id": provider.calendar_id,
            "calendar_sha256": provider.calendar_sha256, "as_of_utc": stamp.astimezone(timezone.utc).isoformat()}


def required_reporting_quarter(target_date: str) -> str:
    """Freshness gate requested for current recommendations, not a PIT activation rule.

    Once the usual 45-day filing deadline has passed, a prior quarter cannot be
    represented as current. Actual activation still comes from the bound manifest.
    """
    target = date.fromisoformat(target_date)
    period = pd.Period(target, freq="Q")
    for offset in range(1, 9):
        candidate = period - offset
        if candidate.end_time.date() + timedelta(days=45) < target:
            return str(candidate)
    raise InputError("REQUIRED_REPORTING_QUARTER_UNAVAILABLE")


def load_bound_universe(binding: dict, target_date: str, required_quarter: str | None = None) -> dict:
    target = pd.Timestamp(date.fromisoformat(target_date))
    refs = binding["readiness_sources"]
    explicit_roster = "manager_registry" in refs
    if explicit_roster:
        reference = refs["manager_registry"]
        if (not isinstance(reference, dict) or not isinstance(reference.get("path"), (str, Path))
                or not str(reference["path"]).strip()
                or not isinstance(reference.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
            raise InputError("A2_MANAGER_REGISTRY_REFERENCE_INVALID")
    schedule_path = _verified(refs["universe_manifest"])
    members_path = _verified(refs["universe_members"])
    schedule_columns = ["quarter", "institution_count", "effective_date",
                        "post_cap_universe_count", "universe_fingerprint"]
    if explicit_roster:
        if "manager_roster_sha256" not in pq.ParquetFile(schedule_path).schema_arrow.names:
            raise InputError("A2_QUARTER_MANAGER_ROSTER_IDENTITY_MISSING")
        schedule_columns.append("manager_roster_sha256")
    schedule = pq.read_table(schedule_path, columns=schedule_columns).to_pandas()
    schedule["effective_date"] = pd.to_datetime(schedule.effective_date)
    if schedule.quarter.duplicated().any() or schedule.effective_date.duplicated().any():
        raise InputError("AMBIGUOUS_UNIVERSE_SCHEDULE")
    active = schedule.loc[schedule.effective_date.le(target)].sort_values("effective_date")
    if active.empty:
        raise InputError("NO_EFFECTIVE_UNIVERSE")
    current = active.iloc[-1]
    quarter = str(current.quarter)
    roster = None
    if explicit_roster:
        from scripts.storage.refresh_13f_quarter import manager_roster_identity
        registry_path = _verified(refs["manager_registry"])
        roster = manager_roster_identity(pd.read_csv(registry_path, dtype=str, keep_default_na=False), quarter)
        expected_count = roster["applicable_manager_count"]
        if current.manager_roster_sha256 != roster["roster_sha256"]:
            raise InputError("A2_QUARTER_MANAGER_ROSTER_IDENTITY_MISMATCH")
    else:
        # This immutable legacy binding certifies the original A2 cohort, which
        # excludes SA. Current quarter registries must be supplied explicitly.
        expected_count = 24
    if (pd.isna(current.institution_count) or float(current.institution_count) != expected_count):
        raise InputError("A2_QUARTER_MANAGER_ROSTER_COUNT_MISMATCH")
    expected = required_quarter or required_reporting_quarter(target_date)
    columns = ["quarter", "cusip", "ticker", "moomoo_transport_code", "effective_date",
               "expiry_date", "quarter_universe_fingerprint"]
    frame = pq.read_table(members_path, columns=columns, filters=[("quarter", "=", quarter)]).to_pandas()
    if frame.empty or len(frame) != int(current.post_cap_universe_count):
        raise InputError("UNIVERSE_MEMBER_COUNT_MISMATCH")
    if not frame.quarter_universe_fingerprint.eq(current.universe_fingerprint).all():
        raise InputError("UNIVERSE_MEMBER_IDENTITY_MISMATCH")
    if not pd.to_datetime(frame.effective_date).eq(current.effective_date).all():
        raise InputError("UNIVERSE_MEMBER_EFFECTIVE_DATE_MISMATCH")
    expiry = pd.to_datetime(frame.expiry_date, errors="coerce")
    if (expiry.notna() & expiry.lt(target)).any():
        raise InputError("UNIVERSE_MEMBERS_EXPIRED")
    for column in ("cusip", "ticker", "moomoo_transport_code"):
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any() or frame[column].duplicated().any():
            raise InputError(f"UNIVERSE_MAPPING_INCOMPLETE_OR_AMBIGUOUS:{column}")
    if not frame.moomoo_transport_code.astype(str).str.match(r"^US\.[A-Z0-9][A-Z0-9._/-]*$").all():
        raise InputError("UNIVERSE_PROVIDER_MAPPING_INVALID")
    members = [{"security_id": str(row.cusip), "ticker": str(row.ticker),
                "moomoo_symbol": str(row.moomoo_transport_code),
                "moomoo_transport_code": str(row.moomoo_transport_code)} for row in frame.itertuples(index=False)]
    ready = quarter == expected
    reason = "" if ready else f"CURRENT_13F_QUARTER_MISSING:{expected}:AVAILABLE:{quarter}"
    return {"status": "READY" if ready else "STALE_UNIVERSE", "inference_ready": ready, "current": ready,
            "target_date": target_date, "quarter": quarter, "required_quarter": expected,
            "effective_date": current.effective_date.date().isoformat(), "universe_id": str(current.universe_fingerprint),
            "members": members, "applicable_manager_count": expected_count, "quarter_manager_roster": roster,
            "manager_completeness_basis": "QUARTER_APPLICABLE_REGISTRY" if roster else "FROZEN_ORIGINAL_A2_COHORT",
            "universe_manifest_sha256": refs["universe_manifest"]["sha256"],
            "universe_members_sha256": refs["universe_members"]["sha256"],
            "failure_reason": reason, "reason": reason}


def load_target_universe(binding: dict, target_date: str, required_quarter: str | None = None) -> dict:
    result = load_bound_universe(binding, target_date, required_quarter)
    if not result["inference_ready"]:
        raise InputError(result["failure_reason"])
    return result


def _top40_records(rows: list[dict], day: str, kind: str, source_id: str) -> list[dict]:
    date.fromisoformat(day)
    selected = []
    for row in rows:
        try:
            rank = int(row["rank"])
        except (ValueError, TypeError, KeyError) as exc:
            raise InputError("INVALID_RECOMMENDATION_RANK") from exc
        if float(row["rank"]) != rank or rank < 1:
            raise InputError("INVALID_RECOMMENDATION_RANK")
        if rank <= 40:
            ticker = str(row["ticker"]).strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,31}", ticker):
                raise InputError("INVALID_RECOMMENDATION_TICKER")
            selected.append({"date": day, "ticker": ticker, "rank": rank, "record_kind": kind,
                             "model_id": MODEL_ID, "source_id": source_id})
    if sorted(row["rank"] for row in selected) != list(range(1, 41)) or len({row["ticker"] for row in selected}) != 40:
        raise InputError(f"TOP40_INCOMPLETE_OR_DUPLICATED:{day}")
    return sorted(selected, key=lambda row: row["rank"])


def _recomputed_priority(root: Path, model_sha256: str) -> dict | None:
    """Read only rank/identity projections from a completed historical run."""
    root = Path(root).resolve()
    pointer = root / "latest.json"
    if not pointer.is_file():
        return None
    manifest = _json(pointer)
    report_path = Path(manifest.get("report_path", "")).resolve()
    if not report_path.is_relative_to(root / "runs") or not report_path.is_file() or _json(report_path) != manifest:
        raise InputError("RECOMPUTED_PRIORITY_MANIFEST_IDENTITY_MISMATCH")
    if (manifest.get("schema_version") != 1 or manifest.get("status") not in {"READY", "PARTIAL"}
            or manifest.get("feature_selection_count") != 0 or manifest.get("model_selection_count") != 0
            or manifest.get("calculate_returns") is not False
            or manifest.get("training_cutoff_exclusive") != "2026-01-01"):
        raise InputError("RECOMPUTED_PRIORITY_RUN_CONTRACT_MISMATCH")
    start, end = str(manifest["start_date"]), str(manifest["end_date"])
    if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end or start > end:
        raise InputError("RECOMPUTED_PRIORITY_DATE_RANGE_INVALID")
    if end < "2026-01-01":
        return None
    model = manifest.get("models", {}).get("artifacts", {}).get("2026", {})
    if (model.get("sha256") != model_sha256 or model.get("model_role") != "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY"
            or str(model.get("labelmax", "9999")) >= "2026-01-01"
            or str(model.get("train_end", "9999")) >= "2026-01-01"):
        raise InputError("RECOMPUTED_PRIORITY_MODEL_MISMATCH")
    _verified(model)
    references = {**manifest["outputs"], **manifest["universe_outputs"]}
    paths = {}
    for key in ("top40", "coverage", "schedule", "ledger", "members"):
        reference = references[key]
        candidate = Path(reference["path"]).resolve()
        if not candidate.is_relative_to(report_path.parent):
            raise InputError("RECOMPUTED_PRIORITY_ARTIFACT_OUTSIDE_RUN")
        paths[key] = _verified(reference)
    _verified(manifest["price_manifest"])
    projections = {
        "top40": ["target_date", "ticker", "rank", "model_year", "model_sha256", "universe_id",
                  "universe_quarter", "universe_effective_date", "institution_count"],
        "coverage": ["target_date", "status", "eligible_count", "universe_member_count", "mapped_count",
                     "quarter", "effective_date", "institution_count"],
        "schedule": ["snapshot_id", "universe_id", "quarter", "effective_date", "snapshot_effective_date",
                     "institution_count", "universe_member_count", "mapped_count"],
        "ledger": ["target_date", "snapshot_id"],
    }
    frames = {key: pq.read_table(paths[key], columns=columns).to_pandas() for key, columns in projections.items()}
    for key, frame in frames.items():
        if "rows" in references[key] and len(frame) != int(references[key]["rows"]):
            raise InputError("RECOMPUTED_PRIORITY_ROW_COUNT_MISMATCH")
        if "target_date" in frame:
            frame["target_date"] = pd.to_datetime(frame.target_date, errors="raise").dt.strftime("%Y-%m-%d")
            if frame.target_date.isna().any() or not frame.target_date.between(start, end).all():
                raise InputError("RECOMPUTED_PRIORITY_ROWS_OUTSIDE_DATE_CONTRACT")
    coverage, schedule, ledger = frames["coverage"], frames["schedule"], frames["ledger"]
    if coverage.target_date.duplicated().any() or ledger.target_date.duplicated().any() or schedule.snapshot_id.duplicated().any():
        raise InputError("RECOMPUTED_PRIORITY_AMBIGUOUS_DATE_OR_SNAPSHOT")
    if set(coverage.target_date) != set(ledger.target_date):
        raise InputError("RECOMPUTED_PRIORITY_COVERAGE_LEDGER_DATE_MISMATCH")
    active = ledger.merge(schedule, on="snapshot_id", how="left", validate="many_to_one").set_index("target_date")
    coverage = coverage.set_index("target_date")
    frame = frames["top40"]
    if frame.duplicated(["target_date", "rank"]).any() or frame.duplicated(["target_date", "ticker"]).any():
        raise InputError("RECOMPUTED_PRIORITY_DUPLICATE_RANK_OR_TICKER")
    frame = frame.loc[frame.target_date.between("2026-01-01", "2026-12-31")]
    if (not frame.model_year.eq(2026).all() or not frame.model_sha256.eq(model_sha256).all()
            or not frame.target_date.isin(coverage.index).all()):
        raise InputError("RECOMPUTED_PRIORITY_ROW_MODEL_OR_DATE_MISMATCH")
    provenance = {"recomputed_root": str(root), "recomputed_manifest": {"path": str(report_path),
        "sha256": sha256_file(report_path)}, "recomputed_hashes": references,
        "model_sha256": model_sha256, "replay_purpose": "ACQUISITION_PRIORITY_INITIALIZATION_ONLY",
        "daily_files": [], "excluded_priority_files": [], "recomputed_coverage": []}
    source_id = f"{model_sha256}:historical_replay:{provenance['recomputed_manifest']['sha256']}"
    by_day = {}
    groups = {day: group for day, group in frame.groupby("target_date", sort=True)}
    for day in sorted(day for day in coverage.index if "2026-01-01" <= day <= "2026-12-31"):
        covered, pool = coverage.loc[day], active.loc[day]
        eligible, total, mapped = (float(covered[name]) for name in ("eligible_count", "universe_member_count", "mapped_count"))
        if any(not value.is_integer() for value in (eligible, total, mapped)) or not 0 <= eligible <= mapped <= total:
            raise InputError("RECOMPUTED_PRIORITY_COVERAGE_COUNTS_INVALID")
        group = groups.get(day, frame.iloc[:0])
        if len(group) != min(int(eligible), 40):
            raise InputError("RECOMPUTED_PRIORITY_TOP40_COVERAGE_MISMATCH")
        if eligible < 40:
            provenance["excluded_priority_files"].append({"path": str(paths["top40"]), "data_date": day,
                "reason": "RECOMPUTED_FULL_TOP40_NOT_AVAILABLE", "eligible_count": int(eligible)})
            continue
        if (covered.status not in {"READY", "PARTIAL"} or pd.isna(pool.snapshot_id)
                or pd.isna(pool.effective_date) or pd.isna(pool.snapshot_effective_date)
                or int(pool.universe_member_count) != total or int(pool.mapped_count) != mapped
                or covered.quarter != pool.quarter or int(covered.institution_count) != int(pool.institution_count)
                or pd.Timestamp(covered.effective_date) != pd.Timestamp(pool.effective_date)
                or pd.Timestamp(pool.effective_date) > pd.Timestamp(day)
                or pd.Timestamp(pool.snapshot_effective_date) > pd.Timestamp(day)
                or pd.Period(pool.quarter, freq="Q") >= pd.Period(day, freq="Q")
                or not group.universe_id.eq(pool.universe_id).all()
                or not group.universe_quarter.eq(pool.quarter).all()
                or not pd.to_datetime(group.universe_effective_date).eq(pd.Timestamp(pool.effective_date)).all()
                or not group.institution_count.eq(pool.institution_count).all()):
            raise InputError("RECOMPUTED_PRIORITY_POOL_OR_PIT_MISMATCH")
        if covered.status == "READY" and eligible != total:
            raise InputError("RECOMPUTED_PRIORITY_FALSE_COMPLETE_COVERAGE")
        by_day[day] = _top40_records(group.to_dict("records"), day, "historical_replay", source_id)
        provenance["recomputed_coverage"].append({"data_date": day, "status": covered.status,
            "eligible_count": int(eligible), "universe_member_count": int(total), "mapped_count": int(mapped),
            "universe_id": pool.universe_id, "quarter": pool.quarter})
    selected = sorted(by_day)[-60:]
    provenance["recomputed_selected_dates"] = selected
    return {"by_day": {day: by_day[day] for day in selected}, "provenance": provenance}


def _legacy_priority(replay_root, expected, model_sha256):
    root = Path(replay_root)
    for filename, digest in expected.items():
        _verified({"path": root / filename, "sha256": digest})
    contract = _json(root / "contract.json")
    if (contract.get("model_sha256") != model_sha256 or contract.get("top_n") != 20
            or contract.get("model_fit_count") != 0 or contract.get("model_selection_count") != 0
            or contract.get("parameter_search_count") != 0
            or contract.get("role") != "ALREADY_EXPOSED_DESCRIPTIVE_COVERAGE_LIMITED"):
        raise InputError("REPLAY_MODEL_OR_ROLE_CONTRACT_MISMATCH")
    if (contract.get("source_resolution_sha256") != expected["source_resolution.json"]
            or contract.get("input_coverage_sha256") != expected["input_coverage.json"]):
        raise InputError("REPLAY_INPUT_PROVENANCE_MISMATCH")
    # Column projection never loads outcomes, returns or prediction scores.
    frame = pq.read_table(root / "predictions.parquet", columns=["signal_date", "ticker", "a2_rank"]).to_pandas()
    frame["date"] = pd.to_datetime(frame.signal_date).dt.strftime("%Y-%m-%d")
    if frame.date.isna().any() or frame.empty:
        raise InputError("REPLAY_DATES_INVALID")
    if frame.date.min() != contract.get("start_date") or frame.date.max() != contract.get("end_date"):
        raise InputError("REPLAY_DATE_CONTRACT_MISMATCH")
    source_id = f"{model_sha256}:historical_replay:{expected['contract.json']}"
    by_day = {day: _top40_records(group.rename(columns={"a2_rank": "rank"}).to_dict("records"), day,
                                "historical_replay", source_id) for day, group in frame.groupby("date", sort=True)}
    provenance = {"replay_root": str(root), "replay_hashes": expected, "model_sha256": model_sha256,
                  "replay_purpose": "ACQUISITION_PRIORITY_INITIALIZATION_ONLY", "daily_files": [],
                  "excluded_priority_files": []}
    return {"by_day": by_day, "provenance": provenance}


def load_priority_history(replay_root: Path, history_root: Path, model_sha256: str = MODEL_SHA256,
                          *, expected_replay_hashes: dict | None = None,
                          recomputed_root: Path | None = None) -> dict:
    expected = dict(REPLAY_HASHES if expected_replay_hashes is None else expected_replay_hashes)
    if set(expected) != set(REPLAY_HASHES) or model_sha256 != MODEL_SHA256:
        raise InputError("UNSUPPORTED_PRIORITY_SOURCE_IDENTITY")
    recomputed_root = (Path(recomputed_root) if recomputed_root is not None
                       else Path(history_root).parent.parent / "A2_historical_top40")
    source = _recomputed_priority(recomputed_root, model_sha256)
    if source is None:
        source = _legacy_priority(replay_root, expected, model_sha256)
    by_day, provenance = source["by_day"], source["provenance"]
    bootstrap_records = [row for day in sorted(by_day) for row in by_day[day]]
    latest = {}
    for path in sorted(Path(history_root).glob("*.json")):
        payload = _json(path)
        if payload.get("status") != "READY":
            continue
        if payload.get("model_id") != MODEL_ID or payload.get("model_sha256") != model_sha256:
            raise InputError(f"DAILY_HISTORY_MODEL_MISMATCH:{path.name}")
        manifest_sha = payload.get("input_manifest_sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", str(manifest_sha)) or not payload.get("run_id"):
            raise InputError("DAILY_HISTORY_INPUT_IDENTITY_MISSING")
        stamp = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise InputError("DAILY_HISTORY_GENERATED_TIMEZONE_REQUIRED")
        day = str(payload["data_date"])
        ranking = payload["ranked_rows"]
        if 20 <= len(ranking) < 40:
            ranks = sorted(float(row["rank"]) for row in ranking)
            if ranks == list(range(1, len(ranking) + 1)) and len({row["ticker"] for row in ranking}) == len(ranking):
                provenance["excluded_priority_files"].append({"path": str(path), "data_date": day,
                    "reason": "RECOMMENDATION_VALID_BUT_FULL_TOP40_NOT_AVAILABLE"})
                continue
        records = _top40_records(payload["ranked_rows"], day, "daily_recommendation",
                                 f"{model_sha256}:daily_recommendation:{manifest_sha}")
        if day not in latest or stamp > latest[day]:
            latest[day] = stamp
            by_day[day] = records
        provenance["daily_files"].append({"path": str(path), "sha256": sha256_file(path),
                                           "data_date": day, "run_id": payload["run_id"]})
    records = [row for day in sorted(latest) for row in by_day[day]]
    return {"records": records, "bootstrap_records": bootstrap_records,
            "provenance": provenance, "available_dates": sorted(by_day)}
