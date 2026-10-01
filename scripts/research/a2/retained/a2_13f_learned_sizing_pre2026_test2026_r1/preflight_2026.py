"""Read-only eligibility check; no 2026 prices, returns, or policy outcomes loaded."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from train_pre2026 import HERE, sha


def main():
    manifest_path=HERE/"RUN_MANIFEST.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["stages"]["model_freeze"]!="MODEL_FROZEN":
        raise RuntimeError("MODEL_NOT_FROZEN")
    model_path=HERE/"MODEL_FROZEN.json"
    assert sha(model_path)==manifest["model_frozen_sha256"]
    surface=Path("D:/us-tech-quant-results/A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2/surface_manifest.json")
    source=Path("D:/us-tech-quant-data/moomoo/source/prices_qfq/year=2026/prices.parquet")
    r1a=Path("D:/us-tech-quant-results/A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR/retrospective_contract.json")
    surface_meta=json.loads(surface.read_text(encoding="utf-8"))
    # Version and coverage columns only; opening/closing values are intentionally not loaded.
    raw_meta=pd.read_parquet(source,columns=["trade_date","ticker","autype"])
    r1a_meta=json.loads(r1a.read_text(encoding="utf-8"))
    assert surface_meta["max_date"]=="2025-12-31"
    report={
        "status":"BLOCKED_QUALIFIED_2026_TEST_INPUTS",
        "model_frozen_sha256":sha(model_path),
        "fixed_test_asof":manifest["test_asof"],
        "frozen_training_price_surface_max_date":surface_meta["max_date"],
        "frozen_training_price_coordinate":"PIT_FORWARD_REHAB_INDEX",
        "2026_raw_vendor_price_autype":sorted(raw_meta.autype.astype(str).unique().tolist()),
        "2026_raw_vendor_price_max_date":str(pd.Timestamp(raw_meta.trade_date.max()).date()),
        "2026_raw_vendor_price_ticker_count":int(raw_meta.ticker.nunique()),
        "2026_existing_candidate_vintage":r1a_meta["model_vintage"],
        "2026_existing_candidate_universe":r1a_meta["universe"],
        "2026_existing_candidate_identity_qualification":"NOT_PROVEN_SAME_FROZEN_RAW_A2_PRODUCER_AND_UNIVERSE_AS_PRE2026_OOF",
        "blockers":[
            "No qualified 2026 continuation of the frozen PIT_FORWARD_REHAB_INDEX surface was found in the cited canonical v22 surface directory; raw qfq is a separate coordinate and was not spliced.",
            "Existing 2026 TOP20 R1A latest-common-vintage archive has not been proven identical to original 2023-2025 Raw A2 OOF producer/universe.",
            "2026Q2 full 13F package is absent; affected days would use predeclared B0 fallback if other test inputs become qualified."
        ],
        "2026_price_values_read":False,
        "2026_new_policy_return_values_read":False,
        "formal_2026_test_reveals":0,
        "fit_or_partial_fit_called":False,
        "source_sha256":{"training_surface_manifest":sha(surface),"2026_raw_vendor_prices":sha(source),
                         "2026_existing_candidate_contract":sha(r1a)}
    }
    (HERE/"TEST2026_INPUT_PREFLIGHT.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    manifest["stages"]["test_2026"]="BLOCKED_QUALIFIED_INPUTS_NO_FORMAL_REVEAL"
    manifest["status"]="MODEL_FROZEN_TEST2026_DATA_GAP"
    manifest["next_command"]="Provide a qualified same-coordinate 2026 PIT_FORWARD_REHAB_INDEX continuation and exact frozen Raw A2 2026 TOP20 identity, then run one fixed formal test; do not refit sizing or A2."
    manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
