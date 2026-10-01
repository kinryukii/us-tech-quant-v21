"""Fixed-spec, no-test numerical reproduction of the two sealed OOF folds."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/bundle")
OUT = Path("/out")
sys.path.insert(0, str(ROOT))
from fit_supervised import FEATURES, FOLDS, SEEDS, SPECS, model_for  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    source = json.loads((ROOT / "input_manifest.json").read_text())
    supervised = json.loads((ROOT / "supervised_manifest.json").read_text())
    if (sha(ROOT / "data/panel.parquet") != source["panel_sha256"]
            or sha(ROOT / "pre2026_oof.parquet") != supervised["oof_sha256"]):
        raise RuntimeError("REPRODUCTION_INPUT_HASH_MISMATCH")
    panel = pd.read_parquet(ROOT / "data/panel.parquet")
    oof = pd.read_parquet(ROOT / "pre2026_oof.parquet")
    mature = (panel.label_end_date_5.notna() & np.isfinite(panel.y5)
              & np.isfinite(panel.y5_cost_positive))
    results = []
    fit_count = 0
    for fold, start, stop in FOLDS:
        train = panel.loc[panel.signal_date.lt(start) & panel.label_end_date_5.lt(start)
                          & mature].copy()
        valid = panel.loc[panel.signal_date.ge(start) & panel.signal_date.lt(stop)].copy()
        original = oof.loc[oof.fold.eq(fold)].reset_index(drop=True)
        valid = valid.reset_index(drop=True)
        for key in ("signal_date", "ticker", "security_id"):
            if not valid[key].equals(original[key]):
                raise RuntimeError(f"OOF_ROW_ALIGNMENT:{fold}:{key}")
        if train.label_end_date_5.max() >= start or valid.signal_date.max() >= stop:
            raise RuntimeError(f"FOLD_DATE_BOUNDARY:{fold}")
        mlp_predictions = []
        for name in SPECS:
            for seed in (SEEDS if name == "MLP" else SEEDS[:1]):
                model = model_for(name, seed)
                label = train.y5_cost_positive if name == "LOGISTIC" else train.y5
                model.fit(train[FEATURES], label)
                fit_count += 1
                predicted = (model.predict_proba(valid[FEATURES])[:, 1] if name == "LOGISTIC"
                             else model.predict(valid[FEATURES]))
                column = f"pred_{name.lower()}" + (f"_{seed}" if name == "MLP" else "")
                reference = original[column].to_numpy(float)
                difference = float(np.max(np.abs(predicted - reference)))
                if not np.isfinite(difference) or difference > 1e-7:
                    raise RuntimeError(f"OOF_NUMERIC_MISMATCH:{fold}:{column}:{difference}")
                results.append({"fold": fold, "model": name, "seed": seed,
                                "max_absolute_prediction_difference": difference,
                                "train_rows": len(train),
                                "train_max_mature_label": str(train.label_end_date_5.max().date()),
                                "valid_rows": len(valid)})
                if name == "MLP":
                    mlp_predictions.append(predicted)
        mean_diff = float(np.max(np.abs(0.5 * (mlp_predictions[0] + mlp_predictions[1])
                                        - original.pred_mlp_mean.to_numpy(float))))
        if mean_diff > 1e-7:
            raise RuntimeError(f"OOF_MLP_ENSEMBLE_MISMATCH:{fold}:{mean_diff}")
    if fit_count != 18 or len(oof) != 20000:
        raise RuntimeError("OOF_REPRODUCTION_COUNT")
    receipt = {"status": "FIXED_SPEC_OOF_NUMERIC_REPRODUCTION_PASS",
               "verification_fits_only": fit_count,
               "oof_rows": len(oof),
               "maximum_prediction_difference": max(row["max_absolute_prediction_difference"]
                                                for row in results),
               "fits": results,
               "scope": "pre-2026 sealed panel/OOF only; no model selection or 2026 source"}
    (OUT / "oof_reproduction_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in
                      ("status", "verification_fits_only", "oof_rows",
                       "maximum_prediction_difference")}))


if __name__ == "__main__":
    main()
