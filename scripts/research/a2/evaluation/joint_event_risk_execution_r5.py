"""R5 thin current-identity reader/assembly and durable risk execution adapter.

The original ProjectedReader, RiskInput assembler, StateCache and lifecycle own
reading, return coordinates, estimator state reuse and reservations. This module
changes the explicit R5 current-pool/event clock binding only. It never implements
risk estimates, allocation, accounts, price substitution or provider acquisition.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, replace
from pathlib import Path
import gc
import json
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.evaluation import joint_short_risk_execution_r4 as prior
from scripts.research.a2.evaluation import joint_r5_runtime as runtime
from scripts.research.a2.data import joint_event_risk_support_r5 as discovery
from scripts.research.a2.data.shared_risk_inputs_r3 import (
    assemble_risk_inputs, _calendar, _clock, STORED_LABEL_COORDINATE)
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, content_hash
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity


class _MetadataRow:
    """Scalar transport for the exact stock metadata fields, never a Series API."""
    __slots__ = ("_row_values", "_positions")
    def __init__(self, values, positions):
        self._row_values, self._positions = values, positions
    def __getitem__(self, key):
        return self._row_values[self._positions[key]]
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error


class _MetadataFrame(pd.DataFrame):
    """Metadata-only faster scalar iteration through unchanged assembler code.

    No parent function/global is altered. All pandas operations retain normal
    semantics; names conflicting with Series attributes use the native iterator.
    Numerical assembly never receives this subclass.
    """
    @property
    def _constructor(self):
        return _MetadataFrame
    def iterrows(self):
        columns = tuple(self.columns)
        safe = (len(set(columns)) == len(columns) and all(isinstance(c,str) and
            not c.startswith("_") and not hasattr(pd.Series,c) and c not in {"name","index"}
            for c in columns))
        if not safe:
            yield from super().iterrows()
            return
        positions = {c:i for i,c in enumerate(columns)}
        for key, values in zip(self.index,self.itertuples(index=False,name=None)):
            yield key,_MetadataRow(values,positions)

SUPPORT = discovery.OUTPUT
QUALIFICATION = "support/RISK_EVENT_QUALIFICATION_R5.json"
BANK = "models/risk/EVENT_RISK_BANK_R5.json"
FREEZE = "R5_SCIENCE_AND_EXECUTION_FREEZE.json"
CONTINUOUS = frozenset(("SHR_HP","SHR_CC","LW","OAS","EWMA","PCA_FACTOR","QQQ_RESIDUAL"))


def ref(path):
    return dict(path=str(Path(path)), sha256=old.sha(path))


def read_event_support(run, *, expected_sha256):
    path = Path(run) / SUPPORT
    assert_safe_output_path(path, kind="backtest", paths=resolve(old.REPO))
    old._pin(path, expected_sha256, "R5_EVENT_METADATA_SUPPORT")
    # Exact R5 metadata file is 76 MiB. No generic JSON limit is weakened.
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("R5_EXACT_EVENT_METADATA_SIZE_LIMIT")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if (result.get("schema") != "B_R5_EVENT_RISK_METADATA_SUPPORT_V1"
            or result.get("research_id") != runtime.ID
            or result.get("decision_session_count") != 752
            or any(result.get(k) != 0 for k in ("numeric_reads", "new_fit_units", "account_attempts", "test2026_rows_read"))
            or result.get("strict_PIT_promotion_eligible") is not False):
        raise ValueError("EXACT_752_ZERO_VALUE_SUPPORT_REQUIRED")
    return result


def read_event_qualification(run, *, qualification_ref):
    """Bounded exact R5 metadata only; generic source readers stay unchanged."""
    import hashlib
    paths = {Path(run) / QUALIFICATION,
             Path(run) / "support/RISK_EVENT_QUALIFICATION_READER_RECOVERY_R5_R1.json"}
    if (not isinstance(qualification_ref, dict)
            or set(qualification_ref) != {"path", "sha256"}
            or not isinstance(qualification_ref["path"], str)
            or Path(qualification_ref["path"]) not in paths
            or not isinstance(qualification_ref["sha256"], str)
            or len(qualification_ref["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in qualification_ref["sha256"])):
        raise ValueError("EXACT_R5_QUALIFICATION_REF_REQUIRED")
    path = Path(qualification_ref["path"])
    # Reject foreign roots and parent links before any resolver can follow them.
    import stat
    for checked in (path, Path(__file__)):
        if not checked.is_absolute() or checked.drive.upper() != "D:":
            raise ValueError("R5_QUALIFICATION_ABSOLUTE_D_PATH_REQUIRED")
        for ancestor in reversed((checked, *checked.parents)):
            info = ancestor.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                raise ValueError("R5_QUALIFICATION_REPARSE_POINT_FORBIDDEN")
    old._safe_source(path)
    assert_safe_output_path(path, kind="backtest", paths=resolve(old.REPO))
    limit = 256 * 1024 * 1024
    if path.stat().st_size > limit:
        raise ValueError("R5_EXACT_QUALIFICATION_METADATA_SIZE_LIMIT")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("R5_EXACT_QUALIFICATION_METADATA_SIZE_LIMIT")
    if hashlib.sha256(payload).hexdigest() != qualification_ref["sha256"]:
        raise ValueError("R5_QUALIFICATION_PHYSICAL_SHA_CHANGED")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("R5_QUALIFICATION_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    result = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique_keys)
    del payload
    fields = {"schema", "research_id", "plan_ref", "support_ref",
              "source_authority_ref", "producer_ref", "model_producer_ref",
              "nodes", "reader_projection_audit", "numeric_reads",
              "new_fit_units", "account_attempts", "outcome_reads",
              "test2026_rows_read", "strict_PIT_promotion_eligible"}
    counters = ("numeric_reads", "new_fit_units", "account_attempts",
                "outcome_reads", "test2026_rows_read")
    recovery = path.name == "RISK_EVENT_QUALIFICATION_READER_RECOVERY_R5_R1.json"
    if recovery:
        fields.add("engineering_recovery")
    if (not isinstance(result, dict) or set(result) != fields
            or result["schema"] != "B_R5_FINITE_EVENT_RISK_QUALIFICATION_V1"
            or result["research_id"] != runtime.ID
            or any(type(result[k]) is not int or result[k] != 0 for k in counters)
            or result["strict_PIT_promotion_eligible"] is not False
            or not isinstance(result["nodes"], list)
            or not isinstance(result["reader_projection_audit"], list)
            or len(result["nodes"]) != 55):
        raise ValueError("EXACT_R5_ZERO_VALUE_QUALIFICATION_REQUIRED")
    for audit in result["reader_projection_audit"]:
        if (not isinstance(audit, dict) or not isinstance(audit.get("columns"), list)
                or any(not isinstance(c, str) for c in audit["columns"])
                or (old.FORBIDDEN | {"nav", "returns", "sharpe", "mu", "sigma", "covariance"}).intersection(audit["columns"])):
            raise ValueError("R5_QUALIFICATION_NUMERIC_PROJECTION_FORBIDDEN")
    ids = [n.get("node_id") if isinstance(n, dict) else None for n in result["nodes"]]
    if any(not isinstance(k, str) or not k for k in ids) or len(set(ids)) != len(ids):
        raise ValueError("EXACT_UNIQUE_R5_QUALIFICATION_NODE_ROSTER_REQUIRED")
    if recovery:
        proof = result["engineering_recovery"]
        proof_fields = {"original_qualification_ref", "retained_nodes_sha256",
                        "original_failed_node", "recovered_node_id",
                        "recovery_producer_ref", "engineering_only", "numeric_reads"}
        if (not isinstance(proof, dict) or set(proof) != proof_fields
                or proof["engineering_only"] is not True
                or type(proof["numeric_reads"]) is not int or proof["numeric_reads"] != 0
                or len(result["nodes"]) != 55
                or proof["retained_nodes_sha256"] != content_hash(result["nodes"][:-1])):
            raise ValueError("EXACT_R5_FINAL_NODE_RECOVERY_PROOF_REQUIRED")
        origin = proof["original_qualification_ref"]
        producer = proof["recovery_producer_ref"]
        if (not isinstance(origin, dict) or set(origin) != {"path", "sha256"}
                or not isinstance(origin["path"], str) or Path(origin["path"]) != Path(run) / QUALIFICATION
                or not isinstance(producer, dict) or set(producer) != {"path", "sha256"}
                or not isinstance(producer["path"], str)
                or any(not isinstance(r["sha256"], str) or len(r["sha256"]) != 64
                       or any(c not in "0123456789abcdef" for c in r["sha256"])
                       for r in (origin, producer))):
            raise ValueError("EXACT_R5_RECOVERY_SOURCE_CUSTODY_REQUIRED")
        failed, current = proof["original_failed_node"], result["nodes"][-1]
        identity = ("node_id", "event_id", "recipe_id", "dependency", "families")
        if (not isinstance(failed, dict)
                or failed.get("status") != "BLOCKED_METADATA"
                or failed.get("block_reason") != "PRE2026_READER_CUTOFF_REQUIRED"
                or proof["recovered_node_id"] != current["node_id"]
                or any(failed.get(k) != current.get(k) for k in identity)):
            raise ValueError("ONLY_ORIGINAL_FINAL_READER_BLOCK_RECOVERABLE")
        if Path(producer["path"]) != Path(__file__):
            raise ValueError("EXACT_R5_RECOVERY_PRODUCER_PATH_REQUIRED")
        old._pin(producer["path"], producer["sha256"], "R5_QUALIFICATION_RECOVERY_PRODUCER")
        original = read_event_qualification(run, qualification_ref=origin)
        if (original["nodes"][:-1] != result["nodes"][:-1]
                or original["nodes"][-1] != failed
                or any(original[k] != result[k] for k in
                       ("plan_ref", "support_ref", "source_authority_ref",
                        "producer_ref", "model_producer_ref"))
                or result["reader_projection_audit"][:len(original["reader_projection_audit"])]
                   != original["reader_projection_audit"]):
            raise ValueError("ORIGINAL_R5_QUALIFICATION_CUSTODY_OR_54_NODES_CHANGED")
    return result


def build_qualification_reader_recovery(original, *, original_qualification_ref,
                                        recovered_node, reader_projection_audit,
                                        recovery_producer_ref):
    """Pure assembly after one caller-owned zero-value final-node qualification."""
    import copy
    if (original.get("schema") != "B_R5_FINITE_EVENT_RISK_QUALIFICATION_V1"
            or original.get("research_id") != runtime.ID
            or "engineering_recovery" in original
            or len(original.get("nodes", ())) != 55
            or any(type(original.get(k)) is not int or original[k] != 0
                   for k in ("numeric_reads", "new_fit_units", "account_attempts",
                             "outcome_reads", "test2026_rows_read"))
            or original.get("strict_PIT_promotion_eligible") is not False):
        raise ValueError("ORIGINAL_ZERO_VALUE_55_NODE_QUALIFICATION_REQUIRED")
    failed = original["nodes"][-1]
    identity = ("node_id", "event_id", "recipe_id", "dependency", "families")
    if (failed.get("status") != "BLOCKED_METADATA"
            or failed.get("block_reason") != "PRE2026_READER_CUTOFF_REQUIRED"
            or any(failed.get(k) != recovered_node.get(k) for k in identity)
            or recovered_node.get("status") not in {
                "QUALIFIED_METADATA_ONLY_NUMERIC_UNKNOWN", "BLOCKED_METADATA"}):
        raise ValueError("ONLY_ORIGINAL_FINAL_READER_BLOCK_RECOVERABLE")
    result = copy.deepcopy(original)
    result["nodes"][-1] = copy.deepcopy(recovered_node)
    result["reader_projection_audit"].extend(copy.deepcopy(reader_projection_audit))
    result["engineering_recovery"] = dict(
        original_qualification_ref=copy.deepcopy(original_qualification_ref),
        retained_nodes_sha256=content_hash(original["nodes"][:-1]),
        original_failed_node=copy.deepcopy(failed),
        recovered_node_id=recovered_node["node_id"],
        recovery_producer_ref=copy.deepcopy(recovery_producer_ref),
        engineering_only=True, numeric_reads=0)
    if content_hash(result["nodes"][:-1]) != content_hash(original["nodes"][:-1]):
        raise ValueError("ORIGINAL_54_METADATA_NODES_CHANGED")
    return result


def validate_event(event, days):
    day = pd.Timestamp(event["decision_date"])
    i = pd.DatetimeIndex(days).get_indexer([day])[0]
    if i <= 0 or day >= old.BOUNDARY:
        raise ValueError("EXACT_PRE2026_CURRENT_EVENT_SESSION_REQUIRED")
    asof, cutoff = _clock(day), _clock(days[i-1])
    if (pd.Timestamp(event["decision_asof"]) != asof
            or pd.Timestamp(event["fit_history_cutoff"]) != cutoff
            or pd.Timestamp(event["current_identity_available_at"]) != asof):
        raise ValueError("CURRENT_CLOSE_AND_PRIOR_HISTORY_CLOCKS_MISMATCH")
    assets = tuple(event["requested_assets"])
    if assets != tuple(sorted(set(assets))) or not assets:
        raise ValueError("FULL_ORDERED_EVENT_DOMAIN_REQUIRED")
    for key in ("asset_uids", "asset_epochs", "segment_starts"):
        if (set(event[key]) != set(assets)
                or any(not discovery.known(v) for v in event[key].values())):
            raise ValueError("KNOWN_COMPLETE_CURRENT_IDENTITY_REQUIRED")
    if len(set(event["asset_uids"].values())) != len(assets):
        raise ValueError("NONUNIQUE_CURRENT_UID")
    support = event["history_support"]
    if (support.get("current_identity_blockers") or support.get("source_metadata_blockers")
            or support.get("parent_origin_count") != 252
            or support.get("qqq_h5_endpoint_key_support") is not True):
        raise ValueError("EVENT_METADATA_SOURCE_OR_PARENT_SUPPORT_BLOCKED")
    signature = event["complete_structural_signature"]
    if (content_hash(signature) != event["structural_signature_sha256"]
            or signature["ordered_assets"] != list(assets)
            or signature["asset_uids"] != event["asset_uids"]
            or signature["asset_epochs"] != event["asset_epochs"]):
        raise ValueError("EVENT_STRUCTURAL_METADATA_MUTATION")
    return asof, cutoff, assets


def source_support_identity(event, dependency, source_pins):
    if dependency not in {"PRIMARY", "QQQ", "FF48"}:
        raise ValueError("EXACT_FAMILY_LOCAL_DEPENDENCY_REQUIRED")
    return dict(dependency=dependency,
        dependency_local_event_id=event["dependency_local_event_ids"][dependency],
        dependency_local_signature_sha256=event["dependency_local_signature_sha256"][dependency],
        source_pins=dict(source_pins))


def current_pool_binding(features, raw, event, days):
    """Validate actual current metadata, retain frozen contiguous suffix witness.

    A bounded history prefix need not rediscover a segment starting years earlier.
    The immutable discovery proof owns that earlier start; all projected rows here
    are rebound to it and current UID, and original assembler independently checks
    every historical session/maturity. Today's identity is never inferred at p.
    """
    asof, cutoff, assets = validate_event(event, days)
    day = asof.tz_convert("America/New_York").tz_localize(None).normalize()
    features = features.copy()
    features["signal_date"] = pd.to_datetime(features.signal_date)
    if features.signal_date.gt(day).any():
        raise ValueError("FUTURE_CURRENT_IDENTITY_ROWS_FORBIDDEN")
    if not pd.to_datetime(raw.trade_date).eq(day).all():
        raise ValueError("CURRENT_RAW_KEY_DATE_REQUIRED")
    current = features.loc[features.signal_date.eq(day)]
    accepted = (current.feature_available.eq(True) & current.all_features_finite.eq(True)
                & current.feature_source.isin(old.FEATURE_TAGS))
    actual = tuple(sorted(set(current.loc[accepted, "ticker"]).intersection(raw.ticker)))
    if actual != assets:
        raise ValueError("FROZEN_CURRENT_REQUESTED_POOL_CHANGED")
    for asset in assets:
        uids = current.loc[current.ticker.eq(asset), "security_id"]
        if len(uids) != 1 or uids.iloc[0] != event["asset_uids"][asset]:
            raise ValueError("CURRENT_UID_UNKNOWN_DUPLICATE_OR_CHANGED")
    history = features.loc[features.ticker.isin(assets), ["ticker", "signal_date", "security_id"]].copy()
    if history.duplicated(["ticker", "signal_date"]).any():
        raise ValueError("AMBIGUOUS_REQUIRED_IDENTITY_HISTORY")
    history["available_at"] = history.signal_date.map(_clock)
    history["identity_epoch"] = [event["asset_epochs"][a]
        if d >= pd.Timestamp(event["segment_starts"][a]) and uid == event["asset_uids"][a]
        else "PRIOR_OBSERVED_UID_EPOCH"
        for a, d, uid in history[["ticker", "signal_date", "security_id"]].itertuples(index=False, name=None)]
    return dict(assets=assets, asset_uids=dict(event["asset_uids"]),
        asset_epochs=dict(event["asset_epochs"]), segment_starts=dict(event["segment_starts"]),
        blocked_assets={}, history=history), asof, cutoff


@dataclass(frozen=True)
class EventContext:
    inputs: object
    support_metadata: pd.DataFrame
    current_identity_proof: dict
    original_support_declarations: dict
    pool: dict


def assemble_event_context(*, labels, base_uids, features, raw, qqq,
                           source, science, days, event, dependency,
                           source_pins, industry_mapping=None, industry_receipt=None,
                           numeric=False, fast_metadata=True):
    """Pure transport over the original assembler; cold assets get zero rows."""
    pool, asof, cutoff = current_pool_binding(features, raw, event, days)
    for frame in (labels, base_uids, features, raw):
        if not numeric and old.FORBIDDEN.intersection(frame.columns):
            raise ValueError("METADATA_PHASE_NUMERIC_FIELD_FORBIDDEN")
    if not numeric and old.FORBIDDEN.intersection(qqq.columns):
        raise ValueError("METADATA_PHASE_QQQ_VALUE_FORBIDDEN")
    metadata = labels.loc[:, list(old.LABEL_META)].copy()
    bound = labels.merge(base_uids, on=["ticker", "signal_date"], how="left", validate="one_to_one")
    bound = bound.merge(pool["history"][["ticker", "signal_date", "identity_epoch"]],
                        on=["ticker", "signal_date"], how="left", validate="many_to_one")
    if not numeric:
        bound["y_open5"] = np.nan  # Unavailable marker, never a fabricated observation.
        if fast_metadata:
            bound = _MetadataFrame(bound)
    epoch = "R5_CURRENT_POOL_OBSERVED_UIDS:" + content_hash(pool["asset_epochs"])
    primary = old._receipt(source, science, cutoff, epoch)
    benchmark = old._receipt(source, science, cutoff, "EXISTING_QQQ_QFQ_OPEN_PROXY", benchmark=True)
    assembly = assemble_risk_inputs(bound, days, assets=pool["assets"],
        asset_uids=pool["asset_uids"], asset_epochs=pool["asset_epochs"], identity_epoch=epoch,
        source_receipt=primary, cutoff=cutoff, identity_history=pool["history"],
        qqq_opens=qqq if numeric else None, qqq_receipt=benchmark if numeric else None,
        industry_mapping=industry_mapping, industry_receipt=industry_receipt)
    inputs = assembly.risk_input
    if not numeric:
        inputs = prior.qqq_metadata_only(inputs, qqq, source, science, days, cutoff)
    keys = prior.source_support_keys(inputs, metadata, base_uids, pool)
    origins = pd.DatetimeIndex(inputs.observations.origin_at.unique()).sort_values()[-252:]
    exact = keys.loc[keys.origin_at.isin(origins)]
    counts = exact.loc[exact.qualified].groupby("asset").size()
    actual_counts = {a: int(counts.get(a, 0)) for a in pool["assets"]}
    frozen = event["history_support"]
    if (actual_counts != frozen["nominal_n"] or
            [v.tz_convert("America/New_York").date().isoformat() for v in origins] != frozen["parent_origins"]):
        raise ValueError("FROZEN_EVENT_HISTORY_SUPPORT_COUNTS_OR_ORIGINS_CHANGED")
    local = source_support_identity(event, dependency, source_pins)
    proof = dict(assets=list(pool["assets"]), asset_uids=pool["asset_uids"],
        asset_epochs=pool["asset_epochs"], security_coordinate=primary.return_coordinate,
        source_support_identity=local, source_qualified=True, maturity_qualified=True,
        current_identity_asof=asof.isoformat(), history_cutoff=cutoff.isoformat(),
        source_qualification_semantic="PINNED_FROZEN_HISTORY_MECHANISM_ONLY_NOT_STRICT_PIT",
        strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False,
        no_cross_identity_stitching=True, observations_created=0)
    declaration = dict(assembly.support_declarations)
    declaration["R5_current_identity_independent_of_prior_identity_inference"] = True
    declaration["original_prior_identity_support_failures_preserved"] = {
        a: ok for a, ok in declaration["inference_support"].items() if not ok}
    return EventContext(inputs, keys, proof, declaration, pool)


class EventInputLoader:
    def __init__(self, source, science, *, reader=None, numeric_authorised=False):
        self.reader = reader if reader is not None else old.ProjectedReader(source, phase="fit" if numeric_authorised else "support")
        self.source, self.science, self.numeric_authorised = source, science, numeric_authorised
        self.days, _ = _calendar(self.reader.read("calendar", ("trade_date",), date_field="trade_date").trade_date)

    def load(self, event, *, dependency="PRIMARY", family_dependencies=None, numeric=False, fast_metadata=True):
        if numeric and not self.numeric_authorised:
            raise ValueError("R5_PRE_NUMERIC_ACTIVATION_REQUIRED")
        asof, cutoff, assets = validate_event(event, self.days)
        day = asof.tz_convert("America/New_York").tz_localize(None).normalize()
        prior_day = cutoff.tz_convert("America/New_York").tz_localize(None).normalize()
        j = self.days.get_loc(prior_day)
        start = self.days[max(0, j-306)]
        features = self.reader.read("prediction_features", old.FEATURE_META,
            date_field="signal_date", start=start, stop=day, tickers=assets)
        # Full current-day predicate is checked, including newly eligible assets.
        today = self.reader.read("prediction_features", old.FEATURE_META, date_field="signal_date", day=day)
        features = pd.concat([features.loc[pd.to_datetime(features.signal_date).lt(day)], today], ignore_index=True)
        raw = self.reader.read("raw_open_close", ("ticker", "trade_date", "code"), date_field="trade_date", day=day)
        labels = self.reader.read("extended_shareholder_y5", old.LABEL_META + (("y_open5",) if numeric else ()),
            date_field="signal_date", start=start, stop=prior_day, tickers=assets, mature_before=prior_day)
        base = self.reader.read("shareholder_y5", ("ticker", "signal_date", "security_id"),
            date_field="signal_date", start=start, stop=prior_day, tickers=assets)
        qqq = self.reader.read("qqq_qfq_years", ("ticker", "trade_date") + (("open",) if numeric else ()),
            date_field="trade_date", start=self.days[max(0,j-360)], stop=prior_day, tickers=("QQQ",))
        pool = dict(assets=assets, asset_uids=event["asset_uids"])
        epoch = "R5_CURRENT_POOL_OBSERVED_UIDS:" + content_hash(event["asset_epochs"])
        industry, industry_receipt, _ = old.asof_ff48(self.reader, self.source, self.science, pool, cutoff, epoch)
        pins = {"primary": self.source["sources"]["extended_shareholder_y5"]["sha256"],
            "identity": self.source["sources"]["prediction_features"]["sha256"],
            "coordinate": self.source["sources"]["uid_intervals"]["sha256"],
            "scientific_contract": self.science["scientific_contract_sha256"]}
        # Every full-domain descendant uses the independently typed HP/QQQ prior.
        pins["QQQ"] = content_hash([p["sha256"] for p in self.source["sources"]["qqq_qfq_years"]])
        if dependency == "FF48":
            pins["FF48"] = self.source["sources"]["ff48_surface"]["sha256"]
        context = assemble_event_context(labels=labels, base_uids=base, features=features, raw=raw,
            qqq=qqq, source=self.source, science=self.science, days=self.days, event=event,
            dependency=dependency, source_pins=pins, industry_mapping=industry,
            industry_receipt=industry_receipt, numeric=numeric, fast_metadata=fast_metadata)
        if family_dependencies:
            families = {}
            for family, local_dependency in family_dependencies.items():
                if local_dependency == "FF48":
                    if family != "FF48_HIERARCHICAL":
                        raise ValueError("ONLY_FF48_FAMILY_USES_FF48_LOCAL_SUPPORT")
                    ff_pins = {**pins, "FF48":self.source["sources"]["ff48_surface"]["sha256"]}
                    ff_source = source_support_identity(event, "FF48", ff_pins)
                    ff_source["industry_source"] = context.inputs.industry_receipt.cache_identity()
                    families[family] = ff_source
                elif local_dependency != "PRIMARY":
                    raise ValueError("EXACT_FROZEN_FAMILY_DEPENDENCY_REQUIRED")
            context = replace(context, current_identity_proof={**context.current_identity_proof,
                "family_source_support_identity":families})
        return context


def effective_family_current(current, family):
    local = current.get("family_source_support_identity",{}).get(family)
    return current if local is None else {**current,"source_support_identity":local}


def family_source_qualification(context, families):
    result = {}
    if "FF48_HIERARCHICAL" in families:
        cohort = [a for a in context.inputs.assets if int(context.current_identity_proof.get("nominal_n",{}).get(a,0))>=30]
        if not cohort:
            # Source counts are obtained from exact typed legal/source-qualified keys.
            origins = pd.DatetimeIndex(context.inputs.observations.origin_at.unique()).sort_values()[-252:]
            keys = context.support_metadata
            counts = keys.loc[keys.origin_at.isin(origins) & keys.qualified].groupby("asset").size()
            cohort = [a for a in context.inputs.assets if int(counts.get(a,0))>=30]
        mapping = context.inputs.industry_mapping
        present = set() if mapping is None else set(mapping.asset)
        missing = sorted(set(cohort)-present)
        result["FF48_HIERARCHICAL"] = dict(status="QUALIFIED_METADATA_SOURCE_ONLY" if cohort and not missing else "BLOCKED_FAMILY_SOURCE_METADATA",
            native_minimum_n=30, native_cohort=cohort, missing_qualified_FF48_assets=missing,
            industry_source=None if context.inputs.industry_receipt is None else context.inputs.industry_receipt.cache_identity(),
            strict_PIT_promotion_eligible=False, numeric_finiteness="UNKNOWN_NOT_READ")
    return result


def code_pins():
    paths = [Path(__file__), Path(prior.__file__), Path(discovery.__file__),
        old.REPO/"scripts/research/a2/data/shared_risk_inputs_r3.py",
        old.REPO/"scripts/research/a2/risk/joint_event_risk_estimators_r5.py",
        old.REPO/"scripts/research/a2/risk/short_history_risk_r4.py",
        old.REPO/"scripts/research/a2/risk/shared_risk_engine_r2.py",
        old.REPO/"scripts/research/a2/risk/shared_risk_extensions_r2.py",
        old.REPO/"scripts/research/a2/risk/joint_risk_estimators.py",
        old.REPO/"scripts/research/a2/inference/joint_event_policy_r5.py",
        old.REPO/"scripts/common/storage_paths.py"]
    return [ref(path) for path in paths]


def compact_qualification(proof):
    result = {k:v for k,v in proof.items() if k != "qualified_keys"}
    result["qualified_keys_sha256"] = content_hash(proof.get("qualified_keys", []))
    return result


def bind_policy_state(state, binding, current):
    current = effective_family_current(current,binding["family"])
    expected = {"parent_risk", "method", "family", "representation", "recipe_sha256", "producer_sha256", "availability"}
    if set(binding) != expected or binding["method"] != state.method:
        raise ValueError("EXACT_FROZEN_EVENT_METHOD_BINDING_REQUIRED")
    if state.covariance is None:
        return state
    if state.status not in {"PASS_FROZEN_HISTORY_MECHANISM", "PASS_SYNTHETIC"}:
        raise ValueError("QUALIFIED_EVENT_STATE_STATUS_REQUIRED")
    proof = dict(parent_risk=binding["parent_risk"], representation=binding["representation"],
        recipe_sha256=binding["recipe_sha256"], model_producer_sha256=binding["producer_sha256"],
        structural_identity=structural_identity(assets=tuple(current["assets"]), uids=current["asset_uids"],
            epochs=current["asset_epochs"], security_coordinate=current["security_coordinate"],
            source_support_identity=current["source_support_identity"]),
        source_support_identity_sha256=content_hash(current["source_support_identity"]),
        asset_uid_epoch_sha256=content_hash(dict(uids=current["asset_uids"], epochs=current["asset_epochs"])))
    if binding["availability"] != "READY" or state.notes["estimator_lineage"].get("family") != binding["family"]:
        raise ValueError("RELATED_QUALIFIED_FAMILY_REQUIRED")
    for a in current["assets"]:
        if (state.coverage.get(a,{}).get("uid") != current["asset_uids"][a]
                or state.coverage.get(a,{}).get("identity_epoch") != current["asset_epochs"][a]):
            raise ValueError("COMPLETE_STATE_CURRENT_UID_EPOCH_REQUIRED")
    lineage = state.notes["estimator_lineage"]
    if any(lineage[k] != proof[k] for k in ("recipe_sha256", "structural_identity", "source_support_identity_sha256", "asset_uid_epoch_sha256")):
        raise ValueError("ESTIMATOR_AND_POLICY_BINDING_LINEAGE_MISMATCH")
    return replace(state, notes={**state.notes, "event_policy_binding":proof})



def load_plan(run, plan_path, *, expected_sha=None):
    runtime.guard(run)
    path = Path(plan_path)
    if not path.resolve().is_relative_to(Path(run).resolve()):
        raise ValueError("R5_RUN_OWNED_FINITE_PLAN_REQUIRED")
    assert_safe_output_path(path, kind="backtest", paths=resolve(old.REPO))
    if expected_sha:
        old._pin(path, expected_sha, "R5_FINITE_PLAN")
    plan = old.read_json(path)
    if (plan.get("schema") != "B_R5_FINITE_EVENT_RISK_PLAN_V1"
            or plan.get("research_id") != runtime.ID
            or type(plan.get("maximum_new_fit_units")) is not int
            or not 0 <= plan["maximum_new_fit_units"] <= runtime.MAX_NEW):
        raise ValueError("EXACT_R5_SOURCE_ONLY_FINITE_PLAN_REQUIRED")
    old._pin(Path(run)/"SOURCE_AUTHORITY.json", plan["source_authority_ref"]["sha256"], "R5_PLAN_SOURCE")
    old._pin(plan["model_producer_ref"]["path"], plan["model_producer_ref"]["sha256"], "R5_PURE_PRODUCER")
    support = read_event_support(run, expected_sha256=plan["support_ref"]["sha256"])
    if Path(plan["support_ref"]["path"]).resolve() != (Path(run)/SUPPORT).resolve():
        raise ValueError("EXACT_PLAN_EVENT_SUPPORT_REF_REQUIRED")
    events = {e["event_id"]:e for e in support["events"]}
    if len(events) != len(support["events"]):
        raise ValueError("DUPLICATE_FROZEN_EVENT_ID")
    from scripts.research.a2.risk.joint_event_risk_estimators_r5 import EventRiskEstimator
    estimators = {k:EventRiskEstimator(recipe) for k,recipe in plan["estimator_recipes"].items()}
    representatives = {}
    for event in support["events"]:
        representatives.setdefault(event["dependency_local_event_ids"]["PRIMARY"],event)
    ordered = list(representatives.values())
    anchor_ids = {next(e["event_id"] for e in ordered if pd.Timestamp(e["decision_date"]).year==year) for year in (2023,2025)}
    if (len(ordered)!=55 or [n["event_id"] for n in plan["nodes"]] != [e["event_id"] for e in ordered]):
        raise ValueError("EXACT_55_PRIMARY_EVENT_CHAIN_REQUIRED")
    seen, bound, bindings = set(), 0, plan["method_bindings"]
    from scripts.research.a2.inference.joint_event_policy_r5 import EventMethodBinding
    for b in bindings:
        EventMethodBinding(**b).validate()
        if b["producer_sha256"] != plan["model_producer_ref"]["sha256"]:
            raise ValueError("BINDING_PURE_PRODUCER_SHA_MISMATCH")
    for node in plan["nodes"]:
        if node["event_id"] not in events or node["recipe_id"] not in estimators:
            raise ValueError("PLAN_EVENT_OR_RECIPE_NOT_FROZEN")
        event, estimator = events[node["event_id"]], estimators[node["recipe_id"]]
        source_support_identity(event,node["dependency"],{"plan":old.sha(path)})
        families = tuple(node["families"])
        if not families or len(set(families)) != len(families):
            raise ValueError("FINITE_UNIQUE_FAMILY_NODE_REQUIRED")
        if type(node.get("maximum_learned_units")) is not int or node["maximum_learned_units"] < 0:
            raise ValueError("KNOWN_NODE_DEPENDENCY_BOUND_REQUIRED")
        if node.get("family_dependencies") != {f:("FF48" if f=="FF48_HIERARCHICAL" else "PRIMARY") for f in families}:
            raise ValueError("EXACT_COMPLETE_FAMILY_LOCAL_DEPENDENCY_MAP_REQUIRED")
        if node["dependency"] != "PRIMARY" or not CONTINUOUS.issubset(families):
            raise ValueError("CONTINUOUS_SEVEN_FAMILY_PRIMARY_CHAIN_REQUIRED")
        all_families = set(estimator.recipe["method_ids"])
        anchor = node["event_id"] in anchor_ids
        if (set(families) != (all_families if anchor else CONTINUOUS)
                or node["maximum_learned_units"] != (51 if anchor else 18)):
            raise ValueError("EXACT_TWO_BROAD_ANCHORS_AND_NO_EXTRA_DATE_SEARCH_REQUIRED")
        bound += node["maximum_learned_units"]
        for family in families:
            identity = (node["event_id"],node["recipe_id"],family)
            if identity in seen:
                raise ValueError("DUPLICATE_FROZEN_FAMILY_ATTEMPT")
            seen.add(identity)
            matches=[b for b in bindings if b["family"]==family and b["recipe_sha256"]==estimator.recipe_sha256]
            if len(matches)!=1 or matches[0]["method"]!=estimator.recipe["method_ids"].get(family):
                raise ValueError("EXACT_FAMILY_RECIPE_METHOD_BINDING_REQUIRED")
    if bound > plan["maximum_new_fit_units"]:
        raise ValueError("FINITE_DEPENDENCY_DAG_EXCEEDS_FROZEN_CAP")
    authority = old.read_json(Path(run)/"SOURCE_AUTHORITY.json")
    source_ref = authority["source_inputs_ref"]
    old._safe_source(source_ref["path"]);old._pin(source_ref["path"],source_ref["sha256"],"R5_SOURCE_INPUTS")
    source = old.read_json(source_ref["path"])
    science = dict(scientific_contract_identity=runtime.ID,
        scientific_contract_sha256=old.sha(path), actual_snapshot_timestamp=authority["actual_snapshot_timestamp"])
    return plan, support, events, estimators, source, science


def node_id(node):
    return content_hash({k:node[k] for k in ("event_id","dependency","recipe_id","families")})


def prepare(run, *, plan_path):
    """Independent source-only qualification; never activates numeric reading."""
    if not plan_path:
        raise ValueError("EXPLICIT_SOURCE_ONLY_PLAN_REQUIRED")
    plan,support,events,estimators,source,science=load_plan(run,plan_path)
    with runtime.stage_writer(run,"risk"):
        loader=EventInputLoader(source,science,numeric_authorised=False)
        nodes=[]
        for node in plan["nodes"]:
            record=dict(node_id=node_id(node),event_id=node["event_id"],recipe_id=node["recipe_id"],
                dependency=node["dependency"],families=node["families"])
            try:
                ctx=loader.load(events[node["event_id"]],dependency=node["dependency"],family_dependencies=node["family_dependencies"],numeric=False)
                proof=estimators[node["recipe_id"]].qualify(ctx.inputs,
                    as_of=pd.Timestamp(events[node["event_id"]]["decision_asof"]),
                    support_metadata=ctx.support_metadata,current_identity_proof=ctx.current_identity_proof)
                record.update(status="QUALIFIED_METADATA_ONLY_NUMERIC_UNKNOWN",
                    metadata_qualification=compact_qualification(proof),source_keys_sha256=content_hash(ctx.support_metadata),
                    current_identity_proof_sha256=content_hash(ctx.current_identity_proof),
                    family_source_qualification=family_source_qualification(ctx,node["families"]),
                    original_prior_identity_failures=ctx.original_support_declarations[
                        "original_prior_identity_support_failures_preserved"])
            except (ValueError,TypeError,KeyError) as error:
                record.update(status="BLOCKED_METADATA",block_reason=str(error))
            nodes.append(record)
            print(json.dumps(dict(phase="prepare",nodes_checked=len(nodes),status=record["status"],new_fit_units=0)),flush=True)
        result=dict(schema="B_R5_FINITE_EVENT_RISK_QUALIFICATION_V1",research_id=runtime.ID,
            plan_ref=ref(plan_path),support_ref=plan["support_ref"],source_authority_ref=plan["source_authority_ref"],
            producer_ref=ref(__file__),model_producer_ref=plan["model_producer_ref"],nodes=nodes,
            reader_projection_audit=loader.reader.audit,numeric_reads=0,new_fit_units=0,account_attempts=0,
            outcome_reads=0,test2026_rows_read=0,strict_PIT_promotion_eligible=False)
        old.write(run,QUALIFICATION,result,immutable=True)
        return dict(status="R5_RISK_SOURCE_QUALIFICATION_COMPLETE",nodes=len(nodes),
            metadata_qualified=sum(n["status"].startswith("QUALIFIED") for n in nodes),qualification_ref=ref(Path(run)/QUALIFICATION),
            new_fit_units=0,numeric_reads=0)


def _save_cache(run,cache,key):
    path=Path(run)/"work"/("EVENT_RISK_CACHE_"+key+".joblib")
    payload=dict(schema="B_R5_EVENT_SHARED_CACHE_V1",context=cache.context,
        records=cache._records,budget_snapshot=cache.budget.snapshot())
    prior._atomic_joblib(payload,path)
    return ref(path)


def _restore_cache(reference,estimator,ctx,asof,ledger,node):
    old._pin(reference["path"],reference["sha256"],"R5_RECOVERY_SHARED_CACHE")
    snapshot=joblib.load(reference["path"])
    counts=snapshot["budget_snapshot"]
    budget=StateBudget(limit=node["maximum_learned_units"],reserve_callback=ledger.reserve)
    cache=estimator.make_cache(ctx.inputs,as_of=asof,budget=budget)
    if snapshot.get("schema")!="B_R5_EVENT_SHARED_CACHE_V1" or snapshot["context"]!=cache.context:
        raise ValueError("R5_RECOVERY_CONTEXT_CHANGED_NO_REFIT")
    budget.counts=counts["counts"];budget.events=counts["events"]
    budget._keys={v["key"] for v in budget.events};cache._records=snapshot["records"]
    return cache


def fit(run, *, expected_freeze_sha):
    """No value projection can precede exact whole-freeze and metadata checks."""
    run=runtime.guard(run,numeric=True,expected_freeze_sha256=expected_freeze_sha)
    freeze=old.read_json(Path(run)/FREEZE)
    actual_pins = {Path(r["path"]).resolve():r["sha256"] for r in freeze["source_code_pins"]}
    if any(actual_pins.get(Path(r["path"]).resolve()) != r["sha256"] for r in code_pins()):
        raise ValueError("COMPLETE_EXACT_R5_RISK_EXECUTION_CLOSURE_REQUIRED")
    plan_ref,qual_ref=freeze["plan_ref"],freeze["qualification_ref"]
    plan,support,events,estimators,source,science=load_plan(run,plan_ref["path"],expected_sha=plan_ref["sha256"])
    old._pin(qual_ref["path"],qual_ref["sha256"],"R5_FROZEN_METADATA_QUALIFICATION")
    qualification=read_event_qualification(run,qualification_ref=qual_ref)
    if qualification["plan_ref"]!=plan_ref or qualification["model_producer_ref"]!=plan["model_producer_ref"]:
        raise ValueError("FROZEN_R5_QUALIFICATION_PLAN_OR_PRODUCER_MISMATCH")
    expected={n["node_id"]:n for n in qualification["nodes"]}
    if len(expected)!=len(plan["nodes"]):
        raise ValueError("EXACT_FINITE_QUALIFICATION_NODE_ROSTER_REQUIRED")
    with runtime.stage_writer(run,"risk"):
        ledger=runtime.R5FitLedger(run,expected_freeze_sha256=expected_freeze_sha)
        loader=EventInputLoader(source,science,numeric_authorised=True)
        for node in plan["nodes"]:
            key=node_id(node);event=events[node["event_id"]];estimator=estimators[node["recipe_id"]]
            prior_records=[r for r in ledger.status["records"] if r.get("node_id")==key]
            done={r["family"] for r in prior_records}
            for record in prior_records:
                if record.get("artifact_ref"):
                    old._pin(record["artifact_ref"]["path"],record["artifact_ref"]["sha256"],"R5_RETAINED_MODEL")
            pending=[f for f in node["families"] if f not in done]
            if not pending: continue
            ctx=cache=proof=None;error=None
            try:
                if expected[key]["status"]!="QUALIFIED_METADATA_ONLY_NUMERIC_UNKNOWN":
                    raise ValueError(expected[key].get("block_reason","FROZEN_METADATA_BLOCK"))
                meta=loader.load(event,dependency=node["dependency"],family_dependencies=node["family_dependencies"],numeric=False)
                asof=pd.Timestamp(event["decision_asof"])
                proof=estimator.qualify(meta.inputs,as_of=asof,support_metadata=meta.support_metadata,
                    current_identity_proof=meta.current_identity_proof)
                if (compact_qualification(proof)!=expected[key]["metadata_qualification"]
                        or content_hash(meta.support_metadata)!=expected[key]["source_keys_sha256"]
                        or content_hash(meta.current_identity_proof)!=expected[key]["current_identity_proof_sha256"]):
                    raise ValueError("FROZEN_R5_METADATA_SOURCE_CONTEXT_CHANGED")
                ctx=loader.load(event,dependency=node["dependency"],family_dependencies=node["family_dependencies"],numeric=True)
                if estimator.qualify(ctx.inputs,as_of=asof,support_metadata=ctx.support_metadata,
                        current_identity_proof=ctx.current_identity_proof)!=proof:
                    raise ValueError("NUMERIC_PROJECTION_CHANGED_METADATA_QUALIFICATION")
                budget=StateBudget(limit=node["maximum_learned_units"],reserve_callback=ledger.reserve)
                cache=estimator.make_cache(ctx.inputs,as_of=asof,budget=budget)
                if prior_records:
                    saved=ledger.status.get("shared_cache_artifacts",{}).get(key)
                    if not saved: raise ValueError("PARTIAL_NODE_CACHE_MISSING_NO_SCIENTIFIC_REFIT")
                    cache=_restore_cache(saved,estimator,ctx,asof,ledger,node)
            except (ValueError,TypeError,KeyError,OSError) as failure:
                error=str(failure)
            for family in pending:
                family_dependency = node["family_dependencies"][family]
                record=dict(node_id=key,event_id=node["event_id"],dependency=family_dependency,
                    dependency_local_event_id=event["dependency_local_event_ids"][family_dependency],
                    recipe_id=node["recipe_id"],family=family,as_of=event["decision_asof"],
                    cutoff=event["fit_history_cutoff"],assets=event["requested_assets"],
                    asset_uids=event["asset_uids"],asset_epochs=event["asset_epochs"],learned_states=0)
                family_source = expected[key].get("family_source_qualification",{}).get(family,{})
                if error:
                    record.update(status="BLOCKED_INPUT",block_reason=error)
                elif family_source.get("status")=="BLOCKED_FAMILY_SOURCE_METADATA":
                    record.update(status="BLOCKED_FAMILY_METADATA",block_reason="MISSING_MIN30_COHORT_ASOF_FF48_SOURCE",family_source_qualification=family_source)
                else:
                    before=cache.budget.learned_total
                    try:
                        with threadpool_limits(limits=2):
                            state=estimator.fit_family(family,ctx.inputs,as_of=asof,
                                support_metadata=ctx.support_metadata,current_identity_proof=ctx.current_identity_proof,
                                cache=cache,expected_qualification=proof,expected_recipe_sha256=estimator.recipe_sha256)
                        binding=next(b for b in plan["method_bindings"] if b["family"]==family and
                            b["recipe_sha256"]==estimator.recipe_sha256)
                        state=bind_policy_state(state,binding,ctx.current_identity_proof)
                        ledger.sync(cache.budget.events)
                        record.update(status=state.status,method=state.method,risk_state_id=state.risk_state_id,
                            artifact_ref=prior._persist_state(run,state),fit_dependency_ids=list(state.fit_dependency_ids),
                            block_reason=state.notes.get("block_reason"),learned_states=cache.budget.learned_total-before,
                            finite_check=state.covariance is not None,covariance_sha256=state.notes.get("covariance_sha256"),
                            source_receipt=state.source_receipt,event_policy_binding=state.notes.get("event_policy_binding"),
                            source_support_identity=effective_family_current(ctx.current_identity_proof,family)["source_support_identity"])
                    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as failure:
                        ledger.sync(cache.budget.events)
                        record.update(status="FIT_FAILURE",block_reason=str(failure),learned_states=cache.budget.learned_total-before)
                        ledger.status["failures"].append(dict(node_id=key,family=family,error=str(failure)))
                if cache is not None:
                    ledger.status.setdefault("shared_cache_artifacts",{})[key]=_save_cache(run,cache,key)
                ledger.status["records"].append(record);ledger.checkpoint()
                print(json.dumps(dict(phase="fit",family=family,event=event["decision_date"],status=record["status"],
                    new_fit_units=ledger.status["new_fit_units"])),flush=True)
            gc.collect()
        ledger.status["status"]="B_R5_FINITE_EVENT_RISK_QUEUE_COMPLETE";ledger.checkpoint()
        qualified=[r for r in ledger.status["records"] if r["status"]=="PASS_FROZEN_HISTORY_MECHANISM" and r.get("finite_check")]
        bank=dict(schema="B_R5_EVENT_RISK_BANK_V1",research_id=runtime.ID,plan_ref=plan_ref,
            qualification_ref=qual_ref,event_support_ref=plan["support_ref"],source_authority_ref=plan["source_authority_ref"],
            execution_producer_ref=ref(__file__),model_producer_ref=plan["model_producer_ref"],method_bindings=plan["method_bindings"],
            states=qualified,blocked_or_failed=[r for r in ledger.status["records"] if r not in qualified],
            ledger_ref=ref(Path(run)/"work/FIT_STATUS.json"),new_fit_units=ledger.status["new_fit_units"],
            cumulative_fit_units=ledger.status["fit_attempts"],daily_metadata_support_ref=plan["support_ref"],
            future_next_event_lookup_allowed=False,strict_PIT_promotion_eligible=False,quote_qualified=False,
            certified_nav_qualified=False,account_attempts=0,test2026_rows_read=0)
        old.write(run,BANK,bank)
        return dict(status=ledger.status["status"],qualified_risk_states=len(qualified),attempted=len(ledger.status["records"]),
            new_fit_units=ledger.status["new_fit_units"],bank_ref=ref(Path(run)/BANK),account_attempts=0,test2026_rows_read=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", choices=("prepare", "fit"), required=True)
    parser.add_argument("--expected-freeze-sha")
    parser.add_argument("--plan", help="Pinned source-only finite plan; required by prepare")
    args = parser.parse_args()
    if args.phase == "fit":
        result = fit(args.run, expected_freeze_sha=args.expected_freeze_sha)
    else:
        result = prepare(args.run, plan_path=args.plan)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
