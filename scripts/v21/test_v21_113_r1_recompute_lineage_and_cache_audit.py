from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_113_r1_recompute_lineage_and_cache_audit.py"
OUT = ROOT / "outputs/v21/V21.113_R1_RECOMPUTE_LINEAGE_AND_CACHE_AUDIT"
SUMMARY = OUT / "V21.113_R1_recompute_lineage_and_cache_audit_summary.json"
REPORT = OUT / "V21.113_R1_recompute_lineage_and_cache_audit_report.md"


def test_v21_113_r1_recompute_lineage_and_cache_audit_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OUT.is_dir()
    assert SUMMARY.is_file()

    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["protected_outputs_modified"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["latest_price_date"] >= "2026-06-25"

    for name in [
        "ranking_file_hash_comparison.csv",
        "factor_input_freshness_audit.csv",
        "stale_factor_cache_report.csv",
        "forced_recompute_comparison.csv",
        "lineage_input_file_manifest.csv",
        "d_score_identity_vs_prior_runs.csv",
        "D_top20_v21_113_vs_forced_recompute.csv",
        "D_top50_v21_113_vs_forced_recompute.csv",
        "D_entrants_removals_vs_V21_108_R2.csv",
        "D_entrants_removals_vs_V21_112_R1.csv",
        "D_entrants_removals_vs_V21_113_original.csv",
    ]:
        assert (OUT / name).is_file(), name

    if not summary["forced_recompute_succeeded"]:
        assert summary["forced_recompute_not_possible_reason"]
        assert (OUT / "forced_recompute/forced_recompute_not_possible.md").is_file()

    if summary["FINAL_STATUS"].startswith("PASS"):
        assert summary["stale_factor_input_count"] == 0
        assert summary["forced_recompute_succeeded"] or "lineage proof" in REPORT.read_text(encoding="utf-8").lower()

    text = REPORT.read_text(encoding="utf-8")
    assert "Did V21.113 fully recompute ABCD rankings from 2026-06-25 data, or did it only refresh prices?" in text
