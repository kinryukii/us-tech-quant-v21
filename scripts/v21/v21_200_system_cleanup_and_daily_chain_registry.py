#!/usr/bin/env python
"""V21.200 system inventory and active daily-chain registry. No deletion."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


STAGE = "V21.200_SYSTEM_CLEANUP_AND_DAILY_CHAIN_REGISTRY"
OUT = ROOT / "outputs/v21/V21.200_SYSTEM_CLEANUP_AND_DAILY_CHAIN_REGISTRY"
DOCS = ROOT / "docs"


def classify(path: Path) -> str:
    name = path.name.lower()
    if any(x in name for x in ["v21_198", "v21_199", "v21_200", "v21_197", "v21_178", "v21_173", "v21_172"]):
        return "active"
    if "test_" in name or "diagnostic" in name or "health" in name:
        return "diagnostic"
    if any(x in name for x in ["official", "weight", "ranking", "trade"]):
        return "frozen_reference"
    if any(x in name for x in ["deprecated", "old", "legacy"]):
        return "deprecated"
    return "unknown"


def inventory() -> pd.DataFrame:
    rows = []
    roots = ["scripts", "configs", "outputs", "data", "docs"]
    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                rows.append({
                    "path": path.relative_to(ROOT).as_posix(),
                    "artifact_type": root_name,
                    "size_bytes": path.stat().st_size,
                    "classification": classify(path),
                    "cleanup_action": "INVENTORY_ONLY_NO_DELETE",
                })
    for path in ROOT.glob("run_*.ps1"):
        rows.append({"path": path.name, "artifact_type": "root_runner", "size_bytes": path.stat().st_size, "classification": classify(path), "cleanup_action": "INVENTORY_ONLY_NO_DELETE"})
    return pd.DataFrame(rows, columns=["path", "artifact_type", "size_bytes", "classification", "cleanup_action"])


def write_docs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "V21_ACTIVE_SYSTEM_REGISTRY.md").write_text(
        "# V21 Active System Registry\n\n"
        "- V21.198: Moomoo quote/data health check.\n"
        "- V21.199: Moomoo broad daily bar import and gated canonical merge.\n"
        "- V21.197/V21.193: broad-date-aware ABCDE rerun chain.\n"
        "- V21.178: DRAM daily research-only chain.\n"
        "- V21.173/V21.172/V21.169/V21.171: forward tracking and switch governance where available.\n\n"
        "Policy: research_only=true, official_adoption_allowed=false, broker_action_allowed=false.\n",
        encoding="utf-8",
    )
    (DOCS / "DATA_SOURCE_MOOMOO_README.md").write_text(
        "# Moomoo Data Source\n\n"
        "The primary market-data path uses Moomoo OpenD quote APIs only. It requires `moomoo-api` and OpenD at "
        "`MOOMOO_OPEND_HOST`/`MOOMOO_OPEND_PORT` (defaults 127.0.0.1:18441). No yfinance fallback, trade API, account unlock, "
        "or broker action is allowed. DRAM maps to `US.DRAM` and is always included as a priority symbol.\n",
        encoding="utf-8",
    )
    (DOCS / "DAILY_CHAIN_RUNBOOK.md").write_text(
        "# Daily Chain Runbook\n\n"
        "1. V21.198 Moomoo health check.\n"
        "2. V21.199 Moomoo broad daily import and canonical merge.\n"
        "3. Existing broad-date-aware ABCDE rerun chain.\n"
        "4. Existing DRAM daily execution chain.\n"
        "5. Existing forward tracking / switch governance chain.\n"
        "6. Report/archive generation.\n\n"
        "ABCDE reruns must use broad_honest_latest_date / broad-date completeness, never raw max(date). "
        "broker_action_allowed remains false throughout the chain.\n",
        encoding="utf-8",
    )


def run(out_dir: Path = OUT) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    inv = inventory()
    inv.to_csv(out_dir / "system_inventory.csv", index=False)
    active = pd.DataFrame([
        {"order": 1, "stage": "V21.198", "script": "scripts/v21/v21_198_moomoo_data_backbone_and_health_check.py", "mandatory": True},
        {"order": 2, "stage": "V21.199", "script": "scripts/v21/v21_199_moomoo_broad_daily_bar_import_and_canonical_merge.py", "mandatory": True},
        {"order": 3, "stage": "V21.197", "script": "scripts/v21/v21_197_final_broad_date_abcde_rerun_after_manual_import.py", "mandatory": True},
        {"order": 4, "stage": "V21.178", "script": "scripts/v21/v21_178_daily_dram_plan_chain_orchestrator_r1.py", "mandatory": True},
        {"order": 5, "stage": "V21.173+", "script": "latest available switch governance stages", "mandatory": False},
    ])
    active.to_csv(out_dir / "active_daily_chain_registry.csv", index=False)
    inv[inv["classification"].eq("deprecated")].to_csv(out_dir / "deprecated_artifact_manifest.csv", index=False)
    inv[inv["classification"].eq("frozen_reference")].to_csv(out_dir / "protected_artifact_manifest.csv", index=False)
    inv[inv["classification"].eq("unknown")].to_csv(out_dir / "unknown_artifact_review_queue.csv", index=False)
    write_docs()
    summary = {
        "stage": STAGE,
        "final_status": "PASS_V21_200_REGISTRY_CREATED_NO_DELETE",
        "final_decision": "DAILY_CHAIN_REGISTRY_ACTIVE_RESEARCH_ONLY",
        "inventoried_file_count": int(len(inv)),
        "files_deleted": 0,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    (out_dir / "v21_200_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "V21.200_system_cleanup_report.txt").write_text(
        "\n".join([STAGE, f"final_status={summary['final_status']}", "cleanup_action=inventory_registry_deprecation_only", "files_deleted=0", "broker_action_allowed=false"]) + "\n",
        encoding="utf-8",
    )
    print(f"final_status={summary['final_status']}")
    return summary


if __name__ == "__main__":
    run()
