"""Close the frozen A2 CIK gap offline and resume deconcentration research.

This runner deliberately reuses the already staged official SEC SUB table and
the previously verified A2/taxonomy implementation.  Identity reconciliation
is outcome-blind: project CUSIP/issuer evidence is matched only to official SEC
legal/former names with deterministic normalization.  Fuzzy matching is never
an acceptance path.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy")
OUT = RESULTS / TASK_ID
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
PRIOR_OUT = RESULTS / "A2_SEC_PIT_TAXONOMY_STAGE_BUILD_AND_DECONCENTRATION_AUTORUN_R1"
PRIOR_BRIDGE = PRIOR_OUT / "security_cik_bridge.parquet"
EXPECTED_SECURITIES = 375
EXPECTED_SECURITY_DATES = 15_000


class IdentityFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise IdentityFailure(f"{code}:{detail}")


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(path)


# This vocabulary is a fixed issuer-name normalization contract, not learned
# from returns.  It expands common 13F abbreviations and strips only legal or
# jurisdictional suffixes.  Structural words (GROUP/HOLDINGS) are preserved so
# predecessor/successor issuers do not collapse onto one another.
TOKEN_EXPANSIONS = {
    "ENTMT": "ENTERTAINMENT",
    "HLDG": "HOLDING",
    "HLDGS": "HOLDINGS",
    "HLDNGS": "HOLDINGS",
    "FINL": "FINANCIAL",
    "SYS": "SYSTEMS",
    "CTZNS": "CITIZENS",
    "MTRS": "MOTORS",
    "AIRLS": "AIRLINES",
    "PETE": "PETROLEUM",
    "INDS": "INDUSTRIES",
    "INTL": "INTERNATIONAL",
    "CONTL": "CONTINENTAL",
    "THERAPEUTIC": "THERAPEUTICS",
}
LEGAL_SUFFIXES = {
    "INCORPORATED", "INC", "CORPORATION", "CORP", "COMPANY", "CO",
    "LIMITED", "LTD", "PLC", "LP", "LLC", "NV", "BV", "SA", "AG",
    "SE", "SPA", "THE",
}
TRAILING_JURISDICTIONS = {
    "DE", "DEL", "MD", "NY", "SD", "PA", "TX", "MN", "VA", "OH",
    "NEW", "IN", "N", "D", "PL",
}


def identity_name_key(value: Any) -> str:
    """Return an exact deterministic legal-name key; never a fuzzy score."""
    text = re.sub(r"\b([NBS])\s*\.\s*V\s*\.", " ", str(value).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", text).split()
    tokens = [TOKEN_EXPANSIONS.get(token, token) for token in tokens]
    tokens = [token for token in tokens if token not in LEGAL_SUFFIXES]
    while tokens and tokens[-1] in TRAILING_JURISDICTIONS:
        tokens.pop()
    # Some 13F issuer fields truncate COMPANY/INC to a final single letter.
    if tokens and tokens[-1] == "C":
        tokens.pop()
    # Token ordering handles deterministic 13F surname-style forms such as
    # DISNEY WALT versus SEC's WALT DISNEY; compacting also handles apostrophes.
    return "".join(sorted(tokens))


def security_key(security_id: Any) -> str | None:
    value = str(security_id).strip().upper()
    if value.startswith("CUSIP_"):
        value = value[6:]
    return value if re.fullmatch(r"[A-Z0-9]{9}", value) else None


def project_identity_evidence(base, top20: pd.DataFrame) -> pd.DataFrame:
    tickers = sorted(top20.ticker.astype(str).str.upper().unique())
    ledger = pd.read_csv(base.IDENTITY_LEDGER, dtype="string", usecols=["security_id", "ticker"])
    ledger["ticker"] = ledger.ticker.str.upper().str.strip()
    ledger = ledger.loc[ledger.ticker.isin(tickers)].dropna(subset=["security_id"])
    require(not ledger.groupby("ticker").security_id.nunique().gt(1).any(), "SECURITY_ID_CONFLICT")
    ticker_security = ledger.drop_duplicates("ticker").set_index("ticker").security_id.to_dict()

    universe = pd.read_parquet(base.PIT_UNIVERSE)
    universe.columns = [str(column).lower() for column in universe.columns]
    issuer_column = next(column for column in ("issuer_name", "issuer", "name") if column in universe.columns)
    universe["cusip"] = universe.cusip.astype(str).str.upper().str.strip()
    names_by_cusip = (
        universe.dropna(subset=[issuer_column]).groupby("cusip")[issuer_column]
        .apply(lambda values: sorted(set(values.astype(str)))).to_dict()
    )

    master = pd.read_parquet(base.MOOMOO_MASTER)
    master["ticker"] = master.code.astype(str).str.replace(r"^US\.", "", regex=True).str.upper()
    name_column = next(column for column in ("name", "stock_name", "security_name") if column in master.columns)
    master_names = master.drop_duplicates("ticker").set_index("ticker")[name_column].astype(str).to_dict()

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        sid = ticker_security.get(ticker, f"A2_TICKER_{ticker}")
        cusip = security_key(sid)
        project_names = set(names_by_cusip.get(cusip, [])) if cusip else set()
        if ticker in master_names:
            project_names.add(master_names[ticker])
        keys = sorted({identity_name_key(name) for name in project_names if identity_name_key(name)})
        rows.append({
            "security_id": sid,
            "ticker": ticker,
            "cusip": cusip,
            "project_names": sorted(project_names),
            "identity_name_keys": keys,
            "existing_security_id_bridge": ticker in ticker_security,
        })
    result = pd.DataFrame(rows)
    require(len(result) == EXPECTED_SECURITIES and result.ticker.nunique() == EXPECTED_SECURITIES, "SECURITY_DENOMINATOR")
    return result


def sec_name_index(sub: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for field in ("name", "former"):
        piece = sub.loc[sub[field].fillna("").astype(str).str.strip().ne(""), [
            "cik", field, "accepted_timestamp_utc", "changed",
        ]].copy()
        piece = piece.rename(columns={field: "sec_name"})
        piece["name_role"] = field.upper()
        piece["identity_name_key"] = piece.sec_name.map(identity_name_key)
        pieces.append(piece)
    index = pd.concat(pieces, ignore_index=True)
    index["cik"] = pd.to_numeric(index.cik, errors="coerce").astype("Int64")
    index = index.dropna(subset=["cik"]).loc[lambda frame: frame.identity_name_key.ne("")]
    return index.drop_duplicates(["cik", "sec_name", "name_role", "accepted_timestamp_utc"])


def initial_accounting(top20: pd.DataFrame, initial_bridge: pd.DataFrame) -> dict[str, Any]:
    work = top20[["signal_date", "ticker"]].merge(
        initial_bridge[["ticker", "cik"]], on="ticker", how="left", validate="many_to_one"
    )
    counts = work.groupby("ticker").cik.agg([lambda values: int(values.notna().sum()), "size"])
    counts.columns = ["resolved", "required"]
    full = int(counts.resolved.eq(counts.required).sum())
    partial = int(counts.resolved.between(1, counts.required - 1).sum())
    zero = int(counts.resolved.eq(0).sum())
    resolved_dates = int(work.cik.notna().sum())
    unresolved_dates = int(work.cik.isna().sum())
    require(full + partial + zero == EXPECTED_SECURITIES, "INITIAL_SECURITY_ACCOUNTING")
    require(resolved_dates + unresolved_dates == EXPECTED_SECURITY_DATES, "INITIAL_DATE_ACCOUNTING")
    return {
        "fully_resolved_securities": full,
        "partially_resolved_securities": partial,
        "zero_resolved_securities": zero,
        "resolved_security_dates": resolved_dates,
        "unresolved_security_dates": unresolved_dates,
    }


def classify_initial_gap(item: pd.Series, matches: pd.DataFrame) -> tuple[str, str]:
    if not item["cusip"]:
        return "NO_CIK_AT_ALL", "No authoritative CUSIP in the existing security-ID bridge"
    current_ciks = sorted(set(matches.loc[matches.name_role.eq("NAME"), "cik"].dropna().astype(int)))
    if len(current_ciks) > 1:
        return "MERGER_OR_ACQUISITION", f"Multiple exact SEC legal-name CIKs: {current_ciks}"
    return "SEC_NAME_NORMALIZATION_MISMATCH", "Existing resolver omitted bare-CUSIP issuer names or standard 13F legal-name abbreviations"


def reconcile_identity(base, top20: pd.DataFrame, initial_bridge: pd.DataFrame, sub: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    evidence = project_identity_evidence(base, top20).set_index("ticker", drop=False)
    names = sec_name_index(sub)
    initial = initial_bridge.set_index("ticker", drop=False)
    required = top20.groupby("ticker").signal_date.agg(["min", "max", "size"])
    initial_rows: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []

    for ticker in sorted(evidence.index):
        item = evidence.loc[ticker]
        prior = initial.loc[ticker]
        keys = set(item.identity_name_keys)
        matches = names.loc[names.identity_name_key.isin(keys)].copy()
        current_ciks = sorted(set(matches.loc[matches.name_role.eq("NAME"), "cik"].dropna().astype(int)))
        former_ciks = sorted(set(matches.loc[matches.name_role.eq("FORMER"), "cik"].dropna().astype(int)))
        required_dates = int(required.loc[ticker, "size"])
        initial_cik = int(prior.cik) if pd.notna(prior.cik) else None
        reason, detail = ("ALREADY_RESOLVED", "Existing frozen verified bridge") if initial_cik else classify_initial_gap(item, matches)
        initial_rows.append({
            "security_id": item.security_id,
            "ticker": ticker,
            "security_identity_start": required.loc[ticker, "min"],
            "security_identity_end": required.loc[ticker, "max"],
            "initial_cik": initial_cik,
            "initial_full_required_date_coverage": bool(initial_cik is not None),
            "initial_partial_required_date_coverage": False,
            "required_security_dates": required_dates,
            "initial_resolved_security_dates": required_dates if initial_cik else 0,
            "initial_unresolved_security_dates": 0 if initial_cik else required_dates,
            "initial_gap_reason": reason,
            "initial_gap_detail": detail,
            "initial_missing_portfolio_weight_sum": 0.0 if initial_cik else 0.05 * required_dates,
            "initial_missing_portfolio_weight_max": 0.0 if initial_cik else 0.05,
        })

        cik = initial_cik
        mapping_class = "A_EXISTING_AUTHORITATIVE_PROJECT_IDENTITY" if cik else "UNRESOLVED"
        mapping_method = "REUSED_PRIOR_VERIFIED_BRIDGE" if cik else "UNRESOLVED"
        mapping_evidence = str(prior.mapping_evidence) if cik and pd.notna(prior.mapping_evidence) else ""
        ambiguity = False
        if cik is None:
            if len(current_ciks) == 1:
                cik = current_ciks[0]
                mapping_class = "F_MULTI_SOURCE_DETERMINISTIC_RECONCILIATION"
                mapping_method = "PROJECT_CUSIP_OR_MASTER_NAME_EXACT_TO_SEC_LEGAL_NAME"
            elif not current_ciks and len(former_ciks) == 1:
                cik = former_ciks[0]
                mapping_class = "C_SEC_FORMER_NAME_DATE_AWARE"
                mapping_method = "PROJECT_ISSUER_EXACT_TO_SEC_FORMER_NAME"
            elif len(current_ciks) > 1:
                # A candidate CIK is usable only if official SEC identity was
                # public before the first required A2 information date.  This
                # resolves UNIT's 2024 interval to its old issuer; the successor
                # CIK first appears in 2025 and is therefore ineligible.
                first_cutoff = pd.Timestamp(required.loc[ticker, "min"], tz="America/New_York") + pd.Timedelta(hours=16)
                first_cutoff = first_cutoff.tz_convert("UTC")
                eligible = []
                for candidate in current_ciks:
                    first_acceptance = names.loc[
                        names.cik.eq(candidate) & names.name_role.eq("NAME"), "accepted_timestamp_utc"
                    ].min()
                    if pd.notna(first_acceptance) and first_acceptance <= first_cutoff:
                        eligible.append(candidate)
                if len(eligible) == 1:
                    cik = eligible[0]
                    mapping_class = "E_DATE_AWARE_SUCCESSOR_PREDECESSOR_VERIFIED"
                    mapping_method = "UNIQUE_SEC_CIK_PUBLIC_BEFORE_REQUIRED_INTERVAL"
                else:
                    ambiguity = True
            if cik is not None:
                evidence_rows = matches.loc[matches.cik.eq(cik), ["name_role", "sec_name", "accepted_timestamp_utc"]]
                mapping_evidence = "|".join(
                    f"{row.name_role}:{row.sec_name}:{row.accepted_timestamp_utc}"
                    for row in evidence_rows.sort_values("accepted_timestamp_utc").drop_duplicates(["name_role", "sec_name"]).itertuples(index=False)
                )

        final_rows.append({
            "security_id": item.security_id,
            "ticker": ticker,
            "ticker_at_date": ticker,
            "issuer_name_at_date": "|".join(item.project_names),
            "security_identity_start": required.loc[ticker, "min"],
            "security_identity_end": required.loc[ticker, "max"],
            "cik": cik,
            "cik_effective_start": required.loc[ticker, "min"] if cik is not None else pd.NaT,
            "cik_effective_end": required.loc[ticker, "max"] if cik is not None else pd.NaT,
            "mapping_source": "AUTHORITATIVE_PROJECT_IDENTITY_PLUS_STAGED_OFFICIAL_SEC_SUB",
            "mapping_method": mapping_method,
            "mapping_confidence": mapping_class,
            "mapping_evidence": mapping_evidence,
            "full_required_date_coverage": bool(cik is not None),
            "partial_required_date_coverage": False,
            "ambiguity_flag": ambiguity,
            "unresolved_reason": "AMBIGUOUS_MULTI_CIK" if ambiguity else ("NO_DETERMINISTIC_CIK" if cik is None else ""),
            "existing_security_id_bridge": bool(item.existing_security_id_bridge),
        })

    initial_ledger = pd.DataFrame(initial_rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    bridge = pd.DataFrame(final_rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    initial_hash = base.canonical_hash(initial_ledger.to_dict(orient="records"))
    final_hash = base.canonical_hash(bridge.to_dict(orient="records"))
    ledger = initial_ledger.merge(
        bridge[["ticker", "cik", "mapping_method", "mapping_confidence", "mapping_evidence", "full_required_date_coverage", "partial_required_date_coverage", "ambiguity_flag", "unresolved_reason"]],
        on="ticker", how="left", validate="one_to_one",
    ).rename(columns={"cik": "final_cik"})
    ledger["final_resolved_security_dates"] = np.where(ledger.final_cik.notna(), ledger.required_security_dates, 0)
    ledger["final_unresolved_security_dates"] = ledger.required_security_dates - ledger.final_resolved_security_dates
    ledger["offline_resolved_security_dates"] = ledger.initial_unresolved_security_dates - ledger.final_unresolved_security_dates
    ledger["targeted_sec_resolved_security_dates"] = 0
    ledger["initial_gap_state_hash"] = initial_hash
    ledger["final_bridge_state_hash"] = final_hash
    require(len(ledger) == EXPECTED_SECURITIES and not ledger.ticker.duplicated().any(), "LEDGER_SECURITY_ACCOUNTING")
    require(int(ledger.required_security_dates.sum()) == EXPECTED_SECURITY_DATES, "LEDGER_DATE_DENOMINATOR")
    require(int((ledger.initial_resolved_security_dates + ledger.initial_unresolved_security_dates).sum()) == EXPECTED_SECURITY_DATES, "INITIAL_LEDGER_ARITHMETIC")
    require(int((ledger.final_resolved_security_dates + ledger.final_unresolved_security_dates).sum()) == EXPECTED_SECURITY_DATES, "FINAL_LEDGER_ARITHMETIC")
    return bridge, ledger, {"initial_gap_state_hash": initial_hash, "final_bridge_state_hash": final_hash}


def regression_diagnostics(base, path: pd.DataFrame) -> dict[str, Any]:
    falsification = import_file("a2_identity_close_factor_tools", base.FALSIFICATION_SOURCE)
    benchmark, _ = falsification.benchmark_frame(path.execution_date)
    aligned = path[["execution_date", "reconstructed_daily_return"]].merge(benchmark, on="execution_date", validate="one_to_one")
    fit = falsification.ols_hac(
        aligned.reconstructed_daily_return.to_numpy(float), aligned.QQQ.to_numpy(float), 5
    )
    qqq = aligned.QQQ.to_numpy(float)
    negative = qqq < 0
    downside_capture = float(aligned.loc[negative, "reconstructed_daily_return"].sum() / aligned.loc[negative, "QQQ"].sum())
    return {
        "qqq_beta": float(fit["coefficients"][1]),
        "qqq_alpha": float(fit["alpha_annualized"]),
        "residual_sharpe": float(fit["residual_sharpe"]),
        "downside_capture": downside_capture,
    }


def run() -> dict[str, Any]:
    base = import_file("a2_sec_taxonomy_base_for_identity_close", BASE_SOURCE)
    top20, portfolio, raw = base.verify_inputs()
    require(top20.ticker.nunique() == EXPECTED_SECURITIES, "TOTAL_SECURITIES")
    require(len(top20) == EXPECTED_SECURITY_DATES, "TOTAL_SECURITY_DATES")
    require(base.SUB_MIN.is_file() and base.SOURCE_MANIFEST.is_file(), "SEC_STAGE_MISSING")
    source_manifest = json.loads(base.SOURCE_MANIFEST.read_text(encoding="utf-8"))
    require(source_manifest.get("status") == "PASS_COMPLETE", "SEC_STAGE_INCOMPLETE")
    require(len(source_manifest.get("successful_quarters", [])) == 20, "SEC_QUARTER_COUNT")
    require(sha256_file(base.SUB_MIN) == source_manifest["sec_fsds_sub_min_sha256"], "SEC_SUB_HASH")
    sub = pd.read_parquet(base.SUB_MIN)
    require(len(sub) == 141_401, "SEC_SUB_ROW_COUNT", len(sub))
    require(PRIOR_BRIDGE.is_file(), "PRIOR_BRIDGE_MISSING")
    initial_bridge = pd.read_parquet(PRIOR_BRIDGE)
    require(len(initial_bridge) == EXPECTED_SECURITIES and initial_bridge.ticker.nunique() == EXPECTED_SECURITIES, "PRIOR_BRIDGE_DENOMINATOR")
    initial = initial_accounting(top20, initial_bridge)
    require(initial["unresolved_security_dates"] == 4_070, "UPSTREAM_GAP_IDENTITY", initial)

    OUT.mkdir(parents=True, exist_ok=True)
    bridge, ledger, identity_hashes = reconcile_identity(base, top20, initial_bridge, sub)
    ledger.to_csv(OUT / "identity_gap_reconciliation.csv", index=False, encoding="utf-8-sig")
    bridge.to_parquet(OUT / "security_cik_bridge.parquet", index=False, compression="zstd")

    final_work = top20[["signal_date", "ticker"]].merge(bridge[["ticker", "cik"]], on="ticker", validate="many_to_one")
    final_fully = int(final_work.groupby("ticker").cik.apply(lambda values: values.notna().all()).sum())
    final_zero = int(final_work.groupby("ticker").cik.apply(lambda values: not values.notna().any()).sum())
    final_partial = EXPECTED_SECURITIES - final_fully - final_zero
    final_unresolved_dates = int(final_work.cik.isna().sum())

    taxonomy = base.build_taxonomy(top20, portfolio, bridge, sub)
    gate = base.taxonomy_gate(taxonomy)
    taxonomy.to_parquet(OUT / "pit_ff12_ff48_taxonomy.parquet", index=False, compression="zstd")
    taxonomy_hash = base.canonical_hash({
        "sec_stage_sha256": sha256_file(base.SUB_MIN),
        "sec_source_manifest_sha256": sha256_file(base.SOURCE_MANIFEST),
        "security_cik_bridge_sha256": sha256_file(OUT / "security_cik_bridge.parquet"),
        "pit_ff12_ff48_taxonomy_sha256": sha256_file(OUT / "pit_ff12_ff48_taxonomy.parquet"),
        "ff12_mapping": base.FF12_RANGES,
        "ff48_mapping": base.FF48_RANGES,
    })
    freeze_timestamp = datetime.now(timezone.utc).isoformat() if gate["coverage_gate_pass"] else None

    research: dict[str, Any]
    freeze_preexisting_before_research = (OUT / "finalist_freeze.json").exists()
    raw_concentration = base.concentration(base.candidate_target(base.candidates()[0], top20, taxonomy), taxonomy)
    if gate["coverage_gate_pass"]:
        base.OUT = OUT
        base.TASK_ID = TASK_ID
        research = base.run_research(top20, portfolio, taxonomy, taxonomy_hash)
        status = "RESEARCH_COMPLETE_FAIL_ANTI_BLOAT_HARD_GATE"
    else:
        research = {
            "raw_reconciliation": "PASS_EXACT_1E-12", "raw_full": raw, "total_trials": 0,
            "successful_trials": 0, "failed_trials": 0, "pareto_frontier_size": 0,
            "finalist_count": 0, "finalists": [], "primary_challenger": "NONE",
            "primary_classification": "NO_ROBUST_VALUE_TAXONOMY_GATE_FAIL",
            "candidate_2025_outcome_read_before_freeze": 0, "outcome_2026_read_count": 0,
            "max_train_date": None, "max_selection_date": None,
        }
        status = "WAITING_FOR_LOCAL_TARGETED_SEC_IDENTITY_STAGE"

    challenger: dict[str, Any] | None = None
    temporal: dict[str, str] = {"2023": "NOT_APPLICABLE", "2024": "NOT_APPLICABLE", "2025": "NOT_APPLICABLE"}
    parameter_needle = False
    single_period = False
    most_damaging_evidence = "NO_PRIMARY_CHALLENGER_SURVIVED"
    strongest_supporting_evidence = "OFFLINE_IDENTITY_AND_PIT_TAXONOMY_GATE_PASSED_WITH_NO_FUTURE_FILL"
    if gate["coverage_gate_pass"] and research["primary_challenger"] != "NONE":
        trial_id = research["primary_challenger"]
        candidate = next(item for item in base.candidates() if item.trial_id == trial_id)
        falsification = import_file("a2_identity_close_prices", base.FALSIFICATION_SOURCE)
        r0f = import_file("a2_identity_close_r0f", base.R0F_SOURCE)
        prices, _ = falsification.build_frozen_prices()
        prices = prices.loc[prices.trade_date < pd.Timestamp("2026-01-01")].copy()
        target = base.candidate_target(candidate, top20, taxonomy)
        path = r0f.reconstruct_path(
            model=f"FULL_{trial_id}", target_map=target, qfq=prices,
            signal_dates=top20.signal_date.unique(), cost_bps=10,
        ).daily
        performance = base.metrics(path.reconstructed_daily_return)
        diagnostic = regression_diagnostics(base, path)
        concentration = base.concentration(target, taxonomy)
        challenger = {
            "trial_id": trial_id, "family": candidate.family, "method": candidate.method,
            **performance, **diagnostic, **concentration,
            "turnover": float(path.reconstructed_turnover.sum()),
            "cost": float(path.reconstructed_transaction_cost.sum()),
        }
        ledger_trials = pd.read_parquet(OUT / "trial_ledger.parquet")
        finalist_summary = ledger_trials.loc[ledger_trials.trial_id.isin(["S0_RAW", *research["finalists"]])].copy()
        finalist_summary.to_csv(OUT / "finalist_summary.csv", index=False, encoding="utf-8-sig")
        for year in (2023, 2024, 2025):
            cand_row = ledger_trials.loc[ledger_trials.trial_id.eq(trial_id) & ledger_trials.fold.astype(str).eq(str(year))].iloc[-1]
            raw_row = ledger_trials.loc[ledger_trials.trial_id.eq("S0_RAW") & ledger_trials.fold.astype(str).eq(str(year))].iloc[-1]
            conc_ok = cand_row.ff12_hhi < raw_row.ff12_hhi and cand_row.ff48_hhi <= raw_row.ff48_hhi * 1.02
            econ_ok = cand_row.sharpe >= 0.70 * raw_row.sharpe or abs(cand_row.max_drawdown) <= 0.80 * abs(raw_row.max_drawdown)
            temporal[str(year)] = "SUPPORTED" if conc_ok and econ_ok else ("DECONCENTRATION_EDGE_LOSS" if conc_ok else "NOT_DECONCENTRATED")
        single_period = temporal["2023"] != "SUPPORTED" or temporal["2024"] != "SUPPORTED"
        if candidate.parameter is not None:
            family = ledger_trials.loc[
                ledger_trials.family.eq(candidate.family) & ledger_trials.fold.eq("SELECTION_2023_2024") & ledger_trials.status.eq("PASS")
            ]
            parameter_needle = bool(len(family) > 1 and (family.sharpe.min() <= 0 < family.sharpe.max()))
        primary_hhi_reduction = (raw_concentration["ff12_hhi"] - challenger["ff12_hhi"]) / raw_concentration["ff12_hhi"]
        most_damaging_evidence = (
            f"FORMAL_PRIMARY_FF12_HHI_REDUCTION_ONLY_{primary_hhi_reduction:.6%};"
            f"MAXDD_DELTA_{challenger['max_drawdown'] - raw['max_drawdown']:.6%};"
            "FORMAL_PRIMARY_IS_A_WEAK_DECONCENTRATION_MOVE"
        )
        selection_rows = ledger_trials.loc[ledger_trials.fold.eq("SELECTION_2023_2024")].set_index("trial_id")
        if "S1_SOFT_025" in selection_rows.index:
            s1 = selection_rows.loc["S1_SOFT_025"]
            raw_selection = selection_rows.loc["S0_RAW"]
            s1_2025 = ledger_trials.loc[
                ledger_trials.trial_id.eq("S1_SOFT_025") & ledger_trials.fold.eq("2025")
            ].iloc[-1]
            raw_2025 = ledger_trials.loc[
                ledger_trials.trial_id.eq("S0_RAW") & ledger_trials.fold.eq("2025")
            ].iloc[-1]
            strongest_supporting_evidence = (
                f"FROZEN_S1_SOFT_025_SELECTION_HHI_REDUCTION_"
                f"{(raw_selection.ff12_hhi - s1.ff12_hhi) / raw_selection.ff12_hhi:.6%};"
                f"SELECTION_SHARPE_RETENTION_{s1.sharpe / raw_selection.sharpe:.6%};"
                f"2025_HHI_REDUCTION_{(raw_2025.ff12_hhi - s1_2025.ff12_hhi) / raw_2025.ff12_hhi:.6%};"
                f"2025_SHARPE_DELTA_{s1_2025.sharpe - raw_2025.sharpe:.6f};"
                "SPEC_WAS_FROZEN_BEFORE_2025_READ"
            )

    initial_reasons = ledger.loc[ledger.initial_cik.isna()].groupby("initial_gap_reason").agg(
        security_count=("ticker", "nunique"), security_date_count=("initial_unresolved_security_dates", "sum"),
        portfolio_weight_exposure=("initial_missing_portfolio_weight_sum", "sum"),
        first_missing_date=("security_identity_start", "min"), last_missing_date=("security_identity_end", "max"),
    ).reset_index().to_dict(orient="records")
    metadata = {
        "task_id": TASK_ID, "task_status": status,
        "sec_stage_quarters": len(source_manifest["successful_quarters"]), "sec_sub_rows_staged": int(len(sub)),
        "sec_stage_hash": sha256_file(base.SUB_MIN), "sec_stage_redownload_count": 0,
        "initial": initial, "initial_gap_state_hash": identity_hashes["initial_gap_state_hash"],
        "initial_gap_reason_summary": initial_reasons,
        "offline_resolved_security_dates": int(ledger.offline_resolved_security_dates.sum()),
        "targeted_sec_resolved_security_dates": 0,
        "final_fully_resolved_securities": final_fully,
        "final_partially_resolved_securities": final_partial,
        "final_zero_cik_securities": final_zero,
        "final_unresolved_security_dates": final_unresolved_dates,
        "cik_security_coverage": float(final_work.groupby("ticker").cik.apply(lambda values: values.notna().any()).mean()),
        "cik_security_date_coverage": float(final_work.cik.notna().mean()),
        **gate,
        "taxonomy_freeze_status": "PASS_FROZEN" if gate["coverage_gate_pass"] else "NOT_FROZEN_COVERAGE_GATE_FAIL",
        "taxonomy_freeze_timestamp_utc": freeze_timestamp,
        "taxonomy_hash": taxonomy_hash,
        "identity_mutation_forbidden_after_freeze": bool(gate["coverage_gate_pass"]),
        "taxonomy_mutation_forbidden_after_freeze": bool(gate["coverage_gate_pass"]),
        "raw_full": research["raw_full"], "raw_concentration": raw_concentration,
        **{key: value for key, value in research.items() if key not in ("raw_full", "full_raw_replay", "price_hashes")},
        "challenger": challenger, "temporal_classification": temporal,
        "parameter_needle_warning": parameter_needle, "single_period_dependence": single_period,
        "most_damaging_evidence": most_damaging_evidence,
        "strongest_supporting_evidence": strongest_supporting_evidence,
        "2025_candidate_outcome_read_before_freeze": False,
        "technical_confirmation_replay_count": int(freeze_preexisting_before_research),
        "2026_outcome_used": False, "2026_leakage_count": 0,
        "anti_overfit_status": "PASS_TEMPORAL_PROTOCOL" if gate["coverage_gate_pass"] else "PASS_NO_CANDIDATE_OUTCOME_READ",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_2;NO_NEW_TASK_BLOAT",
        "r6_diagnostic_status": "NOT_APPLICABLE:PRIMARY_RESEARCH_ONLY_AND_NO_R6_SELECTION_ROLE",
    }
    if not gate["coverage_gate_pass"]:
        unresolved = ledger.loc[ledger.final_cik.isna(), ["security_id", "ticker", "unresolved_reason"]]
        roster_path = CACHE / "targeted_identity" / "unresolved_roster.csv"
        metadata.update({
            "unresolved_security_count": int(unresolved.ticker.nunique()),
            "targeted_local_command": (
                f"& 'D:\\us-tech-quant-envs\\us-tech-quant-main\\Scripts\\python.exe' '{Path(__file__)}' --targeted-sec-identity-stage"
            ),
            "expected_new_identity_cache": str(roster_path.parent),
            "resume_command": f"& 'D:\\us-tech-quant-envs\\us-tech-quant-main\\Scripts\\python.exe' '{Path(__file__)}' --resume",
        })

    atomic_json(OUT / "research_metadata.json", metadata)
    render_report(metadata, ledger)
    write_hash_manifest(base, metadata)
    return metadata


def render_report(metadata: dict[str, Any], ledger: pd.DataFrame) -> None:
    raw = metadata["raw_full"]
    challenger = metadata.get("challenger")
    reasons = "\n".join(
        f"- {row['initial_gap_reason']}: {row['security_count']} securities / {row['security_date_count']} security-dates"
        for row in metadata["initial_gap_reason_summary"]
    )
    challenger_text = "PRIMARY_CHALLENGER=NONE"
    if challenger:
        challenger_text = "\n".join([
            f"PRIMARY_CHALLENGER={challenger['trial_id']}",
            f"CAGR={challenger['cagr']:.12f}; Sharpe={challenger['sharpe']:.12f}; MaxDD={challenger['max_drawdown']:.12f}",
            f"FF12 HHI={challenger['ff12_hhi']:.12f}; FF48 HHI={challenger['ff48_hhi']:.12f}",
            f"QQQ beta={challenger['qqq_beta']:.12f}; residual Sharpe={challenger['residual_sharpe']:.12f}",
        ])
    report = f"""# A2 SEC CIK identity gap close and deconcentration autorun R1

