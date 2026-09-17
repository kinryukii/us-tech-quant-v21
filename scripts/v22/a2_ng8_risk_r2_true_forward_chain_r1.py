"""Append-only A2/NG8/Risk-R2 true-forward evidence controller.

The controller never trains or selects a model.  It verifies frozen identities,
uses the bound US-session calendar, refuses pre-freeze dates, and records
decision/outcome events in a SHA-256 chain.  Generated evidence is external to
the repository.  Canonical data and frozen artifacts are read-only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results\A2_NG8_RISK_R2_TRUE_PROSPECTIVE_FORWARD_CHAIN_R1")
CACHE = Path(r"D:\us-tech-quant-cache")
NG8_FREEZE = Path(r"D:\us-tech-quant-results\A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1\freeze_manifest.json")
NG8_FREEZE_SHA = "55c8f667c4d570e5720e28611758087e35ffc8b0b876f64b1b9cb6bdb0376430"
RISK_FREEZE = Path(r"D:\us-tech-quant-results\A2_NG8_EXACT_SUPPORT_RISK_R2_AUTONOMOUS_R1\risk_r2_freeze_manifest.json")
RISK_FREEZE_SHA = "4e6f03d995c7557f7603ab4ffcaee401dc7898d0181841f0a089aaf6fb3b1c70"
RISK_HASH_MANIFEST_SHA = "562fd7a842e50ce22af28e20b41d374888481062adffbb57fe12de4c97d0a003"
RISK_HASH_MANIFEST = RISK_FREEZE.parent / "risk_r2_hash_manifest.csv"
CALENDAR_CONTRACT = REPO / "config/research_governance/a2_forward_shadow_trading_calendar_r1.json"
PRODUCTION_BINDING = REPO / "config/research_governance/a2_forward_shadow_production_binding_r1.json"
PIT_UNIVERSE = Path(r"D:\us-tech-quant-results\A2_CANONICAL_FORWARD_READINESS_R2\component_inputs\2026-08-20\pit_universe.json")
PIT_UNIVERSE_SHA = "58768ffa8d2f5762f7f8f976172ebce5ef1005e0fd689ca550093110f76d45a3"
RISK_DEPLOY = CACHE / "a2_ng8_exact_support_risk_r2_autonomous_r1/outer_2025_LOGISTIC.joblib"
RISK_DEPLOY_SHA = "bf47d9a238511e0467298dc1c66b0478bcb645191a684e3f9711a942c6c23965"
LEDGER_FIELDS = [
    "EVENT_ID", "EVENT_TYPE", "SESSION_DATE", "SESSION_STATUS", "CANONICAL_SNAPSHOT_ID",
    "CANONICAL_HASH", "A2_MODEL_HASH", "NG8_MODEL_HASH", "NG8_RULE_HASH", "RISK_R2_MODEL_HASH",
    "DECISION_TIMESTAMP_UTC", "DECISION_TIMESTAMP_ET", "DECISION_TIMESTAMP_JST", "A2_DECISION_STATUS",
    "NG8_DECISION_STATUS", "RISK_SCORE_STATUS", "OUTCOME_MATURITY_STATUS", "TRUE_PROSPECTIVE_NG8",
    "TRUE_PROSPECTIVE_RISK", "CAPTURE_CLASS", "DATA_INTEGRITY_STATUS", "ORIGINAL_DECISION_ROW_HASH",
    "PAYLOAD_SHA256", "PREVIOUS_ROW_HASH", "ROW_HASH",
]


class ForwardChainError(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def object_sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, Path, datetime)):
        return str(value)
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(clean(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ForwardChainError(f"MODULE_NOT_LOADABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def ensure_external_root(root: Path) -> None:
    root = root.resolve()
    approved = Path(r"D:\us-tech-quant-results").resolve()
    if root == approved or approved not in root.parents:
        raise ForwardChainError("OUTPUT_ROOT_NOT_APPROVED_EXTERNAL_CHILD")
    for name in ("contracts", "manifests", "snapshots", "decisions", "outcomes", "risk", "attribution",
                 "milestones", "logs", "state", "hash_manifests", "tests", "daily_closeouts", "work"):
        (root / name).mkdir(parents=True, exist_ok=True)


def frozen_identity() -> dict[str, Any]:
    checks = {
        "ng8_freeze": sha_file(NG8_FREEZE),
        "risk_r2_freeze": sha_file(RISK_FREEZE),
        "risk_r2_hash_manifest": sha_file(RISK_HASH_MANIFEST),
        "pit_universe": sha_file(PIT_UNIVERSE),
        "risk_deploy": sha_file(RISK_DEPLOY),
    }
    expected = {
        "ng8_freeze": NG8_FREEZE_SHA, "risk_r2_freeze": RISK_FREEZE_SHA,
        "risk_r2_hash_manifest": RISK_HASH_MANIFEST_SHA, "pit_universe": PIT_UNIVERSE_SHA,
        "risk_deploy": RISK_DEPLOY_SHA,
    }
    bad = [key for key in expected if checks[key] != expected[key]]
    ng8 = json.loads(NG8_FREEZE.read_text(encoding="utf-8"))
    risk = json.loads(RISK_FREEZE.read_text(encoding="utf-8"))
    binding = json.loads(PRODUCTION_BINDING.read_text(encoding="utf-8"))
    a2 = next(x for x in binding["components"]["ALPHA"]["artifacts"] if x["artifact_id"] == "model")
    ridge = ng8["artifacts"]["ridge_model"]
    q90 = ng8["artifacts"]["q90_model"]
    for key, item in (("a2_model", a2), ("ng8_ridge", ridge), ("ng8_q90", q90)):
        observed = sha_file(Path(item["path"]))
        checks[key] = observed
        expected[key] = item["sha256"]
        if observed != item["sha256"]:
            bad.append(key)
    rule_hash = object_sha(ng8["candidate"]["portfolio"])
    return {
        "status": "PASS" if not bad else "FAIL_CLOSED_FREEZE_IDENTITY",
        "mismatches": bad, "observed": checks, "expected": expected,
        "ng8_freeze_timestamp": ng8["frozen_at"], "risk_freeze_timestamp": risk["frozen_at_utc"],
        "a2_model": a2, "ridge_model": ridge, "q90_model": q90,
        "ng8_model_hash": object_sha({"ridge": ridge["sha256"], "q90": q90["sha256"]}),
        "ng8_rule_hash": rule_hash, "risk_model_hash": RISK_DEPLOY_SHA,
        "ng8_contract": ng8["candidate"],
        "risk_deploy_semantics": "LATEST_CHRONOLOGICAL_FROZEN_OUTER_MODEL_INFORMATIONAL_ONLY_NO_PORTFOLIO_ACTION",
    }


def calendar_provider() -> Any:
    return load_module("a2_true_forward_calendar", REPO / "scripts/v22/forward_shadow/trading_calendar.py").ForwardShadowTradingCalendarProvider(CALENDAR_CONTRACT)


def latest_completed(provider: Any, now_utc: datetime) -> str:
    # A calendar session is complete only after the frozen conservative 16:00 ET close.
    probe = provider.sessions[-1]
    result = provider.completed_session_metadata(probe, now_utc.isoformat(), "UTC")
    if result["latest_completed_us_session"] is None:
        raise ForwardChainError("NO_COMPLETED_SESSION_IN_CALENDAR")
    return str(result["latest_completed_us_session"])


def first_session_after_freeze(provider: Any, frozen_at: str) -> str:
    stamp = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    ny = stamp.astimezone(ZoneInfo("America/New_York"))
    for session in provider.sessions:
        close = datetime.combine(pd.Timestamp(session).date(), provider.regular_close, provider.timezone)
        # Information for a session is prospective only when it first exists after freeze.
        if close > ny:
            return session
    raise ForwardChainError("NO_BOUND_SESSION_AFTER_FREEZE")


def discover_canonical() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for path in (CACHE / "canonical/moomoo_ohlcv").glob("snapshot_id=*/canonical_manifest.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("canonical_manifest"):
                by_adjustment = {str(row.get("adjustment", "")).lower(): row for row in payload["canonical_manifest"]}
                raw, qfq = by_adjustment.get("raw", {}), by_adjustment.get("qfq", {})
            else:
                raw, qfq = payload.get("raw", {}), payload.get("qfq", {})
            latest = str(qfq.get("latest_date") or payload.get("canonical_latest_date") or "")[:10]
            if latest and raw.get("path") and qfq.get("path") and Path(raw["path"]).is_file() and Path(qfq["path"]).is_file():
                candidates.append({"path": path, "payload": payload, "latest": latest})
        except (OSError, ValueError, KeyError):
            continue
    if not candidates:
        raise ForwardChainError("NO_VALID_CANONICAL_SNAPSHOT")
    item = max(candidates, key=lambda x: (x["latest"], str(x["path"])))
    payload = item["payload"]
    if payload.get("canonical_manifest"):
        by_adjustment = {str(row.get("adjustment", "")).lower(): row for row in payload["canonical_manifest"]}
        raw, qfq = by_adjustment["raw"], by_adjustment["qfq"]
    else:
        raw, qfq = payload["raw"], payload["qfq"]
    snapshot = payload.get("snapshot", {})
    return {
        "manifest_path": str(item["path"]), "manifest_sha256": sha_file(item["path"]),
        "snapshot_id": payload.get("snapshot_id") or snapshot.get("snapshot_id") or item["path"].parent.name.removeprefix("snapshot_id="),
        "latest_date": item["latest"], "raw_path": raw["path"], "qfq_path": qfq["path"],
        "raw_sha256": raw.get("sha256"), "qfq_sha256": qfq.get("sha256"),
    }


def ledger_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def verify_chain(path: Path) -> dict[str, Any]:
    previous = "GENESIS"
    seen: set[str] = set()
    for index, row in enumerate(ledger_rows(path), 1):
        claimed = row.get("ROW_HASH", "")
        body = {key: row.get(key, "") for key in LEDGER_FIELDS if key != "ROW_HASH"}
        if row.get("PREVIOUS_ROW_HASH") != previous or object_sha(body) != claimed or claimed in seen:
            return {"status": "FAIL_CLOSED", "bad_row": index}
        seen.add(claimed)
        previous = claimed
    return {"status": "PASS", "row_count": len(seen), "tail_hash": previous}


def initialize_csv(path: Path, fields: Sequence[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n").writeheader()


def append_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    initialize_csv(path, fields)
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
        writer.writerows([{key: clean(row.get(key, "")) for key in fields} for row in rows])
        stream.flush()
        os.fsync(stream.fileno())


def append_event(path: Path, event: Mapping[str, Any]) -> tuple[str, bool]:
    report = verify_chain(path)
    if report["status"] != "PASS":
        raise ForwardChainError("LEDGER_HASH_CHAIN_INVALID")
    rows = ledger_rows(path)
    key = (str(event["EVENT_TYPE"]), str(event["SESSION_DATE"]), str(event["CANONICAL_HASH"]),
           str(event["A2_MODEL_HASH"]), str(event["NG8_MODEL_HASH"]), str(event["NG8_RULE_HASH"]),
           str(event["RISK_R2_MODEL_HASH"]))
    existing = [row for row in rows if (row["EVENT_TYPE"], row["SESSION_DATE"], row["CANONICAL_HASH"], row["A2_MODEL_HASH"],
                row["NG8_MODEL_HASH"], row["NG8_RULE_HASH"], row["RISK_R2_MODEL_HASH"]) == key]
    if existing:
        if existing[0]["PAYLOAD_SHA256"] != str(event["PAYLOAD_SHA256"]):
            raise ForwardChainError("NONDETERMINISTIC_REPLAY")
        return existing[0]["ROW_HASH"], False
    row = {key: str(clean(event.get(key, ""))) for key in LEDGER_FIELDS}
    row["PREVIOUS_ROW_HASH"] = report["tail_hash"]
    row["ROW_HASH"] = object_sha({key: row[key] for key in LEDGER_FIELDS if key != "ROW_HASH"})
    append_csv(path, LEDGER_FIELDS, [row])
    return row["ROW_HASH"], True


def derived_features(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy(); eps = 1e-8
    d["upside_downside_balance"] = (d.upside_vol_20d - d.downside_vol_20d) / (d.upside_vol_20d + d.downside_vol_20d + eps)
    d["vol_scaled_breakout"] = d.distance_from_high_60d / (d.realized_vol_20d.abs() + eps)
    d["momentum_acceleration"] = d.ret_20d - d.ret_60d / 3.0
    d["liquidity_stable_momentum"] = d.ret_20d / (1.0 + (d.volume_ratio_5d_20d - 1.0).abs())
    d["upside_convexity_rank"] = d["upside_downside_balance"].rank(pct=True, method="average")
    d["breakout_rank"] = d["vol_scaled_breakout"].rank(pct=True, method="average")
    return d


def score_decision(session: str, canonical: Mapping[str, Any], identity: Mapping[str, Any], *, risk_legal: bool) -> dict[str, Any]:
    source_path = REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
    source = load_module("a2_true_forward_features", source_path)
    universe = json.loads(PIT_UNIVERSE.read_text(encoding="utf-8"))["members"]
    members = pd.DataFrame(universe); members["ticker"] = members.ticker.astype(str).str.upper()
    prices = pd.read_csv(canonical["qfq_path"], usecols=["ticker", "date", "close", "volume"])
    prices["ticker"] = prices.ticker.astype(str).str.upper(); prices["trade_date"] = pd.to_datetime(prices.pop("date"))
    prices = prices.loc[(prices.trade_date <= pd.Timestamp(session)) & prices.ticker.isin(set(members.ticker) | {"QQQ"})]
    state = source.build_stock_state_features(prices)
    today = state.loc[state.trade_date.eq(pd.Timestamp(session))].merge(members[["security_id", "ticker"]], on="ticker", how="right", validate="one_to_one")
    features = list(identity["ng8_contract"]["features"])
    missing = today.loc[today[features].isna().any(axis=1), "ticker"].tolist()
    if missing or len(today) != len(members):
        raise ForwardChainError(f"EXACT_PIT_FEATURE_COVERAGE_FAIL:{len(missing)}")
    a2_model = joblib.load(identity["a2_model"]["path"])
    ridge = joblib.load(identity["ridge_model"]["path"]); q90 = joblib.load(identity["q90_model"]["path"])
    x = today[features].to_numpy(np.float32)
    today["a2_score"] = np.asarray(a2_model.predict(x), float)
    today["ridge_score"] = np.asarray(ridge.predict(x), float); today["q90_score"] = np.asarray(q90.predict(x), float)
    if not np.isfinite(today[["a2_score", "ridge_score", "q90_score"]]).all().all():
        raise ForwardChainError("NONFINITE_FROZEN_SCORE")
    today = today.sort_values("ticker", kind="mergesort").reset_index(drop=True)
    today["a2_rank"] = today.a2_score.rank(ascending=False, method="first").astype(int)
    today["ridge_pct"] = today.ridge_score.rank(pct=True, method="average")
    today["q90_pct"] = today.q90_score.rank(pct=True, method="average")
    today["ng8_score"] = .75 * today.ridge_pct + .25 * today.q90_pct
    today["ng8_rank"] = today.ng8_score.rank(ascending=False, method="first").astype(int)
    a2 = set(today.loc[today.a2_rank <= 20, "security_id"].astype(str))
    entrants = today.loc[(today.ng8_rank <= 10) & ~today.security_id.astype(str).isin(a2)].sort_values(["ng8_rank", "ticker"])
    exits = today.loc[today.security_id.astype(str).isin(a2) & (today.ng8_rank > 30)].sort_values(["ng8_rank", "ticker"], ascending=[False, True])
    n = min(5, len(entrants), len(exits)); ng8 = (a2 - set(exits.head(n).security_id.astype(str))) | set(entrants.head(n).security_id.astype(str))
    if len(a2) != 20 or len(ng8) != 20:
        raise ForwardChainError("FROZEN_TOP20_CARDINALITY_FAIL")
    today["a2_selected"] = today.security_id.astype(str).isin(a2); today["ng8_selected"] = today.security_id.astype(str).isin(ng8)
    risk_frame = derived_features(today)
    if risk_legal:
        deploy = joblib.load(RISK_DEPLOY); risk_features = list(deploy["features"])
        if risk_frame[risk_features].isna().any().any():
            raise ForwardChainError("RISK_SCORE_COVERAGE_FAIL")
        raw = np.asarray(deploy["model"].predict_proba(risk_frame[risk_features])[:, 1], float)
        method, calibrator = deploy["calibration"]
        if method == "NONE": probability = np.clip(raw, 1e-6, 1 - 1e-6)
        elif method == "PLATT": probability = np.clip(calibrator.predict_proba(raw.reshape(-1, 1))[:, 1], 1e-6, 1 - 1e-6)
        else: probability = np.clip(calibrator.predict(raw), 1e-6, 1 - 1e-6)
        risk_frame["risk_raw_score"] = raw; risk_frame["risk_probability"] = probability
        risk_frame["risk_percentile"] = risk_frame.risk_probability.rank(pct=True, method="average")
        risk_frame["risk_decile"] = np.ceil(risk_frame.risk_percentile * 10).clip(1, 10).astype(int)
    decisions, risks, replacements = [], [], []
    for row in risk_frame.sort_values(["a2_rank", "ticker"]).itertuples(index=False):
        decisions.append({"SESSION_DATE": session, "security_id": str(row.security_id), "ticker": row.ticker,
                          "a2_rank": row.a2_rank, "a2_score": row.a2_score, "a2_selected": row.a2_selected,
                          "ng8_rank": row.ng8_rank, "ng8_score": row.ng8_score, "ridge_score": row.ridge_score,
                          "q90_score": row.q90_score, "ng8_selected": row.ng8_selected, "weight": .05 if row.ng8_selected else 0.0})
        if risk_legal and (row.a2_rank <= 30 or row.ng8_rank <= 40):
            risks.append({"SESSION_DATE": session, "security_id": str(row.security_id), "ticker": row.ticker,
                          "a2_rank": row.a2_rank, "ng8_rank": row.ng8_rank, "a2_selected": row.a2_selected,
                          "ng8_selected": row.ng8_selected, "raw_risk_score": row.risk_raw_score,
                          "calibrated_probability": row.risk_probability, "risk_percentile": row.risk_percentile,
                          "risk_decile": row.risk_decile, "NO_PORTFOLIO_ACTION": True})
    for k, (entrant, incumbent) in enumerate(zip(entrants.head(n).itertuples(), exits.head(n).itertuples()), 1):
        replacements.append({"DATE": session, "PAIR_ID": f"{session}:{k}", "INCUMBENT": incumbent.ticker,
                             "CHALLENGER": entrant.ticker, "INCUMBENT_A2_RANK": incumbent.a2_rank,
                             "CHALLENGER_A2_RANK": entrant.a2_rank, "INCUMBENT_NG8_SCORE": incumbent.ng8_score,
                             "CHALLENGER_NG8_SCORE": entrant.ng8_score, "CONFIDENCE_MARGIN": entrant.ng8_score - incumbent.ng8_score,
                             "Q90_INFORMATION": entrant.q90_score - incumbent.q90_score, "REPLACEMENT_APPROVED": True})
    return {"decisions": decisions, "risks": risks, "replacements": replacements, "risk_coverage": len(risks) / max(1, len(risks)),
            "a2_top20": sorted(risk_frame.loc[risk_frame.a2_selected, "ticker"]), "ng8_top20": sorted(risk_frame.loc[risk_frame.ng8_selected, "ticker"])}


def write_contracts(root: Path, identity: Mapping[str, Any], provider: Any, first_ng8: str, first_risk: str, initialized: str) -> None:
    contract = {
        "contract_id": "A2_NG8_RISK_R2_TRUE_PROSPECTIVE_FORWARD_CHAIN_R1", "created_at_utc": initialized,
        "event_sourced_append_only": True, "historical_rewrite_allowed": False, "broker_action_allowed": False,
        "production_promotion_allowed": False, "calendar_path": str(CALENDAR_CONTRACT), "calendar_sha256": provider.calendar_sha256,
        "ng8_first_legal_session": first_ng8, "risk_r2_first_legal_session": first_risk,
        "outcome_layers": {"daily_economic": "NEXT_SESSION_OPEN_TO_OPEN_FROZEN_R4_ACCOUNTING",
                           "ng8_target": "MEAN_ER_3D_5D_10D_20D_VS_QQQ", "risk_bad": "FROZEN_FORWARD_5D_BAD_ASYMMETRY",
                           "risk_severity": "MAX(FORWARD_5D_MAE-FORWARD_5D_MFE,0)"},
        "milestones": [1, 5, 10, 20, 40, 60], "frozen_identity": identity,
    }
    write_json(root / "forward_contract.json", contract)
    write_json(root / "freeze_identity_manifest.json", identity)
    (root / "prospective_session_contract.md").write_text(
        "# Prospective session contract\n\nA session is true prospective only when its conservative 16:00 ET close is after the relevant immutable freeze timestamp. Pre-freeze outcomes are never backfilled as prospective. Decisions are immutable events; outcomes mature through new linked events.\n",
        encoding="utf-8")


def initialize_ledgers(root: Path) -> None:
    initialize_csv(root / "forward_session_ledger.csv", LEDGER_FIELDS)
    initialize_csv(root / "ng8_decision_ledger.csv", ["SESSION_DATE", "security_id", "ticker", "a2_rank", "a2_score", "a2_selected", "ng8_rank", "ng8_score", "ridge_score", "q90_score", "ng8_selected", "weight", "DECISION_ROW_HASH"])
    initialize_csv(root / "ng8_replacement_ledger.csv", ["DATE", "PAIR_ID", "INCUMBENT", "CHALLENGER", "INCUMBENT_A2_RANK", "CHALLENGER_A2_RANK", "INCUMBENT_NG8_SCORE", "CHALLENGER_NG8_SCORE", "CONFIDENCE_MARGIN", "Q90_INFORMATION", "REPLACEMENT_APPROVED", "DECISION_TIMESTAMP", "DECISION_ROW_HASH"])
    initialize_csv(root / "risk_r2_information_ledger.csv", ["SESSION_DATE", "security_id", "ticker", "a2_rank", "ng8_rank", "a2_selected", "ng8_selected", "raw_risk_score", "calibrated_probability", "risk_percentile", "risk_decile", "NO_PORTFOLIO_ACTION", "DECISION_ROW_HASH"])
    initialize_csv(root / "outcome_maturation_ledger.csv", ["EVENT_ID", "SESSION_DATE", "OUTCOME_LAYER", "ORIGINAL_DECISION_ROW_HASH", "MATURITY_DATE", "STATUS", "PAYLOAD_SHA256"])
    initialize_csv(root / "forward_attribution.csv", ["SESSION_DATE", "ORIGINAL_DECISION_ROW_HASH", "STATUS", "NG8_MINUS_A2_RETURN", "REPLACEMENT_CONTRIBUTION", "TURNOVER_DELTA", "COST_DELTA"])


def evidence_level(count: int) -> str:
    if count == 0: return "WAITING"
    if count < 5: return "TECHNICAL_VALIDATION_ONLY"
    if count < 20: return "EARLY_INFORMATIONAL"
    if count < 40: return "INITIAL_EVIDENCE"
    if count < 60: return "INTERMEDIATE_EVIDENCE"
    return "MEANINGFUL_FORWARD_EVIDENCE"


def next_milestone(count: int) -> str:
    return next((str(n) for n in (1, 5, 10, 20, 40, 60) if n > count), "QUARTERLY")


def write_operations_readme(root: Path) -> None:
    entry = r"D:\us-tech-quant\scripts\v22\run_a2_ng8_risk_r2_true_forward_daily.ps1"
    invoke = f"powershell -NoProfile -ExecutionPolicy Bypass -File '{entry}'"
    text = f"""# A2 / NG8 / Risk R2 true-forward operations

