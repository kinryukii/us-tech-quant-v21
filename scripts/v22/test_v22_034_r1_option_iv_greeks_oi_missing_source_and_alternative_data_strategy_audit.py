from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_034_r1_option_iv_greeks_oi_missing_source_and_alternative_data_strategy_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_034_r1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_repo(repo: Path, *, include_underlying_price: bool = True, include_missing_fields: bool = True) -> list[Path]:
    rows = []
    for idx in range(3):
        row = {
            "underlying": "QQQ",
            "expiration": "2026-07-17",
            "strike": str(500 + idx),
            "call_put": "CALL",
            "option_code": f"US.QQQ260717C50{idx}000",
            "bid": "1.00",
            "ask": "1.10",
            "mid": "1.05",
            "spread_pct": "0.0476",
            "volume": "10",
            "last": "1.08",
        }
        if include_underlying_price:
            row["underlying_price"] = "550.0"
        if include_missing_fields:
            row.update({"implied_volatility": "", "delta": "", "gamma": "", "theta": "", "vega": "", "rho": "", "open_interest": ""})
        rows.append(row)
    fields = list(rows[0].keys())
    clean = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_clean.csv"
    raw = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_raw.csv"
    write_csv(clean, fields, rows)
    write_csv(raw, fields, rows)
    summary = repo / module.V22_033_R1_DIR / "v22_option_chain_post_enrichment_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps({"final_status": "WARN_V22_033_R1_QUOTES_READY_BUT_IV_GREEKS_OI_MISSING"}), encoding="utf-8")
    return [clean, raw, summary]


def test_normalize_column_name_handles_common_noise():
    assert module.normalize_column_name(" Implied Volatility (%) ") == "implied_volatility_%"
    assert module.normalize_column_name("Option-IV//Value") == "option_iv_value"
    assert module.normalize_column_name("Greek__Delta") == "greek_delta"


def test_alias_detection_maps_required_targets():
    columns = ["Implied Volatility", "Option Delta", "greek_gamma", "Theta", "option-vega", "Greek Rho", "Open Int"]
    for target in ["implied_volatility", "delta", "gamma", "theta", "vega", "rho", "open_interest"]:
        _alias, column = module.alias_match(columns, target)
        assert column


def test_missing_schema_produces_unsupported_status(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo, include_missing_fields=False)
    summary = module.run(repo)
    caps = read_rows(repo / module.OUT_REL / "option_provider_capability_audit.csv")
    by_cap = {row["capability"]: row for row in caps}
    assert by_cap["IMPLIED_VOLATILITY"]["capability_status"] == "PROVIDER_SCHEMA_MISSING_OR_UNSUPPORTED"
    assert summary["iv_missing_source_classification"] == "PROVIDER_SCHEMA_MISSING_OR_UNSUPPORTED"


def test_schema_present_but_all_null_produces_empty_status(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    module.run(repo)
    caps = read_rows(repo / module.OUT_REL / "option_provider_capability_audit.csv")
    by_cap = {row["capability"]: row for row in caps}
    assert by_cap["IMPLIED_VOLATILITY"]["capability_status"] == "PROVIDER_SCHEMA_PRESENT_BUT_VALUES_EMPTY"


def test_schema_present_but_all_zero_produces_zero_status(tmp_path):
    repo = tmp_path / "repo"
    files = seed_repo(repo)
    for path in files:
        if path.suffix == ".csv":
            rows = read_rows(path)
            for row in rows:
                row["implied_volatility"] = "0"
                row["open_interest"] = "0"
            write_csv(path, list(rows[0].keys()), rows)
    module.run(repo)
    caps = read_rows(repo / module.OUT_REL / "option_provider_capability_audit.csv")
    by_cap = {row["capability"]: row for row in caps}
    assert by_cap["IMPLIED_VOLATILITY"]["capability_status"] == "PROVIDER_SCHEMA_PRESENT_BUT_VALUES_ZERO"
    assert by_cap["OPEN_INTEREST"]["capability_status"] == "PROVIDER_SCHEMA_PRESENT_BUT_VALUES_ZERO"


def test_field_mapping_issue_detected_when_raw_has_alias_and_clean_lacks_it(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo, include_missing_fields=False)
    raw = repo / module.V22_032_R1_READ_ONLY_DIR / "v22_option_quote_enrichment_raw.csv"
    rows = read_rows(raw)
    for row in rows:
        row["option_iv"] = "0.22"
    write_csv(raw, list(rows[0].keys()), rows)
    summary = module.run(repo)
    assert summary["iv_missing_source_classification"] == "FIELD_MAPPING_ISSUE_POSSIBLE"


def test_policy_blocks_candidates_but_allows_liquidity_and_synthetic_next(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    summary = module.run(repo)
    assert summary["full_option_candidate_generation_allowed"] is False
    assert summary["liquidity_only_research_screen_allowed"] is True
    assert summary["synthetic_iv_greeks_research_next_step_allowed"] is True
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_order_allowed"] is False


def test_synthetic_next_requires_underlying_price(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo, include_underlying_price=False)
    summary = module.run(repo)
    assert summary["liquidity_only_research_screen_allowed"] is True
    assert summary["synthetic_iv_greeks_research_next_step_allowed"] is False


def test_missing_input_returns_fail_and_main_exit_code_one(tmp_path):
    repo = tmp_path / "repo"
    output_dir = repo / module.OUT_REL
    summary = module.run(repo)
    assert summary["final_status"] == "FAIL_V22_034_R1_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(repo)]) == 1
    assert (output_dir / "v22_034_r1_summary.json").exists()


def test_warn_status_returns_exit_code_zero(tmp_path):
    repo = tmp_path / "repo"
    seed_repo(repo)
    assert module.main(["--repo-root", str(repo)]) == 0


def test_existing_input_artifacts_are_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    files = seed_repo(repo)
    before = {path: path.read_bytes() for path in files}
    module.run(repo)
    after = {path: path.read_bytes() for path in files}
    assert before == after
