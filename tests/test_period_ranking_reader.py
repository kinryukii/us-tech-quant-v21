"""Synthetic-file reader tests: no downloads, model calls, or outcome reads."""
from datetime import date, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq


MODULE_PATH = Path(__file__).resolve().parents[1] / "apps/demo_console/adapters/period_ranking_reader.py"
SPEC = importlib.util.spec_from_file_location("period_ranking_reader_under_test", MODULE_PATH)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PeriodRankingReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.paths = SimpleNamespace(daily_root=root / "daily", backtest_root=root / "backtests")
        self.replay = self.paths.backtest_root / "research/a2/demo_2026_calendar_replay"
        self.history = self.paths.daily_root / "A2_today_recommendation/history"
        self.replay.mkdir(parents=True)
        self.history.mkdir(parents=True)
        self.make_replay()

    def write_json(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def make_replay(self, records=None, **contract_changes):
        records = records if records is not None else [
            {"signal_date": datetime.fromisoformat(day), "ticker": f"R{i:03}",
             "a2_rank": i, "a2_prediction": i / 1000}
            for day in ("2026-01-02", "2026-01-05") for i in range(1, 43)]
        pq.write_table(pa.Table.from_pylist(records), self.replay / "predictions.parquet")
        for name in ("source_resolution.json", "input_coverage.json"):
            self.write_json(self.replay / name, {"fixture": name})
        days = sorted({r["signal_date"].date().isoformat() for r in records})
        contract = {"model_sha256": reader.MODEL_SHA256, "top_n": 20,
                    "model_fit_count": 0, "model_selection_count": 0, "parameter_search_count": 0,
                    "role": "ALREADY_EXPOSED_DESCRIPTIVE_COVERAGE_LIMITED",
                    "start_date": days[0], "end_date": days[-1],
                    "source_resolution_sha256": digest(self.replay / "source_resolution.json"),
                    "input_coverage_sha256": digest(self.replay / "input_coverage.json"), **contract_changes}
        self.write_json(self.replay / "contract.json", contract)
        self.hashes = {name: digest(self.replay / name) for name in reader.REPLAY_HASHES}

    def daily(self, name="valid.json", day="2026-01-05", count=30, **changes):
        value = {"status": "READY", "model_id": reader.MODEL_ID, "model_sha256": reader.MODEL_SHA256,
                 "input_manifest_sha256": "a" * 64, "run_id": name,
                 "data_date": day, "recommendation_date": "2026-09-23",
                 "generated_at": "2026-09-23T07:00:00+00:00", "report_path": "saved-report.json",
                 "ranked_rows": [{"rank": i, "ticker": f"D{i:03}", "score": i / 100,
                                  "source": "moomoo", "security_id": f"id{i}"} for i in range(1, count + 1)],
                 **changes}
        self.write_json(self.history / name, value)
        return value

    def load(self, **options):
        return reader.load_period_rankings(self.paths, expected_replay_hashes=self.hashes,
                                           today=options.pop("today", date(2026, 9, 23)), **options)

    def test_replay_reads_exact_authorized_projection_and_preserves_rank(self):
        with patch.object(reader.pq, "read_table", wraps=pq.read_table) as read:
            result = self.load()
        self.assertFalse(result["issues"])
        self.assertEqual(result["dates"], ["2026-01-02", "2026-01-05"])
        self.assertEqual(read.call_args.kwargs, {"columns": ["signal_date", "ticker", "a2_rank", "a2_prediction"]})
        entry = result["by_date"]["2026-01-02"]
        self.assertEqual(entry["available_rank_count"], 40)
        self.assertEqual(entry["rows"][0], {"rank": 1, "ticker": "R001", "score": 0.001,
                                          "source": "historical_replay", "security_id": None})
        self.assertEqual(entry["rows"][-1]["rank"], 40)

    def test_latest_daily_uses_data_date_and_replaces_replay_without_padding(self):
        self.daily("a-new.json", count=7, generated_at="2026-09-23T08:00:00+00:00")
        self.daily("z-old.json", count=35)
        result = self.load()
        entry = result["by_date"]["2026-01-05"]
        self.assertFalse(result["issues"])
        self.assertEqual(result["dates"], ["2026-01-02", "2026-01-05"])
        self.assertEqual(entry["source"], "daily_recommendation")
        self.assertEqual(entry["available_rank_count"], 7)
        self.assertEqual(entry["rows"][0]["security_id"], "id1")

    def test_daily_rows_fallback_supports_one_record_and_none_score(self):
        record = self.daily(count=1)
        record["rows"] = record.pop("ranked_rows")
        record["rows"][0]["score"] = None
        self.write_json(self.history / "valid.json", record)
        result = self.load()
        self.assertFalse(result["issues"])
        self.assertEqual(result["by_date"]["2026-01-05"]["available_rank_count"], 1)
        self.assertIsNone(result["by_date"]["2026-01-05"]["rows"][0]["score"])

    def test_newer_daily_preserves_partial_coverage_after_recalculation(self):
        self.recalculated()
        self.daily(generated_at="2026-09-23T08:01:00+00:00",
                   universe={"quarter": "2025Q3", "effective_date": "2025-11-21",
                             "institution_count": 25, "universe_member_count": 50},
                   coverage={"mapped_count": 45, "eligible_count": 30, "excluded_count": 20})
        result = self.load()
        entry = result["by_date"]["2026-01-05"]
        self.assertEqual(entry["source"], "daily_recommendation")
        self.assertEqual(entry["coverage"]["status"], "PARTIAL")
        self.assertEqual(entry["coverage"]["effective_date"], "2025-11-21")
        self.assertEqual(result["coverage_by_date"]["2026-01-05"], entry["coverage"])
        self.assertIn("缺口", entry["coverage"]["reason"])

    def test_bad_daily_files_do_not_block_valid_dates_or_replay(self):
        self.daily(day="2026-09-22")
        self.daily("wrong-model.json", model_sha256="0" * 64)
        self.daily("bad-manifest.json", input_manifest_sha256="bad")
        self.daily("naive-time.json", generated_at="2026-09-23T00:00:00")
        self.daily("future.json", day="2026-09-24")
        self.daily("waiting.json", status="WAITING")
        (self.history / "broken.json").write_text("{", encoding="utf-8")
        result = self.load()
        self.assertEqual(len(result["issues"]), 5)
        self.assertEqual(result["dates"], ["2026-01-02", "2026-01-05", "2026-09-22"])
        self.assertEqual(result["by_date"]["2026-01-05"]["source"], "historical_replay")

    def test_invalid_ranks_tickers_and_scores_are_rejected(self):
        bad_rows = ([{"rank": 2, "ticker": "A", "score": 1}],
                    [{"rank": 1, "ticker": "A"}, {"rank": 2, "ticker": "A"}],
                    [{"rank": 1.5, "ticker": "A"}], [{"rank": True, "ticker": "A"}],
                    [{"rank": 1, "ticker": "A", "score": float("nan")}],
                    [{"rank": 1, "ticker": "bad ticker"}])
        for rows in bad_rows:
            with self.subTest(rows=rows):
                self.daily(ranked_rows=rows)
                result = self.load()
                self.assertEqual(len(result["issues"]), 1)
                self.assertEqual(result["by_date"]["2026-01-05"]["source"], "historical_replay")

    def test_replay_hash_failure_does_not_read_parquet_or_block_daily(self):
        self.daily(day="2026-09-22")
        (self.replay / "input_coverage.json").write_text("{}", encoding="utf-8")
        with patch.object(reader.pq, "read_table") as read:
            result = self.load()
        read.assert_not_called()
        self.assertEqual(result["dates"], ["2026-09-22"])
        self.assertIn("REPLAY_HASH_MISMATCH", result["issues"][0])

    def test_contract_identity_and_provenance_gate_before_projection(self):
        changes = ({"model_sha256": "0" * 64}, {"model_fit_count": 1},
                   {"model_selection_count": 1}, {"parameter_search_count": 1},
                   {"role": "other"}, {"top_n": 40}, {"source_resolution_sha256": "0" * 64},
                   {"input_coverage_sha256": "0" * 64})
        for change in changes:
            with self.subTest(change=change):
                self.make_replay(**change)
                with patch.object(reader.pq, "read_table") as read:
                    result = self.load()
                read.assert_not_called()
                self.assertEqual(result["dates"], [])
                self.assertEqual(len(result["issues"]), 1)

    def test_missing_prediction_column_is_not_silently_substituted(self):
        self.make_replay(records=[{"signal_date": datetime(2026, 1, 2), "ticker": "A", "a2_rank": 1}])
        with patch.object(reader.pq, "read_table") as read:
            result = self.load()
        read.assert_not_called()
        self.assertIn("REPLAY_REQUIRED_PREDICTION_COLUMNS_MISSING", result["issues"][0])

    def test_replay_date_mismatch_is_rejected_and_future_dates_are_excluded(self):
        self.make_replay(end_date="2026-01-06")
        self.assertIn("REPLAY_DATE_CONTRACT_MISMATCH", self.load()["issues"][0])
        self.make_replay()
        result = self.load(today="2026-01-02")
        self.assertEqual(result["dates"], ["2026-01-02"])
        self.assertIn("FUTURE_DATA_DATE", result["issues"][0])

    def test_missing_sources_and_path_failure_are_reported_without_raising(self):
        result = reader.load_period_rankings(SimpleNamespace(daily_root=Path(self.tmp.name) / "missing",
                    backtest_root=Path(self.tmp.name) / "absent"), today="2026-09-23")
        self.assertEqual(result["dates"], [])
        self.assertEqual(len(result["issues"]), 2)
        result = reader.load_period_rankings(SimpleNamespace(), today="invalid")
        self.assertEqual(result["dates"], [])
        self.assertEqual(len(result["issues"]), 1)

    def historical_source(self, day="2023-01-03", count=42):
        from apps.demo_console.config.demo_config import ArtifactSpec
        root = Path(self.tmp.name) / "frozen/A2"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "oof_predictions.parquet"
        pq.write_table(pa.Table.from_pylist([{"signal_date": datetime.fromisoformat(day), "ticker": f"H{i:03}",
            "a2_rank": i, "a2_prediction": -i/100, "target": "FORBIDDEN_OUTCOME"} for i in range(1,count+1)]), path)
        config = SimpleNamespace(ranking=ArtifactSpec("synthetic", root/"top20_selections.parquet", "0"*64, ("signal_date",)))
        bindings = [{"artifact_id":"a2_predictions", "category":"A2_RESULT", "role":"A2_oof_predictions",
                     "immutable":"True", "absolute_path":str(path), "sha256":digest(path)}]
        manifest = {"contracts":{"A2":{"effective_model_vintages":[{"year":2023,
                    "prediction_min_date":"2023-01-03", "prediction_max_date":"2023-12-29",
                    "effective_model_vintage_fingerprint":"b"*64}]}}}
        return config, bindings, manifest

    def test_pre2026_uses_recorded_top40_and_yearly_identity_without_outcomes(self):
        from apps.demo_console.adapters import artifact_reader, system_status_reader
        config, bindings, manifest = self.historical_source()
        self.daily(day="2023-01-03")
        with patch.object(system_status_reader, "read_freeze", return_value=manifest) as freeze, \
             patch.object(system_status_reader, "_hash_rows", return_value=bindings), \
             patch.object(artifact_reader, "read_frozen_parquet", wraps=artifact_reader.read_frozen_parquet) as read:
            result = self.load(pre2026_config=config)
        freeze.assert_called_once_with(config)
        self.assertEqual(read.call_args.args[1], ("signal_date", "ticker", "a2_rank", "a2_prediction"))
        entry = result["by_date"]["2023-01-03"]
        self.assertEqual(entry["available_rank_count"], 40)
        self.assertEqual(entry["model_id"], "A2 OOF · 2023")
        self.assertIsNone(entry["model_sha256"])
        self.assertEqual(entry["model_vintage_fingerprint"], "b"*64)
        self.assertNotIn("target", entry["rows"][0])
        self.assertTrue(any("CANNOT_REPLACE_ANNUAL_OOF" in item for item in result["issues"]))

    def test_pre2026_bad_binding_and_post2025_footer_never_become_history(self):
        from apps.demo_console.adapters import artifact_reader, system_status_reader
        config, bindings, manifest = self.historical_source()
        bindings[0]["immutable"] = "False"
        with patch.object(system_status_reader, "read_freeze", return_value=manifest), \
             patch.object(system_status_reader, "_hash_rows", return_value=bindings), \
             patch.object(artifact_reader, "read_frozen_parquet") as read:
            result = self.load(pre2026_config=config)
        read.assert_not_called()
        self.assertNotIn("2023-01-03", result["dates"])
        config, bindings, manifest = self.historical_source(day="2026-01-02")
        with patch.object(system_status_reader, "read_freeze", return_value=manifest), \
             patch.object(system_status_reader, "_hash_rows", return_value=bindings):
            result = self.load(pre2026_config=config)
        self.assertTrue(any("POST2025_ARTIFACT_BLOCKED" in issue for issue in result["issues"]))

    def test_pre2026_short_native_ranking_is_not_padded(self):
        from apps.demo_console.adapters import system_status_reader
        config, bindings, manifest = self.historical_source(count=20)
        with patch.object(system_status_reader, "read_freeze", return_value=manifest), \
             patch.object(system_status_reader, "_hash_rows", return_value=bindings):
            result = self.load(pre2026_config=config)
        self.assertEqual(result["by_date"]["2023-01-03"]["available_rank_count"], 20)

    def recalculated(self, days=("2026-01-02", "2026-01-05"), *, waiting=(), omit=()):
        root = self.paths.daily_root / "A2_historical_top40"
        run = root / "runs/synthetic-recalculation"
        run.mkdir(parents=True, exist_ok=True)
        rows, coverage = [], []
        for day in days:
            year = int(day[:4])
            model_sha = reader.MODEL_SHA256 if year == 2026 else str(year % 10) * 64
            quarter = f"{year - 1}Q3"
            effective = f"{year - 1}-11-21"
            for rank in range(1, 41):
                rows.append({"target_date": day, "security_id": f"id{rank}", "ticker": f"N{rank:03}",
                    "rank": rank, "score": -rank/100, "model_year": year, "model_sha256": model_sha,
                    "universe_id": "new-quarter-pool", "universe_quarter": quarter,
                    "universe_effective_date": effective, "institution_count": 25, "source": "verified_prices",
                    "FORBIDDEN_OUTCOME": "not projected"})
            coverage.append({"target_date": day, "status": "WAITING_DATA" if day in waiting else "PARTIAL",
                "eligible_count": 0 if day in waiting else 42, "universe_member_count": 50, "mapped_count": 45,
                "excluded_count": 50 if day in waiting else 8, "quarter": quarter, "effective_date": effective,
                "institution_count": 25, "model_year": year, "reason": "PRICE_GAP"})
        table = pa.Table.from_pylist(rows)
        keep = [r for r in rows if r["target_date"] not in set(waiting) | set(omit)]
        pq.write_table(pa.Table.from_pylist(keep, schema=table.schema), run / "top40.parquet")
        pq.write_table(pa.Table.from_pylist([r for r in coverage if r["target_date"] not in omit]), run / "coverage.parquet")
        manifest = {"schema_version": 1, "status": "PARTIAL", "run_id": run.name,
            "generated_at": "2026-09-23T08:00:00+00:00", "start_date": min(days), "end_date": max(days),
            "institution_policy": "REGISTRY_EFFECTIVE_QUARTER_AND_VERIFIED_FILINGS",
            "outputs": {name: {"path": str(run / f"{name}.parquet"), "sha256": digest(run / f"{name}.parquet")}
                        for name in ("top40", "coverage")},
            "models": {"artifacts": {str(int(day[:4])): {"path": "model-is-never-opened.joblib",
                "sha256": reader.MODEL_SHA256 if day.startswith("2026") else str(int(day[:4]) % 10)*64} for day in days}}}
        self.write_json(root / "latest.json", manifest)
        return root, run, manifest

    def test_recalculation_replaces_old_replay_and_old_daily_only_newer_daily_wins(self):
        self.recalculated()
        self.daily(count=20)
        result = self.load()
        row = result["by_date"]["2026-01-05"]
        self.assertEqual(row["source"], "historical_recalculation")
        self.assertEqual(row["rows"][0]["ticker"], "N001")
        self.assertEqual(row["coverage"]["institution_count"], 25)
        self.daily("equal.json", generated_at="2026-09-23T08:00:00+00:00")
        self.assertEqual(self.load()["by_date"]["2026-01-05"]["source"], "historical_recalculation")
        self.daily("newer.json", generated_at="2026-09-23T08:01:00+00:00")
        result = self.load()
        self.assertEqual(result["by_date"]["2026-01-05"]["source"], "daily_recommendation")
        self.assertEqual(result["by_date"]["2026-01-05"]["rows"][0]["ticker"], "D001")

    def test_waiting_and_missing_days_never_fall_back_to_old_rankings(self):
        self.recalculated(waiting=("2026-01-02",), omit=("2026-01-05",))
        self.daily(count=20)
        result = self.load()
        self.assertEqual(result["dates"], [])
        self.assertEqual(result["coverage_by_date"]["2026-01-02"]["status"], "WAITING_DATA")
        self.assertEqual(result["coverage_by_date"]["2026-01-05"]["status"], "MISSING_RECALCULATED_DATE")

    def test_rebuilt_annual_model_identity_and_strict_prediction_projection(self):
        self.recalculated(days=("2023-01-03",))
        with patch.object(reader.pq, "read_table", wraps=pq.read_table) as read:
            result = self.load()
        entry = result["by_date"]["2023-01-03"]
        self.assertEqual(entry["model_sha256"], "3"*64)
        self.assertEqual(entry["model_id"], "A2 年度重建 · 2023")
        calls = [call for call in read.call_args_list if Path(call.args[0]).name == "top40.parquet"]
        self.assertEqual(calls[0].kwargs["columns"], list(reader._RECALCULATED_COLUMNS))
        self.assertNotIn("FORBIDDEN_OUTCOME", entry["rows"][0])

    def test_invalid_recalculated_day_is_local_and_cannot_reveal_old_replay(self):
        root, run, manifest = self.recalculated()
        values = pq.read_table(run / "top40.parquet").to_pylist()
        values[0]["model_sha256"] = "0"*64
        pq.write_table(pa.Table.from_pylist(values), run / "top40.parquet")
        manifest["outputs"]["top40"]["sha256"] = digest(run / "top40.parquet")
        self.write_json(root / "latest.json", manifest)
        result = self.load()
        self.assertEqual(result["dates"], ["2026-01-05"])
        self.assertEqual(result["coverage_by_date"]["2026-01-02"]["status"], "INVALID_RESULT")
        self.assertTrue(any("MODEL_OR_SCORE" in issue for issue in result["issues"]))

    def test_recalculated_hash_or_path_failure_masks_its_range_but_keeps_other_dates(self):
        root, run, manifest = self.recalculated()
        self.daily(day="2026-09-22")
        manifest["outputs"]["top40"]["sha256"] = "0"*64
        self.write_json(root / "latest.json", manifest)
        result = self.load()
        self.assertEqual(result["dates"], ["2026-09-22"])
        self.assertEqual(result["recalculation"]["status"], "INVALID")
        self.assertTrue(any("HASH_MISMATCH" in issue for issue in result["issues"]))
        manifest["outputs"]["top40"] = {"path": str(self.replay / "predictions.parquet"),
                                        "sha256": digest(self.replay / "predictions.parquet")}
        self.write_json(root / "latest.json", manifest)
        self.assertTrue(any("OUTPUT_PATH_INVALID" in issue for issue in self.load()["issues"]))

    def test_annual_cannot_claim_current_model_and_rank_score_effective_gates(self):
        root, run, manifest = self.recalculated(days=("2023-01-03",))
        manifest["models"]["artifacts"]["2023"]["sha256"] = reader.MODEL_SHA256
        self.write_json(root / "latest.json", manifest)
        self.assertTrue(any("MODEL_IDENTITY_INVALID" in issue for issue in self.load()["issues"]))
        for change in ({"rank": 2}, {"score": None}, {"score": float("inf")}, {"universe_effective_date": "2026-02-01"}):
            with self.subTest(change=change):
                root, run, manifest = self.recalculated()
                values = pq.read_table(run / "top40.parquet").to_pylist()
                values[0].update(change)
                pq.write_table(pa.Table.from_pylist(values), run / "top40.parquet")
                manifest["outputs"]["top40"]["sha256"] = digest(run / "top40.parquet")
                self.write_json(root / "latest.json", manifest)
                result = self.load()
                self.assertNotIn("2026-01-02", result["dates"])
                self.assertEqual(result["by_date"]["2026-01-05"]["source"], "historical_recalculation")


if __name__ == "__main__":
    unittest.main()