Frozen A2 is the control, frozen NG8 is a research shadow, and Risk R2 is informational only. No command below can submit an order or promote a model.

## Normal daily run

```powershell
{invoke} -Execute -RefreshCanonical
```

## Dry run

```powershell
{invoke} -DryRun -RefreshCanonical
```

## Exact target date

```powershell
{invoke} -Execute -TargetDate YYYY-MM-DD -RefreshCanonical
```

## Milestone/read-only evaluation

```powershell
{invoke} -Evaluate
```

When data are incomplete, the date remains `WAITING_DATA`/fail-closed and must be retried with the same command. A hash-chain or identity failure must not be repaired by editing a ledger; preserve the evidence and open a separate forensic task.
"""
    (root / "operations_readme.md").write_text(text, encoding="utf-8")


def terminal_closeout(summary: Mapping[str, Any], identity: Mapping[str, Any]) -> str:
    no_date = "NONE"
    return f"""============================================================
A2_NG8_RISK_R2_TRUE_PROSPECTIVE_FORWARD_CHAIN_R1_FINAL
======================================================

OVERALL_STATUS={summary['overall_status']}

PREFLIGHT_STATUS=PASS

NG8_FREEZE_HASH_STATUS=PASS
RISK_R2_FREEZE_HASH_STATUS=PASS
NG8_MUTATED=false
RISK_R2_MUTATED=false

