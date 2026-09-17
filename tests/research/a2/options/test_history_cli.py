"""Actual CLI routing with invented manifests and injected transport only."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.research.a2.options import cli, historical_quotes as history
from scripts.research.a2.options.contracts import Invalid, TEMPLATE
from tests.research.a2.options.test_expression_pilot import external_tmp_path


QUALIFICATION_REQUESTS = history.qualification_requests


@pytest.fixture
def bound_cli(external_tmp_path, monkeypatch):
    root = external_tmp_path
    paths = SimpleNamespace(results_root=root / "results", cache_root=root / "cache")
    parent = paths.results_root / TEMPLATE / "overnight/20260913T032957JST"
    probes = [{"decision_id": f"invented-{n}", "underlying_symbol": "TEST"} for n in range(9)]
    payloads = {"reviewed/run_manifest.json": {"invented": True},
        "reviewed/option_evidence/fixed_probe_plan.json": {"research_identity": TEMPLATE,
            "selected": probes, "pilot_plan_count": 0, "pilot_plan_status": "NOT_GENERATED"},
        "run_config.json": {"no_training": True}}
    bindings = {}
    for name, value in payloads.items():
        path = parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        bindings[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(cli, "HISTORY_BINDINGS", bindings)
    monkeypatch.setattr(cli, "resolve", lambda: paths)
    for name in history.ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(history, "qualification_requests", lambda probe, **kw:
        [{"kind": "contracts", "url": "https://api.massive.com/v3/reference/options/contracts", "params": {}}])
    calls = []
    def transport(**kwargs):
        calls.append(kwargs["probe"]["decision_id"])
        return {"status": "NO_CREDENTIAL", "http_requests": 0, "rows": [], "page_complete": False,
                "authentication": "UNKNOWN", "entitlement": "UNKNOWN"}
    monkeypatch.setattr(history, "request_massive_history", transport)
    output = paths.results_root / TEMPLATE / "runs/INVENTED"
    return output, calls, parent


def test_actual_cli_consumes_history_adapter_and_never_fakes_evaluate(bound_cli, monkeypatch):
    output, calls, _ = bound_cli
    from scripts.research.a2.options import expression
    monkeypatch.setattr(expression, "evaluate", lambda **kw: pytest.fail("No qualified economic inputs"))
    assert cli.main(["--mode", "real-options", "--output", str(output)]) == 3
    assert calls == [f"invented-{n}" for n in range(9)]
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert manifest["evaluate_calls"] == 0
    assert manifest["economic_planned"] == 0
    assert not manifest["required_stage_success"]
    assert manifest["source_modules"]["historical_quotes"]["path"] == str(Path(history.__file__).resolve())
    assert len((output / "actual_pairs.csv").read_text().splitlines()) == 1


def test_resume_keeps_prior_invocation_and_frozen_configuration(bound_cli):
    output, _, _ = bound_cli
    first = cli.run_historical_quotes(output)
    frozen = (output / "run_config.json").read_bytes()
    old_summary = (output / "qualification_summary.json").read_bytes()
    old_manifest = (output / "run_manifest.json").read_bytes()
    interrupted = output / "invocations/001"
    interrupted.mkdir(parents=True)
    (interrupted / "partial.txt").write_text("preserved interrupted archive")
    second = cli.run_historical_quotes(output, output / "run_config.json")
    assert first["run_identity"] == second["run_identity"]
    assert (output / "run_config.json").read_bytes() == frozen
    assert len(second["prior_invocations"]) == 1
    archived = output / second["prior_invocations"][0]["path"]
    assert archived.name == "002"
    assert (interrupted / "partial.txt").read_text() == "preserved interrupted archive"
    assert (archived / "qualification_summary.json").read_bytes() == old_summary
    assert (archived / "run_manifest.json").read_bytes() == old_manifest


def test_changed_parent_rejects_before_transport(bound_cli):
    output, calls, parent = bound_cli
    (parent / "run_config.json").write_text('{}')
    with pytest.raises(Invalid, match="PARENT_BINDING_CHANGED"):
        cli.run_historical_quotes(output)
    assert not calls


def test_unbound_real_option_input_rejects_before_any_read(monkeypatch):
    monkeypatch.setattr(Path, "read_bytes", lambda *a: pytest.fail("Unbound file read"))
    assert cli.main(["--mode", "real-options", "--input", "unbound-2026.json",
                     "--output", "unused"]) == 2


def test_old_output_location_cannot_be_overwritten(bound_cli):
    _, calls, parent = bound_cli
    with pytest.raises(Invalid, match="NEW_RUN_OUTPUT_BOUNDARY"):
        cli.run_historical_quotes(parent / "reviewed")
    assert not calls


def _interactive_console(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "stderr", SimpleNamespace(isatty=lambda: True))


def test_hidden_key_continues_original_cli_and_stays_out_of_artifacts(bound_cli, monkeypatch, capsys):
    import getpass
    import os
    output, calls, _ = bound_cli
    _interactive_console(monkeypatch)
    prompts, received = [], []
    def hidden(prompt):
        prompts.append(prompt)
        return "SYNTHETIC_LOCAL_SECRET"
    monkeypatch.setattr(getpass, "getpass", hidden)
    original = history.request_massive_history
    def transport(**kwargs):
        received.append(kwargs["api_key"])
        return original(**kwargs)
    monkeypatch.setattr(history, "request_massive_history", transport)
    assert cli.main(["--mode", "real-options", "--prompt-api-key", "--output", str(output)]) == 3
    assert len(prompts) == 1 and len(calls) == 9
    assert received == ["SYNTHETIC_LOCAL_SECRET"] * 9
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert manifest["credential_available"] and manifest["credential_source"] == "LOCAL_HIDDEN_PROMPT"
    assert manifest["authentication_transport"] == "MASSIVE_QUERY_PARAMETER"
    assert os.environ.get("MASSIVE_API_KEY") is None and os.environ.get("POLYGON_API_KEY") is None
    assert "SYNTHETIC_LOCAL_SECRET" not in capsys.readouterr().out
    assert all("SYNTHETIC_LOCAL_SECRET" not in p.read_text() for p in output.rglob("*") if p.is_file())


@pytest.mark.parametrize("reason", ["noninteractive", "warning", "cancel", "eof", "empty"])
def test_hidden_input_failure_stops_before_any_output_or_http(bound_cli, monkeypatch, reason):
    import getpass
    import sys
    import warnings
    output, calls, _ = bound_cli
    _interactive_console(monkeypatch)
    def hidden(prompt):
        if reason == "warning":
            warnings.warn("Echo cannot be disabled", getpass.GetPassWarning)
            pytest.fail("Plaintext fallback executed")
        if reason == "cancel":
            raise KeyboardInterrupt
        if reason == "eof":
            raise EOFError
        if reason == "empty":
            return "  "
        pytest.fail("Prompt launched without interactive terminal")
    if reason == "noninteractive":
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(getpass, "getpass", hidden)
    assert cli.main(["--mode", "real-options", "--prompt-api-key", "--output", str(output)]) == 2
    assert not calls and not output.exists()


def test_in_memory_key_available_without_environment_or_prompt(bound_cli, monkeypatch):
    import getpass
    output, _, _ = bound_cli
    monkeypatch.setattr(getpass, "getpass", lambda *a: pytest.fail("Unexpected prompt"))
    manifest = cli.run_historical_quotes(output, api_key="SYNTHETIC_FUNCTION_SECRET")
    assert manifest["credential_available"] and manifest["credential_source"] == "EXPLICIT_IN_MEMORY_ARGUMENT"


def test_empty_explicit_memory_key_stops_before_any_output_or_http(bound_cli):
    output, calls, _ = bound_cli
    with pytest.raises(Invalid, match="EMPTY_API_KEY"):
        cli.run_historical_quotes(output, api_key="  ")
    assert not calls and not output.exists()


def test_hidden_input_cannot_activate_other_cli_modes(monkeypatch):
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda *a: pytest.fail("Unexpected prompt"))
    assert cli.main(["--mode", "synthetic", "--prompt-api-key"]) == 2


@pytest.mark.parametrize("tickers,expected_option_requests", [
    (["O:TEST1250321C00100000", "O:TEST250321C00100000"], 9),
    (["O:TEST1250321C00100000", "O:TEST250221C00100000"], 0),
])
def test_metadata_ticker_scope_rejections_do_not_abort_original_probe_order(
        bound_cli, monkeypatch, tickers, expected_option_requests):
    output, _, _ = bound_cli
    monkeypatch.setattr(history, "_bound_probe", lambda probe: None)
    def descriptors(probe, option_ticker=None):
        return QUALIFICATION_REQUESTS(probe | {"start": "2025-02-04T09:44:59-05:00",
            "end": "2025-02-04T09:46:01-05:00"}, option_ticker=option_ticker)
    monkeypatch.setattr(history, "qualification_requests", descriptors)
    requested = []
    def transport(**kwargs):
        requested.append((kwargs["probe"]["decision_id"], kwargs["url"]))
        rows = [{"ticker": ticker} for ticker in reversed(tickers)] if kwargs["url"].endswith("/contracts") else []
        return {"status": "SYNTHETIC_ENDPOINT_PROBE", "http_requests": 0, "rows": rows,
                "page_complete": True, "authentication": "UNKNOWN", "entitlement": "UNKNOWN"}
    monkeypatch.setattr(history, "request_massive_history", transport)
    manifest = cli.run_historical_quotes(output)
    assert [identity for identity, url in requested if url.endswith("/contracts")] == [f"invented-{n}" for n in range(9)]
    option_urls = [url for _, url in requested if "/quotes/O:" in url]
    assert len(option_urls) == expected_option_requests
    assert all(url.endswith("/O:TEST250321C00100000") for url in option_urls)
    summaries = json.loads((output / "qualification_summary.json").read_text())
    option_rows = [row for row in summaries if row["kind"] == "option_quotes"]
    assert len(option_rows) == 9
    expected_status = "SYNTHETIC_ENDPOINT_PROBE" if expected_option_requests else "NOT_TESTABLE_CONTRACT_ID_NOT_ESTABLISHED"
    assert all(row["status"] == expected_status for row in option_rows)
    assert manifest["evaluate_calls"] == 0 and manifest["paired_rows"] == 0
