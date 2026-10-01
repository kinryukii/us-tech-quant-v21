"""Thin frozen-score binding to the shared persistent pure-selector account."""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve
from scripts.research.a2.evaluation import continuous_research_account as engine
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition

REPO = Path(__file__).resolve().parents[4]
OLD = Path("D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work")
BASE = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1")
AUDIT_SHA = "782e592f17fff8ac9fa9b535cc6b590b59e94e3d725feaedfb7b4f50f39c471c"
PINS = {
    OLD / "selector_replay.py": "b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb",
    OLD / "replay_accounts.py": "4e32c5adc281295b57f6373a50c742a238e35fc0c6e1a2d3d8b12628ffa79402",
    OLD / "full848raw_pre2026.parquet": "20057f59e6188ac4a2d35923ec8c1689e43380aefbbc87a1a7c78312616693f8",
    OLD / "source_bound_CA_events_pre2026.parquet": "73025c4f546660951ed4dad1b931036f74f7aa53859bf326d9e710357b992b8f",
    Path(engine.__file__): "99038f036431c91b1070fe52d5bdbbd057c617356a8b839c295c6c4bf0742d00",
    REPO / "scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py": "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b",
    REPO / "scripts/v22/corporate_action_transition_r1.py": "7b9411c6d6e21ebb4738d080ded28da93d73dec36058d76d808961d22f270ddc",
}
CONFIG = dict(base_currency="USD", initial_nav=3000., initial_cash=3000., initial_holdings=[],
              fractional_shares=True, integer_share_rounding=False, cash_interest=0,
              transaction_cost_bps=0, financing=False, borrowed_cash=False, long_only=True,
              max_weight=.05, max_positions=20, max_invested=1., capacity_fraction=None)