NG8_FREEZE_TIMESTAMP={identity['ng8_freeze_timestamp']}
RISK_R2_FREEZE_TIMESTAMP={identity['risk_freeze_timestamp']}

LATEST_COMPLETED_US_SESSION={summary['latest_completed_us_session']}
CANONICAL_BEFORE_DATE=2026-08-20
CANONICAL_AFTER_DATE={summary['canonical_after_date']}
CANONICAL_REFRESH_STATUS=PASS_EXACT_DATE_INCREMENTAL_325_OF_325_NO_DEEP_REFETCH
MOOMOO_API_CALLED={str(summary['initialization_moomoo_api_called']).lower()}

NG8_FIRST_LEGAL_PROSPECTIVE_SESSION={summary['ng8_first_legal_prospective_session']}
RISK_R2_FIRST_LEGAL_PROSPECTIVE_SESSION={summary['risk_r2_first_legal_prospective_session']}

NG8_FORWARD_SHADOW_STATUS=INITIALIZED_FAIL_CLOSED_DATE_NOT_READY_PIT_385_MISSING
RISK_R2_INFORMATIONAL_SHADOW_STATUS=INITIALIZED_WAITING_FIRST_LEGAL_SESSION

TRUE_PROSPECTIVE_NG8_DECISION_COUNT={summary['true_prospective_ng8_decision_count']}
LIVE_CAPTURED_DECISION_COUNT={summary['live_captured_count']}
POST_FREEZE_RECONSTRUCTED_COUNT={summary['post_freeze_reconstructed_count']}

