"""Resume only the missing subscription Raw corporate-action queries via the original builder."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PRODUCER = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
OLD_STATUS = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_status.csv")


def passing(path: Path) -> set[str]:
    status = pd.read_csv(path)
    return set(status.loc[status.status.eq("PASS"), "code"])


def main() -> None:
    spec = importlib.util.spec_from_file_location("original_rehab_resume", PRODUCER)
    assert spec and spec.loader
    producer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = producer
    spec.loader.exec_module(producer)
    aliases = "--authority-aliases" in sys.argv[1:]
    official_common = "--official-common-aliases" in sys.argv[1:]
    if official_common:
        producer.RUN_CACHE = HERE / "REHAB_OFFICIAL_COMMON_ALIASES_ONLY"
        targets = ["US.DTE","US.LILA"]
        for code in targets:
            assert (HERE / f"SUBSCRIPTION_{code.replace('.', '_')}_RAW_DAY_K_INPUT_ONLY.parquet").is_file()
    elif aliases:
        producer.RUN_CACHE = HERE / "REHAB_AUTHORITY_ALIASES_ONLY"
        targets = ["US.AAMI","US.AZN","US.GE","US.LLYVK",
                   "US.MS","US.ONC","US.SRTA","US.TGT"]
        for code in targets:
            assert (HERE / f"SUBSCRIPTION_{code.replace('.', '_')}_RAW_DAY_K_INPUT_ONLY.parquet").is_file()
    else:
        producer.RUN_CACHE = HERE / "REHAB_SUBSCRIPTION_ONLY"
        raw = set(pd.read_csv(HERE / "SUBSCRIPTION_RAW_FILES_MANIFEST.csv").code)
        old = passing(OLD_STATUS)
        occupied = passing(HERE / "REHAB_NEW_OCCUPIED_ONLY" / "rehab_status.csv")
        targets = sorted(raw - old - occupied)
    checkpoint = producer.RUN_CACHE / "rehab_status.csv"
    before = passing(checkpoint) if checkpoint.exists() else set()
    started = time.time()
    factors, status, requests = producer.load_rehab(targets)
    after = set(status.loc[status.status.eq("PASS"), "code"])
    receipt = {
        "targets": len(targets),
        "checkpoint_done_before": len(set(targets) & before),
        "requests_this_resume": requests,
        "pass_after": len(set(targets) & after),
        "factor_rows": len(factors),
        "elapsed_seconds": round(time.time() - started, 2),
        "status_file": str(producer.RUN_CACHE / "rehab_status.csv"),
        "factor_file": str(producer.RUN_CACHE / "rehab_factors.parquet"),
        "test_asof": "2026-09-23T18:40:43Z",
        "caveat": "Retrieved after TEST_ASOF; source lacks historical publication timestamp.",
    }
    receipt_path = HERE / ("REHAB_OFFICIAL_COMMON_ALIASES_RECEIPT.json" if official_common
                           else "REHAB_AUTHORITY_ALIASES_RECEIPT.json" if aliases
                           else "REHAB_SUBSCRIPTION_ONLY_RECEIPT.json")
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
