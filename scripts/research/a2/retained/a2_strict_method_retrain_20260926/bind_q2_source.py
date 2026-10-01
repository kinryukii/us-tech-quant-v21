"""Verify Q2 original-24 source identity without changing the frozen pool."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage" / "fixed_window_binding"
OTHER = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
ORIGINAL = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
PERSHING_TXT = Path(r"D:\us-tech-quant-cache\13f_intake\13f_personal_contact_20260914\0001172661-26-003790.txt")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_map = pd.read_csv(OTHER / "Q2_ORIGINAL24_SOURCE_MAP.csv", dtype=str).fillna("")
    original = pd.read_csv(ORIGINAL / "audit/authoritative_24_manager_manifest.csv", dtype=str).fillna("")
    left = source_map.set_index("original_manager_id").original_cik.str.zfill(10).to_dict()
    right = original.set_index("normalized_manager_id").cik.str.zfill(10).to_dict()
    assert left == right and len(left) == 24
    initial = source_map.loc[~source_map.source_scope.str.contains("RESTAT", case=False)]
    assert len(initial) == 24
    pershing = source_map.loc[source_map.original_manager_id.eq("pershing_square")]
    assert len(pershing) == 1
    p = pershing.iloc[0]
    assert p.original_cik.zfill(10) == "0001336528" and p.source_cik.zfill(10) == "0002026053"
    assert p.accession == "0001172661-26-003790" and p.source_scope == "OTHER_MANAGER_1_14_OF_15_ROWS"
    rows = pd.read_parquet(OTHER / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet",
                           columns=["original_manager_id", "accession", "other_manager", "cusip"])
    attributed = rows.loc[rows.original_manager_id.eq("pershing_square")]
    assert len(attributed) == 14 and set(attributed.accession) == {p.accession}
    assert attributed.other_manager.astype(str).str.split(",").map(lambda v: "1" in [s.strip() for s in v]).all()
    assert sha(PERSHING_TXT) == "ce5e27e43bc76d8fea60fc5e2b146c017172653649e8433f0b3191dabfa5b310"
    q2 = pd.read_parquet(OTHER / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
    identity_path = Path(r"D:\us-tech-quant-results\13f_pit_v1\data\universe\security_identity_v17c_transport.parquet")
    identity = pd.read_parquet(identity_path, columns=["cusip", "title_of_class", "ticker", "moomoo_transport_code"])
    joined = q2.merge(identity, on="cusip", how="left", validate="one_to_one", suffixes=("_q2", "_index"))
    assert len(joined) == 575 and joined.ticker_index.notna().all()
    assert joined.ticker_q2.eq(joined.ticker_index).all()
    assert joined.moomoo_transport_code_q2.eq(joined.moomoo_transport_code_index).all()
    title_differences = joined.loc[joined.title_of_class_q2.astype(str).ne(joined.title_of_class_index.astype(str)),
        ["cusip", "ticker_q2", "moomoo_transport_code_q2", "title_of_class_q2", "title_of_class_index"]]
    title_differences.to_csv(OUT / "Q2_SHARE_CLASS_TEXT_DIFFERENCES.csv", index=False)
    audit = json.loads((OTHER / "Q2_INTAKE_AUDIT.json").read_text(encoding="utf-8"))
    integrity = json.loads((OTHER / "Q2_SOURCE_INTEGRITY.json").read_text(encoding="utf-8"))
    assert audit["original_managers"] == 24 and audit["pershing_other_manager_1_rows"] == 14
    assert integrity["initial_count"] == 24 and integrity["citadel_restatement_count"] == 1
    intake_root = Path(r"D:\us-tech-quant-data\13f\13f_personal_contact_20260914")
    for name, expected in audit["input_sha256"].items():
        assert sha(intake_root / name) == expected
    receipt = {
        "status": "SOURCE_IDENTITY_BOUND_INPUT_ONLY_NOT_FORMAL_POOL_APPROVAL",
        "original_24_id_and_cik_mapping_exact": True,
        "pershing_original_cik": "0001336528", "pershing_13f_nt_accession": "0001172661-26-003777",
        "pershing_other_manager_filer_cik": "0002026053",
        "pershing_other_manager_filing_accession": p.accession,
        "pershing_attributed_rows": 14, "pershing_filer_detail_rows": 15,
        "pershing_excluded_other_manager_rows": 1,
        "pershing_source_txt_sha256": sha(PERSHING_TXT),
        "initial_effective_date": audit["initial_effective_date"],
        "citadel_restatement_effective_date": audit["citadel_restatement_effective_date"],
        "q2_initial_mapped_candidate_count": audit["initial_mapped_candidate_count"],
        "q2_cusip_ticker_transport_exact_identity_match_count": 575,
        "q2_share_class_text_difference_count": len(title_differences),
        "q2_share_class_text_differences_sha256": sha(OUT / "Q2_SHARE_CLASS_TEXT_DIFFERENCES.csv"),
        "security_identity_v17c_sha256": sha(identity_path),
        "source_summary_mismatch_accessions_preserved": integrity["summary_mismatch_accessions"],
        "original_manager_manifest_sha256": sha(ORIGINAL / "audit/authoritative_24_manager_manifest.csv"),
        "q2_source_map_sha256": sha(OTHER / "Q2_ORIGINAL24_SOURCE_MAP.csv"),
        "q2_versioned_rows_sha256": sha(OTHER / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet"),
        "q2_intake_audit_sha256": sha(OTHER / "Q2_INTAKE_AUDIT.json"),
        "raw_intake_filings_sha256": audit["input_sha256"]["raw_filings.parquet"],
        "raw_intake_holdings_sha256": audit["input_sha256"]["raw_holdings.parquet"],
        "q2_source_integrity_sha256": sha(OTHER / "Q2_SOURCE_INTEGRITY.json"),
        "not_certified_by_this_receipt": ["UID", "121_session_prewarm", "32_features", "price_adjustment_PIT", "execution_open", "held_price_valuation"],
        "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
    }
    (OUT / "Q2_SOURCE_BINDING.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "original_managers": len(left), "pershing_rows": len(attributed)}))


if __name__ == "__main__":
    main()
