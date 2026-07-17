import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("v231_manifest", ROOT / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def setup_snapshot(tmp_path, snapshot="good", missing=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan = tmp_path / "plan.csv"; legs = [("1m", "raw"), ("5m", "raw"), ("15m", "raw"), ("1h", "raw")]
    with plan.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["ticker","moomoo_symbol","frequency","adjustment"]); w.writeheader(); w.writerows({"ticker":"DRAM","moomoo_symbol":"US.DRAM","frequency":q,"adjustment":a} for q,a in legs)
    fields=m.INTRADAY_REQUIRED_COLUMNS
    for frequency, adjustment in legs:
        if frequency == missing: continue
        p=tmp_path/"raw/moomoo/intraday/DRAM"/f"snapshot_id={snapshot}"/frequency/"DRAM.csv"; p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerow({"ticker":"DRAM","moomoo_symbol":"US.DRAM","market":"US","date":"2026-07-15","adjustment":adjustment,"source":"MOOMOO_OPEND","source_policy":"MOOMOO_ONLY","snapshot_id":snapshot,"fetched_at_utc":"2026-07-15T00:00:00Z"})
    return plan


def test_reconstruct_and_select_skips_newer_empty_snapshot(tmp_path):
    plan=setup_snapshot(tmp_path); (tmp_path/"raw/moomoo/intraday/DRAM/snapshot_id=new-empty").mkdir(parents=True)
    manifest=m.reconstruct_intraday_manifest(tmp_path,plan,"good","2026-07-15")
    assert manifest["written"] and manifest["valid_leg_count"] == 4
    assert m.select_valid_intraday_snapshot(tmp_path,plan,"2026-07-15")["snapshot_id"] == "good"


def test_hash_mismatch_and_missing_leg_are_rejected(tmp_path):
    plan=setup_snapshot(tmp_path); m.reconstruct_intraday_manifest(tmp_path,plan,"good","2026-07-15")
    p=tmp_path/"raw/moomoo/intraday/DRAM/snapshot_id=good/1m/DRAM.csv"; p.write_text(p.read_text(encoding="utf-8")+"\n",encoding="utf-8")
    assert m.select_valid_intraday_snapshot(tmp_path,plan,"2026-07-15") is None
    plan2=setup_snapshot(tmp_path/"missing", missing="1h")
    assert not m.reconstruct_intraday_manifest(tmp_path/"missing",plan2,"good","2026-07-15")["written"]


def test_aggregate_is_stable_and_reconstructed_manifest_needs_no_sdk(tmp_path):
    plan=setup_snapshot(tmp_path); a=m.reconstruct_intraday_manifest(tmp_path,plan,"good","2026-07-15"); b=m.reconstruct_intraday_manifest(tmp_path,plan,"good","2026-07-15")
    assert a["aggregate_sha256"] == b["aggregate_sha256"]
    assert m.select_valid_intraday_snapshot(tmp_path,plan,"2026-07-15")["sdk_call_used"] is False


def test_file_change_during_validation_is_rejected(tmp_path, monkeypatch):
    plan=setup_snapshot(tmp_path); original=m.sha256_file; target=tmp_path/"raw/moomoo/intraday/DRAM/snapshot_id=good/1m/DRAM.csv"
    changed=[False]
    def mutate_while_hashing(path):
        digest=original(path)
        if Path(path) == target and not changed[0]:
            changed[0]=True; target.write_text(target.read_text(encoding="utf-8")+"\n", encoding="utf-8")
        return digest
    monkeypatch.setattr(m, "sha256_file", mutate_while_hashing)
    result=m.reconstruct_intraday_manifest(tmp_path,plan,"good","2026-07-15")
    assert not result["written"]
    assert "DRAM|1m|raw" in result["files_changed_during_validation"]
