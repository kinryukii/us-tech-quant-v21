"""Preparation-only whitelist export for the R1 pre-2026 trainer."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "trainer_bundle"
OLD = ROOT.parent / "a2_top20_all_methods_20260925"
E5 = Path(r"D:\us-tech-quant-results\A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS\run_a2_execution_efficiency_r2.py")
SURFACE = Path(r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json")
CALENDAR = Path(r"D:\us-tech-quant-data\reference\trading_calendar\XNYS\versions\xnys_sessions_f61c8f8d47cd94ae4b75.parquet")
CUTOFF = pd.Timestamp("2026-01-01")
EXPECTED_PANEL = "d637bb48a8de86a5cd61ac85824ffd3f0eae4d37947e000343ca9112bc679202"
EXPECTED_RISK_PANEL = "5b3f913203f1681da40374fd34f03699da61501c67b2b34a5aa778da93f40db4"
EXPECTED_E5 = "005fdbc3a50df5552b4837e2706b7184198c1d1bfcfd7d51d03d3f3b55aabfa6"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_physical(path: Path, date_column: str) -> None:
    source = pq.ParquetFile(path)
    index = source.schema_arrow.names.index(date_column)
    for row_group in range(source.metadata.num_row_groups):
        stats = source.metadata.row_group(row_group).column(index).statistics
        if stats is None or not stats.has_min_max or pd.Timestamp(stats.max) >= CUTOFF:
            raise RuntimeError(f"UNPROVEN_PRE2026_ROW_GROUP:{path}:{row_group}")


def extract_ledger() -> str:
    text = E5.read_text(encoding="utf-8")
    tree = ast.parse(text)
    wanted = {"safe_div", "Replay", "replay"}
    found = {node.name: ast.get_source_segment(text, node) for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted}
    if set(found) != wanted:
        raise RuntimeError("E5_LEDGER_SYMBOL_CHANGED")
    replay = found["replay"]
    anchor = "signal = signal_by_execution.get(date)"
    old = "target = targets.get(signal, {}) if signal is not None else {}"
    stale = "price = marks.get(ticker, opening(date, ticker))"
    if replay.count(anchor) != 1 or replay.count(old) != 1 or replay.count(stale) != 2:
        raise RuntimeError("E5_CLOCK_SEAM_CHANGED")
    injection = '''signal = signal_by_execution.get(date)
        decision_values = {}
        if signal is not None:
            for ticker, qty in shares.items():
                if ticker not in close_wide.columns:
                    raise RuntimeError(f"no signal-close series:{ticker}:{signal}")
                hist = close_wide.loc[close_wide.index <= signal, ticker].dropna()
                hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
                if hist.empty:
                    raise RuntimeError(f"no prior signal-close mark:{ticker}:{signal}")
                decision_values[ticker] = qty * float(hist.iloc[-1])
            decision_nav = cash + sum(decision_values.values())
            target = targets(signal, shares.copy(), decision_values.copy(), decision_nav)
        else:
            target = {}'''
    replay = replay.replace(anchor, injection, 1).replace(old, "# target fixed at signal close", 1)
    replay = replay.replace(stale, "price = opening(date, ticker)")
    header = ('"""Whitelisted E5 Replay/safe_div source with the R1 close-clock seam.\n'
              'No other E5 execution or accounting branch is changed.\n"""\n'
              'from __future__ import annotations\n'
              'from dataclasses import dataclass\nimport numpy as np\nimport pandas as pd\n'
              'TOL = 1e-10\nCOST_RATE = 0.001\n\n')
    return header + found["safe_div"] + "\n\n@dataclass\n" + found["Replay"] + "\n\n" + replay + "\n"


