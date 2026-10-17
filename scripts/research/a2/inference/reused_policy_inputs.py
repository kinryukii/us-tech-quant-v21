"""Consume frozen annual B opportunity forecasts without fitting or changing model inputs.

The annual opportunity clock is checked against the decision, independently of
any risk-state clock. Historical availability remains an explicit research
assumption. No target, account outcome, model pickle, or inference is read here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from scripts.research.a2.data.joint_input_binding import FEATURES, guard_parquet

P0_COLUMNS = (
    "signal_date", "ticker", "HGB_mu", "HGB_uncertainty",
    "source_fit_cutoff", "fold_year",
)
SOURCE_ROOT = Path(
    "D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24"
)


@dataclass(frozen=True)
class AnnualOpportunityRef:
    year: int
    path: str
    sha256: str
    receipt_path: str
    receipt_sha256: str
    model_sha256: str
    calibration_sha256: str
    label_maturity_max: str


def _ref(year, oof, receipt, model, calibration, maturity):
    return AnnualOpportunityRef(
        year, str(SOURCE_ROOT / f"OOF/INITIAL_{year}.parquet"), oof,
        str(SOURCE_ROOT / f"receipts/INITIAL_{year}.json"), receipt,
        model, calibration, maturity,
    )


P0_ANNUAL_REFERENCES = {
    2023: _ref(
        2023, "f2501177f2efaf5e5ed6ddf1ebce3a72e2d5b554adde5595df96d83a992523d0",
        "13c7177e600ad4972d291253644038f4f9540a03b4242a9ce96b5bf8fe954cc4",
        "dc2480dce313ebeb0ac6ecb3af7f1656b6cdb4716788adf1b137df6355283229",
        "8f81a1d1d6b2a2293dd9f9e8966cd69c9a136f7b9788c0cee50a3108deca98be",
        "2022-12-30",
    ),
    2024: _ref(
        2024, "fdbe20e37a34d4474762a9bc28b99684d1871f399432ed8abc1ffb5389409ae0",
        "041dce4e50cca1a4b5badb334666e4c509718b8d513dca8e00a27a5003accd47",
        "9667d0882864faa778a05d0b45fe03e0d6301dad5a9394389a97fb614688b474",
        "feb6f93ba2f0b69b84e3946f83b7b1ced24619831422d15c913ebd81a6e68f10",
        "2023-12-29",
    ),
    2025: _ref(
        2025, "d66cffe15e9f84f4f6f46b4e540626ed0aeba94c033132e76a9d7bda1547faa7",
        "ed9ad4bd6418d3e1247569129f06052ae4cbabec3131147d67fca2e0b2f455de",
        "eb091ad5e25696466e4c3ca4b7c0e2aa391c069cf8cfc5927e8ac2f21bdbf97f",
        "af0db205441a3319340fefe4093d689165960af63a522bfcb33d4a7d01b30d40",
        "2024-12-31",
    ),
}


# Model pins from the existing V24/work/FIT_STATUS.json, same INITIAL tables.
_RIDGE_PINS = {
    2023: ("16d0870189073d6b8a68f684cc4629e5372e5185e8e2dc6a3b19963ad521a45f", "7e28836f677532a52970163a191a95060139ef594a1cf37260a95100f0f64f6b"),
    2024: ("35e159fae13012f40e509465f69b4fdaf4feb2ace93aa5408c5fb0e0bb160d53", "535e4d859ef3ad8b893042f853266ec748ddd0a2cf7c901956d94e6c64e87eca"),
    2025: ("5789236c8187e94418cac306572ff61d94afbb9053edff1981536d006f86ca62", "210dc47fccafd725cc72a2e262929af10ad982e5eb1bdfcef5f6e5129e29311c"),
}
RIDGE_ANNUAL_REFERENCES = {
    year: replace(P0_ANNUAL_REFERENCES[year], model_sha256=model, calibration_sha256=calibration)
    for year, (model, calibration) in _RIDGE_PINS.items()
}
FORECAST_RECIPES = {"HGB": ("HGB",), "RIDGE": ("Ridge",),
                    "RIDGE_HGB_EQUAL": ("Ridge", "HGB")}


@dataclass(frozen=True)
class OpportunitySlice:
    assets: tuple[str, ...]
    mean: np.ndarray
    uncertainty: np.ndarray
    required: np.ndarray
    source_receipt: dict


def _day(value):
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_OPPORTUNITY_SESSION_DAY") from exc
    if pd.isna(result) or result.tzinfo is not None or result != result.normalize():
        raise ValueError("INVALID_OPPORTUNITY_SESSION_DAY")
    if result.year not in (2023, 2024, 2025):
        raise ValueError("OPPORTUNITY_OUTSIDE_PRE2026_PAIR_SCOPE")
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def required_opportunity_mask(eligible, held_units, held_weights=None):
    """Require the current eligible set plus actual holdings, never future holdings."""
    eligibility = np.asarray(eligible)
    units = np.asarray(held_units, dtype=float)
    if eligibility.ndim != 1 or eligibility.dtype != np.dtype(bool):
        raise ValueError("INVALID_OPPORTUNITY_ELIGIBILITY_MASK")
    if units.shape != eligibility.shape or not np.isfinite(units).all() or np.any(units < 0):
        raise ValueError("INVALID_OPPORTUNITY_ACTUAL_HOLDINGS")
    required = eligibility | (units > 0)
    if held_weights is not None:
        weights = np.asarray(held_weights, dtype=float)
        if weights.shape != units.shape or not np.isfinite(weights).all() or np.any(weights < 0):
            raise ValueError("INVALID_OPPORTUNITY_ACTUAL_WEIGHTS")
        required |= weights > 0
    return required


class OpportunityInputUnavailable(ValueError):
    """An actual missing required key/value, distinct from engineering defects."""
    def __init__(self, reason, **evidence):
        self.receipt = dict(status="BLOCKED_REQUIRED_OPPORTUNITY_INPUT", reason=reason, **evidence)
        super().__init__(reason)


class FrozenAnnualOpportunityReader:
    """Hash-bound, column-scoped P0 OOF consumption; no fit/predict entry point."""

    def __init__(self, references: Mapping[int, AnnualOpportunityRef] | None = None, *,
                 recipe="HGB", ridge_references: Mapping[int, AnnualOpportunityRef] | None = None):
        if recipe not in FORECAST_RECIPES:
            raise ValueError("UNREGISTERED_EXISTING_FORECAST_RECIPE")
        self.recipe, self.members = recipe, FORECAST_RECIPES[recipe]
        defaults = RIDGE_ANNUAL_REFERENCES if recipe == "RIDGE" else P0_ANNUAL_REFERENCES
        self.references = dict(defaults if references is None else references)
        self.ridge_references = dict(RIDGE_ANNUAL_REFERENCES if ridge_references is None else ridge_references)
        self.value_columns = [member + suffix for member in self.members for suffix in ("_mu", "_uncertainty")]
        self.columns = ["signal_date", "ticker", *self.value_columns, "source_fit_cutoff", "fold_year"]
        self._annual_cache = {}

    def _annual(self, year):
        if year in self._annual_cache:
            return self._annual_cache[year]
        reference = self.references.get(year)
        if not isinstance(reference, AnnualOpportunityRef) or reference.year != year:
            raise ValueError("UNBOUND_OPPORTUNITY_ANNUAL_REFERENCE")
        for digest in (reference.sha256, reference.receipt_sha256,
                       reference.model_sha256, reference.calibration_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("INVALID_OPPORTUNITY_SOURCE_DIGEST")
        receipt_bytes = Path(reference.receipt_path).read_bytes()
        if hashlib.sha256(receipt_bytes).hexdigest() != reference.receipt_sha256:
            raise ValueError("OPPORTUNITY_RECEIPT_SHA_MISMATCH")
        receipt = json.loads(receipt_bytes)
        cutoff = pd.Timestamp(year, 1, 1)
        maturity = pd.Timestamp(reference.label_maturity_max)
        if (pd.isna(maturity) or maturity.tzinfo is not None or maturity >= cutoff
            or receipt.get("status") != "REAL_TRUE_OOF" or receipt.get("year") != year
            or receipt.get("calibrated") is not True
            or receipt.get("sha256") != reference.sha256
            or pd.Timestamp(receipt.get("source_fit_cutoff")) != cutoff
            or pd.Timestamp(receipt.get("source_label_maturity_max")) != maturity):
            raise ValueError("OPPORTUNITY_ORIGINAL_ANNUAL_LINEAGE_MISMATCH")
        if self.recipe == "RIDGE_HGB_EQUAL":
            other = self.ridge_references.get(year)
            fields = ("year", "path", "sha256", "receipt_path", "receipt_sha256", "label_maturity_max")
            if (not isinstance(other, AnnualOpportunityRef)
                    or any(getattr(other, key) != getattr(reference, key) for key in fields)):
                raise ValueError("TWO_MEMBER_ANNUAL_SOURCE_OR_CUTOFF_MISMATCH")
            for digest in (other.model_sha256, other.calibration_sha256):
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("INVALID_OPPORTUNITY_SOURCE_DIGEST")
        file, _ = guard_parquet(reference.path, reference.sha256,
                                ["signal_date", "source_fit_cutoff"])
        if not set(self.columns).issubset(file.schema_arrow.names):
            raise ValueError("OPPORTUNITY_SOURCE_SCHEMA_MISMATCH")
        frame = file.read(columns=self.columns).to_pandas()
        dates = pd.to_datetime(frame.signal_date)
        source_cutoffs = pd.to_datetime(frame.source_fit_cutoff)
        tickers = frame.ticker
        if (dates.isna().any() or dates.dt.tz is not None
            or not dates.equals(dates.dt.normalize()) or not dates.dt.year.eq(year).all()
            or source_cutoffs.isna().any() or source_cutoffs.dt.tz is not None
            or not source_cutoffs.eq(cutoff).all() or not frame.fold_year.eq(year).all()
            or tickers.isna().any() or any(
                not isinstance(t, str) or not t or t != t.strip() for t in tickers)):
            raise ValueError("OPPORTUNITY_KEY_FOLD_OR_CUTOFF_MISMATCH")
        frame = frame.assign(signal_date=dates, source_fit_cutoff=source_cutoffs)
        if frame.duplicated(["signal_date", "ticker"]).any():
            raise ValueError("DUPLICATE_OPPORTUNITY_SOURCE_KEY")
        frame = frame.set_index(["signal_date", "ticker"])
        self._annual_cache[year] = (frame, reference, cutoff)
        return self._annual_cache[year]

    def for_decision(self, day, assets, eligible, held_units, *, decision_as_of,
                     held_weights=None):
        day = _day(day)
        try:
            asof = pd.Timestamp(decision_as_of)
        except (TypeError, ValueError) as exc:
            raise ValueError("INVALID_OPPORTUNITY_DECISION_CLOCK") from exc
        if (pd.isna(asof) or asof.tzinfo is None
            or asof.tz_convert("America/New_York").date() != day.date()):
            raise ValueError("INVALID_OPPORTUNITY_DECISION_CLOCK")
        assets = tuple(assets)
        if (len(set(assets)) != len(assets) or any(
            not isinstance(a, str) or not a or a != a.strip() for a in assets)):
            raise ValueError("INVALID_OPPORTUNITY_ASSET_COORDINATE")
        required = required_opportunity_mask(eligible, held_units, held_weights)
        if required.shape != (len(assets),):
            raise ValueError("OPPORTUNITY_REQUIRED_COORDINATE_SHAPE")
        frame, reference, cutoff = self._annual(day.year)
        cutoff_clock = cutoff.tz_localize("America/New_York").tz_convert("UTC")
        if cutoff_clock > asof:
            raise ValueError("OPPORTUNITY_MODEL_CUTOFF_AFTER_DECISION")
        keys = pd.MultiIndex.from_tuples(
            [(day, asset) for asset in assets], names=["signal_date", "ticker"],
        )
        present = keys.isin(frame.index)
        if np.any(required & ~present):
            missing = [a for a, needed, found in zip(assets, required, present) if needed and not found]
            raise OpportunityInputUnavailable("MISSING_REQUIRED_OPPORTUNITY_KEY:" + ",".join(missing), assets=missing)
        selected = frame.reindex(keys)
        member_means = selected[[member + "_mu" for member in self.members]].to_numpy(dtype=float).T
        member_sigma = selected[[member + "_uncertainty" for member in self.members]].to_numpy(dtype=float).T
        if (not np.isfinite(member_means[:, required]).all()
                or not np.isfinite(member_sigma[:, required]).all()
                or np.any(member_sigma[:, required] < 0)):
            raise OpportunityInputUnavailable("INVALID_REQUIRED_OPPORTUNITY_VALUE")
        mean = member_means.mean(axis=0)
        # Reuse original two-member disagreement formula in the existing H5 coordinate.
        # This is not the five-member P2 genuine-OOF RMS definition.
        uncertainty = (np.abs(member_means[0] - member_means[1]) / 2
                       if self.recipe == "RIDGE_HGB_EQUAL" else member_sigma[0].copy())
        if (not np.isfinite(mean[required]).all()
            or not np.isfinite(uncertainty[required]).all()
            or np.any(uncertainty[required] < 0)):
            raise OpportunityInputUnavailable("INVALID_REQUIRED_OPPORTUNITY_VALUE")
        # Irrelevant cells carry no authority and never acquire fabricated values.
        mean[~required] = np.nan
        uncertainty[~required] = np.nan
        payload = dict(
            signal_date=str(day.date()), decision_as_of=asof.tz_convert("UTC").isoformat(),
            assets=list(assets), required=required.tolist(),
            mean=[float(v) if needed else None for v, needed in zip(mean, required)],
            uncertainty=[float(v) if needed else None for v, needed in zip(uncertainty, required)],
            source_sha256=reference.sha256,
        )
        source_receipt = dict(
            schema="B_REUSED_P0_OPPORTUNITY_USE_V1",
            status="FROZEN_ANNUAL_OPPORTUNITY_REQUIRED_KEYS_VERIFIED_RESEARCH_ONLY",
            source_kind="EXISTING_FROZEN_ANNUAL_OOF", source_path=reference.path,
            source_sha256=reference.sha256, original_receipt_path=reference.receipt_path,
            original_receipt_sha256=reference.receipt_sha256,
            original_model_sha256=reference.model_sha256,
            original_calibration_sha256=reference.calibration_sha256,
            original_feature_columns=list(FEATURES), original_base_scaler="NONE",
            original_calibration="WEIGHTED_STANDARD_SCALER_THEN_RIDGE_ALPHA_100",
            value_columns=self.value_columns, fold_year=day.year,
            source_fit_cutoff=cutoff_clock.isoformat(),
            label_maturity_max=reference.label_maturity_max,
            mechanism_available_at_assumption=cutoff_clock.isoformat(),
            historical_availability_authority="UNKNOWN", strict_PIT=False,
            production_qualified=False, calibrated_uncertainty_certified=False,
            uncertainty_scope="ORIGINAL_PRIOR_MATURED_OOF_CALIBRATION_RESIDUAL_RMS",
            required_basis="CURRENT_ELIGIBLE_UNION_ACTUAL_HELD_UNITS_OR_WEIGHTS",
            required_assets=[a for a, needed in zip(assets, required) if needed],
            signal_date=payload["signal_date"], decision_as_of=payload["decision_as_of"],
            slice_content_sha256=_digest(payload), additional_fit_units=0,
            additional_inference_rows=0,
        )
        if self.recipe != "HGB":
            refs = ({"Ridge": self.ridge_references[day.year], "HGB": reference}
                    if self.recipe == "RIDGE_HGB_EQUAL" else {"Ridge": reference})
            payload["forecast_recipe"] = self.recipe
            source_receipt.update(schema="B_REUSED_H5_EXPLICIT_FORECAST_RECIPE_V1",
                forecast_recipe=self.recipe, member_model_pins={name: {
                    "model_sha256": item.model_sha256, "calibration_sha256": item.calibration_sha256}
                    for name, item in refs.items()},
                original_base_scaler="RIDGE_STANDARD_SCALER;HGB_NONE" if len(refs) == 2 else "STANDARD_SCALER",
                uncertainty_scope=("HALF_ABSOLUTE_TWO_MEMBER_DISAGREEMENT_NOT_CALIBRATED_PREDICTIVE_SD"
                    if len(refs) == 2 else "ORIGINAL_PRIOR_MATURED_OOF_CALIBRATION_RESIDUAL_RMS"),
                mean_semantic="CALIBRATED_EXISTING_OPEN_ALIGNED_H5",
                old_P1_P2_identity_claim=False, slice_content_sha256=_digest(payload))
        for array in (mean, uncertainty, required):
            array.setflags(write=False)
        return OpportunitySlice(assets, mean, uncertainty, required, source_receipt)


# These are original prediction artifacts, not a new prediction producer.  The
# base uses its original frozen rank-only sigma rule, and held cells retain the
# existing raw_uncertainty.  No market cache, model or feature body is needed.
RAW_CONTROL_BASE_REF = dict(
    path="D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet",
    sha256="e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    namespace="ORIGINAL_RAW_OOF",
)
RAW_CONTROL_FREEZE_REF = dict(
    path=str(SOURCE_ROOT / "continuation/RAW_HELD_INPUT_FREEZE.json"),
    sha256="3cabfd17870817207689b6174ccdaf4878fdd3c5ab6d768e8730cf181c4d3e14",
)
RAW_CONTROL_VALIDATION_REF = dict(
    path=str(SOURCE_ROOT / "continuation/RAW_HELD_INPUT_VALIDATION.json"),
    sha256="c73b042fba485731d8328d3cdd4894b8e7a272253ba3608a06355b0117ead407",
)
_RAW_HELD_SHA = {
    2023: "f9109064e1fded6268ac3aea526f521c1117e6f80853bae7e9c56d408d9f9263",
    2024: "70c6bc34255a16d66a71ff4b22576a7f2969da37c3afd93452a47826f7a80a41",
    2025: "b6466ccbbdf6cf1aa39d142fc540d88ea9686276125a2ef0273fc43b82e4a8e0",
}
RAW_CONTROL_HELD_REFS = {
    year: dict(path=str(SOURCE_ROOT / f"continuation/OOF/RAW_HELD_MISSING_{year}.parquet"),
               sha256=sha, namespace=f"ORIGINAL_RAW_HELD_{year}")
    for year, sha in _RAW_HELD_SHA.items()
}


def _raw_bound_json(reference):
    raw = Path(reference["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("RAW_CONTROL_METADATA_SHA_MISMATCH:" + reference["path"])
    return json.loads(raw)


def _raw_control_metadata():
    frozen = _raw_bound_json(RAW_CONTROL_FREEZE_REF)
    validation = _raw_bound_json(RAW_CONTROL_VALIDATION_REF)
    if (frozen.get("status") != "FROZEN_BEFORE_REAL_MISSING_KEY_INFERENCE"
            or frozen.get("features") != list(FEATURES)
            or validation.get("status") != "PASS_FROZEN_RAW_MISSING_HELD_KEY_INFERENCE"):
        raise ValueError("RAW_CONTROL_ORIGINAL_SOURCE_CONTRACT_MISMATCH")
    annual = {}
    for year, reference in RAW_CONTROL_HELD_REFS.items():
        output = validation["annual_outputs"][str(year)]
        model = frozen["models"][str(year)]
        manifest_ref = dict(path=model["manifest_path"], sha256=model["manifest_sha256"])
        manifest = _raw_bound_json(manifest_ref)["contract"]
        cutoff = pd.Timestamp(year, 1, 1)
        deploy = _day(manifest["prediction_min_date"])
        if (Path(output["path"]).resolve() != Path(reference["path"]).resolve()
                or output["sha256"] != reference["sha256"]
                or output.get("input_freeze_sha256") != RAW_CONTROL_FREEZE_REF["sha256"]
                or manifest.get("year") != year or manifest.get("feature_columns") != list(FEATURES)
                or deploy.year != year or deploy < cutoff
                or pd.Timestamp(manifest["train_end"]) >= cutoff
                or pd.Timestamp(manifest["labelmax"]) >= cutoff
                or any(output["model"].get(key) != model.get(key) for key in (
                    "path", "sha256", "manifest_path", "manifest_sha256",
                    "train_end", "labelmax", "prediction_min_date"))):
            raise ValueError("RAW_CONTROL_ORIGINAL_ANNUAL_LINEAGE_MISMATCH")
        annual[year] = dict(manifest_ref=manifest_ref, model_sha256=model["sha256"],
            source_fit_cutoff=cutoff.isoformat(), label_maturity_max=manifest["labelmax"],
            prediction_min_date=str(deploy.date()),
            original_equivalence_status=model.get("original_equivalence_status_preserved", "UNKNOWN"))
    return dict(annual=annual, base_ref=dict(RAW_CONTROL_BASE_REF),
        held_refs={year: dict(ref) for year, ref in RAW_CONTROL_HELD_REFS.items()},
        original_freeze_ref=dict(RAW_CONTROL_FREEZE_REF),
        original_validation_ref=dict(RAW_CONTROL_VALIDATION_REF),
        rank_units=frozen["rank_units"])


def _project_raw_control_base(frame):
    """Retain exact keys/row ordinals and native values; no sorting of scores."""
    frame = frame.copy()
    dates = pd.to_datetime(frame.signal_date)
    if (dates.isna().any() or dates.dt.tz is not None
            or not dates.equals(dates.dt.normalize())
            or not dates.dt.year.isin((2023, 2024, 2025)).all()
            or frame.ticker.isna().any()
            or any(not isinstance(t, str) or not t or t != t.strip() for t in frame.ticker)):
        raise ValueError("RAW_CONTROL_BASE_KEY_OR_CLOCK_MISMATCH")
    frame["signal_date"] = dates
    if frame.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("RAW_CONTROL_DUPLICATE_BASE_KEY")
    frame["row_identity"] = np.arange(len(frame))
    return frame


def _load_raw_control_provider():
    """Read only guarded original score/key columns; no market/fit/predict IO."""
    import pyarrow as pa
    import pyarrow.dataset as ds
    from scripts.research.a2.data.frozen_joint_raw_provider_research import FrozenJointRawProviderResearch
    metadata = _raw_control_metadata()
    # Every artifact is physically pre-2026 before any prediction body is read.
    base_file, _ = guard_parquet(RAW_CONTROL_BASE_REF["path"], RAW_CONTROL_BASE_REF["sha256"], ["signal_date"])
    held_files = {year: guard_parquet(ref["path"], ref["sha256"],
        ["signal_date", "source_fit_cutoff"])[0] for year, ref in RAW_CONTROL_HELD_REFS.items()}
    base = _project_raw_control_base(base_file.read(columns=["signal_date", "ticker", "a2_prediction"]).to_pandas())
    held, datasets, ordinals = [], {}, {}
    for year, file in held_files.items():
        block = file.read(columns=["signal_date", "ticker", "source_fit_cutoff", "source_kind", "feature_source"]).to_pandas()
        block["signal_date"] = pd.to_datetime(block.signal_date)
        if (not block.signal_date.dt.year.eq(year).all()
                or not pd.to_datetime(block.source_fit_cutoff).eq(pd.Timestamp(year, 1, 1)).all()
                or block.signal_date.lt(metadata["annual"][year]["prediction_min_date"]).any()
                or block.duplicated(["signal_date", "ticker"]).any()):
            raise ValueError("RAW_CONTROL_HELD_ANNUAL_KEY_OR_CLOCK_MISMATCH")
        block["row_identity"] = np.arange(len(block))
        block["source_year"] = year
        held.append(block)
        ordinals[year] = {(pd.Timestamp(r.signal_date), str(r.ticker)): int(r.row_identity) for r in block.itertuples()}
        datasets[year] = ds.dataset(RAW_CONTROL_HELD_REFS[year]["path"], format="parquet")
    held = pd.concat(held, ignore_index=True)
    dates = pd.DatetimeIndex(pd.concat([base.signal_date, held.signal_date]).unique()).sort_values()
    assets = tuple(sorted(set(base.ticker) | set(held.ticker)))
    mu = np.full((len(dates), len(assets)), np.nan)
    ri, ci = dates.get_indexer(base.signal_date), pd.Index(assets).get_indexer(base.ticker)
    mu[ri, ci] = base.a2_prediction.to_numpy(dtype=float)
    # Exact original joint_method_stages.py RAW_CONTROL rank metadata rule.
    sigma = np.where(np.isfinite(mu), 0., np.nan)
    def held_values(year, day, tickers):
        dataset = datasets[int(year)]
        predicate = (ds.field("signal_date") == pa.scalar(pd.Timestamp(day).to_pydatetime(),
            type=dataset.schema.field("signal_date").type)) & ds.field("ticker").isin(list(tickers))
        frame = dataset.to_table(columns=["signal_date", "ticker", "a2_prediction", "raw_uncertainty",
            "source_fit_cutoff", "source_kind", "feature_source"], filter=predicate).to_pandas()
        frame["row_identity"] = [ordinals[int(year)][(pd.Timestamp(r.signal_date), str(r.ticker))] for r in frame.itertuples()]
        return frame
    provider = FrozenJointRawProviderResearch(dates=dates, tickers=assets,
        base_keys=base[["signal_date", "ticker", "row_identity"]].to_dict("records"),
        mu=mu, sigma=sigma, base_ref=RAW_CONTROL_BASE_REF,
        cache_ref=dict(RAW_CONTROL_BASE_REF, namespace="EXACT_RAW_OOF_KEY_PROJECTION_NOT_MARKET_CACHE"),
        held_rows=held.to_dict("records"), held_refs=RAW_CONTROL_HELD_REFS,
        held_value_loader=held_values, source_namespace="ORIGINAL_RAW_CONTROL_SOURCE_PROJECTION")
    return provider, metadata


class FrozenRawControlReader:
    """OpportunitySlice API over the existing exact Raw provider and source pins."""
    recipe = "ORIGINAL_RAW_A2"

    def __init__(self, *, provider_factory=None):
        self._factory = _load_raw_control_provider if provider_factory is None else provider_factory
        self._provider = self._metadata = None

    def for_decision(self, day, assets, eligible, held_units, *, decision_as_of, held_weights=None):
        day = _day(day)
        asof = pd.Timestamp(decision_as_of)
        if (pd.isna(asof) or asof.tzinfo is None
                or asof.tz_convert("America/New_York").date() != day.date()):
            raise ValueError("INVALID_OPPORTUNITY_DECISION_CLOCK")
        assets = tuple(assets)
        if len(set(assets)) != len(assets) or any(not isinstance(a, str) or not a or a != a.strip() for a in assets):
            raise ValueError("INVALID_OPPORTUNITY_ASSET_COORDINATE")
        required = required_opportunity_mask(eligible, held_units, held_weights)
        if required.shape != (len(assets),):
            raise ValueError("OPPORTUNITY_REQUIRED_COORDINATE_SHAPE")
        if self._provider is None:
            self._provider, self._metadata = self._factory()
        provider, metadata = self._provider, self._metadata
        columns = pd.Index(provider.tickers).get_indexer(assets)
        if np.any(required & (columns < 0)):
            missing = [a for a, need, col in zip(assets, required, columns) if need and col < 0]
            raise OpportunityInputUnavailable("MISSING_REQUIRED_RAW_CONTROL_KEY:" + ",".join(missing), assets=missing)
        annual = metadata["annual"][day.year]
        if day < pd.Timestamp(annual["prediction_min_date"]):
            raise ValueError("RAW_CONTROL_BEFORE_ORIGINAL_ANNUAL_DEPLOYMENT")
        master_required = np.zeros(len(provider.tickers), dtype=bool)
        master_required[columns[required]] = True
        from scripts.research.a2.data.frozen_joint_raw_provider_research import RawProviderFailure
        try:
            values = provider.for_day(day, master_required, tickers=provider.tickers)
        except RawProviderFailure as error:
            raise OpportunityInputUnavailable("RAW_CONTROL_" + error.reason, provider_failure=error.receipt) from error
        mean, uncertainty = np.full(len(assets), np.nan), np.full(len(assets), np.nan)
        mean[required], uncertainty[required] = values.mu[columns[required]], values.sigma[columns[required]]
        if (not np.isfinite(mean[required]).all() or not np.isfinite(uncertainty[required]).all()
                or np.any(uncertainty[required] < 0)):
            raise OpportunityInputUnavailable("INVALID_REQUIRED_RAW_CONTROL_VALUE")
        provenance = []
        for raw in values.provenance:
            item = dict(raw)
            if item["base_present"]:
                # These arrays were reconstructed from the exact source key/row,
                # not loaded from the historical market cache. Never claim its cells.
                item.pop("value_cell_identity", None)
                item["value_coordinate"] = "EXACT_SOURCE_KEY_AND_PHYSICAL_ROW_PROJECTION"
            provenance.append(item)
        payload = dict(signal_date=str(day.date()), assets=list(assets), required=required.tolist(),
            mean=[float(v) if need else None for v, need in zip(mean, required)],
            uncertainty=[float(v) if need else None for v, need in zip(uncertainty, required)],
            forecast_recipe=self.recipe, source_sha256=metadata["base_ref"]["sha256"])
        receipt = dict(schema="B_REUSED_RAW_CONTROL_OPPORTUNITY_USE_V1",
            status="FROZEN_RAW_CONTROL_REQUIRED_KEYS_VERIFIED_RESEARCH_ONLY", forecast_recipe=self.recipe,
            source_kind="ORIGINAL_RAW_OOF_AND_EXISTING_HELD_EXTENSION", source_path=metadata["base_ref"]["path"],
            source_sha256=metadata["base_ref"]["sha256"], source_projection_not_market_cache=True,
            original_freeze_ref=metadata["original_freeze_ref"], original_validation_ref=metadata["original_validation_ref"],
            original_annual_lineage=annual, original_feature_columns=list(FEATURES),
            source_fit_cutoff=pd.Timestamp(annual["source_fit_cutoff"]).tz_localize("America/New_York").tz_convert("UTC").isoformat(),
            label_maturity_max=annual["label_maturity_max"],
            mean_semantic=metadata["rank_units"], calibrated_uncertainty_certified=False,
            uncertainty_scope="ORIGINAL_RANK_CONTROL_METADATA_NOT_CALIBRATED_H5_SD",
            base_sigma_rule="ORIGINAL_WHERE_FINITE_RAW_SCORE_ZERO_ELSE_NAN", held_sigma_rule="EXACT_EXISTING_RAW_UNCERTAINTY",
            required_basis="CURRENT_ELIGIBLE_UNION_ACTUAL_HELD_UNITS_OR_WEIGHTS",
            required_assets=[a for a, need in zip(assets, required) if need], provenance=provenance,
            signal_date=str(day.date()), decision_as_of=asof.tz_convert("UTC").isoformat(),
            slice_content_sha256=_digest(payload), historical_availability_authority="UNKNOWN",
            strict_PIT=False, production_qualified=False, additional_fit_units=0, additional_inference_rows=0)
        for array in (mean, uncertainty, required):
            array.setflags(write=False)
        return OpportunitySlice(assets, mean, uncertainty, required, receipt)


def make_raw_control_reader():
    """Lazy factory; construction performs no source/model/market IO."""
    return FrozenRawControlReader()