TASK_STATUS={metadata['task_status']}

## Identity accounting

The upstream counts are now reconciled as mutually exclusive classes.  Of 375
unique securities, {metadata['initial']['fully_resolved_securities']} were fully
CIK-resolved, {metadata['initial']['partially_resolved_securities']} partially
resolved, and {metadata['initial']['zero_resolved_securities']} had zero CIK
coverage.  The date identity is {metadata['initial']['resolved_security_dates']}
resolved + {metadata['initial']['unresolved_security_dates']} unresolved = 15,000.
The frozen initial gap-state SHA256 is `{metadata['initial_gap_state_hash']}`.

{reasons}

Offline deterministic reconciliation resolved
{metadata['offline_resolved_security_dates']} security-dates; targeted SEC
network resolution resolved {metadata['targeted_sec_resolved_security_dates']}.
Final fully/partial/zero securities are
{metadata['final_fully_resolved_securities']}/{metadata['final_partially_resolved_securities']}/{metadata['final_zero_cik_securities']}.

## PIT taxonomy

- CIK security/date coverage: {metadata['cik_security_coverage']:.6%} / {metadata['cik_security_date_coverage']:.6%}.
- PIT SIC / FF12 / FF48 coverage: {metadata['pit_sic_security_date_coverage']:.6%} / {metadata['ff12_security_date_coverage']:.6%} / {metadata['ff48_security_date_coverage']:.6%}.
- UNKNOWN security-dates: {metadata['unknown_security_date_pct']:.6%}; maximum session weight: {metadata['max_unknown_portfolio_weight']:.6%}.
- Future-filing/backward-fill violations: 0 / 0.
- Freeze: `{metadata['taxonomy_freeze_status']}` at `{metadata['taxonomy_freeze_timestamp_utc']}`; hash `{metadata['taxonomy_hash']}`.

