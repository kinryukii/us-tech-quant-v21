from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.data_sources import moomoo_client
from scripts.data_sources.moomoo_market_state_gate import import_allowed, market_state_gate
from scripts.data_sources.moomoo_quota_auditor import audit_quota
from scripts.data_sources.moomoo_symbol_mapper import map_symbols
from scripts.v21 import v21_198_moomoo_data_backbone_and_health_check as stage


class FakeClient:
    module = SimpleNamespace(RET_OK=0)

    def __init__(self, state: str = "CLOSED"):
        self.state = state

    def health_check(self):
        return {"minimal_quote_function_ok": True, "opend_reachable": True}

    def checked_call(self, name, *args, **kwargs):
        if name == "get_market_state":
            return pd.DataFrame({"code": ["US.DRAM"], "market_state": [self.state]})
        if name == "get_history_kl_quota":
            return {"used_quota": 1, "remain_quota": 99, "detail_list": [{"code": "US.DRAM"}]}
        raise AssertionError(name)

    def close(self):
        pass


def test_moomoo_api_missing_fails_clearly(monkeypatch):
    def fail_import(name):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", fail_import)
    with pytest.raises(moomoo_client.MoomooApiMissingError):
        moomoo_client.import_moomoo()


def test_opend_unavailable_health_check(monkeypatch):
    fake_module = SimpleNamespace(OpenQuoteContext=lambda host, port: (_ for _ in ()).throw(RuntimeError("down")))
    client = moomoo_client.MoomooQuoteClient(module=fake_module)
    health = client.health_check()
    assert health["final_status"] == "FAIL"
    assert health["minimal_quote_function_ok"] is False
    assert "OpenD" in health["error"]


def test_symbol_mapping_priority_dram():
    audit = map_symbols(["AAPL", "QQQ"], include_priority=True)
    assert {"US.AAPL", "US.QQQ", "US.DRAM"}.issubset(set(audit["moomoo_code"]))
    assert audit.loc[audit["internal_symbol"].eq("DRAM"), "mapping_status"].iloc[0] == "PASS"


def test_market_state_gate_closed_open_behavior():
    closed = market_state_gate(FakeClient("CLOSED"), ["US.DRAM"])
    open_ = market_state_gate(FakeClient("OPEN"), ["US.DRAM"])
    assert import_allowed(closed) is True
    assert import_allowed(open_) is False


def test_quota_audit_detail_list():
    quota = audit_quota(FakeClient())
    assert quota["quota_status"] == "PASS"
    assert quota["remain_quota"] == 99


def test_stage_198_outputs(tmp_path):
    summary = stage.run(client=FakeClient(), out_dir=tmp_path)
    assert summary["final_status"] == "PASS"
    assert (tmp_path / "moomoo_health_check.json").is_file()
    assert (tmp_path / "moomoo_symbol_mapping_audit.csv").is_file()
    assert summary["broker_action_allowed"] is False
