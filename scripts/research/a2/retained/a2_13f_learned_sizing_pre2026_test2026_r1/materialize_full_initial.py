"""Materialize full as-filed initial 13F rows from the existing local SEC cache.

This is an initial-filing data asset, not a PIT-complete version resolver. The
amendment audit remains a separate acceptance gate.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
PACKAGE = Path("D:/us-tech-quant-results/13f_pit_v1")
CACHE = Path("D:/us-tech-quant-cache/13f_pit_v1")
SOURCE = PACKAGE / "scripts/v17b/integrity_rebuild_v17b.py"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    spec = importlib.util.spec_from_file_location("frozen_v17b_full_initial", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    filing_map = module.load_authoritative_filing_map(PACKAGE)
    raw = module.load_and_classify_source(PACKAGE, CACHE, filing_map)
    raw = raw.loc[raw.manager_id.ne("situational_awareness")].copy()
    meta = pd.read_csv(PACKAGE / "data/filings/filing_metadata.csv", dtype=str).fillna("")
    meta = meta.loc[meta.manager_id.ne("situational_awareness")].copy()
    meta["accession_key"] = meta.accession_number.str.replace("-", "", regex=False)
    meta["filing_date"] = pd.to_datetime(meta.filing_date, format="%Y-%m-%d")
    assert len(meta) == 600 and meta.accession_key.nunique() == 600
    raw = raw.merge(meta[["accession_key", "cik", "filing_date", "status"]], on="accession_key", how="left", validate="many_to_one")
    assert raw.filing_date.notna().all() and raw.status.eq("VERIFIED").all()
    raw["source_to_usd_factor"] = np.where(raw.filing_date.ge(pd.Timestamp("2023-01-03")), 1.0, 1000.0)
    raw["value_usd"] = raw.reported_value_raw * raw.source_to_usd_factor
    assert raw.reported_value_raw.notna().all() and raw.value_usd.ge(0).all()
    assert raw.groupby(["quarter", "manager_id"]).accession_key.nunique().eq(1).all()
    assert raw.groupby("quarter").manager_id.nunique().eq(24).all()
    assert raw.quarter.max() == "2026Q1"
    raw["public_date_granularity"] = "SEC_FILING_DATE_DAILY"
    raw["version_type"] = "INITIAL_SELECTED_BY_FROZEN_24_MANAGER_SOURCE"
    raw["source_info_table"] = "D:/us-tech-quant-cache/13f_pit_v1/sec_bulk_reduced"
    raw["full_report_amount_status"] = "INITIAL_ONLY_AMENDMENT_REVIEW_PENDING"
    for column in ("OTHERMANAGER", "INVESTMENTDISCRETION", "INFOTABLE_SK"):
        if column not in raw:
            raw[column] = None
    expected = ["quarter", "manager_id", "manager_name", "cik", "accession_key", "filing_date",
                "cusip", "issuer_name", "title_of_class", "ssh_prnamt_type", "put_call",
                "reported_value_raw", "source_to_usd_factor", "value_usd", "eligible", "eligibility_reason",
                "OTHERMANAGER", "INVESTMENTDISCRETION", "INFOTABLE_SK",
                "public_date_granularity", "version_type", "source_info_table", "full_report_amount_status"]
    full = raw[expected].copy()
    full.to_parquet(OUT / "FULL_INITIAL_INFOTABLE.parquet", index=False, compression="zstd")
    full.loc[full.quarter.between("2022Q3", "2025Q3")].to_parquet(OUT / "PRE2026_FULL_INITIAL_INFOTABLE.parquet", index=False, compression="zstd")
    eligible = full.loc[full.eligible].copy()
    h = eligible.groupby(["quarter", "manager_id", "accession_key", "filing_date"], as_index=False).agg(
        full_eligible_equity_value_usd=("value_usd", "sum"),
        eligible_row_count=("value_usd", "size"),
        eligible_cusip_count=("cusip", "nunique"))
    assert len(h) == 600 and h.full_eligible_equity_value_usd.gt(0).all()
    h.to_csv(OUT / "FULL_INITIAL_H.csv", index=False)
    audit = {
        "status": "INITIAL_FULL_ROWS_MATERIALIZED_AMENDMENT_REVIEW_PENDING",
        "source_v17b_path": str(SOURCE), "source_v17b_sha256": sha(SOURCE),
        "filing_metadata_sha256": sha(PACKAGE / "data/filings/filing_metadata.csv"),
        "initial_filing_count": len(h), "manager_count": int(h.manager_id.nunique()),
        "report_quarter_count": int(h.quarter.nunique()),
        "full_initial_row_count": len(full), "eligible_equity_row_count": len(eligible),
        "option_row_count": int(full.put_call.fillna("").ne("").sum()),
        "non_equity_or_unqualified_row_count": int((~full.eligible).sum()),
        "other_manager_nonempty_row_count": int(full.OTHERMANAGER.fillna("").astype(str).str.strip().ne("").sum()),
        "same_filing_cusip_multirow_group_count": int((full.loc[full.eligible].groupby(["accession_key", "cusip"]).size() > 1).sum()),
        "unit_factor_counts": {str(k): int(v) for k, v in full.source_to_usd_factor.value_counts().items()},
        "unknown_initial_h_count": int(h.full_eligible_equity_value_usd.isna().sum()),
        "max_report_quarter": str(h.quarter.max()),
        "limits": ["Amendment type and subsequent effective version remain unresolved", "Public time is SEC filing date granularity; exact accepted timestamp not present in this local reduced cache", "2026Q2 not in local source"],
        "output_sha256": {"FULL_INITIAL_INFOTABLE.parquet": sha(OUT / "FULL_INITIAL_INFOTABLE.parquet"),
                          "PRE2026_FULL_INITIAL_INFOTABLE.parquet": sha(OUT / "PRE2026_FULL_INITIAL_INFOTABLE.parquet"),
                          "FULL_INITIAL_H.csv": sha(OUT / "FULL_INITIAL_H.csv")}
    }
    (OUT / "FULL_INITIAL_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: audit[k] for k in ("status", "initial_filing_count", "full_initial_row_count", "eligible_equity_row_count", "unit_factor_counts")}, indent=2))


if __name__ == "__main__":
    main()