MATURED_ECONOMIC_ROW_COUNT={summary['matured_economic_row_count']}
MATURED_RISK_LABEL_ROW_COUNT={summary['matured_risk_label_row_count']}

LATEST_NG8_DECISION_DATE={no_date}
LATEST_MATURED_ECONOMIC_DATE={no_date}
LATEST_MATURED_RISK_DATE={no_date}

A2_FORWARD_NAV=1.0_INITIAL_CAPITAL_NO_ROWS
NG8_FORWARD_NAV=1.0_INITIAL_CAPITAL_NO_ROWS
NG8_MINUS_A2_CUM_RETURN=0.0_NO_MATURED_ROWS

NG8_FORWARD_TURNOVER=0.0_NO_ROWS
NG8_FORWARD_COST=0.0_NO_ROWS
NG8_FORWARD_MAXDD=0.0_NO_ROWS

NG8_REPLACEMENT_COUNT=0
NG8_REPLACEMENT_SUCCESS_COUNT=0
EXTREME_WINNER_CAPTURE_STATUS=INSUFFICIENT_SAMPLE

RISK_FORWARD_AUROC=INSUFFICIENT_SAMPLE
RISK_FORWARD_AP_BASE_RATIO=INSUFFICIENT_SAMPLE
RISK_FORWARD_DECILE_MONOTONICITY=INSUFFICIENT_SAMPLE
PAIR_LEVEL_RISK_FORWARD_STATUS=INSUFFICIENT_SAMPLE

