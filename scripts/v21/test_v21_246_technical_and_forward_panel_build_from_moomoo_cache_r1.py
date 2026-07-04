from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_246_technical_and_forward_panel_build_from_moomoo_cache_r1.py")
S = importlib.util.spec_from_file_location("m246p", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed(tmp_path: Path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    r1a = repo / m.DEFAULT_R1A_REL
    r1a.mkdir(parents=True, exist_ok=True)
    (r1a / "v21_245_r1a_summary.json").write_text(json.dumps({"ready_for_v21_246_gate_status": "PARTIAL_PASS_READY_WITH_EXCLUSIONS", "ready_for_v21_246_gate_decision": "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST", "universe_count": 3, "both_price_types_usable_count": 2}), encoding="utf-8")
    write_csv(r1a / "moomoo_cache_ready_for_v21_246_gate.csv", [{"gate_status": "PARTIAL_PASS_READY_WITH_EXCLUSIONS", "gate_decision": "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST"}])
    current = []
    for t in ["AAA", "BBB", "MISS"]:
        for pt in ["RAW_DAILY", "QFQ_DAILY"]:
            current.append({"ticker": t, "price_type": pt})
    write_csv(r1a / "moomoo_cache_currentness_audit.csv", current)
    write_csv(r1a / "moomoo_cache_file_integrity_audit.csv", [{"ticker": "AAA"}])
    for t in ["AAA", "BBB"]:
        for pt, sub in [("RAW_DAILY", "raw"), ("QFQ_DAILY", "qfq")]:
            data = []
            for i in range(70):
                # Trading-row sequence deliberately skips calendar weekends by just using day numbers in January/March fixture.
                d = f"2026-01-{(i % 28) + 1:02d}" if i < 28 else f"2026-02-{((i - 28) % 28) + 1:02d}" if i < 56 else f"2026-03-{i - 55:02d}"
                close = 10 + i + (1 if t == "BBB" else 0)
                data.append({"date": d, "ticker": t, "moomoo_symbol": f"US.{t}", "open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": 1000 + i, "turnover": "", "price_type": pt, "provider": "MOOMOO", "fetch_timestamp": "x", "source_run_id": "r"})
            write_csv(cache / f"market_data/moomoo/daily/{sub}/{t}.csv", data)
    before = {p: file_hash(p) for p in cache.rglob("*.csv")}
    return repo, cache, before


def run_seeded(tmp_path):
    repo, cache, before = seed(tmp_path)
    s = m.run(repo, cache_root=cache, r1a_root=m.DEFAULT_R1A_REL, expected_latest_date="2026-03-14", min_usable_ticker_count=1)
    return repo, cache, repo / m.OUT_REL, s, before


def test_required_output_files_are_created(tmp_path):
    _, _, out, _, _ = run_seeded(tmp_path)
    req = ["v21_246_summary.json", "v21_246_input_cache_gate.csv", "v21_246_exclusion_list_used.csv", "technical_subfactor_panel_long.csv", "technical_subfactor_panel_wide.csv", "forward_return_panel_aligned.csv", "technical_forward_join_panel.csv", "technical_indicator_formula_audit.csv", "technical_panel_quality_audit.csv", "forward_return_quality_audit.csv", "ticker_panel_build_audit.csv", "V21.246_technical_and_forward_panel_report.txt"]
    assert all((out / x).exists() for x in req)


def test_summary_json_governance_fields(tmp_path):
    _, _, out, s, _ = run_seeded(tmp_path)
    payload = json.loads((out / "v21_246_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert k in payload
    assert s["official_adoption_allowed"] is False and s["broker_action_allowed"] is False


def test_no_provider_fetch_and_non_moomoo_providers(tmp_path):
    _, _, _, s, _ = run_seeded(tmp_path)
    assert s["provider_fetch_attempted"] is False
    text = P.read_text(encoding="utf-8").lower()
    assert not any(re.search(p, text) for p in [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"alphavantage", r"polygon", r"nasdaq"])


def test_cache_source_files_are_not_mutated(tmp_path):
    _, cache, _, _, before = run_seeded(tmp_path)
    after = {p: file_hash(p) for p in cache.rglob("*.csv")}
    assert before == after


def test_exclusion_list_is_respected(tmp_path):
    _, _, out, _, _ = run_seeded(tmp_path)
    ex = rows(out / "v21_246_exclusion_list_used.csv")
    assert any(r["ticker"] == "MISS" and r["exclusion_reason"] != "NOT_EXCLUDED" for r in ex)
    tickers = {r["ticker"] for r in rows(out / "technical_subfactor_panel_wide.csv")}
    assert "MISS" not in tickers


def test_forward_returns_use_trading_row_shifts_and_maturity_flags(tmp_path):
    _, _, out, _, _ = run_seeded(tmp_path)
    fwd = [r for r in rows(out / "forward_return_panel_aligned.csv") if r["ticker"] == "AAA"]
    first = fwd[0]
    assert abs(float(first["forward_close_5d"]) - 15.0) < 1e-9
    assert abs(float(first["forward_return_5d"]) - 0.5) < 1e-9
    assert fwd[-1]["maturity_1d"] == "False"
    assert fwd[-20]["maturity_20d"] == "False"


def test_formula_audit_includes_required_families(tmp_path):
    _, _, out, _, _ = run_seeded(tmp_path)
    names = {r["indicator_name"] for r in rows(out / "technical_indicator_formula_audit.csv")}
    assert {"RSI_14", "KDJ_K_9_3_3", "MACD_DIF_12_26", "BB_MID_20", "MA20", "MA50", "EMA12", "VOLUME_MA20", "VOLATILITY_20", "MOMENTUM_20", "RELATIVE_STRENGTH_20_VS_QQQ", "BREAKOUT_20", "PULLBACK_FROM_20D_HIGH"} <= names


def test_long_panel_standard_columns_and_cross_sectional_normalization(tmp_path):
    _, _, out, _, _ = run_seeded(tmp_path)
    data = rows(out / "technical_subfactor_panel_long.csv")
    required = {"asof_date", "ticker", "technical_subfactor_name", "technical_group", "raw_value", "normalized_value_by_date", "rank_pct_by_date", "warmup_valid", "data_quality_flag"}
    assert required <= set(data[0])
    subset = [r for r in data if r["asof_date"] == "2026-03-01" and r["technical_subfactor_name"] == "MA20" and r["rank_pct_by_date"]]
    assert len(subset) == 2
    assert sorted(float(r["rank_pct_by_date"]) for r in subset) == [0.5, 1.0]


def test_no_effectiveness_or_promotion_decisions_computed(tmp_path):
    _, _, out, s, _ = run_seeded(tmp_path)
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in [P, out / "v21_246_summary.json"])
    forbidden = ["rank_ic", "quantile_spread", "officially_adopted", "shadow_candidate"]
    assert not any(x in text.lower() for x in forbidden)
    assert "official_factor_marked_count" not in s


def test_partial_exclusions_are_not_execution_failure(tmp_path):
    _, _, _, s, _ = run_seeded(tmp_path)
    assert s["final_status"] != "FAIL_V21_246_TECHNICAL_FORWARD_PANEL_BUILD_ERROR"
