"""Small read-only real-ETF contract smoke; it does not train or select a model."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
from fast3.src.fast3.backtest.portfolio_contract import simulate_primary_portfolio
from fast3.src.fast3.common.contracts import ExecutableContract
from fast3.src.fast3.labels.executable_trade_label import build_executable_trade_labels

CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
STATE = REPO / "fast3" / "state" / "FAST3_STATE.json"


def resolve_result_root(state_path: Path = STATE) -> Path:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return Path(state["result_root"])


def resolve_output_dir(output_dir: str | None = None, state_path: Path = STATE) -> Path:
    root = resolve_result_root(state_path)
    candidate = Path(output_dir) if output_dir else root / "_tmp" / "FAST3_002_contract_smoke"
    if os.environ.get("FAST3_TEST_MODE") != "1" and (candidate == REPO or REPO in candidate.parents):
        raise ValueError("repository-internal FAST3 result paths are forbidden outside FAST3_TEST_MODE")
    if os.environ.get("FAST3_TEST_MODE") != "1" and root not in candidate.parents and candidate != root:
        raise ValueError("FAST3 result path must be under FAST3_STATE result_root")
    return candidate


def load(symbol: str) -> pd.DataFrame:
    path = CANONICAL / f"symbol={symbol}" / "year=2024" / "month=01" / "data.parquet"
    return pd.read_parquet(path, columns=["timestamp_et", "timestamp_utc", "broker_trade_date", "session", "open", "high", "low", "close", "volume"])


def legacy_up_label(underlying: pd.DataFrame, timestamp, horizon_minutes=1440) -> int:
    x = underlying.copy(); x.timestamp_et = pd.to_datetime(x.timestamp_et)
    start = x[x.timestamp_et > timestamp]
    if start.empty: return 0
    entry = start.iloc[0]; path = start[start.timestamp_et <= entry.timestamp_et + pd.Timedelta(minutes=horizon_minutes)]
    if path.empty: return 0
    up = (path.high >= entry.open * 1.01).any(); down = (path.low <= entry.open * .99).any()
    return int(up and not down)


def main(output_dir: str | None = None) -> int:
    out = resolve_output_dir(output_dir)
    contract = ExecutableContract.from_file(REPO / "fast3" / "configs" / "contracts" / "FAST3_002_EXECUTABLE_CONTRACT.json")
    soxx, soxl, soxs = load("SOXX"), load("SOXL"), load("SOXS")
    soxx.timestamp_et = pd.to_datetime(soxx.timestamp_et)
    candidates = soxx.iloc[60::120].head(12)
    signals = pd.DataFrame({"decision_timestamp_et": candidates.timestamp_et, "underlying_symbol": "SOXX", "direction": "UP"})
    labels_a = build_executable_trade_labels(signals, {"SOXL": soxl, "SOXS": soxs}, contract, 10)
    labels_b = build_executable_trade_labels(signals, {"SOXL": soxl, "SOXS": soxs}, contract, 10, "MODE_B_NEXT_BAR_VWAP_PROXY")
    portfolio, counts = simulate_primary_portfolio(labels_a)
    legacy = [legacy_up_label(soxx, t) for t in signals.decision_timestamp_et]
    comparable = labels_a.executable_trade_label.notna()
    disagreement = float((pd.Series(legacy, index=labels_a.index)[comparable] != labels_a.loc[comparable, "executable_trade_label"]).mean()) if comparable.any() else None
    out.mkdir(parents=True, exist_ok=True)
    labels_a.to_csv(out / "FAST3_002_SMOKE_LABELS_MODE_A.csv", index=False)
    summary = {"stage": "FAST3-002", "purpose": "contract smoke only; no model trained or selected", "confirmation_read_count": 0,
               "config_sha256": contract.config_hash, "smoke_event_count": len(signals), "smoke_accepted_trade_count": counts["ACCEPTED_TRADE_COUNT"],
               "portfolio_counts": counts, "legacy_vs_executable_label_disagreement_rate": disagreement,
               "mode_a_rows": len(labels_a), "mode_b_rows": len(labels_b), "broker_action_allowed": False, "live_trading_allowed": False}
    (out / "FAST3_002_SMOKE_SUMMARY.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir")
    raise SystemExit(main(parser.parse_args().output_dir))
