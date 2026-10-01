"""Prove log-only startup fixes did not change the preserved partial policy path."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from replay import write, sha


def compare_frames(before, after):
    assert list(before.columns) == list(after.columns)
    dates = sorted(before.signal_date.unique())
    after = after.loc[after.signal_date.isin(dates)].reset_index(drop=True)
    before = before.reset_index(drop=True)
    assert len(before) == len(after)
    numeric_error = {}
    for name in before:
        left, right = before[name], after[name]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            a, b = left.to_numpy(float), right.to_numpy(float)
            assert np.allclose(a, b, rtol=1e-10, atol=1e-12, equal_nan=True), name
            numeric_error[name] = float(np.nanmax(np.abs(a-b))) if len(a) else 0.
        else:
            assert left.equals(right), name
    return dict(rows=len(before), signals=len(dates), numeric_max_abs_difference=numeric_error,
                values_reconciled=True, type_only_change_permitted="reserved_weight int0 normalized to float0 in pair log")


def main():
    base = ROOT / "evaluation_2025/cost_10"
    failed, completed = base/"M0_stream_schema_failure_02", base/"M0"
    # The pairs ended one signal before the action diagnostics; each has its
    # own date set and both are compared without extending the preserved data.
    result = dict(status="PASS", no_retraining=True, repairs="source-file collector and float log serialization only",
        files={name: dict(**compare_frames(pd.read_parquet(failed/name), pd.read_parquet(completed/name)),
                         preserved_sha256=sha(failed/name), completed_sha256=sha(completed/name))
               for name in ["action_diagnostics.parquet", "same_account_pair.parquet"]})
    write(base / "RECOVERY_PREFIX_PROOF.json", result)
    print({name: (record["rows"], record["signals"], max(record["numeric_max_abs_difference"].values(), default=0.))
           for name, record in result["files"].items()})


if __name__ == "__main__":
    main()
