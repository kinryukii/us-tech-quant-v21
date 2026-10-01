"""Exercise the existing inventory CLI; do not implement a second search."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from build_retrospective import OUT, sha
from stage_registry_patch import ENTITY_ID


def main():
    receipt = json.loads((OUT / "REGISTRY_UPDATE_RECEIPT.json").read_text(encoding="utf-8"))
    executable = "D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe"
    source = "D:/us-tech-quant/scripts/maintenance/research_inventory.py"
    results = []
    for term in ["fusion_conditional_gate", "NNLS", "a2_cooperative_fusion_20260928_9231"]:
        command = [executable, "-X", "utf8", "-B", source, "query", "--repo-root", "D:/us-tech-quant", "--text", term]
        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        assert run.returncode == 0, (term, run.stderr, run.stdout)
        actual = json.loads(run.stdout)
        assert actual["registry_head_sha256"] == receipt["new_head_sha256"]
        entity = next(e for e in actual["entities"] if e["entity_id"] == ENTITY_ID)
        knowledge = entity["metadata"]["related_task_knowledge_refs"]
        item = next(k for k in knowledge if k["task_id"] == "TOP20_MULTIMODEL_COOPERATION_20260928_9231")
        assert item["report_ref"] == receipt["report_ref"]
        assert item["report_sha256"] == sha(Path(item["report_ref"]))
        assert actual["new_research_authorized"] is False
        results.append({"query": term, "cli_exit_code": run.returncode, "existing_cli_status": actual["status"], "matching_entity_ids": [e["entity_id"] for e in actual["entities"]], "expected_task_reference_found": True, "found_report_ref": item["report_ref"], "found_report_sha256": item["report_sha256"], "new_research_authorized": False})
    out = {"status": "PASS", "created_utc": datetime.now(timezone.utc).isoformat(), "existing_cli": source, "existing_cli_sha256": sha(Path(source)), "registry_head_sha256": receipt["new_head_sha256"], "checks": results, "mutations": 0}
    (OUT / "REGISTRY_DISCOVERY_CHECK.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "query_count": len(results), "expected_reference_found_for_all": True, "mutations": 0}))


if __name__ == "__main__":
    main()