def main() -> None:
    if BUNDLE.exists():
        raise RuntimeError("BUNDLE_ALREADY_EXISTS_NON_OVERWRITE")
    if sha(E5) != EXPECTED_E5:
        raise RuntimeError("E5_SOURCE_IDENTITY_CHANGED")
    (BUNDLE / "data").mkdir(parents=True)
    panel_source = OLD / "pre2026_panel.parquet"
    if sha(panel_source) != EXPECTED_PANEL:
        raise RuntimeError("PANEL_IDENTITY_CHANGED")
    require_physical(panel_source, "signal_date")
    require_physical(panel_source, "label_end_date_5")
    panel = pq.read_table(panel_source).to_pandas()
    if panel.signal_date.max() >= CUTOFF or panel.label_end_date_5.dropna().max() >= CUTOFF:
        raise RuntimeError("PANEL_DATE_BOUNDARY")
    shutil.copyfile(panel_source, BUNDLE / "data" / "panel.parquet")
    safe_path = ROOT.parent / "a2_top20_action_nn_20260925" / "safe_inputs.py"
    module_spec = importlib.util.spec_from_file_location("r1_preparer_safe_inputs", safe_path)
    safe = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(safe)
    old_panel, _, _, _ = safe.load_inputs()
    risk_columns = ["signal_date", "ticker", "raw_rank_strength", "raw_score_z",
                    "ret_1d", "ret_5d", "ret_20d", "realized_vol_20d", "downside_vol_20d",
                    "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20",
                    "distance_from_high_20d"]
    risk_panel = old_panel[risk_columns]
    if risk_panel.signal_date.max() >= CUTOFF:
        raise RuntimeError("RISK_PANEL_DATE_BOUNDARY")
    risk_panel.to_parquet(BUNDLE / "data" / "risk_panel.parquet", index=False)
    require_physical(BUNDLE / "data" / "risk_panel.parquet", "signal_date")
    if sha(BUNDLE / "data" / "risk_panel.parquet") != EXPECTED_RISK_PANEL:
        raise RuntimeError("RISK_PANEL_IDENTITY_CHANGED")

    source_manifest = json.loads(SURFACE.read_text(encoding="utf-8"))
    base = Path(source_manifest["surface_path"])
    pieces = []
    sources = []
    for item in source_manifest["partitions"]:
        path = base / item["relative_path"]
        if sha(path) != item["sha256"]:
            raise RuntimeError(f"PRICE_SOURCE_HASH_CHANGED:{item['relative_path']}")
        require_physical(path, "trade_date")
        pieces.append(pq.read_table(path, columns=["ticker", "trade_date", "open", "close"]).to_pandas())
        sources.append({"relative_path": item["relative_path"], "sha256": item["sha256"]})
    sessions = pq.read_table(CALENDAR, columns=["trade_date"]).to_pandas()
    sessions = sessions.loc[pd.to_datetime(sessions.trade_date).lt(CUTOFF)
                            & pd.to_datetime(sessions.trade_date).ge("2020-01-01")]
    calendar_only = pd.DataFrame({"ticker": "QQQ", "trade_date": pd.to_datetime(sessions.trade_date),
                                  "open": 1.0, "close": 1.0})
    prices = pd.concat([*pieces, calendar_only], ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    if prices.trade_date.max() >= CUTOFF or prices.duplicated(["ticker", "trade_date"]).any():
        raise RuntimeError("PRICE_DATE_OR_IDENTITY_BOUNDARY")
    price_path = BUNDLE / "data" / "prices.parquet"
    prices.to_parquet(price_path, index=False)
    require_physical(price_path, "trade_date")
    ledger_path = BUNDLE / "ledger.py"
    ledger_path.write_text(extract_ledger(), encoding="utf-8")
    spec = {
        "status": "PRE2026_WHITELIST_PREPARATION_ONLY", "cutoff_exclusive": "2026-01-01",
        "test_asof_utc": "2026-09-25T15:34:48Z", "panel_rows": len(panel),
        "panel_signal_max": str(panel.signal_date.max().date()),
        "panel_label_end_max": str(panel.label_end_date_5.dropna().max().date()),
        "panel_sha256": sha(BUNDLE / "data" / "panel.parquet"),
        "risk_panel_rows": len(risk_panel),
        "risk_panel_sha256": sha(BUNDLE / "data" / "risk_panel.parquet"),
        "prices_rows": len(prices), "prices_max": str(prices.trade_date.max().date()),
        "prices_sha256": sha(price_path), "price_parts": sources,
        "calendar_sha256": sha(CALENDAR), "original_e5_sha256": EXPECTED_E5,
        "patched_ledger_sha256": sha(ledger_path),
        "source_pre2026_manifest_sha256": sha(OLD / "pre2026_manifest.json"),
    }
    (BUNDLE / "input_manifest.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: spec[k] for k in ("panel_rows", "panel_signal_max", "prices_rows", "prices_max")}, indent=2))


if __name__ == "__main__":
    main()
