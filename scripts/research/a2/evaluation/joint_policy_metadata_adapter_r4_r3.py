"""R3 equivalent metadata adapter: proof applies to the complete requested pool.

All current-day rows still enter the unchanged current_pool eligibility/UID
helper. Unknown or duplicate rows of eligible assets block, never get removed.
Off-pool rows do not invalidate the already-proven contiguous-epoch suffix.
R1/R2 sources, audits, original wrapper and frozen science remain unchanged.
"""
from pathlib import Path
import pandas as pd
from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4 as base
from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4_r2 as r2
policy, old = base.policy, base.old
OriginalDailyMetadataPool = policy.DailyMetadataPool
AUDIT = "POLICY_METADATA_EQUIVALENCE_AUDIT_R3.json"
BINDING = "POLICY_METADATA_ENGINEERING_BINDING_R3.json"


class EpochCarryMetadataPoolR3(base.EpochCarryMetadataPool):
    """Original full rebuild or exact consecutive full-pool epoch carry."""
    def __call__(self, day):
        day = pd.Timestamp(day).normalize()
        if day not in self.positions or day >= old.BOUNDARY or (self.loaded_through is not None and day <= self.loaded_through):
            raise policy.PolicyInputBlocked("MONOTONE_LEGAL_COMMON_SESSION_REQUIRED")
        if not self.witness.unchanged():
            old._pin(self.witness.path, self.witness.sha256, "immutable_policy_history_changed")
            consecutive = False
        else:
            consecutive = (self.loaded_through is not None and self.previous_pool is not None
                and self.positions[day] == self.positions[self.loaded_through] + 1)
        if not consecutive or day in self.quarter_starts:
            result = OriginalDailyMetadataPool.__call__(self, day)
            self.full_helper_calls += 1
            raw = None
        else:
            added = self.reader.read("prediction_features", old.FEATURE_META, date_field="signal_date",
                start=self.loaded_through + pd.Timedelta(days=1),
                stop=(day + pd.Timedelta(days=1) if day + pd.Timedelta(days=1) < old.BOUNDARY else None))
            dates = pd.to_datetime(added.signal_date)
            if (dates <= self.loaded_through).any() or (dates > day).any():
                raise policy.PolicyInputBlocked("NEW_METADATA_WINDOW_REWRITES_PAST_OR_OBSERVES_FUTURE")
            self.history = pd.concat([self.history, added], ignore_index=True)
            raw = self.reader.read("raw_open_close", ("ticker", "trade_date"), date_field="trade_date", day=day)
            today = added.loc[dates.eq(day)]
            # Crucially use all rows and the original eligibility predicate.
            # The original helper rejects missing/duplicate/nonunique eligible UID.
            local = old.current_pool(today, raw, self.days, base._clock(day))
            clean = not local["blocked_assets"] and not self.previous_pool["blocked_assets"]
            same = (tuple(local["assets"]) == tuple(self.previous_pool["assets"])
                and local["asset_uids"] == self.previous_pool["asset_uids"])
            if clean and same:
                result = {**local, "asset_epochs": dict(self.previous_pool["asset_epochs"]),
                    "segment_starts": dict(self.previous_pool["segment_starts"]),
                    "history": None, "history_not_materialised": True,
                    "epoch_carry_witness": dict(previous_common_session=str(self.loaded_through.date()),
                        current_common_session=str(day.date()),
                        previous_identity_sha256=base.content_hash(base.identity(self.previous_pool)),
                        new_metadata_keys_sha256=base.content_hash(added), immutable_source_sha256=self.witness.sha256,
                        complete_domain_uid_match=True, no_unknown_or_duplicate_requested_rows=True,
                        proof_domain="ORIGINAL_HELPER_COMPLETE_CURRENT_REQUESTED_POOL",
                        all_current_rows_original_eligibility_predicate=True, no_past_rewrite=True,
                        no_source_availability_authority_upgrade=True)}
                self.carry_calls += 1
            else:
                result = old.current_pool(self.history, raw, self.days, base._clock(day))
                self.full_helper_calls += 1
            self.loaded_through = day
        if day in self.audit_dates:
            if raw is None:
                raw = self.reader.read("raw_open_close", ("ticker", "trade_date"), date_field="trade_date", day=day)
            reference = old.current_pool(self.history, raw, self.days, base._clock(day))
            actual, expected = base.content_hash(base.identity(result)), base.content_hash(base.identity(reference))
            self.audits.append(dict(date=day.date().isoformat(), original_identity_sha256=expected,
                adapter_identity_sha256=actual, exact_identity_equal=actual == expected,
                numerical_quote_score_label_values_read=0, outcome_reads=0, new_fit_units=0))
            if actual != expected:
                raise policy.PolicyInputBlocked("METADATA_ADAPTER_NOT_EQUIVALENT_TO_ORIGINAL_HELPER")
        self.previous_pool = result
        return result