BATCH_PATHS = 8


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def readj(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def putj(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def pre2026(path, columns, clock):
    footer = pq.ParquetFile(path)
    for field in (clock if isinstance(clock, tuple) else (clock,)):
        index = footer.schema_arrow.get_field_index(field)
        if index < 0:
            raise ValueError("BOUNDARY_COLUMN_MISSING")
        for i in range(footer.metadata.num_row_groups):
            stat = footer.metadata.row_group(i).column(index).statistics
            if stat is None or not stat.has_min_max or stat.null_count != 0 or pd.isna(stat.max) or pd.Timestamp(stat.max) >= pd.Timestamp("2026-01-01"):
                raise ValueError("PHYSICAL_PRE2026_BOUNDARY_NOT_PROVEN:" + str(path))
    return pq.read_table(path, columns=columns).to_pandas()


def adapter():
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError("FROZEN_SOURCE_OR_INPUT_CHANGED:" + str(path))
    spec = importlib.util.spec_from_file_location("v24_frozen_membership_adapter", OLD / "selector_replay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_events(ca):
    """Execute only the hash-pinned R1 event mapping statements, never its runner."""
    if sha(OLD / "replay_accounts.py") != PINS[OLD / "replay_accounts.py"]:
        raise ValueError("FROZEN_CA_SOURCE_CHANGED")
    tree = ast.parse((OLD / "replay_accounts.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    nodes = [node for node in main.body if 82 <= node.lineno <= 83]
    if len(nodes) != 5 or not isinstance(nodes[-1], ast.For):
        raise ValueError("FROZEN_CA_MAPPING_SOURCE_COORDINATES_CHANGED")
    scope = dict(ca=ca, BASE=BASE, AUDIT_SHA=AUDIT_SHA, hashlib=hashlib, json=json,
                 np=np, pd=pd, CorporateActionTransition=CorporateActionTransition)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(OLD / "replay_accounts.py"), "exec"), scope)
    return scope["events"], scope["known"], scope["unsupported"]


def score_panel(run_directory, cid):
    if Path(cid).name != cid or cid in {".", ".."}:
        raise ValueError("INVALID_CANDIDATE_ID")
    path = run_directory / "predictions" / ("scores_" + cid + "_pre2026.parquet")
    frame = pre2026(path, ["signal_date", "ticker", "security_uid", "U_t_fingerprint", "candidate_id", "score", "rank"], "signal_date")
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if (frame.signal_date.lt("2023-01-01").any() or frame.duplicated(["signal_date", "security_uid"]).any()
            or frame.duplicated(["signal_date", "ticker"]).any() or frame[["ticker", "security_uid", "U_t_fingerprint"]].isna().any().any() or not frame.candidate_id.eq(cid).all()
            or not np.isfinite(frame[["score", "rank"]].to_numpy(float)).all()
            or not frame["rank"].eq(np.floor(frame["rank"])).all()):
        raise ValueError("INVALID_FULL_COMMON_SCORE_PANEL:" + cid)
    counts = frame.groupby("signal_date").size()
    ranks = frame.groupby("signal_date")["rank"]
    if (frame.duplicated(["signal_date", "rank"]).any() or not ranks.min().eq(1).all()
            or not ranks.max().eq(counts).all() or not counts.ge(20).all()):
        raise ValueError("FULL_DAILY_RANK_PERMUTATION_REQUIRED:" + cid)
    return frame.sort_values(["signal_date", "security_uid", "ticker"]).reset_index(drop=True), sha(path)


def run(run_directory):
    directory = Path(run_directory).resolve()
    if not directory.is_relative_to(resolve(repo_root=REPO).backtest_root / "V24"):
        raise ValueError("V24_BACKTEST_DESTINATION_REQUIRED")
    cfg, design, ready = (readj(directory / n) for n in ("run_config.json", "DESIGN_FREEZE.json", "SCORE_ASSEMBLY.json"))
    if (cfg["strategy_id"] != "V24" or cfg["research_line"] != "C_SELECTOR"
            or sha(directory / "DESIGN_FREEZE.json") != readj(directory / "DESIGN_FREEZE_SHA.json")["sha256"]
            or not design["selection_rule"]["primary"] or not design["selection_rule"]["economic_gate"]):
        raise ValueError("PRIMARY_DESIGN_FREEZE_REQUIRED")
    expected = dict(initial_cash_usd=3000, top_k=20, target_weight=.05, gross=1., cash_target=0, long_only=True, margin=False,
                    fees_bps=0, cash_interest=0, fractional=True, execution="NEXT_LEGAL_SESSION_RESEARCH_RAW_OPEN", account="CONTINUOUS_2023_2025_NO_YEAR_RESET_NO_TERMINAL_LIQUIDATION")
    if any(design["controls"].get(k) != v or cfg["controls"].get(k) != v for k, v in expected.items()):
        raise ValueError("FIXED_PURE_SELECTOR_CONTROLS_CHANGED")
    candidates, failed = ready["complete_candidates"], ready["failed_or_untestable"]
    if len(set(candidates)) != len(candidates) or set(candidates) & set(failed) or set(candidates) | set(failed) != set(design["candidates"]):
        raise ValueError("EVERY_FROZEN_CANDIDATE_REQUIRES_EXPLICIT_READINESS")
    ids = [ready["raw_candidate_id"]] + sorted(candidates)
    if len(ids) > 54 or len(ids) > design["budget"]["max_full_account_paths"]:
        raise ValueError("FULL_ACCOUNT_PATH_BUDGET")
    helper = adapter()
    raw, raw_sha = score_panel(directory, ids[0])
    keys = ["signal_date", "security_uid", "ticker", "U_t_fingerprint"]
    if len(raw) != ready["common_rows"] or raw.signal_date.nunique() != ready["common_dates"] or set(raw.signal_date.dt.year) != {2023, 2024, 2025}:
        raise ValueError("COMMON_PANEL_READINESS_MISMATCH")
    membership, score_hashes = [], {ids[0]: raw_sha}
    for cid in ids:
        frame, digest = (raw, raw_sha) if cid == ids[0] else score_panel(directory, cid)
        if not frame[keys].equals(raw[keys]):
            raise ValueError("MODEL_COMMON_POOL_SHRINK_OR_CHANGE:" + cid)
        membership.append(frame.loc[frame["rank"].le(20), ["signal_date", "ticker", "rank"]].assign(path_id=cid))
        score_hashes[cid] = digest
    members = pd.concat(membership, ignore_index=True)
    calendar = pd.DatetimeIndex(sorted(raw.signal_date.unique()))
    prices = pre2026(OLD / "full848raw_pre2026.parquet", ["ticker", "trade_date", "open", "close"], "trade_date")
    prices = prices.loc[prices.trade_date.isin(calendar)].copy()
    ca = pre2026(OLD / "source_bound_CA_events_pre2026.parquet", ["code", "ticker", "event_date", "source_event_date", "factor_a", "factor_b", "share_event", "source_order"], ("event_date", "source_event_date"))
    ca = ca.loc[ca.event_date.isin(calendar)].sort_values(["code", "event_date", "source_order"], kind="stable")
    events, known, unsupported = source_events(ca)
    next_day = dict(zip(calendar[:-1], calendar[1:]))
    quoted = set(zip(prices.loc[np.isfinite(prices.open) & prices.open.gt(0), "trade_date"], prices.loc[np.isfinite(prices.open) & prices.open.gt(0), "ticker"]))
    gaps = {cid: [(str(r.signal_date.date()), str(r.ticker)) for r in members.loc[members.path_id.eq(cid)].itertuples() if r.signal_date in next_day and (next_day[r.signal_date], r.ticker) not in quoted] for cid in ids}
    active = [cid for cid in ids if not gaps[cid]]
    out = directory / "accounting"
    if out.exists() and any(out.iterdir()):
        raise ValueError("PRESERVE_EXISTING_ACCOUNT_OUTPUT")
    out.mkdir(exist_ok=True)
    groups, qualified = [], {}
    for start in range(0, len(active), BATCH_PATHS):
        batch = active[start:start + BATCH_PATHS]
        folder = out / ("batch_%03d" % (start // BATCH_PATHS)); folder.mkdir()
        writers, row_counts = {}, {}
        def callback(name, frame):
            if name not in {"daily", "positions", "fills", "orders", "execution_results"} or frame.empty:
                return
            table = pa.Table.from_pandas(frame, preserve_index=False)
            table = table.cast(pa.schema([pa.field(f.name, pa.timestamp("ns", tz=f.type.tz), nullable=f.nullable) if pa.types.is_timestamp(f.type) else f for f in table.schema]))
            if name not in writers:
                writers[name] = pq.ParquetWriter(folder / (name + ".parquet"), table.schema)
            writers[name].write_table(table)
            row_counts[name] = row_counts.get(name, 0) + len(frame)
        market = helper.make_market(engine, prices, raw[["signal_date", "ticker"]], calendar, signal_dates=calendar)
        try:
            replay = helper.replay_fixed_membership(engine, market, members.loc[members.path_id.isin(batch)], batch, account_config=CONFIG, corporate_actions=events, corporate_action_known_at=known, unsupported_events=unsupported, ledger_callback=callback)
        finally:
            for writer in writers.values():
                writer.close()
        for cid, day in replay.daily.groupby("path_id"):
            qualified[cid] = bool(day.accounting_qualified.all() and np.isfinite(day.certified_nav).all())
        np.savez_compressed(folder / "final_state_arrays.npz", **{k: v for k, v in replay.final_state.items() if isinstance(v, np.ndarray)}, tickers=market.tickers, path_ids=np.asarray(batch))
        putj(folder / "ACCOUNT_METADATA.json", replay.metadata)
        putj(folder / "PREFIX_IDENTITY.json", replay.prefix_identity)
        replay.accounting_exceptions.to_json(folder / "accounting_exceptions.json", orient="records", indent=2)
        groups.append(dict(path_ids=batch, directory=str(folder), row_counts=row_counts))
        del replay, market
    receipt = dict(status="PRE2026_ACCOUNTS_COMPLETE", annual_reset=False, terminal_liquidation=False, test2026_read=False,
                   groups=groups, last_signal_pending_without_2026_open=str(calendar[-1].date()), failed_or_untestable=failed, non_executable_price_gaps={cid: rows for cid, rows in gaps.items() if rows},
                   accounting_qualified=qualified, economic_metrics={cid: None for cid in ids if cid not in active or not qualified.get(cid, False)},
                   design_sha256=sha(directory / "DESIGN_FREEZE.json"), score_sha256=score_hashes, source_sha256={str(p): digest for p, digest in PINS.items()},
                   account_config=CONFIG, batch_paths=BATCH_PATHS, grouping="independent accounts, each replays the full continuous prefix", availability="accepted vendor effective-Open accounting assumption; not public publication certification")
    putj(out / "ACCOUNT_RECEIPT.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--run", required=True, type=Path)
    print(json.dumps(run(parser.parse_args().run), default=str))
