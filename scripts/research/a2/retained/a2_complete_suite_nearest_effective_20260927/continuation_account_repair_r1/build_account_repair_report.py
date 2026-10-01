"""Summarize completed, evidence-gated frozen-account repair versions.

Replay directories are supplied in evidence-version order.  A later complete
directory replaces only paths it actually contains; no path is chosen by PnL.
This script reads saved ledgers and receipts and never runs a model or replay.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
QUEUE = HERE / "queue"
PROOF = HERE / "proof"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def split_ids(value: str | None):
    return set(filter(None, (value or "").split("|")))


def compact_needs(needs):
    return "; ".join(
        f"{ticker} {date} {','.join(sorted(fields))}"
        for (ticker, date), fields in sorted(needs.items(), key=lambda item: (item[0][1], item[0][0]))
    )


def money(value):
    return "—" if value is None or value == "" else f"{float(value):,.2f}"


def esc(value):
    return str(value).replace("|", "/").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", action="append", required=True, type=Path,
                        help="complete replay directory, oldest evidence version first")
    parser.add_argument("--final", action="store_true", help="require all 27 affected paths")
    args = parser.parse_args()

    # Completed version receipts are authoritative; a partial PROGRESS file is not.
    selected = {}
    receipts = []
    approval_receipts = {}
    for directory in args.replay_dir:
        directory = directory.resolve()
        complete_path = directory / "COMPLETE.json"
        if not complete_path.is_file():
            raise SystemExit(f"incomplete replay directory: {directory}")
        complete = read_json(complete_path)
        if complete.get("fit_guard_attempts") != 0 or complete.get("formal_full_pool_result") is not False:
            raise SystemExit(f"unexpected fit/formal status: {complete_path}")
        if not (directory / "SOURCE_HASHES.json").is_file():
            raise SystemExit(f"missing source seal: {directory}")
        progress = {row["run_id"]: row for row in read_csv(directory / "PATH_PROGRESS.csv")}
        fills = defaultdict(list)
        for row in read_csv(directory / "FIRST_BLOCK_ACTUAL_FILL.csv"):
            fills[row["run_id"]].append(row)
        for item in complete["paths"]:
            run_id = item["run_id"]
            if run_id not in progress:
                raise SystemExit(f"missing path summary: {directory} {run_id}")
            checkpoint = read_json(directory / run_id / "CHECKPOINT.json")
            if checkpoint["run_id"] != run_id or checkpoint["certified_through"] != item["certified_through"]:
                raise SystemExit(f"checkpoint mismatch: {directory} {run_id}")
            if checkpoint["new_predictor_fit_attempts"] or checkpoint["new_preprocessor_fit_attempts"]:
                raise SystemExit(f"nonzero fit in checkpoint: {directory} {run_id}")
            if item["status"] not in {"paused_before_uncertified_input", "certified_to_terminal"}:
                raise SystemExit(f"unknown path status: {directory} {run_id}")
            approval = checkpoint["input_approval_ledger"]
            if not approval:
                raise SystemExit(f"missing approval ledger: {directory} {run_id}")
            if directory in approval_receipts and approval_receipts[directory] != approval:
                raise SystemExit(f"approval ledger differs inside version: {directory}")
            approval_receipts[directory] = approval
            selected[run_id] = (directory, item, checkpoint, progress[run_id], fills[run_id])
        receipts.append((directory, complete, digest(complete_path)))

    initial = read_csv(QUEUE / "INITIAL_HELD_INPUT_QUEUE.csv")
    blocked = read_csv(QUEUE / "KNOWN_BLOCKED_BUY_DEMAND.csv")
    old_first = read_csv(QUEUE / "PATH_FIRST_INPUT_BLOCK.csv")
    affected = {row["run_id"] for row in old_first if row["status"] != "NO_OLD_MISSING_OPEN_OR_HELD_VALUATION"}
    unaffected = sorted({row["run_id"] for row in old_first} - affected)
    if len(affected) != 27 or len(unaffected) != 15:
        raise SystemExit("old 27/15 path partition changed")
    if not set(selected).issubset(affected):
        raise SystemExit("replay includes path outside old affected set")
    if args.final and set(selected) != affected:
        raise SystemExit(f"final needs 27 affected paths; got {len(selected)}")

    # Historical first needs stay visible, while only repaired-account next inputs
    # carry current_required=true.  Exact ticker/date/field is the grouping key.
    merged = defaultdict(lambda: {"origins": set(), "historical_paths": set(),
                                  "current_paths": set(), "purposes": set(),
                                  "signal_dates": set(), "sources": set(), "versions": set()})

    def add(ticker, date, field, origin, paths, purpose, source, version="", signal="", current=False):
        if not ticker or not date or not field:
            return
        row = merged[ticker, date, field]
        row["origins"].add(origin)
        row["current_paths" if current else "historical_paths"].update(paths)
        row["purposes"].add(purpose)
        row["sources"].add(source)
        if version:
            row["versions"].add(version)
        if signal:
            row["signal_dates"].add(signal)

    for row in initial:
        add(row["ticker"], row["first_held_need_date"], "close", "old_held_first_valuation",
            split_ids(row["old_run_ids"]), "old_actual_holding_close_valuation",
            "queue/INITIAL_HELD_INPUT_QUEUE.csv")
        if row["first_need"] == "pending_open_execution_if_order_then_close_valuation":
            add(row["ticker"], row["first_held_need_date"], "open", "old_held_first_conditional_open",
                split_ids(row["old_run_ids"]), "old_pending_execution_or_pretrade_nav_conditional",
                "queue/INITIAL_HELD_INPUT_QUEUE.csv")
    for row in blocked:
        add(row["ticker"], row["execution_date"], "open", "old_blocked_buy",
            split_ids(row["old_blocked_buy_run_ids"]), "old_requested_buy_execution",
            "queue/KNOWN_BLOCKED_BUY_DEMAND.csv", signal=row["signal_date"])
    for row in old_first:
        if row["first_old_input_block_kind"] in {"missing_open_buy", "missing_open_sell"}:
            for ticker in split_ids(row["first_old_input_block_tickers"]):
                add(ticker, row["first_old_input_block_date"], "open", "old_first_missing_open",
                    {row["run_id"]}, row["first_old_input_block_kind"],
                    "queue/PATH_FIRST_INPUT_BLOCK.csv")

    actual_consumed = defaultdict(set)
    consumed_evidence = defaultdict(set)
    consumed_by_version = defaultdict(set)
    for run_id, (directory, item, checkpoint, progress, fills) in selected.items():
        version = directory.name
        for need in item["next_required_inputs"]:
            add(need["ticker"], need["date"], need["field"], "repaired_account_next_input",
                {run_id}, need["purpose"], f"{version}/{run_id}/CHECKPOINT.json",
                version=version, signal=need.get("pending_signal_date", ""), current=True)
        consumed_path = directory / run_id / "CONSUMED_APPROVALS.csv"
        if consumed_path.is_file():
            for field in read_csv(consumed_path):
                key = field["ticker"], field["trade_date"], field["field"]
                actual_consumed[key].add(run_id)
                consumed_evidence[key].add(field["evidence_id"])
                consumed_by_version[version].add(key)

    for key, paths in actual_consumed.items():
        row = merged[key]
        row["origins"].add("actually_consumed_approved_field")
        row["purposes"].add("certified_repaired_account_consumption")
        for run_id in paths:
            row["versions"].add(selected[run_id][0].name)
            row["sources"].add(f"{selected[run_id][0].name}/{run_id}/CONSUMED_APPROVALS.csv")

    current_price_days = {(ticker, date) for (ticker, date, _), value in merged.items() if value["current_paths"]}
    price_flags = {}
    if current_price_days:
        columns = ["ticker", "trade_date", "open", "close", "price_quality_warning",
                   "unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump"]
        prices = pd.read_parquet(ROOT / "data/test_prices.parquet", columns=columns)
        prices = prices.loc[prices.ticker.isin({ticker for ticker, _ in current_price_days})]
        for row in prices.itertuples(index=False):
            key = str(row.ticker), pd.Timestamp(row.trade_date).date().isoformat()
            if key in current_price_days:
                price_flags[key] = row
        del prices

    def frozen_field_status(ticker, date, field):
        row = price_flags.get((ticker, date))
        if row is None:
            return "NO_FROZEN_SAME_SOURCE_PRICE_ROW"
        value = getattr(row, field)
        if pd.isna(value) or float(value) <= 0:
            return "NO_POSITIVE_FROZEN_PRICE_FIELD"
        flags = [name for name in ("unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump")
                 if bool(getattr(row, name))]
        if flags:
            return "FROZEN_FIELD_PRESENT_BUT_" + "+".join(flags).upper()
        if bool(row.price_quality_warning):
            return "FROZEN_FIELD_PRESENT_BUT_OTHER_QUALITY_WARNING"
        return "FROZEN_FIELD_PRESENT_REPLAY_REASON_REQUIRES_REVIEW"

    queue_path = HERE / "DYNAMIC_NEXT_INPUT_QUEUE.csv"
    queue_tmp = queue_path.with_suffix(".csv.tmp")
    with queue_tmp.open("w", newline="", encoding="utf-8-sig") as handle:
        columns = ["ticker", "date", "field", "current_repaired_account_need", "historical_initial_or_blocked_need",
                   "demand_origins", "historical_run_ids", "current_run_ids", "purposes",
                   "pending_signal_dates", "replay_input_versions", "actually_consumed_by_run_ids",
                   "consumed_evidence_ids", "frozen_price_field_status", "specific_evidence_gap", "source_files"]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for key, value in sorted(merged.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
            ticker, date, field = key
            writer.writerow({"ticker": ticker, "date": date, "field": field,
                             "current_repaired_account_need": bool(value["current_paths"]),
                             "historical_initial_or_blocked_need": bool(value["historical_paths"]),
                             "demand_origins": "|".join(sorted(value["origins"])),
                             "historical_run_ids": "|".join(sorted(value["historical_paths"])),
                             "current_run_ids": "|".join(sorted(value["current_paths"])),
                             "purposes": "|".join(sorted(value["purposes"])),
                             "pending_signal_dates": "|".join(sorted(value["signal_dates"])),
                             "replay_input_versions": "|".join(sorted(value["versions"])),
                             "actually_consumed_by_run_ids": "|".join(sorted(actual_consumed.get(key, set()))),
                             "consumed_evidence_ids": "|".join(sorted(consumed_evidence.get(key, set()))),
                             "frozen_price_field_status": frozen_field_status(ticker, date, field)
                             if value["current_paths"] else "",
                             "specific_evidence_gap": (
                                 "CORNING_EX_DATE_2026-02-26_VS_CONSUMED_ADJUSTMENT_2026-02-27_REQUIRES_VENDOR_OR_EXCHANGE_SOURCE"
                                 if ticker == "GLW" and date == "2026-02-27" else
                                 "EXAS_MERGER_ENTITLEMENT_UNIT_MAPPING_AND_CASH_AVAILABILITY_CLOCK"
                                 if ticker == "EXAS" else
                                 "DTE_IDENTITY_CONFIRMED_EVENT_VERSION_OR_ACTUAL_RAW_ROW_REQUIRED"
                                 if ticker == "DTP" else
                                 frozen_field_status(ticker, date, field)
                                 if value["current_paths"] else ""),
                             "source_files": "|".join(sorted(value["sources"]))})

    # Report only certified prefixes.  Old NAV after the first bad input is an
    # indicative state number, not a performance comparator.
    path_rows, fill_rows = [], []
    for run_id in sorted(selected):
        directory, item, checkpoint, progress, fills = selected[run_id]
        needs = defaultdict(set)
        for need in item["next_required_inputs"]:
            needs[need["ticker"], need["date"]].add(need["field"])
        first_fills = "; ".join(
            f"{f['ticker']} {f['new_actual_sides'] or '无成交'}"
            + (f" {money(f.get('new_any_side_trade_notional') or f['new_trade_notional'])}"
               if (f.get("new_any_side_trade_notional") or f["new_trade_notional"]) else "")
            for f in fills
        ) or "旧首阻断日无同证券已存缺开盘诊断"
        if not item["account_advanced_beyond_old_bad"]:
            first_fills = "尚未消费旧首阻断日"
        path_rows.append(
            f"| {run_id} | {directory.name} | {item['historical_first_bad']} | "
            f"{item['certified_through'] or '无新增核证日'} | {compact_needs(needs) or '终止估值日'} | "
            f"{item['approved_fields_consumed_in_certified_prefix']} | {esc(first_fills)} |"
        )
        if progress["first_account_change_date"]:
            fill_rows.append((run_id, progress["first_account_change_date"],
                              progress["old_first_day_cash"], progress["new_first_day_cash"],
                              progress["old_first_day_valuation_status"], progress["new_first_day_valuation_status"],
                              first_fills))

    current_keys = [key for key, value in merged.items() if value["current_paths"]]
    consumed_ids = sorted(actual_consumed)
    versions = ", ".join(f"`{d.name}`（{len(c['paths'])} 路径，COMPLETE SHA-256 `{h}`）" for d, c, h in receipts)
    version_names = [d.name for d, _, _ in receipts]
    selected_by_version = defaultdict(int)
    for directory, *_ in selected.values():
        selected_by_version[directory.name] += 1
    consumed_version_text = "；".join(f"`{name}` 当前选定 {selected_by_version[name]} 路径、实耗去重 {len(consumed_by_version[name])} 字段"
                                     for name in version_names)
    advanced_count = sum(bool(item["account_advanced_beyond_old_bad"]) for _, item, *_ in selected.values())
    terminal_count = sum(item["status"] == "certified_to_terminal" for _, item, *_ in selected.values())
    terminal_ids = sorted(run_id for run_id, (_, item, *_rest) in selected.items()
                          if item["status"] == "certified_to_terminal")
    source_manifests = [(directory.name, read_json(directory / "SOURCE_HASHES.json"))
                        for directory, _, _ in receipts]
    source_counts = [len(manifest["frozen_source_hashes"]) for _, manifest in source_manifests]
    source_count_text = f"每版 {source_counts[0]}" if len(set(source_counts)) == 1 else "各版 " + ", ".join(map(str, source_counts))
    explicitly_bound, sealed_only = [], []
    for name, manifest in source_manifests:
        bound = manifest.get("actual_run_replay_source")
        if bound is None:
            sealed_only.append(name)
            continue
        expected_engine = (ROOT / "engine.py").resolve()
        if Path(bound["path"]).resolve() != expected_engine or bound["sha256"] != digest(expected_engine):
            raise SystemExit(f"actual run_replay source binding mismatch: {name}")
        explicitly_bound.append((name, bound["sha256"]))
    cohort_note = "27/27 条受影响路径已有检查点" if set(selected) == affected else f"{len(selected)}/27 条受影响路径已有检查点；此稿未完成全部路径"

    proof_catalog = {}
    for path in sorted((HERE / "next_proof").glob("*_PROOF.json")):
        proof = read_json(path)
        intervals = [(event["ticker"], event["first"], event["last_authorized"],
                      event.get("next_unproved_event_exclusive", "")) for event in proof.get("events", [])]
        if path.name == "SLMT_SPLIT_PROOF.json":
            intervals.append(("SLMT", proof["first_authorized"], proof["last_authorized"], ""))
        if intervals:
            proof_catalog[path.name] = intervals

    version_inputs = []
    previous_values = {}
    used_proofs = set()
    for directory, _, _ in receipts:
        approval = approval_receipts[directory]
        approval_path = Path(approval["path"])
        if not approval_path.is_absolute():
            approval_path = ROOT / approval_path
        if digest(approval_path) != approval["sha256"]:
            raise SystemExit(f"approval hash mismatch: {approval_path}")
        values = {}
        for row in read_csv(approval_path):
            for field in ("open", "close"):
                if row[f"{field}_authorized"].lower() == "true":
                    key = row["ticker"], row["trade_date"], field
                    if key in values:
                        raise SystemExit(f"duplicate approved field: {approval_path} {key}")
                    values[key] = row[field]
        added = set(values) - set(previous_values)
        removed = set(previous_values) - set(values)
        common = set(values) & set(previous_values)
        text_changes = sum(values[key] != previous_values[key] for key in common)
        max_abs_change = max((abs(float(values[key]) - float(previous_values[key])) for key in common), default=0.0)
        changed = sum(abs(float(values[key]) - float(previous_values[key])) > 1e-9 for key in common)
        proofs = set()
        unmatched = set()
        if previous_values:
            for ticker, date, field in added:
                matches = [name for name, intervals in proof_catalog.items()
                           if any(ticker == t and start <= date <= end for t, start, end, _ in intervals)]
                if matches:
                    proofs.update(matches)
                else:
                    unmatched.add((ticker, date))
        used_proofs.update(proofs)
        version_inputs.append({"name": directory.name, "path": approval_path, "sha256": approval["sha256"],
                               "authorized_dates": len({(t, d) for t, d, _ in values}),
                               "added_dates": len({(t, d) for t, d, _ in added}),
                               "added_fields": len(added), "removed_fields": len(removed),
                               "retained_numeric_changes": changed, "retained_text_changes": text_changes,
                               "max_abs_retained_csv_change": max_abs_change, "proofs": sorted(proofs),
                               "unmatched_new_dates": len(unmatched)})
        previous_values = values

    input_rows = ["| 账户输入版 | 白名单证券日 | 比上个回放版新增证券日 / 字段 | 保留字段数值变化 >1e-9 | 当前选定路径 / 实耗去重字段 | 新证据收据 |",
                  "| --- | ---: | ---: | ---: | ---: | --- |"]
    for item in version_inputs:
        input_rows.append(f"| `{item['name']}` | {item['authorized_dates']} | "
                          f"{item['added_dates']} / {item['added_fields']} | {item['retained_numeric_changes']} | "
                          f"{selected_by_version[item['name']]} / {len(consumed_by_version[item['name']])} | "
                          f"{', '.join('`next_proof/' + name + '`' for name in item['proofs']) or '`proof/PROOF.md` + FLYX 单日证明'} |")
    input_issue_lines = [f"`{item['name']}` 相对前版移除 {item['removed_fields']} 字段、未映射新证明 {item['unmatched_new_dates']} 证券日"
                         for item in version_inputs if item["removed_fields"] or item["unmatched_new_dates"]]
    csv_rounding_lines = [f"`{item['name']}` 与前版有 {item['retained_text_changes']} 个保留字段的 CSV 末位文本差异（最大绝对差 {item['max_abs_retained_csv_change']:.3g}）"
                          for item in version_inputs if item["retained_text_changes"]]

    proof_boundary_lines = []
    for name in sorted(used_proofs):
        detail = "；".join(f"{ticker} {start}–{end}" + (f"，下一未证 {next_date}" if next_date else "")
                          for ticker, start, end, next_date in proof_catalog[name])
        proof_boundary_lines.append(f"- `next_proof/{name}`：{detail}。")
    unused_inputs = []
    for input_path in sorted((HERE / "replay/inputs").glob("APPROVED_PRICE_FIELDS_V5*.csv")):
        if not any(f"_{input_path.stem.split('_')[-1].lower()}_" in name for name in version_names):
            unused_inputs.append(f"`replay/inputs/{input_path.name}` {len(read_csv(input_path))} 证券日")
    unused_input_note = ("、".join(unused_inputs) + " 均只是保存的中间输入版，无同名账户路径；"
                         "它们的许可字段仅在后续完成回放的版次按真实消费入账。") if unused_inputs else ""

    slmt_sequence_note = ""
    q90 = selected.get("joint_q90_10bps")
    if q90 and "_v6_" in q90[0].name and q90[1]["certified_through"] >= "2026-05-15":
        path = q90[0] / "joint_q90_10bps"
        trades = pd.read_parquet(path / "trades.parquet", columns=["execution_date", "ticker", "side", "action", "notional"])
        positions = pd.read_parquet(path / "positions.parquet", columns=["date", "ticker"])
        slmt = trades.loc[trades.ticker.eq("SLMT") & trades.execution_date.isin(
            [pd.Timestamp("2026-05-14"), pd.Timestamp("2026-05-15")])]
        buy = slmt.loc[slmt.execution_date.eq(pd.Timestamp("2026-05-14")) & slmt.side.eq("BUY"), "notional"].sum()
        sell = slmt.loc[slmt.execution_date.eq(pd.Timestamp("2026-05-15")) & slmt.side.eq("SELL"), "notional"].sum()
        no_slmt_after_exit = not positions.loc[positions.date.eq(pd.Timestamp("2026-05-15")) & positions.ticker.eq("SLMT")].shape[0]
        if buy > 0 and sell > 0 and no_slmt_after_exit:
            slmt_sequence_note = (f"Q90 10bp 的冻结重推在 05-14 实际买入/增加 SLMT 指数坐标名义金额 {money(buy)}，"
                                  f"05-15 卖出/退出 {money(sell)}，当日收盘已无 SLMT 持仓；"
                                  f"对应检查点连续核证至 {q90[1]['certified_through']}，下一输入 "
                                  f"{q90[1]['next_required_inputs'][0]['ticker']} {q90[1]['next_date']}。"
                                  "这证明修复后的真实持仓不要求旧错误账本的 SLMT 全部价格后缀；金额属于原指数单位会计，不是原股数结算。")

    lines = [
        "# R6 冻结账户修复：证据消费与连续可核证前缀",
        "",
        f"**状态：{'交付版' if args.final else '工作稿'}。** {cohort_note}。本次是看过 2026 结果后的回顾性输入修复，不是新的盲测，也不构成完整 13F 池收益结论。",
        "",
        "## 实际完成",
        "",
        "- 联合分支仍使用原 R6 的 61,963 条核证候选日，47,701 条未知未改；原四冻结评分模型的全池正式测试仍属独立待完成事项。模型、已拟合预处理器、成本、1% ADV、2026-09-22 末信号与 2026-09-24 终止估值日均未改变。",
        f"- 输入版本依次为：{versions}。每版保留自己的白名单、价格字段差异和源哈希；晚版仅替换同一路径的修复检查点。未到终点的路径在首个未证输入之前暂停，保存原引擎的逐日现金、持仓、成交、决策和诊断账。",
        f"- 当前选定的 {len(selected)} 路径，实际消费 **{len(consumed_ids)} 个唯一证券×日期×开盘/收盘字段**（跨路径重复消费不重复计）；具体路径消费见各路径 `CONSUMED_APPROVALS.csv`。证据许可总数不是实际成交或实际持仓需求数。",
        f"- 当前有 **{advanced_count} 条路径**连续核证地越过旧首阻断，**{terminal_count} 条**核证至 09-24 终止估值；其余在下一项未证输入前暂停。按当前选定路径及输入版计：{consumed_version_text}。跨版本重复消费在上行总体数中只算一次。",
        f"- 到终点路径：{', '.join('`' + run_id + '`' for run_id in terminal_ids) or '无'}。它们只说明 R6 固定子池中的账户连续核证，不能当作完整 13F 股票池的正式测试收益。",
        f"- 源封印{source_count_text} 个冻结来源哈希、3 个成本情景封印；所有已选路径新增预测器拟合 **0**、预处理拟合 **0**，回放完成收据 `fit_guard_attempts=0`。旧账本及冻结工件未覆盖。",
        "- 实际执行函数绑定：" + ("；".join(f"`{name}/SOURCE_HASHES.json` 记录 `run_replay.__code__.co_filename=ROOT/engine.py`，现场 SHA-256 `{sha}`"
                                      for name, sha in explicitly_bound) or "本次无显式绑定收据")
        + ("。`" + "`、`".join(sealed_only) + "` 仅有源哈希/成本封印，未留显式执行函数绑定断言；不得追溯声称这些早期回放已有该检查。" if sealed_only else "。"),
        "- 账户从原初始化状态调用实际 `engine.run_replay`，每次由冻结策略重算目标；检查点以确定性重放恢复，未把旧目标复制成新订单。旧零目标的动作理由原来未落盘，仍标未证。获准字段只恢复本批原同源价格行；缺行或未证事件不会被陈旧价、零价或现金替代。",
        "",
        "## 已核证开盘、收盘输入与账户变化",
        "",
        "`proof/APPROVED_PRICE_FIELDS_V2.csv` 起始许可 R7 首现金事件 811 个精确证券日及 FLYX 01-08，共 812 日的 open/close。五组后续证明及 GLW 冲突见 `next_proof/NEXT_PROOF_REPORT.md`、`next_proof/GLW_BLOCKER.md`。这只是账户价格字段证明，未将 R7 候选池并入 R6。",
        f"后续完成的账户输入版累计新增 {sum(item['added_dates'] for item in version_inputs[1:])} 个精确证券日；当前最后一版白名单 {version_inputs[-1]['authorized_dates']} 日。新增键按证券日与 V2 无重复，发行人和同源 Raw 证明索引见 `next_proof/NEXT_PROOF_REPORT.md`。",
        "",
        *input_rows,
        "",
    ]
    if unused_input_note:
        lines.append(unused_input_note)
    if input_issue_lines:
        lines.append("输入版差异待核：" + "；".join(input_issue_lines) + "。")
    if csv_rounding_lines:
        lines.append("保留字段的文本精度差异：" + "；".join(csv_rounding_lines)
                     + "。原回放适配器以冻结 `data/test_prices.parquet` 的数值填入账户，白名单 CSV 仅作不超过 1e-9 的一致性检查。")
    if any("_v4_" in name for name in version_names):
        lines.append("V4 对保留行的证据标签更正另见 `replay/inputs/APPROVED_PRICE_FIELDS_V4_LABEL_CORRECTION.json`；上表按账户实际价格字段数值核对。")
    lines += [
        "",
        *proof_boundary_lines,
        "- SLMT 仅核证原价格指数单位账户字段；1:10 真实股类换股中的碎股与现金替代结算未核证，不由此声称真实股东收益。",
        "- 上述价格仍属原调整指数坐标，不是股东总收益。独立历史供应商实际接收时刻未证，发行人公告只约束事件公开日，均按保存证明的适用范围使用。",
        "- 实际被各路径消费的字段见上面的唯一计数和逐路径消费账。下表仅记录旧首阻断处已发生的账户变化；旧 NAV 自首个坏输入后是示意值，不能据其差额计算收益。",
        "",
        "| 路径 | 首次账户改变日 | 首坏日旧现金 | 首坏日新现金 | 旧/新估值状态 | 首旧阻断证券实际成交 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for run_id, changed, old_cash, new_cash, old_status, new_status, first_fills in fill_rows:
        lines.append(f"| {run_id} | {changed} | {money(old_cash)} | {money(new_cash)} | {old_status}/{new_status} | {esc(first_fills)} |")
    if not fill_rows:
        lines.append("| — | — | — | — | — | 尚无可核证账户变化 |")
    if slmt_sequence_note:
        lines += ["", slmt_sequence_note]
    lines += [
        "",
        "## 各路径连续可核证位置和下一项",
        "",
        "`open` 可用于实际执行或盘前权益；`close` 用于真实持仓当日估值。下一项同时出现两字段时须分别补证。以下日期均为前缀终点，**不得当成完整窗口收益**。",
        "",
        "| 路径 | 输入版 | 原首坏日 | 连续核证至 | 下一证券、日期、字段 | 实耗获准字段数 | 原首阻断同证券新成交 |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
        *path_rows,
        "",
        "## 动态补证队列与仍未解决的输入",
        "",
        f"`DYNAMIC_NEXT_INPUT_QUEUE.csv` 合并旧实际持仓首需求（含条件开盘需求）、旧受阻买入、旧首缺开盘、已消费获准字段与修复路径下一需求，按证券×日期×字段去重，保留全部路径和来源。其 `current_repaired_account_need=true` 的 **{len(current_keys)} 个字段键**才是当前检查点的直接下一输入；历史/条件需求不自动成为修复后的直接需求，也未预先要求补齐旧后缀。",
        "HGB baseline 三档成本的下一项是 **GLW 2026-02-27 open/close**。Corning 官方材料所列 Ex-Date 为 02-26，而原消费事件及 Raw 调整从 02-27 起，存在具体日期冲突；需原供应商事件原件或交易所通知裁定，不能当普通缺价或直接放行。见 `next_proof/GLW_BLOCKER.md`。",
        "EXAS 仍需按并购后的权益转换、指数单位映射及可用结算时钟核算，不能填零或假设已现金清仓；DTP 已按 CUSIP 对应 DTE 身份，03-16 事件版及若新账户实际走到 09-23/09-24 的同源价格缺行仍须分别证明。二者旧需求保留在历史队列；是否进入修复后的直接下一队列，以真实新持仓和订单为准。",
        "",
        "旧 15 条无这两类输入阻断路径保持原状态：" + "、".join(unaffected) + "。它们没有因本次修复升级为完整池正式测试。",
        "",
        "## 复核",
        "",
        "- 输入证据：`proof/PROOF.md`、各版白名单和所用 `next_proof` 逐事件收据；各路径 `CHECKPOINT.json` 的 `input_approval_ledger` 固定实际消费的白名单哈希。",
        "- 原队列：`queue/QUEUE.md`、`queue/PATH_FIRST_INPUT_BLOCK.csv`；续接输出：各完成目录的 `COMPLETE.json`、`SOURCE_HASHES.json`、`PRICE_FIELD_DIFF.csv`、`PATH_PROGRESS.csv`、`FIRST_BLOCK_ACTUAL_FILL.csv`、逐路径 `CHECKPOINT.json` 与五种账本。",
        "- `ACCOUNT_REPAIR_REPORT_RECEIPT.json` 固定本报告、动态队列、生成脚本哈希和逐路径最终输入版；`DYNAMIC_NEXT_INPUT_QUEUE.csv` 可过滤 `current_repaired_account_need=true` 查看真正下一项。",
        "- 本报告及动态队列可用 `python continuation_account_repair_r1/build_account_repair_report.py "
        + " ".join(f"--replay-dir continuation_account_repair_r1/replay/{d.name}" for d, _, _ in receipts)
        + (" --final" if args.final else "") + "` 复算；脚本只读上游，不调用预测或会计。",
        "",
    ]
    report_path = HERE / "ACCOUNT_REPAIR_REPORT.md"
    report_tmp = report_path.with_suffix(".md.tmp")
    report_tmp.write_text("\n".join(lines), encoding="utf-8")
    queue_tmp.replace(queue_path)
    report_tmp.replace(report_path)
    receipt_path = HERE / "ACCOUNT_REPAIR_REPORT_RECEIPT.json"
    receipt_tmp = receipt_path.with_suffix(".json.tmp")
    receipt = {"status": "DELIVERY" if args.final else "DRAFT",
               "report": {"path": str(report_path), "sha256": digest(report_path)},
               "dynamic_queue": {"path": str(queue_path), "sha256": digest(queue_path)},
               "generator": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__).resolve())},
               "replay_complete": {directory.name: sha for directory, _, sha in receipts},
               "selected_path_versions": {run_id: item[0].name for run_id, item in sorted(selected.items())},
               "affected_paths": len(selected), "old_no_block_paths": len(unaffected),
               "beyond_old_first_block": advanced_count, "certified_to_terminal": terminal_count,
               "actually_consumed_unique_price_fields": len(consumed_ids),
               "current_next_unique_price_fields": len(current_keys),
               "new_predictor_fit_attempts": 0, "new_preprocessor_fit_attempts": 0}
    receipt_tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt_tmp.replace(receipt_path)
    print(json.dumps({"selected_paths": len(selected), "unchanged_old_paths": len(unaffected),
                      "current_next_field_keys": len(current_keys), "unique_consumed_fields": len(consumed_ids),
                      "report": str(report_path), "report_sha256": receipt["report"]["sha256"],
                      "queue": str(queue_path), "queue_sha256": receipt["dynamic_queue"]["sha256"],
                      "receipt": str(receipt_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