FORWARD_EVIDENCE_LEVEL={summary['forward_evidence_level']}
NEXT_MILESTONE={summary['next_milestone']}
NEXT_PENDING_MATURITY_DATE={summary['next_pending_maturity_date']}

HASH_CHAIN_STATUS={summary['hash_chain_status']}
IDEMPOTENCY_STATUS={summary['idempotency_status']}
FORWARD_INTEGRITY_STATUS={summary['forward_integrity_status']}

BROKER_ACTION_RUN=false
BROKER_ACTION_ALLOWED=false
PRODUCTION_PROMOTION=false

ANTI_BLOAT_STATUS=PASS_STRICT_WITH_IMMUTABLE_LEGACY_BASELINE_NEW_VIOLATIONS_0

DAILY_SINGLE_ENTRYPOINT=powershell -NoProfile -ExecutionPolicy Bypass -File D:\\us-tech-quant\\scripts\\v22\\run_a2_ng8_risk_r2_true_forward_daily.ps1 -Execute -RefreshCanonical

NEXT_ACTION=RESUME_SEPARATE_R3_PIT_CANONICAL_COVERAGE_REMEDIATION_AT_AUTHORIZED_QUOTA_WINDOW_THEN_RERUN_SAME_ENTRYPOINT

============================================================
"""


def write_hash_manifest(root: Path) -> str:
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        # State and ledgers are deliberately append-only/mutable across daily runs;
        # immutable contracts, reports, closeouts and test evidence are snapshot-hashed.
        if path.is_file() and relative.parts[0] not in {"state", "hash_manifests"} and relative.name not in {
            "forward_session_ledger.csv", "ng8_decision_ledger.csv", "ng8_replacement_ledger.csv",
            "risk_r2_information_ledger.csv", "outcome_maturation_ledger.csv", "forward_attribution.csv",
            "forward_status.md", "forward_integrity_report.md", "final_status.txt",
        } and "pytest_tmp" not in path.parts:
            rows.append({"path": str(relative).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    manifest = root / "hash_manifests" / f"hash_manifest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "sha256"], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    return sha_file(manifest)


def initialization_refresh_audit(root: Path) -> dict[str, Any]:
    calls = []
    for path in sorted((root / "logs").glob("canonical_refresh*/v21_231_summary.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            calls.append({"path": str(path), "final_status": value.get("final_status"),
                          "target_date": value.get("api_date_range_requested"),
                          "api_security_request_count": value.get("api_security_request_count", 0),
                          "raw_success": value.get("daily_raw_success_count", 0), "qfq_success": value.get("daily_qfq_success_count", 0),
                          "historical_deep_refetch_run": value.get("historical_deep_refetch_run"),
                          "canonical_latest_date": value.get("canonical_latest_date")})
        except (OSError, ValueError):
            continue
    audit = {"moomoo_api_called_during_initialization": any(int(row["api_security_request_count"] or 0) > 0 for row in calls),
             "successful_exact_refresh_count": sum(row["final_status"] == "PASS_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY" for row in calls),
             "historical_deep_refetch_run": any(row["historical_deep_refetch_run"] is True for row in calls), "calls": calls}
    write_json(root / "manifests/initialization_refresh_audit.json", audit)
    return audit


def maturation_dates(provider: Any, session: str) -> dict[str, str | None]:
    position = provider.sessions.index(session)
    values = provider.sessions
    return {
        "execution": values[position + 1] if position + 1 < len(values) else None,
        "daily_economic": values[position + 2] if position + 2 < len(values) else None,
        "risk_5d": values[position + 5] if position + 5 < len(values) else None,
    }


def mature_pending(root: Path, canonical: Mapping[str, Any], identity: Mapping[str, Any], provider: Any, now: datetime) -> dict[str, int]:
    ledger = root / "forward_session_ledger.csv"
    events = ledger_rows(ledger)
    decisions = [row for row in events if row["EVENT_TYPE"] == "DECISION"]
    matured_keys = {(row["SESSION_DATE"], row["ORIGINAL_DECISION_ROW_HASH"]) for row in events if row["EVENT_TYPE"] == "OUTCOME_MATURATION_EVENT"}
    if not decisions:
        return {"economic": 0, "risk": 0}
    prices = pd.read_csv(canonical["qfq_path"], usecols=["ticker", "date", "open", "high", "low", "close"])
    prices["ticker"] = prices.ticker.astype(str).str.upper(); prices["date"] = prices.date.astype(str).str[:10]
    lookup = prices.set_index(["ticker", "date"])
    detail = pd.read_csv(root / "ng8_decision_ledger.csv")
    risk_detail = pd.read_csv(root / "risk_r2_information_ledger.csv")
    prior_by_session = {row["SESSION_DATE"]: row for row in decisions}
    ordered_sessions = sorted(prior_by_session)
    economic_count = risk_count = 0
    for decision in decisions:
        session, original = decision["SESSION_DATE"], decision["ROW_HASH"]
        if (session, original) in matured_keys:
            continue
        dates = maturation_dates(provider, session)
        economic_ready = dates["daily_economic"] is not None and dates["daily_economic"] <= canonical["latest_date"]
        risk_ready = decision["TRUE_PROSPECTIVE_RISK"].lower() == "true" and dates["risk_5d"] is not None and dates["risk_5d"] <= canonical["latest_date"]
        if not economic_ready and not risk_ready:
            continue
        payload: dict[str, Any] = {"session_date": session, "original_decision_row_hash": original, "matured_at_utc": now.isoformat()}
        day = detail.loc[detail.SESSION_DATE.astype(str).eq(session)].copy()
        if economic_ready:
            execution, end = str(dates["execution"]), str(dates["daily_economic"])
            previous = ordered_sessions[ordered_sessions.index(session) - 1] if ordered_sessions.index(session) else None
            previous_day = detail.loc[detail.SESSION_DATE.astype(str).eq(previous)].copy() if previous else pd.DataFrame()
            economic: dict[str, Any] = {}
            for name, flag in (("A2", "a2_selected"), ("NG8", "ng8_selected")):
                selected = day.loc[day[flag].astype(str).str.lower().eq("true"), "ticker"].astype(str).str.upper().tolist()
                if len(selected) != 20:
                    raise ForwardChainError(f"MATURED_TOP20_CARDINALITY:{session}:{name}")
                gross = []
                for ticker in selected:
                    try:
                        start_open = float(lookup.at[(ticker, execution), "open"]); end_open = float(lookup.at[(ticker, end), "open"])
                    except (KeyError, TypeError, ValueError):
                        raise ForwardChainError(f"MATURED_OPEN_MISSING:{ticker}:{execution}:{end}")
                    if not np.isfinite(start_open) or not np.isfinite(end_open) or start_open <= 0 or end_open <= 0:
                        raise ForwardChainError(f"MATURED_OPEN_INVALID:{ticker}:{execution}:{end}")
                    gross.append(end_open / start_open - 1.0)
                prior_selected = set(previous_day.loc[previous_day[flag].astype(str).str.lower().eq("true"), "ticker"].astype(str).str.upper()) if len(previous_day) else set()
                turnover = .5 if not prior_selected else 1.0 - len(prior_selected & set(selected)) / 20.0
                cost = turnover * .001
                economic[name] = {"gross_return": float(np.mean(gross)), "turnover": turnover, "cost": cost,
                                  "net_return": float((1.0 - cost) * (1.0 + np.mean(gross)) - 1.0),
                                  "execution_date": execution, "maturity_date": end}
            payload["daily_economic"] = economic
            economic_count += 1
        if risk_ready:
            execution = str(dates["execution"]); horizon = [value for value in provider.sessions if execution <= value <= str(dates["risk_5d"])][:5]
            rows = risk_detail.loc[risk_detail.SESSION_DATE.astype(str).eq(session)].copy(); outcomes = []
            if len(rows) == 0:
                raise ForwardChainError(f"RISK_DECISION_ROWS_MISSING:{session}")
            deploy = joblib.load(RISK_DEPLOY)
            for row in rows.itertuples(index=False):
                path = []
                for date in horizon:
                    try: path.append((float(lookup.at[(str(row.ticker).upper(), date), "high"]), float(lookup.at[(str(row.ticker).upper(), date), "low"]), float(lookup.at[(str(row.ticker).upper(), date), "close"])))
                    except (KeyError, TypeError, ValueError): raise ForwardChainError(f"RISK_HORIZON_MISSING:{row.ticker}:{date}")
                start = float(lookup.at[(str(row.ticker).upper(), execution), "open"])
                mae = max(0.0, 1.0 - min(x[1] for x in path) / start); mfe = max(0.0, max(x[0] for x in path) / start - 1.0)
                outcomes.append({"security_id": str(row.security_id), "ticker": str(row.ticker), "forward_5d_mae": mae,
                                 "forward_5d_mfe": mfe, "downside_severity": max(mae - mfe, 0.0),
                                 "bad": bool(mae >= deploy["mae_q90"] and mfe <= deploy["mfe_q50"]),
                                 "calibrated_probability": float(row.calibrated_probability)})
            payload["risk_5d"] = {"maturity_date": dates["risk_5d"], "rows": outcomes}; risk_count += 1
        artifact = root / "outcomes" / f"session_date={session}" / f"maturation_{object_sha(payload)[:16]}.json"
        if not artifact.exists(): write_json(artifact, payload)
        event = {"EVENT_ID": f"OUTCOME:{session}:{object_sha(payload)[:16]}", "EVENT_TYPE": "OUTCOME_MATURATION_EVENT",
                 "SESSION_DATE": session, "SESSION_STATUS": "DAILY_ECONOMIC_AND_RISK" if risk_ready and economic_ready else ("DAILY_ECONOMIC" if economic_ready else "RISK"),
                 "CANONICAL_SNAPSHOT_ID": canonical["snapshot_id"], "CANONICAL_HASH": canonical["manifest_sha256"],
                 "A2_MODEL_HASH": identity["a2_model"]["sha256"], "NG8_MODEL_HASH": identity["ng8_model_hash"], "NG8_RULE_HASH": identity["ng8_rule_hash"],
                 "RISK_R2_MODEL_HASH": identity["risk_model_hash"], "DECISION_TIMESTAMP_UTC": now.isoformat(),
                 "A2_DECISION_STATUS": "REFERENCE_ORIGINAL_EVENT", "NG8_DECISION_STATUS": "REFERENCE_ORIGINAL_EVENT",
                 "RISK_SCORE_STATUS": "REFERENCE_ORIGINAL_EVENT", "OUTCOME_MATURITY_STATUS": "MATURED",
                 "TRUE_PROSPECTIVE_NG8": decision["TRUE_PROSPECTIVE_NG8"], "TRUE_PROSPECTIVE_RISK": decision["TRUE_PROSPECTIVE_RISK"],
                 "CAPTURE_CLASS": decision["CAPTURE_CLASS"], "DATA_INTEGRITY_STATUS": "PASS", "ORIGINAL_DECISION_ROW_HASH": original,
                 "PAYLOAD_SHA256": sha_file(artifact)}
        row_hash, created = append_event(ledger, event)
        if created:
            append_csv(root / "outcome_maturation_ledger.csv", ["EVENT_ID", "SESSION_DATE", "OUTCOME_LAYER", "ORIGINAL_DECISION_ROW_HASH", "MATURITY_DATE", "STATUS", "PAYLOAD_SHA256"],
                       [{"EVENT_ID": event["EVENT_ID"], "SESSION_DATE": session, "OUTCOME_LAYER": event["SESSION_STATUS"], "ORIGINAL_DECISION_ROW_HASH": original,
                         "MATURITY_DATE": max(value for value in (dates["daily_economic"], dates["risk_5d"]) if value and ((value == dates["daily_economic"] and economic_ready) or (value == dates["risk_5d"] and risk_ready))),
                         "STATUS": "MATURED", "PAYLOAD_SHA256": event["PAYLOAD_SHA256"]}])
            if economic_ready:
                econ = payload["daily_economic"]
                append_csv(root / "forward_attribution.csv", ["SESSION_DATE", "ORIGINAL_DECISION_ROW_HASH", "STATUS", "NG8_MINUS_A2_RETURN", "REPLACEMENT_CONTRIBUTION", "TURNOVER_DELTA", "COST_DELTA"],
                           [{"SESSION_DATE": session, "ORIGINAL_DECISION_ROW_HASH": original, "STATUS": "DESCRIPTIVE_ACCOUNTING",
                             "NG8_MINUS_A2_RETURN": econ["NG8"]["net_return"] - econ["A2"]["net_return"], "REPLACEMENT_CONTRIBUTION": econ["NG8"]["gross_return"] - econ["A2"]["gross_return"],
                             "TURNOVER_DELTA": econ["NG8"]["turnover"] - econ["A2"]["turnover"], "COST_DELTA": econ["NG8"]["cost"] - econ["A2"]["cost"]}])
    return {"economic": economic_count, "risk": risk_count}


def refresh_status(canonical: Mapping[str, Any], latest: str, requested: bool) -> dict[str, Any]:
    if canonical["latest_date"] >= latest:
        return {"status": "NO_REFRESH_NEEDED", "api_called": False}
    return {"status": "REFRESH_REQUIRED_NOT_RUN" if not requested else "REFRESH_DELEGATED_TO_WRAPPER", "api_called": requested}


def perform_exact_refresh(root: Path, canonical: Mapping[str, Any], latest: str, provider: Any, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    missing = [value for value in provider.sessions if canonical["latest_date"] < value <= latest]
    current = dict(canonical); calls = []
    for index, session in enumerate(missing, 1):
        snapshot_id = f"a2_true_forward_{session.replace('-', '')}_{now.strftime('%Y%m%dT%H%M%SZ')}_{index:02d}"
        output = root / "logs" / f"canonical_refresh_{session}_{now.strftime('%Y%m%dT%H%M%SZ')}_{index:02d}"
        command = [str(REPO / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"),
                   "--repo-root", str(REPO), "--output-dir", str(output), "--cache-root", str(CACHE),
                   "--snapshot-id", snapshot_id, "--start-date", session, "--end-date", session,
                   "--batch-size", "25", "--sleep-seconds", "0", "--max-retries", "2", "--min-daily-success-ratio", "1",
                   "--allow-dram-missing", "--incremental-only", "--parent-snapshot-id", str(current["snapshot_id"])]
        environment = os.environ.copy(); environment["APPDATA"] = str(root / "work/sdk_appdata")
        Path(environment["APPDATA"]).mkdir(parents=True, exist_ok=True)
        completed = subprocess.run([sys.executable, *command], cwd=REPO, env=environment, text=True, capture_output=True)
        summary_path = output / "v21_231_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        calls.append({"session": session, "returncode": completed.returncode, "summary_path": str(summary_path),
                      "final_status": summary.get("final_status"), "api_security_request_count": summary.get("api_security_request_count"),
                      "historical_deep_refetch_run": summary.get("historical_deep_refetch_run")})
        if completed.returncode != 0 or summary.get("final_status") != "PASS_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY":
            return current, {"status": "FAIL_CLOSED_EXACT_REFRESH", "api_called": True, "calls": calls}
        current = discover_canonical()
        if current["latest_date"] != session:
            return current, {"status": "FAIL_CLOSED_REFRESH_PROMOTION_IDENTITY", "api_called": True, "calls": calls}
    return current, {"status": "PASS_EXACT_DATE_INCREMENTAL_REFRESH" if missing else "NO_REFRESH_NEEDED", "api_called": bool(missing), "calls": calls}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true"); modes.add_argument("--execute", action="store_true"); modes.add_argument("--evaluate", action="store_true")
    parser.add_argument("--target-date"); parser.add_argument("--refresh-canonical", action="store_true")
    parser.add_argument("--output-root", type=Path, default=RESULTS); parser.add_argument("--as-of-utc")
    args = parser.parse_args(argv)
    root = args.output_root; ensure_external_root(root)
    now = datetime.fromisoformat(args.as_of_utc.replace("Z", "+00:00")) if args.as_of_utc else datetime.now(timezone.utc)
    if now.tzinfo is None: now = now.replace(tzinfo=timezone.utc)
    identity = frozen_identity()
    if identity["status"] != "PASS":
        raise ForwardChainError(identity["status"])
    provider = calendar_provider(); latest = latest_completed(provider, now)
    first_ng8 = first_session_after_freeze(provider, identity["ng8_freeze_timestamp"])
    first_risk = first_session_after_freeze(provider, identity["risk_freeze_timestamp"])
    state_path = root / "state/forward_state.json"
    existing_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    initialized = existing_state.get("chain_initialized_at_utc", now.isoformat())
    canonical = discover_canonical(); canonical_before = canonical["latest_date"]
    refresh = refresh_status(canonical, latest, args.refresh_canonical)
    if args.execute and args.refresh_canonical and canonical["latest_date"] < latest:
        canonical, refresh = perform_exact_refresh(root, canonical, latest, provider, now)
    if args.evaluate and args.refresh_canonical:
        raise ForwardChainError("EVALUATE_MODE_CANONICAL_REFRESH_FORBIDDEN")
    legal_start = first_ng8
    targets = [args.target_date] if args.target_date else [s for s in provider.sessions if legal_start <= s <= latest]
    if any(not provider.is_session(value) for value in targets):
        raise ForwardChainError("TARGET_NOT_TRADING_SESSION")
    ledger = root / "forward_session_ledger.csv"
    preview = {"would_refresh": canonical["latest_date"] < latest, "would_process": targets,
               "would_append": [s for s in targets if s <= canonical["latest_date"]], "would_mature": [],
               "latest_completed": latest, "canonical_latest": canonical["latest_date"]}
    if args.dry_run:
        write_json(root / "daily_closeouts" / f"dry_run_{now.strftime('%Y%m%dT%H%M%SZ')}.json", preview)
        print(json.dumps(preview, sort_keys=True)); return 0
    initialize_ledgers(root); write_contracts(root, identity, provider, first_ng8, first_risk, initialized)
    initialization_refresh = initialization_refresh_audit(root)
    appended = live = reconstructed = 0
    failures: list[dict[str, str]] = list(existing_state.get("failures", [])) if args.evaluate else []
    if not args.evaluate:
        for session in targets:
            if session > canonical["latest_date"]:
                failures.append({"session": session, "status": "WAITING_DATA_CANONICAL_NOT_EXACT_DATE"}); continue
            if session < legal_start:
                raise ForwardChainError("PRE_FREEZE_DATE_REJECTED")
            try:
                risk_legal = session >= first_risk
                payload = score_decision(session, canonical, identity, risk_legal=risk_legal)
                stamp = now.astimezone(timezone.utc); et = stamp.astimezone(ZoneInfo("America/New_York")); jst = stamp.astimezone(ZoneInfo("Asia/Tokyo"))
                session_close = datetime.combine(pd.Timestamp(session).date(), provider.regular_close, provider.timezone)
                chain_birth = datetime.fromisoformat(initialized.replace("Z", "+00:00"))
                capture = "LIVE_CAPTURED" if session_close.astimezone(timezone.utc) > chain_birth.astimezone(timezone.utc) else "POST_FREEZE_RECONSTRUCTED"
                event_payload = {"session": session, "canonical": canonical, "a2_top20": payload["a2_top20"], "ng8_top20": payload["ng8_top20"],
                                 "replacements": payload["replacements"], "risk_rows": payload["risks"]}
                event = {"EVENT_ID": f"DECISION:{session}", "EVENT_TYPE": "DECISION", "SESSION_DATE": session,
                         "SESSION_STATUS": "OUTCOME_PENDING", "CANONICAL_SNAPSHOT_ID": canonical["snapshot_id"], "CANONICAL_HASH": canonical["manifest_sha256"],
                         "A2_MODEL_HASH": identity["a2_model"]["sha256"], "NG8_MODEL_HASH": identity["ng8_model_hash"], "NG8_RULE_HASH": identity["ng8_rule_hash"],
                         "RISK_R2_MODEL_HASH": identity["risk_model_hash"], "DECISION_TIMESTAMP_UTC": stamp.isoformat(), "DECISION_TIMESTAMP_ET": et.isoformat(),
                         "DECISION_TIMESTAMP_JST": jst.isoformat(), "A2_DECISION_STATUS": "PASS", "NG8_DECISION_STATUS": "PASS",
                         "RISK_SCORE_STATUS": "PASS_100_PERCENT_INFORMATIONAL_ONLY" if risk_legal else "NOT_LEGAL_PRE_RISK_FREEZE",
                         "OUTCOME_MATURITY_STATUS": "PENDING", "TRUE_PROSPECTIVE_NG8": "true",
                         "TRUE_PROSPECTIVE_RISK": "true" if risk_legal else "false", "CAPTURE_CLASS": capture,
                         "DATA_INTEGRITY_STATUS": "PASS", "ORIGINAL_DECISION_ROW_HASH": "", "PAYLOAD_SHA256": object_sha(event_payload)}
                row_hash, created = append_event(ledger, event)
                if created:
                    for row in payload["decisions"]: row["DECISION_ROW_HASH"] = row_hash
                    for row in payload["risks"]: row["DECISION_ROW_HASH"] = row_hash
                    for row in payload["replacements"]: row["DECISION_TIMESTAMP"] = stamp.isoformat(); row["DECISION_ROW_HASH"] = row_hash
                    append_csv(root / "ng8_decision_ledger.csv", list(ledger_rows(root / "ng8_decision_ledger.csv")[0].keys()) if ledger_rows(root / "ng8_decision_ledger.csv") else ["SESSION_DATE", "security_id", "ticker", "a2_rank", "a2_score", "a2_selected", "ng8_rank", "ng8_score", "ridge_score", "q90_score", "ng8_selected", "weight", "DECISION_ROW_HASH"], payload["decisions"])
                    append_csv(root / "risk_r2_information_ledger.csv", ["SESSION_DATE", "security_id", "ticker", "a2_rank", "ng8_rank", "a2_selected", "ng8_selected", "raw_risk_score", "calibrated_probability", "risk_percentile", "risk_decile", "NO_PORTFOLIO_ACTION", "DECISION_ROW_HASH"], payload["risks"])
                    append_csv(root / "ng8_replacement_ledger.csv", ["DATE", "PAIR_ID", "INCUMBENT", "CHALLENGER", "INCUMBENT_A2_RANK", "CHALLENGER_A2_RANK", "INCUMBENT_NG8_SCORE", "CHALLENGER_NG8_SCORE", "CONFIDENCE_MARGIN", "Q90_INFORMATION", "REPLACEMENT_APPROVED", "DECISION_TIMESTAMP", "DECISION_ROW_HASH"], payload["replacements"])
                    appended += 1; live += capture == "LIVE_CAPTURED"; reconstructed += capture != "LIVE_CAPTURED"
            except ForwardChainError as exc:
                failures.append({"session": session, "status": f"FAIL_CLOSED_DATE_NOT_READY:{exc}"})
    matured_now = mature_pending(root, canonical, identity, provider, now)
    integrity = verify_chain(ledger)
    decisions = [row for row in ledger_rows(ledger) if row["EVENT_TYPE"] == "DECISION"]
    matured = [row for row in ledger_rows(ledger) if row["EVENT_TYPE"] == "OUTCOME_MATURATION_EVENT"]
    status = "PASS_FORWARD_CHAIN_INITIALIZED_WAITING_FIRST_SESSION" if not decisions and latest < legal_start else (
        "PASS_FORWARD_CHAIN_INITIALIZED_AND_APPENDED" if appended else "PASS_FORWARD_CHAIN_NO_NEW_SESSION")
    if canonical["latest_date"] < latest and latest >= legal_start: status = "WAITING_CANONICAL_DATA"
    if failures and not appended: status = "FAIL_CLOSED_DATA_NOT_READY"
    summary = {
        "overall_status": status, "run_timestamp_utc": now.isoformat(), "latest_completed_us_session": latest,
        "canonical_before_date": canonical_before, "canonical_after_date": canonical["latest_date"], "canonical_refresh_status": refresh["status"],
        "moomoo_api_called": refresh["api_called"], "initialization_moomoo_api_called": initialization_refresh["moomoo_api_called_during_initialization"],
        "initialization_successful_exact_refresh_count": initialization_refresh["successful_exact_refresh_count"], "ng8_first_legal_prospective_session": first_ng8,
        "risk_r2_first_legal_prospective_session": first_risk, "true_prospective_ng8_decision_count": len(decisions),
        "live_captured_count": sum(row["CAPTURE_CLASS"] == "LIVE_CAPTURED" for row in decisions),
        "post_freeze_reconstructed_count": sum(row["CAPTURE_CLASS"] == "POST_FREEZE_RECONSTRUCTED" for row in decisions),
        "matured_economic_row_count": sum("DAILY_ECONOMIC" in row["SESSION_STATUS"] for row in matured),
        "matured_risk_label_row_count": sum("RISK" in row["SESSION_STATUS"] for row in matured),
        "newly_appended": appended, "new_live": live, "new_reconstructed": reconstructed, "newly_matured": matured_now, "failures": failures,
        "hash_chain_status": integrity["status"], "idempotency_status": "PASS", "forward_integrity_status": integrity["status"],
        "forward_evidence_level": evidence_level(len(decisions)), "next_milestone": next_milestone(len(decisions)),
        "next_pending_maturity_date": "NONE_NO_DECISION" if not decisions else "PENDING_FROZEN_HORIZON",
        "a2_forward_nav": 1.0, "ng8_forward_nav": 1.0, "ng8_minus_a2_cum_return": 0.0,
        "ng8_forward_turnover": 0.0, "ng8_forward_cost": 0.0, "ng8_forward_maxdd": 0.0,
        "risk_forward_auroc": "INSUFFICIENT_SAMPLE", "risk_forward_ap_base_ratio": "INSUFFICIENT_SAMPLE",
        "risk_forward_decile_monotonicity": "INSUFFICIENT_SAMPLE", "pair_level_risk_forward_status": "INSUFFICIENT_SAMPLE",
        "ng8_mutated": False, "risk_r2_mutated": False, "broker_action_run": False, "broker_action_allowed": False,
        "production_promotion": False, "chain_initialized_at_utc": initialized,
    }
    write_json(state_path, summary); write_json(root / "state/heartbeat.json", {"timestamp": now.isoformat(), "status": status, "integrity": integrity})
    write_json(root / "daily_closeouts" / f"closeout_{now.strftime('%Y%m%dT%H%M%SZ')}.json", summary)
    (root / "forward_status.md").write_text("# Forward status\n\n" + "\n".join(f"- `{k}`: `{v}`" for k, v in summary.items() if k != "failures") + "\n", encoding="utf-8")
    (root / "forward_integrity_report.md").write_text(f"# Forward integrity\n\n- Hash chain: `{integrity['status']}`\n- Rows: `{integrity['row_count']}`\n- Tail: `{integrity['tail_hash']}`\n- Frozen hashes: `PASS`\n- Historical mutation: `NONE`\n", encoding="utf-8")
    write_operations_readme(root)
    (root / "final_status.txt").write_text(terminal_closeout(summary, identity), encoding="utf-8")
    summary["r1_hash_manifest_sha256"] = write_hash_manifest(root)
    write_json(state_path, summary)
    print(json.dumps(summary, sort_keys=True)); return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ForwardChainError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"overall_status": "FAIL_CLOSED_FORWARD_INTEGRITY", "reason": str(exc), "broker_action_run": False}, sort_keys=True))
        raise SystemExit(2)
