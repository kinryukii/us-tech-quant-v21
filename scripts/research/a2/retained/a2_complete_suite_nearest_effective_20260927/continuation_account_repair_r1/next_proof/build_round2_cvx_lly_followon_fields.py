"""Prove only two V10 follow-on held-position and requested-sell dates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
JOINT = HERE.parents[1]
WORKSPACE = JOINT.parent
OLD = WORKSPACE / "a2_complete_suite_20260927"
STAGE = WORKSPACE / "a2_strict_method_retrain_20260926" / "test2026_stage"
V10 = HERE.parent / "replay/repair_r2_v10_cvx_lly_ral_9"
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
SPEC = {
    "CVX": {
        "date": "2026-02-18", "prior": "2026-02-17", "pre_event": "2026-02-13",
        "factor": 0.99031, "cash": 1.78, "cusip": "166764100", "public": "2026-01-30",
        "family": "joint_rl_ensemble", "prior_proof": "ROUND2_CVX_PROOF.json",
        "prior_allowlist": "ROUND2_CVX_ACCOUNT_PRICE_FIELDS.parquet",
        "prior_evidence_id": "CVX_20260217_FIRST_CASH_ACCOUNT_FIELD",
        "issuer_source": "https://www.chevron.com/-/media/chevron/stories/documents/4Q-2025-earnings-pressrelease.pdf",
        "evidence_id": "ROUND2_CVX_20260218_CASH_SUCCESSOR_INDEX_UNIT",
    },
    "LLY": {
        "date": "2026-02-17", "prior": "2026-02-13", "pre_event": "2026-02-12",
        "factor": 0.99833, "cash": 1.73, "cusip": "532457108", "public": "2025-12-08",
        "family": "joint_mlp", "prior_proof": "ROUND2_LLY_PROOF.json",
        "prior_allowlist": "ROUND2_LLY_EVENT_ACCOUNT_PRICE_FIELDS.parquet",
        "prior_evidence_id": "ROUND2_LLY_20260213_CASH_DIVIDEND_INDEX_UNIT",
        "issuer_source": "https://investor.lilly.com/node/53501/pdf",
        "issuer_ex_date_table": "https://investor.lilly.com/stock-information/dividends-splits",
        "evidence_id": "ROUND2_LLY_20260217_CASH_SUCCESSOR_INDEX_UNIT",
    },
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(actual: float, expected: float, label: str, atol: float = 1e-7) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=atol), (label, actual, expected)


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "frozen_account_engine": JOINT / "engine.py",
    }
    for ticker, spec in SPEC.items():
        paths[f"{ticker}_prior_proof"] = HERE / spec["prior_proof"]
        paths[f"{ticker}_prior_allowlist"] = HERE / spec["prior_allowlist"]
        paths[f"{ticker}_fixed_raw"] = STAGE / f"fixed_window_raw/RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"
        for bps in (5, 10, 25):
            run = f"{spec['family']}_{bps}bps"
            paths[f"{ticker}_{run}_checkpoint"] = V10 / run / "CHECKPOINT.json"
            paths[f"{ticker}_{run}_consumed_approvals"] = V10 / run / "CONSUMED_APPROVALS.csv"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    prices = pd.read_parquet(paths["joint_prices"])
    calendar = pd.read_parquet(paths["calendar"])
    events = pd.read_parquet(paths["consumed_events"])
    audit = pd.read_csv(paths["event_audit"])
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    allowed = []
    findings = []
    for ticker, spec in SPEC.items():
        day = pd.Timestamp(spec["date"])
        prior_day = pd.Timestamp(spec["prior"])
        pre_day = pd.Timestamp(spec["pre_event"])
        code = f"US.{ticker}"
        assert pd.Timestamp(spec["public"]) < prior_day < day
        prior_proof = json.loads(paths[f"{ticker}_prior_proof"].read_text("utf-8"))
        assert prior_proof["candidate_pool_version"] == "R6_UNCHANGED"
        assert prior_proof["output_sha256"][spec["prior_allowlist"]] == hashes[f"{ticker}_prior_allowlist"]["sha256"]
        prior_allow = pd.read_parquet(paths[f"{ticker}_prior_allowlist"])
        prior_allow = one(prior_allow.loc[prior_allow.ticker.eq(ticker) & prior_allow.trade_date.eq(prior_day)], "prior allowlist")
        assert bool(prior_allow.open_authorized) and bool(prior_allow.close_authorized)
        assert prior_allow.evidence_id == spec["prior_evidence_id"]
        assert prior_allow.fixed_raw_sha256 == hashes[f"{ticker}_fixed_raw"]["sha256"]
        assert bool(one(calendar.loc[calendar.trade_date.eq(day)], "follow-on calendar session").is_test)

        demand = []
        holdings = {}
        run_ids = []
        for bps in (5, 10, 25):
            run = f"{spec['family']}_{bps}bps"
            checkpoint = json.loads(paths[f"{ticker}_{run}_checkpoint"].read_text("utf-8"))
            assert checkpoint["run_id"] == run and checkpoint["status"] == "paused_before_uncertified_input"
            assert checkpoint["certified_through"] == spec["prior"] and checkpoint["next_date"] == spec["date"]
            assert checkpoint["new_predictor_fit_attempts"] == 0 and checkpoint["new_preprocessor_fit_attempts"] == 0
            found = checkpoint["next_required_inputs"]
            assert len(found) == 3
            assert {(x["ticker"], x["date"], x["field"], x["purpose"]) for x in found} == {
                (ticker, spec["date"], "open", "held_position_pretrade_nav_or_exit"),
                (ticker, spec["date"], "open", "requested_position_sell"),
                (ticker, spec["date"], "close", "actual_held_position_valuation"),
            }
            held_need = one(pd.DataFrame(found).loc[lambda d: d.purpose.eq("held_position_pretrade_nav_or_exit")], "held open")
            assert held_need.pending_signal_date == spec["prior"]
            position = checkpoint["holdings"][ticker]
            assert position["index_units"] > 0 and position["mark_date"] == spec["prior"]
            assert position["mark_source"] == "close"
            close(float(position["mark"]), float(prior_allow.close), "certified preceding close mark")
            approvals = pd.read_csv(paths[f"{ticker}_{run}_consumed_approvals"], dtype=str).fillna("")
            consumed_prior = approvals.loc[approvals.ticker.eq(ticker) & approvals.trade_date.eq(spec["prior"])]
            assert len(consumed_prior) == 2 and set(consumed_prior.field) == {"open", "close"}
            assert set(consumed_prior.evidence_id) == {spec["prior_evidence_id"]}
            demand.extend([{"run_id": run, **item} for item in found])
            holdings[run] = float(position["index_units"])
            run_ids.append(run)

        pre = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(pre_day)], "pre-event price")
        prior = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(prior_day)], "prior certified price")
        p = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(day)], "follow-on price")
        assert not bool(pre.price_quality_warning) and not bool(pre.unresolved_event_on_or_before)
        for row in (prior, p):
            assert row.original_transport == code and row.transport_used == code
            assert row.price_coordinate == COORDINATE
            assert bool(row.unresolved_event_on_or_before) and bool(row.price_quality_warning)
            assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
            for field in ("open", "close", "raw_open", "raw_close", "volume"):
                assert np.isfinite(row[field]) and row[field] > 0
        close(float(prior.open), float(prior_allow.open), "prior open remains unchanged")
        close(float(prior.close), float(prior_allow.close), "prior close remains unchanged")

        receipt = [r for r in receipts if r["ticker"] == ticker and r["original_code"] == code]
        assert len(receipt) == 1 and receipt[0]["transport"] == code
        raw_path = paths[f"{ticker}_fixed_raw"]
        raw_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == raw_path.name]
        assert len(raw_receipt) == 1 and raw_receipt[0]["sha256"] == hashes[f"{ticker}_fixed_raw"]["sha256"]
        raw = pd.read_parquet(raw_path)
        rpre = one(raw.loc[raw.code.eq(code) & raw.trade_date.eq(pre_day)], "pre-event same-source Raw")
        rprior = one(raw.loc[raw.code.eq(code) & raw.trade_date.eq(prior_day)], "prior same-source Raw")
        rnew = one(raw.loc[raw.code.eq(code) & raw.trade_date.eq(day)], "follow-on same-source Raw")
        close(float(rprior.last_close), float(rpre.close), "event-day Raw previous close")
        close(float(rnew.last_close), float(rprior.close), "follow-on Raw previous close")
        for adjusted, source in ((prior, rprior), (p, rnew)):
            close(float(adjusted.raw_open), float(source.open), "same-source raw open")
            close(float(adjusted.raw_close), float(source.close), "same-source raw close")
            close(float(adjusted.volume), float(source.volume), "same-source unchanged volume")

        applied = events.loc[
            events.code.eq(code) & events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & pd.to_datetime(events.event_date).between("2026-01-01", day)
        ]
        event = one(applied, "single original 2026 event through follow-on date")
        original = one(audit.loc[audit.code.eq(code) & audit.source_event_date.eq(spec["prior"])], "r4 event audit")
        for item in (event, original):
            assert item.code == code and item.ticker == ticker
            assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
            assert pd.Timestamp(item.event_date) == prior_day and pd.Timestamp(item.source_event_date) == prior_day
            assert not bool(item.aligned_to_next_session) and not bool(item.share_event)
            close(float(item.factor_a), spec["factor"], "original cash factor", atol=1e-12)
            close(float(item.factor_b), 0.0, "zero additive factor", atol=1e-12)
        assert original.original_code == code and original.transport_code == code
        close(float(original.prior_raw_close), float(rpre.close), "audited preceding Raw close")
        close(float(original.total_cash_div), spec["cash"], "cash per original share")
        assert bool(original.simple_cash_floor_matches_vendor)
        factor = np.floor(((float(rpre.close) - spec["cash"]) / float(rpre.close)) * 100000) / 100000
        close(factor, spec["factor"], "five-place cash factor", atol=1e-12)
        security = identity.loc[
            identity.original_code.eq(code) & identity.transport_code.eq(code)
            & identity.source_event_date.eq(spec["prior"])
        ]
        assert len(security) > 0 and set(security.cusip) == {spec["cusip"]}
        assert set(security.title_of_class) == {"COM"}
        assert security.total_cash_div.eq(spec["cash"]).all()

        assert pre.raw_open != pre.raw_close
        alpha_before = (float(pre.open) - float(pre.close)) / (float(pre.raw_open) - float(pre.raw_close))
        beta_before = float(pre.open) - alpha_before * float(pre.raw_open)
        alpha_after = alpha_before / factor
        close(beta_before, 0.0, "unchanged affine beta", atol=1e-8)
        for adjusted, source in ((prior, rprior), (p, rnew)):
            close(float(adjusted.open), alpha_after * float(source.open) + beta_before, "cash-successor index open")
            close(float(adjusted.close), alpha_after * float(source.close) + beta_before, "cash-successor index close")

        allowed.append({
            "ticker": ticker, "trade_date": day, "open": float(p.open), "close": float(p.close),
            "open_authorized": True, "close_authorized": True,
            "evidence_id": spec["evidence_id"], "candidate_pool_version": "R6_UNCHANGED",
            "fixed_raw_sha256": hashes[f"{ticker}_fixed_raw"]["sha256"],
        })
        findings.append({
            "ticker": ticker, "authorized_date": spec["date"],
            "authorized_keys": [[ticker, spec["date"], "open"], [ticker, spec["date"], "close"]],
            "v10_run_ids": sorted(run_ids), "v10_required_input_rows": demand,
            "v10_previous_certified_holdings_index_units": holdings,
            "prior_authorized_date": spec["prior"], "prior_evidence_id": spec["prior_evidence_id"],
            "original_event_date": spec["prior"], "original_cusip": spec["cusip"],
            "issuer_public_date": spec["public"], "issuer_source": spec["issuer_source"],
            "issuer_ex_date_table": spec.get("issuer_ex_date_table"),
            "issuer_cash_per_common_share": spec["cash"],
            "original_factor_a": factor, "original_factor_b": 0.0,
            "no_intervening_consumed_event": True,
            "raw_prior_close_continuity": True,
            "coordinate": COORDINATE, "alpha_before": alpha_before,
            "beta_before": beta_before, "alpha_after": alpha_after,
            "followon_raw_open": float(rnew.open), "followon_raw_close": float(rnew.close),
            "followon_raw_volume": float(rnew.volume),
            "authorized_open": float(p.open), "authorized_close": float(p.close),
        })

    out = pd.DataFrame(allowed).sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    assert len(out) == 2 and not out.duplicated(["ticker", "trade_date"]).any()
    csv_path = HERE / "ROUND2_CVX_LLY_FOLLOWON_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_CVX_LLY_FOLLOWON_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_V10_TWO_FOLLOWON_ACCOUNT_DATES_PROVEN",
        "candidate_pool_version": "R6_UNCHANGED",
        "authorized_ticker_dates": 2,
        "authorized_field_keys": [key for item in findings for key in item["authorized_keys"]],
        "excluded_scope": "No CVX date after 2026-02-18 or LLY date after 2026-02-17 is authorized by this proof.",
        "findings": findings,
        "unverified_source_details": [
            "Chevron's issuer release names 2026-02-17 as the record date, not explicitly as the U.S. ex-dividend date; the frozen original applied event and already certified 2026-02-17 account field anchor the follow-on coordinate.",
            "Historical point-in-time vendor factor-version receipts were not observed; issuer page bytes were not archived.",
        ],
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "ROUND2_CVX_LLY_FOLLOWON_PROOF.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(json.dumps({"authorized_field_keys": proof["authorized_field_keys"]}))


if __name__ == "__main__":
    main()