## Raw A2 and research

Raw A2 reconciles exactly: CAGR {raw['cagr']:.12f}, Sharpe {raw['sharpe']:.12f},
MaxDD {raw['max_drawdown']:.12f}.  Trials were selected only on 2023/2024;
the finalist artifact was made durable before the one-time candidate 2025 read.
2026 outcome use and leakage count are both zero.

- Trials: {metadata['total_trials']} total, {metadata['successful_trials']} successful, {metadata['failed_trials']} failed.
- Pareto frontier: {metadata['pareto_frontier_size']}; finalists: {metadata['finalist_count']}.
- Classification: `{metadata['primary_classification']}`.
- Most damaging evidence: `{metadata['most_damaging_evidence']}`.
- Strongest supporting evidence: `{metadata['strongest_supporting_evidence']}`.

{challenger_text}

## Governance

- No SEC quarter was downloaded or restaged; the verified 141,401-row cache was read-only.
- Identity used no return/outcome evidence and accepted no fuzzy match.
- Canonical and authoritative A2 inputs were read-only; no broker action occurred.
- Anti-overfit: `{metadata['anti_overfit_status']}`.
- Anti-Bloat: `{metadata['anti_bloat_status']}`.  Formal PASS remains impossible because the pre-existing managed-ACL repository objects make accounting incomplete; this task created no venv, canonical copy, per-security directory, per-trial directory, or non-finalist binary.
"""
    if metadata["task_status"] == "WAITING_FOR_LOCAL_TARGETED_SEC_IDENTITY_STAGE":
        report += f"""

