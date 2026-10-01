"""Pure selector cooperation over the retained statistical adapters; no I/O."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import nnls

UNIT = "Raw MEAN_ER_3D_5D_10D_20D decimal"
MEMBERS = ("ridge", "hgb", "xgb_rank", "logistic", "cat_uncertainty")
CONTEXT = ("ret_1d", "ret_20d", "realized_vol_20d", "realized_vol_60d", "volume_ratio_5d_20d")
METHODS = ("equal", "median", "fixed_weighted", "nnls", "simplex", "ridge_stack",
           "elastic_stack", "hgb_stack", "mlp_stack", "linear_gate", "mlp_gate",
           "ridge_then_hgb", "hgb_then_ridge")
SPEC = {"methods": METHODS, "unit": UNIT, "target_adapter": "y_next_open = target; values unchanged",
        "base_lineage": "MODEL_OOF, source_cutoff < signal_date, label_end_date < fit cutoff",
        "meta_lineage": "CALIBRATED_OOF; every member calibration_cutoff < signal_date and calibration_max_label_end < calibration_cutoff",
        "seed": 20260928, "max_rows": 40000, "sampling": "retained sample; deterministic day-balanced quota",
        "date_weighting": "retained date_weights; equal total weight per date",
        "contexts": CONTEXT, "fixed_members": MEMBERS, "fixed_weights": (.30, .25, .20, .15, .10),
        "nnls": "weighted scipy.optimize.nnls; nonnegative, unnormalized, no intercept",
        "uncertainty": "chronological date half; probe trained only on labels mature before boundary; second-half residual RMS and scale; future calibrator refit all earlier mature OOF",
        "probability_label": "target > 0", "svc": "raw decision score; not PROB",
        "residual": "root fits on 32 features against true stage1 annual OOF; not retained meta residual",
        "architecture_search": False}

@dataclass
class LinearFusion:
    method: str
    members: list
    coefficients: np.ndarray
    def predict(self, mu, context=None):
        x = np.asarray(mu, dtype=float)
        if x.ndim != 2 or x.shape[1] != len(self.members) or not np.isfinite(x).all():
            raise ValueError("INVALID_FUSION_MEMBER_MATRIX")
        return x @ self.coefficients


def _guard(frame, cutoff, kind):
    h = frame.copy()
    required = {"signal_date", "ticker", "security_uid", "U_t_fingerprint", "target",
                "label_end_date", "source_kind", "source_cutoff"}
    if not required.issubset(h) or h.empty or h[list(required)].isna().any().any():
        raise ValueError("MISSING_OOF_IDENTITY_OR_LINEAGE")
    cut = pd.Timestamp(cutoff)
    if cut > pd.Timestamp("2026-01-01"):
        raise ValueError("FIT_CUTOFF_AFTER_PRE2026")
    for key in ("signal_date", "label_end_date", "source_cutoff"):
        h[key] = pd.to_datetime(h[key])
    if (h.duplicated(["signal_date", "ticker"]).any() or not h.source_kind.eq(kind).all()
            or not h.source_cutoff.lt(h.signal_date).all()
            or not h.signal_date.lt(cut).all() or not h.label_end_date.lt(cut).all()
            or not np.isfinite(h.target.to_numpy(float)).all()):
        raise ValueError("OOF_LINEAGE_OR_MATURITY_VIOLATION")
    h["y_next_open"] = h.target
    return h, cut


def _sampling(module):
    if module.SEED != SPEC["seed"] or module.MAX_ROWS != SPEC["max_rows"]:
        raise ValueError("RETAINED_SAMPLING_SPEC_CHANGED")


def fit_calibration(module, name, history, cutoff):
    _sampling(module)
    h, cut = _guard(history, cutoff, "MODEL_OOF")
    if not np.isfinite(module.inputs(h, name)).all():
        raise ValueError("UNAVAILABLE_BASE_PREDICTION_DO_NOT_DROP")
    if name in module.DISTRIBUTION and (not np.isfinite(h[f"{name}__scale"]).all() or h[f"{name}__scale"].le(0).any()):
        raise ValueError("INVALID_BASE_DISTRIBUTION_SCALE_DO_NOT_DROP")
    dates = np.sort(h.signal_date.unique())
    if len(dates) < 2:
        raise ValueError("CHRONOLOGICAL_UNCERTAINTY_HISTORY_TOO_SHORT")
    boundary = pd.Timestamp(dates[len(dates) // 2])
    first = h.loc[h.signal_date.lt(boundary) & h.label_end_date.lt(boundary)]
    second = h.loc[h.signal_date.ge(boundary)]
    if first.empty or second.empty:
        raise ValueError("NO_MATURE_CHRONOLOGICAL_UNCERTAINTY_SPLIT")
    probe, probe_receipt = module.fit_calibration(name, first, boundary)
    held = module.sample(second)
    mu, provisional_scale, _ = probe.predict(held)
    residual = held.target.to_numpy(float) - mu
    weights = module.date_weights(held.signal_date)
    sigma = held[f"{name}__scale"].to_numpy(float) if name in module.DISTRIBUTION else provisional_scale
    if not np.isfinite(residual).all() or not np.isfinite(sigma).all() or np.any(sigma <= 0):
        raise ValueError("INVALID_HELDOUT_UNCERTAINTY")
    rms = max(float(np.sqrt(np.average(residual ** 2, weights=weights))), 1e-6)
    multiplier = float(np.sqrt(np.average((residual / np.maximum(sigma, 1e-6)) ** 2, weights=weights)))
    obj, receipt = module.fit_calibration(name, h, cut)
    obj.residual_rms = rms
    if name in module.DISTRIBUTION:
        obj.scale_multiplier = multiplier
    receipt.pop("residual_rms_in_fit", None)
    amplitude = 2 if name in module.PROB else 0
    receipt.update(unit=UNIT, calibration_unit=UNIT, spec=SPEC, reused_source_spec=module.SPEC,
        source_kind="MODEL_OOF", max_label_end=str(h.label_end_date.max()),
        uncertainty_boundary=str(boundary), uncertainty_first_rows=len(first), uncertainty_heldout_rows=len(held),
        probe_max_label_end=probe_receipt["max_label_end"], uncertainty_heldout_max_label_end=str(held.label_end_date.max()),
        residual_rms_chronological_holdout=rms, scale_multiplier=multiplier,
        scale_multiplier_applied=name in module.DISTRIBUTION, legacy_in_fit_uncertainty_discarded=True,
        delegated_calibration_calls=2, preprocessing_fit_count=2, model_fit_count=2,
        uncertainty_statistical_fit_count=2, signed_amplitude_mapping_fit_count=amplitude,
        signed_amplitude_scalar_parameter_count=2 * amplitude, total_fit_count=6 + amplitude)
    return obj, receipt


def fit_fusion(module, method, members, frame, cutoff):
    _sampling(module)
    if method not in METHODS[:11] or tuple(members) != MEMBERS:
        raise ValueError("UNREGISTERED_FUSION_OR_MEMBER_ORDER")
    h, cut = _guard(frame, cutoff, "CALIBRATED_OOF")
    for name in members:
        cc, ml = f"{name}__calibration_cutoff", f"{name}__calibration_max_label_end"
        if cc not in h or ml not in h or h[[cc, ml]].isna().any().any():
            raise ValueError("MISSING_CALIBRATED_OOF_LINEAGE")
        cc_values, ml_values = pd.to_datetime(h[cc]), pd.to_datetime(h[ml])
        if not cc_values.lt(h.signal_date).all() or not ml_values.lt(cc_values).all():
            raise ValueError("CALIBRATED_OOF_CLOCK_VIOLATION")
    columns = [f"{name}__mu" for name in members]
    if not np.isfinite(h[columns].to_numpy(float)).all():
        raise ValueError("UNAVAILABLE_MEMBER_DO_NOT_DROP")
    learned, preprocessing, target_scale = 0, 0, 0
    if method in ("fixed_weighted", "nnls"):
        sampled = module.sample(h)
        coefficients = np.asarray(SPEC["fixed_weights"], float)
        if method == "nnls":
            weight = np.sqrt(module.date_weights(sampled.signal_date))
            coefficients, _ = nnls(sampled[columns].to_numpy(float) * weight[:, None], sampled.target.to_numpy(float) * weight)
            learned = 1
        obj = LinearFusion(method, list(members), coefficients)
        receipt = {"method": method, "members": list(members), "rows": len(sampled), "coefficients": coefficients.tolist()}
    else:
        obj, receipt = module.fit_fusion(method, list(members), h, cut)
        learned = int(method not in ("equal", "median"))
        preprocessing = int(method not in ("equal", "median", "simplex"))
        target_scale = int(method in ("simplex", "linear_gate", "mlp_gate"))
    receipt.update(unit=UNIT, spec=SPEC, reused_source_spec=module.SPEC, source_kind="CALIBRATED_OOF",
        cutoff_exclusive=str(cut.date()), max_signal=str(h.signal_date.max()), max_label_end=str(h.label_end_date.max()),
        preprocessing_fit_count=preprocessing, model_fit_count=learned, statistical_fit_count=target_scale,
        total_fit_count=preprocessing + learned + target_scale, coefficient_normalization=False if method == "nnls" else None)
    return obj, receipt
