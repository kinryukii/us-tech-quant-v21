"""Two-stage frozen joint-batch replay: freeze identities, then run a scenario.

`--freeze` hashes sources and fixed policies without deserializing 2026 market
tables or economic results. `--run` requires that manifest before any market
read. Scenarios reuse the original engine and account policy methods.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import ntpath
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "joint_linear_tree_coverage_v2" / "bundle"))
sys.path.insert(0, str(ROOT / "followup_review" / "valuation"))

from engine import run_replay  # noqa: E402
from joint_linear_tree import JointActionValuePolicy, FEATURES, sha as model_sha  # noqa: E402
from joint_risk import JointRiskPolicy  # noqa: E402
from risk import FrozenRisk  # noqa: E402
from run_suite import Stateful, forbid_fitting, metrics  # noqa: E402
from v2_policy import load_policy_v2  # noqa: E402
from price_overlay import gate_prices_with_r7_exact  # noqa: E402


OUT = ROOT / "evaluation_2026_sampling_v2"
MANIFEST = OUT / "PRE_SCORE_BATCH_FREEZE.json"
V2 = ROOT / "joint_linear_tree_coverage_v2" / "out"
OVERLAY = ROOT / "followup_review" / "valuation" / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
OVERLAY_RECEIPT = ROOT / "followup_review" / "valuation" / "R7_OVERLAY_RECEIPT.json"
OLD_FIT = ROOT / "joint_linear_tree_artifacts" / "FIT_RECEIPT.json"
V2_FIT = V2 / "FIT_RECEIPT.json"
TEST_PANEL = ROOT / "data" / "test_features_context.parquet"
TEST_PRICES = ROOT / "data" / "test_prices.parquet"
TEST_CALENDAR = ROOT / "data" / "calendar.parquet"
ESTIMATOR_NAMES = ["ridge", "elastic_net", "logistic", "hgb", "q10", "q50", "q90"]
AFFECTED = [f"joint_{name}" for name in ESTIMATOR_NAMES] + [
    "joint_quantile_risk", "joint_hgb_lw", "joint_hgb_pca",
]
UNCHANGED = ["joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control", "hgb_return_baseline"]
ROSTER = [
    "joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
    "joint_q10", "joint_q50", "joint_q90", "joint_quantile_risk",
    "joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control",
    "hgb_return_baseline", "joint_hgb_lw", "joint_hgb_pca",
]
SCENARIOS = {
    "r6_v2_10": dict(folder="r6_v2", cost=10, gate="r6", version="v2", run=AFFECTED, links=UNCHANGED),
    "r6_v2_5": dict(folder="r6_v2", cost=5, gate="r6", version="v2", run=AFFECTED, links=UNCHANGED),
    "r6_v2_25": dict(folder="r6_v2", cost=25, gate="r6", version="v2", run=AFFECTED, links=UNCHANGED),
    "r7_original_10": dict(folder="r7_original", cost=10, gate="r7", version="original", run=ROSTER, links=[]),
    "r7_v2_10": dict(folder="r7_v2", cost=10, gate="r7", version="v2", run=AFFECTED, links=UNCHANGED),
}
FIXED_IMAGE = "sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               default=str, allow_nan=False), encoding="utf-8")


def original_selected(stage: str = "final") -> dict[str, Path]:
    receipt = read_json(OLD_FIT)
    if receipt["status"] != "PASS":
        raise RuntimeError("Original fit receipt not PASS")
    selected = {}
    for name in ESTIMATOR_NAMES:
        records = [r for r in receipt["fits"] if r["stage"] == stage and r["name"] == name]
        if len(records) != 1:
            raise RuntimeError(f"Original model count changed: {name}")
        repairs = [r for r in receipt.get("numerical_repairs", [])
                   if r["stage"] == stage and r["name"] == name and r["used_for_policy"]]
        record = repairs[-1] if repairs else records[0]
        artifact = ROOT / "joint_linear_tree_artifacts" / ntpath.basename(record["artifact"])
        if sha(artifact) != record["artifact_sha256"]:
            raise RuntimeError(f"Original model hash mismatch: {name}")
        selected[name] = artifact
    return selected


def v2_selected(stage: str = "final") -> dict[str, Path]:
    receipt = read_json(V2_FIT)
    if receipt.get("status") != "PASS" or receipt.get("revision") != "DATE_COMPLETE_WITHIN_DAY_HASH_V2":
        raise RuntimeError("v2 fit receipt not frozen complete")
    selected = {}
    for name in ESTIMATOR_NAMES:
        records = [r for r in receipt["fits"] if r["stage"] == stage and r["name"] == name]
        if len(records) != 1:
            raise RuntimeError(f"v2 model count changed: {name}")
        repairs = [r for r in receipt.get("numerical_repairs", [])
                   if r["stage"] == stage and r["name"] == name and r["used_for_policy"]]
        record = repairs[-1] if repairs else records[0]
        artifact = V2 / Path(record["artifact"]).name
        if sha(artifact) != record["artifact_sha256"]:
            raise RuntimeError(f"v2 model hash mismatch: {name}")
        selected[name] = artifact
    return selected


def old_seal(cost: int) -> tuple[Path, dict]:
    path = ROOT / "evaluation_2026" / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json"
    seal = read_json(path)
    if seal["roster"] != ROSTER or seal["cost_bps_per_side"] != [10, 5, 25]:
        raise RuntimeError(f"Old frozen roster/cost mismatch: {cost}")
    return path, seal


def original_link_files() -> dict[str, str]:
    result = {}
    for cost in (10, 5, 25):
        for name in UNCHANGED:
            folder = ROOT / "evaluation_2026" / f"cost_{cost}" / f"{name}_{cost}bps"
            for basename in ("daily.parquet", "positions.parquet"):
                path = folder / basename
                result[str(path.relative_to(ROOT)).replace("\\", "/")] = sha(path)
    return result


def freeze() -> None:
    if MANIFEST.exists() or (OUT.exists() and any(OUT.iterdir())):
        raise RuntimeError("Preserve existing v2 test output; freeze requires a fresh output root")
    seals = {cost: old_seal(cost) for cost in (10, 5, 25)}
    first_sources = seals[10][1]["source_hashes"]
    for cost, (_, seal) in seals.items():
        if seal["source_hashes"] != first_sources:
            raise RuntimeError(f"Original {cost}bp source identity differs")
    # Raw-byte hash only. No 2026 table, prediction or result is deserialized.
    for relative, expected in first_sources.items():
        path = ROOT / relative.replace("\\", "/")
        if sha(path) != expected:
            raise RuntimeError(f"Original frozen source changed: {relative}")
    pre2026 = ROOT / "joint_linear_tree_coverage_v2" / "PRE2026_V2_FREEZE.json"
    preseal = read_json(pre2026)
    if preseal["status"] != "PRE2026_SUPERVISED_V2_FROZEN":
        raise RuntimeError("v2 pre-2026 seal absent")
    for relative, expected in preseal["files_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError(f"v2 pre-2026 artifact changed: {relative}")
    validation = read_json(ROOT / "evaluation_2025_sampling_v2" / "COMPLETE.json")
    if validation["status"] != "PRE2026_V2_VALIDATION_COMPLETE" or validation["evaluations"] != 8:
        raise RuntimeError("v2 2025 whole-account validation incomplete")
    old_models, new_models = original_selected(), v2_selected()
    overlay_receipt = read_json(OVERLAY_RECEIPT)
    if overlay_receipt["source_sha256"]["prices"] != sha(TEST_PRICES):
        raise RuntimeError("R7 overlay is not bound to the original test price source")

    # Every mounted inference input, policy, account and reporting file is
    # bound before any revised 2026 result. Linked old outcomes are bound only
    # as byte identities; their values never enter new policy callbacks.
    runtime_rel = [
        "data/test_features_context.parquet", "data/test_prices.parquet", "data/calendar.parquet",
        "data/DATA_AUDIT.json", "data/JOINT_DATA_AUDIT.json", "data/PRICE_SOURCE_RECEIPTS.json",
        "JOINT_CONTRACT.md", "engine.py", "run_suite.py", "joint_linear_tree.py",
        "joint_neural.py", "joint_risk.py", "risk.py", "models/predict.py",
        "models/model_registry.json", "models/hgb.joblib",
        "joint_linear_tree_artifacts/FIT_RECEIPT.json",
        "joint_linear_tree_coverage_v2/PRE2026_V2_FREEZE.json",
        "joint_linear_tree_coverage_v2/out/FIT_RECEIPT.json",
        "joint_linear_tree_coverage_v2/bundle/v2_policy.py",
        "evaluation_2025_sampling_v2/COMPLETE.json",
        "evaluation_2025_sampling_v2/PRE_REPLAY_FREEZE.json",
        "followup_review/valuation/price_overlay.py",
        "followup_review/valuation/summarize_replay_valuation.py",
        "followup_review/valuation/OVERLAY_ADAPTER_TECHNICAL_CHECK.json",
        "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "followup_review/valuation/R7_OVERLAY_RECEIPT.json",
        "followup_review/cost/replay_2026_sampling_v2.py",
        "followup_review/cost/run_2026_sampling_v2_container.ps1",
        "followup_review/cost/verify_2026_runner_technical.py",
        "followup_review/cost/technical_container_20260927_02/V2_2026_RUNNER_TECHNICAL_CHECK.json",
        "followup_review/cost/technical_container_20260927_02/RUNTIME_TECHNICAL_COMMAND.json",
        "followup_review/cost/technical_container_20260927_02/RUNTIME_TECHNICAL_INSPECT.json",
        "followup_review/cost/technical_container_20260927_02/RUNTIME_TECHNICAL_RECEIPT.json",
        "followup_review/cost/V2_BASELINE_HGB_EQUIVALENCE.json",
        "risk/frozen_covariance.npz", "risk/TRAIN_RECEIPT.json",
        "joint_neural_artifacts/final_normalization.npz",
        "joint_neural_artifacts/final_direct_20260927.pt",
        "joint_neural_artifacts/final_rl_20260927.pt",
        "joint_neural_artifacts/final_rl_20260928.pt",
        "joint_neural_artifacts/final_rl_20260927_zero.pt",
        "joint_neural_artifacts/final_rl_20260928_zero.pt",
    ]
    runtime_rel += [str(p.relative_to(ROOT)).replace("\\", "/")
                    for p in list(old_models.values()) + list(new_models.values())]
    runtime_rel += [str(path.relative_to(ROOT)).replace("\\", "/") for path, _ in seals.values()]
    runtime_rel += [f"evaluation_2026/cost_{cost}/comparison.csv" for cost in (10, 5, 25)]
    runtime_hashes = {rel: sha(ROOT / rel) for rel in sorted(set(runtime_rel))}
    old_links = original_link_files()
    manifest = dict(
        status="JOINT_SAMPLING_V2_FULL_BATCH_FROZEN_BEFORE_REVISED_SCORING",
        batch="a2_latest_effective_joint_20260927",
        image_id=FIXED_IMAGE,
        pre2026_v2_seal_sha256=sha(pre2026),
        original_frozen_test_seals_sha256={str(cost): sha(path) for cost, (path, _) in seals.items()},
        original_frozen_test_source_sha256=first_sources,
        runtime_files_sha256=runtime_hashes,
        original_result_link_files_sha256=old_links,
        roster=ROSTER,
        costs_bps_per_side=[10, 5, 25],
        model_mapping={
            "joint_ridge/joint_elastic_net/joint_logistic/joint_hgb/joint_q10/joint_q50/joint_q90": "v2 final in r6_v2 and r7_v2; original final in r7_original",
            "joint_quantile_risk": "v2 final q10/q50/q90 in v2 scenarios; original final q10/q50/q90 in r7_original",
            "joint_hgb_lw/joint_hgb_pca": "same frozen risk and original solver, explicitly v2 final HGB base in v2 scenarios; original HGB base in r7_original",
            "joint_mlp/joint_rl_ensemble/joint_rl_zero_control/hgb_return_baseline": "original frozen models and policy; original R6 result linked in v2 R6; original R7 replay linked in v2 R7",
        },
        scenario_plan=SCENARIOS,
        test_window=dict(signals="2026-01-02 through 2026-09-22",
                         last_execution="2026-09-23", terminal_mark="2026-09-24"),
        source_asof_identity=dict(
            data_audit_sha256=runtime_hashes["data/DATA_AUDIT.json"],
            price_source_receipts_sha256=runtime_hashes["data/PRICE_SOURCE_RECEIPTS.json"],
            explicit_test_asof_timestamp="not present in original joint-batch source metadata; no invented timestamp",
        ),
        price_scenarios=dict(
            r6="original warning gate; flagged quotes become unavailable at consumption",
            r7="conditional posthoc exact-price gate, all 811 policy-independent verified keys; distinct from R6 main scenario",
        ),
        report_rule="full-path indicative return null when any daily NAV is nonfinite; retain original metric only as diagnostic",
        historical_2026_exposure_acknowledged=True,
        shareholder_total_return_certified=False,
        freeze_deserializes_2026_economic_values=False,
        training_after_freeze_forbidden=True,
    )
    OUT.mkdir(exist_ok=True)
    write_json(MANIFEST, manifest)
    print("JOINT_V2_BATCH_FROZEN", sha(MANIFEST), flush=True)


class OriginalMappedPolicy(JointActionValuePolicy):
    """Use original final joblib hashes while resolving Windows paths in Linux."""

    def __init__(self, name: str):
        self.name, self.stage = name, "final"
        receipt = read_json(OLD_FIT)
        names = ("q10", "q50", "q90") if name == "quantile_risk" else (name,)
        self.models = {}
        selected = original_selected()
        for model_name in names:
            self.models[model_name] = joblib.load(selected[model_name])
        self.last_actions = None


class VersionedRisk(JointRiskPolicy):
    def __init__(self, *, factor: bool, version: str):
        # The original constructor loads v1 HGB. Set the same risk/solver
        # fields explicitly, then bind the versioned base before any call.
        self.base = (load_policy_v2("hgb", "final", V2) if version == "v2"
                     else OriginalMappedPolicy("hgb"))
        self.risk = FrozenRisk()
        self.factor = factor
        self.last_diagnostic = {}


class VersionedStateful(Stateful):
    def __init__(self, name: str, version: str):
        if name in UNCHANGED:
            super().__init__(name, "final")
            return
        self.name, self.age, self.lastdate, self.records = name, {}, None, []
        if name in ("joint_hgb_lw", "joint_hgb_pca"):
            self.policy = VersionedRisk(factor=name.endswith("pca"), version=version)
        else:
            method = name.removeprefix("joint_")
            self.policy = (load_policy_v2(method, "final", V2) if version == "v2"
                           else OriginalMappedPolicy(method))


def baseline_hgb_scores(panel: pd.DataFrame) -> pd.DataFrame:
    registry = read_json(ROOT / "models" / "model_registry.json")
    record = registry["models"]["hgb"]
    path = ROOT / "models" / "hgb.joblib"
    if sha(path) != record["sha256"]:
        raise RuntimeError("Original HGB baseline model hash mismatch")
    if list(registry["feature_order"]) != list(FEATURES):
        raise RuntimeError("Original baseline feature order changed")
    model = joblib.load(path)
    scores = model.predict(panel[FEATURES].to_numpy(float))
    if not np.isfinite(scores).all():
        raise RuntimeError("Nonfinite original HGB baseline score")
    return pd.DataFrame({"signal_date": panel.signal_date, "ticker": panel.ticker,
                         "baseline_hgb": scores})


def safe_metrics(result, name: str, cost: int) -> dict:
    row = metrics(result, name, cost, 2026)
    finite = np.isfinite(result.daily.nav.to_numpy(float))
    row["all_daily_nav_finite"] = bool(finite.all())
    row["terminal_nav_finite"] = bool(finite[-1])
    row["original_last_finite_indicative_return"] = row["indicative_return"]
    if not finite.all():
        row["indicative_return"] = None
        row["indicative_max_drawdown"] = None
        row["all_prices_current_path_return"] = None
        row["full_path_return_status"] = "unavailable_nonfinite_nav"
    else:
        row["full_path_return_status"] = "complete_price_coordinate_proxy"
    return row


def link_records(name: str, scenario: dict) -> list[dict]:
    cost = scenario["cost"]
    result = []
    for policy in scenario["links"]:
        if name.startswith("r6_v2_"):
            source = ROOT / "evaluation_2026" / f"cost_{cost}" / f"{policy}_{cost}bps"
        else:
            source = OUT / "r7_original" / "cost_10" / f"{policy}_10bps"
        hashes = {base: sha(source / base) for base in ("daily.parquet", "positions.parquet")}
        result.append(dict(policy=policy, cost_bps=cost,
                           source_directory=str(source.relative_to(ROOT)).replace("\\", "/"),
                           source_sha256=hashes))
    return result


def run(name: str) -> None:
    if name not in SCENARIOS:
        raise RuntimeError("Unknown frozen scenario")
    if not MANIFEST.exists():
        raise RuntimeError("No full-batch freeze manifest")
    manifest = read_json(MANIFEST)
    if manifest["status"] != "JOINT_SAMPLING_V2_FULL_BATCH_FROZEN_BEFORE_REVISED_SCORING" or manifest["scenario_plan"] != SCENARIOS:
        raise RuntimeError("Frozen batch identity changed")
    if manifest["image_id"] != FIXED_IMAGE:
        raise RuntimeError("Runtime image identity changed")
    for rel, expected in manifest["runtime_files_sha256"].items():
        if sha(ROOT / rel) != expected:
            raise RuntimeError(f"Runtime source changed since freeze: {rel}")
    for rel, expected in manifest["original_result_link_files_sha256"].items():
        if sha(ROOT / rel) != expected:
            raise RuntimeError(f"Original R6 linked result changed since freeze: {rel}")
    for cost, expected in manifest["original_frozen_test_seals_sha256"].items():
        if sha(old_seal(int(cost))[0]) != expected:
            raise RuntimeError("Original test seal changed")
    if sha(ROOT / "joint_linear_tree_coverage_v2" / "PRE2026_V2_FREEZE.json") != manifest["pre2026_v2_seal_sha256"]:
        raise RuntimeError("v2 pre-2026 seal changed")
    scenario = SCENARIOS[name]
    destination = OUT / scenario["folder"] / f"cost_{scenario['cost']}"
    if destination.exists():
        raise RuntimeError("Preserve existing scenario output; no overwrite")
    if name == "r7_v2_10" and not (OUT / "r7_original" / "cost_10" / "COMPLETE.json").is_file():
        raise RuntimeError("Original frozen policies must complete R7 replay first")

    fit_guard = forbid_fitting()
    # This is the first deserialization of 2026 market rows. All identities
    # above were checked against the pre-score freeze before reaching here.
    panel = pd.read_parquet(TEST_PANEL)
    raw_prices = pd.read_parquet(TEST_PRICES)
    calendar_frame = pd.read_parquet(TEST_CALENDAR)
    calendar = pd.DatetimeIndex(calendar_frame.loc[calendar_frame.is_test, "trade_date"])
    if scenario["gate"] == "r6":
        prices = raw_prices.copy()
        warnings = prices.price_quality_warning.astype(bool)
        prices.loc[warnings, ["open", "close"]] = np.nan
        gate_receipt = dict(status="ORIGINAL_R6_PRICE_WARNING_GATE", mode="R6",
                            price_source_sha256=manifest["runtime_files_sha256"]["data/test_prices.parquet"],
                            original_warning_rows=int(warnings.sum()), restored_keys=0)
    else:
        prices, gate_receipt = gate_prices_with_r7_exact(
            raw_prices,
            raw_price_sha256=manifest["runtime_files_sha256"]["data/test_prices.parquet"],
            overlay_path=OVERLAY,
            expected_overlay_sha256=manifest["runtime_files_sha256"][
                "followup_review/valuation/R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"],
            receipt_path=OVERLAY_RECEIPT,
            expected_receipt_sha256=manifest["runtime_files_sha256"][
                "followup_review/valuation/R7_OVERLAY_RECEIPT.json"],
        )
        gate_receipt = dict(gate_receipt, mode="R7",
                            price_source_sha256=manifest["runtime_files_sha256"]["data/test_prices.parquet"],
                            restored_keys=gate_receipt["r7_exact_keys_restored"])
    if calendar.empty or calendar.max() != pd.Timestamp("2026-09-24"):
        raise RuntimeError("Unexpected frozen test calendar")
    panel = panel.loc[panel.signal_date.le("2026-09-22")].copy()
    baseline = baseline_hgb_scores(panel)
    panel = panel.merge(baseline, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    keep = ["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + list(FEATURES)
    panel = panel[keep]
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "PRICE_GATE.json", gate_receipt)
    write_json(destination / "SCENARIO_IDENTITY.json",
               dict(batch_manifest_sha256=sha(MANIFEST), scenario=name,
                    policy_version=scenario["version"], price_gate=scenario["gate"],
                    cost_bps_each_side=scenario["cost"], policies_run=scenario["run"],
                    policies_linked=scenario["links"], no_new_fit=True))
    if scenario["links"]:
        write_json(destination / "LINKED_ORIGINAL_RESULTS.json", dict(links=link_records(name, scenario)))
    rows = []
    for policy in scenario["run"]:
        actor = VersionedStateful(policy, scenario["version"])
        with threadpool_limits(limits=2):
            result = run_replay(
                prices, calendar, panel, actor, candidate=policy,
                initial_cash=1_000_000.0, cost_bps=float(scenario["cost"]),
                max_weight=.10, max_positions=20, max_invested=.95,
                capacity_fraction=.01, missing_signal_policy="cash",
                signal_start="2026-01-01", signal_end="2026-09-22",
            )
        folder = destination / f"{policy}_{scenario['cost']}bps"
        folder.mkdir(exist_ok=False)
        for key in ("daily", "trades", "positions", "target_decisions",
                    "diagnostics", "valuation_intervals"):
            getattr(result, key).to_parquet(folder / f"{key}.parquet", index=False)
        write_json(folder / "metadata.json", result.metadata)
        if actor.records:
            write_json(folder / "risk_solver.json", actor.records)
        row = safe_metrics(result, policy, scenario["cost"])
        row["reused_result"] = False
        row["source_directory"] = str(folder.relative_to(ROOT)).replace("\\", "/")
        rows.append(row)
        pd.DataFrame(rows).to_csv(destination / "comparison.partial.csv", index=False)
        print("JOINT_V2_TEST_SCENARIO_POLICY", name, policy, row["days"], row["full_path_return_status"], flush=True)
        del actor, result
        gc.collect()
    if fit_guard["attempts"] != 0:
        raise RuntimeError("Fitting was attempted during frozen test replay")
    (destination / "comparison.partial.csv").replace(destination / "comparison.csv")
    by_policy = {row["policy"]: row for row in rows}
    if scenario["links"]:
        comparison_source = (ROOT / "evaluation_2026" / f"cost_{scenario['cost']}" / "comparison.csv"
                             if name.startswith("r6_v2_") else
                             OUT / "r7_original" / "cost_10" / "comparison.csv")
        source_rows = pd.read_csv(comparison_source).set_index("policy")
        for link in link_records(name, scenario):
            policy = link["policy"]
            source = ROOT / link["source_directory"]
            linked = source_rows.loc[policy].to_dict()
            linked["policy"] = policy
            linked["reused_result"] = True
            linked["source_directory"] = link["source_directory"]
            old_daily = pd.read_parquet(source / "daily.parquet", columns=["nav"])
            finite = np.isfinite(old_daily.nav.to_numpy(float))
            linked["all_daily_nav_finite"] = bool(finite.all())
            linked["terminal_nav_finite"] = bool(finite[-1])
            linked["original_last_finite_indicative_return"] = linked["indicative_return"]
            if not finite.all():
                linked["indicative_return"] = None
                linked["indicative_max_drawdown"] = None
                linked["all_prices_current_path_return"] = None
                linked["full_path_return_status"] = "unavailable_nonfinite_nav"
            else:
                linked["full_path_return_status"] = "complete_price_coordinate_proxy"
            by_policy[policy] = linked
    if set(by_policy) != set(ROSTER):
        raise RuntimeError("Unified fixed 14-policy roster is incomplete")
    pd.DataFrame([by_policy[policy] for policy in ROSTER]).to_csv(
        destination / "comparison_all14.csv", index=False)
    write_json(destination / "COMPLETE.json", dict(
        status="FROZEN_SCENARIO_REPLAY_COMPLETE", scenario=name,
        policies_run=scenario["run"], policies_linked=scenario["links"],
        cost_bps_each_side=scenario["cost"], price_gate=scenario["gate"],
        fit_guard_attempts=fit_guard["attempts"],
        training_2026_rows=0, full_pool_formal_result=False,
        metric_rule=manifest["report_rule"],
    ))
    print("JOINT_V2_TEST_SCENARIO_COMPLETE", name, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument("--freeze", action="store_true")
    phase.add_argument("--run", choices=sorted(SCENARIOS))
    args = parser.parse_args()
    freeze() if args.freeze else run(args.run)


if __name__ == "__main__":
    main()
