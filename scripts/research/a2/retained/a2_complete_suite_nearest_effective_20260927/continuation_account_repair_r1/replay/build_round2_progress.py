"""Summarize versioned frozen-account checkpoints without running the policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
TERMINAL = "2026-09-24"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, action="append", required=True,
                        help="complete version directory, in evidence order")
    parser.add_argument("--output-stem", default="ROUND2", help="new filename stem; output may not exist")
    args = parser.parse_args()
    paths_csv = PARENT / f"{args.output_stem}_LATEST_27_PATHS.csv"
    queue_csv = PARENT / f"{args.output_stem}_NEXT_INPUT_QUEUE.csv"
    report_md = PARENT / f"{args.output_stem}_ACCOUNT_PROGRESS.md"
    receipt_json = PARENT / f"{args.output_stem}_ACCOUNT_PROGRESS_RECEIPT.json"
    for out in (paths_csv, queue_csv, report_md, receipt_json):
        if out.exists():
            raise RuntimeError(f"preserve old version: {out}")

    selected = {}
    versions = []
    for directory in args.replay_dir:
        directory = directory.resolve()
        complete_path = directory / "COMPLETE.json"
        manifest = directory / "SOURCE_HASHES.json"
        complete = read_json(complete_path)
        assert complete["fit_guard_attempts"] == 0 and complete["formal_full_pool_result"] is False
        assert manifest.is_file()
        source = read_json(manifest)
        assert complete["source_hashes_checked_before_and_after"] == len(source["frozen_source_hashes"])
        assert complete["source_seals_checked_before_and_after"] == len(source["seal_files"])
        actual_source = source.get("actual_run_replay_source")
        if actual_source is not None:
            assert actual_source["sha256"] == sha(Path(actual_source["path"]))
        for item in complete["paths"]:
            run_id = item["run_id"]
            checkpoint_path = directory / run_id / "CHECKPOINT.json"
            checkpoint = read_json(checkpoint_path)
            assert checkpoint["run_id"] == run_id
            assert checkpoint["status"] == item["status"]
            assert checkpoint["certified_through"] == item["certified_through"]
            assert checkpoint["new_predictor_fit_attempts"] == 0
            assert checkpoint["new_preprocessor_fit_attempts"] == 0
            assert checkpoint["status"] in {"paused_before_uncertified_input", "certified_to_terminal"}
            if checkpoint["status"] == "certified_to_terminal":
                assert checkpoint["certified_through"] == TERMINAL and not checkpoint["next_required_inputs"]
            else:
                assert checkpoint["certified_through"] < checkpoint["next_date"] <= TERMINAL
                assert checkpoint["next_required_inputs"]
            selected[run_id] = (directory, item, checkpoint, checkpoint_path)
        versions.append({"directory": str(directory), "complete_sha256": sha(complete_path),
                         "source_manifest_sha256": sha(manifest), "paths": len(complete["paths"])})

    old = pd.read_csv(HERE / "LATEST_27_PATHS.csv", dtype=str).set_index("run_id")
    assert set(selected) == set(old.index) and len(selected) == 27
    rows = []
    queue = defaultdict(lambda: {"run_ids": set(), "purposes": set(), "signal_dates": set(), "versions": set()})
    consumed = defaultdict(set)
    for run_id, (directory, item, checkpoint, checkpoint_path) in sorted(selected.items()):
        prior = old.loc[run_id]
        rows.append({
            "run_id": run_id, "input_version": directory.name,
            "historical_first_bad": item["historical_first_bad"],
            "old_certified_through": prior.certified_through,
            "certified_through": item["certified_through"],
            "next_date": item["next_date"] or "", "status": item["status"],
            "approved_fields_consumed_in_prefix": item["approved_fields_consumed_in_certified_prefix"],
            "checkpoint_sha256": sha(checkpoint_path),
            "actual_run_replay_source_sha256": (
                read_json(directory / "SOURCE_HASHES.json").get("actual_run_replay_source") or {}
            ).get("sha256", "see_R2_runtime_binding_receipt"),
        })
        for need in checkpoint["next_required_inputs"]:
            key = (need["ticker"], need["date"], need["field"])
            q = queue[key]
            q["run_ids"].add(run_id)
            q["purposes"].add(need["purpose"])
            if need.get("pending_signal_date"):
                q["signal_dates"].add(need["pending_signal_date"])
            q["versions"].add(directory.name)
        approvals = directory / run_id / "CONSUMED_APPROVALS.csv"
        if approvals.is_file():
            for row in csv.DictReader(approvals.open(newline="", encoding="utf-8-sig")):
                consumed[(row["ticker"], row["trade_date"], row["field"])].add(run_id)

    qrows = []
    for (ticker, date, field), info in sorted(queue.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
        qrows.append({"ticker": ticker, "date": date, "field": field,
                      "run_ids": "|".join(sorted(info["run_ids"])),
                      "purposes": "|".join(sorted(info["purposes"])),
                      "pending_signal_dates": "|".join(sorted(info["signal_dates"])),
                      "input_versions": "|".join(sorted(info["versions"])),
                      "evidence_state": "GLW_EX_DATE_CONFLICT_QUARANTINED" if ticker == "GLW" and date == "2026-02-26"
                      else "AWAITING_EXACT_ACCOUNT_INPUT_PROOF"})
    write_csv(paths_csv, rows, list(rows[0]))
    write_csv(queue_csv, qrows, list(qrows[0]))

    terminal = [r for r in rows if r["status"] == "certified_to_terminal"]
    advanced = [r for r in rows if r["certified_through"] > r["old_certified_through"]]
    rolled_back = [r for r in rows if r["certified_through"] < r["old_certified_through"]]
    lines = [
        "# R6 子池冻结账户：本轮实际消费进度",
        "",
        "本报告只汇总保存的冻结账户检查点与实际消费字段；不训练、不重跑策略。原始预测、R6 候选集合、成本和固定终点保持不变；该结果不是正式全池收益比较。",
        "",
        f"27 条原受影响路径中，**{len(terminal)} 条连续核证到 {TERMINAL}**，{27-len(terminal)} 条在下一项未核证输入前暂停。相对旧进度 {len(advanced)} 条前进、{len(rolled_back)} 条因 GLW 日期冲突回退；当前实际下一输入为 **{len(qrows)} 个证券×日期×字段键**。最新路径累计实际消费许可字段去重为 **{len(consumed)} 个键**，每条路径的消费文件与检查点均保存。",
        "",
        "| 路径 | 旧连续日期 | 新连续日期 | 状态 | 下一项 | 输入版 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        run = row["run_id"]
        next_keys = sorted({f"{n['ticker']} {n['date']} {n['field']}"
                            for n in selected[run][2]["next_required_inputs"]})
        lines.append(f"| {run} | {row['old_certified_through']} | {row['certified_through']} | "
                     f"{'终点' if row['status'] == 'certified_to_terminal' else '暂停'} | "
                     f"{'; '.join(next_keys) if next_keys else '—'} | {row['input_version']} |")
    lines += [
        "", "## 边界", "",
        "GLW 02-26 除息日与原供应商 02-27 相冲突；HGB 基准三档隔离在 02-25。其余路径不会因这项冲突停摆。当前下一输入详见 `ROUND2_NEXT_INPUT_QUEUE.csv`，保留用途与受影响路径；未来价格只有被实际账户要求时才补证。",
        "",
        "价格仍是原 `PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN` 坐标，不是股东实际净收益。R6 未知候选日和原四冻结评分模型正式全池测试仍未解决。本轮所有完整回放收据与检查点的新增预测器拟合、预处理拟合均为 0。",
        "",
    ]
    report_md.write_text("\n".join(lines), encoding="utf-8")
    receipt = {"selected_paths": len(rows), "terminal_paths": len(terminal),
               "advanced_vs_old": len(advanced), "rolled_back_vs_old": len(rolled_back),
               "current_next_field_keys": len(qrows), "unique_consumed_field_keys": len(consumed),
               "new_predictor_fit_attempts": 0, "new_preprocessor_fit_attempts": 0,
               "replay_versions": versions,
               "outputs": {str(p): sha(p) for p in (paths_csv, queue_csv, report_md)},
               "generator": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).resolve())}}
    receipt_json.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("terminal_paths", "advanced_vs_old", "rolled_back_vs_old",
                                                 "current_next_field_keys", "unique_consumed_field_keys")}))


if __name__ == "__main__":
    main()
