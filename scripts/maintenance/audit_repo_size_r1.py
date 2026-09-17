"""Compatibility CLI for the canonical, metadata-only repository budget check."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def audit(root: Path = ROOT) -> dict:
    # Keep the historical CLI; the existing guard owns accounting and thresholds.
    from fast3.scripts.audit.run_fast3_guard import repository_budget, repository_policy

    budget = repository_budget(root)
    limits = repository_policy()
    complete = budget["accounting_complete"]
    return {
        **budget,
        "repo_root": str(root),
        "repo_size_bytes": budget["repository_worktree_bytes"] + budget["git_database_bytes"],
        "size_is_lower_bound": not complete,
        "soft_warning": budget["repository_worktree_bytes"] >= limits["preferred_bytes"],
        "hard_limit_bytes": limits["required_maximum_bytes"],
        "hard_limit_passed": complete and not budget["violations"],
        "large_files": [
            {"path": str(root / row["path"]), "size_bytes": row["bytes"]}
            for row in budget["oversized_files"]
        ],
        "budget_scope": "worktree; Git database reported separately",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from scripts.common.storage_paths import assert_safe_output_path

    output = Path(args.json).resolve()
    assert_safe_output_path(output)
    report = audit()
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["hard_limit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