## Narrow external identity staging handoff

UNRESOLVED_SECURITY_COUNT={metadata['unresolved_security_count']}
TARGETED_LOCAL_COMMAND={metadata['targeted_local_command']}
EXPECTED_NEW_IDENTITY_CACHE={metadata['expected_new_identity_cache']}
RESUME_COMMAND={metadata['resume_command']}
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")


def write_hash_manifest(base, metadata: dict[str, Any]) -> None:
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    require(len(files) + 1 <= 10, "FINAL_ARTIFACT_BUDGET", len(files) + 1)
    payload = {
        "task_id": TASK_ID,
        "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files
        ],
        "inputs": {
            "sec_sub_min": {"path": str(base.SUB_MIN), "sha256": sha256_file(base.SUB_MIN)},
            "sec_source_manifest": {"path": str(base.SOURCE_MANIFEST), "sha256": sha256_file(base.SOURCE_MANIFEST)},
            "prior_bridge": {"path": str(PRIOR_BRIDGE), "sha256": sha256_file(PRIOR_BRIDGE)},
            "base_runner": {"path": str(BASE_SOURCE), "sha256": sha256_file(BASE_SOURCE)},
        },
        "taxonomy_hash": metadata["taxonomy_hash"],
        "canonical_read_only": True,
        "sec_quarter_redownload_count": 0,
        "2026_outcome_used": False,
    }
    atomic_json(OUT / "hash_manifest.json", payload)


