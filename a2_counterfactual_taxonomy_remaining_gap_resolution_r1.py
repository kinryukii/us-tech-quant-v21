"""Targeted tail-gap recovery for the canonical pre-2026 PIT SIC/FF surface.

This runner deliberately has three phases.  ``prepare`` freezes the denominator,
the complete missing-row ledger, and the bounded SEC request plan.  ``recover``
may then open only the accessions named by that frozen plan.  ``finalize`` is
reserved for validation/review/registry publication after the scientific output
has been inspected.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import requests


TASK_ID = "A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
BASE_TASK = "A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1"
BASE = RESULTS / BASE_TASK
REGISTRY_MODULE = REPO / "research_registry.py"
REGISTRY_CONFIG = REPO / "config" / "research_registry.json"

BASE_SURFACE = BASE / "pit_sec_sic_ff12_ff48_eligible_surface.parquet"
BASE_BRIDGE = BASE / "security_identity_bridge.parquet"
BASE_EVENTS = BASE / "sec_as_filed_sic_events.parquet"
BASE_IDENTITY_HEADERS = BASE / "sec_header_identity_manifest.parquet"
BASE_SIC_HEADERS = BASE / "sec_header_sic_state_manifest.parquet"
BASE_PROVIDER_HEADERS = BASE / "provider_cache" / "sec_headers"
BASE_FINAL_MANIFEST = BASE / "final_manifest.json"
BASE_STATUS = BASE / "taxonomy_surface_status.json"
BASE_SIC_CONTRACT = BASE / "sic_availability_contract.json"
BASE_FF12_MANIFEST = BASE / "ff12_mapping_manifest.json"
BASE_FF48_MANIFEST = BASE / "ff48_mapping_manifest.json"
SEC_SUB = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_fsds_sub_min.parquet")
SEC_SOURCE_MANIFEST = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_source_manifest.json")
FF12_ZIP = BASE / "provider_cache" / "kenneth_french" / "official_ff12_sic_definitions.zip"
FF48_ZIP = BASE / "provider_cache" / "kenneth_french" / "official_ff48_sic_definitions.zip"
RV_CONTRACT = RESULTS / "A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1" / "rv_contract.json"

EXPECTED = {
    BASE_SURFACE: "591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646",
    BASE_BRIDGE: "439c9bfa1d92915f3c3a2fe7320d88f8db16e5fe1aacba6cb5f8720635641866",
    BASE_EVENTS: "1b50135121476a574a66b2331cc90e346e5d47232aec5df897a67e246a79a4fb",
    BASE_IDENTITY_HEADERS: "cff0f8914139e63281c3e101ef6c9e0436125329f2f793a356db76f255c2d439",
    BASE_SIC_HEADERS: "c847279b4e9fb4bb7b9a40d947fa613799eb918e076b15f591d199e989137f84",
    BASE_FINAL_MANIFEST: "8447_PLACEHOLDER",
    BASE_STATUS: "fac90ff26c3fdabcf2b5ae0ce73a379dcaf8684151dc4e263b45b1190aa42de7",
    BASE_SIC_CONTRACT: "6c595671b6fc29aeecc57987de6f316fc279bf582919c941d83fe857d2c4fda2",
    BASE_FF12_MANIFEST: "d37b1939e7f38709183d313d680a0a4e662f6fb36330b1067f51b6461b38f91d",
    BASE_FF48_MANIFEST: "322a98feb1cc349bb6b55cc3523b11f8def532213d61a79dda59aada37bd9da7",
    SEC_SUB: "ce2f7a3a2df1237a1b30f79eaf31604c6ea256029e8726f65c6b50112089489e",
    SEC_SOURCE_MANIFEST: "217e75433fa73f6d4a9070b0553caceb99413a9d3a365dd52ef47451a4c59b63",
    FF12_ZIP: "d801141acf039f2e06e6d4d9ba2b3992e9747a1d82fabd53ef21da4a3af79fff",
    FF48_ZIP: "f37edffc024fe7b91b794dd933244430da2de212df2549dc448c0dfcca45d740",
    RV_CONTRACT: "146af857798c21441b24a1106d32112878ffba43be289ac69098b9a4c070e9c8",
}

# The manifest itself is intentionally not pinned by the task contract because
# its finalization timestamp was updated after the surface hash was frozen.  All
# consumed member hashes are pinned above and checked against the manifest.
EXPECTED.pop(BASE_FINAL_MANIFEST)

TOTAL = 313_668
BASE_MAPPED = 278_757
BASE_COVERAGE = 0.8887007919201194
BASE_UNMAPPED = 34_911
BASE_RANK_GT20_COVERAGE = 0.887100338883159
DISSEMINATION_LAG_MINUTES = 5
DEFAULT_USER_AGENT = "us-tech-quant targeted PIT taxonomy recovery JIN kinryukii@gmail.com"
TAXONOMY_ENTITY = "PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE"
RV_ENTITY = "A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1"

ZERO_COUNTERS = {
    "new_alpha_component_count": 0,
    "new_predictive_model_count": 0,
    "new_model_fit_count": 0,
    "new_security_master_count": 0,
    "new_taxonomy_framework_count": 0,
    "new_factor_surface_count": 0,
    "new_capacity_surface_count": 0,
    "new_moomoo_fetch_count": 0,
    "new_threshold_search_count": 0,
    "new_taxonomy_search_count": 0,
    "new_portfolio_spec_count": 0,
    "moomoo_history_request_count": 0,
    "post_2025_realized_label_metric_read_count": 0,
    "post_2025_model_evaluation_metric_read_count": 0,
    "post_2025_outcome_derived_metadata_read_count": 0,
    "2026_economic_outcome_read_count": 0,
    "holdout_peek_count": 0,
    "mixed_source_content_open_count": 0,
    "economic_result_read_count": 0,
}

PRIMARY_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
LISTING_FORMS = {"S-1", "S-3", "F-1", "F-3"}
GAP_FORMS = {"8-K", "6-K", "10", "10-12B", "10-12G"}

# Fixed 13F/SEC spelling normalization.  It changes issuer-bridge spelling only;
# it never infers SIC or FF48 from a name.  Every promoted link still requires a
# unique CIK and a validated historical SEC header with an as-filed SIC.
TOKEN_EXPANSIONS = {
    "AIRLS": "AIRLINES", "AMER": "AMERICA", "CMNTYS": "COMMUNITIES",
    "CONTL": "CONTINENTAL", "COR": "CORPORATION", "COS": "COMPANIES",
    "CTZNS": "CITIZENS", "ELEC": "ELECTRIC", "ENTMT": "ENTERTAINMENT",
    "FINL": "FINANCIAL", "FMRS": "FARMERS", "HL": "HOLDINGS",
    "HLD": "HOLDINGS", "HLDG": "HOLDINGS", "HLDGS": "HOLDINGS",
    "HLDNGS": "HOLDINGS", "INDS": "INDUSTRIES", "INS": "INSURANCE",
    "INSTRS": "INSTRUMENTS", "INTL": "INTERNATIONAL", "MATLS": "MATERIALS",
    "MFG": "MANUFACTURING", "MGMT": "MANAGEMENT", "MKTS": "MARKETS",
    "MTRS": "MOTORS", "PETE": "PETROLEUM", "PPTYS": "PROPERTIES",
    "PWR": "POWER", "RLTY": "REALTY", "SOLU": "SOLUTIONS",
    "SVC": "SERVICES", "SVCS": "SERVICES", "SYS": "SYSTEMS",
    "SYSTEM": "SYSTEMS", "THERAPEUTIC": "THERAPEUTICS",
    "TRANSN": "TRANSPORTATION", "WHSL": "WHOLESALE",
}
DROP_TOKENS = {
    "AG", "BV", "CA", "CO", "COMPANY", "CORP", "CORPORATION", "DE",
    "DEL", "FORMERLY", "INC", "INCORPORATED", "L", "LIMITED", "LLC",
    "LP", "LTD", "MA", "MD", "MN", "N", "NEW", "NV", "NY", "OH",
    "P", "PA", "PL", "PLC", "SA", "SD", "SE", "SPA", "STATES",
    "THE", "TX", "UNITED", "V", "VA",
}
MIN_TRUNCATED_PREFIX_CHARS = 20


class TaskError(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise TaskError(f"{code}:{detail}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def row_sha256(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].copy()
    for column in columns:
        if isinstance(values[column].dtype, pd.DatetimeTZDtype):
            values[column] = values[column].dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z").fillna("<NA>")
        elif pd.api.types.is_datetime64_any_dtype(values[column]):
            values[column] = values[column].dt.strftime("%Y-%m-%dT%H:%M:%S.%f").fillna("<NA>")
        else:
            values[column] = values[column].astype("string").fillna("<NA>")
    return values.apply(lambda row: hashlib.sha256("\x1f".join(str(value) for value in row.tolist()).encode("utf-8")).hexdigest(), axis=1)


def foundation_row_sha256(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    """Use the canonical foundation's exact row-hash serialization contract."""
    values = frame[list(columns)].copy()
    for column in columns:
        if pd.api.types.is_datetime64_any_dtype(values[column]):
            values[column] = pd.to_datetime(values[column], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z").astype("string").fillna("<NA>")
        else:
            values[column] = values[column].astype("string").fillna("<NA>")
    return values.apply(lambda row: hashlib.sha256("\x1f".join(str(value) for value in row.tolist()).encode("utf-8")).hexdigest(), axis=1)


def registry_module() -> Any:
    spec = importlib.util.spec_from_file_location("canonical_research_registry_tail_gap", REGISTRY_MODULE)
    require(spec is not None and spec.loader is not None, "HARD_BLOCKER_REGISTRY_CORRUPT", REGISTRY_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_root(module: Any) -> Path:
    root, _ = module._load_config(str(REGISTRY_CONFIG), None)
    return Path(root)


def tail_name_tokens(value: Any) -> list[str]:
    text = re.sub(r"\b([NBS])\s*\.\s*V\s*\.", r" \1 V ", str(value).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", text).split()
    tokens = [TOKEN_EXPANSIONS.get(token, token) for token in tokens]
    return [token for token in tokens if token and token not in DROP_TOKENS]


def tail_name_key(value: Any) -> str:
    return "".join(tail_name_tokens(value))


def tail_names_equivalent(left: Any, right: Any) -> bool:
    left_key, right_key = tail_name_key(left), tail_name_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shorter, longer = sorted((left_key, right_key), key=len)
    return len(shorter) >= MIN_TRUNCATED_PREFIX_CHARS and longer.startswith(shorter)


def base_form(value: Any) -> str:
    return re.sub(r"/A$", "", str(value).upper())


def form_allowed(value: Any) -> bool:
    form = base_form(value)
    return form in PRIMARY_FORMS | LISTING_FORMS | GAP_FORMS or form.startswith("424B")


def next_legal_session(accepted: pd.Series, legal_dates: Sequence[pd.Timestamp]) -> pd.Series:
    accepted_utc = pd.to_datetime(accepted, utc=True) + pd.Timedelta(minutes=DISSEMINATION_LAG_MINUTES)
    normalized = accepted_utc.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize().to_numpy(dtype="datetime64[ns]")
    sessions = np.asarray(pd.to_datetime(list(legal_dates)), dtype="datetime64[ns]")
    positions = np.searchsorted(sessions, normalized, side="right")
    result = np.full(len(positions), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    valid = positions < len(sessions)
    result[valid] = sessions[positions[valid]]
    return pd.Series(pd.to_datetime(result), index=accepted.index)


def parse_sec_header(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="latin-1", errors="replace")

    def one(tag: str) -> str | None:
        match = re.search(rf"<{re.escape(tag)}>\s*([^\r\n<]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else None

    names = re.findall(r"<(?:FORMER-CONFORMED-NAME|CONFORMED-NAME)>\s*([^\r\n<]+)", text, flags=re.IGNORECASE)
    accepted = pd.to_datetime(one("ACCEPTANCE-DATETIME"), format="%Y%m%d%H%M%S", errors="coerce")
    if pd.notna(accepted):
        accepted = accepted.tz_localize("America/New_York", ambiguous="raise", nonexistent="shift_forward").tz_convert("UTC")
    return {
        "header_cik": pd.to_numeric(one("CIK") or one("CENTRAL-INDEX-KEY"), errors="coerce"),
        "header_sic": pd.to_numeric(one("ASSIGNED-SIC"), errors="coerce"),
        "header_accession": one("ACCESSION-NUMBER"),
        "header_form": one("TYPE") or one("FORM-TYPE"),
        "header_acceptance_datetime": accepted,
        "header_names": names,
    }


def sec_header_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}.hdr.sgml"


def parse_ff_definition(path: Path, taxonomy: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "FF_ZIP_INTEGRITY_FAILURE", taxonomy)
        members = [name for name in archive.namelist() if not name.endswith("/")]
        require(len(members) == 1, "FF_ZIP_MEMBER_COUNT", members)
        raw = archive.read(members[0])
    current: tuple[int, str, str] | None = None
    ranges: list[dict[str, Any]] = []
    for line in raw.decode("latin-1").splitlines():
        range_match = re.match(r"^\s*(\d{4})-(\d{4})(?:\s+.*?)?\s*$", line)
        header = re.match(r"^\s*(\d{1,2})\s+([A-Za-z0-9]+)\s+(.+?)\s*$", line)
        if header and not range_match:
            current = (int(header.group(1)), header.group(2), header.group(3).strip())
        elif range_match and current is not None:
            ranges.append({"industry_code": current[0], "industry_short_name": current[1], "industry_name": current[2], "sic_start": int(range_match.group(1)), "sic_end": int(range_match.group(2))})
    expanded = []
    for row in ranges:
        for sic in range(row["sic_start"], row["sic_end"] + 1):
            expanded.append({"sic4": sic, "industry_code": row["industry_code"], "industry_short_name": row["industry_short_name"], "industry_name": row["industry_name"]})
    mapping = pd.DataFrame(expanded)
    require(not mapping.duplicated("sic4").any(), "FF_OFFICIAL_RANGE_OVERLAP", taxonomy)
    if taxonomy == "FF12":
        residual = sorted(set(range(100, 10000)) - set(mapping.sic4))
        mapping = pd.concat([mapping, pd.DataFrame({"sic4": residual, "industry_code": 12, "industry_short_name": "Other", "industry_name": "Other"})], ignore_index=True)
    return mapping, {"taxonomy": taxonomy, "official_zip_sha256": sha256_file(path), "official_member_sha256": hashlib.sha256(raw).hexdigest(), "range_count": len(ranges), "mapping_fingerprint": sha256_value(ranges)}


def input_readback() -> dict[str, Any]:
    manifest = json.loads(BASE_FINAL_MANIFEST.read_text(encoding="utf-8"))
    checks = []
    for path, expected in EXPECTED.items():
        actual = sha256_file(path)
        require(actual == expected, "AUTHORITATIVE_INPUT_HASH_MISMATCH", f"{path}:{actual}")
        member = manifest.get("files", {}).get(path.name)
        if path.parent == BASE and member:
            require(member.get("sha256") == actual and member.get("byte_size") == path.stat().st_size, "AUTHORITATIVE_MANIFEST_MEMBER_MISMATCH", path.name)
        checks.append({"path": str(path), "sha256": actual, "byte_size": path.stat().st_size})
    return {"status": "PASS", "checks": checks, "base_manifest_sha256": sha256_file(BASE_FINAL_MANIFEST)}


def build_registry_preflight() -> tuple[Any, Path, str]:
    registry = registry_module()
    root = registry_root(registry)
    current = registry.current_state(root)
    validation = registry.validate_registry(root)
    require(current.get("status") == "PASS" and validation.get("status") == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT")
    head = str(current["head_sha256"])
    taxonomy = registry.query_registry(root, entity_id=TAXONOMY_ENTITY)
    rv = registry.query_registry(root, entity_id=RV_ENTITY)
    require(taxonomy.get("count") == 1 and taxonomy["entities"][0].get("status") == "ACTIVE", "HARD_BLOCKER_REGISTRY_CORRUPT", TAXONOMY_ENTITY)
    require(rv.get("count") == 1, "HARD_BLOCKER_REGISTRY_CORRUPT", RV_ENTITY)
    all_entities = registry.query_registry(root)["entities"]
    terms = ["taxonomy gap", "SEC SIC", "FF48", "FF12", "PIT taxonomy", "security master", "identity bridge", "counterfactual readiness", "sector-neutral RV"]
    matches = {}
    for term in terms:
        normalized = term.lower().replace("-", " ")
        matches[term] = sorted({str(row["entity_id"]) for row in all_entities if normalized in json.dumps(row, sort_keys=True).lower().replace("-", " ")})
    alias_results = {}
    for alias in ["PIT AS FILED SEC SIC FF12 FF48 ELIGIBLE SURFACE", "A2 SECTOR NEUTRAL CONTINUOUS RANK RV V1"]:
        try:
            alias_results[alias] = registry.resolve_alias(root, alias)
        except Exception as exc:  # absence is recorded, never guessed
            alias_results[alias] = {"status": "UNAVAILABLE", "error": str(exc)}
    existing = taxonomy["entities"][0]
    contract = recovery_contract()
    candidate = {
        "entity_id": TASK_ID,
        "canonical_name": TASK_ID,
        "entity_type": "DATA_INFRASTRUCTURE_MAINTENANCE",
        "status": "ACTIVE",
        "specification_fingerprint": sha256_value(contract),
        "information_source_fingerprint": existing["information_source_fingerprint"],
        "mechanism_fingerprint": existing["mechanism_fingerprint"],
        "decision_layer": "TARGETED_EVIDENCE_EXTENSION_OF_EXISTING_PIT_SIC_FF48_SURFACE",
        "parent_entity_id": TAXONOMY_ENTITY,
        "evidence_source_temporal_status": "SAFE_PRE2026_OFFICIAL_OR_CERTIFIED_LOCAL",
        "excluded_source_refs": ["**/risk_registry.json", "current SEC SIC", "current Moomoo industry"],
        "temporal_evidence_limitations": ["EVIDENCE_EXTENSION_ONLY", "NO_PARALLEL_TAXONOMY_ENTITY"],
        "information_family": "PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE",
    }
    proposal = {"candidate": candidate, "change_type": "EVIDENCE_EXTENSION_ONLY", "parent_entity_id": TAXONOMY_ENTITY}
    proposal_result = registry.preflight_proposal(root, proposal)
    require(proposal_result.get("decision") not in {"BLOCKED_EXACT_DUPLICATE", "BLOCKED_CLOSED_BRANCH", "BLOCKED_SUPERSEDED_BRANCH"}, "HARD_BLOCKER_PREEXISTING_EXACT_DUPLICATE", proposal_result)
    payload = {
        "task_id": TASK_ID, "status": "PASS", "registry_base_head": head,
        "current": current, "validation": validation, "taxonomy_query": taxonomy,
        "rv_query": rv, "concept_queries": matches, "alias_resolution": alias_results,
        "proposal": proposal, "proposal_result": proposal_result,
    }
    atomic_json(OUT / "registry_preflight.json", payload)
    anti = {
        "task_id": TASK_ID,
        "status": "PASS",
        "decision": "EXTEND_EXISTING_CANONICAL_PIT_SIC_FF48_CAPABILITY",
        "canonical_entity_id": TAXONOMY_ENTITY,
        "parallel_taxonomy_entity_created": False,
        "reason": "The ACTIVE canonical PIT as-filed SEC SIC/FF12/FF48 surface exists; this task attaches targeted evidence/version only.",
        "registry_head_sha256": head,
        "proposal_decision": proposal_result.get("decision"),
    }
    atomic_json(OUT / "anti_duplication_preflight.json", anti)
    return registry, root, head


def recovery_contract() -> dict[str, Any]:
    return {
        "contract_id": "A2_COUNTERFACTUAL_TAXONOMY_TAIL_TARGETED_SEC_HEADER_RECOVERY_R1",
        "scope": "ONLY_BASE_FF48_UNMAPPED_CANONICAL_SECURITY_DATE_ROWS",
        "base_total": TOTAL,
        "base_mapped": BASE_MAPPED,
        "base_surface_sha256": EXPECTED[BASE_SURFACE],
        "temporal_contract_sha256": EXPECTED[BASE_SIC_CONTRACT],
        "dissemination_lag_minutes": DISSEMINATION_LAG_MINUTES,
        "availability_rule": "NEXT_LEGAL_DECISION_SESSION_STRICTLY_AFTER_ACCEPTANCE_PLUS_5_MINUTES",
        "candidate_rule": "UNIQUE_CIK_FROM_EXACT_FIXED_13F_SEC_TOKEN_NORMALIZATION_OR_FIXED_TRUNCATED_PREFIX",
        "validation_rule": "OFFICIAL_HISTORICAL_SEC_HEADER_CIK_SIC_ACCEPTANCE_ACCESSION_FORM_AND_NAME_EQUIVALENCE_ALL_PASS;NEW_ISSUER_LINKS_ALSO_REQUIRE_EXACT_AS_FILED_XBRL_TRADING_SYMBOL",
        "candidate_forms": sorted(PRIMARY_FORMS | LISTING_FORMS | GAP_FORMS) + ["424B*"],
        "reuse_before_request": True,
        "one_accession_per_unique_candidate_security": True,
        "minimum_truncated_prefix_characters": MIN_TRUNCATED_PREFIX_CHARS,
        "token_expansions": TOKEN_EXPANSIONS,
        "drop_tokens": sorted(DROP_TOKENS),
        "forbidden": [
            "CURRENT_SIC_BACKFILL", "CURRENT_MOOMOO_INDUSTRY", "FUTURE_FILING_BACKFILL",
            "NAME_TO_SECTOR_INFERENCE", "SYNTHETIC_FF48", "MOOMOO_HISTORY_REQUEST",
            "TOP20_DEPENDENT_TAXONOMY", "INNER_JOIN_MISSING_ROW_DELETION",
        ],
        "ff48_mapping": "IMMUTABLE_KENNETH_FRENCH_OFFICIAL_SIC_RANGES",
        "new_threshold_search_count": 0,
        "new_taxonomy_search_count": 0,
    }


def load_authoritative_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    surface = pd.read_parquet(BASE_SURFACE)
    bridge = pd.read_parquet(BASE_BRIDGE)
    events = pd.read_parquet(BASE_EVENTS)
    sub = pd.read_parquet(SEC_SUB)
    surface["decision_date"] = pd.to_datetime(surface.decision_date).dt.normalize()
    bridge["decision_date"] = pd.to_datetime(bridge.decision_date).dt.normalize()
    sub["accepted_timestamp_utc"] = pd.to_datetime(sub.accepted_timestamp_utc, utc=True)
    require(len(surface) == TOTAL and len(bridge) == TOTAL, "HARD_BLOCKER_CANONICAL_KEYSET_CONFLICT")
    require(not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "HARD_BLOCKER_CANONICAL_KEYSET_CONFLICT", "surface duplicates")
    require(not bridge.duplicated(["decision_date", "canonical_security_id"]).any(), "HARD_BLOCKER_CANONICAL_KEYSET_CONFLICT", "bridge duplicates")
    require(int(surface.ff48_code.notna().sum()) == BASE_MAPPED, "HARD_BLOCKER_CANONICAL_KEYSET_CONFLICT", "mapped denominator")
    require(int(surface.ff48_code.isna().sum()) == BASE_UNMAPPED, "HARD_BLOCKER_CANONICAL_KEYSET_CONFLICT", "unmapped denominator")
    require(surface.decision_date.max() <= pd.Timestamp("2025-12-31"), "HARD_BLOCKER_TEMPORAL_INTEGRITY_UNPROVEN")
    require(sub.accepted_timestamp_utc.max() <= pd.Timestamp("2025-12-31 23:59:59", tz="UTC"), "HARD_BLOCKER_TEMPORAL_INTEGRITY_UNPROVEN")
    return surface, bridge, events, sub


def build_candidate_index(sub: pd.DataFrame, project_names: Mapping[str, set[str]]) -> tuple[dict[str, set[int]], pd.DataFrame]:
    rows = []
    for field, role in (("name", "CURRENT_LEGAL_NAME"), ("former", "FORMER_NAME_AS_FILED")):
        piece = sub[["adsh", "cik", "sic", "form", "accepted_timestamp_utc", "instance", field]].rename(columns={field: "sec_name"}).copy()
        piece = piece.loc[piece.sec_name.fillna("").ne("") & piece.form.map(form_allowed)]
        piece["name_role"] = role
        rows.append(piece)
    names = pd.concat(rows, ignore_index=True)
    names["base_form"] = names.form.map(base_form)
    names["sec_name_key"] = names.sec_name.map(tail_name_key)
    distinct = names.loc[names.sec_name_key.ne(""), ["cik", "sec_name_key"]].drop_duplicates()
    exact: dict[str, set[int]] = {}
    for key, group in distinct.groupby("sec_name_key"):
        exact[str(key)] = set(group.cik.dropna().astype(int))
    distinct_pairs = [(str(row.sec_name_key), int(row.cik)) for row in distinct.itertuples(index=False)]
    candidate_ciks: dict[str, set[int]] = {}
    matches = []
    for security_id, variants in sorted(project_names.items()):
        project_keys = {tail_name_key(variant) for variant in variants if tail_name_key(variant)}
        ciks: set[int] = set()
        for project_key in project_keys:
            ciks.update(exact.get(project_key, set()))
            if len(project_key) >= MIN_TRUNCATED_PREFIX_CHARS:
                ciks.update(cik for sec_key, cik in distinct_pairs if (len(sec_key) >= MIN_TRUNCATED_PREFIX_CHARS and (sec_key.startswith(project_key) or project_key.startswith(sec_key))))
        candidate_ciks[security_id] = ciks
        if ciks:
            candidate_rows = names.loc[names.cik.isin(ciks)].copy()
            mask = pd.Series(False, index=candidate_rows.index)
            for project_key in project_keys:
                mask |= candidate_rows.sec_name_key.eq(project_key)
                if len(project_key) >= MIN_TRUNCATED_PREFIX_CHARS:
                    mask |= candidate_rows.sec_name_key.str.startswith(project_key) | candidate_rows.sec_name_key.map(lambda sec_key: len(sec_key) >= MIN_TRUNCATED_PREFIX_CHARS and project_key.startswith(sec_key))
            matched = candidate_rows.loc[mask].copy()
        else:
            matched = names.iloc[0:0].copy()
        if not matched.empty:
            matched["canonical_security_id"] = security_id
            matches.append(matched)
    return candidate_ciks, pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=[*names.columns, "canonical_security_id"])


def cached_header_candidates() -> tuple[dict[str, dict[str, Any]], set[str]]:
    combined = pd.concat([pd.read_parquet(BASE_IDENTITY_HEADERS), pd.read_parquet(BASE_SIC_HEADERS)], ignore_index=True)
    combined = combined.sort_values(["adsh", "validation_status"], kind="mergesort").drop_duplicates("adsh", keep="last")
    passed = combined.loc[combined.validation_status.eq("PASS")]
    return {str(row.adsh): row._asdict() for row in passed.itertuples(index=False)}, set(passed.adsh.astype(str))


def choose_recovery_plan(
    surface: pd.DataFrame,
    bridge: pd.DataFrame,
    sub: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, set[int]], pd.DataFrame]:
    missing = surface.loc[surface.ff48_code.isna(), ["decision_date", "canonical_security_id", "ticker_at_date", "taxonomy_status", "sic4", "a2_rank"]]
    project_names = bridge.loc[bridge.canonical_security_id.isin(missing.canonical_security_id), ["canonical_security_id", "issuer_name"]].dropna()
    name_map = project_names.groupby("canonical_security_id").issuer_name.agg(lambda values: set(map(str, values))).to_dict()
    candidate_ciks, candidate_matches = build_candidate_index(sub, name_map)
    cached_by_accession, cached_accessions = cached_header_candidates()
    legal_dates = sorted(surface.decision_date.unique())
    candidate_matches["usable_decision_session"] = next_legal_session(candidate_matches.accepted_timestamp_utc, legal_dates) if not candidate_matches.empty else pd.NaT
    security_summary = missing.groupby("canonical_security_id", as_index=False).agg(
        ticker_at_date=("ticker_at_date", "last"),
        missing_observations=("decision_date", "size"),
        first_missing_date=("decision_date", "min"),
        last_missing_date=("decision_date", "max"),
        base_taxonomy_status=("taxonomy_status", lambda values: "|".join(sorted(set(map(str, values))))),
    )
    existing_security_ciks = bridge.groupby("canonical_security_id").cik.agg(lambda values: sorted(set(values.dropna().astype(int)))).to_dict()
    plan_rows = []
    for row in security_summary.itertuples(index=False):
        security_id = str(row.canonical_security_id)
        ciks = candidate_ciks.get(security_id, set())
        action = "NO_REQUEST_FAIL_CLOSED"
        reason = "NO_UNIQUE_CIK_CANDIDATE"
        selected: Mapping[str, Any] = {}
        if row.base_taxonomy_status == "SIC_VALID_FF48_UNMAPPED":
            reason = "SIC_PRESENT_BUT_NOT_FF48_MAPPABLE"
        elif len(ciks) > 1:
            reason = "MULTIPLE_CIK_CANDIDATES_FAIL_CLOSED"
        elif len(ciks) == 1:
            cik = next(iter(ciks))
            candidates = candidate_matches.loc[
                candidate_matches.canonical_security_id.eq(security_id)
                & candidate_matches.cik.eq(cik)
                & candidate_matches.sic.notna()
                & candidate_matches.usable_decision_session.notna()
                & candidate_matches.instance.fillna("").ne("")
            ].copy()
            prior = candidates.loc[candidates.usable_decision_session.le(row.first_missing_date)]
            cached_prior = prior.loc[prior.adsh.astype(str).isin(cached_accessions)]
            if not cached_prior.empty:
                picked = cached_prior.sort_values(["accepted_timestamp_utc", "adsh"], kind="mergesort").iloc[-1]
                action, reason = "REUSE_VALIDATED_HEADER_CACHE", "UNIQUE_CIK_AND_PRIOR_CACHED_HEADER"
            elif not prior.empty:
                picked = prior.sort_values(["accepted_timestamp_utc", "adsh"], kind="mergesort").iloc[-1]
                action, reason = "TARGETED_SEC_HEADER_REQUEST", "UNIQUE_CIK_PRIOR_AS_FILED_CANDIDATE"
            elif not candidates.empty:
                picked = candidates.sort_values(["accepted_timestamp_utc", "adsh"], kind="mergesort").iloc[0]
                action, reason = "TARGETED_SEC_HEADER_REQUEST", "UNIQUE_CIK_FIRST_EVIDENCE_AFTER_INITIAL_GAP"
            else:
                picked = None
                reason = "UNIQUE_CIK_BUT_NO_CLASSIFIABLE_FILING"
            if picked is not None:
                selected = picked.to_dict()
        existing_ciks = existing_security_ciks.get(security_id, [])
        new_issuer_link = bool(selected) and int(selected.get("cik")) not in existing_ciks
        instance_name = str(selected.get("instance", "")) if selected else ""
        instance_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(selected['cik'])}/{str(selected['adsh']).replace('-', '')}/{instance_name}"
            if selected and instance_name else ""
        )
        plan_rows.append({
            "canonical_security_id": security_id,
            "ticker_at_date": row.ticker_at_date,
            "missing_observations": int(row.missing_observations),
            "first_missing_date": row.first_missing_date,
            "last_missing_date": row.last_missing_date,
            "base_taxonomy_status": row.base_taxonomy_status,
            "candidate_cik_count": len(ciks),
            "candidate_ciks": "|".join(map(str, sorted(ciks))),
            "action": action,
            "plan_reason": reason,
            "target_cik": selected.get("cik"),
            "target_accession": selected.get("adsh"),
            "target_form": selected.get("form"),
            "target_sic": selected.get("sic"),
            "target_acceptance_datetime": selected.get("accepted_timestamp_utc"),
            "target_usable_decision_session": selected.get("usable_decision_session"),
            "source_url": sec_header_url(int(selected["cik"]), str(selected["adsh"])) if selected else "",
            "cache_path": str(BASE_PROVIDER_HEADERS / f"{selected.get('adsh')}.hdr.sgml") if selected and str(selected.get("adsh")) in cached_by_accession else "",
            "target_instance": instance_name,
            "instance_url": instance_url,
            "new_issuer_link": new_issuer_link,
            "instance_validation_required": new_issuer_link,
            "request_allowed": action == "TARGETED_SEC_HEADER_REQUEST" or new_issuer_link,
        })
    plan = pd.DataFrame(plan_rows).sort_values(["missing_observations", "canonical_security_id"], ascending=[False, True], kind="mergesort")
    plan["plan_row_sha256"] = row_sha256(plan, [column for column in plan.columns])
    return plan, candidate_ciks, candidate_matches


def classify_gap_rows(
    surface: pd.DataFrame,
    bridge: pd.DataFrame,
    sub: pd.DataFrame,
    plan: pd.DataFrame,
    candidate_ciks: Mapping[str, set[int]],
) -> pd.DataFrame:
    base_cols = ["decision_date", "canonical_security_id", "ticker_at_date", "exchange_at_date", "cik", "identity_status", "sic4", "ff48_code", "taxonomy_status", "mapping_reason", "a2_rank"]
    gap = surface.loc[surface.ff48_code.isna(), base_cols].copy()
    bridge_cols = ["decision_date", "canonical_security_id", "issuer_name", "title_of_class", "effective_start", "effective_end", "confidence_class", "temporal_status", "evidence_type", "issuer_candidate_count", "history_cik_conflict"]
    gap = gap.merge(bridge[bridge_cols], on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    gap = gap.merge(plan[["canonical_security_id", "candidate_cik_count", "candidate_ciks", "action", "plan_reason", "target_cik", "target_accession", "target_acceptance_datetime", "target_usable_decision_session"]], on="canonical_security_id", how="left", validate="many_to_one")
    group_ciks = bridge.groupby("canonical_security_id").cik.agg(lambda values: sorted(set(values.dropna().astype(int)))).to_dict()
    sub_by_cik = {int(cik): group.sort_values("accepted_timestamp_utc") for cik, group in sub.loc[sub.cik.notna()].groupby("cik")}
    gap["CUSIP"] = gap.canonical_security_id
    gap["country_or_issuer_type"] = np.where(gap.CUSIP.str.match(r"^[A-Z]"), "FOREIGN_CINS_NAMESPACE", "US_NUMERIC_CUSIP_NAMESPACE")
    gap["existing_identity_status"] = gap.identity_status
    gap["existing_SEC_bridge_status"] = gap.temporal_status.astype(str) + "|" + gap.evidence_type.astype(str)
    gap["existing_SIC_status"] = np.where(gap.sic4.notna(), "PRESENT", "UNAVAILABLE")
    gap["existing_FF48_status"] = "UNMAPPED"
    # This interval comes from the canonical identity/CUSIP bridge.  It is not
    # an authoritative exchange-listing date, so do not use it as listing age.
    gap["identity_interval_start"] = pd.to_datetime(gap.effective_start).dt.normalize()
    gap["first_known_listing_date"] = pd.NaT
    first_filing, last_prior = [], []
    for row in gap.itertuples(index=False):
        known = group_ciks.get(str(row.canonical_security_id), [])
        candidates = sorted(candidate_ciks.get(str(row.canonical_security_id), set()))
        ciks = known if known else candidates if len(candidates) == 1 else []
        frames = [sub_by_cik[cik] for cik in ciks if cik in sub_by_cik]
        if not frames:
            first_filing.append(pd.NaT)
            last_prior.append(pd.NaT)
        else:
            filings = pd.concat(frames, ignore_index=True).sort_values("accepted_timestamp_utc")
            first_filing.append(filings.accepted_timestamp_utc.iloc[0])
            eligible = filings.loc[filings.accepted_timestamp_utc.le(pd.Timestamp(row.decision_date, tz="UTC") + pd.Timedelta(days=1))]
            last_prior.append(eligible.accepted_timestamp_utc.iloc[-1] if not eligible.empty else pd.NaT)
    gap["first_known_SEC_filing_date"] = first_filing
    gap["last_known_SEC_filing_before_decision"] = last_prior

    is_foreign = gap.country_or_issuer_type.eq("FOREIGN_CINS_NAMESPACE")
    is_adr = gap.title_of_class.fillna("").str.contains("ADR|ADS|DEPOSITARY", case=False, regex=True)
    history_conflict = gap.history_cik_conflict.fillna(False)
    ambiguous = gap.issuer_candidate_count.fillna(0).gt(1) | gap.candidate_cik_count.fillna(0).gt(1)
    sic_unmapped = gap.sic4.notna() & gap.ff48_code.isna()
    candidate_prior = pd.to_datetime(gap.target_usable_decision_session).notna() & pd.to_datetime(gap.target_usable_decision_session).le(gap.decision_date)
    candidate_later = gap.candidate_cik_count.eq(1) & ~candidate_prior
    gap["gap_reason_primary"] = np.select(
        [sic_unmapped, history_conflict, ambiguous, candidate_prior, candidate_later, is_adr, is_foreign],
        ["SIC_PRESENT_BUT_NOT_FF48_MAPPABLE", "CIK_TRANSITION_OR_ISSUER_CHANGE", "CIK_TRANSITION_OR_ISSUER_CHANGE", "SEC_ISSUER_BRIDGE_NOT_AVAILABLE_AT_DATE", "TEMPORAL_AVAILABILITY_GAP", "ADR_OR_DEPOSITARY_STRUCTURE", "FOREIGN_PRIVATE_ISSUER"],
        default="SEC_ISSUER_BRIDGE_NOT_AVAILABLE_AT_DATE",
    )
    gap["gap_reason_secondary"] = np.select(
        [gap.taxonomy_status.eq("SIC_UNAVAILABLE"), gap.candidate_cik_count.eq(0), gap.candidate_cik_count.gt(1), gap.action.eq("REUSE_VALIDATED_HEADER_CACHE")],
        ["SEC_FORM_SCOPE_GAP", "NO_SEC_FILING_AVAILABLE_BEFORE_DATE", "SHARE_CLASS_SECURITY_ISSUER_AMBIGUITY", "SEC_ARCHIVE_RETRIEVAL_GAP"],
        default=gap.plan_reason.fillna("OTHER_DOCUMENTED"),
    )
    gap["repairability_class"] = np.select(
        [sic_unmapped, history_conflict | ambiguous, gap.action.eq("REUSE_VALIDATED_HEADER_CACHE"), gap.action.eq("TARGETED_SEC_HEADER_REQUEST") & candidate_prior, gap.action.eq("TARGETED_SEC_HEADER_REQUEST")],
        ["NON_REPAIRABLE_OFFICIAL_MAPPING_GAP", "FAIL_CLOSED_IDENTITY_CONFLICT", "CACHE_REUSE_REPAIRABLE", "TARGETED_SEC_REPAIRABLE", "PARTIAL_TARGETED_SEC_REPAIRABLE"],
        default="COMMERCIAL_OR_NEW_INDEPENDENT_SOURCE_REQUIRED",
    )
    gap["candidate_source_class"] = np.where(gap.action.eq("REUSE_VALIDATED_HEADER_CACHE"), "CERTIFIED_LOCAL_SEC_HEADER_CACHE", np.where(gap.action.eq("TARGETED_SEC_HEADER_REQUEST"), "OFFICIAL_SEC_ARCHIVES_TARGETED", "UNAVAILABLE"))
    columns = [
        "decision_date", "canonical_security_id", "ticker_at_date", "CUSIP", "cik", "exchange_at_date", "country_or_issuer_type",
        "existing_identity_status", "existing_SEC_bridge_status", "existing_SIC_status", "existing_FF48_status",
        "first_known_listing_date", "identity_interval_start", "first_known_SEC_filing_date", "last_known_SEC_filing_before_decision",
        "gap_reason_primary", "gap_reason_secondary", "repairability_class", "candidate_source_class",
        "candidate_cik_count", "candidate_ciks", "target_cik", "target_accession", "a2_rank",
    ]
    ledger = gap[columns].sort_values(["decision_date", "canonical_security_id"], kind="mergesort").reset_index(drop=True)
    ledger["row_sha256"] = row_sha256(ledger, columns)
    require(len(ledger) == BASE_UNMAPPED and not ledger.duplicated(["decision_date", "canonical_security_id"]).any(), "GAP_LEDGER_KEY_FAILURE")
    return ledger


def rank_bucket(rank: pd.Series) -> pd.Series:
    return pd.cut(rank, bins=[0, 20, 40, 100, 200, np.inf], labels=["RANK_1_20", "RANK_21_40", "RANK_41_100", "RANK_101_200", "RANK_201_PLUS"])


def write_gap_reports(ledger: pd.DataFrame, plan: pd.DataFrame) -> None:
    summary = ledger.groupby(["gap_reason_primary", "gap_reason_secondary", "repairability_class"], dropna=False).agg(observations=("decision_date", "size"), unique_securities=("canonical_security_id", "nunique")).reset_index()
    summary["share_of_unmapped"] = summary.observations / BASE_UNMAPPED
    atomic_csv(OUT / "gap_reason_summary.csv", summary.sort_values("observations", ascending=False))
    by_year = ledger.assign(year=ledger.decision_date.dt.year).groupby(["year", "gap_reason_primary"], dropna=False).agg(observations=("decision_date", "size"), unique_securities=("canonical_security_id", "nunique")).reset_index()
    atomic_csv(OUT / "gap_reason_by_year.csv", by_year)
    by_rank = ledger.assign(rank_bucket=rank_bucket(ledger.a2_rank)).groupby(["rank_bucket", "gap_reason_primary"], observed=True, dropna=False).agg(observations=("decision_date", "size"), unique_securities=("canonical_security_id", "nunique")).reset_index()
    atomic_csv(OUT / "gap_reason_by_rank_bucket.csv", by_rank)
    by_security = ledger.groupby("canonical_security_id", as_index=False).agg(ticker_at_date=("ticker_at_date", "last"), observations=("decision_date", "size"), first_missing_date=("decision_date", "min"), last_missing_date=("decision_date", "max"), gap_reason_primary=("gap_reason_primary", lambda values: "|".join(sorted(set(values)))), repairability_class=("repairability_class", lambda values: "|".join(sorted(set(values)))))
    by_security = by_security.sort_values(["observations", "canonical_security_id"], ascending=[False, True], kind="mergesort")
    atomic_csv(OUT / "gap_reason_by_security.csv", by_security)
    closure = by_security.merge(plan[["canonical_security_id", "action", "plan_reason", "candidate_ciks", "target_accession"]], on="canonical_security_id", how="left", validate="one_to_one")
    closure["priority_class"] = np.select([closure.action.eq("REUSE_VALIDATED_HEADER_CACHE"), closure.action.eq("TARGETED_SEC_HEADER_REQUEST")], ["P1_CACHE_REUSE", "P2_TARGETED_SEC"], default="P3_FAIL_CLOSED")
    closure = closure.sort_values(["priority_class", "observations", "canonical_security_id"], ascending=[True, False, True], kind="mergesort").reset_index(drop=True)
    closure["structural_priority_rank"] = np.arange(1, len(closure) + 1)
    closure["cumulative_repairable_observations"] = np.where(closure.priority_class.ne("P3_FAIL_CLOSED"), closure.observations, 0).cumsum()
    required_rows = int(np.ceil(0.90 * TOTAL) - BASE_MAPPED)
    repairable = closure.priority_class.ne("P3_FAIL_CLOSED")
    crossing = np.flatnonzero((repairable & closure.cumulative_repairable_observations.ge(required_rows)).to_numpy())
    require(len(crossing) > 0, "MINIMUM_STRUCTURAL_GATE_SET_UNAVAILABLE", required_rows)
    closure["rows_required_for_overall_90_gate"] = required_rows
    closure["minimum_gate_set_member"] = repairable & (np.arange(len(closure)) <= int(crossing[0]))
    atomic_csv(OUT / "minimal_structural_gap_closure_set.csv", closure)


def prepare() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    readback = input_readback()
    registry, root, head = build_registry_preflight()
    contract = recovery_contract()
    atomic_json(OUT / "targeted_recovery_contract.json", contract)
    surface, bridge, events, sub = load_authoritative_inputs()
    plan, candidate_ciks, _ = choose_recovery_plan(surface, bridge, sub)
    ledger = classify_gap_rows(surface, bridge, sub, plan, candidate_ciks)
    atomic_parquet(OUT / "remaining_ff48_gap_ledger.parquet", ledger)
    atomic_csv(OUT / "targeted_sec_recovery_plan.csv", plan)
    write_gap_reports(ledger, plan)
    status = json.loads(BASE_STATUS.read_text(encoding="utf-8"))
    baseline = {
        "task_id": TASK_ID,
        "status": "PASS_FROZEN_BEFORE_EXTERNAL_RETRIEVAL",
        "created_utc": utc_now(),
        "registry_base_head": head,
        "base_total_eligible_observations": TOTAL,
        "base_strict_ff48_mapped": BASE_MAPPED,
        "base_strict_ff48_coverage": BASE_COVERAGE,
        "base_unmapped_observations": BASE_UNMAPPED,
        "base_rank_gt20_ff48_coverage": BASE_RANK_GT20_COVERAGE,
        "base_surface_sha256": EXPECTED[BASE_SURFACE],
        "base_key_uniqueness": True,
        "base_date_min": str(surface.decision_date.min().date()),
        "base_date_max": str(surface.decision_date.max().date()),
        "input_readback": readback,
        "recovery_contract_sha256": sha256_file(OUT / "targeted_recovery_contract.json"),
        "gap_ledger_sha256": sha256_file(OUT / "remaining_ff48_gap_ledger.parquet"),
        "gap_ledger_rows": len(ledger),
        "gap_unique_securities": int(ledger.canonical_security_id.nunique()),
        "targeted_plan_sha256": sha256_file(OUT / "targeted_sec_recovery_plan.csv"),
        "targeted_security_count": int(plan.action.isin(["REUSE_VALIDATED_HEADER_CACHE", "TARGETED_SEC_HEADER_REQUEST"]).sum()),
        "targeted_sec_request_count_planned": int(plan.action.eq("TARGETED_SEC_HEADER_REQUEST").sum()),
        "zero_read_counters": ZERO_COUNTERS,
        "base_status_readback": status,
    }
    atomic_json(OUT / "authoritative_baseline_manifest.json", baseline)
    print(json.dumps({key: baseline[key] for key in ["status", "registry_base_head", "base_total_eligible_observations", "base_strict_ff48_mapped", "base_unmapped_observations", "gap_unique_securities", "targeted_security_count", "targeted_sec_request_count_planned"]}, indent=2))
    return baseline


def official_get(
    url: str,
    target: Path,
    *,
    user_agent: str,
    max_attempts: int = 4,
    limiter: dict[str, float] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if target.is_file():
        return {"status": "REUSED", "path": str(target), "url": url, "sha256": sha256_file(target), "byte_size": target.stat().st_size}
    session = session or requests.Session()
    session.trust_env = False
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    error = ""
    for attempt in range(max_attempts):
        try:
            if limiter is not None and limiter.get("last", 0.0):
                time.sleep(max(0.0, 0.21 - (time.monotonic() - limiter["last"])))
            response = session.get(url, headers=headers, timeout=120)
            if limiter is not None:
                limiter["last"] = time.monotonic()
            if response.status_code == 200:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(response.content)
                os.replace(temporary, target)
                return {"status": "DOWNLOADED", "path": str(target), "url": url, "sha256": sha256_file(target), "byte_size": target.stat().st_size}
            error = f"HTTP_{response.status_code}"
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}:{exc}"
        if attempt + 1 < max_attempts:
            time.sleep(min(2 ** attempt, 16))
    return {"status": "UNAVAILABLE", "path": str(target), "url": url, "error": error}


def clean_fact_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&amp;", "&").replace("&#160;", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", value).strip()


def parse_instance_identity(path: Path) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    facts: dict[str, list[str]] = {}
    for fact in ("TradingSymbol", "SecurityExchangeName", "Security12bTitle"):
        values: set[str] = set()
        for pattern in (
            rf"<(?:[A-Za-z0-9_.-]+:)?{fact}\b[^>]*>(.*?)</(?:[A-Za-z0-9_.-]+:)?{fact}>",
            rf"<ix:nonNumeric\b(?=[^>]*\bname=[\"'][^\"']*:{fact}[\"'])[^>]*>(.*?)</ix:nonNumeric>",
        ):
            for match in re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                cleaned = clean_fact_text(match)
                if cleaned:
                    values.add(cleaned)
        facts[fact] = sorted(values)
    return facts


def normalized_ticker(value: Any) -> str:
    return re.sub(r"[^A-Z0-9.-]", "", str(value).upper())


def share_class_tokens(value: Any) -> set[str]:
    text = str(value).upper()
    tokens: set[str] = set()
    for label, pattern in {
        "CLASS_A": r"(?:CLASS|CL)\s*A\b",
        "CLASS_B": r"(?:CLASS|CL)\s*B\b",
        "ADR_ADS": r"\b(?:ADR|ADS|DEPOSITARY)\b",
        "ORDINARY": r"\b(?:ORD|ORDINARY)\b",
        "COMMON": r"\b(?:COM|COMMON)\b",
    }.items():
        if re.search(pattern, text):
            tokens.add(label)
    return tokens


def validate_header(
    parsed: Mapping[str, Any],
    plan_row: Mapping[str, Any],
    project_names: Iterable[str],
) -> tuple[bool, str]:
    expected_acceptance = pd.Timestamp(plan_row["target_acceptance_datetime"])
    if expected_acceptance.tzinfo is None:
        expected_acceptance = expected_acceptance.tz_localize("UTC")
    checks = {
        "CIK": pd.notna(parsed.get("header_cik")) and int(parsed["header_cik"]) == int(float(plan_row["target_cik"])),
        "SIC": pd.notna(parsed.get("header_sic")) and int(parsed["header_sic"]) == int(float(plan_row["target_sic"])),
        "ACCEPTED": pd.notna(parsed.get("header_acceptance_datetime")) and abs((pd.Timestamp(parsed["header_acceptance_datetime"]) - expected_acceptance).total_seconds()) <= 60,
        "ACCESSION": str(parsed.get("header_accession")) == str(plan_row["target_accession"]),
        "FORM": str(parsed.get("header_form", "")).upper() == str(plan_row["target_form"]).upper(),
        "NAME": any(tail_names_equivalent(project_name, header_name) for project_name in project_names for header_name in parsed.get("header_names", [])),
    }
    return all(checks.values()), ";".join(f"{key}={value}" for key, value in checks.items())


def validate_instance(
    facts: Mapping[str, list[str]],
    ticker: str,
    project_title: str,
) -> tuple[bool, str]:
    symbols = {normalized_ticker(value) for value in facts.get("TradingSymbol", []) if normalized_ticker(value)}
    target = normalized_ticker(ticker)
    ticker_ok = target in symbols
    title_tokens = share_class_tokens(project_title)
    filing_tokens = set().union(*(share_class_tokens(value) for value in facts.get("Security12bTitle", []))) if facts.get("Security12bTitle") else set()
    # Multiple as-filed symbols require class/title corroboration.  A single
    # exact symbol is sufficient for an issuer-level SIC bridge.
    class_ok = len(symbols) <= 1 or not title_tokens or bool(title_tokens & filing_tokens)
    return ticker_ok and class_ok, f"TICKER={ticker_ok};CLASS={class_ok};SYMBOLS={'|'.join(sorted(symbols))};PROJECT_CLASS={'|'.join(sorted(title_tokens))};FILING_CLASS={'|'.join(sorted(filing_tokens))}"


def run_targeted_requests(user_agent: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline = json.loads((OUT / "authoritative_baseline_manifest.json").read_text(encoding="utf-8"))
    require(sha256_file(OUT / "targeted_recovery_contract.json") == baseline["recovery_contract_sha256"], "FROZEN_RECOVERY_CONTRACT_CHANGED")
    require(sha256_file(OUT / "remaining_ff48_gap_ledger.parquet") == baseline["gap_ledger_sha256"], "FROZEN_GAP_LEDGER_CHANGED")
    require(sha256_file(OUT / "targeted_sec_recovery_plan.csv") == baseline["targeted_plan_sha256"], "FROZEN_TARGETED_PLAN_CHANGED")
    plan = pd.read_csv(OUT / "targeted_sec_recovery_plan.csv")
    bridge = pd.read_parquet(BASE_BRIDGE)
    project_names = bridge.groupby("canonical_security_id").issuer_name.agg(lambda values: sorted(set(map(str, values.dropna())))).to_dict()
    project_titles = bridge.groupby("canonical_security_id").title_of_class.agg(lambda values: str(values.dropna().iloc[-1]) if not values.dropna().empty else "").to_dict()
    limiter = {"last": 0.0}
    session = requests.Session()
    session.trust_env = False
    rows, evidence_rows = [], []
    for plan_row in plan.to_dict("records"):
        security_id = str(plan_row["canonical_security_id"])
        action = str(plan_row["action"])
        if action == "NO_REQUEST_FAIL_CLOSED" or pd.isna(plan_row.get("target_accession")):
            rows.append({
                "canonical_security_id": security_id, "ticker_at_date": plan_row.get("ticker_at_date"),
                "action": action, "status": "SKIPPED_FAIL_CLOSED", "plan_reason": plan_row.get("plan_reason"),
                "header_request_count": 0, "instance_request_count": 0, "validation_reason": plan_row.get("plan_reason"),
            })
            continue
        accession = str(plan_row["target_accession"])
        cached_path = str(plan_row.get("cache_path", ""))
        if cached_path and cached_path.lower() != "nan" and Path(cached_path).is_file():
            header_path = Path(cached_path)
        else:
            header_path = OUT / "provider_cache" / "sec_headers" / f"{accession}.hdr.sgml"
        header_result = official_get(str(plan_row["source_url"]), header_path, user_agent=user_agent, limiter=limiter, session=session)
        header_valid = False
        header_reason = header_result.get("error", "DOWNLOAD_UNAVAILABLE")
        parsed_header: dict[str, Any] = {}
        if header_result.get("status") in {"DOWNLOADED", "REUSED"}:
            parsed_header = parse_sec_header(header_path)
            header_valid, header_reason = validate_header(parsed_header, plan_row, project_names.get(security_id, []))

        instance_required = str(plan_row.get("instance_validation_required", "False")).lower() == "true"
        instance_result: dict[str, Any] = {"status": "NOT_REQUIRED"}
        instance_facts: dict[str, list[str]] = {"TradingSymbol": [], "SecurityExchangeName": [], "Security12bTitle": []}
        instance_valid, instance_reason = (True, "EXISTING_STRICT_CIK_LINK_REUSED") if not instance_required else (False, "INSTANCE_UNAVAILABLE")
        if instance_required:
            instance_name = str(plan_row.get("target_instance", ""))
            if instance_name and instance_name.lower() != "nan":
                instance_path = OUT / "provider_cache" / "sec_instances" / accession / Path(instance_name).name
                instance_result = official_get(str(plan_row["instance_url"]), instance_path, user_agent=user_agent, limiter=limiter, session=session)
                if instance_result.get("status") in {"DOWNLOADED", "REUSED"}:
                    instance_facts = parse_instance_identity(instance_path)
                    instance_valid, instance_reason = validate_instance(instance_facts, str(plan_row["ticker_at_date"]), project_titles.get(security_id, ""))
        status = "PASS" if header_valid and instance_valid else "FAIL_CLOSED"
        header_request_count = int(header_result.get("status") == "DOWNLOADED")
        instance_request_count = int(instance_result.get("status") == "DOWNLOADED")
        result_row = {
            "canonical_security_id": security_id,
            "ticker_at_date": plan_row.get("ticker_at_date"),
            "action": action,
            "status": status,
            "plan_reason": plan_row.get("plan_reason"),
            "target_cik": int(float(plan_row["target_cik"])),
            "target_accession": accession,
            "target_form": plan_row.get("target_form"),
            "target_sic": int(float(plan_row["target_sic"])),
            "target_acceptance_datetime": plan_row.get("target_acceptance_datetime"),
            "target_usable_decision_session": plan_row.get("target_usable_decision_session"),
            "header_status": header_result.get("status"),
            "header_path": header_result.get("path", str(header_path)),
            "header_sha256": header_result.get("sha256", ""),
            "header_request_count": header_request_count,
            "instance_required": instance_required,
            "instance_status": instance_result.get("status"),
            "instance_path": instance_result.get("path", ""),
            "instance_sha256": instance_result.get("sha256", ""),
            "instance_request_count": instance_request_count,
            "trading_symbols": "|".join(instance_facts.get("TradingSymbol", [])),
            "security_exchange_names": "|".join(instance_facts.get("SecurityExchangeName", [])),
            "security_12b_titles": "|".join(instance_facts.get("Security12bTitle", [])),
            "validation_reason": f"HEADER[{header_reason}];INSTANCE[{instance_reason}]",
        }
        rows.append(result_row)
        if status == "PASS":
            accepted = pd.Timestamp(parsed_header["header_acceptance_datetime"])
            evidence_rows.append({
                "canonical_security_id": security_id,
                "ticker_at_date": plan_row.get("ticker_at_date"),
                "cik": int(parsed_header["header_cik"]),
                "accession_number": accession,
                "form": str(parsed_header["header_form"]),
                "acceptance_datetime": accepted,
                "assigned_sic": int(parsed_header["header_sic"]),
                "sic_available_at": accepted + pd.Timedelta(minutes=DISSEMINATION_LAG_MINUTES),
                "usable_decision_session": pd.Timestamp(plan_row["target_usable_decision_session"]),
                "source_archive_ref": str(plan_row["source_url"]),
                "source_sha256": str(header_result["sha256"]),
                "identity_instance_ref": str(plan_row.get("instance_url", "")) if instance_required else "EXISTING_STRICT_CIK_LINK",
                "identity_instance_sha256": str(instance_result.get("sha256", "")) if instance_required else "",
                "identity_evidence_type": "EXACT_AS_FILED_XBRL_TRADING_SYMBOL" if instance_required else "EXISTING_STRICT_CIK_LINK_REUSED",
                "evidence_temporal_status": "STRICT_PIT",
            })
        atomic_csv(OUT / "targeted_sec_recovery_results.csv", pd.DataFrame(rows))
    results = pd.DataFrame(rows)
    evidence = pd.DataFrame(evidence_rows)
    if evidence.empty:
        evidence = pd.DataFrame(columns=[
            "canonical_security_id", "ticker_at_date", "cik", "accession_number", "form", "acceptance_datetime", "assigned_sic", "sic_available_at", "usable_decision_session", "source_archive_ref", "source_sha256", "identity_instance_ref", "identity_instance_sha256", "identity_evidence_type", "evidence_temporal_status",
        ])
    evidence["row_sha256"] = row_sha256(evidence, [column for column in evidence.columns]) if not evidence.empty else pd.Series(dtype="string")
    atomic_parquet(OUT / "new_classification_evidence.parquet", evidence)
    return results, evidence


def extend_surface(evidence: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    surface = pd.read_parquet(BASE_SURFACE)
    surface["decision_date"] = pd.to_datetime(surface.decision_date).dt.normalize()
    ff12, ff12_meta = parse_ff_definition(FF12_ZIP, "FF12")
    ff48, ff48_meta = parse_ff_definition(FF48_ZIP, "FF48")
    ff12_lookup = ff12.set_index("sic4").to_dict("index")
    ff48_lookup = ff48.set_index("sic4").to_dict("index")
    base_copy = surface.copy(deep=True)
    changed_indices: list[int] = []
    for row in evidence.itertuples(index=False):
        sic = int(row.assigned_sic)
        if sic not in ff48_lookup or sic not in ff12_lookup:
            continue
        usable = pd.Timestamp(row.usable_decision_session).normalize()
        mask = surface.canonical_security_id.eq(str(row.canonical_security_id)) & surface.ff48_code.isna() & surface.decision_date.ge(usable)
        indices = surface.index[mask].tolist()
        if not indices:
            continue
        changed_indices.extend(indices)
        surface.loc[mask, "cik"] = int(row.cik)
        surface.loc[mask, "sic4"] = sic
        surface.loc[mask, "sic_available_at"] = pd.Timestamp(row.sic_available_at)
        surface.loc[mask, "sic_accession"] = str(row.accession_number)
        surface.loc[mask, "sic_source_sha256"] = str(row.source_sha256)
        surface.loc[mask, "ff48_code"] = int(ff48_lookup[sic]["industry_code"])
        surface.loc[mask, "ff48_name"] = str(ff48_lookup[sic]["industry_name"])
        surface.loc[mask, "ff12_code"] = int(ff12_lookup[sic]["industry_code"])
        surface.loc[mask, "ff12_name"] = str(ff12_lookup[sic]["industry_name"])
        surface.loc[mask, "taxonomy_status"] = "STRICT_PIT_SIC_FF12_FF48_MAPPED"
        surface.loc[mask, "mapping_reason"] = "TARGETED_VERIFIED_SEC_HEADER_IDENTITY_AND_OFFICIAL_FRENCH_RULES"
        source_payload = json.dumps({
            "base_surface_sha256": EXPECTED[BASE_SURFACE],
            "targeted_header_sha256": str(row.source_sha256),
            "targeted_identity_instance_sha256": str(row.identity_instance_sha256),
            "ff12_official_zip_sha256": EXPECTED[FF12_ZIP],
            "ff48_official_zip_sha256": EXPECTED[FF48_ZIP],
            "temporal_contract_sha256": EXPECTED[BASE_SIC_CONTRACT],
        }, sort_keys=True)
        surface.loc[mask, "source_fingerprints"] = source_payload
    changed_indices = sorted(set(changed_indices))
    output_columns = [column for column in surface.columns if column != "row_sha256"]
    if changed_indices:
        surface.loc[changed_indices, "row_sha256"] = foundation_row_sha256(surface.loc[changed_indices], output_columns).values
    # Every base-mapped row and every unchanged row must remain byte-value equal.
    unchanged = surface.index.difference(changed_indices)
    comparison_columns = list(surface.columns)
    require(surface.loc[unchanged, comparison_columns].reset_index(drop=True).equals(base_copy.loc[unchanged, comparison_columns].reset_index(drop=True)), "UNAUTHORIZED_EXISTING_ROW_CHANGE")
    require(base_copy.loc[changed_indices, "ff48_code"].isna().all() if changed_indices else True, "NEW_EVIDENCE_CHANGED_PREVIOUSLY_MAPPED_ROW")
    require(len(surface) == TOTAL and not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "UPDATED_SURFACE_KEY_FAILURE")
    available = pd.to_datetime(surface.sic_available_at, utc=True)
    require(available.loc[available.notna()].dt.tz_convert(None).le(surface.loc[available.notna(), "decision_date"]).all(), "FUTURE_SIC_BACKWARD_FILL")
    output = OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet"
    atomic_parquet(output, surface.sort_values(["decision_date", "canonical_security_id"], kind="mergesort").reset_index(drop=True))
    manifest = {
        "task_id": TASK_ID,
        "status": "PASS",
        "entity_id": TAXONOMY_ENTITY,
        "base_surface_path": str(BASE_SURFACE),
        "base_surface_sha256": EXPECTED[BASE_SURFACE],
        "surface_path": str(output),
        "surface_sha256": sha256_file(output),
        "row_count": len(surface),
        "unique_key": True,
        "min_date": str(surface.decision_date.min().date()),
        "max_date": str(surface.decision_date.max().date()),
        "additional_strict_ff48_rows": len(changed_indices),
        "new_persistent_data_surface_count": 1,
        "ff12_mapping": ff12_meta,
        "ff48_mapping": ff48_meta,
        "temporal_contract_sha256": EXPECTED[BASE_SIC_CONTRACT],
        "targeted_evidence_sha256": sha256_file(OUT / "new_classification_evidence.parquet"),
        "source_lineage": [str(BASE_SURFACE), str(SEC_SUB), str(OUT / "targeted_sec_recovery_results.csv")],
    }
    atomic_json(OUT / "taxonomy_surface_manifest.json", manifest)
    return surface, manifest


def coverage_rows(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = [{"version": label, "dimension": "OVERALL", "bucket": "ALL", "total": len(frame), "mapped": int(frame.ff48_code.notna().sum())}]
    work = frame.assign(year=pd.to_datetime(frame.decision_date).dt.year, rank_group=np.where(frame.a2_rank.le(20), "RANK_LE20", "RANK_GT20"))
    for dimension, column in (("YEAR", "year"), ("RANK_GROUP", "rank_group")):
        for value, group in work.groupby(column, observed=True):
            rows.append({"version": label, "dimension": dimension, "bucket": str(value), "total": len(group), "mapped": int(group.ff48_code.notna().sum())})
    result = pd.DataFrame(rows)
    result["unmapped"] = result.total - result.mapped
    result["coverage"] = result.mapped / result.total
    return result


def missingness_bias_report(surface: pd.DataFrame, bridge: pd.DataFrame) -> pd.DataFrame:
    work = surface[["decision_date", "canonical_security_id", "ff48_code", "a2_rank"]].merge(
        bridge[["decision_date", "canonical_security_id", "title_of_class", "exchange_at_date"]],
        on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one",
    )
    work["year"] = work.decision_date.dt.year
    work["rank_bucket"] = rank_bucket(work.a2_rank).astype("string")
    work["listing_age_bucket"] = "UNAVAILABLE_NO_AUTHORITATIVE_LISTING_DATE"
    work["security_namespace"] = np.where(work.canonical_security_id.str.match(r"^[A-Z]"), "FOREIGN_CINS", "US_NUMERIC_CUSIP")
    work["listing_type"] = np.select(
        [work.title_of_class.fillna("").str.contains("ADR|ADS|DEPOSITARY", case=False, regex=True), work.title_of_class.fillna("").str.contains("ORD", case=False, regex=True), work.title_of_class.fillna("").str.contains("COM", case=False, regex=True)],
        ["ADR_ADS", "ORDINARY", "COMMON"], default="OTHER_OR_UNAVAILABLE",
    )
    rows = []
    for dimension in ["year", "rank_bucket", "listing_age_bucket", "security_namespace", "listing_type", "exchange_at_date"]:
        for value, group in work.groupby(dimension, dropna=False, observed=True):
            rows.append({"dimension": dimension.upper(), "bucket": "UNAVAILABLE" if pd.isna(value) else str(value), "total": len(group), "mapped": int(group.ff48_code.notna().sum()), "unmapped": int(group.ff48_code.isna().sum()), "coverage": float(group.ff48_code.notna().mean())})
    rows.extend([
        {"dimension": "PIT_MARKET_CAP_BUCKET", "bucket": "UNAVAILABLE_NO_FROZEN_CONSTRUCTIBLE_MARKET_CAP", "total": len(work), "mapped": int(work.ff48_code.notna().sum()), "unmapped": int(work.ff48_code.isna().sum()), "coverage": float(work.ff48_code.notna().mean())},
        {"dimension": "PIT_LIQUIDITY_BUCKET", "bucket": "NOT_RECOMPUTED_EXISTING_CAPACITY_SURFACE_UNCHANGED", "total": len(work), "mapped": int(work.ff48_code.notna().sum()), "unmapped": int(work.ff48_code.isna().sum()), "coverage": float(work.ff48_code.notna().mean())},
    ])
    return pd.DataFrame(rows)


def analyze_after(surface: pd.DataFrame, manifest: Mapping[str, Any], results: pd.DataFrame) -> dict[str, Any]:
    before = pd.read_parquet(BASE_SURFACE)
    before["decision_date"] = pd.to_datetime(before.decision_date).dt.normalize()
    bridge = pd.read_parquet(BASE_BRIDGE)
    bridge["decision_date"] = pd.to_datetime(bridge.decision_date).dt.normalize()
    coverage = pd.concat([coverage_rows(before, "BEFORE"), coverage_rows(surface, "AFTER")], ignore_index=True)
    atomic_csv(OUT / "taxonomy_coverage_before_after.csv", coverage)
    bias = missingness_bias_report(surface, bridge)
    atomic_csv(OUT / "taxonomy_missingness_bias_report.csv", bias)
    after_overall = float(surface.ff48_code.notna().mean())
    after_mapped = int(surface.ff48_code.notna().sum())
    rank_le = float(surface.loc[surface.a2_rank.le(20), "ff48_code"].notna().mean())
    rank_gt = float(surface.loc[surface.a2_rank.gt(20), "ff48_code"].notna().mean())
    year_cov = surface.assign(year=surface.decision_date.dt.year).groupby("year").ff48_code.apply(lambda values: float(values.notna().mean()))
    gates = {
        "overall_90_gate": after_overall >= 0.90,
        "each_year_85_gate": bool(year_cov.ge(0.85).all()),
        "rank_gt20_85_gate": rank_gt >= 0.85,
        "rank_coverage_gap_10pp_gate": abs(rank_le - rank_gt) <= 0.10,
    }
    ready = all(gates.values())
    remaining = surface.loc[surface.ff48_code.isna()].copy()
    readiness = {
        "task_id": TASK_ID,
        "status": "READY_WITH_DOCUMENTED_STRUCTURAL_MISSINGNESS" if ready and len(remaining) else "READY" if ready else "NOT_READY",
        "counterfactual_identification_ready": "YES" if ready else "NO",
        "strict_ff48_mapped_before": BASE_MAPPED,
        "strict_ff48_coverage_before": BASE_COVERAGE,
        "strict_ff48_mapped_after": after_mapped,
        "strict_ff48_coverage_after": after_overall,
        "additional_strict_ff48_rows": after_mapped - BASE_MAPPED,
        "rank_le20_ff48_coverage_after": rank_le,
        "rank_gt20_ff48_coverage_after": rank_gt,
        "minimum_year_ff48_coverage_after": float(year_cov.min()),
        "year_coverage": {str(year): value for year, value in year_cov.items()},
        "gates": gates,
        "remaining_observations": len(remaining),
        "remaining_unique_securities": int(remaining.canonical_security_id.nunique()),
        "structural_limitation": "STRICT_PIT_MISSING_ROWS_REMAIN_NO_SYNTHETIC_FILL" if len(remaining) else "NONE",
        "zero_read_counters": ZERO_COUNTERS,
    }
    atomic_json(OUT / "counterfactual_readiness.json", readiness)
    rv = {
        "rv_frozen_child": RV_ENTITY,
        "rv_contract_sha256": EXPECTED[RV_CONTRACT],
        "rv_contract_modified": False,
        "rv_economics_run": False,
        "rv_contract_compatibility": "NO",
        "rv_data_dependency_available": False,
        "reason": "Frozen RV V1 requires authoritative sector grouping; FF48 remains an industry-control taxonomy and no authoritative sector-equivalence contract exists.",
    }
    atomic_json(OUT / "rv_data_dependency_report.json", rv)
    if not ready:
        ledger = pd.read_parquet(OUT / "remaining_ff48_gap_ledger.parquet")
        remaining_keys = remaining[["decision_date", "canonical_security_id", "a2_rank"]].merge(
            ledger[["decision_date", "canonical_security_id", "gap_reason_primary", "gap_reason_secondary"]],
            on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one",
        )
        contract = {
            "contract_id": "COMMERCIAL_TAXONOMY_EXACT_REMAINING_GAP_R1",
            "status": "REQUIRED",
            "remaining_observation_count": len(remaining_keys),
            "remaining_unique_securities": int(remaining_keys.canonical_security_id.nunique()),
            "min_date": str(remaining_keys.decision_date.min().date()),
            "max_date": str(remaining_keys.decision_date.max().date()),
            "gap_reason_distribution": remaining_keys.gap_reason_primary.value_counts(dropna=False).to_dict(),
            "year_distribution": remaining_keys.decision_date.dt.year.value_counts().sort_index().to_dict(),
            "rank_bucket_distribution": rank_bucket(remaining_keys.a2_rank).value_counts(sort=False).to_dict(),
            "minimum_external_fields_required": ["permanent_security_identifier", "historical_classification", "effective_from", "effective_to", "classification_source", "classification_version"],
            "acquisition_scope": "TARGETED_HISTORICAL_COVERAGE_MAY_SUFFICE_IF_ALL_FROZEN_GATES_CAN_BE_CERTIFIED;FULL_MARKET_PRODUCT_NOT_PRECOMMITTED",
            "purchase_authorized": False,
            "paywall_scraping_authorized": False,
        }
        atomic_json(OUT / "commercial_taxonomy_exact_gap_contract.json", contract)
    elif (OUT / "commercial_taxonomy_exact_gap_contract.json").exists():
        raise TaskError("STALE_COMMERCIAL_CONTRACT_PRESENT_AFTER_GATE_RESOLVED")
    request_count = int(results.get("header_request_count", pd.Series(dtype=int)).sum() + results.get("instance_request_count", pd.Series(dtype=int)).sum())
    summary = {
        **readiness,
        "targeted_securities_attempted": int(results.loc[results.action.ne("NO_REQUEST_FAIL_CLOSED"), "canonical_security_id"].nunique()),
        "targeted_sec_requests": request_count,
        "new_valid_sic_evidence_rows": int(results.status.eq("PASS").sum()),
        "surface_sha256": manifest["surface_sha256"],
        "rv_data_dependency_available": False,
        "moomoo_history_request_count": 0,
    }
    atomic_json(OUT / "recovery_summary.json", summary)
    return summary


def recover(user_agent: str) -> dict[str, Any]:
    input_readback()
    results, evidence = run_targeted_requests(user_agent)
    surface, manifest = extend_surface(evidence)
    summary = analyze_after(surface, manifest, results)
    print(json.dumps({key: summary.get(key) for key in ["targeted_securities_attempted", "targeted_sec_requests", "new_valid_sic_evidence_rows", "additional_strict_ff48_rows", "strict_ff48_mapped_after", "strict_ff48_coverage_after", "counterfactual_identification_ready"]}, indent=2))
    return summary


def repo_pytest_staging() -> list[str]:
    matches: list[str] = []
    for pattern in ("pytest-cache-files-*", "nested-probe-*", "_fix*_validation_tmp"):
        matches.extend(str(path) for path in REPO.glob(pattern) if path.is_dir())
    return sorted(set(matches))


def build_final_validation(registry: Any, root: Path, base_head: str) -> dict[str, Any]:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: Any) -> dict[str, Any]:
        if not condition:
            failures.append(name)
        return {"check": name, "status": "PASS" if condition else "FAIL", "detail": detail}

    surface_path = OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet"
    surface = pd.read_parquet(surface_path)
    base = pd.read_parquet(BASE_SURFACE)
    evidence = pd.read_parquet(OUT / "new_classification_evidence.parquet")
    results = pd.read_csv(OUT / "targeted_sec_recovery_results.csv")
    readiness = json.loads((OUT / "counterfactual_readiness.json").read_text(encoding="utf-8"))
    surface_manifest = json.loads((OUT / "taxonomy_surface_manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads((OUT / "authoritative_baseline_manifest.json").read_text(encoding="utf-8"))
    tests = json.loads((OUT / "test_execution_report.json").read_text(encoding="utf-8"))
    reviewed_sources = json.loads((OUT / "reviewed_source_manifest.json").read_text(encoding="utf-8"))
    semantic_correction = json.loads((OUT / "prepublication_semantic_correction.json").read_text(encoding="utf-8"))
    current = registry.current_state(root)
    changed = base.row_sha256.ne(surface.row_sha256)
    available = pd.to_datetime(surface.sic_available_at, utc=True)
    hash_columns = [column for column in surface.columns if column != "row_sha256"]
    closure = pd.read_csv(OUT / "minimal_structural_gap_closure_set.csv")
    selected_closure = closure.loc[closure.minimum_gate_set_member]
    required_rows = int(np.ceil(0.90 * TOTAL) - BASE_MAPPED)
    missingness = pd.read_csv(OUT / "taxonomy_missingness_bias_report.csv")
    listing_age = missingness.loc[missingness.dimension.eq("LISTING_AGE_BUCKET")]
    base_surface_for_plan, bridge_for_plan, _, sec_sub_for_plan = load_authoritative_inputs()
    rebuilt_plan, _, _ = choose_recovery_plan(base_surface_for_plan, bridge_for_plan, sec_sub_for_plan)
    frozen_plan = pd.read_csv(OUT / "targeted_sec_recovery_plan.csv")
    plan_identity_columns = ["canonical_security_id", "action", "plan_reason", "candidate_ciks", "target_accession"]
    plan_rebuild_matches = (
        rebuilt_plan.plan_row_sha256.astype(str).reset_index(drop=True).equals(frozen_plan.plan_row_sha256.astype(str).reset_index(drop=True))
        and rebuilt_plan[plan_identity_columns].fillna("").astype(str).reset_index(drop=True).equals(frozen_plan[plan_identity_columns].fillna("").astype(str).reset_index(drop=True))
    )
    checks = [
        check("authoritative_input_hash_readback", input_readback()["status"] == "PASS", "all pinned inputs"),
        check("authoritative_denominator_unchanged", len(surface) == TOTAL and len(base) == TOTAL, len(surface)),
        check("canonical_key_unique", not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "unique date/security"),
        check("base_mapped_count", int(base.ff48_code.notna().sum()) == BASE_MAPPED, int(base.ff48_code.notna().sum())),
        check("only_previously_unmapped_rows_changed", bool(base.loc[changed, "ff48_code"].isna().all()), int(changed.sum())),
        check("unchanged_rows_identical", base.loc[~changed].reset_index(drop=True).equals(surface.loc[~changed].reset_index(drop=True)), int((~changed).sum())),
        check("canonical_foundation_row_hash_contract", foundation_row_sha256(surface, hash_columns).equals(surface.row_sha256.astype(str)), len(surface)),
        check("no_future_sic_projection", bool(available.loc[available.notna()].dt.tz_convert(None).le(pd.to_datetime(surface.loc[available.notna(), "decision_date"])).all()), "sic_available_at <= decision_date"),
        check("five_minute_lag_reused", bool((pd.to_datetime(evidence.sic_available_at, utc=True) == pd.to_datetime(evidence.acceptance_datetime, utc=True) + pd.Timedelta(minutes=5)).all()), len(evidence)),
        check("official_ff48_hash_unchanged", sha256_file(FF48_ZIP) == EXPECTED[FF48_ZIP], sha256_file(FF48_ZIP)),
        check("sic3990_not_synthetically_mapped", bool(surface.loc[surface.sic4.eq(3990), "ff48_code"].isna().all()), int(surface.sic4.eq(3990).sum())),
        check("targeted_plan_hash_frozen", sha256_file(OUT / "targeted_sec_recovery_plan.csv") == baseline["targeted_plan_sha256"], baseline["targeted_plan_sha256"]),
        check("targeted_plan_deterministic_typed_rebuild", plan_rebuild_matches, {"rows": len(rebuilt_plan), "csv_note": "direct read_csv loses original dtype/empty-string schema; compare against deterministic typed rebuild"}),
        check("minimum_structural_gate_set_crosses_exact_threshold", int(selected_closure.observations.sum()) >= required_rows and int(selected_closure.iloc[:-1].observations.sum()) < required_rows, {"required": required_rows, "selected": int(selected_closure.observations.sum())}),
        check("listing_age_fail_closed", listing_age.bucket.tolist() == ["UNAVAILABLE_NO_AUTHORITATIVE_LISTING_DATE"], listing_age.to_dict("records")),
        check("prepublication_semantic_correction_provenance", semantic_correction.get("original_frozen_gap_ledger_sha256") == "826b3618125247b0a15c0d21de26e35ae14425e790bf0c7bc319733bfbbecb0a" and Path(semantic_correction["preserved_original_path"]).is_file() and sha256_file(Path(semantic_correction["preserved_original_path"])) == semantic_correction["original_frozen_gap_ledger_sha256"] and sha256_file(OUT / "remaining_ff48_gap_ledger.parquet") == semantic_correction["corrected_gap_ledger_sha256"] == baseline["gap_ledger_sha256"] and semantic_correction.get("targeted_plan_sha256_unchanged") == baseline["targeted_plan_sha256"] and semantic_correction.get("network_requests_for_correction") == 0, semantic_correction),
        check("all_planned_securities_accounted", results.canonical_security_id.nunique() == 84, int(results.canonical_security_id.nunique())),
        check("frozen_gates_all_pass", all(readiness["gates"].values()), readiness["gates"]),
        check("strict_ff48_mapped_readback", int(surface.ff48_code.notna().sum()) == readiness["strict_ff48_mapped_after"], int(surface.ff48_code.notna().sum())),
        check("surface_hash_readback", sha256_file(surface_path) == surface_manifest["surface_sha256"], surface_manifest["surface_sha256"]),
        check("focused_tests_pass", tests.get("status") == "PASS" and tests["focused_test"]["passed"] == 10, tests),
        check("anti_bloat_consistency_pass", tests.get("status") == "PASS" and tests["anti_bloat_consistency"]["passed"] == 3, tests),
        check("reviewed_runner_source_frozen", sha256_file(REPO / "a2_counterfactual_taxonomy_remaining_gap_resolution_r1.py") == reviewed_sources["runner_sha256"], reviewed_sources["runner_sha256"]),
        check("reviewed_test_source_frozen", sha256_file(REPO / "test_a2_counterfactual_taxonomy_remaining_gap_resolution_r1.py") == reviewed_sources["focused_test_sha256"], reviewed_sources["focused_test_sha256"]),
        check("reviewed_surface_frozen", sha256_file(surface_path) == reviewed_sources["surface_sha256"], reviewed_sources["surface_sha256"]),
        check("rv_v1_hash_unchanged", sha256_file(RV_CONTRACT) == EXPECTED[RV_CONTRACT], sha256_file(RV_CONTRACT)),
        check("registry_head_unchanged_before_patch", current.get("head_sha256") == base_head, current.get("head_sha256")),
        check("registry_valid_before_patch", registry.validate_registry(root).get("status") == "PASS", registry.validate_registry(root).get("errors", [])),
        check("repo_pytest_staging_zero", len(repo_pytest_staging()) == 0, repo_pytest_staging()),
        check("zero_moomoo_history", ZERO_COUNTERS["moomoo_history_request_count"] == 0, 0),
        check("zero_post2025_outcome_reads", all(ZERO_COUNTERS[key] == 0 for key in ["post_2025_realized_label_metric_read_count", "post_2025_model_evaluation_metric_read_count", "post_2025_outcome_derived_metadata_read_count", "2026_economic_outcome_read_count", "holdout_peek_count", "mixed_source_content_open_count", "economic_result_read_count"]), ZERO_COUNTERS),
    ]
    validation = {
        "task_id": TASK_ID,
        "status": "PASS" if not failures else "FAIL",
        "created_utc": utc_now(),
        "checks": checks,
        "failures": failures,
        "zero_read_counters": ZERO_COUNTERS,
        "repo_pytest_staging_count": len(repo_pytest_staging()),
        "review_required_before_registry_publish": True,
    }
    atomic_json(OUT / "final_validation.json", validation)
    return validation


def build_registry_patch(registry: Any, root: Path, base_head: str, reviewer: str) -> dict[str, Any]:
    query = registry.query_registry(root, entity_id=TAXONOMY_ENTITY)
    require(query.get("count") == 1, "HARD_BLOCKER_REGISTRY_CORRUPT", TAXONOMY_ENTITY)
    existing = query["entities"][0]
    metadata = dict(existing.get("metadata", {}))
    prior_refs = list(metadata.get("authoritative_artifact_refs", []))
    new_refs = [
        str(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet"),
        str(OUT / "taxonomy_surface_manifest.json"),
        str(OUT / "counterfactual_readiness.json"),
        str(OUT / "final_validation.json"),
        str(OUT / "final_independent_review.md"),
    ]
    metadata.update({
        "authoritative_artifact_refs": list(dict.fromkeys([*prior_refs, *new_refs])),
        "artifact_sha256": sha256_file(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet"),
        "latest_evidence_extension_task": TASK_ID,
        "strict_ff48_mapped": int(pd.read_parquet(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet", columns=["ff48_code"]).ff48_code.notna().sum()),
        "strict_ff48_structural_coverage": json.loads((OUT / "counterfactual_readiness.json").read_text(encoding="utf-8"))["strict_ff48_coverage_after"],
        "counterfactual_identification_ready": True,
        "counterfactual_readiness_status": "READY_WITH_DOCUMENTED_STRUCTURAL_MISSINGNESS",
        "next_legal_action": "RUN_RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1",
        "new_security_master_count": 0,
        "new_taxonomy_framework_count": 0,
        "moomoo_history_request_count": 0,
    })
    limitations = list(existing.get("temporal_evidence_limitations", []))
    limitations = [value for value in limitations if value != "OVERALL_FF48_COVERAGE_BELOW_FROZEN_90_PERCENT_GATE"]
    limitations.extend([
        "AS_FILED_SIC_IS_NOT_GICS",
        "FF48_IS_INDUSTRY_CONTROL",
        "STRICT_PIT_MISSING_ROWS_REMAIN_NO_SYNTHETIC_FILL",
        "MULTI_CIK_AND_UNMAPPED_SIC_CONFLICTS_REMAIN_FAILED_CLOSED",
    ])
    operation = {
        "op": "update_entity",
        "record_type": "OPERATION",
        "change_type": "EVIDENCE_EXTENSION_ONLY",
        "entity": {
            "entity_id": TAXONOMY_ENTITY,
            "metadata": metadata,
            "temporal_evidence_limitations": sorted(set(limitations)),
        },
    }
    operations = [operation]
    patch = {
        "schema_version": 1,
        "patch_purpose": "STANDARD",
        "expected_base_head_sha256": base_head,
        "event_time_utc": utc_now(),
        "author": "CodexPrimary",
        "validation": {"status": "PASS", "scope": TASK_ID, "post_2025_counter_zero": True},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": reviewer},
        "operation_count": len(operations),
        "operations_sha256": registry.sha256_value(operations),
        "operations": operations,
    }
    # Full dry validation without writing a snapshot.
    registry._patch_integrity(patch, audited_bootstrap=False)
    registry._review_gate(patch)
    head, _, entities, aliases = registry._load_live_snapshot(root)
    require(head == base_head, "HARD_BLOCKER_REGISTRY_HEAD_CHANGED", f"{base_head}:{head}")
    registry._apply_operations(entities, aliases, patch, head_sha256=head, audited_inventory_bootstrap=False)
    lines = [{key: value for key, value in patch.items() if key != "operations"}, *operations]
    temporary = OUT / "registry_patch.jsonl.tmp"
    temporary.write_text("".join(json.dumps(line, sort_keys=True, ensure_ascii=False, default=str) + "\n" for line in lines), encoding="utf-8")
    os.replace(temporary, OUT / "registry_patch.jsonl")
    return patch


def build_final_report(summary: Mapping[str, Any], registry_report: Mapping[str, Any]) -> str:
    results = pd.read_csv(OUT / "targeted_sec_recovery_results.csv")
    pass_count = int(results.status.eq("PASS").sum())
    fail_count = int(results.status.eq("FAIL_CLOSED").sum())
    skipped_count = int(results.status.eq("SKIPPED_FAIL_CLOSED").sum())
    return f"""# {TASK_ID}

STATUS=PASS_COUNTERFACTUAL_TAXONOMY_GATE_RESOLVED_WITH_LIMITATIONS

## Decision

The frozen strict-PIT FF48 readiness gate is resolved. Coverage rose from **278,757 / 313,668 (88.870079%)** to **{summary['strict_ff48_mapped_after']:,} / 313,668 ({summary['strict_ff48_coverage_after']:.6%})** without changing the denominator, FF48 ranges, the five-minute SEC availability rule, the Raw A2 universe, or any economic research specification.

All four preregistered gates pass: overall coverage is at least 90%; every natural year is at least 85%; rank >20 coverage is at least 85%; and the rank<=20 versus rank>20 coverage gap is no more than 10 percentage points. `COUNTERFACTUAL_IDENTIFICATION_READY=YES` therefore means only that the frozen data dependency is now legal to consume in a separate economic task.

## What changed

The complete 34,911-row tail ledger and 84-security recovery plan were frozen before retrieval. A single bounded plan then evaluated every unique issuer candidate produced by fixed 13F/SEC spelling normalization; it did not stop after crossing 90%. New issuer links required both a verified historical SEC header (CIK, assigned SIC, accession, form, acceptance time, registrant name) and an exact historical `dei:TradingSymbol` in the same accession's XBRL instance. Existing strict CIK links reused already-validated headers.

Independent review caught one reporting-only semantic defect before publication: the canonical identity bridge's `effective_start` had been mislabeled as a listing date. The original frozen ledger is preserved with SHA-256 `826b3618125247b0a15c0d21de26e35ae14425e790bf0c7bc319733bfbbecb0a`; the corrected ledger preserves that field as `identity_interval_start` and marks `first_known_listing_date` unavailable. The recovery plan SHA, actions, accessions, evidence, surface values, coverage, and network-request count were unchanged.

- Targeted securities attempted: {summary['targeted_securities_attempted']}
- Official SEC files newly downloaded: {summary['targeted_sec_requests']}
- Valid evidence records: {pass_count}
- Failed-closed attempted records: {fail_count}
- Non-requested conflict/unavailable records: {skipped_count}
- Eligible rows newly mapped to official FF48: {summary['additional_strict_ff48_rows']:,}
- Remaining strict-PIT unmapped rows: {summary['remaining_observations']:,} across {summary['remaining_unique_securities']} securities

The zero-network CRM recovery reused a previously verified 2022 10-Q header. Four attempted new links failed exact ticker validation (CCC/CCCS, PHVS/no ticker, MPT/MPW, MRSH/MMC) and were not promoted. Multi-CIK histories, late-only evidence, no-candidate identities, and SIC 3990 remain missing. No current SIC, Moomoo industry, future filing, synthetic FF48, or inner-join row deletion was used.

## Coverage and limitations

- Overall after: {summary['strict_ff48_coverage_after']:.6%}
- Rank <=20 after: {summary['rank_le20_ff48_coverage_after']:.6%}
- Rank >20 after: {summary['rank_gt20_ff48_coverage_after']:.6%}
- Minimum natural-year coverage after: {summary['minimum_year_ff48_coverage_after']:.6%}

The result is intentionally classified **WITH_LIMITATIONS** because 15,731 rows remain structurally missing and missingness is not random. Exact multi-CIK/corporate-action histories and official FF48-unmapped SICs remain failed closed. FF48 is an industry-control taxonomy, not GICS and not an economic sector equivalence claim.

## Separation and safety

No returns, P&L, NAV, Sharpe, alpha, IC, label metric, model-evaluation metric, or 2026 outcome was opened. Moomoo historical request count is zero. Prices, factor/risk, capacity, canonical CUSIP identity, Raw A2, and frozen RV V1 were not rebuilt or modified. Focused tests passed 10/10 and Anti-Bloat consistency passed 3/3 using external RESULTS_ROOT runtime directories; repo-local pytest staging count is zero.

RV V1 remains blocked because its frozen contract requires sector grouping and this task has not established FF48-to-sector equivalence. `RV_DATA_DEPENDENCY_AVAILABLE=FALSE`; `RV_ECONOMICS_RUN=NO`.

## Registry

The task extended the existing `{TAXONOMY_ENTITY}` entity only. No parallel taxonomy or alpha entity was created. Registry base head was `{registry_report['registry_base_head']}` and final head is `{registry_report['registry_final_head']}`. Decision: `{registry_report['registry_decision']}`.

## Next legal action

`RUN_RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1`

That economic task must remain separate. This task ran no counterfactual economics and made no alpha claim.
"""


def build_manifest() -> dict[str, Any]:
    files = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name == "final_manifest.json" or ".tmp" in path.name:
            continue
        relative = path.relative_to(OUT).as_posix()
        files[relative] = {"sha256": sha256_file(path), "byte_size": path.stat().st_size}
    manifest = {
        "task_id": TASK_ID,
        "status": "PASS",
        "terminal_state": "PASS_COUNTERFACTUAL_TAXONOMY_GATE_RESOLVED_WITH_LIMITATIONS",
        "created_utc": utc_now(),
        "file_count": len(files),
        "files": files,
        "authoritative_surface": "updated_pit_sec_sic_ff12_ff48_surface.parquet",
        "authoritative_surface_sha256": sha256_file(OUT / "updated_pit_sec_sic_ff12_ff48_surface.parquet"),
        "base_surface_sha256": EXPECTED[BASE_SURFACE],
        "reviewed_source_manifest_sha256": sha256_file(OUT / "reviewed_source_manifest.json"),
        "reviewed_sources": json.loads((OUT / "reviewed_source_manifest.json").read_text(encoding="utf-8")),
        "zero_read_counters": ZERO_COUNTERS,
    }
    atomic_json(OUT / "final_manifest.json", manifest)
    return manifest


def finalize(reviewer: str, *, publish_registry: bool = False) -> dict[str, Any]:
    registry = registry_module()
    root = registry_root(registry)
    baseline = json.loads((OUT / "authoritative_baseline_manifest.json").read_text(encoding="utf-8"))
    base_head = str(baseline["registry_base_head"])
    current = registry.current_state(root)
    require(current.get("head_sha256") == base_head, "HARD_BLOCKER_REGISTRY_HEAD_CHANGED", f"{base_head}:{current.get('head_sha256')}")
    review_path = OUT / "final_independent_review.md"
    require(review_path.is_file(), "INDEPENDENT_REVIEW_REQUIRED")
    review_text = review_path.read_text(encoding="utf-8")
    require("REVIEW_STATUS=PASS" in review_text, "INDEPENDENT_REVIEW_PASS_REQUIRED")
    validation = build_final_validation(registry, root, base_head)
    require(validation["status"] == "PASS", "FINAL_VALIDATION_FAILED", validation["failures"])
    patch = build_registry_patch(registry, root, base_head, reviewer)
    if publish_registry:
        current_again = registry.current_state(root)
        require(current_again.get("head_sha256") == base_head, "HARD_BLOCKER_REGISTRY_HEAD_CHANGED", f"{base_head}:{current_again.get('head_sha256')}")
        applied = registry.apply_patch(root, patch)
        final_head = str(applied["head_sha256"])
        post_validation = registry.validate_registry(root)
        require(post_validation.get("status") == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT", post_validation)
        registry_decision = "UPDATED_EXISTING_TAXONOMY_ENTITY_EVIDENCE_ONLY"
    else:
        final_head = base_head
        post_validation = registry.validate_registry(root)
        applied = {"status": "NOT_PUBLISHED"}
        registry_decision = "PATCH_VALIDATED_NOT_PUBLISHED"
    registry_report = {
        "task_id": TASK_ID,
        "status": "PASS",
        "registry_base_head": base_head,
        "registry_final_head": final_head,
        "registry_decision": registry_decision,
        "head_changed_before_apply": False,
        "parallel_entity_created": False,
        "updated_entity_id": TAXONOMY_ENTITY,
        "patch_sha256": registry.sha256_value(patch),
        "patch_validation": "PASS",
        "apply_result": applied,
        "post_validation": post_validation,
    }
    atomic_json(OUT / "registry_integration_report.json", registry_report)
    summary = json.loads((OUT / "recovery_summary.json").read_text(encoding="utf-8"))
    report = build_final_report(summary, registry_report)
    (OUT / "final_report.md").write_text(report, encoding="utf-8")
    results = pd.read_csv(OUT / "targeted_sec_recovery_results.csv")
    console = {
        "TASK": TASK_ID,
        "STATUS": "PASS_COUNTERFACTUAL_TAXONOMY_GATE_RESOLVED_WITH_LIMITATIONS",
        "REGISTRY_BASE_HEAD": base_head,
        "REGISTRY_FINAL_HEAD": final_head,
        "TOTAL_ELIGIBLE_OBSERVATIONS": TOTAL,
        "STRICT_FF48_MAPPED_BEFORE": BASE_MAPPED,
        "STRICT_FF48_COVERAGE_BEFORE": BASE_COVERAGE * 100,
        "UNMAPPED_OBSERVATIONS_BEFORE": BASE_UNMAPPED,
        "UNMAPPED_UNIQUE_SECURITIES": 84,
        "TARGETED_SECURITIES_ATTEMPTED": summary["targeted_securities_attempted"],
        "TARGETED_SEC_REQUESTS": summary["targeted_sec_requests"],
        "NEW_VALID_SIC_EVIDENCE_ROWS": int(results.status.eq("PASS").sum()),
        "ADDITIONAL_STRICT_FF48_ROWS": summary["additional_strict_ff48_rows"],
        "STRICT_FF48_MAPPED_AFTER": summary["strict_ff48_mapped_after"],
        "STRICT_FF48_COVERAGE_AFTER": summary["strict_ff48_coverage_after"] * 100,
        "STRICT_FF48_UNMAPPED_AFTER": summary["remaining_observations"],
        "RANK_LE20_FF48_COVERAGE_AFTER": summary["rank_le20_ff48_coverage_after"] * 100,
        "RANK_GT20_FF48_COVERAGE_AFTER": summary["rank_gt20_ff48_coverage_after"] * 100,
        "MIN_YEAR_FF48_COVERAGE_AFTER": summary["minimum_year_ff48_coverage_after"] * 100,
        "OVERALL_90_GATE": "PASS",
        "EACH_YEAR_85_GATE": "PASS",
        "RANK_GT20_85_GATE": "PASS",
        "RANK_COVERAGE_GAP_10PP_GATE": "PASS",
        "COUNTERFACTUAL_IDENTIFICATION_READY": "YES",
        "RV_DATA_DEPENDENCY_AVAILABLE": "FALSE",
        "RV_CONTRACT_MODIFIED": "NO",
        "RV_ECONOMICS_RUN": "NO",
        "MOOMOO_HISTORY_REQUEST_COUNT": 0,
        "COMMERCIAL_DATA_STILL_REQUIRED": "NO_FOR_FROZEN_COUNTERFACTUAL_GATE",
        "COMMERCIAL_REMAINING_OBSERVATIONS": 0,
        "NEW_ALPHA_COMPONENT_COUNT": 0,
        "NEW_MODEL_COUNT": 0,
        "NEW_SECURITY_MASTER_COUNT": 0,
        "NEW_TAXONOMY_FRAMEWORK_COUNT": 0,
        "POST_2025_OUTCOME_READ_COUNT": 0,
        "HOLDOUT_PEEK_COUNT": 0,
        "MIXED_SOURCE_CONTENT_OPEN_COUNT": 0,
        "REPO_PYTEST_STAGING_COUNT": len(repo_pytest_staging()),
        "FINAL_VALIDATION": validation["status"],
        "FINAL_INDEPENDENT_REVIEW": "PASS",
        "NEXT_LEGAL_ACTION": "RUN_RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1",
        "FINAL_REPORT_PATH": str(OUT / "final_report.md"),
        "FINAL_MANIFEST_PATH": str(OUT / "final_manifest.json"),
    }
    atomic_json(OUT / "final_console_summary.json", console)
    manifest = build_manifest()
    print("\n".join(f"{key}={value}" for key, value in console.items()))
    return {"status": "PASS", "console": console, "manifest": manifest}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "recover", "finalize", "all"])
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--reviewer", default="PENDING_INDEPENDENT_REVIEW")
    parser.add_argument("--publish-registry", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command in {"prepare", "all"}:
        prepare()
    if args.command in {"recover", "all"}:
        recover(args.user_agent)
    if args.command in {"finalize", "all"}:
        finalize(args.reviewer, publish_registry=args.publish_registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
