from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.v21 import v21_200_system_cleanup_and_daily_chain_registry as stage


def test_cleanup_registry_does_not_delete_files(tmp_path, monkeypatch):
    root = tmp_path
    (root / "scripts/v21").mkdir(parents=True)
    (root / "outputs/v21").mkdir(parents=True)
    keep = root / "outputs/v21/protected_official_ranking.csv"
    keep.write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "scripts/v21/v21_198_moomoo_data_backbone_and_health_check.py").write_text("print('x')\n", encoding="utf-8")
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "OUT", root / "outputs/v21/V21.200_SYSTEM_CLEANUP_AND_DAILY_CHAIN_REGISTRY")
    monkeypatch.setattr(stage, "DOCS", root / "docs")
    summary = stage.run(stage.OUT)
    assert summary["files_deleted"] == 0
    assert keep.exists()
    inv = pd.read_csv(stage.OUT / "system_inventory.csv")
    assert "outputs/v21/protected_official_ranking.csv" in set(inv["path"])
    assert (root / "docs/DAILY_CHAIN_RUNBOOK.md").is_file()


def test_runbook_states_broker_actions_false(tmp_path, monkeypatch):
    root = tmp_path
    (root / "scripts").mkdir()
    (root / "outputs").mkdir()
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "OUT", root / "outputs/v21/V21.200_SYSTEM_CLEANUP_AND_DAILY_CHAIN_REGISTRY")
    monkeypatch.setattr(stage, "DOCS", root / "docs")
    stage.run(stage.OUT)
    text = (root / "docs/DAILY_CHAIN_RUNBOOK.md").read_text(encoding="utf-8")
    assert "broker_action_allowed remains false" in text