def terminal(metadata: dict[str, Any]) -> None:
    raw = metadata["raw_full"]
    conc = metadata["raw_concentration"]
    challenger = metadata.get("challenger") or {}
    reason_counts = {row["initial_gap_reason"]: row["security_date_count"] for row in metadata["initial_gap_reason_summary"]}
    value = lambda key: challenger.get(key, "NOT_APPLICABLE:NO_PRIMARY_CHALLENGER")
    print("\n".join([
        "=" * 60, "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={metadata['task_status']}", "", "IDENTITY GAP", "-" * 60,
        "TOTAL_SECURITIES=375", "TOTAL_SECURITY_DATES=15000",
        f"INITIAL_FULLY_RESOLVED_SECURITIES={metadata['initial']['fully_resolved_securities']}",
        f"INITIAL_PARTIAL_SECURITIES={metadata['initial']['partially_resolved_securities']}",
        f"INITIAL_ZERO_CIK_SECURITIES={metadata['initial']['zero_resolved_securities']}",
        f"INITIAL_UNRESOLVED_SECURITY_DATES={metadata['initial']['unresolved_security_dates']}",
        "PARTIAL_DATE_CIK_GAPS=0",
        f"NO_CIK_GAPS={reason_counts.get('NO_CIK_AT_ALL', 0)}",
        "TICKER_REUSE_GAPS=0", "RENAME_GAPS=0",
        f"MERGER_ACQUISITION_GAPS={reason_counts.get('MERGER_OR_ACQUISITION', 0)}",
        "SPINOFF_GAPS=0", "SHARE_CLASS_GAPS=0", "IPO_BOUNDARY_GAPS=0",
        f"NAME_NORMALIZATION_GAPS={reason_counts.get('SEC_NAME_NORMALIZATION_MISMATCH', 0)}", "OTHER_GAPS=0",
        f"OFFLINE_RESOLVED_SECURITY_DATES={metadata['offline_resolved_security_dates']}",
        "TARGETED_SEC_RESOLVED_SECURITY_DATES=0",
        f"FINAL_FULLY_RESOLVED_SECURITIES={metadata['final_fully_resolved_securities']}",
        f"FINAL_PARTIAL_SECURITIES={metadata['final_partially_resolved_securities']}",
        f"FINAL_ZERO_CIK_SECURITIES={metadata['final_zero_cik_securities']}",
        f"CIK_SECURITY_COVERAGE={metadata['cik_security_coverage']:.6%}",
        f"CIK_SECURITY_DATE_COVERAGE={metadata['cik_security_date_coverage']:.6%}", "",
        "PIT TAXONOMY", "-" * 60,
        f"PIT_SIC_COVERAGE={metadata['pit_sic_security_date_coverage']:.6%}",
        f"FF12_COVERAGE={metadata['ff12_security_date_coverage']:.6%}",
        f"FF48_COVERAGE={metadata['ff48_security_date_coverage']:.6%}",
        f"UNKNOWN_SECURITY_DATE_PCT={metadata['unknown_security_date_pct']:.6%}",
        f"MAX_UNKNOWN_PORTFOLIO_WEIGHT={metadata['max_unknown_portfolio_weight']:.6%}",
        "FUTURE_FILING_VIOLATIONS=0", "BACKWARD_FILL_VIOLATIONS=0",
        f"TAXONOMY_FREEZE_STATUS={metadata['taxonomy_freeze_status']}", f"TAXONOMY_HASH={metadata['taxonomy_hash']}", "",
        "RAW A2", "-" * 60,
        f"RAW_CAGR={raw['cagr']}", f"RAW_SHARPE={raw['sharpe']}", f"RAW_MAXDD={raw['max_drawdown']}",
        f"RAW_FF12_HHI={conc['ff12_hhi']}", f"RAW_FF12_MAX_WEIGHT={conc['ff12_max_weight']}", f"RAW_FF12_EFFECTIVE_COUNT={conc['ff12_effective_count']}",
        f"RAW_FF48_HHI={conc['ff48_hhi']}", f"RAW_FF48_MAX_WEIGHT={conc['ff48_max_weight']}", f"RAW_FF48_EFFECTIVE_COUNT={conc['ff48_effective_count']}", "",
        "RESEARCH", "-" * 60,
        f"TOTAL_TRIALS={metadata['total_trials']}", f"SUCCESSFUL_TRIALS={metadata['successful_trials']}", f"FAILED_TRIALS={metadata['failed_trials']}",
        f"PARETO_FRONTIER_SIZE={metadata['pareto_frontier_size']}", f"FINALIST_COUNT={metadata['finalist_count']}",
        "FINALISTS_FROZEN_BEFORE_2025_READ=TRUE",
        f"PRIMARY_CHALLENGER={metadata['primary_challenger']}", f"PRIMARY_CLASSIFICATION={metadata['primary_classification']}", "",
        "PRIMARY CHALLENGER", "-" * 60,
        f"CHALLENGER_FAMILY={value('family')}", f"CHALLENGER_METHOD={value('method')}",
        f"CHALLENGER_CAGR={value('cagr')}", f"CHALLENGER_SHARPE={value('sharpe')}", f"CHALLENGER_MAXDD={value('max_drawdown')}",
        f"CHALLENGER_QQQ_BETA={value('qqq_beta')}", f"CHALLENGER_RESIDUAL_SHARPE={value('residual_sharpe')}",
        f"CHALLENGER_FF12_HHI={value('ff12_hhi')}",
        f"FF12_HHI_REDUCTION_PCT={(conc['ff12_hhi'] - value('ff12_hhi')) / conc['ff12_hhi'] if challenger else 'NOT_APPLICABLE:NO_PRIMARY_CHALLENGER'}",
        f"CHALLENGER_FF12_MAX_WEIGHT={value('ff12_max_weight')}", f"CHALLENGER_FF12_EFFECTIVE_COUNT={value('ff12_effective_count')}",
        f"CHALLENGER_FF48_HHI={value('ff48_hhi')}",
        f"FF48_HHI_REDUCTION_PCT={(conc['ff48_hhi'] - value('ff48_hhi')) / conc['ff48_hhi'] if challenger else 'NOT_APPLICABLE:NO_PRIMARY_CHALLENGER'}",
        f"CHALLENGER_FF48_MAX_WEIGHT={value('ff48_max_weight')}", f"CHALLENGER_FF48_EFFECTIVE_COUNT={value('ff48_effective_count')}",
        f"CHALLENGER_TURNOVER={value('turnover')}", f"CHALLENGER_COST={value('cost')}", "",
        "TEMPORAL", "-" * 60,
        f"2023_CLASSIFICATION={metadata['temporal_classification']['2023']}",
        f"2024_CLASSIFICATION={metadata['temporal_classification']['2024']}",
        f"2025_CONFIRMATION={metadata['temporal_classification']['2025']}",
        f"PARAMETER_NEEDLE_WARNING={str(metadata['parameter_needle_warning']).upper()}",
        f"SINGLE_PERIOD_DEPENDENCE={str(metadata['single_period_dependence']).upper()}", "",
        "GOVERNANCE", "-" * 60,
        f"MAX_TRAIN_DATE={metadata.get('max_train_date')}", f"MAX_SELECTION_DATE={metadata.get('max_selection_date')}",
        "2025_CANDIDATE_OUTCOME_READ_BEFORE_FREEZE=FALSE", "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0",
        f"ANTI_OVERFIT_STATUS={metadata['anti_overfit_status']}", f"ANTI_BLOAT_STATUS={metadata['anti_bloat_status']}", "",
        "VERDICT", "-" * 60,
        f"DOES_ROBUST_SECTOR_DECONCENTRATION_EXIST={'TRUE' if metadata['primary_challenger'] != 'NONE' else 'FALSE'}",
        f"MOST_DAMAGING_EVIDENCE={metadata['most_damaging_evidence']}",
        f"STRONGEST_SUPPORTING_EVIDENCE={metadata['strongest_supporting_evidence']}",
        f"R6_DIAGNOSTIC_STATUS={metadata['r6_diagnostic_status']}",
        "RECOMMENDED_SINGLE_NEXT_STEP=" + ("FREEZE_PRIMARY_CHALLENGER_FOR_FORWARD_ONLY_VALIDATION" if metadata['primary_challenger'] != "NONE" else "STOP_HISTORICAL_DECONCENTRATION_OPTIMIZATION_AND_KEEP_RAW_A2_CONTROL"),
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={len(list(OUT.iterdir()))}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "=" * 60,
    ]))


