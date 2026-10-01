"""Read verified, recorded A2 rankings without running acquisition or inference.

The replay projection is deliberately limited to the four authorized prediction
fields. No portfolio, outcome, return, or performance artifacts are opened.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

import pyarrow.parquet as pq

from scripts.daily_recommendation_inputs import MODEL_ID, MODEL_SHA256, REPLAY_HASHES

_REPLAY_COLUMNS = ("signal_date", "ticker", "a2_rank", "a2_prediction")
_RECALCULATED_COLUMNS = ("target_date", "security_id", "ticker", "rank", "score", "model_year", "model_sha256",
    "universe_id", "universe_quarter", "universe_effective_date", "institution_count", "source")
_COVERAGE_COLUMNS = ("target_date", "status", "eligible_count", "universe_member_count", "mapped_count",
    "excluded_count", "quarter", "effective_date", "institution_count", "model_year", "reason")
_JST = timezone(timedelta(hours=9))


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("EXPECTED_JSON_OBJECT")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _day(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("INVALID_RANKING_DATE")
    return date.fromisoformat(value).isoformat()


def _ranking(records: list[dict], *, replay: bool) -> list[dict]:
    if not isinstance(records, list) or not records:
        raise ValueError("EMPTY_OR_INVALID_RANKING")
    rows = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("INVALID_RANKING_ROW")
        raw_rank = record.get("a2_rank" if replay else "rank")
        if isinstance(raw_rank, bool):
            raise ValueError("INVALID_RANK")
        try:
            rank = int(raw_rank)
            valid_rank = float(raw_rank) == rank and rank >= 1
        except (TypeError, ValueError, OverflowError):
            valid_rank = False
        if not valid_rank:
            raise ValueError("INVALID_RANK")
        ticker = record.get("ticker")
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,31}", ticker.strip().upper()):
            raise ValueError("INVALID_TICKER")
        score = record.get("a2_prediction" if replay else "score")
        if score is not None:
            if isinstance(score, bool):
                raise ValueError("INVALID_SCORE")
            try:
                score = float(score)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("INVALID_SCORE") from exc
            if not math.isfinite(score):
                raise ValueError("INVALID_SCORE")
        security_id = None if replay else record.get("security_id")
        rows.append({"rank": rank, "ticker": ticker.strip().upper(), "score": score,
                     "source": "historical_replay" if replay else str(record.get("source") or "daily_recommendation"),
                     "security_id": str(security_id) if security_id is not None else None})
    rows.sort(key=lambda row: row["rank"])
    if [row["rank"] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("NONCONTIGUOUS_OR_DUPLICATED_RANKS")
    if len({row["ticker"] for row in rows}) != len(rows):
        raise ValueError("DUPLICATED_TICKERS")
    return rows[:40]


def _entry(day: str, rows: list[dict], source: str, report_path: str,
           generated_at: str | None = None) -> dict:
    return {"date": day, "source": source,
            "source_label": "真实每日推荐" if source == "daily_recommendation" else "已验证历史回放（预测记录）",
            "generated_at": generated_at, "model_id": MODEL_ID, "model_sha256": MODEL_SHA256,
            "rows": rows, "available_rank_count": len(rows), "report_path": report_path}


def _timestamp(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("GENERATED_TIMEZONE_REQUIRED")
    return stamp


def _count(value):
    if isinstance(value, bool):
        raise ValueError("INVALID_COVERAGE_COUNT")
    count = int(value)
    if count < 0 or float(value) != count:
        raise ValueError("INVALID_COVERAGE_COUNT")
    return count


def _read_recalculated(root: Path, today: str, issues: list[str]):
    """Read only the new prediction/coverage projections; never model binaries.

    A parsed request range suppresses older records even if its output fails
    validation. Thus a failed new result cannot silently appear as old success.
    """
    entries, coverage, scope = {}, {}, None
    pointer = root / "latest.json"
    if not pointer.is_file():
        return entries, coverage, scope
    try:
        manifest = _json(pointer)
        start, end = _day(manifest["start_date"]), _day(manifest["end_date"])
        stamp = _timestamp(manifest["generated_at"])
        if start > end or start < "2023-01-01" or end > today or stamp.astimezone(_JST).date().isoformat() > today:
            raise ValueError("RECALCULATED_DATE_RANGE_INVALID")
        scope = {"start_date": start, "end_date": end, "generated_at": str(manifest["generated_at"]),
                 "report_path": str(pointer), "status": "INVALID"}
        if (manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool)
                or manifest.get("status") not in {"READY", "PARTIAL"}
                or manifest.get("institution_policy") != "REGISTRY_EFFECTIVE_QUARTER_AND_VERIFIED_FILINGS"):
            raise ValueError("RECALCULATED_MANIFEST_CONTRACT_INVALID")
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
            raise ValueError("RECALCULATED_RUN_ID_INVALID")
        run_root = (root / "runs" / run_id).resolve()
        if not run_root.is_relative_to(root.resolve()):
            raise ValueError("RECALCULATED_RUN_PATH_OUTSIDE_ROOT")
        tables = {}
        for name, columns in (("top40", _RECALCULATED_COLUMNS), ("coverage", _COVERAGE_COLUMNS)):
            reference = manifest["outputs"][name]
            path = Path(reference["path"])
            expected = str(reference.get("sha256", ""))
            if not path.is_absolute() or path.resolve().parent != run_root or path.suffix.lower() != ".parquet":
                raise ValueError(f"RECALCULATED_OUTPUT_PATH_INVALID:{name}")
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or _sha256(path) != expected:
                raise ValueError(f"RECALCULATED_OUTPUT_HASH_MISMATCH:{name}")
            if not set(columns).issubset(pq.read_schema(path).names):
                raise ValueError(f"RECALCULATED_OUTPUT_COLUMNS_MISSING:{name}")
            tables[name] = pq.read_table(path, columns=list(columns)).to_pylist()
            if _sha256(path) != expected:
                raise ValueError(f"RECALCULATED_OUTPUT_CHANGED_DURING_READ:{name}")
        model_artifacts = manifest["models"]["artifacts"]
        groups = {}
        for row in tables["top40"]:
            groups.setdefault(_day(row["target_date"]), []).append(row)
        duplicate_days = set()
        for item in tables["coverage"]:
            day = _day(item["target_date"])
            if day in coverage:
                duplicate_days.add(day)
            coverage[day] = dict(item)
        for day in sorted(set(coverage) | set(groups)):
            if not start <= day <= end:
                coverage.pop(day, None)
                issues.append(f"逐日重算 {day}：RECALCULATED_DAY_OUTSIDE_REQUEST")
                continue
            try:
                if day in duplicate_days:
                    raise ValueError("RECALCULATED_COVERAGE_DATE_DUPLICATED")
                if day not in coverage:
                    raise ValueError("RECALCULATED_COVERAGE_DATE_MISSING")
                item = coverage[day]
                item["target_date"] = day
                if item["status"] not in {"READY", "PARTIAL", "WAITING_DATA"}:
                    raise ValueError("RECALCULATED_DAY_STATUS_INVALID")
                for key in ("eligible_count", "universe_member_count", "mapped_count", "excluded_count", "institution_count", "model_year"):
                    item[key] = _count(item[key])
                if not item["eligible_count"] <= item["mapped_count"] <= item["universe_member_count"]:
                    raise ValueError("RECALCULATED_COVERAGE_COUNTS_INCONSISTENT")
                if item["model_year"] != int(day[:4]):
                    raise ValueError("RECALCULATED_MODEL_YEAR_MISMATCH")
                if item.get("effective_date"):
                    item["effective_date"] = _day(item["effective_date"])
                    if item["effective_date"] > day:
                        raise ValueError("RECALCULATED_UNIVERSE_NOT_EFFECTIVE")
                if item["status"] == "WAITING_DATA":
                    if groups.get(day):
                        raise ValueError("RECALCULATED_WAITING_DAY_HAS_RANKS")
                    continue
                if not re.fullmatch(r"\d{4}Q[1-4]", str(item.get("quarter"))) or not item.get("effective_date") or item["institution_count"] < 1:
                    raise ValueError("RECALCULATED_UNIVERSE_METADATA_INVALID")
                year = str(item["model_year"])
                expected_model = str(model_artifacts[year]["sha256"])
                if (not re.fullmatch(r"[0-9a-f]{64}", expected_model) or year not in {"2023", "2024", "2025", "2026"}
                        or (year == "2026" and expected_model != MODEL_SHA256)
                        or (year != "2026" and expected_model == MODEL_SHA256)):
                    raise ValueError("RECALCULATED_MODEL_IDENTITY_INVALID")
                records = groups.get(day, [])
                if len(records) != min(40, item["eligible_count"]):
                    raise ValueError("RECALCULATED_TOP40_COUNT_MISMATCH")
                identities, universes = set(), set()
                for row in records:
                    if (row["score"] is None or isinstance(row["score"], bool) or not math.isfinite(float(row["score"]))
                            or _count(row["model_year"]) != int(year) or row["model_sha256"] != expected_model):
                        raise ValueError("RECALCULATED_ROW_MODEL_OR_SCORE_INVALID")
                    if (row["universe_quarter"] != item["quarter"] or _day(row["universe_effective_date"]) != item["effective_date"]
                            or _count(row["institution_count"]) != item["institution_count"]):
                        raise ValueError("RECALCULATED_ROW_UNIVERSE_MISMATCH")
                    if not str(row.get("security_id") or "").strip() or not str(row.get("universe_id") or "").strip():
                        raise ValueError("RECALCULATED_ROW_IDENTITY_MISSING")
                    identities.add(str(row["security_id"]))
                    universes.add(str(row["universe_id"]))
                if len(identities) != len(records) or len(universes) != 1:
                    raise ValueError("RECALCULATED_IDENTITY_DUPLICATE_OR_UNIVERSE_CONFLICT")
                rows = _ranking(records, replay=False)
                entries[day] = {"date": day, "source": "historical_recalculation", "source_label": "更新后逐日重算",
                    "generated_at": scope["generated_at"], "model_id": f"A2 {'年度重建' if year != '2026' else '冻结模型'} · {year}",
                    "model_sha256": expected_model, "model_identity_kind": "REBUILT_ANNUAL_MODEL" if year != "2026" else "FROZEN_FULL_PRE2026_MODEL",
                    "model_note": "使用该年度固定模型重新计算；原有 OOF 记录未作为此次重算结果。" if year != "2026" else "使用完整 pre-2026 冻结模型重新预测；未用 2026 数据训练。",
                    "rows": rows, "available_rank_count": len(rows), "report_path": str(pointer),
                    "universe_id": next(iter(universes)), "coverage": dict(item), "run_id": run_id}
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                entries.pop(day, None)
                coverage[day] = {"target_date": day, "status": "INVALID_RESULT", "reason": str(exc)}
                issues.append(f"逐日重算 {day}：{exc}")
        scope["status"] = manifest["status"]
        scope["run_id"] = run_id
    except Exception as exc:
        entries, coverage = {}, {}
        issues.append(f"逐日重算读取失败：{type(exc).__name__}:{exc}")
    return entries, coverage, scope


def _read_pre2026(config, today: str, issues: list[str]) -> dict:
    """Reuse the DEMO freeze gates, projecting recorded yearly OOF predictions."""
    from apps.demo_console.adapters.artifact_reader import read_frozen_parquet
    from apps.demo_console.adapters.system_status_reader import read_freeze, _hash_rows, _verify_artifact_binding
    from apps.demo_console.config.demo_config import ArtifactSpec
    import pyarrow.compute as pc

    manifest = read_freeze(config)
    hashes = _hash_rows(config)
    matches = [row for row in hashes if row.get("artifact_id") == "a2_predictions"]
    if len(matches) != 1:
        raise ValueError("PRE2026_PREDICTION_BINDING_MISSING")
    row = matches[0]
    expected_path = config.ranking.path.with_name("oof_predictions.parquet")
    spec = ArtifactSpec("Frozen annual A2 OOF predictions", expected_path, row.get("sha256", ""), ("signal_date",))
    _verify_artifact_binding(hashes, spec, "a2_predictions", "A2_RESULT", "A2_oof_predictions")
    table = read_frozen_parquet(spec, _REPLAY_COLUMNS)
    # Filter the already recorded ranks; never derive ranks from predictions.
    table = table.filter(pc.less_equal(table["a2_rank"], 40))
    groups = {}
    for record in table.to_pylist():
        groups.setdefault(_day(record["signal_date"]), []).append(record)
    vintages = manifest["contracts"]["A2"].get("effective_model_vintages", [])
    output = {}
    for day, records in sorted(groups.items()):
        try:
            if day >= "2026-01-01" or day > today:
                raise ValueError("PRE2026_DATE_BOUNDARY_INVALID")
            matching = [v for v in vintages if v.get("prediction_min_date", "") <= day <= v.get("prediction_max_date", "")
                        and str(v.get("year")) == day[:4]]
            if len(matching) != 1:
                raise ValueError("PRE2026_MODEL_VINTAGE_UNBOUND")
            vintage = matching[0]
            fingerprint = vintage.get("effective_model_vintage_fingerprint", "")
            if not re.fullmatch(r"[0-9a-f]{64}", str(fingerprint)):
                raise ValueError("PRE2026_MODEL_VINTAGE_IDENTITY_INVALID")
            rows = _ranking(records, replay=True)
            for ranked in rows:
                ranked["source"] = "pre2026_oof"
            output[day] = {"date": day, "source": "pre2026_oof",
                "source_label": f"{vintage['year']} 年度冻结 OOF 预测", "generated_at": None,
                "model_id": f"A2 OOF · {vintage['year']}", "model_sha256": None,
                "model_identity_kind": "ANNUAL_OOF_VINTAGE",
                "model_vintage_fingerprint": fingerprint,
                "model_note": "当年冻结模型的原始预测；该阶段模型未保存序列化文件，与当前完整样本模型不同。",
                "rows": rows, "available_rank_count": len(rows), "report_path": str(spec.path)}
        except (TypeError, ValueError, KeyError) as exc:
            issues.append(f"年度 OOF {day}：{exc}")
    return output


def _read_replay(root: Path, expected: dict, today: str, issues: list[str]) -> dict:
    if set(expected) != set(REPLAY_HASHES):
        raise ValueError("UNSUPPORTED_REPLAY_SOURCE_IDENTITY")
    for filename, digest in expected.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)) or _sha256(root / filename) != digest:
            raise ValueError(f"REPLAY_HASH_MISMATCH:{filename}")
    contract = _json(root / "contract.json")
    if (contract.get("model_sha256") != MODEL_SHA256 or contract.get("top_n") != 20
            or contract.get("model_fit_count") != 0 or contract.get("model_selection_count") != 0
            or contract.get("parameter_search_count") != 0
            or contract.get("role") != "ALREADY_EXPOSED_DESCRIPTIVE_COVERAGE_LIMITED"):
        raise ValueError("REPLAY_MODEL_OR_ROLE_CONTRACT_MISMATCH")
    if (contract.get("source_resolution_sha256") != expected["source_resolution.json"]
            or contract.get("input_coverage_sha256") != expected["input_coverage.json"]):
        raise ValueError("REPLAY_INPUT_PROVENANCE_MISMATCH")
    parquet = root / "predictions.parquet"
    if not set(_REPLAY_COLUMNS).issubset(pq.read_schema(parquet).names):
        raise ValueError("REPLAY_REQUIRED_PREDICTION_COLUMNS_MISSING")
    # Never expand this projection to unapproved outcome or performance fields.
    records = pq.read_table(parquet, columns=list(_REPLAY_COLUMNS)).to_pylist()
    groups = {}
    for record in records:
        groups.setdefault(_day(record["signal_date"]), []).append(record)
    if not groups:
        raise ValueError("REPLAY_DATES_INVALID")
    if min(groups) != contract.get("start_date") or max(groups) != contract.get("end_date"):
        raise ValueError("REPLAY_DATE_CONTRACT_MISMATCH")
    result = {}
    for day, rows in sorted(groups.items()):
        if day > today:
            issues.append(f"历史预测 {day}：FUTURE_DATA_DATE")
            continue
        try:
            result[day] = _entry(day, _ranking(rows, replay=True), "historical_replay", str(root / "contract.json"))
        except (TypeError, ValueError) as exc:
            issues.append(f"历史预测 {day}：{exc}")
    return result


def load_period_rankings(paths=None, *, expected_replay_hashes: dict | None = None,
                         today: date | str | None = None, pre2026_config=None) -> dict:
    """Return available dates and at most 40 verified recorded ranks per date.

    Recalculated ranges suppress all older OOF/replay dates, including gaps.
    Only a strictly newer 2026 daily record can supersede a recalculation.
    Errors remain local and never initiate computation or downloads.
    """
    result = {"dates": [], "by_date": {}, "issues": [], "coverage_by_date": {}, "recalculation": None}
    issues = result["issues"]
    try:
        if paths is None:
            from scripts.common.storage_paths import resolve
            paths = resolve()
        current_day = _day(today if today is not None else datetime.now(_JST).date())
        replay_root = Path(paths.backtest_root) / "research/a2/demo_2026_calendar_replay"
        history_root = Path(paths.daily_root) / "A2_today_recommendation/history"
    except Exception as exc:
        issues.append(f"排名读取路径或日期无效：{type(exc).__name__}:{exc}")
        return result
    by_date = result["by_date"]
    if pre2026_config is not None or hasattr(paths, "results_root"):
        try:
            if pre2026_config is None:
                from apps.demo_console.config.demo_config import default_config
                pre2026_config = default_config()
            by_date.update(_read_pre2026(pre2026_config, current_day, issues))
        except Exception as exc:
            issues.append(f"年度冻结预测读取失败：{type(exc).__name__}:{exc}")
    try:
        expected = dict(REPLAY_HASHES if expected_replay_hashes is None else expected_replay_hashes)
        by_date.update(_read_replay(replay_root, expected, current_day, issues))
    except Exception as exc:
        issues.append(f"历史预测读取失败：{type(exc).__name__}:{exc}")
    rebuilt, coverage, scope = _read_recalculated(Path(paths.daily_root) / "A2_historical_top40", current_day, issues)
    result["recalculation"] = scope
    if scope:
        for day in list(by_date):
            if scope["start_date"] <= day <= scope["end_date"]:
                by_date.pop(day)
                coverage.setdefault(day, {"target_date": day, "status": "MISSING_RECALCULATED_DATE",
                    "reason": "本次重算未提供通过校验的该日记录，不使用旧排名填补。"})
        by_date.update(rebuilt)
    result["coverage_by_date"] = coverage
    try:
        if not history_root.is_dir():
            issues.append("每日推荐历史目录不存在")
            daily_files = []
        else:
            daily_files = sorted(history_root.glob("*.json"))
    except OSError as exc:
        issues.append(f"每日推荐历史目录读取失败：{type(exc).__name__}:{exc}")
        daily_files = []
    latest = {}
    for path in daily_files:
        try:
            payload = _json(path)
            if payload.get("status") != "READY":
                continue
            if payload.get("model_id") != MODEL_ID or payload.get("model_sha256") != MODEL_SHA256:
                raise ValueError("DAILY_HISTORY_MODEL_MISMATCH")
            if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("input_manifest_sha256", ""))) or not payload.get("run_id"):
                raise ValueError("DAILY_HISTORY_INPUT_IDENTITY_MISSING")
            day = _day(payload.get("data_date"))
            if day < "2026-01-01":
                raise ValueError("CURRENT_MODEL_DAILY_CANNOT_REPLACE_ANNUAL_OOF")
            if day > current_day:
                raise ValueError("FUTURE_DATA_DATE")
            stamp = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("DAILY_HISTORY_GENERATED_TIMEZONE_REQUIRED")
            if scope and scope["start_date"] <= day <= scope["end_date"] and stamp <= _timestamp(scope["generated_at"]):
                continue
            # Older producers may only persist their displayed rows.
            rows = _ranking(payload.get("ranked_rows", payload.get("rows")), replay=False)
            if day not in latest or stamp > latest[day]:
                latest[day] = stamp
                by_date[day] = _entry(day, rows, "daily_recommendation",
                                      str(payload.get("report_path") or path), str(payload["generated_at"]))
                universe, counts = payload.get("universe") or {}, payload.get("coverage") or {}
                partial = (counts.get("status") == "PARTIAL" or (counts.get("excluded_count") or 0) > 0
                           or universe.get("coverage_status") == "PARTIAL_IDENTITY_COVERAGE")
                daily_coverage = {"target_date": day, "status": "PARTIAL" if partial else "READY", "quarter": universe.get("quarter"),
                    "effective_date": universe.get("effective_date"), "institution_count": universe.get("institution_count", universe.get("registry", {}).get("manager_count")),
                    "universe_member_count": universe.get("universe_member_count"), "mapped_count": counts.get("mapped_count"),
                    "eligible_count": counts.get("eligible_count"), "excluded_count": counts.get("excluded_count"),
                    "model_year": 2026, "reason": str(counts.get("reason") or ("存在行情、特征或证券身份缺口。" if partial else ""))}
                by_date[day]["coverage"] = daily_coverage
                if day in coverage:
                    coverage[day] = daily_coverage
        except Exception as exc:
            issues.append(f"每日推荐 {path.name}：{type(exc).__name__}:{exc}")
    result["dates"] = sorted(by_date)
    return result
