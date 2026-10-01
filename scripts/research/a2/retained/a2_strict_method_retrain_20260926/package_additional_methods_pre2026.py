"""Append independent pre-2026 method artifacts; stream-copy with hash checks."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "additional_methods_20260927"
DEST = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\additional_methods_pre2026_20260927")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    assert not DEST.exists(), f"Refuse overwrite: {DEST}"
    audit = json.loads((SOURCE / "INTEGRATED_AUDIT.json").read_text("utf-8"))
    assert audit["status"] == "IDENTITIES_AND_PRE2026_CUTOFF_VERIFIED_NO_2026_METHOD_TEST"
    files = sorted(p for p in SOURCE.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    assert files and len(files) >= 100
    assert not any(p.name in {"training_matrix.parquet", "pre2026_original_price_coordinate.parquet"} for p in files)
    DEST.mkdir(parents=False)
    rows = []
    for source in files:
        rel = source.relative_to(SOURCE)
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        digest = sha(source)
        assert sha(target) == digest, rel
        rows.append({"relative_path": rel.as_posix(), "bytes": target.stat().st_size, "sha256": digest})
    with (DEST / "FILE_MANIFEST.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"path": str(DEST), "files": len(rows), "bytes": sum(r["bytes"] for r in rows),
                      "test2026_fit_calls": audit["original_four_fit_calls_in_test2026"]}))


if __name__ == "__main__":
    main()