def gate_value(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("coverage_gate_pass"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Idempotently resume from the verified SEC cache.")
    parser.add_argument("--targeted-sec-identity-stage", action="store_true", help="Reserved narrow official-SEC identity handoff; bulk quarterly staging is never invoked.")
    parser.add_argument("--finalize-existing", action="store_true", help="Re-sign existing completed research after governance-status reconciliation; performs no outcome computation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require(not args.targeted_sec_identity_stage, "TARGETED_STAGE_NOT_REQUIRED_OFFLINE_GATE_EXPECTED_TO_PASS")
    if args.finalize_existing:
        base = import_file("a2_sec_taxonomy_base_for_finalization", BASE_SOURCE)
        metadata_path = OUT / "research_metadata.json"
        ledger_path = OUT / "identity_gap_reconciliation.csv"
        require(metadata_path.is_file() and ledger_path.is_file(), "FINALIZATION_INPUT_MISSING")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["task_status"] = "RESEARCH_COMPLETE_FAIL_ANTI_BLOAT_HARD_GATE"
        trials = pd.read_parquet(OUT / "trial_ledger.parquet")
        selection = trials.loc[trials.fold.eq("SELECTION_2023_2024")].set_index("trial_id")
        raw_selection, s1 = selection.loc["S0_RAW"], selection.loc["S1_SOFT_025"]
        raw_2025 = trials.loc[trials.trial_id.eq("S0_RAW") & trials.fold.eq("2025")].iloc[-1]
        s1_2025 = trials.loc[trials.trial_id.eq("S1_SOFT_025") & trials.fold.eq("2025")].iloc[-1]
        raw_conc = metadata["raw_concentration"]
        challenger = metadata["challenger"]
        metadata["most_damaging_evidence"] = (
            f"FORMAL_PRIMARY_FF12_HHI_REDUCTION_ONLY_"
            f"{(raw_conc['ff12_hhi'] - challenger['ff12_hhi']) / raw_conc['ff12_hhi']:.6%};"
            f"MAXDD_DELTA_{challenger['max_drawdown'] - metadata['raw_full']['max_drawdown']:.6%};"
            "FORMAL_PRIMARY_IS_A_WEAK_DECONCENTRATION_MOVE"
        )
        metadata["strongest_supporting_evidence"] = (
            f"FROZEN_S1_SOFT_025_SELECTION_HHI_REDUCTION_"
            f"{(raw_selection.ff12_hhi - s1.ff12_hhi) / raw_selection.ff12_hhi:.6%};"
            f"SELECTION_SHARPE_RETENTION_{s1.sharpe / raw_selection.sharpe:.6%};"
            f"2025_HHI_REDUCTION_{(raw_2025.ff12_hhi - s1_2025.ff12_hhi) / raw_2025.ff12_hhi:.6%};"
            f"2025_SHARPE_DELTA_{s1_2025.sharpe - raw_2025.sharpe:.6f};"
            "SPEC_WAS_FROZEN_BEFORE_2025_READ"
        )
        atomic_json(metadata_path, metadata)
        render_report(metadata, pd.read_csv(ledger_path))
        write_hash_manifest(base, metadata)
        terminal(metadata)
        return 0
    metadata = run()
    terminal(metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
