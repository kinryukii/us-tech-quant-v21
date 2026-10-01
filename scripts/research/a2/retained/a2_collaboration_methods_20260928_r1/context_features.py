"""Only signal-known cross-sectional states; labels never enter context features."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
CONTEXTS = ["g_ret20mean", "g_vol20mean", "g_breadth_ma20", "g_disagreement"]


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def attach_context(panel):
    panel = panel.copy()
    if panel.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("DUPLICATE_CONTEXT_KEY")
    panel["_breadth"] = panel.price_vs_ma20.gt(0).astype(float)
    panel["_disagreement"] = panel[["p_ridge", "p_hgb", "p_mlp"]].to_numpy(float).std(axis=1)
    # Held-only context rows are available to the account but are not new pool members.
    pool = panel.loc[panel.new_buy_eligible.astype(bool)] if "new_buy_eligible" in panel else panel
    grouped = pool.groupby("signal_date", sort=False)
    for output, source in [("g_ret20mean", "ret_20d"), ("g_vol20mean", "realized_vol_20d"),
                           ("g_breadth_ma20", "_breadth"), ("g_disagreement", "_disagreement")]:
        panel[output] = panel.signal_date.map(grouped[source].mean())
    panel.drop(columns=["_breadth", "_disagreement"], inplace=True)
    if not np.isfinite(panel[CONTEXTS].to_numpy(float)).all():
        raise ValueError("NONFINITE_SIGNAL_CONTEXT")
    return panel


def main():
    output = ROOT / "OOF_WITH_CONTEXT.parquet"
    if output.exists():
        raise RuntimeError("EXISTING_OOF_CONTEXT_PRESERVED")
    oof_path = ROOT / "base_artifacts/OOF_PREDICTIONS.parquet"
    hashes = {str(p): sha(p) for p in [SOURCE, oof_path, Path(__file__)]}
    oof = pd.read_parquet(oof_path)
    known = pd.read_parquet(SOURCE, columns=["signal_date", "ticker", "ret_20d", "realized_vol_20d", "price_vs_ma20"])
    frame = oof.merge(known, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    frame = attach_context(frame)
    assert frame.signal_date.dt.year.isin([2024, 2025]).all()
    assert (pd.to_datetime(frame.base_cutoff) <= frame.signal_date).all()
    frame.to_parquet(output, index=False)
    assert all(sha(path) == digest for path, digest in hashes.items())
    (ROOT / "CONTEXT_RECEIPT.json").write_text(json.dumps({
        "status": "PASS", "source_sha256": hashes, "rows": len(frame),
        "contexts": CONTEXTS, "only_signal_known_fields": True,
        "state_pool": "all supplied new-buy-eligible candidates; broadcast unchanged to held-only rows",
        "future_label_fields_used_for_context": [], "2026_rows": 0, "fit_calls": 0,
        "output_sha256": sha(output)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OOF_CONTEXT_COMPLETE", "rows": len(frame)}), flush=True)


if __name__ == "__main__":
    main()
