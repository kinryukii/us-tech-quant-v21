"""Exercise startup policy routing without opening a broker or server."""
from contextlib import redirect_stdout, redirect_stderr
import io
import unittest
from unittest.mock import patch

from moomoo_component import server


class ServerConfigurationTests(unittest.TestCase):
    def test_invalid_policy_is_rejected_before_engine_or_sdk_creation(self):
        cases = [
            ["--execution-window-seconds", "600"],
            ["--qualified-quotes-only"],
            ["--no-qualified-quotes-only"],
            ["--applied-strategies", "--execution-window-seconds", "0"],
            ["--applied-strategies", "--execution-window-seconds", "601"],
            ["--applied-strategies", "--execution-delay-minutes", "181"],
            ["--broker-execution-window-seconds", "3600"],
            ["--applied-strategies", "--moomoo-best", "--broker-execution-window-seconds", "3601"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), patch("sys.argv", ["component", *arguments]), \
                    patch.object(server, "Engine") as engine, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    server.main()
                self.assertEqual(result.exception.code, 2)
                engine.assert_not_called()

    def _start(self, extra):
        with patch("sys.argv", ["component", "--applied-strategies", "--moomoo-best", *extra]), \
                patch.object(server, "Engine"), patch.object(server, "LocalServer") as local, \
                patch("moomoo_component.applied_source.DailySource"), \
                patch("moomoo_component.quotes.MoomooQuoteFeed"), \
                patch("moomoo_component.cohort.Cohort") as cohort, \
                patch("moomoo_component.best_broker.BestBroker") as best, redirect_stdout(io.StringIO()):
            server.main()
            local.return_value.serve_forever.assert_called_once()
            local.return_value.server_close.assert_called_once()
            cohort.return_value.close.assert_called_once()
            return cohort.call_args.kwargs, best.call_args.kwargs, cohort.return_value.start.call_count

    def test_authorized_partial_policy_reaches_both_account_workers(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "45", "--execution-window-seconds", "600",
            "--qualified-quotes-only", "--activate-applied"])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=45,
                execution_window_seconds=600, allow_partial_quotes=True))
        self.assertEqual(starts, 1)

    def test_omitted_policy_preserves_persisted_configuration_without_activation(self):
        paper, broker, starts = self._start([])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=None,
                execution_window_seconds=None, allow_partial_quotes=None))
        self.assertEqual(starts, 0)

    def test_repository_and_cache_state_destinations_reject_before_engine(self):
        from pathlib import Path
        from scripts.common.storage_paths import resolve
        paths = resolve(Path("D:/us-tech-quant"))
        for invalid in (paths.repo_root / "runtime", paths.cache_root / "paper", paths.data_root / "paper", paths.daily_root):
            with self.subTest(path=invalid), patch("sys.argv", ["component", "--data-dir", str(invalid)]), \
                    patch.object(server, "Engine") as engine, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    server.main()
                engine.assert_not_called()

    def test_open_policy_reaches_both_workers(self):
        paper, broker, starts = self._start(["--execution-delay-minutes", "0", "--activate-applied"])
        self.assertEqual(paper["execution_delay_minutes"], 0)
        self.assertEqual(broker["execution_delay_minutes"], 0)
        self.assertEqual(starts, 1)

    def test_noon_policy_reaches_both_workers(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "150", "--execution-window-seconds", "600",
            "--qualified-quotes-only", "--activate-applied"])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=150,
                execution_window_seconds=600, allow_partial_quotes=True))
        self.assertEqual(starts, 1)

    def test_broker_window_does_not_change_three_paper_accounts(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "150", "--execution-window-seconds", "600",
            "--broker-execution-window-seconds", "3600",
            "--qualified-quotes-only", "--activate-applied"])
        self.assertEqual(paper["execution_window_seconds"], 600)
        self.assertEqual(broker["execution_window_seconds"], 3600)
        self.assertEqual(starts, 1)


if __name__ == "__main__":
    unittest.main()
