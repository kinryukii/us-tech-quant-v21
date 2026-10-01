"""Read-only local coverage inventory; never opens price or policy outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

OUT = Path(__file__).resolve().parent
PACKAGE = Path("D:/us-tech-quant-results/13f_pit_v1")
REDUCED = Path("D:/us-tech-quant-cache/13f_pit_v1/sec_bulk_reduced")


def main() -> None:
    original = pd.read_csv(PACKAGE / "data/filings/filing_metadata.csv", dtype=str).fillna("")
    original = original.loc[original.manager_id.ne("situational_awareness")].copy()
    assert original.groupby("quarter").manager_id.nunique().eq(24).all()
    original["accession_key"] = original.accession_number.str.replace("-", "", regex=False)
    original["cik_norm"] = original.cik.str.lstrip("0")
    original["filing_date"] = pd.to_datetime(original.filing_date)
    submissions = []
    file_rows = []
    for path in sorted(REDUCED.glob("*_submission.parquet")):
        info = path.with_name(path.name.replace("_submission.parquet", "_infotable.parquet"))
        if not info.is_file():
            continue
        part = pd.read_parquet(path)
        part["source_package"] = path.stem.removesuffix("_submission")
        submissions.append(part)
        file_rows.append({"source_package": path.stem.removesuffix("_submission"), "submission_rows": len(part),
                          "infotable_rows": pq.ParquetFile(info).metadata.num_rows,
                          "submission_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "infotable_sha256": hashlib.sha256(info.read_bytes()).hexdigest()})
    all_sub = pd.concat(submissions, ignore_index=True)
    all_sub["accession_key"] = all_sub.ACCESSION_NUMBER.astype(str).str.replace("-", "", regex=False)
    all_sub["cik_norm"] = all_sub.CIK.astype(str).str.lstrip("0")
    all_sub["filing_date"] = pd.to_datetime(all_sub.FILING_DATE, format="%d-%b-%Y")
    all_sub["report_date"] = pd.to_datetime(all_sub.PERIODOFREPORT, format="%d-%b-%Y")
    sec_rows = []
    for path in sorted((PACKAGE.parent.parent / "us-tech-quant-cache" / "13f_pit_v1" / "sec").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not all(k in payload for k in ("accessionNumber", "acceptanceDateTime", "form")):
            continue
        for accession, accepted, form in zip(payload["accessionNumber"], payload["acceptanceDateTime"], payload["form"]):
            sec_rows.append({"accession_key": str(accession).replace("-", ""), "accepted_at_utc": accepted, "cached_form": form})
    # The SEC submissions JSON cache may contain repeated copies; identical accession metadata must agree.
    sec_meta = pd.DataFrame(sec_rows).drop_duplicates()
    assert not sec_meta.accession_key.duplicated().any()
    all_sub = all_sub.merge(sec_meta, on="accession_key", how="left", validate="many_to_one")
    relevant = all_sub.loc[all_sub.cik_norm.isin(set(original.cik_norm)) &
                           all_sub.report_date.ge(pd.Timestamp("2022-06-30"))].copy()
    relevant["report_quarter"] = relevant.report_date.dt.to_period("Q").astype(str)
    relevant.sort_values(["report_date", "cik_norm", "filing_date", "ACCESSION_NUMBER"]).to_csv(OUT / "LOCAL_RELEVANT_SUBMISSIONS.csv", index=False)
    amendments = relevant.loc[relevant.SUBMISSIONTYPE.astype(str).str.contains("/A", regex=False)].copy()
    amendments.to_csv(OUT / "AMENDMENT_CANDIDATES.csv", index=False)
    mapped = original.merge(all_sub[["accession_key", "source_package", "SUBMISSIONTYPE", "report_date", "filing_date"]],
                            on="accession_key", how="left", suffixes=("_old", "_source"), validate="many_to_one")
    mapped["submission_found"] = mapped.source_package.notna()
    mapped["report_period_matches"] = mapped.report_date.eq(pd.PeriodIndex(mapped.quarter, freq="Q").to_timestamp(how="end").normalize())
    mapped.to_csv(OUT / "LOCAL_FILING_COVERAGE.csv", index=False)
    pd.DataFrame(file_rows).to_csv(OUT / "LOCAL_SOURCE_FILE_HASHES.csv", index=False)
    summary = {
        "original_manager_count": int(original.manager_id.nunique()),
        "original_manager_quarters": len(original),
        "original_selected_accessions_found_in_full_local_source": int(mapped.submission_found.sum()),
        "original_report_period_mismatches": int((~mapped.report_period_matches).sum()),
        "relevant_full_source_submission_rows": len(relevant),
        "relevant_amendment_candidate_count": len(amendments),
        "selected_original_accepted_at_known": int(mapped.accession_key.isin(set(sec_meta.accession_key)).sum()),
        "relevant_amendment_accepted_at_known": int(amendments.accepted_at_utc.notna().sum()),
        "relevant_amendment_report_periods": sorted(amendments.report_quarter.unique().tolist()),
        "local_source_package_count": len(file_rows),
        "latest_local_source_package": file_rows[-1]["source_package"],
        "source_scope": "Local reduced full information tables for original selected accessions, not mere Top100 holdings; amendment semantics require cover-page evidence if relevant. No 2026 policy outcomes opened."
    }
    (OUT / "LOCAL_COVERAGE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
