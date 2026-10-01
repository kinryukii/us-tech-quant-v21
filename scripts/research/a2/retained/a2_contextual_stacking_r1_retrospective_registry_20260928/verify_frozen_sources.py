"""Check existing sealed byte inventories; writes only this new documentation task."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    original = WORKSPACE / "a2_contextual_stacking_r1_20260928"
    old = json.loads((original / "OLD_SOURCE_BEFORE.json").read_text(encoding="utf-8"))
    manifest = json.loads((original / "ARTIFACT_MANIFEST.json").read_text(encoding="utf-8"))
    completion = json.loads((original / "COMPLETION.json").read_text(encoding="utf-8"))
    expected = {Path(path): digest for path, digest in old["files"].items()}
    expected.update({original / path: item["sha256"] for path, item in manifest["files"].items()})
    expected[original / "ARTIFACT_MANIFEST.json"] = completion["manifest_sha256"]
    missing = [str(path) for path in expected if not path.is_file()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        actual = dict(zip(expected, pool.map(sha, expected))) if not missing else {}
    changed = [str(path) for path, digest in expected.items() if actual.get(path) != digest]
    actual_inventory = {path.resolve() for directory in [*old["roots"], str(original)] for path in Path(directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts and path.suffix != ".pyc"}
    # Original completion seals manifest/report; completion is a subsequent write-once receipt.
    permitted_extra = {(original / "COMPLETION.json").resolve()}
    added = sorted(str(path) for path in actual_inventory - {path.resolve() for path in expected} - permitted_extra)
    result = {
        "status": "PASS" if not (missing or changed or added) else "FAIL",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "old_training_and_review_files_checked": len(old["files"]),
        "r1_manifest_files_checked": len(manifest["files"]),
        "r1_manifest_sha_matches_completion": actual.get(original / "ARTIFACT_MANIFEST.json") == completion["manifest_sha256"],
        "files_checked": len(expected), "missing": missing, "changed": changed, "added": added,
        "r1_completion_sha256": sha(original / "COMPLETION.json"),
        "new_fit_calls": 0, "new_portfolio_replays": 0,
        "method": "Streamed SHA256 against existing old-source seal and R1 delivery manifest; original cache exclusions preserved; no model imports or replay",
    }
    (HERE / "FROZEN_SOURCE_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
