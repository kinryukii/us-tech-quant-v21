from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import v22_055_fast3_multifactor_data_and_factor_preflight_r1 as mod


def valid_054():
    return {
        "final_status": "PASS",
        "final_decision": "FAST3_SIGNAL_FAMILY_TERMINATED_NOT_ROBUST",
        "fast3_signal_family_robust": False,
        "fast3_development_continue": False,
        "paper_trading_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }


def test_validate_054_accepts(): mod.validate_v22_054(valid_054())

def test_validate_054_rejects():
    p = valid_054(); p["final_status"] = "FAIL"
    with pytest.raises(mod.PreflightError): mod.validate_v22_054(p)

def test_find_column_case_insensitive(): assert mod.find_column(["Timestamp_UTC"], ["timestamp_utc"]) == "Timestamp_UTC"

def test_supported_files_single(tmp_path):
    p = tmp_path / "vix.csv"; p.write_text("timestamp,close\n", encoding="utf-8")
    assert mod.supported_files(p) == [p]

def test_select_vix_source():
    inv = pd.DataFrame([{"candidate_root":"x","file_count":1,"readable":True}])
    assert mod.select_vix_source(inv) == Path("x")

def test_select_vix_source_none():
    inv = pd.DataFrame([{"candidate_root":"x","file_count":0,"readable":False}])
    assert mod.select_vix_source(inv) is None

def test_rsi_uptrend_high():
    close = pd.Series(np.arange(1, 40, dtype=float))
    assert mod.rsi_wilder(close).dropna().iloc[-1] == pytest.approx(100.0)

def test_kdj_lengths():
    f = pd.DataFrame({"high":np.arange(1,30)+1,"low":np.arange(1,30)-1,"close":np.arange(1,30)})
    k,d,j = mod.kdj(f)
    assert len(k) == len(f) == len(d) == len(j)

def test_atr_nonnegative():
    f = pd.DataFrame({"high":[2,3,4]*10,"low":[1,2,3]*10,"close":[1.5,2.5,3.5]*10})
    assert (mod.atr_wilder(f).dropna() >= 0).all()

def test_factor_readiness():
    n=100
    et=pd.date_range("2026-01-02 09:30", periods=n, freq="5min", tz="America/New_York")
    f=pd.DataFrame({"timestamp_utc":et.tz_convert("UTC"),"timestamp_et":et,"open":np.arange(n)+100.,"high":np.arange(n)+101.,"low":np.arange(n)+99.,"close":np.arange(n)+100.5,"volume":1000.,"minute_count":5})
    result=mod.factor_readiness(f)
    assert result["factor_ready_count"] > 0

def test_requirements_forbid_proxy():
    r=mod.requirements_payload()
    assert "VXX" in r["forbidden_substitutions"]

def test_parse_defaults():
    a=mod.parse_args(["--execute"])
    assert "V22.054_FAST3_TERMINATION" in a.v22_054_summary

def test_common_roots_include_vix(): assert all("vix" in p.lower() for p in mod.COMMON_VIX_ROOTS)
