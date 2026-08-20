import importlib.util
import sys
from pathlib import Path

import pandas as pd


SOURCE = Path(r"D:\us-tech-quant\fast3\scripts\audit\fast3_factor_cartography_postmortem_r1.py")
SPEC = importlib.util.spec_from_file_location("fast3_factor_cartography_postmortem_r1", SOURCE)
M = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def test_authoritative_source_is_complete_and_hash_verified():
    source = M.verify_source()
    assert source["audit"]["SOURCE_PREREGISTRATION_SHA256_VERIFIED"] is True
    assert source["audit"]["SOURCE_FACTOR_UNIVERSE_SHA256_VERIFIED"] is True
    assert source["audit"]["FROZEN_BOOTSTRAP_REP_REQUIREMENT"] == 10_000
    assert source["audit"]["ACTUAL_BOOTSTRAP_REP_COUNT"] == 10_000
    assert source["audit"]["RAW_CANDIDATE_COUNT"] == 50


def test_cluster_and_markdown_are_deterministic_descriptive_helpers():
    redundancy = pd.DataFrame({"factor_A": ["a", "b", "a"], "factor_B": ["b", "c", "c"],
                               "spearman": [.91, .76, .2], "absolute_spearman": [.91, .76, .2]})
    group = M.clusters(redundancy, .75)
    assert group["a"] == group["b"] == group["c"]
    rendered = M.gfm(pd.DataFrame({"factor": ["x|y"], "value": [.125]}))
    assert "x\\|y" in rendered and "0.125" in rendered


def test_analysis_has_no_fitting_or_research_mutation_surface():
    text = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("HistGradientBoosting", ".fit(", "bootstrap_batch", "permut", "R45_STAGE"):
        assert forbidden not in text
    assert "POST_HOC_DESCRIPTIVE_ONLY" in text
    assert "MODEL_FIT_COUNT_THIS_TASK\": 0" in text
