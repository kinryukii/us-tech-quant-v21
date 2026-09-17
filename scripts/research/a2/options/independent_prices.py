"""Bound projection of the existing frozen Raw-Moomoo market surface.

This is an adapter, not a builder: reuse the frozen producer's pure loader
definitions without importing its build-time modules or mixed input readers.
No holdings, ranking or outcome determines the requested market keys.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from .contracts import calendar, require
from .input_adapter import BASELINE, _bytes

SURFACE = "A2_PRE2026_RAW_MOOMOO_REHAB_SURFACE_R1"
MANIFEST = "A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json"
MANIFEST_SHA = "94d3bec3c8fe34075b6dc4a3bc03954015b87c28247d3e49e79b254795c4c7ec"
BUILDER = Path("D:/us-tech-quant-worktrees/a2-raw-a2-true-return-attribution-r1-20260827-013537/scripts/v22/a2_pre2026_raw_moomoo_rehab_builder_r2.py")
BUILDER_SHA = "f0b1111051ff6dd986241ec43aea9469f9906747d67dae2f31ade9a0af1d3d8c"
MEMBERSHIP_SHA = "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637"
REBUILD_SHA = "68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e"
KEY = ["underlying_uid", "ticker", "session", "field"]
KNOWN = {"VERIFIED_DATED_HISTORICAL_MAPPING"}


def _validated_keys(keys: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    require(set(KEY).issubset(keys.columns), "INDEPENDENT_PRICE_KEY_SCHEMA")
    result = keys[KEY].copy()
    result["session"] = pd.to_datetime(result.session)
    require(result.session.notna().all() and result.session.lt("2026-01-01").all(),
            "INDEPENDENT_PRICE_NON_PRE2026_KEY")
    require(result.session.eq(result.session.dt.normalize()).all(), "INDEPENDENT_PRICE_NON_SESSION_DATE")
    require(result.session.isin(calendar().sessions).all(), "INDEPENDENT_PRICE_NON_TRADING_SESSION")
    require(result.field.eq("open").all(), "INDEPENDENT_PRICE_UNBOUND_FIELD")
    allowed = panel[["underlying_uid", "ticker"]].drop_duplicates()
    checked = result.merge(allowed, on=["underlying_uid", "ticker"], how="left", indicator=True)
    require(checked._merge.eq("both").all(), "INDEPENDENT_PRICE_UNBOUND_OPPORTUNITY")
    return result.drop_duplicates().sort_values(KEY, kind="stable").reset_index(drop=True)


def _pure_loader(source: bytes, manifest_path: Path) -> dict:
    """Reuse exact hash-pinned, reviewed pure definitions; execute no imports/build.

    The producer's ordinary import loads corporate-action research modules.
    This finite extraction keeps its one market loader and validation logic,
    and avoids those unrelated top-level imports. It never reads mixed inputs.
    """
    functions = {"require", "sha256_file", "canonical_json_hash", "content_hash",
                 "normalize_adjusted_frame", "validate_surface_frame",
                 "verify_manifest_contract", "load_frozen_surface"}
    constants = {"SURFACE_NAME", "END_EXCLUSIVE", "MAX_OUTPUT_DATE", "OUTPUT_COLUMNS",
                 "STRING_COLUMNS", "FLOAT_COLUMNS"}
    tree = ast.parse(source.decode("utf-8"))
    selected = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in constants:
                selected.append(node)
                found.add(node.targets[0].id)
    require(found == functions | constants, "FROZEN_LOADER_DEFINITION_SET")
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    scope = {"pd": pd, "np": np, "hashlib": hashlib, "json": json, "Path": Path, "MANIFEST_PATH": manifest_path}
    exec(compile(module, str(BUILDER) + ":pure-loader", "exec"), scope)
    return scope


def project_prices(keys: pd.DataFrame, panel: pd.DataFrame, surface: pd.DataFrame,
                   membership: pd.DataFrame) -> pd.DataFrame:
    """Project independently observed opens with separate identity/action status.

    Static transport routing does not certify historical identity intervals.
    Every ticker needs dated frozen UID evidence for economic qualification;
    an absent mapping stays UNKNOWN even when the market price is available.
    """
    wanted = _validated_keys(keys, panel)
    require(not surface.duplicated(["ticker", "trade_date"]).any(), "DUPLICATE_INDEPENDENT_PRICE")
    require(pd.to_datetime(surface.trade_date).lt("2026-01-01").all(), "SURFACE_NON_PRE2026")
    require(surface.source.eq("MOOMOO_OPEND_RAW_PLUS_REHAB").all(), "SURFACE_SOURCE_LEVEL")
    require(surface.autype.eq("PIT_FORWARD_REHAB_INDEX").all(), "SURFACE_ADJUSTMENT_LEVEL")
    members = membership[["signal_date", "ticker", "cusip", "moomoo_transport_code"]].copy()
    members["signal_date"] = pd.to_datetime(members.signal_date)
    require(members.signal_date.lt("2026-01-01").all(), "MAPPING_NON_PRE2026")
    require(not members.duplicated(["signal_date", "ticker"]).any(), "AMBIGUOUS_DATED_TRANSPORT")
    mapping = members[["ticker", "cusip", "moomoo_transport_code"]].drop_duplicates()
    transport_count = mapping.groupby("ticker").moomoo_transport_code.nunique()
    require(transport_count.le(1).all(), "AMBIGUOUS_FROZEN_TRANSPORT")
    require(mapping.groupby("cusip").ticker.nunique().le(1).all(), "AMBIGUOUS_FROZEN_UID")
    dated = members.set_index(["signal_date", "ticker"])
    idx = pd.MultiIndex.from_arrays([wanted.session, wanted.ticker])
    direct = dated.reindex(idx)
    direct.index = wanted.index
    mapped_code = wanted.ticker.map(mapping.drop_duplicates("ticker").set_index("ticker").moomoo_transport_code)
    wanted["identity_status"] = "UNKNOWN_HISTORICAL_IDENTITY"
    dated_ok = direct.cusip.eq(wanted.underlying_uid)
    wanted.loc[dated_ok, "identity_status"] = "VERIFIED_DATED_HISTORICAL_MAPPING"
    changed = direct.cusip.notna() & ~direct.cusip.eq(wanted.underlying_uid)
    wanted.loc[changed, "identity_status"] = "CHANGED_HISTORICAL_UID"
    wanted["identity_valid"] = wanted.identity_status.isin(KNOWN)
    wanted["moomoo_transport_code"] = mapped_code
    wanted["transport_identity_status"] = "BOUND_STATIC_ROUTE_NOT_TEMPORAL_UID_CERTIFICATION"
    wanted.loc[mapped_code.isna(), "transport_identity_status"] = "UNKNOWN_TRANSPORT_ROUTE"
    prices = surface.rename(columns={"trade_date": "session", "open": "price"})
    wanted = wanted.merge(prices[["ticker", "session", "moomoo_transport_code", "price"]],
                          on=["ticker", "session", "moomoo_transport_code"], how="left", validate="many_to_one")
    wanted["price_valid"] = np.isfinite(wanted.price) & wanted.price.gt(0)
    wanted["valid"] = wanted.price_valid  # Price validity only; never merges identity/lifecycle.
    wanted["action_status"] = "VERIFIED_INHERITED_FROZEN_FORWARD_REHAB"
    wanted["action_valid"] = wanted.moomoo_transport_code.notna()
    wanted["lifecycle_status"] = "RESOLVED_CONTINUOUS_BOUND_TRANSPORT_MARK"
    wanted.loc[~wanted.price_valid, "lifecycle_status"] = "UNKNOWN_MISSING_MARK_NOT_TERMINAL_EVIDENCE"
    wanted.loc[~wanted.identity_valid, "lifecycle_status"] = "UNKNOWN_HISTORICAL_IDENTITY"
    # A price index is not a settlement/rights ledger. The producer documents
    # this bankruptcy replacement; do not claim its same-ticker index resolves
    # an original ordinary-share lifecycle or its additional rights.
    wolf = wanted.ticker.eq("WOLF") & wanted.session.ge("2025-09-29")
    wanted.loc[wolf, "lifecycle_status"] = "UNKNOWN_COMPLEX_REORGANIZATION_RIGHTS"
    wanted["lifecycle_valid"] = wanted.lifecycle_status.eq("RESOLVED_CONTINUOUS_BOUND_TRANSPORT_MARK")
    wanted["source"] = SURFACE
    wanted["price_kind"] = "PIT_FORWARD_REHAB_OPEN_INDEX_NOT_BBO_FILL"
    wanted["currency"] = "USD"
    wanted["return_semantics"] = "INHERITED_ADJUSTED_PRICE_INDEX_RETURN_NOT_CERTIFIED_TOTAL_RETURN"
    return wanted.sort_values(KEY, kind="stable").reset_index(drop=True)


def load_independent_prices(expected_keys: pd.DataFrame, panel: pd.DataFrame,
                            output: Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Load only the bound physical pre-2026 frozen surface; no raw fallback."""
    keys = _validated_keys(expected_keys, panel)  # Reject before any source open.
    paths = resolve()
    manifest_path = paths.results_root / MANIFEST
    reads = []
    manifest = json.loads(_bytes(manifest_path, MANIFEST_SHA, reads))
    source = _bytes(BUILDER, BUILDER_SHA, reads)
    loader = _pure_loader(source, manifest_path)
    loader["verify_manifest_contract"](manifest)
    require(Path(manifest["surface_path"]).resolve() == (paths.data_root / "canonical/v22" / SURFACE).resolve(),
            "SURFACE_ROOT_BINDING")
    require(manifest["rehab_implementation"]["sha256"] == REBUILD_SHA, "ADJUSTMENT_PRODUCER_BINDING")
    require(manifest["authoritative_universe"]["sha256"] == MEMBERSHIP_SHA, "SURFACE_MAPPING_BINDING")
    membership_path = paths.results_root / BASELINE / "universe/daily_eligible_universe_membership.parquet"
    members = pd.read_parquet(io.BytesIO(_bytes(membership_path, MEMBERSHIP_SHA, reads)),
                              columns=["signal_date", "ticker", "cusip", "moomoo_transport_code"])
    mapping = members[["ticker", "moomoo_transport_code"]].drop_duplicates()
    require(mapping.groupby("ticker").moomoo_transport_code.nunique().le(1).all(), "SURFACE_TRANSPORT_CONFLICT")
    codes = sorted(set(mapping.loc[mapping.ticker.isin(keys.ticker), "moomoo_transport_code"]))
    require(bool(codes), "NO_BOUND_INDEPENDENT_TRANSPORT_CODES")
    # The reviewed pinned manifest establishes physical pre-2026 admission,
    # before the reused loader hashes/opens any price partition.
    for part in manifest["partitions"]:
        p = (Path(manifest["surface_path"]) / part["relative_path"]).resolve()
        require(Path(manifest["surface_path"]).resolve() in p.parents, "PARTITION_PATH_BOUNDARY")
        require(part["max_date"] < "2026-01-01", "PARTITION_DATE_BOUNDARY")
    surface = loader["load_frozen_surface"](codes=codes, manifest_path=manifest_path)
    marks = project_prices(keys, panel, surface, members)
    evidence = {
        "status": "BOUND_FROZEN_INDEPENDENT_MARKET_SURFACE_CONSUMED",
        "source": SURFACE, "source_role": "CANONICAL_SAME_PRODUCER_PRICE_INDEX",
        "manifest_sha256": MANIFEST_SHA, "builder_sha256": BUILDER_SHA,
        "read_boundary": "EXISTING_IMMUTABLE_PHYSICAL_PRE2026_PARTITIONS_NO_MIXED_FALLBACK",
        "loader_reuse": "Hash-pinned producer pure loader definitions; build imports not executed",
        "bound_source_reads": reads,
        "surface_partition_reads": [{"path": str(Path(manifest["surface_path"]) / p["relative_path"]),
                                      "sha256": p["sha256"], "bytes": p["bytes"],
                                      "price_payload_read": bool(set(p["codes"]) & set(codes))}
                                     for p in manifest["partitions"]],
        "requested_keys": len(keys), "unique_uids": int(keys.underlying_uid.nunique()),
        "unique_tickers": int(keys.ticker.nunique()), "transport_codes": len(codes),
        "surface_rows_loaded": len(surface), "valid_prices": int(marks.price_valid.sum()),
        "identity_status_counts": marks.identity_status.value_counts().to_dict(),
        "lifecycle_status_counts": marks.lifecycle_status.value_counts().to_dict(),
        "dates": {"min": str(surface.trade_date.min().date()), "max": str(surface.trade_date.max().date())},
        "price_kind": "PIT_FORWARD_REHAB_OPEN_INDEX_NOT_BBO_FILL",
        "corporate_actions": manifest["rehab_implementation"],
        "identity_scope": "Every price-key date requires original frozen dated CUSIP identity; static transport mapping is routing only, never temporal UID certification; no active325 intersection",
        "holding_dependence": "NONE; no holdings input; original ledger producer emits only union of shares_before/shares_after/transaction_cost tickers",
        "limitations": ["Static transport uniqueness does not establish historical UID validity intervals; missing dated identity remains UNKNOWN",
                        "Vendor forward-rehab index retains original treatment; no extra dividends added",
                        "No certified total return, intraday extrema, 09:45 quote or execution claim",
                        "Missing marks do not distinguish halt/delisting/no-record; no final-price substitution",
                        "Complex reorganization rights are not resolved by price-index adjustment alone"],
        "raw_or_rehab_container_reads": 0, "network_requests": 0,
    }
    if output is not None:
        output = Path(output).resolve()
        allowed = paths.results_root / "OPTIONS_EXPRESSION_PILOT_R1/overnight"
        require(allowed.resolve() in output.parents, "PRICE_EVIDENCE_OUTPUT_BOUNDARY")
        output.mkdir(parents=True, exist_ok=True)
        (output / "price_source_evidence.json").write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    return marks, evidence
