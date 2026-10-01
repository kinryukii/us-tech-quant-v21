"""Original-24 2026Q2 initial candidate pool and versioned full V/H sources.

Reads the September official intake and frozen v17b rules; never changes D or training.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = Path(r"D:\us-tech-quant-results\13f_pit_v1")
R1 = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
INTAKE = Path(r"D:\us-tech-quant-data\13f\13f_personal_contact_20260914")
SOURCE = ROOT / "scripts/v17b/integrity_rebuild_v17b.py"
OLD_CIK = "1336528"
NEW_CIK = "2026053"
PERSHING_ACCESSION = "0001172661-26-003790"
CITADEL_RESTATEMENT = "0001104659-26-104387"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    spec = importlib.util.spec_from_file_location("frozen_v17b_q2", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    registry = pd.read_csv(R1 / "audit/authoritative_24_manager_manifest.csv", dtype={"cik": str})
    registry["cik_norm"] = registry.cik.str.lstrip("0")
    assert len(registry) == 24 and registry.cik_norm.nunique() == 24
    by_cik = registry.set_index("cik_norm")["normalized_manager_id"].to_dict()
    filing = pd.read_parquet(INTAKE / "raw_filings.parquet")
    detail = pd.read_parquet(INTAKE / "raw_holdings.parquet")
    filing["cik_norm"] = filing.cik.astype(str).str.lstrip("0")
    detail["cik_norm"] = detail.cik.astype(str).str.lstrip("0")
    assert len(filing) == 26 and len(detail) == 49631
    direct = filing.loc[filing.cik_norm.isin(by_cik) & ~filing.is_amendment].copy()
    assert len(direct) == 23 and set(by_cik)-set(direct.cik_norm) == {OLD_CIK}
    direct["original_manager_id"] = direct.cik_norm.map(by_cik)
    alias_filing = filing.loc[filing.accession.eq(PERSHING_ACCESSION)]
    assert len(alias_filing) == 1 and str(alias_filing.cik_norm.iloc[0]) == NEW_CIK
    assert alias_filing.form.iloc[0] == "13F-HR"
    original = pd.read_csv(HERE / "Q2_FILINGS_METADATA_ONLY.csv", dtype=str)
    nt = original.loc[original.cik.eq(OLD_CIK)]
    assert len(nt) == 1 and nt.form.iloc[0] == "13F-NT"
    alias_text_path = Path(str(alias_filing.raw_path.iloc[0]))
    assert sha(alias_text_path) == alias_filing.source_sha256.iloc[0]
    alias_text = alias_text_path.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"<sequenceNumber>1</sequenceNumber>\s*<otherManager>\s*<cik>0001336528</cik>", alias_text)
    assert "Pershing Square Capital Management, L.P." in alias_text
    first = detail.loc[detail.accession.eq(PERSHING_ACCESSION)].copy()
    token1 = first.other_manager.fillna("").astype(str).str.split(",").map(lambda parts: "1" in [p.strip() for p in parts])
    assert len(first) == 15 and int(token1.sum()) == 14
    initial_accessions = set(direct.accession) | {PERSHING_ACCESSION}
    versioned = detail.loc[detail.accession.isin(initial_accessions | {CITADEL_RESTATEMENT})].copy()
    versioned["original_manager_id"] = versioned.cik_norm.map(by_cik)
    versioned.loc[versioned.accession.eq(PERSHING_ACCESSION), "original_manager_id"] = "pershing_square"
    versioned["original_manager_scope"] = np.where(versioned.accession.eq(PERSHING_ACCESSION),
                                                        "OTHER_MANAGER_1_ONLY", "DIRECT_ORIGINAL_CIK")
    versioned = versioned.loc[~versioned.accession.eq(PERSHING_ACCESSION) |
                              versioned.other_manager.fillna("").astype(str).str.split(",").map(
                                  lambda parts: "1" in [p.strip() for p in parts])].copy()
    assert versioned.original_manager_id.nunique() == 24
    assert not versioned.original_manager_id.eq("situational_awareness").any()
    assert versioned.loc[versioned.accession.eq(PERSHING_ACCESSION)].shape[0] == 14
    # The original v17b rule classifies all rows before Top100 selection and full-H aggregation.
    classified = [mod.classify_equity(row.issuer_name, row.title_of_class,
                                      str(row.share_type or "").upper(), str(row.put_call or "").upper())
                  for row in versioned.itertuples(index=False)]
    versioned["eligible"] = [x[0] for x in classified]
    versioned["eligibility_reason"] = [x[1] for x in classified]
    assert versioned.value_usd.notna().all() and versioned.value_usd.ge(0).all()
    versioned["reported_value_usd"] = versioned.value_usd
    versioned["accession_key"] = versioned.accession.str.replace("-", "", regex=False)
    versioned["manager_id"] = versioned.original_manager_id
    weights = pd.read_csv(ROOT / "data/filings/filing_metadata.csv")
    manager_weight = weights.groupby("manager_id").manager_weight.first().to_dict() if "manager_weight" in weights else {}
    if not manager_weight:
        old = pd.read_parquet(R1 / "universe/selected_top100_24_manager.parquet")
        manager_weight = old.groupby("manager_id").manager_weight.first().to_dict()
    versioned["manager_weight"] = versioned.manager_id.map(manager_weight)
    assert versioned.manager_weight.notna().all()
    versioned["manager_name"] = versioned.manager_id.map(registry.set_index("normalized_manager_id").manager_name)
    initial = versioned.loc[versioned.accession.isin(initial_accessions)].copy()
    assert initial.groupby("manager_id").accession.nunique().eq(1).all()
    assert initial.manager_id.nunique() == 24
    ranked = mod.aggregate_eligible_for_ranking(initial)
    selected = mod.select_top100(ranked)
    timing = pd.DataFrame([{"quarter": "2026Q2", "report_date": pd.Timestamp("2026-06-30"),
                            "effective_date": pd.Timestamp("2026-08-21"), "expiry_date": pd.Timestamp("2026-12-31")}])
    universe = mod.build_universe(selected, timing)
    identity = pd.read_parquet(ROOT / "data/universe/security_identity_v17c_transport.parquet")
    identity["cusip"] = identity.cusip.astype(str).str.upper().str.strip()
    resolved = identity.loc[identity.mapping_status.eq("RESOLVED") &
                            identity.transport_static_validated.fillna(False).astype(bool) &
                            identity.ticker.fillna("").astype(str).str.strip().ne("") &
                            identity.moomoo_transport_code.fillna("").astype(str).str.strip().ne(""),
                            ["cusip", "ticker", "moomoo_transport_code", "mapping_source", "mapping_confidence"]].drop_duplicates("cusip")
    members = universe.merge(resolved, on="cusip", how="inner", validate="many_to_one")
    members["ticker"] = members.ticker.astype(str).str.upper().str.strip()
    members["moomoo_transport_code"] = members.moomoo_transport_code.astype(str).str.upper().str.strip()
    members = members.sort_values(["universe_rank", "cusip"], kind="mergesort")
    members = members.drop_duplicates("ticker", keep="first").drop_duplicates("moomoo_transport_code", keep="first").head(900)
    assert not members.duplicated("ticker").any() and not members.duplicated("moomoo_transport_code").any()
    restatement = filing.loc[filing.accession.eq(CITADEL_RESTATEMENT)]
    assert len(restatement) == 1 and restatement.amendment_type.iloc[0] == "RESTATEMENT"
    assert restatement.accepted_at.iloc[0] == "2026-09-01T22:14:00+00:00"
    snapshot = Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")
    qqq = pd.read_csv(snapshot / "canonical_moomoo_ohlcv_daily_qfq.csv", usecols=["ticker", "date"])
    calendar = pd.DatetimeIndex(pd.to_datetime(qqq.loc[qqq.ticker.eq("QQQ"), "date"]).sort_values().unique())
    published = pd.Timestamp(restatement.filed_date.iloc[0])
    future = calendar[calendar > published]
    assert len(future) >= 5 and future[4] == pd.Timestamp("2026-09-10")
    # Preserve as-filed complete rows and accession versions. Do not add revised Citadel to initial.
    versioned.to_parquet(HERE / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet", index=False)
    selected.to_parquet(HERE / "Q2_ORIGINAL24_INITIAL_TOP100.parquet", index=False)
    members.to_parquet(HERE / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet", index=False)
    h = versioned.loc[versioned.eligible].groupby(["manager_id", "accession", "filed_date"], as_index=False).agg(
        full_eligible_equity_value_usd=("value_usd", "sum"), eligible_row_count=("value_usd", "size"),
        eligible_cusip_count=("cusip", "nunique"))
    h.to_csv(HERE / "Q2_ORIGINAL24_VERSIONED_H.csv", index=False)
    manager_rows = []
    aggregate_rows = []
    for state, citadel_accession in (("INITIAL_24", direct.loc[direct.original_manager_id.eq("citadel"), "accession"].iloc[0]),
                                     ("CITADEL_RESTATED", CITADEL_RESTATEMENT)):
        chosen = initial.loc[~initial.manager_id.eq("citadel")].copy()
        citadel = versioned.loc[versioned.accession.eq(citadel_accession)]
        chosen = pd.concat([chosen, citadel], ignore_index=True)
        h_state = h.loc[h.accession.isin(set(chosen.accession))]
        assert len(h_state) == 24 and h_state.manager_id.nunique() == 24
        values = chosen.loc[chosen.eligible].groupby(["manager_id", "cusip"], as_index=False).value_usd.sum()
        grid = h_state[["manager_id", "accession", "full_eligible_equity_value_usd"]].merge(
            members[["ticker", "cusip"]], how="cross").merge(values, on=["manager_id", "cusip"], how="left", validate="many_to_one")
        grid["amount_status"] = np.where(grid.value_usd.notna(), "LISTED_FULL_VERSION", "COMPLETE_PUBLIC_VERSION_NOT_LISTED")
        grid["public_equity_amount_usd"] = grid.value_usd.fillna(0.0)
        grid["holding_share"] = grid.public_equity_amount_usd / grid.full_eligible_equity_value_usd
        assert len(grid) == 24 * len(members) and grid.holding_share.between(0,1+1e-10).all()
        grid["version_state"] = state
        manager_rows.append(grid)
        agg = grid.groupby(["ticker", "cusip"], as_index=False).agg(
            M_full_version_usd=("public_equity_amount_usd", "sum"),
            C_full_version=("holding_share", "mean"),
            B_full_version=("public_equity_amount_usd", lambda s: float((s>0).sum())/24),
            listed_manager_count=("value_usd", lambda s:int(s.notna().sum())),
            H_known_manager_count=("full_eligible_equity_value_usd", "count"))
        agg["version_state"] = state
        aggregate_rows.append(agg)
    pd.concat(manager_rows, ignore_index=True).to_parquet(HERE / "Q2_ORIGINAL24_CANDIDATE_MANAGER_VH.parquet", index=False)
    pd.concat(aggregate_rows, ignore_index=True).to_parquet(HERE / "Q2_ORIGINAL24_CANDIDATE_AGG_VH.parquet", index=False)
    source_rows = []
    for row in direct.itertuples(index=False):
        source_rows.append({"original_manager_id": row.original_manager_id, "original_cik": row.cik_norm,
                            "source_cik": row.cik_norm, "accession": row.accession,
                            "form": row.form, "accepted_at": row.accepted_at,
                            "source_scope": "DIRECT_INITIAL", "value_total_status": row.value_total_status})
    source_rows.append({"original_manager_id":"pershing_square", "original_cik":OLD_CIK,"source_cik":NEW_CIK,
                        "accession":PERSHING_ACCESSION,"form":"13F-HR","accepted_at":alias_filing.accepted_at.iloc[0],
                        "source_scope":"OTHER_MANAGER_1_14_OF_15_ROWS","value_total_status":alias_filing.value_total_status.iloc[0]})
    source_rows.append({"original_manager_id":"citadel", "original_cik":"1423053","source_cik":"1423053",
                        "accession":CITADEL_RESTATEMENT,"form":"13F-HR/A","accepted_at":restatement.accepted_at.iloc[0],
                        "source_scope":"RESTATEMENT_REPLACES_INITIAL_AFTER_FIFTH_SESSION","value_total_status":restatement.value_total_status.iloc[0]})
    pd.DataFrame(source_rows).sort_values(["original_manager_id", "accepted_at"]).to_csv(HERE / "Q2_ORIGINAL24_SOURCE_MAP.csv", index=False)
    result = {"status":"Q2_ORIGINAL24_INITIAL_POOL_MATERIALIZED_VERSIONS_SEPARATED", "original_managers":24,
              "direct_initial_managers":23,"pershing_other_manager_1_rows":14,"pershing_excluded_other_manager_rows":1,
              "initial_accessions":24,"citadel_restatement_accession":CITADEL_RESTATEMENT,
              "citadel_restatement_filed_date":"2026-09-02","citadel_restatement_accepted_at":"2026-09-01T22:14:00+00:00",
              "citadel_restatement_effective_date":str(future[4].date()), "initial_effective_date":"2026-08-21",
              "initial_complete_h_states":int(h.loc[~h.accession.eq(CITADEL_RESTATEMENT)].manager_id.nunique()),
              "initial_top100_rows":len(selected),"initial_mapped_candidate_count":len(members),
              "versioned_candidate_vh_states":2,"candidate_manager_vh_rows":sum(len(x) for x in manager_rows),
              "duquesne_himalaya_cover_detail_mismatch_preserved":True,
              "input_sha256":{name:sha(INTAKE / name) for name in ("raw_filings.parquet","raw_holdings.parquet")},
              "v17b_sha256":sha(SOURCE), "no_training_or_policy_outcomes_read":True}
    (HERE / "Q2_INTAKE_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
