#!/usr/bin/env python
"""Contract tests for V21.057-R2 algorithmic discovery expansion."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_057_r2_algorithmic_candidate_discovery_expansion.py"
WRAPPER = ROOT / "scripts/v21/run_v21_057_r2_algorithmic_candidate_discovery_expansion.ps1"
spec = importlib.util.spec_from_file_location("v21_057_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path) -> list[Path]:
    write_csv(root / module.R1_POOL_REL, [
        {"ticker": "AAA", "instrument_type": "STOCK", "eligible_for_unified_pool": "TRUE"},
        {"ticker": "QQQ", "instrument_type": "CORE_ETF", "eligible_for_unified_pool": "TRUE"},
    ])
    write_csv(root / module.STOCK_REL, [{"ticker": "AAA"}, {"ticker": "QQQ"}])
    write_csv(root / module.SEED_REL, [{"ticker": "QQQ", "instrument_type": "CORE_ETF"}])
    price_rows = []
    for index in range(30):
        day = f"2026-05-{index + 1:02d}" if index < 15 else f"2026-06-{index - 14:02d}"
        for ticker, start, growth in (("SPY", 100, 0.2), ("QQQ", 100, 0.3), ("AAA", 100, 0.4), ("NEW", 100, 1.0)):
            price_rows.append({"as_of_date": day, "ticker": ticker, "close": str(start + growth * index), "adjusted_close": "", "volume": "1000000"})
    write_csv(root / module.PRICE_REL, price_rows)
    write_csv(root / module.DEPTH_REL, [{"ticker": ticker, "row_count": "30", "max_date": "2026-06-15"} for ticker in ("SPY", "QQQ", "AAA", "NEW")])
    write_csv(root / module.METADATA_REL, [{"ticker": "NEW", "sector": "Technology", "industry": "Semiconductors", "business_summary": "AI hardware and memory"}])
    a0 = root / module.A0_REL
    snap = root / module.R1_SNAPSHOT_REL
    write_csv(a0, [{"observation_id": "O1"}])
    write_csv(snap, [{"observation_id": "O1"}])
    protected = [a0, snap]
    for relpath in ("outputs/v21/official/OFFICIAL_RANKING.csv", "outputs/v21/official/OFFICIAL_WEIGHTS.csv"):
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("same\n", encoding="utf-8")
        protected.append(path)
    return protected


def assert_contract(root: Path, summary: dict[str, object], before: dict[str, str]) -> None:
    out = root / module.OUT_REL
    for name in (module.POOL_NAME, module.ELIGIBLE_NAME, module.FORCED_NAME, module.SOURCE_NAME, module.SUMMARY_NAME):
        assert (out / name).is_file()
    rows = list(csv.DictReader((out / module.POOL_NAME).open("r", encoding="utf-8")))
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED) == {row["ticker"] for row in forced}
    assert all(row["eligible_for_unified_pool"] == "FALSE" for row in rows if row["entered_by_forced_audit_only"] == "TRUE")
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["official_mutation_detected"] is False
    assert summary["research_only"] is True
    assert before == {path: sha(root / path) for path in before}


def test_objective_discovery_and_forced_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        protected = fixture(root)
        before = {path.relative_to(root).as_posix(): sha(path) for path in protected}
        summary = module.run_stage(root)
        rows = {row["ticker"]: row for row in csv.DictReader((root / module.OUT_REL / module.POOL_NAME).open("r", encoding="utf-8"))}
        assert rows["NEW"]["eligible_for_unified_pool"] == "TRUE"
        assert rows["NEW"]["entered_by_relative_strength_discovery"] == "TRUE"
        assert rows["NEW"]["entered_by_theme_discovery"] == "TRUE"
        assert rows["MU"]["entered_by_forced_audit_only"] == "TRUE"
        assert rows["MU"]["eligible_for_unified_pool"] == "FALSE"
        assert_contract(root, summary, before)


def test_repository_wrapper() -> None:
    protected = [path for path in (ROOT / module.A0_REL, ROOT / module.R1_SNAPSHOT_REL) if path.is_file()]
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            text = path.as_posix().lower()
            if ("official" in text and ("rank" in text or "weight" in text)) or "real_book" in text or "realbook" in text or "broker" in text:
                protected.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads((ROOT / module.OUT_REL / module.SUMMARY_NAME).read_text(encoding="utf-8"))
    assert_contract(ROOT, summary, before)


if __name__ == "__main__":
    test_objective_discovery_and_forced_diagnostics()
    test_repository_wrapper()
    print("PASS test_v21_057_r2_algorithmic_candidate_discovery_expansion")
