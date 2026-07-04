from __future__ import annotations
import importlib.util
from pathlib import Path
P=Path(__file__).with_name("v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py")
S=importlib.util.spec_from_file_location("m248",P); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
def test_event_refs_inventory_and_moomoo_coverage(tmp_path):
 repo=tmp_path/"repo"; p=repo/"scripts/v21/event_auto_update.py"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text("import yfinance\n# event refresh",encoding="utf-8")
 before=p.read_text(encoding="utf-8"); s=m.run(repo); out=repo/m.OUT_REL
 assert p.read_text(encoding="utf-8")==before
 assert s["broker_action_allowed"] is False and s["official_adoption_allowed"] is False
 assert "event_auto_update.py" in (out/"event_auto_update_module_inventory.csv").read_text(encoding="utf-8")
 assert "PLACEHOLDER_ONLY" in (out/"moomoo_only_replacement_coverage_audit.csv").read_text(encoding="utf-8")
 assert all((out/n).exists() for n in ["event_auto_update_import_reference_audit.csv","non_moomoo_fetch_dependency_audit.csv","event_auto_update_retirement_plan.csv","v21_248_summary.json"])
