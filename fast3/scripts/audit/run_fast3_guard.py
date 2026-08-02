"""FAST3 architecture, bloat, single-source, and forbidden-pattern guard."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FAST = REPO / "fast3"
ALLOWED_TOP = {"compatibility", "configs", "docs", "manifests", "scripts", "src", "state", "tests"}
EXTERNAL_RESULTS_ROOT = Path(r"D:\us-tech-quant-results\fast3")
EXTERNAL_DATA_ROOT = Path(r"D:\us-tech-quant-data\fast3")
RESULT_FILE_BUDGET = 8


def _json(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def _hash(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _files(root=FAST): return [p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def architecture():
    top = {p.name for p in FAST.iterdir() if p.is_dir()}
    bad = sorted(top - ALLOWED_TOP)
    allowed_root = {"FAST3.md", "run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1", "start_codex_v22_080a.ps1"}
    root_named_fast3 = [p.name for p in REPO.iterdir() if p.is_file() and "fast3" in p.name.lower() and not p.name.endswith(".bak") and p.name != "fast3_migration_worklog.md"]
    active_root = [name for name in allowed_root if (REPO / name).is_file()]
    allowed_codex = {"CODEX_GOAL.md", "CODEX_PLAN.md", "CODEX_STATUS.md"}
    root_codex = [p.name for p in REPO.iterdir() if p.is_file() and p.name.upper().startswith("CODEX_") and not p.name.endswith(".bak")]
    root_legacy = {"CODEX_AUTOPILOT_PROMPT.txt", "CODEX_RESUME_FULL_CHAIN_PROMPT.txt", "fast3_migration_worklog.md", "-tech-quant"}
    violations = [f"top:{x}" for x in bad] + [f"root:{x}" for x in root_named_fast3 if x not in allowed_root]
    violations += [f"root_codex:{x}" for x in root_codex if x not in allowed_codex]
    violations += [f"root_legacy:{x}" for x in root_legacy if (REPO / x).exists()]
    return {"name": "architecture", "violations": violations, "root_fast3_file_count": len(active_root)}


def bloat(root=FAST):
    limits = _json(root / "configs" / "runtime" / "FAST3_ANTI_BLOAT_LIMITS.json")
    big = [p.relative_to(root).as_posix() for p in _files(root) if p.suffix.lower() in limits["forbidden_binary_suffixes"] and "legacy/" not in p.relative_to(root).as_posix()]
    big += [p.relative_to(root).as_posix() for p in _files(root) if p.suffix.lower() in {".csv", ".json"} and p.stat().st_size > limits["max_csv_json_bytes_outside_legacy"] and "legacy/" not in p.relative_to(root).as_posix()]
    oversized_py = [p.relative_to(root).as_posix() for p in _files(root) if p.suffix == ".py" and len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) > limits["single_python_file_line_budget"]]
    suffix = re.compile(r"FAST3[-_]\d{3}.*(?:_R\d+|_FINAL(?:\d+|_V\d+)|_PATCH(?:ED)?\d*|_V\d+)", re.I)
    forbidden = [p.relative_to(root).as_posix() for p in _files(root) if suffix.search(p.name) and "legacy/" not in p.relative_to(root).as_posix()]
    return {"name": "bloat", "violations": [f"large:{x}" for x in big] + [f"python_lines:{x}" for x in oversized_py] + [f"suffix:{x}" for x in forbidden]}


def registry_hygiene():
    configs = _json(FAST / "manifests" / "registries" / "FAST3_CONFIG_REGISTRY.json")["configs"]
    stages = _json(FAST / "manifests" / "registries" / "FAST3_STAGE_REGISTRY.json")["stages"]
    formal = {}
    for item in configs: formal[item["stage_id"]] = formal.get(item["stage_id"], 0) + int(item["canonical"])
    active_auth = [p for p in _files() if "AUTHORIZATION" in p.name and "docs/legacy/" not in p.relative_to(FAST).as_posix()]
    active_patch = [p for p in _files() if "PATCH_APPLIED" in p.name and "manifests/legacy/" not in p.relative_to(FAST).as_posix()]
    active_prompt = [p for p in _files() if "PROMPT" in p.name and "docs/legacy/" not in p.relative_to(FAST).as_posix()]
    stage_manifests = list((FAST / "manifests" / "stages").glob("FAST3_003*MANIFEST.json"))
    state_files = list((FAST / "state").glob("*STATE*.json"))
    bad = [f"duplicate_config:{k}" for k,v in formal.items() if v > 1]
    if len(state_files) != 1: bad.append("duplicate_state")
    if len(stage_manifests) != 1: bad.append("duplicate_stage_manifest")
    if active_auth: bad.append("active_authorization")
    if active_patch: bad.append("active_patch")
    if active_prompt: bad.append("active_prompt")
    if (FAST / "outputs").exists() or (FAST / "stages").exists(): bad.append("deprecated_result_directory")
    if len({x["stage_id"] for x in stages}) != len(stages): bad.append("duplicate_stage_id")
    return {"name": "registry_hygiene", "violations": bad, "active_authorization_file_count": len(active_auth), "active_patch_file_count": len(active_patch), "active_prompt_file_count": len(active_prompt), "duplicate_config_count": len([k for k,v in formal.items() if v > 1]), "duplicate_state_count": max(0, len(state_files)-1)}


def compatibility():
    targets = {"run_fast3_overnight_autopilot.ps1": "fast3\\compatibility\\run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1": "fast3\\compatibility\\start_codex_fast3_full_chain.ps1", "start_codex_v22_080a.ps1": "fast3\\compatibility\\start_codex_v22_080a.ps1"}
    bad = []
    for old, relative in targets.items():
        if not (REPO / old).is_file() or not (REPO / relative).is_file(): bad.append(f"compatibility_missing:{old}")
    return {"name": "compatibility", "violations": bad, "compatibility_wrapper_count": len(targets)}


def single_source():
    state = _json(FAST / "state" / "FAST3_STATE.json")
    registry = _json(FAST / "manifests" / "registries" / "FAST3_STAGE_REGISTRY.json")
    status = (FAST / "FAST3_STATUS.md").read_text(encoding="utf-8")
    current = next((x for x in registry["stages"] if x["stage_id"] == state["current_stage"]), None)
    bad = []
    if current is None or current["status"] != state["current_status"]: bad.append("stage_state_registry_mismatch")
    if state["current_stage"] not in status or state["current_status"] not in status: bad.append("stage_state_status_mismatch")
    if state["live_trading_allowed"] or state["confirmation_read_count"] != 0: bad.append("unsafe_state")
    if Path(state.get("result_root", "")) != EXTERNAL_RESULTS_ROOT: bad.append("result_root_mismatch")
    if Path(state.get("data_root", "")) != EXTERNAL_DATA_ROOT: bad.append("data_root_mismatch")
    contract = FAST / "configs" / "contracts" / "FAST3_002_EXECUTABLE_CONTRACT.json"
    raw = _json(contract); claimed = raw.pop("config_sha256")
    actual = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if claimed != actual or state["contract_hashes"].get("FAST3-002") != claimed: bad.append("frozen_contract_hash_mismatch")
    return {"name": "single_source", "violations": bad}


def result_routing():
    state = _json(FAST / "state" / "FAST3_STATE.json")
    registry_path = EXTERNAL_RESULTS_ROOT / "FAST3_RESULTS_REGISTRY.json"
    latest_path = EXTERNAL_RESULTS_ROOT / "FAST3_LATEST.json"
    bad = []
    if Path(state["result_root"]) != EXTERNAL_RESULTS_ROOT: bad.append("state_result_root")
    if not registry_path.is_file() or not latest_path.is_file(): bad.append("external_result_registry_missing")
    production = list((FAST / "scripts" / "run").glob("*.py"))
    forbidden = (".local_results", "fast3\\outputs", "fast3/outputs", "fast3\\stages", "fast3/stages")
    internal_writes = [p.relative_to(FAST).as_posix() for p in production if any(x in p.read_text(encoding="utf-8", errors="ignore") for x in forbidden)]
    if internal_writes: bad.extend(f"internal_result_write:{x}" for x in internal_writes)
    for root in (REPO / ".local_results", REPO / "outputs"):
        if root.exists():
            fast3_files = [p for p in root.rglob("*") if p.is_file() and re.search(r"FAST3|V22[._-]?0(49|65|66|69|70|71|72|73|74|75|76|77|78|79|80|81|82|83|84|85|86)", p.as_posix(), re.I)]
            if fast3_files: bad.append(f"repository_result_files:{root.name}:{len(fast3_files)}")
    canonical_count = {}
    if registry_path.is_file():
        for item in _json(registry_path).get("results", []):
            if item.get("canonical"):
                stage = item.get("stage_id"); canonical_count[stage] = canonical_count.get(stage, 0) + 1
                result_path = Path(item.get("result_path", ""))
                if result_path.parent != EXTERNAL_RESULTS_ROOT or not result_path.is_dir(): bad.append(f"canonical_result_path:{stage}")
                elif sum(1 for p in result_path.rglob("*") if p.is_file()) > RESULT_FILE_BUDGET: bad.append(f"result_file_budget:{stage}")
                elif any(p.suffix.lower() in {".pickle", ".pkl", ".joblib"} for p in result_path.rglob("*")): bad.append(f"forbidden_result_binary:{stage}")
    bad.extend(f"duplicate_canonical_result:{stage}" for stage, count in canonical_count.items() if count > 1)
    return {"name": "result_routing", "violations": bad, "repository_internal_result_write_count": len(internal_writes), "local_result_reference_count": sum(1 for p in production if ".local_results" in p.read_text(encoding="utf-8", errors="ignore"))}


def forbidden_patterns():
    targets = list((FAST / "src").rglob("*.py")) + list((FAST / "scripts" / "run").glob("*.py"))
    direct = []; hacks = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?:from|import)\s+scripts\.v22|Path\([^\n]*scripts[/\\]v22", text): direct.append(path.relative_to(FAST).as_posix())
        if "sys" + ".path" in text: hacks.append(path.relative_to(FAST).as_posix())
    return {"name": "forbidden_patterns", "violations": [f"legacy_import:{x}" for x in direct] + [f"sys_path:{x}" for x in hacks], "direct_legacy_v22_import_count": len(direct), "sys_path_hack_count": len(hacks)}


def write_file_registry():
    tracked = set(subprocess.run(["git", "ls-files"], cwd=REPO, text=True, capture_output=True, check=False).stdout.splitlines())
    rows = []
    for path in _files():
        if path == FAST / "manifests" / "registries" / "FAST3_FILE_REGISTRY.json":
            continue
        rel = path.relative_to(REPO).as_posix()
        legacy = "legacy/" in path.relative_to(FAST).as_posix()
        rows.append({"path": rel, "owner_stage": "legacy" if legacy else "FAST3-003", "category": path.suffix.lstrip(".") or "file", "canonical": not legacy,
                     "generated": path.name.endswith(("SUMMARY.json", "TEST_EVIDENCE.json")), "tracked": rel in tracked, "external": False,
                     "deprecated": legacy, "replacement": None, "reason": "FAST3 legacy archive" if legacy else "FAST3 canonical project file", "sha256": _hash(path)})
    for name in ("CODEX_GOAL.md", "CODEX_PLAN.md", "CODEX_STATUS.md"):
        path = REPO / name
        if path.is_file():
            rows.append({"path": name, "owner_stage": "repository", "category": "md", "canonical": True,
                         "generated": False, "tracked": name in tracked, "external": False, "deprecated": False,
                         "replacement": None, "reason": "repository-level active instruction required by AGENTS.md", "sha256": _hash(path)})
    out = FAST / "manifests" / "registries" / "FAST3_FILE_REGISTRY.json"
    out.write_text(json.dumps({"schema_version": "1.0.0", "files": rows}, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--write-file-registry", action="store_true"); args = parser.parse_args(argv)
    if args.write_file_registry: write_file_registry()
    checks = [architecture(), bloat(), single_source(), registry_hygiene(), forbidden_patterns(), compatibility(), result_routing()]
    violations = [v for check in checks for v in check["violations"]]
    result = {"status": "PASS" if not violations else "FAIL", "checks": checks, "violations": violations}
    print(json.dumps(result, indent=2))
    return 0 if not violations else 1

if __name__ == "__main__": raise SystemExit(main())