def invoke(run, phase):
    run = Path(run)
    inherited = policy.inherited_metadata
    original_pool, original_audit, original_binding = base.EpochCarryMetadataPool, base.AUDIT, base.BINDING
    base.EpochCarryMetadataPool, base.AUDIT, base.BINDING = EpochCarryMetadataPoolR3, AUDIT, BINDING
    policy.inherited_metadata = lambda root, spec: r2.canonical_inherited(inherited, root, spec)
    try:
        if phase == "support":
            proof = old.read_json(run / AUDIT)
            if proof.get("all_exact_equal") is not True or proof.get("carry_calls", 0) < 1:
                raise policy.PolicyInputBlocked("R3_REAL_METADATA_EXACT_CARRY_EQUIVALENCE_REQUIRED")
            old.write(run, "POLICY_METADATA_R3_EXTENSION_BINDING.json", dict(
                schema="B_R4_POLICY_METADATA_R3_EXTENSION_BINDING_V1", research_id=policy.ID,
                R3_extension_code_ref=policy._ref(__file__), R2_scope_adapter_ref=policy._ref(r2.__file__),
                R1_adapter_code_ref=policy._ref(base.__file__), original_wrapper_ref=policy._ref(policy.__file__),
                original_helper_ref=policy._ref(old.__file__), policy_spec_ref=policy._ref(run / policy.SPEC),
                audit_ref=policy._ref(run / AUDIT),
                scope_projection="ONLY_MISSING_SCOPE_ON_ORIGINAL_MAIN_LIST_DERIVES_MAIN",
                unknown_duplicate_proof_domain="ORIGINAL_HELPER_COMPLETE_CURRENT_REQUESTED_POOL",
                all_current_rows_original_eligibility_predicate=True,
                offpool_rows_retained_in_history=True, eligible_unknown_or_duplicate="ORIGINAL_HELPER_HARD_BLOCK",
                semantic_change=False, full_domain_UID_epoch_cadence_unchanged=True,
                new_fit_units=0, numeric_reads=0, outcome_reads=0, account_attempts=0, test2026_rows_read=0), immutable=True)
        return base.audit(run) if phase == "audit" else base.support(run)
    finally:
        base.EpochCarryMetadataPool, base.AUDIT, base.BINDING = original_pool, original_audit, original_binding
        policy.inherited_metadata = inherited


def main():
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", choices=["audit", "support"], required=True)
    args = parser.parse_args(); run = Path(args.run)
    lease = run / "work/leases/policy_metadata_engineering"
    base.assert_safe_output_path(lease, kind="backtest", paths=base.resolve(old.REPO))
    (lease / "work").mkdir(parents=True, exist_ok=True)
    with old.task_writer(lease):
        result = invoke(run, args.phase)
    print(json.dumps(old._json(result), allow_nan=False), flush=True)

if __name__ == "__main__":
    main()
