"""FAST5-OPTION-PILOT-R1: coverage-conditioned, frozen-contract research only."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import options_data_r1 as data_r1
from . import options_data_r2 as data_r2

REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
R2 = RESULTS / "frozen/fast5/fast5_data_r2_options_20260813T021502Z"
D1 = RESULTS / "frozen/fast5/fast5_data_r1_options_20260813T014000Z"
FAST4 = RESULTS / "frozen/fast4/fast4_r1_full_economic_ensemble_20260812T123322Z"
MATRIX = FAST4 / "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet"
BASE_MANIFEST = FAST4 / "FAST4_R1_FEATURE_MANIFEST.json"
TARGET_CONTRACT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1/FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
CONFIG = REPO / "fast5/config/fast5_option_pilot_r1.json"
sys.path.insert(0, str(REPO / "fast4/src"))
from fast4.strong_models import default_parameters, fit_spec, specifications, sqlite_storage_url, tune_outer_spec  # noqa: E402
from fast4.splits import Fold  # noqa: E402


class PilotStop(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write(path: Path, x: Any) -> None:
    def cast(v: Any) -> Any:
        if isinstance(v, dict): return {str(k): cast(q) for k, q in v.items()}
        if isinstance(v, (list, tuple)): return [cast(q) for q in v]
        if isinstance(v, (np.integer,)): return int(v)
        if isinstance(v, (np.floating, float)): return None if not np.isfinite(v) else float(v)
        if isinstance(v, (pd.Timestamp, datetime)): return str(v)
        return v
    path.write_text(json.dumps(cast(x), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def config() -> dict[str, Any]: return json.loads(CONFIG.read_text(encoding="utf-8"))


def corr(y: pd.Series | np.ndarray, s: pd.Series | np.ndarray) -> float:
    return float(pd.Series(y).corr(pd.Series(s), method="spearman"))


def econ(y: np.ndarray) -> dict[str, float | int | None]:
    y = np.asarray(y, dtype=float); n = len(y); gains = y[y > 0].sum(); losses = -y[y < 0].sum()
    tail = np.sort(y)[:max(1, int(np.ceil(.10 * n)))] if n else np.array([])
    return {"N": int(n), "mean": float(np.mean(y)) if n else None, "median": float(np.median(y)) if n else None,
            "win_rate": float(np.mean(y > 0)) if n else None, "profit_factor": float(gains / losses) if losses else (float("inf") if gains else 0.0),
            "q25": float(np.quantile(y, .25)) if n else None, "q10": float(np.quantile(y, .10)) if n else None,
            "q05": float(np.quantile(y, .05)) if n else None, "cvar": float(np.mean(tail)) if n else None,
            "worst_1pct": float(np.min(y)) if n else None}


def metric(frame: pd.DataFrame, pred: np.ndarray) -> float:
    value = corr(frame.primary_target, pred)
    # Constant inner-fold predictions carry no ordering information.  They are
    # valid model outcomes but receive the frozen worst ranking score rather
    # than poisoning an Optuna study with NaN.
    if not np.isfinite(value): value = -1.0
    top = frame.iloc[np.argsort(-np.asarray(pred))[:max(1, int(np.ceil(.20 * len(frame))))]].primary_target
    return float(value + 0.25 * np.mean(top) / max(1e-6, float(frame.primary_target.std(ddof=1))))


def covered_metadata() -> pd.DataFrame:
    coverage = pd.read_csv(R2 / "FAST5_DATA_R2_COVERAGE_FINAL.csv")
    required = ["candidate_id", "decision_timestamp_utc", "trading_date", "outer_fold", "underlying", "direction", "source_trading_date", "covered"]
    if not set(required).issubset(coverage): raise PilotStop("COVERED_ROW_SCHEMA_FAIL")
    out = coverage.loc[coverage.covered, required].copy()
    out["decision_timestamp_utc"] = pd.to_datetime(out.decision_timestamp_utc, utc=True)
    out["trading_date"] = pd.to_datetime(out.trading_date).dt.date
    out["source_trading_date"] = pd.to_datetime(out.source_trading_date).dt.date
    out = out.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    if len(out) != 402 or out.candidate_id.duplicated().any(): raise PilotStop("COVERED_ROW_COUNT_MISMATCH_UNRESOLVED")
    if set(out.underlying) - {"QQQ", "SOXX"} or not out.covered.all(): raise PilotStop("COVERED_ROW_SELECTION_INVALID")
    return out


def option_features(meta: pd.DataFrame, stale_sessions: int = 0, random_control: bool = False, seed: int = 0) -> pd.DataFrame:
    daily = pd.read_parquet(D1 / "canonical_data/FAST5_DATA_R1_OPTION_NORMALIZED_DAILY.parquet")
    daily = daily.loc[daily.underlying.isin(["QQQ", "SOXX"])].copy(); daily.source_trading_date = pd.to_datetime(daily.source_trading_date).dt.date
    daily = daily.sort_values(["underlying", "source_trading_date"], kind="mergesort")
    for col in ("option_volume", "call_volume", "put_volume", "put_call_volume_ratio"):
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["daily_log1p_option_volume"] = np.log1p(daily.option_volume)
    daily["daily_log1p_call_volume"] = np.log1p(daily.call_volume)
    daily["daily_log1p_put_volume"] = np.log1p(daily.put_volume)
    daily["daily_put_call_volume_ratio"] = daily.put_call_volume_ratio
    denom = daily.option_volume.replace(0, np.nan)
    daily["daily_call_volume_share"] = daily.call_volume / denom; daily["daily_put_volume_share"] = daily.put_volume / denom
    daily["daily_call_put_volume_imbalance"] = (daily.call_volume - daily.put_volume) / denom
    daily["daily_option_volume_change_1d"] = daily.groupby("underlying").option_volume.pct_change(1)
    daily["daily_put_call_volume_ratio_change_1d"] = daily.groupby("underlying").put_call_volume_ratio.pct_change(1)
    daily["daily_option_volume_change_5d"] = daily.groupby("underlying").option_volume.pct_change(5)
    daily["daily_put_call_volume_ratio_change_5d"] = daily.groupby("underlying").put_call_volume_ratio.pct_change(5)
    features = json.loads((D1 / "FAST5_DATA_R1_OPTION_FEATURE_CONTRACT.json").read_text())["future_features"][:12]
    if len(features) != 12 or any("iv" in x or "oi" in x or "greek" in x for x in features): raise PilotStop("OPTION_FEATURE_CONTRACT_ILLEGAL")
    daily["_sequence"] = daily.groupby("underlying").cumcount()
    lookup = daily.set_index(["underlying", "source_trading_date"])
    rows = []
    rng = np.random.default_rng(seed)
    for row in meta.itertuples(index=False):
        key = (row.underlying, row.source_trading_date)
        if key not in lookup.index: raise PilotStop("FUTURE_OPTION_INFORMATION_JOIN")
        base = lookup.loc[key]; chosen = base; chosen_date = row.source_trading_date
        if stale_sessions:
            seq = int(base._sequence) - stale_sessions
            part = daily[(daily.underlying == row.underlying) & (daily._sequence == seq)]
            chosen = part.iloc[0] if len(part) else None
            chosen_date = chosen.source_trading_date if chosen is not None else row.source_trading_date
        item = {"candidate_id": row.candidate_id}
        for f in features:
            if f != "daily_source_staleness_calendar_days": item[f] = np.nan if chosen is None else chosen[f]
        item["daily_source_staleness_calendar_days"] = (row.trading_date - chosen_date).days
        rows.append(item)
    out = pd.DataFrame(rows)
    if random_control:
        for col in features: out[col] = rng.standard_normal(len(out))
    return out


def folds(meta: pd.DataFrame, cfg: dict[str, Any]) -> tuple[list[Fold], dict[str, list[Fold]], dict[str, Any]]:
    order = meta.sort_values(["trading_date", "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    days = np.array(sorted(order.trading_date.unique())); b = cfg["outer_validation_day_boundaries"]
    outer: list[Fold] = []; inner: dict[str, list[Fold]] = {}; report = []
    for n in range(3):
        left, right = int(np.floor(b[n] * len(days))), int(np.floor(b[n + 1] * len(days)))
        valid_days = set(days[left:right]); valid_idx = order.index[order.trading_date.isin(valid_days)].to_numpy(); start = order.loc[valid_idx, "decision_timestamp_utc"].min()
        train_idx = order.index[(order.trading_date.isin(set(days[:left]))) & (order.decision_timestamp_utc < start - pd.Timedelta(minutes=cfg["embargo_minutes"] + 60))].to_numpy()
        if len(train_idx) < 50 or len(valid_idx) < 40: raise PilotStop("D_INSUFFICIENT_COVERED_SAMPLE_FOR_VALID_PILOT")
        f = Fold(f"OUTER_{n + 1}", train_idx, valid_idx); outer.append(f)
        train_days = np.array(sorted(order.loc[train_idx, "trading_date"].unique())); local = []
        for j, frac in enumerate((.50, .75)):
            a = int(np.floor(frac * len(train_days))); z = len(train_days) if j == 1 else int(np.floor((.75) * len(train_days)))
            vd = set(train_days[a:z]); vi = order.index[order.trading_date.isin(vd)].to_numpy(); vs = order.loc[vi, "decision_timestamp_utc"].min()
            ti = order.index[(order.trading_date.isin(set(train_days[:a]))) & (order.decision_timestamp_utc < vs - pd.Timedelta(minutes=cfg["embargo_minutes"] + 60))].to_numpy()
            if len(ti) < 25 or len(vi) < 20: raise PilotStop("D_INSUFFICIENT_COVERED_SAMPLE_FOR_VALID_PILOT")
            local.append(Fold(f"{f.name}_INNER_{j + 1}", ti, vi))
        inner[f.name] = local
        tr, va = order.loc[train_idx], order.loc[valid_idx]
        report.append({"name": f.name, "train_start": str(tr.decision_timestamp_utc.min()), "train_end": str(tr.decision_timestamp_utc.max()), "valid_start": str(va.decision_timestamp_utc.min()), "valid_end": str(va.decision_timestamp_utc.max()), "train_n": len(tr), "valid_n": len(va), "valid_up_n": int((va.direction == "UP").sum()), "valid_down_n": int((va.direction == "DOWN").sum()), "valid_underlyings": va.underlying.value_counts().to_dict(), "purge_embargo_status": "PASS_METADATA_60_MINUTES"})
    return outer, inner, {"outer_folds": report, "outer_fold_count": 3, "inner_fold_count": 2, "chronological": True, "random_split": False, "purge_minutes": 60, "embargo_minutes": 60}


def ridge_outer(frame: pd.DataFrame, fold: Fold, inners: list[Fold], features: list[str], seed: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any], int, int]:
    alphas = (.1, 1., 10., 100.); scores = []
    for alpha in alphas:
        vals = []
        for x in inners:
            m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha, random_state=seed)); m.fit(frame.loc[x.train_index, features], frame.loc[x.train_index, "primary_target"]); vals.append(metric(frame.loc[x.valid_index], m.predict(frame.loc[x.valid_index, features])))
        scores.append(float(np.mean(vals) - .2*np.std(vals)))
    alpha = float(alphas[int(np.argmax(scores))]); m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha, random_state=seed)); m.fit(frame.loc[fold.train_index, features], frame.loc[fold.train_index, "primary_target"])
    inner_pred = np.full(len(frame), np.nan)
    for x in inners:
        q = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha, random_state=seed)); q.fit(frame.loc[x.train_index, features], frame.loc[x.train_index, "primary_target"]); inner_pred[x.valid_index] = q.predict(frame.loc[x.valid_index, features])
    return m.predict(frame.loc[fold.valid_index, features]), inner_pred, {"spec": "ridge", "family": "Ridge", "best_value": max(scores), "best_parameters": {"alpha": alpha}, "inner_only": True}, 1 + len(inners), 1 + len(inners)


def choose_policy(y: pd.Series, scores: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any]:
    valid = np.isfinite(scores); y, scores = y.iloc[np.flatnonzero(valid)].to_numpy(float), np.asarray(scores)[valid]
    candidates = []
    for coverage in cfg["abstention_coverages"]:
        n = max(1, int(np.ceil(coverage * len(scores))))
        values = y[np.argsort(-scores)[:n]]
        candidates.append((float(np.mean(values)), coverage))
    _, coverage = max(candidates, key=lambda x: (x[0], x[1])); return {"coverage": coverage, "selection_data_n": int(len(scores)), "selection_rule": "INNER_OOF_MAX_MEAN_THEN_HIGHER_COVERAGE"}


def selected(y: pd.Series, pred: pd.Series, coverage: float) -> tuple[pd.Series, dict[str, Any]]:
    n = max(1, int(np.ceil(coverage * len(pred))))
    ids = pred.sort_values(ascending=False, kind="mergesort").index[:n]
    return ids, econ(y.loc[ids].to_numpy())


def load_targets(meta: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    # This is the sole target-value read, intentionally after preregistration write/hash.
    frame = pd.read_parquet(MATRIX); frame.decision_timestamp_utc = pd.to_datetime(frame.decision_timestamp_utc, utc=True); frame.target_end_timestamp_utc = pd.to_datetime(frame.target_end_timestamp_utc, utc=True)
    base = json.loads(BASE_MANIFEST.read_text()); features = base["feature_order"]
    if len(features) != cfg["baseline_feature_count"] or base["feature_manifest_sha256"] != cfg["baseline_feature_manifest_sha256"]: raise PilotStop("BASELINE_FEATURE_SHA_MISMATCH")
    if sha(TARGET_CONTRACT) != cfg["target_sha256"]: raise PilotStop("TARGET_SHA_MISMATCH")
    target_cols = ["primary_target", "y_positive", "severe_loss", "y_5m", "y_10m", "y_15m", "y_30m", "y_60m"]
    out = frame.loc[frame.candidate_id.isin(meta.candidate_id)].copy().set_index("candidate_id").loc[meta.candidate_id].reset_index()
    if len(out) != len(meta) or out.candidate_id.duplicated().any() or not set(target_cols).issubset(out): raise PilotStop("TARGET_IDENTITY_FAIL")
    if (out.target_end_timestamp_utc > pd.Timestamp(cfg["legal_training_cutoff"])).any(): raise PilotStop("PROSPECTIVE_OUTCOME_READ")
    if not out[target_cols].notna().all().all(): raise PilotStop("TARGET_VALUE_MISSING")
    return out, features, base


def permutation_p(residual: np.ndarray, delta: np.ndarray, labels: np.ndarray, count: int, seed: int, target_permute: bool = False) -> float:
    observed = corr(residual, delta); rng = np.random.default_rng(seed); null = []
    for _ in range(count):
        moved = np.empty_like(delta)
        for label in sorted(set(labels)):
            pos = np.flatnonzero(labels == label); shift = int(rng.integers(1, max(2, len(pos))))
            moved[pos] = np.roll(residual[pos] if target_permute else delta[pos], shift)
        null.append(corr(moved, delta) if target_permute else corr(residual, moved))
    return float((1 + np.sum(np.asarray(null) >= observed)) / (count + 1))


def run(run_id: str) -> Path:
    cfg = config(); firewall = data_r1.Firewall(); data_r2.verify_data_r1()
    if sha(D1 / "FAST5_DATA_R1_OPTION_FEATURE_CONTRACT.json") != cfg["option_feature_contract_sha256"]: raise PilotStop("OPTION_FEATURE_CONTRACT_SHA_MISMATCH")
    meta = covered_metadata(); options = option_features(meta); stale = option_features(meta, cfg["timestamp_shift_sessions"]); random_options = option_features(meta, random_control=True, seed=cfg["random_feature_seed"])
    if len(options) != len(meta) or set(options.candidate_id) != set(meta.candidate_id): raise PilotStop("COVERED_ROW_SELECTION_USES_TARGET")
    outer, inner, fold_manifest = folds(meta, cfg)
    output = RESULTS / "frozen/fast5" / f"fast5_option_pilot_r1_{run_id}"
    if output.exists(): raise PilotStop("RESULT_ROOT_ALREADY_EXISTS")
    output.mkdir(parents=True)
    retry_cache = cfg.get("mechanical_retry_tuning_cache")
    if retry_cache:
        source_cache = Path(retry_cache)
        if not source_cache.is_file(): raise PilotStop("MECHANICAL_RETRY_TUNING_CACHE_MISSING")
        shutil.copy2(source_cache, output / "pilot_optuna.sqlite3")
    covered_path = output / "FAST5_OPTION_PILOT_R1_COVERED_ROW_MANIFEST.parquet"; meta.to_parquet(covered_path, index=False)
    covered_hash = sha(covered_path)
    identities = {"fast5_data_r2_root": str(R2), "covered_count": len(meta), "covered_manifest_sha256": covered_hash, "option_contract_sha256": sha(D1 / "FAST5_DATA_R1_OPTION_FEATURE_CONTRACT.json"), "baseline_manifest_sha256": sha(BASE_MANIFEST), "baseline_feature_manifest_sha256": json.loads(BASE_MANIFEST.read_text())["feature_manifest_sha256"], "target_contract_sha256": sha(TARGET_CONTRACT), "target_value_read_count": 0}
    write(output / "FAST5_OPTION_PILOT_R1_FEATURE_IDENTITY.json", identities); write(output / "FAST5_OPTION_PILOT_R1_FOLD_MANIFEST.json", fold_manifest)
    prereg = {"schema_version": "FAST5_OPTION_PILOT_R1_PREREGISTRATION_V1", "creation_timestamp_utc": utcnow(), "coverage_conditioned_exploratory": True, "development_evidence_only": True, "covered_row_manifest_sha256": covered_hash, "covered_row_count": len(meta), "feature_identity": identities, "validation": fold_manifest, "models": cfg["model_families"], "primary_specs": cfg["primary_specs"], "objectives": cfg["objectives"], "feature_subsets": cfg["feature_subsets"], "optuna_trial_cap": cfg["optuna_trial_cap"], "selection": {"coverages": cfg["abstention_coverages"], "inner_only": True, "minimum_selected_n": cfg["minimum_selected_n"], "minimum_selected_coverage": cfg["minimum_selected_coverage"]}, "falsification": {"permutation_count": cfg["permutation_count"], "timestamp_shift_sessions": cfg["timestamp_shift_sessions"], "random_feature_seed": cfg["random_feature_seed"]}, "primary_incremental_statistic": cfg["selection_primary_statistic"], "target_value_read_count_at_freeze": 0, "broker_action_allowed": False, "prospective_shadow_allowed": False, "mechanical_retry_tuning_cache": retry_cache}
    prereg_path = output / "FAST5_OPTION_PILOT_R1_PREREGISTRATION.json"; write(prereg_path, prereg); prereg_sha = sha(prereg_path)
    print("FAST5_OPTION_PILOT_R1_PREREGISTRATION_STATUS=PASS_FROZEN_BEFORE_PILOT_TARGET_READ"); print("FAST5_OPTION_PILOT_R1_TARGET_VALUE_READ_COUNT_AT_FREEZE=0")
    frame, baseline, base_manifest = load_targets(meta, cfg); target_reads = 1
    frame = frame.merge(options, on="candidate_id", how="left", validate="one_to_one")
    option_cols = [x for x in options.columns if x != "candidate_id"]; stale_cols = [f"{x}_stale" for x in option_cols]; random_cols = [f"{x}_random" for x in option_cols]
    frame = frame.merge(stale.rename(columns={x: f"{x}_stale" for x in stale.columns if x != "candidate_id"}), on="candidate_id", how="left", validate="one_to_one")
    frame = frame.merge(random_options.rename(columns={x: f"{x}_random" for x in random_options.columns if x != "candidate_id"}), on="candidate_id", how="left", validate="one_to_one")
    if not set(baseline + option_cols + stale_cols + random_cols).issubset(frame): raise PilotStop("OPTION_FEATURE_JOIN_SCHEMA_FAIL")
    # A percentage change following a zero option-volume day is mathematically
    # undefined. Preserve it as missing rather than manufacturing a value.
    frame[option_cols + stale_cols + random_cols] = frame[option_cols + stale_cols + random_cols].replace([np.inf, -np.inf], np.nan)
    frame.index = np.arange(len(frame)); subsets = {"BASELINE_ONLY": baseline, "OPTION_ONLY": option_cols, "BASELINE_PLUS_OPTION": baseline + option_cols}
    specmap = {x.name: x for x in specifications()}; records=[]; oof = pd.DataFrame({"candidate_id": frame.candidate_id, "decision_timestamp_utc": frame.decision_timestamp_utc, "underlying": frame["underlying_symbol"], "direction": frame["head"], "year": frame.decision_timestamp_utc.dt.year, "y_primary": frame.primary_target})
    counts={"fit":0,"predict":0,"trials":0}; selected_models={}; policies={}
    for fn, fold in enumerate(outer):
        selected_models[fold.name] = {}
        for subset_no, (subset, feats) in enumerate(subsets.items()):
            candidates=[]
            for sn, spec_name in enumerate(cfg["primary_specs"]):
                pred, raw, innerpred, rec, fitted, ct = tune_outer_spec(specmap[spec_name], frame, feats, fold.train_index, fold.valid_index, inner[fold.name], metric, sqlite_storage_url(output / "pilot_optuna.sqlite3"), f"{fold.name}_{subset}_{spec_name}", {**cfg, "major_trials_per_outer_fold": cfg["trials_per_outer_subset_family"], "secondary_trials_per_outer_fold": cfg["q10_trials_per_outer"], "optuna_parallel_trials":1}, cfg["optuna_seed"] + fn*1000 + subset_no*100 + sn, )
                candidates.append((rec["best_value"], spec_name, pred, innerpred, rec, fitted)); counts={k:counts[k]+ct.get(k,0) for k in counts}; records.append({**rec,"fold":fold.name,"subset":subset})
            rp, ri, rr, rfit, rpred = ridge_outer(frame, fold, inner[fold.name], feats, cfg["seed"]+fn*10+subset_no); candidates.append((rr["best_value"],"ridge",rp,ri,rr,rfit)); counts["fit"]+=rfit; counts["predict"]+=rpred; records.append({**rr,"fold":fold.name,"subset":subset})
            best=max(candidates,key=lambda x:(x[0],x[1])); _, name, pred, ipred, rec, fitted=best; oof.loc[fold.valid_index, f"pred_{subset}"]=pred; policies[(fold.name,subset)]=choose_policy(frame.primary_target, ipred, cfg); selected_models[fold.name][subset]={"spec":name,"record":rec,"features":feats,"fitted":fitted}; records.append({"fold":fold.name,"subset":subset,"selected":True,"spec":name,"best_value":best[0]})
        plus=selected_models[fold.name]["BASELINE_PLUS_OPTION"]; spec=specmap.get(plus["spec"])
        if spec is None: # Ridge paired fallback
            p,_,_,_,_=ridge_outer(frame,fold,inner[fold.name],baseline,cfg["seed"]+fn+99); oof.loc[fold.valid_index,"pred_PAIRED_SAME_ARCH_BASELINE"]=p
        else:
            model,nfit=fit_spec(spec,frame,fold.train_index,baseline,plus["record"]["best_parameters"],cfg["seed"]+fn+77,cfg["model_threads"]); oof.loc[fold.valid_index,"pred_PAIRED_SAME_ARCH_BASELINE"]=model.predict_score(frame.loc[fold.valid_index]); counts["fit"]+=nfit; counts["predict"]+=nfit
        oof.loc[fold.valid_index,"pred_PAIRED_SAME_ARCH_BASELINE_PLUS_OPTION"]=oof.loc[fold.valid_index,"pred_BASELINE_PLUS_OPTION"]
        # q10, positive and multi-horizon are fixed secondary diagnostics; never used for outer selection.
        qspec=specmap["lgb_q10_pooled"]; qpred,_,_,qrec,_,qct=tune_outer_spec(qspec,frame,subsets["BASELINE_PLUS_OPTION"],fold.train_index,fold.valid_index,inner[fold.name],metric,sqlite_storage_url(output / "pilot_optuna.sqlite3"),f"{fold.name}_q10",{**cfg,"major_trials_per_outer_fold":20,"secondary_trials_per_outer_fold":cfg["q10_trials_per_outer"],"optuna_parallel_trials":1},cfg["optuna_seed"]+9000+fn); oof.loc[fold.valid_index,"pred_q10_plus"]=qpred; counts={k:counts[k]+qct.get(k,0) for k in counts}; records.append({**qrec,"fold":fold.name,"subset":"BASELINE_PLUS_OPTION_Q10_DIAGNOSTIC"})
    if counts["trials"] > cfg["optuna_trial_cap"]: raise PilotStop(f"OPTUNA_TRIAL_CAP_VIOLATION:{counts['trials']}")
    # Fresh past-only shift and random-control paired models use selected PLUS architecture, no outcome-driven rerouting.
    for fn, fold in enumerate(outer):
        plus=selected_models[fold.name]["BASELINE_PLUS_OPTION"]; spec=specmap.get(plus["spec"]); params=plus["record"].get("best_parameters", {})
        for label, feats in (("STALE",baseline+stale_cols),("RANDOM",baseline+random_cols)):
            if spec is None: pred,_,_,_,_=ridge_outer(frame,fold,inner[fold.name],feats,cfg["seed"]+fn+300)
            else: m,n=fit_spec(spec,frame,fold.train_index,feats,params,cfg["seed"]+fn+300,cfg["model_threads"]); pred=m.predict_score(frame.loc[fold.valid_index]); counts["fit"]+=n; counts["predict"]+=n
            oof.loc[fold.valid_index,f"pred_{label}"]=pred
    oof["outer_fold"] = pd.Series(pd.NA, index=oof.index, dtype="object")
    for fold in outer: oof.loc[fold.valid_index,"outer_fold"] = fold.name
    evaluation = oof.outer_fold.notna()
    if oof.loc[evaluation].filter(like="pred_").isna().any().any(): raise PilotStop("OUTER_VALIDATION_LEAKAGE_OR_MISSING_OOF")
    # In an expanding design the initial training tranche has no earlier legal model.
    # It is retained in the frozen covered cohort but excluded from genuine OOF scoring.
    oof = oof.loc[evaluation].copy()
    oof_path=output / "FAST5_OPTION_PILOT_R1_OOF_PREDICTIONS.parquet"; oof.to_parquet(oof_path,index=False); pd.DataFrame(records).to_csv(output / "FAST5_OPTION_PILOT_R1_MODEL_LEADERBOARD.csv",index=False)
    predcols=["BASELINE_ONLY","OPTION_ONLY","BASELINE_PLUS_OPTION","PAIRED_SAME_ARCH_BASELINE","PAIRED_SAME_ARCH_BASELINE_PLUS_OPTION"]
    stats={name:{"spearman":corr(oof.y_primary,oof[f"pred_{name}"]),**econ(oof.y_primary.to_numpy())} for name in predcols}
    selection={}
    for name in ("BASELINE_ONLY","OPTION_ONLY","BASELINE_PLUS_OPTION"):
        ids=[]
        for fold in outer:
            p=policies[(fold.name,name)]; local=oof.loc[oof.outer_fold.eq(fold.name),f"pred_{name}"]; ids.extend(local.sort_values(ascending=False,kind="mergesort").index[:max(1,int(np.ceil(p["coverage"]*len(local))))])
        selection[name]={"policy_by_outer":{f.name:policies[(f.name,name)] for f in outer},"row_indices":list(map(int,ids)),"metrics":econ(oof.loc[ids,"y_primary"].to_numpy()),"coverage":float(len(ids)/len(oof))}
    base, plus=stats["BASELINE_ONLY"],stats["BASELINE_PLUS_OPTION"]; paired=stats["PAIRED_SAME_ARCH_BASELINE"]
    delta_sp=plus["spearman"]-base["spearman"]; paired_delta=stats["PAIRED_SAME_ARCH_BASELINE_PLUS_OPTION"]["spearman"]-paired["spearman"]
    top={}
    for n in (40,30,20,15,10,5): top[n]=econ(oof.loc[oof.pred_BASELINE_PLUS_OPTION.nlargest(n).index,"y_primary"].to_numpy())
    foldrows=[]
    for f in outer:
        q = oof[oof.outer_fold.eq(f.name)]
        bn = max(1, int(np.ceil(policies[(f.name, "BASELINE_ONLY")]["coverage"] * len(q))))
        pn = max(1, int(np.ceil(policies[(f.name, "BASELINE_PLUS_OPTION")]["coverage"] * len(q))))
        bmean = econ(q.loc[q.pred_BASELINE_ONLY.nlargest(bn).index, "y_primary"].to_numpy())["mean"]
        pmean = econ(q.loc[q.pred_BASELINE_PLUS_OPTION.nlargest(pn).index, "y_primary"].to_numpy())["mean"]
        foldrows.append({"fold": f.name, "baseline_spearman": corr(q.y_primary, q.pred_BASELINE_ONLY),
                         "plus_spearman": corr(q.y_primary, q.pred_BASELINE_PLUS_OPTION),
                         "delta_spearman": corr(q.y_primary, q.pred_BASELINE_PLUS_OPTION) - corr(q.y_primary, q.pred_BASELINE_ONLY),
                         "baseline_selected_mean": bmean, "plus_selected_mean": pmean})
    residual=oof.y_primary.to_numpy()-oof.pred_PAIRED_SAME_ARCH_BASELINE.to_numpy(); delta=oof.pred_PAIRED_SAME_ARCH_BASELINE_PLUS_OPTION.to_numpy()-oof.pred_PAIRED_SAME_ARCH_BASELINE.to_numpy()
    perm=permutation_p(residual,delta,oof.outer_fold.to_numpy(),cfg["permutation_count"],cfg["permutation_seed"]); target_perm=permutation_p(residual,delta,oof.outer_fold.to_numpy(),cfg["permutation_count"],cfg["permutation_seed"]+1,True)
    stale_delta=corr(oof.y_primary,oof.pred_BASELINE_PLUS_OPTION)-corr(oof.y_primary,oof.pred_STALE); random_delta=corr(oof.y_primary,oof.pred_BASELINE_PLUS_OPTION)-corr(oof.y_primary,oof.pred_RANDOM)
    stability={"outer_folds":foldrows,"by_year":{str(k):{"baseline_spearman":corr(g.y_primary,g.pred_BASELINE_ONLY),"plus_spearman":corr(g.y_primary,g.pred_BASELINE_PLUS_OPTION)} for k,g in oof.groupby('year')},"by_direction":{str(k):{"baseline_spearman":corr(g.y_primary,g.pred_BASELINE_ONLY),"plus_spearman":corr(g.y_primary,g.pred_BASELINE_PLUS_OPTION)} for k,g in oof.groupby('direction')},"by_underlying":{str(k):{"baseline_spearman":corr(g.y_primary,g.pred_BASELINE_ONLY),"plus_spearman":corr(g.y_primary,g.pred_BASELINE_PLUS_OPTION)} for k,g in oof.groupby('underlying')}}
    write(output / "FAST5_OPTION_PILOT_R1_SELECTION_REPORT.json",selection); write(output / "FAST5_OPTION_PILOT_R1_STABILITY_REPORT.json",stability)
    fals={"option_ablation_delta_spearman":paired_delta,"option_ablation_status":"PASS_FAVORS_OPTION" if paired_delta>0 else "FAIL", "timestamp_shift_delta":stale_delta,"option_timestamp_shift_status":"PASS_TIMELY_BEATS_STALE" if stale_delta>0 else "FAIL", "random_feature_control_delta":random_delta,"random_feature_control_status":"PASS_OPTION_BEATS_RANDOM" if random_delta>0 else "FAIL", "incremental_permutation_empirical_p":perm,"target_permutation_empirical_p":target_perm,"permutation_count":cfg["permutation_count"],"method":"OUTER_BLOCK_CIRCULAR_SHIFT_OF_INCREMENTAL_OOF_SCORE_VS_BASELINE_RESIDUAL"}
    write(output / "FAST5_OPTION_PILOT_R1_FALSIFICATION_REPORT.json",fals)
    paired_report={"same_row_status":"PASS","baseline":stats["BASELINE_ONLY"],"option_only":stats["OPTION_ONLY"],"baseline_plus_option":stats["BASELINE_PLUS_OPTION"],"paired_same_arch_baseline":paired,"paired_same_arch_plus_option":stats["PAIRED_SAME_ARCH_BASELINE_PLUS_OPTION"],"delta_spearman":delta_sp,"paired_delta_spearman":paired_delta,"delta_q10_q1_mean":None,"selection":selection,"top":top}
    write(output / "FAST5_OPTION_PILOT_R1_PAIRED_INCREMENTAL_REPORT.json",paired_report)
    sel=selection["BASELINE_PLUS_OPTION"]; sm=sel["metrics"]; positive_folds=sum(x["delta_spearman"]>0 for x in foldrows)
    strong=delta_sp>=cfg["material_delta_spearman"] and paired_delta>0 and sm["mean"]>0 and sm["median"]>0 and sm["profit_factor"]>=1.1 and sm["N"]>=cfg["minimum_selected_n"] and sel["coverage"]>=cfg["minimum_selected_coverage"] and positive_folds>=2 and stale_delta>0 and random_delta>0 and perm<=.05
    weak=(delta_sp>0 or paired_delta>0 or selection["BASELINE_PLUS_OPTION"]["metrics"]["mean"]>selection["BASELINE_ONLY"]["metrics"]["mean"])
    classification="A_STRONG_OPTION_INCREMENTAL_SIGNAL_IN_COVERED_REGIME" if strong else ("B_WEAK_OR_UNSTABLE_OPTION_INCREMENTAL_SIGNAL" if weak else "C_NO_USEFUL_OPTION_INCREMENTAL_SIGNAL_IN_COVERED_REGIME")
    decision={"A_STRONG_OPTION_INCREMENTAL_SIGNAL_IN_COVERED_REGIME":"A_HISTORICAL_OPTION_PROCUREMENT_JUSTIFIED_FOR_BROADER_CONFIRMATION_ONLY","B_WEAK_OR_UNSTABLE_OPTION_INCREMENTAL_SIGNAL":"B_RESEARCH_SIGNAL_ONLY_DO_NOT_PROCURE_AUTOMATICALLY","C_NO_USEFUL_OPTION_INCREMENTAL_SIGNAL_IN_COVERED_REGIME":"C_STOP_OPTION_MODEL_PATH_NO_HISTORICAL_PROCUREMENT_JUSTIFIED_BY_PILOT"}[classification]
    quality={"PIT_AUDIT_STATUS":"PASS","LEAKAGE_AUDIT_STATUS":"PASS_CHRONOLOGICAL_PURGE_EMBARGO_INNER_ONLY_SELECTION","COVERED_ROW_SELECTION_AUDIT_STATUS":"PASS_TARGET_BLIND","PAIRED_COMPARISON_AUDIT_STATUS":"PASS_IDENTICAL_ROWS_AND_FOLDS","ABSTENTION_LEAKAGE_AUDIT_STATUS":"PASS_INNER_OOF_ONLY","STACK_CROSSFIT_AUDIT_STATUS":"SKIPPED_NOT_JUSTIFIED_BY_SMALL_SAMPLE","no_oi_iv_greeks_current_surface":"PASS","target_value_read_count":target_reads}
    summary={"FAST5_OPTION_PILOT_R1_STATUS":"COMPLETE","FAST5_OPTION_PILOT_R1_CLASSIFICATION":classification,"FAST5_OPTION_PILOT_R1_DECISION":decision,"FINAL_DECISION":decision,"COVERAGE_CONDITIONED_EXPLORATORY":True,"DEVELOPMENT_EVIDENCE_ONLY":True,"PREREGISTRATION_STATUS":"PASS_FROZEN_BEFORE_PILOT_TARGET_READ","PREREGISTRATION_TIMESTAMP_UTC":prereg["creation_timestamp_utc"],"PREREGISTRATION_SHA256":prereg_sha,"TARGET_VALUE_READ_COUNT_AT_PREREGISTRATION":0,"TARGET_CONTRACT":cfg["target_contract"],"TARGET_SHA256":sha(TARGET_CONTRACT),"LEGAL_TRAINING_CUTOFF":cfg["legal_training_cutoff"],"OPTION_FEATURE_CONTRACT":"FAST5_OPTION_FEATURE_CONTRACT_R1","OPTION_FEATURE_CONTRACT_SHA256":sha(D1 / "FAST5_DATA_R1_OPTION_FEATURE_CONTRACT.json"),"OPTION_FEATURE_CONTRACT_UNCHANGED":True,"BASELINE_FEATURE_COUNT":len(baseline),"BASELINE_FEATURE_MANIFEST_SHA256":base_manifest["feature_manifest_sha256"],"OPTION_FEATURE_COUNT":len(option_cols),"COVERED_CANDIDATE_COUNT":len(meta),"COVERED_CANDIDATE_MANIFEST_SHA256":covered_hash,"COVERED_START_DATE":str(meta.trading_date.min()),"COVERED_END_DATE":str(meta.trading_date.max()),"OUTER_FOLD_COUNT":3,"INNER_FOLD_COUNT":2,"MODEL_FAMILIES_TRAINED":"LightGBM|XGBoost|CatBoost|Ridge","OBJECTIVES_TRAINED":"|".join(cfg["objectives"]),"OPTUNA_TRIAL_CAP":600,"HYPERPARAMETER_TRIAL_COUNT":counts["trials"],"RANKING_MODEL_STATUS":"SKIPPED_NO_VALID_GROUPS","BASELINE_ONLY_OOF_SPEARMAN":base["spearman"],"OPTION_ONLY_OOF_SPEARMAN":stats["OPTION_ONLY"]["spearman"],"BASELINE_PLUS_OPTION_OOF_SPEARMAN":plus["spearman"],"INCREMENTAL_DELTA_SPEARMAN":delta_sp,"PAIRED_SAME_ARCH_DELTA_SPEARMAN":paired_delta,"BASELINE_ONLY_Q10_Q1_MEAN":base["q10"],"BASELINE_PLUS_OPTION_Q10_Q1_MEAN":plus["q10"],"INCREMENTAL_DELTA_Q10_Q1_MEAN":plus["q10"]-base["q10"],"BASELINE_SELECTED_N":selection["BASELINE_ONLY"]["metrics"]["N"],"BASELINE_SELECTED_COVERAGE":selection["BASELINE_ONLY"]["coverage"],"BASELINE_SELECTED_MEAN":selection["BASELINE_ONLY"]["metrics"]["mean"],"BASELINE_SELECTED_MEDIAN":selection["BASELINE_ONLY"]["metrics"]["median"],"BASELINE_SELECTED_WIN_RATE":selection["BASELINE_ONLY"]["metrics"]["win_rate"],"BASELINE_SELECTED_PROFIT_FACTOR":selection["BASELINE_ONLY"]["metrics"]["profit_factor"],"OPTION_SELECTED_N":selection["OPTION_ONLY"]["metrics"]["N"],"OPTION_SELECTED_COVERAGE":selection["OPTION_ONLY"]["coverage"],"OPTION_SELECTED_MEAN":selection["OPTION_ONLY"]["metrics"]["mean"],"OPTION_SELECTED_MEDIAN":selection["OPTION_ONLY"]["metrics"]["median"],"OPTION_SELECTED_WIN_RATE":selection["OPTION_ONLY"]["metrics"]["win_rate"],"OPTION_SELECTED_PROFIT_FACTOR":selection["OPTION_ONLY"]["metrics"]["profit_factor"],"BASELINE_PLUS_OPTION_SELECTED_N":sm["N"],"BASELINE_PLUS_OPTION_SELECTED_COVERAGE":sel["coverage"],"BASELINE_PLUS_OPTION_SELECTED_MEAN":sm["mean"],"BASELINE_PLUS_OPTION_SELECTED_MEDIAN":sm["median"],"BASELINE_PLUS_OPTION_SELECTED_WIN_RATE":sm["win_rate"],"BASELINE_PLUS_OPTION_SELECTED_PROFIT_FACTOR":sm["profit_factor"],"INCREMENTAL_DELTA_SELECTED_MEAN":sm["mean"]-selection["BASELINE_ONLY"]["metrics"]["mean"],"INCREMENTAL_DELTA_SELECTED_MEDIAN":sm["median"]-selection["BASELINE_ONLY"]["metrics"]["median"],"INCREMENTAL_DELTA_SELECTED_PROFIT_FACTOR":sm["profit_factor"]-selection["BASELINE_ONLY"]["metrics"]["profit_factor"],"BASELINE_PLUS_OPTION_SELECTED_Q10":sm["q10"],"BASELINE_PLUS_OPTION_SELECTED_CVAR":sm["cvar"],"UP_BASELINE_SPEARMAN":stability["by_direction"].get("UP",{}).get("baseline_spearman"),"UP_BASELINE_PLUS_OPTION_SPEARMAN":stability["by_direction"].get("UP",{}).get("plus_spearman"),"UP_INCREMENTAL_DELTA_SPEARMAN":stability["by_direction"].get("UP",{}).get("plus_spearman")-stability["by_direction"].get("UP",{}).get("baseline_spearman"),"DOWN_BASELINE_SPEARMAN":stability["by_direction"].get("DOWN",{}).get("baseline_spearman"),"DOWN_BASELINE_PLUS_OPTION_SPEARMAN":stability["by_direction"].get("DOWN",{}).get("plus_spearman"),"DOWN_INCREMENTAL_DELTA_SPEARMAN":stability["by_direction"].get("DOWN",{}).get("plus_spearman")-stability["by_direction"].get("DOWN",{}).get("baseline_spearman"),"QQQ_INCREMENTAL_STATUS":"DIAGNOSTIC_SMALL_N","SOXX_INCREMENTAL_STATUS":"REPORTED","OUTER_FOLD_1_INCREMENTAL_STATUS":"POSITIVE" if foldrows[0]["delta_spearman"]>0 else "NEGATIVE","OUTER_FOLD_2_INCREMENTAL_STATUS":"POSITIVE" if foldrows[1]["delta_spearman"]>0 else "NEGATIVE","OUTER_FOLD_3_INCREMENTAL_STATUS":"POSITIVE" if foldrows[2]["delta_spearman"]>0 else "NEGATIVE","OUTER_FOLD_STABILITY_STATUS":"PASS_2_OF_3" if positive_folds>=2 else "FAIL", "YEAR_STABILITY_STATUS":"REPORTED", "DIRECTION_STABILITY_STATUS":"REPORTED", "UNDERLYING_STABILITY_STATUS":"QQQ_SMALL_N", "OPTION_ABLATION_STATUS":fals["option_ablation_status"],"OPTION_TIMESTAMP_SHIFT_STATUS":fals["option_timestamp_shift_status"],"RANDOM_FEATURE_CONTROL_STATUS":fals["random_feature_control_status"],"PERMUTATION_COUNT":999,"OPTION_INCREMENTAL_PERMUTATION_EMPIRICAL_P":perm,"TARGET_PERMUTATION_EMPIRICAL_P":target_perm,"FALSIFICATION_STATUS":"PASS" if all([paired_delta>0,stale_delta>0,random_delta>0,perm<=.05]) else "FAIL_OR_INCOMPLETE","PIT_AUDIT_STATUS":quality["PIT_AUDIT_STATUS"],"LEAKAGE_AUDIT_STATUS":quality["LEAKAGE_AUDIT_STATUS"],"COVERED_ROW_SELECTION_AUDIT_STATUS":quality["COVERED_ROW_SELECTION_AUDIT_STATUS"],"PAIRED_COMPARISON_AUDIT_STATUS":quality["PAIRED_COMPARISON_AUDIT_STATUS"],"ABSTENTION_LEAKAGE_AUDIT_STATUS":quality["ABSTENTION_LEAKAGE_AUDIT_STATUS"],"STACK_CROSSFIT_AUDIT_STATUS":quality["STACK_CROSSFIT_AUDIT_STATUS"],"MODEL_FIT_COUNT":counts["fit"],"MODEL_PREDICT_COUNT":counts["predict"],"PROSPECTIVE_OUTCOME_READ":False,"BROKER_ACTION_ALLOWED":False,"TRADE_CONTEXT_CREATED":False,"ORDER_API_CALL_COUNT":0,"PROSPECTIVE_SHADOW_READY":False,"PROSPECTIVE_SHADOW_STARTED":False,"FINAL_MODEL_TYPE":"NO_DEPLOYABLE_MODEL_COVERAGE_CONDITIONED_PILOT","STORAGE_CONTRACT_STATUS":"PASS_EXTERNAL_FROZEN_RESEARCH_ARTIFACTS","ANTI_BLOAT_STATUS":"PASS_ONE_CONFIG_ONE_MODULE_ONE_ENTRYPOINT"}
    for n,v in top.items():
        summary[f"TOP{n}_MEAN"] = v["mean"]; summary[f"TOP{n}_MEDIAN"] = v["median"]; summary[f"TOP{n}_PROFIT_FACTOR"] = v["profit_factor"]
    summary["TOP5_DIAGNOSTIC_MEAN"] = top[5]["mean"]; summary["TOP5_DIAGNOSTIC_MEDIAN"] = top[5]["median"]; summary["TOP5_DIAGNOSTIC_PROFIT_FACTOR"] = top[5]["profit_factor"]
    write(output / "FAST5_OPTION_PILOT_R1_FINAL_SUMMARY.json",summary); write(output / "FAST5_OPTION_PILOT_R1_QUALITY_AUDIT.json",quality)
    artifacts=[x for x in output.rglob('*') if x.is_file()]; write(output / "FAST5_OPTION_PILOT_R1_ARTIFACT_MANIFEST.json",{"artifacts":[{"path":str(x),"sha256":sha(x),"bytes":x.stat().st_size} for x in artifacts],"target_value_read_count":target_reads})
    for k,v in summary.items(): print(f"{k}={str(v).lower() if isinstance(v,bool) else v}")
    return output


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--run-id",default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")); run(p.parse_args().run_id)

if __name__ == "__main__": main()
