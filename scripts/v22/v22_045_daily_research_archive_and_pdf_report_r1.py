#!/usr/bin/env python
"""V22.045 daily research archive and PDF report R1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVISION = "V22.045_R1"
STAGE = "V22.045_DAILY_RESEARCH_ARCHIVE_AND_PDF_REPORT_R1"
OUT_REL = Path("outputs/v22") / STAGE
ARCHIVE_BASE_REL = Path("outputs/v22/daily_research_archives")

PASS_STATUS = "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_CREATED"
PASS_DECISION = "DAILY_RESEARCH_ARCHIVE_CREATED_RESEARCH_ONLY"
DRY_RUN_STATUS = "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_DRY_RUN_VALIDATED"
DRY_RUN_DECISION = "DAILY_RESEARCH_ARCHIVE_VALIDATED_EXECUTE_REQUIRED"

POINTER_JSON_REL = Path("outputs/v22/current_daily_research_entrypoint.json")
POINTER_MD_REL = Path("outputs/v22/CURRENT_DAILY_RESEARCH_ENTRYPOINT.md")
V22_044_SUMMARY_REL = Path("outputs/v22/V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1/v22_044_summary.json")
DEFAULT_V22_040_SUMMARY_REL = Path("outputs/v22/V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1/v22_040_summary.json")
ABCDE_DIR_REL = Path("outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN")

RECOMMENDED_COMMAND = r".\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute"
ACCEPTED_CHILD_COMMAND = r".\scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1 -Execute"
EXPECTED_POINTER_ENTRYPOINT = "V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1"
EXPECTED_V22_044_STATUS = "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN"
EXPECTED_V22_044_DECISION = "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT"
EXPECTED_V22_040_STATUS = "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE"
EXPECTED_V22_040_DECISION = "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY"

ABCDE_REQUIRED_FOR_ARCHIVE = [
    "abcde_strategy_ranking_master.csv",
    "abcde_top50_summary.csv",
    "abcde_top20_summary.csv",
    "abcde_strategy_overlap_matrix.csv",
    "abcde_canonical_snapshot_audit.csv",
    "abcde_coverage_audit.csv",
    "abcde_feature_audit.csv",
    "abcde_latest_date_audit.csv",
    "abcde_missing_audit.csv",
    "abcde_source_audit.csv",
]
ABCDE_HARD_REQUIRED = [
    "abcde_strategy_ranking_master.csv",
    "abcde_top20_summary.csv",
    "abcde_top50_summary.csv",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def date_text(value: Any) -> str:
    return str(value or "").strip()[:10]


def bool_false(value: Any) -> bool:
    return value is False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_or_abs(repo_root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = repo_root / path
    return path


def fail_status_for(failed: list[str]) -> str:
    if any(name.startswith("entrypoint_pointer") for name in failed):
        return "FAIL_V22_045_ENTRYPOINT_POINTER_MISSING"
    if "v22_044_summary_exists" in failed:
        return "FAIL_V22_045_V22_044_SUMMARY_MISSING"
    if any(name.startswith("v22_044_") or name == "accepted_child_command_points_to_v22_040" for name in failed):
        return "FAIL_V22_045_V22_044_NOT_ACCEPTED"
    if "v22_040_summary_exists" in failed:
        return "FAIL_V22_045_V22_040_SUMMARY_MISSING"
    if any(name.startswith("v22_040_") for name in failed):
        return "FAIL_V22_045_V22_040_NOT_PASS"
    if any(name in failed for name in ["dates_exist", "dates_equal", "same_date_comparable_all_strategies", "data_gap_days_zero"]):
        return "FAIL_V22_045_DATE_ALIGNMENT_FAILED"
    if any(name.endswith("_false") for name in failed):
        return "FAIL_V22_045_RESEARCH_ONLY_GATE_FAILED"
    if any(name.startswith("abcde_") for name in failed):
        return "FAIL_V22_045_REQUIRED_ABCDE_FILES_MISSING"
    return "FAIL_V22_045_ARCHIVE_MANIFEST_FAILED"


def base_summary(repo_root: Path, execute: bool, output_dir: Path) -> dict[str, Any]:
    return {
        "revision": REVISION,
        "stage": STAGE,
        "run_mode": "EXECUTE" if execute else "DRY_RUN",
        "run_start_utc": utc_now(),
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "summary_path": str(output_dir / "v22_045_summary.json"),
        "archive_accepted": False,
        "latest_research_date": "",
        "archive_root": "",
        "archive_zip_path": "",
        "markdown_report_path": "",
        "pdf_report_path": "",
        "source_inventory_path": "",
        "archive_manifest_csv_path": "",
        "archive_manifest_json_path": "",
        "copied_file_count": 0,
        "total_archived_bytes": 0,
        "sha256_manifest_written": False,
        "v22_044_summary_path": str(repo_root / V22_044_SUMMARY_REL),
        "v22_040_summary_path": str(repo_root / DEFAULT_V22_040_SUMMARY_REL),
        "canonical_latest_date": "",
        "abcde_latest_date": "",
        "dram_latest_price_date": "",
        "same_date_comparable_all_strategies": False,
        "data_gap_days": None,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
        "direct_market_data_fetch_attempted": False,
        "direct_child_strategy_invocation_attempted": False,
        "source_files_mutated": False,
        "hard_gate_passed": False,
        "failed_gate_names": [],
        "warning_count": 0,
        "warnings": [],
        "recommended_daily_refresh_command": RECOMMENDED_COMMAND,
        "accepted_child_orchestrator": ACCEPTED_CHILD_COMMAND,
        "source_inventory": [],
    }


def validate_gates(repo_root: Path, summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    failed: list[str] = []
    warnings: list[str] = []

    pointer_json_path = repo_root / POINTER_JSON_REL
    pointer_md_path = repo_root / POINTER_MD_REL
    pointer = read_json(pointer_json_path) if pointer_json_path.exists() else {}
    if not pointer_json_path.exists():
        failed.append("entrypoint_pointer_json_exists")
    elif pointer.get("accepted_current_entrypoint_name") != EXPECTED_POINTER_ENTRYPOINT:
        failed.append("entrypoint_pointer_identifies_v22_044")
    if not pointer_md_path.exists():
        failed.append("entrypoint_pointer_markdown_exists")

    v22_044_path = repo_root / V22_044_SUMMARY_REL
    v22_044 = read_json(v22_044_path) if v22_044_path.exists() else {}
    if not v22_044_path.exists():
        failed.append("v22_044_summary_exists")
    else:
        if v22_044.get("final_status") != EXPECTED_V22_044_STATUS:
            failed.append("v22_044_final_status")
        if v22_044.get("final_decision") != EXPECTED_V22_044_DECISION:
            failed.append("v22_044_final_decision")
        child_command = str(v22_044.get("child_v22_040_command") or v22_044.get("accepted_child_orchestrator_command") or "")
        if "run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1" not in child_command.lower():
            failed.append("accepted_child_command_points_to_v22_040")

    v22_040_path = rel_or_abs(repo_root, v22_044.get("v22_040_summary_path")) if v22_044 else None
    if v22_040_path is None:
        v22_040_path = repo_root / DEFAULT_V22_040_SUMMARY_REL
    summary["v22_040_summary_path"] = str(v22_040_path)
    v22_040 = read_json(v22_040_path) if v22_040_path.exists() else {}
    if not v22_040_path.exists():
        failed.append("v22_040_summary_exists")
    else:
        if v22_040.get("final_status") != EXPECTED_V22_040_STATUS:
            failed.append("v22_040_final_status")
        if v22_040.get("final_decision") != EXPECTED_V22_040_DECISION:
            failed.append("v22_040_final_decision")

    canonical = date_text(v22_040.get("canonical_latest_date"))
    abcde = date_text(v22_040.get("abcde_latest_date"))
    dram = date_text(v22_040.get("dram_latest_price_date"))
    summary["canonical_latest_date"] = canonical
    summary["abcde_latest_date"] = abcde
    summary["dram_latest_price_date"] = dram
    summary["latest_research_date"] = canonical or abcde or dram
    summary["same_date_comparable_all_strategies"] = v22_040.get("same_date_comparable_all_strategies") is True
    summary["data_gap_days"] = v22_040.get("data_gap_days")
    summary["broker_action_allowed"] = v22_040.get("broker_action_allowed")
    summary["official_adoption_allowed"] = v22_040.get("official_adoption_allowed")
    summary["factor_promotion_allowed"] = v22_040.get("factor_promotion_allowed", False)

    if not (canonical and abcde and dram):
        failed.append("dates_exist")
    if not (canonical and abcde and dram and canonical == abcde == dram):
        failed.append("dates_equal")
    if v22_040.get("same_date_comparable_all_strategies") is not True:
        failed.append("same_date_comparable_all_strategies")
    if v22_040.get("data_gap_days") != 0:
        failed.append("data_gap_days_zero")
    if not bool_false(v22_040.get("broker_action_allowed")):
        failed.append("broker_action_allowed_false")
    if not bool_false(v22_040.get("official_adoption_allowed")):
        failed.append("official_adoption_allowed_false")
    if "factor_promotion_allowed" in v22_040 and not bool_false(v22_040.get("factor_promotion_allowed")):
        failed.append("factor_promotion_allowed_false")

    abcde_dir = repo_root / ABCDE_DIR_REL
    if not abcde_dir.exists():
        failed.append("abcde_directory_exists")
    else:
        missing_hard = [name for name in ABCDE_HARD_REQUIRED if not (abcde_dir / name).exists()]
        if missing_hard:
            failed.append("abcde_master_top20_top50_exist")
            warnings.append("Missing required ABCDE hard files: " + ", ".join(missing_hard))

    summary["failed_gate_names"] = failed
    summary["hard_gate_passed"] = not failed
    summary["warnings"] = warnings
    summary["warning_count"] = len(warnings)
    return pointer, v22_044, v22_040


def add_warning(summary: dict[str, Any], warning: str) -> None:
    if warning not in summary["warnings"]:
        summary["warnings"].append(warning)
    summary["warning_count"] = len(summary["warnings"])


def discover_files(repo_root: Path, v22_040: dict[str, Any], summary: dict[str, Any]) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for group, rel in [
        ("entrypoint", POINTER_JSON_REL),
        ("entrypoint", POINTER_MD_REL),
        ("summaries", V22_044_SUMMARY_REL),
    ]:
        path = repo_root / rel
        if path.exists():
            files.append((group, path))

    v22_040_path = Path(summary["v22_040_summary_path"])
    if v22_040_path.exists():
        files.append(("summaries", v22_040_path))
    for child_path in (v22_040.get("child_summary_paths") or {}).values():
        path = rel_or_abs(repo_root, child_path)
        if path and path.exists():
            files.append(("summaries", path))

    abcde_dir = repo_root / ABCDE_DIR_REL
    for name in ABCDE_REQUIRED_FOR_ARCHIVE:
        path = abcde_dir / name
        if path.exists():
            files.append(("abcde", path))
        elif name not in ABCDE_HARD_REQUIRED:
            add_warning(summary, f"Optional ABCDE archive file not present: {name}")
    if abcde_dir.exists():
        for pattern in ["abcde_*audit*.csv", "abcde_*summary.csv", "abcde_*report.txt", "v21_233_summary.json"]:
            for path in sorted(abcde_dir.glob(pattern)):
                files.append(("abcde", path))

    dram_paths: list[Path] = []
    for child_key in ["V21.232", "dram", "DRAM"]:
        candidate = (v22_040.get("child_summary_paths") or {}).get(child_key)
        path = rel_or_abs(repo_root, candidate)
        if path and path.exists():
            dram_paths.append(path)
            for sibling in sorted(path.parent.glob("dram_*.*")):
                if sibling.is_file():
                    dram_paths.append(sibling)
    if dram_paths:
        for path in dram_paths:
            files.append(("dram", path))
    else:
        add_warning(summary, "Raw DRAM files are not discoverable; DRAM date and gate fields were retained from V22.040 summary.")

    forward_dirs = sorted((repo_root / "outputs/v22").glob("V22.043*"))
    if forward_dirs:
        for directory in forward_dirs:
            for path in sorted(directory.glob("*")):
                if path.is_file() and path.suffix.lower() in {".json", ".csv", ".txt", ".md"}:
                    files.append(("forward_optional", path))
    else:
        add_warning(summary, "Optional forward outcome files are missing or not mature; this is expected and not a V22.045 failure.")

    option_dirs = [
        directory
        for directory in sorted((repo_root / "outputs/v22").glob("V22.*OPTION*"))
        if directory.is_dir()
    ]
    if option_dirs:
        for directory in option_dirs:
            for path in sorted(directory.glob("*")):
                if path.is_file() and path.suffix.lower() in {".json", ".csv", ".txt", ".md"}:
                    files.append(("option_optional", path))
    else:
        add_warning(summary, "Optional option quote, IV, and Greeks audit files are missing.")

    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for group, path in files:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append((group, path))
    return deduped


def archive_name(group: str, path: Path, used: set[str]) -> str:
    name = path.name
    if name in used:
        name = f"{group}_{name}"
    used.add(name)
    return name


def copy_sources(archive_root: Path, sources: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    used_by_group: dict[str, set[str]] = {}
    for group, source in sources:
        used = used_by_group.setdefault(group, set())
        target_dir = archive_root / "raw" / group
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / archive_name(group, source, used)
        shutil.copy2(source, target)
        stat = source.stat()
        target_stat = target.stat()
        rows.append(
            {
                "source_group": group,
                "source_path": str(source),
                "archived_path": str(target),
                "archive_relative_path": str(target.relative_to(archive_root)).replace("\\", "/"),
                "file_size": target_stat.st_size,
                "source_modified_timestamp": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "sha256": sha256_file(target),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def report_markdown(summary: dict[str, Any], manifest_rows: list[dict[str, Any]]) -> str:
    copied = {Path(row["archived_path"]).name: row for row in manifest_rows}
    abcde_lines = []
    for label, name in [
        ("master ranking file", "abcde_strategy_ranking_master.csv"),
        ("Top20 file", "abcde_top20_summary.csv"),
        ("Top50 file", "abcde_top50_summary.csv"),
        ("overlap matrix file", "abcde_strategy_overlap_matrix.csv"),
        ("coverage audit", "abcde_coverage_audit.csv"),
        ("feature audit", "abcde_feature_audit.csv"),
        ("source audit", "abcde_source_audit.csv"),
        ("latest-date audit", "abcde_latest_date_audit.csv"),
        ("missing audit", "abcde_missing_audit.csv"),
    ]:
        abcde_lines.append(f"- {label}: {'present' if name in copied else 'not archived'}")

    dram_files = [row["archive_relative_path"] for row in manifest_rows if row["source_group"] == "dram"]
    forward_files = [row for row in manifest_rows if row["source_group"] == "forward_optional"]
    option_files = [row for row in manifest_rows if row["source_group"] == "option_optional"]
    final_decision = "accepted archive" if summary["archive_accepted"] else "failed archive"
    return "\n".join(
        [
            "# Daily Research Archive Audit Report",
            "",
            f"Revision: `{REVISION}`",
            f"Latest research date: `{summary['latest_research_date'] or 'UNAVAILABLE'}`",
            f"Recommended daily refresh command: `{RECOMMENDED_COMMAND}`",
            f"Accepted child orchestrator: `{ACCEPTED_CHILD_COMMAND}`",
            "",
            "## V22.044 Status",
            f"- status: `{summary.get('v22_044_final_status', 'UNAVAILABLE')}`",
            f"- summary path: `{summary['v22_044_summary_path']}`",
            "",
            "## V22.040 Status",
            f"- status: `{summary.get('v22_040_final_status', 'UNAVAILABLE')}`",
            f"- summary path: `{summary['v22_040_summary_path']}`",
            "",
            "## Date Alignment",
            f"- canonical latest date: `{summary['canonical_latest_date']}`",
            f"- ABCDE latest date: `{summary['abcde_latest_date']}`",
            f"- DRAM latest price date: `{summary['dram_latest_price_date']}`",
            f"- same-date comparable flag: `{summary['same_date_comparable_all_strategies']}`",
            f"- data gap days: `{summary['data_gap_days']}`",
            "",
            "## Research-Only Gates",
            f"- broker action allowed: `{summary['broker_action_allowed']}`",
            f"- official adoption allowed: `{summary['official_adoption_allowed']}`",
            f"- factor promotion allowed: `{summary['factor_promotion_allowed']}`",
            "",
            "## ABCDE Archive",
            *abcde_lines,
            "",
            "## DRAM Archive",
            f"- date: `{summary['dram_latest_price_date']}`",
            f"- discovered files: `{len(dram_files)}`",
            *[f"- {item}" for item in dram_files[:20]],
            "",
            "## Optional Forward Outcome",
            f"- V22.043 files discovered: `{len(forward_files)}`",
            "- If not mature, this is expected and not a V22.045 failure.",
            "",
            "## Optional Option Chain",
            f"- option audit files discovered: `{len(option_files)}`",
            "- Broker/trade action remains blocked.",
            "",
            "## Manifest Summary",
            f"- copied file count: `{summary['copied_file_count']}`",
            f"- total archived bytes: `{summary['total_archived_bytes']}`",
            f"- SHA256 manifest path: `{summary['archive_manifest_csv_path']}`",
            "",
            "## Final Decision",
            f"- `{final_decision}`",
            f"- final_status: `{summary['final_status']}`",
            f"- final_decision: `{summary['final_decision']}`",
            "",
            "## Safety Statement",
            "- research only",
            "- no broker action",
            "- no official adoption",
            "- no factor promotion",
            "- no direct market data fetch",
            "- no source ranking mutation",
            "",
        ]
    )


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_minimal_pdf(path: Path, markdown: str) -> None:
    lines: list[str] = []
    for raw in markdown.replace("`", "").replace("#", "").splitlines():
        text = raw.strip()
        if text:
            lines.append(text[:105])
    pages = [lines[i : i + 46] for i in range(0, len(lines), 46)] or [["Daily Research Archive Audit Report"]]
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    page_refs: list[str] = []
    for page in pages:
        stream_lines = ["BT", "/F1 10 Tf", "50 760 Td", "14 TL"]
        for line in page:
            stream_lines.append(f"({escape_pdf_text(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        content_obj_no = len(objects) + 2
        page_obj_no = len(objects) + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {len(pages) * 2 + 3} 0 R >> >> /Contents {content_obj_no} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_refs.append(f"{page_obj_no} 0 R")
    font_obj = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects.append(font_obj)
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_refs)} >>".encode()

    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode())
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(bytes(content))


def write_zip(archive_root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(archive_root.rglob("*")):
            if path.is_file() and path != zip_path:
                zf.write(path, path.relative_to(archive_root).as_posix())


def persist_primary_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    slim = dict(summary)
    slim.pop("source_inventory", None)
    write_json_atomic(output_dir / "v22_045_summary.json", slim)


def run(repo_root: Path, execute: bool = False) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = base_summary(repo_root, execute, output_dir)

    pointer, v22_044, v22_040 = validate_gates(repo_root, summary)
    summary["v22_044_final_status"] = v22_044.get("final_status", "")
    summary["v22_040_final_status"] = v22_040.get("final_status", "")

    if not summary["hard_gate_passed"]:
        summary["final_status"] = fail_status_for(summary["failed_gate_names"])
        summary["final_decision"] = "DAILY_RESEARCH_ARCHIVE_NOT_CREATED"
        summary["run_end_utc"] = utc_now()
        persist_primary_summary(output_dir, summary)
        return summary

    latest = summary["latest_research_date"] or "UNKNOWN_DATE"
    archive_root = repo_root / ARCHIVE_BASE_REL / latest / f"V22.045_{timestamp()}"
    summary["archive_root"] = str(archive_root)
    summary["archive_zip_path"] = str(archive_root / "daily_research_archive.zip")
    summary["markdown_report_path"] = str(archive_root / "daily_research_audit_report.md")
    summary["pdf_report_path"] = str(archive_root / "daily_research_audit_report.pdf")
    summary["source_inventory_path"] = str(archive_root / "source_inventory.csv")
    summary["archive_manifest_csv_path"] = str(archive_root / "archive_manifest.csv")
    summary["archive_manifest_json_path"] = str(archive_root / "archive_manifest.json")

    if not execute:
        summary["final_status"] = DRY_RUN_STATUS
        summary["final_decision"] = DRY_RUN_DECISION
        summary["archive_accepted"] = False
        summary["run_end_utc"] = utc_now()
        persist_primary_summary(output_dir, summary)
        return summary

    for rel in [
        "raw/entrypoint",
        "raw/summaries",
        "raw/abcde",
        "raw/dram",
        "raw/forward_optional",
        "raw/option_optional",
    ]:
        (archive_root / rel).mkdir(parents=True, exist_ok=True)

    sources = discover_files(repo_root, v22_040, summary)
    manifest_rows = copy_sources(archive_root, sources)
    summary["source_inventory"] = manifest_rows
    summary["copied_file_count"] = len(manifest_rows)
    summary["total_archived_bytes"] = sum(int(row["file_size"]) for row in manifest_rows)

    fields = [
        "source_group",
        "source_path",
        "archived_path",
        "archive_relative_path",
        "file_size",
        "source_modified_timestamp",
        "sha256",
    ]
    write_csv(Path(summary["source_inventory_path"]), manifest_rows, fields)
    write_csv(Path(summary["archive_manifest_csv_path"]), manifest_rows, fields)
    write_json_atomic(Path(summary["archive_manifest_json_path"]), {"revision": REVISION, "files": manifest_rows})
    summary["sha256_manifest_written"] = True

    summary["final_status"] = PASS_STATUS
    summary["final_decision"] = PASS_DECISION
    summary["archive_accepted"] = True
    markdown = report_markdown(summary, manifest_rows)
    Path(summary["markdown_report_path"]).write_text(markdown, encoding="utf-8")
    write_minimal_pdf(Path(summary["pdf_report_path"]), markdown)
    if not Path(summary["pdf_report_path"]).exists() or Path(summary["pdf_report_path"]).stat().st_size <= 0:
        summary["archive_accepted"] = False
        summary["final_status"] = "FAIL_V22_045_PDF_REPORT_MISSING"
        summary["final_decision"] = "DAILY_RESEARCH_ARCHIVE_NOT_CREATED"

    summary["run_end_utc"] = utc_now()
    persist_primary_summary(output_dir, summary)
    write_json_atomic(archive_root / "v22_045_summary.json", {k: v for k, v in summary.items() if k != "source_inventory"})
    if summary["archive_accepted"]:
        write_zip(archive_root, Path(summary["archive_zip_path"]))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    payload = run(args.repo_root, execute=args.execute)
    for key in [
        "final_status",
        "final_decision",
        "latest_research_date",
        "archive_root",
        "archive_zip_path",
        "markdown_report_path",
        "pdf_report_path",
        "source_inventory_path",
        "archive_manifest_csv_path",
        "archive_manifest_json_path",
        "copied_file_count",
        "total_archived_bytes",
        "warning_count",
        "canonical_latest_date",
        "abcde_latest_date",
        "dram_latest_price_date",
        "same_date_comparable_all_strategies",
        "data_gap_days",
        "broker_action_allowed",
        "official_adoption_allowed",
        "direct_market_data_fetch_attempted",
        "direct_child_strategy_invocation_attempted",
        "source_files_mutated",
    ]:
        print(f"{key}={payload.get(key)}")
    print("warnings=" + json.dumps(payload.get("warnings", []), ensure_ascii=False))
    print("failed_gate_names=" + json.dumps(payload.get("failed_gate_names", []), ensure_ascii=False))
    return 0 if str(payload.get("final_status", "")).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
