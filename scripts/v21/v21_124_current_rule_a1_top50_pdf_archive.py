from pathlib import Path
import json
import pandas as pd
from datetime import datetime

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
except ImportError as e:
    raise SystemExit("Missing reportlab. Run: python -m pip install reportlab") from e


STAGE = "V21.124_CURRENT_RULE_A1_TOP50_PDF_ARCHIVE"

SOURCE = Path("outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST/daily_A1_top50_full_ledger.csv")
OUTDIR = Path("outputs/v21") / STAGE
OUTDIR.mkdir(parents=True, exist_ok=True)

if not SOURCE.exists():
    raise SystemExit(f"Missing source file: {SOURCE}")

df = pd.read_csv(SOURCE)
if df.empty:
    raise SystemExit(f"Source file is empty: {SOURCE}")

cols_lower = {c.lower(): c for c in df.columns}

ticker_col = next((cols_lower[c] for c in cols_lower if c in ["ticker", "symbol"]), None)
rank_col = next((cols_lower[c] for c in cols_lower if c in ["rank", "final_rank", "ranking"]), None)
score_col = next((cols_lower[c] for c in cols_lower if c in ["score", "final_score", "total_score"]), None)
date_col = next((cols_lower[c] for c in cols_lower if c in ["ranking_date", "date", "asof_date", "as_of_date"]), None)
variant_col = next((cols_lower[c] for c in cols_lower if c in ["strategy", "variant", "strategy_variant", "model_variant"]), None)

if not ticker_col or not rank_col:
    raise SystemExit(f"Required columns missing. columns={list(df.columns)}")

x = df.copy()

if variant_col:
    x = x[x[variant_col].astype(str).eq("A1_BASELINE_CONTROL")]

if x.empty:
    raise SystemExit("No A1_BASELINE_CONTROL rows found.")

if date_col:
    latest_date = sorted(x[date_col].astype(str).dropna().unique())[-1]
    x = x[x[date_col].astype(str).eq(latest_date)]
else:
    latest_date = "UNKNOWN"

x[rank_col] = pd.to_numeric(x[rank_col], errors="coerce")
top50 = x[x[rank_col].between(1, 50)].sort_values(rank_col).copy()

if len(top50) < 50:
    raise SystemExit(f"Top50 incomplete. Found only {len(top50)} rows for latest_date={latest_date}")

export_cols = [rank_col, ticker_col]
if score_col:
    export_cols.append(score_col)

top50_export = top50[export_cols].copy()
top50_export.columns = ["rank", "ticker"] + (["score"] if score_col else [])

if "score" in top50_export.columns:
    top50_export["score"] = pd.to_numeric(top50_export["score"], errors="coerce").round(6)

csv_path = OUTDIR / f"current_rule_A1_top50_{latest_date}.csv"
pdf_path = OUTDIR / f"current_rule_A1_top50_{latest_date}.pdf"
manifest_path = OUTDIR / "V21.124_manifest.json"

top50_export.to_csv(csv_path, index=False, encoding="utf-8-sig")

styles = getSampleStyleSheet()
title_style = ParagraphStyle(
    "TitleCustom",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=16,
    leading=20,
    alignment=1,
)
normal = ParagraphStyle(
    "NormalCustom",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=8,
    leading=10,
)
small = ParagraphStyle(
    "SmallCustom",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=7,
    leading=9,
)

doc = SimpleDocTemplate(
    str(pdf_path),
    pagesize=A4,
    rightMargin=12 * mm,
    leftMargin=12 * mm,
    topMargin=12 * mm,
    bottomMargin=12 * mm,
)

story = []
story.append(Paragraph("Current Rule A1 Top50 Archive", title_style))
story.append(Spacer(1, 4 * mm))

meta_lines = [
    f"Stage: {STAGE}",
    f"Current rule variant: A1_BASELINE_CONTROL",
    f"Latest ranking date used: {latest_date}",
    f"Source file: {SOURCE.as_posix()}",
    "Current hierarchy: A1 primary evidence leader; B/C secondary research candidates; D_R2C frozen tracking only; original D downgraded reference.",
    "Official adoption allowed: false",
    "Broker action allowed: false",
    "Research only: true",
    f"Generated at local time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
]
for line in meta_lines:
    story.append(Paragraph(line, normal))

story.append(Spacer(1, 5 * mm))

table_data = [["Rank", "Ticker", "Score"]]
for _, r in top50_export.iterrows():
    rank = int(r["rank"])
    ticker = str(r["ticker"])
    score = "" if "score" not in top50_export.columns else f"{float(r['score']):.6f}"
    table_data.append([rank, ticker, score])

table = Table(table_data, colWidths=[20 * mm, 35 * mm, 35 * mm], repeatRows=1)
table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("ALIGN", (0, 0), (0, -1), "RIGHT"),
    ("ALIGN", (1, 0), (1, -1), "LEFT"),
    ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story.append(table)

story.append(Spacer(1, 5 * mm))
story.append(Paragraph(
    "Note: This archive records the current-rule A1 Top50 only. It is not an official trading list, not an adoption decision, and not a broker action instruction.",
    small
))

doc.build(story)

manifest = {
    "stage": STAGE,
    "FINAL_STATUS": "PASS_V21_124_CURRENT_RULE_A1_TOP50_PDF_ARCHIVED",
    "DECISION": "CURRENT_RULE_A1_TOP50_ARCHIVED_RESEARCH_ONLY",
    "latest_ranking_date_used": latest_date,
    "current_rule_variant": "A1_BASELINE_CONTROL",
    "source_file": SOURCE.as_posix(),
    "pdf_path": pdf_path.as_posix(),
    "csv_path": csv_path.as_posix(),
    "top50_count": int(len(top50_export)),
    "protected_outputs_modified": False,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "research_only": True,
    "model_parameters_changed": False,
    "rankings_recomputed": False,
    "new_strategy_variants_created": False,
    "generated_at": datetime.now().isoformat(timespec="seconds"),
}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

print(json.dumps(manifest, indent=2))
