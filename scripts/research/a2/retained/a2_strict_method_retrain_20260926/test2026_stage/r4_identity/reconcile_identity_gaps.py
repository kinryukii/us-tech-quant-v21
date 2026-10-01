"""Exact-key r4 identity, first-trade, and raw-jump evidence overlay.

This script never modifies the r3 ledger or invokes price/model builders.
Its proposed dependency resolutions require the full gate to be recomputed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
OLD = Path(r"C:\Users\Lenovo\Documents\CODING开发\a2_13f_learned_sizing_pre2026_test2026_r1\continuation_2026_r1")
RAW = Path(r"C:\Users\Lenovo\Documents\CODING开发\a2_strict_method_retrain_20260926\test2026_stage\fixed_window_raw")
QFQ = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
POLICY = Path(r"D:\us-tech-quant-results\permanent_security_uid_authority_policy_r1\20260903T154404Z\summary\uid_authority_policy_v1.json")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ledger = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
    assert len(ledger) == 111868 and not ledger.duplicated(KEY).any()
    remaining = ledger.loc[ledger.final_input_gate.isin([
        "UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY", "UNKNOWN_121_HISTORY",
        "UNKNOWN_UNEXPLAINED_RAW_JUMP", "UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL",
    ])].copy()
    assert remaining.final_input_gate.value_counts().to_dict() == {
        "UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY": 2849,
        "UNKNOWN_121_HISTORY": 768,
        "UNKNOWN_UNEXPLAINED_RAW_JUMP": 208,
        "UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL": 181,
    }
    resolutions = pd.read_csv(OLD / "REMAINING75_RESOLUTION.csv", dtype={"original_cusip": str})
    no_raw = remaining.loc[remaining.feature_error.eq("NO_SAVED_RAW")].copy()
    assert len(no_raw) == 2787 and no_raw.moomoo_transport_code.nunique() == 43
    grouped = no_raw.groupby(["moomoo_transport_code", "ticker", "cusip"], as_index=False).agg(
        affected_candidate_days=("signal_date", "size"),
        first_signal=("signal_date", "min"), last_signal=("signal_date", "max"))
    grouped = grouped.merge(resolutions[["original_code", "case_kind", "lifecycle_end_exclusive",
                                         "prior_provider_status", "resolution_status", "evidence_refs"]],
                            left_on="moomoo_transport_code", right_on="original_code", validate="one_to_one")
    assert grouped.prior_provider_status.eq("SUBSCRIBE_REJECTED_CODE").all()
    dated = grouped.loc[grouped.lifecycle_end_exclusive.notna()].copy()
    assert dated.last_signal.lt(dated.lifecycle_end_exclusive).all()
    grouped["r4_disposition"] = "STILL_UNKNOWN_PRE_TERMINATION_OR_ACTIVE_RAW_MISSING"
    grouped["required_next_input"] = "ORIGINAL_SOURCE_RAW_OHLC_WITH_SECURITY_IDENTITY_AND_REHAB_PASS"
    grouped.to_csv(HERE / "NO_SAVED_RAW_43_CODE_TASKS.csv", index=False)
    no_raw[KEY + ["ticker", "moomoo_transport_code", "final_input_gate"]].to_parquet(
        HERE / "NO_SAVED_RAW_2787_EXACT_KEYS.parquet", index=False)

    first_trade = {
        "MDLN": ("2025-12-17", "MDLN_NASDAQ_FIRST_TRADE.html",
                 "https://www.nasdaq.com/events/medline-inc-rings-opening-bell"),
        "PURR": ("2025-12-03", "PURR_NASDAQ_ISSUER_RELEASE.html",
                 "https://www.nasdaq.com/press-release/hyperliquid-strategies-inc-and-sonnet-biotherapeutics-holdings-inc-announce-closing"),
        "WLTH": ("2025-12-12", "WLTH_NASDAQ_LISTING_DAY.html",
                 "https://www.nasdaq.com/events/wealthfront-rings-opening-bell"),
    }
    qqq = []
    for year in (2025, 2026):
        qqq.append(pd.read_parquet(QFQ / f"year={year}/prices.parquet", columns=["ticker", "trade_date"])
                   .loc[lambda x: x.ticker.eq("QQQ"), "trade_date"])
    calendar = pd.DatetimeIndex(pd.concat(qqq)).unique().sort_values()
    position = pd.Series(range(len(calendar)), index=calendar)
    prewarm = remaining.loc[remaining.final_input_gate.eq("UNKNOWN_121_HISTORY")].copy()
    prewarm["first_trade_official"] = prewarm.ticker.map({k: v[0] for k, v in first_trade.items()})
    prewarm["official_source_url"] = prewarm.ticker.map({k: v[2] for k, v in first_trade.items()})
    prewarm["corroborating_sec_url"] = prewarm.ticker.map({
        "PURR": "https://www.sec.gov/Archives/edgar/data/2078856/000119312525311400/d47504d10q.htm",
        "WLTH": "https://www.sec.gov/Archives/edgar/data/1524566/000162828026027232/wlth-20260131.htm",
    })
    prewarm["official_local_original"] = prewarm.ticker.map({k: str(HERE / v[1]) for k, v in first_trade.items()})
    prewarm["first_eligible_qqq_session"] = None
    for ticker, (first, _, _) in first_trade.items():
        start = position[pd.Timestamp(first)]
        eligible = calendar[int(start) + 120]
        prewarm.loc[prewarm.ticker.eq(ticker), "first_eligible_qqq_session"] = str(eligible.date())
    studied = prewarm.loc[prewarm.first_trade_official.notna()].copy()
    assert len(studied) == 209
    assert (studied.signal_date.astype(str) < studied.first_eligible_qqq_session).all()
    studied["r4_dependency_result"] = "PROVEN_ORIGINAL_121_INELIGIBLE_BY_OFFICIAL_FIRST_TRADE"
    studied[KEY + ["ticker", "first_trade_official", "first_eligible_qqq_session",
                   "official_source_url", "corroborating_sec_url", "official_local_original",
                   "r4_dependency_result"]].to_parquet(
        HERE / "PREWARM_209_EXACT_KEYS.parquet", index=False)
    prewarm.loc[prewarm.first_trade_official.isna(), KEY + ["ticker", "final_input_gate"]].to_parquet(
        HERE / "PREWARM_559_STILL_UNKNOWN_KEYS.parquet", index=False)

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["cusip_rules"]["cusip_change_implies_new_uid"] is False
    rlyb = remaining.loc[remaining.final_input_gate.eq("UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL")].copy()
    assert len(rlyb) == 181 and rlyb.ticker.eq("RLYB").all()
    assert set(rlyb.cusip) == {"75120L100", "75120L209"}
    rlyb["effective_cusip_on_signal"] = rlyb.signal_date.map(
        lambda d: "75120L100" if d < pd.Timestamp("2026-02-06") else "75120L209")
    rlyb["original_13f_cusip_continues_via_split"] = rlyb.cusip.ne(rlyb.effective_cusip_on_signal)
    rlyb["r4_identity_result"] = "SAME_COMMON_SHARE_ECONOMIC_SECURITY_EFFECTIVE_DATED_CUSIP_CHANGE"
    rlyb["r4_recomputed_primary_pending_event_review"] = rlyb.signal_date.map(
        lambda d: "INPUT_VERIFIED_THIS_GATE" if d < pd.Timestamp("2026-02-06")
        else "UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME")
    rlyb["r4_identity_source"] = str(HERE / "RLYB_NASDAQ_ECA2026_71.html")
    rlyb[KEY + ["ticker", "moomoo_transport_code", "effective_cusip_on_signal",
                "original_13f_cusip_continues_via_split", "r4_identity_result", "r4_identity_source",
                "r4_recomputed_primary_pending_event_review",
                "first_consumed_2026_event", "2026_event_publication_time_unverified"]].to_parquet(
        HERE / "RLYB_181_EXACT_KEY_INTERVAL_OVERLAY.parquet", index=False)

    jumps = remaining.loc[remaining.final_input_gate.eq("UNKNOWN_UNEXPLAINED_RAW_JUMP")].copy()
    assert jumps.ticker.value_counts().to_dict() == {"FLYX": 177, "SION": 31}
    jump_checks = []
    for ticker, day in [("FLYX", "2026-01-08"), ("SION", "2026-08-10")]:
        old = pd.read_parquet(Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw") / f"US_{ticker}.parquet")
        new = pd.read_parquet(RAW / f"RAW_US_{ticker}_K_DAY_NONE_RTH.parquet")
        cols = ["time_key", "open", "high", "low", "close", "volume"]
        old.time_key = pd.to_datetime(old.time_key)
        new.time_key = pd.to_datetime(new.time_key)
        overlap = old[cols].merge(new[cols], on="time_key", suffixes=("_old", "_new"), validate="one_to_one")
        assert all(overlap[f"{col}_old"].equals(overlap[f"{col}_new"]) for col in cols[1:])
        event = new.loc[new.time_key.eq(pd.Timestamp(day))].iloc[0]
        jump_checks.append({"ticker": ticker, "jump_date": day, "old_new_raw_overlap_rows": len(overlap),
                            "old_new_ohlcv_exact": True, "event_open": event.open, "event_close": event.close,
                            "event_volume": event.volume,
                            "old_raw_sha256": sha(Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw") / f"US_{ticker}.parquet"),
                            "new_raw_sha256": sha(RAW / f"RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"),
                            "issuer_context_url": "https://ir.flyexclusive.com/news-events/press-releases/detail/162/flyexclusive-named-authorized-starlink-aviation-dealer"
                            if ticker == "FLYX" else "https://investors.sionnatx.com/news-releases/news-release-details/sionna-therapeutics-reports-topline-data-two-development"})
    pd.DataFrame(jump_checks).to_csv(HERE / "JUMP_TWO_CODE_RAW_OVERLAP_CHECK.csv", index=False)
    jumps[KEY + ["ticker", "first_unexplained_2026_jump", "final_input_gate"]].to_parquet(
        HERE / "JUMP_208_EXACT_KEYS.parquet", index=False)
    flyx = jumps.loc[jumps.ticker.eq("FLYX")].copy()
    assert len(flyx) == 177
    assert flyx.lookback_121_eligible.fillna(False).all()
    assert flyx.has_32_finite.all() and flyx.coordinate_match.all()
    assert not flyx.no_frozen_coordinate_overlap.any()
    assert not flyx["2026_event_publication_time_unverified"].any()
    flyx["r4_dependency_result"] = "JUMP_IS_CORROBORATED_UNADJUSTED_SAME_CLASS_MARKET_MOVE"
    flyx["r4_recomputed_gate_if_no_other_new_conflict"] = "INPUT_VERIFIED_THIS_GATE"
    flyx["official_price_source"] = str(HERE / "FLYX_ISSUER_PROSPECTUS_20260109.html")
    flyx[KEY + ["ticker", "r4_dependency_result", "r4_recomputed_gate_if_no_other_new_conflict",
                "official_price_source"]].to_parquet(HERE / "FLYX_177_EXACT_KEY_PASS_OVERLAY.parquet", index=False)
    source_manifest = []
    for name, (_, file, url) in first_trade.items():
        path = HERE / file
        source_manifest.append({"case": name, "url": url, "path": str(path), "sha256": sha(path)})
    for case, file, url in [
        ("RLYB", "RLYB_NASDAQ_ECA2026_71.html", "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-71"),
        ("FLYX", "FLYX_ISSUER_20260108.html", "https://ir.flyexclusive.com/news-events/press-releases/detail/162/flyexclusive-named-authorized-starlink-aviation-dealer"),
        ("FLYX", "FLYX_ISSUER_PROSPECTUS_20260109.html", "https://ir.flyexclusive.com/sec-filings/all-sec-filings/content/0001193125-26-009098/333-287720_final_pro-sup.htm"),
    ]:
        path = HERE / file
        source_manifest.append({"case": case, "url": url, "path": str(path), "sha256": sha(path)})
    pd.DataFrame(source_manifest).to_csv(HERE / "LOCAL_PRIMARY_SOURCE_MANIFEST.csv", index=False)
    transitions = []
    for part, proposed, basis in [
        (studied, "PROVEN_ORIGINAL_121_INELIGIBLE", "OFFICIAL_FIRST_TRADE_AND_FROZEN_QQQ_CALENDAR"),
        (flyx, "INPUT_VERIFIED_THIS_GATE", "ISSUER_PROSPECTUS_EXACT_CLOSE_PLUS_SAME_SOURCE_RAW"),
    ]:
        t = part[KEY + ["ticker", "final_input_gate"]].copy()
        t["r4_primary_proposal"] = proposed
        t["r4_basis"] = basis
        transitions.append(t)
    t = rlyb[KEY + ["ticker", "final_input_gate"]].copy()
    t["r4_primary_proposal"] = rlyb.r4_recomputed_primary_pending_event_review
    t["r4_basis"] = "SAME_SECURITY_EFFECTIVE_DATED_CUSIP_SPLIT;_EVENT_VERSION_STILL_SEPARATE"
    transitions.append(t)
    transitions = pd.concat(transitions, ignore_index=True)
    assert len(transitions) == 567 and not transitions.duplicated(KEY).any()
    transitions.to_parquet(HERE / "R4_IDENTITY_567_EXACT_KEY_TRANSITIONS.parquet", index=False)
    report = {
        "r3_ledger_sha256": sha(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet"),
        "remaining75_resolution_sha256": sha(OLD / "REMAINING75_RESOLUTION.csv"),
        "frozen_uid_policy_sha256": sha(POLICY),
        "original_adjusted_price_builder_sha256": sha(Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")),
        "r3_target_rows": len(remaining), "no_raw_rows_still_unknown": len(no_raw),
        "no_raw_codes": no_raw.moomoo_transport_code.nunique(),
        "prewarm_rows_proven_121_ineligible": len(studied),
        "prewarm_rows_still_unknown": len(prewarm) - len(studied),
        "rlyb_rows_identity_interval_resolved_only": len(rlyb),
        "rlyb_old_13f_cusip_after_change_continuing_security_rows": int(rlyb.original_13f_cusip_continues_via_split.sum()),
        "rlyb_pre_split_rows_recomputed_input_verified": int(rlyb.signal_date.lt(pd.Timestamp("2026-02-06")).sum()),
        "rlyb_post_split_rows_pending_event_version_review": int(rlyb.signal_date.ge(pd.Timestamp("2026-02-06")).sum()),
        "jump_rows_with_repeated_exact_same_source_ohlcv": len(jumps),
        "flyx_jump_rows_dependency_resolved": len(flyx),
        "sion_jump_rows_still_unknown": int(jumps.ticker.eq("SION").sum()),
        "jump_economic_interpretation": "FLYX original issuer prospectus confirms 2026-01-08 NYSE American common-share close $7.23, exactly matching saved original-source Raw; repeated old/new OHLCV overlap and same-day issuer news support genuine market move. SION has same-day issuer negative trial data and repeated exact original-source Raw, but no saved independent original exchange/issuer close; keep 31 unknown.",
        "rlyb_notice": "CUSIP change does not imply new UID under frozen policy; do not mark old 13F membership ineligible solely because CUSIP changed.",
        "model_fit_calls": 0, "preprocessor_fit_calls": 0,
    }
    (HERE / "IDENTITY_R4_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
