"""Original R5 reuse and an explicitly authorized continuous LW descendant.

The legacy consumer never fits; the descendant invokes the original-owner
backend only when no qualified whole state covers its actual required domain.
Original source metadata determines the full pool before opportunity selection.
Current-use identity is checked separately from original state/fit clocks.
Historical publication authority remains UNKNOWN and research-only.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import importlib.util
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.research.a2.inference import joint_event_risk_chain_r5 as chain
from scripts.research.a2.evaluation import joint_event_risk_execution_r5 as producer
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance

ORIGINAL_HELPER_REF = dict(
    path="D:/us-tech-quant-cache/V24/V24_B_FINAL_JOINT_POLICY_ACCOUNT_AND_COVERAGE_R1/source_audit/run_final_B_R5_policy_space.py",
    sha256="8789dbfd1245d2f44148d837f792fbf9db4914b14bac3125246d25acb99c35a3",
)
CODE_REFS = (
    dict(path="D:/us-tech-quant/scripts/research/a2/inference/joint_event_risk_chain_r5.py",
         sha256="58f6f272039f990abb050393cdfacbb952772970bd7968156fcd0c2c426050a7"),
    dict(path="D:/us-tech-quant/scripts/research/a2/evaluation/joint_event_risk_execution_r5.py",
         sha256="955fff74f7eff3bab56063a17a3d4f3ee749b26bbad4b2a1452ddfe3e65c0643"),
)


class ExistingRiskInputUnavailable(ValueError):
    def __init__(self, reason, **evidence):
        self.receipt = dict(status="BLOCKED_REQUIRED_ORIGINAL_RISK_INPUT", reason=reason, **evidence)
        super().__init__(reason)


@dataclass(frozen=True)
class ExistingRiskSlice:
    assets: tuple[str, ...]
    columns: np.ndarray
    covariance: np.ndarray
    pool_mask: np.ndarray
    covariance_psd_qualified: bool
    source_receipt: dict
    loads_count: int


def _load_original_components(interface):
    """Pin existing source and metadata before any original serialized load."""
    path = interface.pin(ORIGINAL_HELPER_REF)
    for reference in CODE_REFS:
        interface.pin(reference)
    spec = importlib.util.spec_from_file_location("_reused_original_r5_helpers", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    metadata = {name: interface.read(interface.pin(helper.REFS[name]))
                for name in ("plan", "support", "global", "source")}
    plan, support = metadata["plan"], metadata["support"]
    if (plan.get("research_id") != chain.RESEARCH_ID or support.get("research_id") != chain.RESEARCH_ID
            or support.get("decision_session_count") != chain.REQUIRED_DAILY_COUNT
            or len(metadata["global"]["states_and_retained_attempts"]) != 403):
        raise ValueError("EXACT_ORIGINAL_R5_PUBLICATION_DOMAIN_REQUIRED")
    lw = [r for r in metadata["global"]["states_and_retained_attempts"] if r["family"] == "LW"]
    if len(lw) != 55:
        raise ValueError("EXACT_55_ORIGINAL_LW_STATES_REQUIRED")
    reader = producer.old.ProjectedReader(metadata["source"], phase="support")
    calendar, _ = producer._calendar(reader.read("calendar", ("trade_date",), date_field="trade_date").trade_date)
    pool, proof = helper.current_pool_factory()
    return dict(plan=plan, support=support, publication=metadata["global"], reader=reader,
                calendar=calendar, state_loader=helper.OriginalStateLoader(interface),
                current_pool=pool, current_pool_proof=proof, refs=helper.REFS)


def _qualify_existing(*args):
    try:
        return chain._qualify_record(*args)
    except chain.ChainQualificationBlocked as exc:
        raise ExistingRiskInputUnavailable(str(exc)) from exc


def _vector(ctx, name, count, *, boolean=False):
    value = np.asarray(getattr(ctx, name))
    if value.shape == (1, count):
        value = value[0]
    if value.shape != (count,):
        raise ValueError("EXACT_MASTER_CONTEXT_SHAPE_REQUIRED:" + name)
    if boolean:
        if value.dtype != bool:
            raise ValueError("BOOLEAN_CONTEXT_MASK_REQUIRED:" + name)
    elif not np.isfinite(value).all() or np.any(value < 0):
        raise ValueError("FINITE_NONNEGATIVE_ACTUAL_HOLDINGS_REQUIRED:" + name)
    return value


PTO_INVESTMENT_EXCLUSION_TICKERS = ("INTC", "MKFG")


def frozen_investment_exclusion_tickers(freeze):
    """Admit only the explicitly frozen two-book investment exception."""
    if "investment_exclusion_tickers" not in freeze:
        return ()
    tickers = freeze["investment_exclusion_tickers"]
    profile = freeze.get("pto_account_profile", {})
    if (not isinstance(tickers, list) or tuple(tickers) != PTO_INVESTMENT_EXCLUSION_TICKERS
            or freeze.get("task_id") != "V24_B_FAST_TRACK_PAIR_COMPLETION_R1"
            or not isinstance(profile, dict)
            or profile.get("schema") != "B_PTO_MATCHED_SOURCE_ACCOUNT_PROFILE_V1"
            or profile.get("policies") != ["PTO_REUSE_ROBUST_COST", "RAW_A2_SOURCE_REUSE"]):
        raise ExistingRiskInputUnavailable("EXACT_FROZEN_PTO_INVESTMENT_EXCLUSIONS_REQUIRED")
    account = freeze.get("account_config", {})
    if (not isinstance(account, dict) or account.get("initial_holdings") != []
            or freeze.get("source_retry_replay_from_original_beginning") is not True):
        raise ExistingRiskInputUnavailable("INVESTMENT_EXCLUSIONS_REQUIRE_EMPTY_ORIGINAL_START")
    return PTO_INVESTMENT_EXCLUSION_TICKERS


def causal_held_domain(ctx, entry_pool_mask, *, excluded_tickers=()):
    """Separate original entry eligibility from actual held management support.

    This is domain transport only. It grants no identity, forecast or risk
    authority, and cannot change original reserved/operational/decision inputs.
    An outside-pool holding never regains permission to increase its position.
    """
    assets = tuple(map(str, ctx.tickers))
    if len(set(assets)) != len(assets):
        raise ValueError("UNIQUE_MASTER_ASSET_ORDER_REQUIRED")
    count = len(assets)
    pool = np.asarray(entry_pool_mask)
    if pool.shape != (count,) or pool.dtype != bool:
        raise ValueError("EXACT_BOOLEAN_ENTRY_POOL_REQUIRED")
    units = _vector(ctx, "current_units", count)
    weights = _vector(ctx, "current_weights", count)
    decision = _vector(ctx, "decision_mask", count, boolean=True)
    buy = _vector(ctx, "buy_allowed", count, boolean=True)
    held = (units > 0) | (weights > 0)
    if (not isinstance(excluded_tickers, tuple)
            or excluded_tickers not in ((), PTO_INVESTMENT_EXCLUSION_TICKERS)):
        raise ExistingRiskInputUnavailable("EXACT_FROZEN_PTO_INVESTMENT_EXCLUSIONS_REQUIRED")
    excluded = np.isin(np.asarray(assets), excluded_tickers)
    if np.any(excluded & ((units != 0) | (weights != 0))):
        raise HeldLineageUnavailable("EXCLUDED_INVESTMENT_ACTUAL_HOLDING_FORBIDDEN",
            assets=[assets[i] for i in np.flatnonzero(excluded & ((units != 0) | (weights != 0)))])
    original_eligible = decision & buy & pool
    eligible = original_eligible & ~excluded
    columns = np.flatnonzero(eligible | held)
    # Preserve an existing modeled held action; do not manufacture a lock by
    # intersecting its decision mask with the entry pool. Existing locks stay.
    management = decision & (pool | held) & ~excluded
    permitted_buy = buy & pool & ~excluded
    output = dict(assets=tuple(assets[i] for i in columns), columns=columns,
                  eligible_mask=eligible, held_mask=held,
                  decision_mask=management, buy_allowed=permitted_buy)
    if excluded_tickers:
        output.update(investment_exclusion_tickers=excluded_tickers,
                      original_eligible_mask=original_eligible, excluded_mask=excluded)
    for value in output.values():
        if isinstance(value, np.ndarray):
            value.flags.writeable = False
    return output


def audit_complete_original_lw_axes(records, required_assets, *, decision_as_of):
    """Necessary single-state axis test before any serialized/numeric load.

    A negative result is conclusive even with the most permissive age rule:
    every original state available by the decision is considered. A positive
    result is only an axis candidate; identity continuity, reuse expiry,
    original recipe/source, physical/typed commitments and full numeric/PSD
    guards still have to pass before use. No matrix is selected or combined.
    """
    required = tuple(required_assets)
    if (len(set(required)) != len(required)
            or any(not isinstance(a, str) or not a or a != a.strip() for a in required)):
        raise ValueError("EXACT_REQUIRED_ASSET_ORDER_REQUIRED")
    asof = pd.Timestamp(decision_as_of)
    if pd.isna(asof) or asof.tzinfo is None or asof >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("PRE2026_AWARE_DECISION_CLOCK_REQUIRED")
    rows, candidates, seen = [], [], set()
    for record in records:
        if record.get("family") != "LW":
            continue
        state_id = record.get("risk_state_id")
        if not isinstance(state_id, str) or not state_id or state_id in seen:
            raise ValueError("UNIQUE_ORIGINAL_LW_STATE_ID_REQUIRED")
        seen.add(state_id)
        assets = tuple(record["assets"])
        if len(set(assets)) != len(assets):
            raise ValueError("UNIQUE_ORIGINAL_LW_AXIS_REQUIRED")
        clocks = {name: pd.Timestamp(record.get(name))
                  for name in ("as_of", "cutoff", "state_available_at")}
        if any(pd.isna(c) or c.tzinfo is None for c in clocks.values()):
            raise ValueError("ORIGINAL_LW_AWARE_MECHANISM_CLOCKS_REQUIRED")
        if clocks["cutoff"] >= clocks["as_of"]:
            raise ValueError("ORIGINAL_LW_FIT_CUTOFF_MUST_PRECEDE_STATE")
        causal = max(clocks["as_of"], clocks["state_available_at"]) <= asof
        missing = [a for a in required if a not in assets]
        verified = record.get("publication_status") == "VERIFIED_MECHANISM_STATE"
        candidate = causal and verified and not missing
        reasons = ([] if causal else ["FUTURE_STATE_OR_MECHANISM_AVAILABILITY"])
        if not verified:
            reasons.append("ORIGINAL_STATE_NOT_VERIFIED")
        if missing:
            reasons.append("INCOMPLETE_REQUIRED_AXIS_AND_CROSS_COVARIANCE")
        rows.append(dict(risk_state_id=state_id, as_of=record["as_of"],
            state_available_at=record["state_available_at"], cutoff=record["cutoff"],
            original_asset_count=len(assets), causal=causal, axis_candidate=candidate,
            missing_required_assets=missing, exclusion_reasons=reasons,
            artifact_ref=record.get("artifact_ref"),
            typed_state_content_sha256=record.get("typed_state_content_sha256")))
        if candidate:
            candidates.append((clocks["as_of"], state_id))
    candidates.sort(key=lambda item: (-item[0].value, item[1]))
    return dict(schema="B_CAUSAL_WHOLE_ORIGINAL_LW_AXIS_AUDIT_R1",
        status=("COMPLETE_AXIS_CANDIDATE_REQUIRES_FURTHER_QUALIFICATION" if candidates
                else "BLOCKED_NO_COMPLETE_CAUSAL_ORIGINAL_LW_AXIS"),
        decision_as_of=asof.isoformat(), required_assets=list(required),
        original_lw_state_count=len(rows), causal_state_count=sum(r["causal"] for r in rows),
        axis_candidate_ids=[s for _, s in candidates], selected_state_id=None,
        state_use_authorized=False, age_filter="NONE_NECESSARY_CONDITION_RELAXATION_ONLY",
        historical_availability_authority="UNKNOWN_ORIGINAL_MECHANISM_ASSUMPTION_ONLY",
        numeric_payloads_read=0, new_risk_estimates=0, matrix_mixing=False,
        all_required_cross_covariance_must_exist_in_one_state=True,
        states=rows, strict_PIT=False, production_qualified=False,
        quote_qualified=False, certified_NAV=False)


class ExistingR5LWInputs:
    """Lazy source-pinned provider shared by both matched research policies."""
    def __init__(self, *, interface, market_dates, master_assets):
        self.interface = interface
        self.market_dates = pd.DatetimeIndex(market_dates)
        self.master_assets = tuple(map(str, master_assets))
        if (self.market_dates.tz is not None or self.market_dates.has_duplicates
                or not self.market_dates.is_monotonic_increasing
                or not self.market_dates.equals(self.market_dates.normalize())
                or self.market_dates.empty or self.market_dates[-1] >= pd.Timestamp("2026-01-01")
                or len(set(self.master_assets)) != len(self.master_assets)):
            raise ValueError("UNIQUE_PRE2026_MARKET_DOMAIN_REQUIRED")
        self._components = None
        self._last_domain = None
        self._domain_memo = OrderedDict()
        self._domain_memo_guard = None
        self._checked = OrderedDict()

    @property
    def loads_count(self):
        return 0 if self._components is None else self._components["state_loader"].loads

    def _initialize(self):
        if self._components is not None:
            return
        c = _load_original_components(self.interface)
        c["calendar"] = pd.DatetimeIndex(c["calendar"])
        c["daily"] = {pd.Timestamp(r["decision_date"]): r for r in c["support"]["daily_support_chain"]}
        if (len(c["daily"]) != len(c["support"]["daily_support_chain"])
                or tuple(c["daily"]) != tuple(self.market_dates)
                or len(c["daily"]) != c["support"]["decision_session_count"]
                or np.any(c["calendar"].get_indexer(self.market_dates) < 1)):
            raise ValueError("COMPLETE_ORIGINAL_DAILY_AND_PRIOR_SESSION_DOMAIN_REQUIRED")
        c["events"] = chain._event_indices(c["support"])
        c["nodes"] = {n["event_id"]: n for n in c["plan"]["nodes"]}
        matches = [b for b in c["plan"]["method_bindings"] if b["family"] == "LW"]
        if len(matches) != 1:
            raise ValueError("UNIQUE_ORIGINAL_LW_BINDING_REQUIRED")
        c["binding"] = matches[0]
        c["states"] = {}
        for row in c["publication"]["states_and_retained_attempts"]:
            if row["family"] == "LW":
                key = row["dependency_local_event_id"]
                if key in c["states"]:
                    raise ValueError("DUPLICATE_ORIGINAL_LW_DEPENDENCY")
                c["states"][key] = row
        self._components = c

    def _memo_original_source_version_guard(self, c):
        """Memo only within this already-pinned, unchanged reader/version.

        The original initializer still owns physical SHA/footer qualification.
        Stat identities are change sentinels, never substitute hash authority.
        A new source/version requires a new provider and original qualification.
        """
        reader = c["reader"]
        if not hasattr(reader, "sources") and self._domain_memo_guard is None:
            return None  # Other/synthetic readers retain their prior behavior.
        if getattr(reader, "phase", None) != "support":
            raise ValueError("DOMAIN_MEMO_EXACT_SUPPORT_READER_REQUIRED")
        sources = {name: reader.sources[name] for name in ("prediction_features", "raw_open_close")}
        version = content_hash(dict(refs=c["refs"], source_pins=sources,
            current_pool_proof=c["current_pool_proof"], master_assets=self.master_assets,
            market_dates=self.market_dates.values, calendar=c["calendar"].values))
        files = list(c["refs"][name] for name in ("plan", "support", "global", "source"))
        files.extend((ORIGINAL_HELPER_REF, *CODE_REFS, dict(path=str(Path(__file__).resolve()))))
        for pins in sources.values():
            files.extend(pins if isinstance(pins, list) else (pins,))
        physical = []
        import stat
        for reference in files:
            path = Path(reference["path"])
            if not path.is_absolute() or path.drive.upper() != "D:":
                raise ValueError("DOMAIN_MEMO_EXISTING_D_SOURCE_REQUIRED")
            for ancestor in (path, *path.parents):
                info = ancestor.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError("DOMAIN_MEMO_REPARSE_SOURCE_FORBIDDEN")
            info = path.stat()
            if "bytes" in reference and info.st_size != reference["bytes"]:
                raise ValueError("DOMAIN_MEMO_FROZEN_SOURCE_BYTES_CHANGED")
            physical.append((str(path), info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns))
        identity = (version, tuple(physical), id(reader), id(c["current_pool"]),
                    tuple(sorted((k, id(v)) for k, v in reader.datasets.items())))
        if self._domain_memo_guard is None:
            self._domain_memo_guard = identity
        elif self._domain_memo_guard != identity:
            raise ValueError("DOMAIN_MEMO_FROZEN_INPUT_OR_SOURCE_VERSION_CHANGED")
        return version

    @staticmethod
    def _copy_original_domain(domain):
        # Event/state metadata remain original owner objects. Account consumers
        # receive independent receipts/masks; holdings and numerical states are
        # never stored in the shared original-domain memo.
        from copy import deepcopy
        result = dict(domain, receipt=deepcopy(domain["receipt"]), mask=domain["mask"].copy())
        result["mask"].flags.writeable = False
        return result

    def _domain(self, day, decision_as_of):
        when = pd.Timestamp(day)
        asof = pd.Timestamp(decision_as_of)
        if (when.tzinfo is not None or when != when.normalize()
                or when >= pd.Timestamp("2026-01-01") or when not in self.market_dates
                or asof.tzinfo is None or asof != producer._clock(when)):
            raise ValueError("EXACT_PRE2026_CURRENT_CLOSE_REQUIRED")
        self._initialize()
        c = self._components
        version = self._memo_original_source_version_guard(c)
        if version is None and self._last_domain is not None and self._last_domain["day"] == when:
            return self._last_domain
        item = c["daily"][when]
        if item["future_event_date_used"] is not False or pd.Timestamp(item["decision_asof"]) != asof:
            raise ValueError("ORIGINAL_DAILY_EVENT_CLOCK_CHANGED")
        event = c["events"][item["support_epoch_event_id"]]
        producer.validate_event(event, c["calendar"])
        if (item["dependency_local_event_ids"] != event["dependency_local_event_ids"]
                or item["dependency_local_signature_sha256"] != event["dependency_local_signature_sha256"]):
            raise ValueError("ORIGINAL_DAILY_LOCAL_EVENT_BINDING_CHANGED")
        record = c["states"].get(item["dependency_local_event_ids"]["PRIMARY"])
        if record is None or record.get("publication_status") != "VERIFIED_MECHANISM_STATE":
            raise ExistingRiskInputUnavailable("ORIGINAL_LW_STATE_NOT_VERIFIED", date=str(when.date()))
        _qualify_existing(record, "LW", c["nodes"][record["event_id"]], event, asof,
                              c["events"][record["event_id"]], c["binding"], c["refs"]["plan"], None)
        assets = tuple(record["assets"])
        columns = pd.Index(self.master_assets).get_indexer(assets)
        if np.any(columns < 0):
            raise ExistingRiskInputUnavailable("ORIGINAL_FULL_POOL_OUTSIDE_MASTER", date=str(when.date()))
        index = c["calendar"].get_indexer([when])[0]
        memo_key = None
        if version is not None:
            # Revalidate original event/state gates before every hit. These are
            # complete metadata inputs only, not current holdings or covariance.
            record_fields = ("event_id", "family", "dependency_local_event_id", "recipe_id",
                "method", "as_of", "cutoff", "assets", "asset_uids", "asset_epochs", "status",
                "finite_check", "risk_state_id", "source_support_identity", "event_policy_binding",
                "publication_status", "artifact_ref", "typed_state_content_sha256",
                "covariance_sha256", "source_receipt")
            memo_key = content_hash(dict(version=version, day=when, asof=asof,
                daily=item, event=event, fit_event=c["events"][record["event_id"]],
                node=c["nodes"][record["event_id"]], binding=c["binding"],
                record={name: record.get(name) for name in record_fields}))
            if memo_key in self._domain_memo:
                self._domain_memo.move_to_end(memo_key)
                return self._copy_original_domain(self._domain_memo[memo_key])
        history = c["reader"].read("prediction_features", producer.old.FEATURE_META,
            date_field="signal_date", start=c["calendar"][max(0, index-1-306)], stop=when, tickers=assets)
        current = c["reader"].read("prediction_features", producer.old.FEATURE_META, date_field="signal_date", day=when)
        raw = c["reader"].read("raw_open_close", ("ticker", "trade_date", "code"), date_field="trade_date", day=when)
        _, _, identity_history = c["current_pool"](pd.concat((history, current), ignore_index=True), raw, event, when, assets)
        mask = np.zeros(len(self.master_assets), bool)
        mask[columns] = True
        mask.flags.writeable = False
        receipt = dict(schema="REUSED_R5_LW_CURRENT_USE_SOURCE_R1", date=str(when.date()),
            current_use_asof=asof.isoformat(), support_epoch_event_id=event["event_id"],
            original_state_asof=record["as_of"], original_fit_cutoff=record["cutoff"],
            state_id=record["risk_state_id"], original_artifact_ref=record["artifact_ref"],
            publication_typed_state_content_sha256=record["typed_state_content_sha256"],
            original_covariance_sha256=record.get("covariance_sha256"),
            ordered_fullpool_assets=list(assets), fullpool_sha256=content_hash(assets),
            asset_uids=record["asset_uids"], asset_epochs=record["asset_epochs"],
            source_support_identity=record["source_support_identity"], method_binding=c["binding"],
            current_pool_proof=c["current_pool_proof"], identity_history_rows=len(identity_history),
            identity_history_sha256=content_hash(identity_history.astype(str).to_dict("records")),
            source_refs={k: c["refs"][k] for k in ("plan", "support", "global", "source")},
            historical_publication_authority="UNKNOWN", strict_PIT=False,
            production_qualified=False, quote_qualified=False, certified_NAV=False,
            additional_fit_units=0, additional_inference_calls=0)
        self._last_domain = dict(day=when, asof=asof, event=event, record=record, mask=mask, receipt=receipt)
        if memo_key is not None:
            self._domain_memo[memo_key] = self._copy_original_domain(self._last_domain)
            while len(self._domain_memo) > len(self.market_dates):
                self._domain_memo.popitem(last=False)
            return self._copy_original_domain(self._domain_memo[memo_key])
        return self._last_domain

    def causal_domain(self, ctx):
        """New-descendant source-only domain; no old held gate is overridden."""
        if tuple(map(str, ctx.tickers)) != self.master_assets:
            raise ValueError("EXACT_MASTER_ASSET_ORDER_REQUIRED")
        original = self._domain(ctx.signal_date, ctx.signal_asof)
        result = causal_held_domain(ctx, original["mask"])
        result["source_receipt"] = dict(original["receipt"],
            domain_role="ENTRY_AND_ACTUAL_HELD_ONLY_NOT_RISK_OR_IDENTITY_AUTHORITY",
            required_assets=list(result["assets"]),
            required_domain="original_E_t_union_actual_positive_units_or_weights",
            old_default_qualification_unchanged=True, numeric_state_loaded=False)
        return result

    def audit_original_axes(self, ctx):
        """Bounded zero-estimation preflight; does not activate an account."""
        domain = self.causal_domain(ctx)
        audit = audit_complete_original_lw_axes(
            self._components["publication"]["states_and_retained_attempts"],
            domain["assets"], decision_as_of=ctx.signal_asof)
        audit["domain_source_receipt"] = domain["source_receipt"]
        return audit

    def daily_domain(self, day, *, decision_as_of):
        """Original full pool in master order; no covariance/artifact load."""
        return self._domain(day, decision_as_of)["mask"].copy()

    def for_decision(self, ctx):
        if tuple(map(str, ctx.tickers)) != self.master_assets:
            raise ValueError("EXACT_MASTER_ASSET_ORDER_REQUIRED")
        domain = self._domain(ctx.signal_date, ctx.signal_asof)
        count = len(self.master_assets)
        units = _vector(ctx, "current_units", count)
        weights = _vector(ctx, "current_weights", count)
        decision = _vector(ctx, "decision_mask", count, boolean=True)
        buy = _vector(ctx, "buy_allowed", count, boolean=True)
        held = (units > 0) | (weights > 0)
        if np.any(held & ~domain["mask"]):
            raise ExistingRiskInputUnavailable("ACTUAL_HELD_OUTSIDE_ORIGINAL_FULLPOOL", date=str(domain["day"].date()),
                assets=[self.master_assets[i] for i in np.flatnonzero(held & ~domain["mask"])])
        eligible = decision & buy & domain["mask"]
        columns = np.flatnonzero(eligible | held)
        assets = tuple(self.master_assets[i] for i in columns)
        receipt = dict(domain["receipt"], required_assets=list(assets), required_domain="(decision&buy&original_fullpool)|actual_positive_units_or_weights",
                       required_domain_sha256=content_hash(assets), exact_principal_projection=True,
                       numerical_cache_max_states=2, per_use_original_physical_and_typed_guards=True)
        if not len(columns):
            covariance = np.empty((0, 0))
            receipt.update(numeric_state_loaded=False, consumer_psd_guard="EMPTY_REQUIRED_CASH_DOMAIN")
        else:
            c, record = self._components, domain["record"]
            key = (record["risk_state_id"], record["artifact_ref"]["sha256"], record["typed_state_content_sha256"])
            # Original physical and typed commitments are guarded on every use.
            state = c["state_loader"](record)
            _qualify_existing(record, "LW", c["nodes"][record["event_id"]], domain["event"], domain["asof"],
                c["events"][record["event_id"]], c["binding"], c["refs"]["plan"], {state.risk_state_id: state})
            if key not in self._checked:
                full = np.asarray(state.covariance, dtype=float)
                if full.shape != (len(record["assets"]), len(record["assets"])):
                    raise ValueError("ORIGINAL_FULL_COVARIANCE_SHAPE_CHANGED")
                _, psd = validate_covariance(full, regularize=False)
                self._checked[key] = (state, full, psd)
                while len(self._checked) > 2:
                    self._checked.popitem(last=False)
                loader_cache = getattr(c["state_loader"], "cache", {})
                active = {id(item[0]) for item in self._checked.values()}
                for cached_key in tuple(loader_cache):
                    if id(loader_cache[cached_key]) not in active:
                        del loader_cache[cached_key]
            self._checked.move_to_end(key)
            cached_state, full, psd = self._checked[key]
            if cached_state is not state:
                raise ValueError("ORIGINAL_STATE_CACHE_IDENTITY_CHANGED")
            positions = pd.Index(record["assets"]).get_indexer(assets)
            covariance = np.array(full[np.ix_(positions, positions)], copy=True)
            receipt.update(numeric_state_loaded=True, consumer_psd_guard=psd,
                           original_numeric_check=state.notes.get("numeric_check", state.notes.get("numeric")),
                           consumer_projection_sha256=content_hash(dict(assets=assets, covariance=covariance)))
        for value in (columns, covariance):
            value.flags.writeable = False
        return ExistingRiskSlice(assets, columns, covariance, domain["mask"], True,
                                 receipt, self.loads_count)


class HeldLineageUnavailable(ValueError):
    """A missing/conflicting current held source is not a feature-pool expiry."""

    def __init__(self, reason, **details):
        self.receipt = dict(status="BLOCKED_REQUIRED_HELD_IDENTITY", reason=reason,
                            strict_PIT=False, production_qualified=False, **details)
        super().__init__(reason)


def _held_session(value):
    when = pd.Timestamp(value)
    if (pd.isna(when) or when.tzinfo is not None or when != when.normalize()
            or when >= pd.Timestamp("2026-01-01")):
        raise ValueError("PRE2026_HELD_SESSION_REQUIRED")
    return str(when.date())


def _held_text(value):
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in ("UNKNOWN", "NONE", "NAN"):
        raise HeldLineageUnavailable("EXACT_HELD_IDENTITY_FIELD_REQUIRED")
    return value


def _held_ref(value):
    if not isinstance(value, dict):
        raise HeldLineageUnavailable("PINNED_HELD_SOURCE_REF_REQUIRED")
    path, sha = value.get("path"), value.get("sha256")
    if (not isinstance(path, str) or not path.strip()
            or path.replace("\\", "/").upper().startswith(("E:/", "F:/"))
            or not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)):
        raise HeldLineageUnavailable("PINNED_HELD_SOURCE_REF_REQUIRED")
    # This validates a supplied commitment only; it never resolves or reads it.
    return dict(path=path, sha256=sha)


def _held_quantity(value):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("DIRECT_NONNEGATIVE_RAW_QUANTITY_REQUIRED")
    result = float(value)
    if not np.isfinite(result) or result < 0:
        raise ValueError("DIRECT_NONNEGATIVE_RAW_QUANTITY_REQUIRED")
    return result


def _held_equal(left, right):
    return bool(np.isclose(left, right, rtol=1e-12, atol=1e-10))


def _held_identity(value):
    result = {k: _held_text(value.get(k)) for k in
              ("security_id", "security_id_type", "cusip", "share_class", "raw_code")}
    if result["security_id_type"] == "CUSIP" and result["security_id"] != result["cusip"]:
        raise HeldLineageUnavailable("SID_CUSIP_CONFLICT")
    if value.get("raw_actual_share_coordinate") != "RAW_ACTUAL_SHARE":
        raise HeldLineageUnavailable("RAW_ACTUAL_SHARE_COORDINATE_REQUIRED")
    result["raw_actual_share_coordinate"] = "RAW_ACTUAL_SHARE"
    return result


def _held_class_equal(left, right):
    """Compare exact class tokens and generic ordinary-common-stock wording.

    Only COM and Common Stock are spelling forms of the same generic label.
    Raw source literals and commitments remain untouched; callers still bind
    exact security, CUSIP, raw-share, source and clock coordinates. No class,
    quantity, membership or accounting conversion is granted here.
    """
    import re
    try:
        _held_text(left); _held_text(right)
    except HeldLineageUnavailable:
        return False
    if left == right:
        return True
    ascii_space = " \t\n\r\f\v"
    def tokens(value):
        if any(char.isspace() and char not in ascii_space for char in value):
            return None
        return tuple(re.split(r"[ \t\n\r\f\v]+", value.strip(ascii_space)))
    first, second = tokens(left), tokens(right)
    if first is None or second is None:
        return False
    if first == second:
        return True
    if not all(token.isascii() for token in first + second):
        return False
    generic_common = {("COM",), ("COMMON", "STOCK")}
    return (tuple(token.upper() for token in first) in generic_common
            and tuple(token.upper() for token in second) in generic_common)



def _held_security_identity_equal(left, right, descriptor_bridges=()):
    """Keep non-class coordinates exact; compare class spellings without rewriting."""
    fields = {"security_id", "security_id_type", "cusip", "share_class", "raw_code",
              "raw_actual_share_coordinate"}
    if not isinstance(left, dict) or not isinstance(right, dict) or set(left) != fields or set(right) != fields:
        return False
    try:
        _held_identity(left); _held_identity(right)
    except HeldLineageUnavailable:
        return False
    if not all(left[k] == right[k] for k in fields - {"share_class"}):
        return False
    if _held_class_equal(left["share_class"], right["share_class"]):
        return True
    return any(all(left[k] == bridge["coordinates"][k] for k in fields - {"share_class"})
               and {left["share_class"], right["share_class"]} == set(bridge["descriptors"])
               for bridge in descriptor_bridges)


def _load_share_class_descriptor_bridge(interface, reference, uid_intervals_ref):
    """Bind specific original source descriptors; never infer a generic class alias."""
    from copy import deepcopy
    reference = _held_ref(reference)
    value = interface.read(_causal_pin(interface, reference))
    scope = value.get('bridge_binding_requirements', {})
    _causal_need(value.get('schema') == 'B_ISSUER_CUSIP_SOURCE_BOUND_SHARE_CLASS_DESCRIPTOR_BRIDGE_V1'
        and value.get('status') == 'SOURCE_FACTS_VERIFIED_BRIDGE_CANDIDATE_NOT_RUNTIME_ADMISSION'
        and value.get('original_interval_authority_unchanged') is True
        and value.get('authority', {}).get('research_identity_descriptor_evidence_only') is True
        and all(value['authority'].get(k) is False for k in
            ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
        and scope.get('scope') == 'EXACT_ISSUER_CUSIP_CLASS_SPECIFIC_SOURCE_DESCRIPTOR_EQUIVALENCE_FOR_RETAINED_ACCOUNT_IDENTITY_ONLY'
        and all(scope.get(k) is False for k in ('buy_permission_extension_allowed',
            'class_B_or_preferred_or_warrant_bridge_allowed','cross_cusip_substitution_allowed',
            'membership_interval_extension_allowed','new_ticker_alias_inference_allowed')),
        'EXACT_SOURCE_BOUND_DESCRIPTOR_BRIDGE_REQUIRED')
    subject=value['subject']; descriptors=tuple(subject['source_descriptor_pair'])
    _causal_need(len(descriptors)==2 and len(set(descriptors))==2
        and all(isinstance(c,str) and _held_text(c)==c for c in descriptors)
        and subject['security_id_type']=='CUSIP' and subject['security_id']==subject['cusip']
        and subject['share_unit']=='RAW_ACTUAL_SHARE', 'EXACT_DESCRIPTOR_SUBJECT_REQUIRED')
    rows=value['original_interval_rows']
    _causal_need(len(rows)==2, 'EXACT_TWO_SOURCE_DESCRIPTOR_ROWS_REQUIRED')
    row_hashes=[]; normalized=[]
    for entry in rows:
        row=deepcopy(entry['source_row'])
        row['effective_start']=pd.Timestamp(row['effective_start'])
        row['effective_end']=pd.Timestamp(row['effective_end'])
        _held_session(row['effective_start']); _held_session(row['effective_end'])
        _causal_need(row['effective_start']<=row['effective_end']
            and row['mapping_status']=='RESOLVED'
            and content_hash(row)==entry['source_row_content_sha256'],
            'UNCHANGED_ORIGINAL_DESCRIPTOR_ROW_COMMITMENT_REQUIRED')
        identity=_held_identity(entry['identity'])
        _causal_need(identity==_held_identity(dict(row,share_class=row['title_of_class'],
            raw_code=row['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
            and identity['security_id']==subject['security_id'] and identity['cusip']==subject['cusip']
            and identity['share_class'] in descriptors, 'EXACT_DESCRIPTOR_ROW_SUBJECT_REQUIRED')
        normalized.append(row);row_hashes.append(content_hash(row))
    coordinates={k:rows[0]['identity'][k] for k in rows[0]['identity'] if k!='share_class'}
    _causal_need(all({k:e['identity'][k] for k in e['identity'] if k!='share_class'}==coordinates for e in rows)
        and len({r['ticker'] for r in normalized})==1
        and set(row_hashes)==set(scope['source_row_identity_commitments_required'])
        and {e['identity']['share_class'] for e in rows}==set(descriptors),
        'EXACT_COMMON_SECURITY_DESCRIPTOR_COORDINATES_REQUIRED')
    # The original pool source is already pinned by the original reader. Bind its
    # commitment explicitly without rehashing the large interval parquet here.
    _causal_need(_held_ref(uid_intervals_ref)['sha256']==value.get('original_uid_intervals_sha256',
        'cafd53e665143e56d31c3f7b5299593a099fc53a0032879d63fbd8abae6a0d30'),
        'EXACT_ORIGINAL_DESCRIPTOR_INTERVAL_SOURCE_REQUIRED')
    for artifact in value['existing_official_dataset_refs']:
        _causal_pin(interface,dict(path=artifact['path'],sha256=artifact['physical_sha256']))
    facts=value['existing_official_dataset_identity_rows']
    filings={r['ACCESSION_NUMBER']:r for r in value['existing_official_dataset_submission_rows']}
    # Original proofs keep their exact March-2023 default.  Source descendants
    # explicitly declare one of the reviewed reports; this is not a date search
    # or a generic class spelling alias.
    same_report=value.get('same_report_date','31-MAR-2023')
    _causal_need(type(same_report) is str and same_report in ('31-MAR-2023','31-DEC-2022','30-JUN-2024'),
        'EXACT_DECLARED_DESCRIPTOR_SAME_REPORT_DATE_REQUIRED')
    if same_report!='31-MAR-2023':
        names=subject.get('issuer_source_names')
        _causal_need(isinstance(names,list) and len(names)==len(set(names))
            and set(names)=={r['issuer_name'] for r in normalized}
            and all(isinstance(n,str) and bool(n.strip()) for n in names)
            and all(r.get('NAMEOFISSUER') in names for r in facts)
            and {r.get('NAMEOFISSUER') for r in facts}==set(names),
            'EXACT_ORIGINAL_DESCRIPTOR_ISSUER_SOURCE_NAMES_REQUIRED')
    _causal_need(all(r['CUSIP']==subject['cusip'] and r['SSHPRNAMTTYPE']=='SH'
        and r['PUTCALL'] is None and r['TITLEOFCLASS'] in descriptors for r in facts)
        and len(facts)>=3 and set(r['TITLEOFCLASS'] for r in facts)==set(descriptors)
        and all(r['ACCESSION_NUMBER'] in filings for r in facts)
        and max(pd.to_datetime(f['FILING_DATE']) for f in filings.values())<=
            min(r['effective_end'] for r in normalized)
        and {r['TITLEOFCLASS'] for r in facts
             if filings[r['ACCESSION_NUMBER']]['PERIODOFREPORT']==same_report}==set(descriptors),
        'EXACT_PREEXISTING_COMMON_CUSIP_SHARE_DESCRIPTOR_FACTS_REQUIRED')
    return (dict(source_ref=reference,coordinates=coordinates,descriptors=descriptors,
        original_rows=normalized,row_hashes=tuple(row_hashes),
        original_uid_intervals_ref=_held_ref(uid_intervals_ref),
        historical_bridge_available_at=value['identity_source_filing_availability']['historical_bridge_available_at'],
        historical_availability_qualified=False),)


def _extend_share_class_descriptor_bridge(interface, bridges, reference, uid_intervals_ref):
    """Append only independently evidenced original rows, preserving R1 gates."""
    from copy import deepcopy
    _causal_need(len(bridges)==1, 'EXACT_BASE_DESCRIPTOR_BRIDGE_REQUIRED')
    bridge=deepcopy(bridges[0]); reference=_held_ref(reference)
    value=interface.read(_causal_pin(interface,reference));base=value['base_receipt']
    _causal_need(value.get('schema')=='B_NXDR_DATED_DESCRIPTOR_SOURCE_COMPLETENESS_EXTENSION_V1'
        and value.get('status')=='PARTIAL_SOURCE_FACT_EXTENSION_COMPLETE_NOT_RUNTIME_ADMISSION'
        and _held_ref(dict(path=base['path'],sha256=base['physical_sha256']))==bridge['source_ref']
        and base.get('unchanged') is True
        and value['authority'].get('research_identity_descriptor_evidence_only') is True
        and all(value['authority'].get(k) is False for k in
            ('strict_PIT','production_qualified','quote_qualified','certified_NAV')),
        'EXACT_UNCHANGED_BASE_DESCRIPTOR_EXTENSION_REQUIRED')
    scope=value['bridge_binding_requirements'];subject=value['subject'];source=value['uid_interval_source']
    _causal_need(scope.get('scope')=='EXACT_ISSUER_CUSIP_CLASS_SPECIFIC_SOURCE_DESCRIPTOR_EQUIVALENCE_FOR_RETAINED_ACCOUNT_IDENTITY_ONLY'
        and all(scope.get(k) is False for k in ('buy_permission_extension_allowed',
            'class_B_or_preferred_or_warrant_bridge_allowed','cross_cusip_substitution_allowed',
            'membership_interval_extension_allowed','new_ticker_alias_inference_allowed'))
        and tuple(subject['source_descriptor_pair'])==bridge['descriptors']
        and subject['security_id']==bridge['coordinates']['security_id']
        and subject['security_id_type']==bridge['coordinates']['security_id_type']
        and subject['cusip']==bridge['coordinates']['cusip'] and subject['share_unit']=='RAW_ACTUAL_SHARE'
        and _held_ref(dict(path=source['path'],sha256=source['accepted_immutable_physical_sha256']))==
            _held_ref(uid_intervals_ref)==bridge['original_uid_intervals_ref'],
        'EXACT_DESCRIPTOR_EXTENSION_SUBJECT_SOURCE_AND_SCOPE_REQUIRED')
    dataset_refs=tuple(_held_ref(dict(path=a['path'],sha256=a['physical_sha256']))
        for a in value['new_existing_official_dataset_refs'])
    rows=[];hashes=[];blocked=[];new_count=0
    for entry in value['original_interval_assessments']:
        row=deepcopy(entry['source_row'])
        row['effective_start']=pd.Timestamp(row['effective_start']);row['effective_end']=pd.Timestamp(row['effective_end'])
        _held_session(row['effective_start']);_held_session(row['effective_end'])
        digest=content_hash(row)
        _causal_need(digest==entry['source_row_content_sha256']
            and row['effective_start']<=row['effective_end']
            and entry.get('membership_interval_unchanged') is True,
            'UNCHANGED_DATED_DESCRIPTOR_EXTENSION_ROW_REQUIRED')
        if entry.get('bridge_allowed') is not True:
            if entry['status']=='BLOCKED_NO_CLASS_EXPLICIT_SAME_REPORT_COUNTERPART_IN_ORIGINAL_SOURCE_FILINGS':
                blocked.append(digest)
            continue
        observed=_held_identity(dict(row,share_class=row['title_of_class'],
            raw_code=row['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
        _causal_need(row['mapping_status']=='RESOLVED' and row['ticker']==bridge['original_rows'][0]['ticker']
            and {k:v for k,v in observed.items() if k!='share_class'}==bridge['coordinates']
            and observed['share_class'] in bridge['descriptors'], 'EXACT_EXTENSION_ROW_SECURITY_COORDINATES_REQUIRED')
        if digest in bridge['row_hashes']:
            _causal_need(entry['status']=='VERIFIED_BY_UNCHANGED_BASE_SOURCE_RECEIPT'
                and any(content_hash(old)==digest and old==row for old in bridge['original_rows']),
                'UNCHANGED_ORIGINAL_TWO_DESCRIPTOR_ROWS_REQUIRED')
        else:
            facts=entry['source_facts'];accessions=set(row['source_filing'].split(';'))
            _causal_need(entry['status']=='VERIFIED_EXACT_SAME_REPORT_DESCRIPTOR_PAIR'
                and entry.get('same_report_descriptor_pair_observed') is True
                and set(entry['original_source_filing_accessions'])==accessions
                and len(facts)==2
                and {f['identity_row']['TITLEOFCLASS'] for f in facts}==set(bridge['descriptors'])
                and len({f['report_date_iso'] for f in facts})==1,
                'EXACT_SOURCE_ROW_BOUND_SAME_REPORT_DESCRIPTOR_PAIR_REQUIRED')
            counterparts=entry.get('counterpart_source_accessions',())
            counterpart_set=set(counterparts)
            if counterparts:
                _causal_need(entry.get('counterpart_source_binding_kind')==
                    'EXISTING_OFFICIAL_SAME_REPORT_CUSIP_CLASS_COUNTERPART'
                    and len(counterpart_set)==len(counterparts) and not counterpart_set&accessions
                    and {f['identity_row']['ACCESSION_NUMBER'] for f in facts}==accessions|counterpart_set
                    and {f.get('role') for f in facts}==
                        {'ORIGINAL_ARK_GENERIC_SOURCE','ADDITIONAL_OTHER_FILER_CLASS_EXPLICIT_SOURCE'},
                    'EXPLICIT_ORIGINAL_AND_OTHER_FILER_COUNTERPART_BINDING_REQUIRED')
            else:
                _causal_need('counterpart_source_binding_kind' not in entry,
                    'UNDECLARED_OTHER_FILER_COUNTERPART_REQUIRED')
            for fact in facts:
                identity,submission=fact['identity_row'],fact['submission_row']
                filing=pd.Timestamp(fact['filing_date_iso']);report=pd.Timestamp(fact['report_date_iso'])
                _held_session(filing);_held_session(report)
                if counterparts:
                    _causal_need(bool(_held_text(identity['INFOTABLE_SK']))
                        and content_hash(identity)==fact['identity_row_content_sha256']
                        and content_hash(submission)==fact['submission_row_content_sha256']
                        and _held_ref(fact['identity_source_ref']) in dataset_refs
                        and _held_ref(fact['submission_source_ref']) in dataset_refs
                        and submission['SUBMISSIONTYPE']=='13F-HR'
                        and ((identity['ACCESSION_NUMBER'] in accessions
                            and fact['role']=='ORIGINAL_ARK_GENERIC_SOURCE'
                            and identity['TITLEOFCLASS']==row['title_of_class'])
                            or (identity['ACCESSION_NUMBER'] in counterpart_set
                            and fact['role']=='ADDITIONAL_OTHER_FILER_CLASS_EXPLICIT_SOURCE'
                            and identity['TITLEOFCLASS']!=row['title_of_class'])),
                        'EXACT_OTHER_FILER_SOURCE_REFS_SK_AND_TYPED_CONTENT_REQUIRED')
                _causal_need(isinstance(identity.get('NAMEOFISSUER'),str)
                    and isinstance(row.get('issuer_name'),str)
                    and bool(identity['NAMEOFISSUER']) and bool(row['issuer_name'])
                    and identity['NAMEOFISSUER'].isascii() and row['issuer_name'].isascii()
                    and identity['NAMEOFISSUER'].upper()==row['issuer_name'].upper(),
                    'EXACT_ASCII_CASE_ONLY_SOURCE_ISSUER_BINDING_REQUIRED')
                _causal_need(identity['ACCESSION_NUMBER']==submission['ACCESSION_NUMBER']
                    and identity['ACCESSION_NUMBER'] in accessions|counterpart_set
                    and identity['CUSIP']==bridge['coordinates']['cusip']
                    and identity['SSHPRNAMTTYPE']=='SH' and identity['PUTCALL'] is None
                    and identity['TITLEOFCLASS'] in bridge['descriptors']
                    and pd.Timestamp(submission['PERIODOFREPORT'])==report
                    and pd.Timestamp(submission['FILING_DATE'])==filing
                    and report<=filing<=row['effective_start'],
                    'EXACT_PREEXISTING_EXTENSION_FILING_CUSIP_CLASS_AND_CLOCK_REQUIRED')
            new_count+=1
        rows.append(row);hashes.append(digest)
    counts=value['counts']
    _causal_need(isinstance(counts['additional_same_report_source_proven_rows'],int)
        and not isinstance(counts['additional_same_report_source_proven_rows'],bool)
        and counts['additional_same_report_source_proven_rows']>0
        and counts['unchanged_base_bridge_rows']==len(bridge['row_hashes'])
        and counts['bridge_bound_rows_total']==len(bridge['row_hashes'])+counts['additional_same_report_source_proven_rows']
        and len(hashes)==len(set(hashes))
        and new_count==counts['additional_same_report_source_proven_rows']
        and len(hashes)==counts['bridge_bound_rows_total']
        and set(bridge['row_hashes']).issubset(hashes)
        and set(hashes)==set(scope['source_row_identity_commitments_required'])
        and set(blocked)==set(value['blocked_original_row_content_sha256'])
        and not set(blocked)&set(hashes), 'EXACT_DECLARED_PROVEN_EXTENSION_ROWS_ONLY_REQUIRED')
    for artifact in value['new_existing_official_dataset_refs']:
        _causal_pin(interface,dict(path=artifact['path'],sha256=artifact['physical_sha256']))
    bridge.update(original_rows=rows,row_hashes=tuple(hashes),extension_ref=reference,
        blocked_original_row_hashes=tuple(blocked),historical_availability_qualified=False)
    return (bridge,)


def _normalize_additional_descriptor_bridge_refs(references):
    """Validate only explicit input references; source proof gates remain below."""
    if references is None: return ()
    _causal_need(isinstance(references,list) and bool(references),
        'EXPLICIT_ADDITIONAL_DESCRIPTOR_BRIDGE_REFERENCE_LIST_REQUIRED')
    normalized=[];seen=set()
    for entry in references:
        _causal_need(isinstance(entry,dict) and set(entry) in
            ({'bridge_ref'},{'bridge_ref','extension_ref'}),
            'EXACT_ADDITIONAL_DESCRIPTOR_BRIDGE_REFERENCE_SHAPE_REQUIRED')
        item={}
        for key in ('bridge_ref','extension_ref'):
            if key not in entry: continue
            reference=_held_ref(entry[key])
            _causal_need(set(entry[key])=={'path','sha256'} and reference['sha256'] not in seen,
                'UNIQUE_EXACT_ADDITIONAL_DESCRIPTOR_BRIDGE_INPUT_REFS_REQUIRED')
            seen.add(reference['sha256']);item[key]=reference
        normalized.append(item)
    return tuple(normalized)


def _load_additional_share_class_descriptor_bridges(interface, normalized_references, uid_intervals_ref, existing_bridges=()):
    """Append separately pinned proofs via the unchanged base/extension owners."""
    bridges=tuple(existing_bridges)
    seen={r['sha256'] for b in bridges for r in
        ([b['source_ref']]+([b['extension_ref']] if 'extension_ref' in b else []))}
    for item in normalized_references:
        _causal_need(not any(r['sha256'] in seen for r in item.values()),
            'ADDITIONAL_DESCRIPTOR_INPUT_MUST_NOT_DUPLICATE_EXISTING_BRIDGE')
        extra=_load_share_class_descriptor_bridge(interface,item['bridge_ref'],uid_intervals_ref)
        if 'extension_ref' in item:
            extra=_extend_share_class_descriptor_bridge(interface,extra,item['extension_ref'],uid_intervals_ref)
        bridges+=extra;seen.update(r['sha256'] for r in item.values())
    return bridges


def _held_source_row_descriptor_bridge(row, identity, descriptor_bridges):
    """A different descriptor requires this exact original dated source row."""
    try:
        observed=_held_identity(dict(row,share_class=row['title_of_class'],
            raw_code=row['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
    except HeldLineageUnavailable:
        return False
    if _held_security_identity_equal(observed,identity):
        return True
    return any(content_hash(row) in b['row_hashes'] and
        _held_security_identity_equal(observed,identity,(b,)) for b in descriptor_bridges)



DELAYED_IDENTITY_METADATA_TRANSPORT_RULE = dict(
    schema='B_DELAYED_SOURCE_IDENTITY_METADATA_TRANSPORT_RULE_V1',
    scope='PINNED_COMMON_STOCK_CUSIP_UPDATE_FOR_POST_ACTION_RAW_SHARE_POSITION_ONLY',
    immutable_admission_seed=True, historical_observations_relabelled=False,
    quantity_effect=False, typed_CA_event=False, risk_identity_alias=False,
    membership_extension=False, buy_permission_extension=False,
    strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)


def _load_pre_action_existing_held_identity_metadata_transport(interface, reference, value, uid_ref, event_ref):
    """A declared common identity relation; actual accepted share history admits its use."""
    from copy import deepcopy
    import html, re
    _causal_need(value.get('status')=='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION'
        and value.get('rule')==DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
        and value.get('relation_role')=='SAME_ISSUED_AND_OUTSTANDING_COMMON_STOCK_OLD_QUALIFIED_SEED_AND_NEW_ISSUER_SOURCE'
        and _held_ref(value['original_uid_intervals_ref'])==_held_ref(uid_ref)
        and _held_ref(value['original_event_binding_ref'])==_held_ref(event_ref)
        and value.get('historical_original_archive_vintage')=='UNKNOWN'
        and all(value.get(k) is False for k in ('quantity_effect','typed_CA_event','historical_observations_relabelled',
            'historical_availability_qualified','strict_PIT','production_qualified','quote_qualified','certified_NAV')),
        'EXACT_PRE_ACTION_EXISTING_HELD_METADATA_SOURCE_INPUT_REQUIRED')
    original=Path(_causal_pin(interface,_held_ref(value['issuer_original_ref'])))
    fragment=Path(_causal_pin(interface,_held_ref(value['issuer_fragment_ref']))).read_bytes()
    bounds=value['issuer_fragment_byte_range']
    _causal_need(isinstance(bounds,list) and len(bounds)==2 and all(type(v) is int for v in bounds)
        and 0<=bounds[0]<bounds[1]<=original.stat().st_size,'EXACT_ISSUER_ARTICLE_BYTE_RANGE_REQUIRED')
    with original.open('rb') as stream:
        stream.seek(bounds[0]);actual=stream.read(bounds[1]-bounds[0])
    text=' '.join(html.unescape(re.sub('<[^>]*>',' ',fragment.decode('utf-8'))).split())
    _causal_need(actual==fragment and text==value['issuer_article_text']
        and value['source_unchanged_rights_literal']=='will not modify any rights or preferences'
        and all(value[k] in text for k in ('source_ratio_literal','source_effective_literal',
            'source_new_cusip_literal','source_common_literal','source_unchanged_rights_literal','source_ticker_literal')),
        'EXACT_ORIGINAL_ISSUER_COMMON_SPLIT_AND_IDENTITY_TERMS_REQUIRED')
    entries=value['original_rows'];_causal_need(len(entries)==2,'EXACT_TWO_ORIGINAL_HELD_METADATA_ROWS_REQUIRED')
    rows=[];identities=[]
    for entry in entries:
        row=deepcopy(entry['source_row'])
        row['effective_start']=pd.Timestamp(row['effective_start']);row['effective_end']=pd.Timestamp(row['effective_end'])
        identity=_held_identity(entry['identity'])
        observed=_held_identity(dict(row,share_class=row['title_of_class'],raw_code=row['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
        _causal_need(set(FrozenHeldSourceGuards.IDENTITY_COLUMNS)==set(row)
            and content_hash(row)==entry['source_row_content_sha256'] and identity==observed
            and row['mapping_status']=='RESOLVED' and identity['security_id_type']=='CUSIP'
            and identity['cusip']==identity['security_id'] and row['effective_start']<=row['effective_end'],
            'EXACT_IMMUTABLE_ORIGINAL_HELD_METADATA_ROW_REQUIRED')
        rows.append(row);identities.append(identity)
    before,after=rows;old,new=identities
    common=('COM','COM SHS','COM CL A','Common Stock','Class A Common Stock')
    effective=pd.Timestamp(value['split_effective_at']);post=_held_session(value['post_split_trading_session'])
    publication=_held_session(value['issuer_publication_date'])
    event=value['original_share_event'];ratio_terms=re.fullmatch(r'([1-9][0-9]*)-for-([1-9][0-9]*)',value['source_ratio_literal'])
    _causal_need(before['ticker']==after['ticker'] and before['issuer_name']==after['issuer_name']
        and before['title_of_class'] in common and after['title_of_class'] in common
        and value['source_common_literal']=='common stock' and old['cusip']!=new['cusip']
        and re.fullmatch(r'(NYSE|NASDAQ|NYSE American): '+re.escape(before['ticker']),value['source_ticker_literal']) is not None
        and re.sub(r'\s+','',value['source_new_cusip_literal'])==new['cusip']
        and old['raw_code']==new['raw_code']=='US.'+before['ticker']
        and before['effective_end']<after['effective_start'] and not pd.isna(effective) and effective.tzinfo is not None
        and str(effective.tz_convert('America/New_York').date())==post==publication
        and value['source_effective_literal']==effective.tz_convert('America/New_York').strftime('%I:%M %p').lower().lstrip('0')+' Eastern Time today, '+effective.tz_convert('America/New_York').strftime('%B ')+str(effective.tz_convert('America/New_York').day)+effective.tz_convert('America/New_York').strftime(', %Y')
        and before['effective_start']<pd.Timestamp(post)<after['effective_start']
        and ratio_terms is not None and event['effective_date']==post
        and event['old_ticker']==event['new_ticker']==before['ticker']
        and event['old_security_id']==event['new_security_id']
        and event['action_type'] in ('FORWARD_SPLIT','REVERSE_SPLIT','OTHER_SHARE_COUNT_TRANSFORM')
        and _held_equal(event['quantity_multiplier'],int(ratio_terms[1])/int(ratio_terms[2])),
        'EXACT_SOURCE_BOUND_PRE_ACTION_COMMON_AND_ALREADY_TYPED_SHARE_RELATION_REQUIRED')
    return (dict(source_ref=reference,facts_ref=reference,original_uid_intervals_ref=_held_ref(uid_ref),
        original_event_binding_ref=_held_ref(event_ref),original_event=deepcopy(event),account_owner_ref=_held_ref(value['account_owner_ref']),
        old_identity=old,new_identity=new,old_row=before,new_row=after,old_row_hash=content_hash(before),new_row_hash=content_hash(after),
        post_split_trading_session=post,split_effective_at=effective.isoformat(),source_filing_day=publication,
        historical_availability_qualified=False,pre_action_existing_held=True),)


def _load_post_action_public_class_a_metadata_transport(interface,reference,value,uid_ref):
    """Pinned public-parent rights and original reported SH rows; no quantity event."""
    from copy import deepcopy
    import re
    from scripts.storage.refresh_sec_event_originals import FilingText
    _causal_need(value.get('schema')=='B_SOURCE_BOUND_POST_ACTION_PUBLIC_CLASS_A_HELD_METADATA_INPUT_V1'
        and value.get('status')=='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION'
        and value.get('rule')==DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
        and value.get('relation_role')=='PUBLIC_PARENT_CLASS_A_ONE_FOR_ONE_RECLASSIFICATION_RETAINED_ACTUAL_RAW_H_METADATA_ONLY'
        and _held_ref(value['original_uid_intervals_ref'])==_held_ref(uid_ref)
        and value.get('diagnostic_role')=='DIGEST_ONLY_NOT_A_FUTURE_H_TABLE_OR_CURRENT_SECURITY_AUTHORITY'
        and value.get('broker_redemption_election_authority')=='UNKNOWN'
        and value.get('actual_legal_reclassification_execution')=='NOT_INFERRED'
        and all(value.get(k) is False for k in ('quantity_effect','typed_CA_event','historical_observations_relabelled','historical_availability_qualified','strict_PIT','production_qualified','quote_qualified','certified_NAV','BUY_permission','pool_interval_extension')),
        'EXACT_POST_ACTION_PUBLIC_CLASS_A_METADATA_INPUT_REQUIRED')
    # Hash custody only. Never decode the multi-session diagnostic held table.
    _causal_pin(interface,_held_ref(value['actual_mechanism_continuity_diagnostic_ref']))
    facts_ref=_held_ref(value['source_facts_ref']);facts=interface.read(_causal_pin(interface,facts_ref))
    _causal_need(facts.get('schema')=='B_POST_ACTION_PUBLIC_CLASS_A_EXISTING_HELD_SOURCE_FACTS_V1'
        and facts.get('issuer_original_CUSIP_literal') is None and facts.get('issuer_original_no_CUSIP_claim') is True
        and facts.get('public_nonredeemed_Class_A_relation')=='ONE_FOR_ONE_PUBLIC_CLASS_A_RECLASSIFICATION_TO_COMPANY_CLASS_A_COMMON'
        and facts.get('private_exchange_and_Sponsor_Class_B_not_held_role') is True
        and facts.get('actual_reclassification_execution_or_redemption_not_observed') is True
        and all(facts.get(k) is False for k in ('quantity_effect','typed_CA_event','voluntary_redemption_assumed','strict_PIT','production_qualified','quote_qualified','certified_NAV')),
        'PUBLIC_RECLASSIFICATION_NOT_PRIVATE_EXCHANGE_OR_BROKER_ACTION')
    original=Path(_causal_pin(interface,_held_ref(facts['issuer_primary_original_ref'])))
    fragments={}
    for item in facts['issuer_fragments']:
        start,end=item['source_original_byte_range']
        _causal_need(type(start) is int and type(end) is int and 0<=start<end<=original.stat().st_size and end-start<=65536,'BOUNDED_PUBLIC_CLASS_A_FRAGMENT_REQUIRED')
        with original.open('rb') as stream:stream.seek(start);raw=stream.read(end-start)
        saved=Path(_causal_pin(interface,_held_ref(item['original_fragment_ref']))).read_bytes()
        parser=FilingText();parser.feed(raw.decode('utf-8'));text=' '.join(' '.join(parser.parts).split())
        _causal_need(raw==saved and text==item['visible_text'] and content_hash(text)==item['text_typed_content_sha256'],'PUBLIC_CLASS_A_ORIGINAL_FRAGMENT_CHANGED')
        fragments[item['role']]=text
    public=fragments['PUBLIC_CLASS_A_RECLASSIFICATION_SEPARATE_SPONSOR_CLASSES']
    _causal_need(re.search(r'\(i\) each share of Class A common stock subject to redemption held by AltC stockholders.*?AltC public stockholders.*?was reclassified on a one\s*-\s*for\s*-\s*one basis as one share of the Company.*?Class A common stock.*?\(ii\)',public) is not None,
        'EXPLICIT_PUBLIC_CLASS_A_ONE_FOR_ONE_ROLE_REQUIRED')
    capital=fragments['RESTATED_CAPITAL_ONLY_PUBLIC_CLASS_A_COMMON_AND_PREFERRED']
    _causal_need(re.search(r'consisting of \(i\).*?shares of Class A common stock.*?and \(ii\).*?shares of preferred stock',capital) is not None,
        'EXPLICIT_RESTATED_PUBLIC_CLASS_A_COMMON_AND_PREFERRED_CAPITAL_REQUIRED')
    legal=fragments['PUBLIC_PARENT_AND_PRIVATE_SUBSIDIARY_DISTINCT']
    _causal_need('AltC Acquisition Corp.' in legal and 'AltC changed its name to Oklo Inc.' in legal
        and 'Oklo Technologies, Inc.' in legal,'PUBLIC_PARENT_AND_PRIVATE_SUBSIDIARY_MUST_STAY_DISTINCT')
    md=deepcopy(facts['historical_SEC_metadata_row'])
    for field in ('filed_date','accepted_datetime'):md[field]=pd.Timestamp(md[field])
    _causal_need(content_hash(md)==facts['historical_SEC_metadata_row_content_sha256'] and md['cik']==facts['issuer_CIK']
        and md['form']=='10-Q' and md['name']==facts['issuer_public_parent_current']
        and pd.Timestamp(md['filed_date'])<pd.Timestamp('2026-01-01') and pd.Timestamp(md['accepted_datetime'])<pd.Timestamp('2026-01-01',tz='UTC'),
        'EXACT_ORIGINAL_PRE2026_ISSUER_FILING_CLOCK_REQUIRED')
    _causal_pin(interface,_held_ref(facts['historical_SEC_metadata_ref']))
    url='https://www.sec.gov/Archives/edgar/data/'+str(md['cik'])+'/'+md['adsh'].replace('-','')+'/'+md['instance']
    capture=interface.read(_causal_pin(interface,_held_ref(facts['issuer_capture_ref'])))
    _causal_need(capture['url']==url and capture['actual_url']==url and capture['http_status']==200
        and _held_ref(capture['original_ref'])==_held_ref(facts['issuer_primary_original_ref']),'EXACT_ISSUER_PRIMARY_METADATA_AND_ORIGINAL_REQUIRED')
    for item in facts['existing_dataset_refs']:_causal_pin(interface,_held_ref(item['ref']))
    _causal_need(len(facts['original_uid_rows'])>=2 and len({r['source_row_content_sha256'] for r in facts['original_uid_rows']})==len(facts['original_uid_rows']),
        'UNIQUE_ORIGINAL_PUBLIC_COMMON_ROWS_REQUIRED')
    reports={r['ACCESSION_NUMBER']:r for r in facts['existing_reported_13F_submission_rows']}
    evidence=facts['existing_reported_13F_identity_rows'];rows=[]
    for item in facts['original_uid_rows']:
        row=deepcopy(item['source_row'])
        for field in ('effective_start','effective_end'):row[field]=pd.Timestamp(row[field])
        _causal_need(set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS) and content_hash(row)==item['source_row_content_sha256'] and row['effective_start']<=row['effective_end']<pd.Timestamp('2026-01-01')
            and row['mapping_status']=='RESOLVED' and row['security_id_type']=='CUSIP' and row['security_id']==row['cusip']
            and row['moomoo_transport_code']=='US.'+row['ticker'],'EXACT_ORIGINAL_PUBLIC_COMMON_UID_ROW_REQUIRED')
        match=[r for r in evidence if r['ACCESSION_NUMBER']==row['source_filing'] and r['CUSIP']==row['cusip']]
        _causal_need(len(match)==1 and match[0]['SSHPRNAMTTYPE']=='SH' and match[0]['PUTCALL'] is None
            and match[0]['TITLEOFCLASS']==row['title_of_class'] and match[0]['NAMEOFISSUER']==row['issuer_name']
            and row['source_filing'] in reports,'INDEPENDENT_EXACT_REPORTED_CLASS_CUSIP_SH_ROW_REQUIRED')
        rows.append((row,item['source_row_content_sha256'],pd.to_datetime(reports[row['source_filing']]['FILING_DATE'],format='%d-%b-%Y')))
    past_ref=value.get('historical_original_uid_metadata_projection_ref')
    past_rows=()
    if past_ref is not None:
        past_ref=_held_ref(past_ref);past=interface.read(_causal_pin(interface,past_ref))
        _causal_need(past.get('status')=='SOURCE_METADATA_ONLY_NOT_HELD_OR_ACCOUNT_QUALIFICATION'
            and _held_ref(past['original_UID_ref'])==_held_ref(uid_ref)
            and tuple(past['columns'])==tuple(FrozenHeldSourceGuards.IDENTITY_COLUMNS)
            and past.get('future_UID_start_rows_not_materialized') is True and past.get('future_H_not_read') is True
            and len(past['original_rows'])==past['projected_count'], 'EXACT_BOUNDED_ORIGINAL_UID_METADATA_PROJECTION_REQUIRED')
        prepared=[]
        for entry in past['original_rows']:
            row=deepcopy(entry['source_row'])
            for k in ('effective_start','effective_end'):row[k]=pd.Timestamp(row[k])
            _causal_need(set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS)
                and content_hash(row)==entry['source_row_content_sha256']
                and row['effective_start']<=row['effective_end']<pd.Timestamp('2026-01-01'),
                'EXACT_ORIGINAL_PAST_UID_ROW_COMMITMENT_REQUIRED')
            prepared.append(row)
        _causal_need(len({content_hash(r) for r in prepared})==len(prepared), 'UNIQUE_ORIGINAL_PAST_UID_ROWS_REQUIRED')
        past_rows=tuple(prepared)
    old,old_hash,old_filed=rows[0];out=[]
    norm=lambda s:re.sub(r'[\s.,]+','',s).casefold()
    _causal_need(norm(old['issuer_name'])==norm(facts['issuer_public_parent_predecessor']) and old['title_of_class']=='COM CL A','ORIGINAL_PUBLIC_CLASS_A_SEED_DESCRIPTOR_REQUIRED')
    old_identity=_held_identity(dict(old,share_class=old['title_of_class'],raw_code=old['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
    for now,now_hash,now_filed in rows[1:]:
        current=_held_identity(dict(now,share_class=now['title_of_class'],raw_code=now['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
        _causal_need(norm(now['issuer_name'])==norm(facts['issuer_public_parent_current']) and now['title_of_class']=='Common Stock'
            and old['ticker']==now['ticker'] and all(old_identity[k]==current[k] for k in old_identity if k!='share_class')
            and now_filed<now['effective_start'] and old_filed<old['effective_end'],'EXACT_CURRENT_PUBLIC_COMMON_REPORTED_METADATA_REQUIRED')
        out.append(dict(source_ref=_held_ref(reference),facts_ref=facts_ref,old_row=old,new_row=now,old_row_hash=old_hash,new_row_hash=now_hash,
            old_identity=old_identity,new_identity=current,original_uid_intervals_ref=_held_ref(uid_ref),post_action_existing_public_class_a_metadata=True,
            required_source_filing_days=(old_filed,now_filed,pd.Timestamp(md['filed_date'])),quantity_effect=False,typed_CA_event=False,
            historical_original_uid_metadata_projection_ref=past_ref, historical_original_uid_metadata_rows=past_rows,
            actual_mechanism_continuity_diagnostic_ref=_held_ref(value['actual_mechanism_continuity_diagnostic_ref'])))
    return tuple(out)


def _held_post_action_public_class_a_past_row(row,item,bindings,identity,day):
    """Past original descriptors, only under the exact current actual-H role."""
    import re
    if item.get('post_action_existing_public_class_a_metadata') is not True:
        return False
    source=next((b for b in bindings if b.get('binding_scope')=='POST_ACTION_PUBLIC_CLASS_A_EXISTING_ACCEPTED_HELD'
        and b.get('transport_source_ref')==item['source_ref'] and b.get('historical_sources_candidate_ref')==item['facts_ref']
        and b.get('seed_source_row_identity')==item['old_row_hash'] and b.get('new_source_row_identity')==item['new_row_hash']
        and b.get('current_identity')==identity and b.get('source_filings_completed_before_current_day') is True
        and b.get('decision_session')==_held_session(day)),None)
    if source is None or item.get('historical_original_uid_metadata_projection_ref') is None:
        return False
    norm=lambda s:re.sub(r'[\s.,]+','',s).casefold()
    return (content_hash(row) in {content_hash(r) for r in item.get('historical_original_uid_metadata_rows',())}
        and set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS) and row['mapping_status']=='RESOLVED'
        and row['ticker']==item['old_row']['ticker'] and row['title_of_class']==item['old_identity']['share_class']
        and _held_source_row_descriptor_bridge(row,item['old_identity'],())
        and norm(row['issuer_name']) in {norm(item['old_row']['issuer_name']),norm(item['new_row']['issuer_name'])}
        and pd.Timestamp(row['effective_start'])<=pd.Timestamp(row['effective_end'])<item['new_row']['effective_start']
        and item['new_row']['effective_start']<=pd.Timestamp(day)<=item['new_row']['effective_end']
        and all(pd.Timestamp(d)<pd.Timestamp(day) for d in item['required_source_filing_days']))


def _held_post_action_public_class_a_metadata_binding(item,seed,identity,day,held_spell):
    """Only an actual accepted positive raw position at this current original UID."""
    from copy import deepcopy
    day=_held_session(day);row=item['new_row']
    if (not row['effective_start']<=pd.Timestamp(day)<=row['effective_end']
            or any(not pd.Timestamp(filed)<pd.Timestamp(day) for filed in item['required_source_filing_days'])
            or not isinstance(held_spell,dict) or held_spell.get('role')!='ACCEPTED_POSITION'
            or held_spell.get('seed')!=seed or not isinstance(held_spell.get('position_id'),str)
            or not _held_session(seed['signal_session'])<_held_session(held_spell['seed_admitted_at'])<=day):return None
    q=held_spell.get('committed_prior_raw_quantity');binding=held_spell.get('prior_quantity_binding')
    if (q is None or not isinstance(binding,dict) or not _held_quantity(q)>0
            or binding.get('stage')!='DECISION_CLOSE_RAW_ACTUAL_SHARE'
            or not isinstance(binding.get('account_id'),str) or not binding['account_id']
            or not isinstance(binding.get('owner_ref'),dict)
            or not _held_equal(binding.get('raw_quantity'),q) or _held_session(binding['session'])>=day):return None
    _held_ref(binding['owner_ref'])
    return dict(role='SOURCE_IDENTITY_METADATA_TRANSPORT_NO_QUANTITY_EFFECT',binding_scope='POST_ACTION_PUBLIC_CLASS_A_EXISTING_ACCEPTED_HELD',
        decision_session=day,ticker=item['old_row']['ticker'],old_identity=deepcopy(item['old_identity']),current_identity=deepcopy(item['new_identity']),
        seed_source_ref=deepcopy(item['original_uid_intervals_ref']),seed_source_row_identity=item['old_row_hash'],
        seed_signal_session=_held_session(seed['signal_session']),seed_historical_source_epoch=seed['historical_source_epoch'],
        transport_source_ref=deepcopy(item['source_ref']),historical_sources_candidate_ref=deepcopy(item['facts_ref']),new_source_row_identity=item['new_row_hash'],
        metadata_effective_start=str(row['effective_start'].date()),metadata_effective_end=str(row['effective_end'].date()),
        source_filings_completed_before_current_day=True,pre_action_held_position_id=held_spell['position_id'],
        actual_prior_raw_unit_binding=deepcopy(binding),diagnostic_continuity_ref_digest_only=deepcopy(item['actual_mechanism_continuity_diagnostic_ref']),
        original_action_ref=None,certificate_effective_date='UNKNOWN',quantity_effect=False,typed_CA_event=False,
        historical_observations_relabelled=False,historical_availability_qualified=False,strict_PIT=False)


def _load_pre_action_class_a_seed_extension(interface, reference, value, uid_ref, event_ref):
    """Extend one V2 source relation to an exact old seed; the own share chain admits use."""
    from copy import deepcopy
    _causal_need(value.get('schema')=='B_SOURCE_BOUND_PRE_ACTION_CLASS_A_SEED_EXTENSION_V1'
        and value.get('status')=='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION'
        and value.get('rule')==DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
        and value.get('relation_role')=='EXACT_PRE_ACTION_IMMUTABLE_SEED_TO_EXISTING_POST_SPLIT_CLASS_A_SOURCE_RELATION'
        and _held_ref(value['original_uid_intervals_ref'])==_held_ref(uid_ref)
        and _held_ref(value['original_event_binding_ref'])==_held_ref(event_ref)
        and value.get('historical_original_archive_vintage')=='UNKNOWN'
        and all(value.get(k) is False for k in ('quantity_effect','typed_CA_event','historical_observations_relabelled',
            'historical_availability_qualified','strict_PIT','production_qualified','quote_qualified','certified_NAV',
            'BUY_permission','pool_interval_extension')),
        'EXACT_PRE_ACTION_CLASS_A_SEED_EXTENSION_REQUIRED')
    parent_ref=_held_ref(value['existing_post_action_transport_ref'])
    parent_value=interface.read(_causal_pin(interface,parent_ref))
    _causal_need(parent_value.get('schema')=='B_SOURCE_BOUND_DELAYED_COMMON_CLASS_IDENTITY_METADATA_TRANSPORT_V2',
        'EXISTING_V2_POST_ACTION_CLASS_A_SOURCE_OWNER_REQUIRED')
    parents=_load_delayed_identity_metadata_transport(interface,parent_ref,uid_ref,event_ref)
    _causal_need(len(parents)==1,'ONE_EXISTING_POST_ACTION_CLASS_A_SOURCE_RELATION_REQUIRED')
    parent=parents[0]
    bridge_ref=_held_ref(value['share_class_descriptor_bridge_ref'])
    bridges=_load_share_class_descriptor_bridge(interface,bridge_ref,uid_ref)
    _causal_need(len(bridges)==1,'ONE_EXACT_PRE_ACTION_DESCRIPTOR_BRIDGE_REQUIRED')
    bridge=bridges[0];entry=value['original_pre_action_seed_row'];row=deepcopy(entry['source_row'])
    row['effective_start']=pd.Timestamp(row['effective_start']);row['effective_end']=pd.Timestamp(row['effective_end'])
    _held_session(row['effective_start']);_held_session(row['effective_end'])
    old=_held_identity(entry['identity'])
    observed=_held_identity(dict(row,share_class=row['title_of_class'],raw_code=row['moomoo_transport_code'],
        raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
    row_hash=content_hash(row);post=parent['post_split_trading_session']
    _causal_need(set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS)
        and row_hash==entry['source_row_content_sha256'] and old==observed
        and row['mapping_status']=='RESOLVED' and row['ticker']==parent['old_row']['ticker']
        and row['effective_start']<pd.Timestamp(post)<=row['effective_end']<parent['old_row']['effective_start']
        and row['source_filing'] and set(bridge['row_hashes'])=={row_hash,parent['old_row_hash']}
        and _held_security_identity_equal(old,parent['old_identity'],bridges)
        and old!=parent['old_identity'] and old['cusip']!=parent['new_identity']['cusip'],
        'EXACT_IMMUTABLE_PRE_ACTION_SEED_AND_POST_ACTION_DESCRIPTOR_ROWS_REQUIRED')
    facts=interface.read(_causal_pin(interface,parent['facts_ref']))
    typed=deepcopy(facts['original_share_event'])
    # V2 already validates source/typed roles and ratio.  Runtime still requires
    # this account's exact processed typed fingerprint, position and quantities.
    _causal_need(typed['event_date']==post and typed['ticker']==row['ticker']
        and all(typed[k]==parent['original_event'][k] for k in
            ('ticker','event_date','status','quantity_multiplier','source_fingerprint')),
        'EXISTING_SOURCE_AND_TYPED_CLASS_A_SHARE_ACTION_REQUIRED')
    owner_ref=_held_ref(value['account_owner_ref']);_causal_pin(interface,owner_ref)
    result=deepcopy(parent)
    result.update(source_ref=_held_ref(reference),old_identity=old,old_row=row,old_row_hash=row_hash,
        original_event=typed,original_source_event=deepcopy(parent['original_event']),account_owner_ref=owner_ref,
        existing_post_action_transport_ref=parent_ref,share_class_descriptor_bridge_ref=bridge_ref,
        exact_pre_action_historical_rows=deepcopy(bridge['original_rows']),
        pre_action_existing_held=True,pre_action_class_a_seed_extension=True)
    return (result,)


def _load_issuer_bound_held_accounting_source(interface, reference, value, uid_ref, event_ref):
    """Exact issuer evidence for an own-H label; never a pool UID or risk alias."""
    from copy import deepcopy
    from scripts.storage.refresh_sec_event_originals import parse_original, FilingText
    _causal_need(value.get('schema')=='B_MKFG_ISSUER_BOUND_OWN_HELD_ACCOUNTING_COORDINATE_SOURCE_V1'
        and value.get('status')=='DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION'
        and value.get('scope')=='ORIGINAL_OWN_HELD_IMMUTABLE_SEED_AND_SOURCE_BOUND_POST_SPLIT_ACCOUNTING_LABEL_ONLY'
        and _held_ref(value['original_uid_intervals_ref'])==_held_ref(uid_ref)
        and _held_ref(value['original_event_binding_ref'])==_held_ref(event_ref)
        and value.get('original_research_fractional_contract_unchanged') is True
        and all(value.get(k) is False for k in ('new_UID_pool_row','BUY_permission','risk_identity_alias',
            'quantity_effect','issuer_roundup_applied','broker_nominee_actual_quantity_certified',
            'historical_observations_relabelled','historical_availability_qualified','strict_PIT',
            'production_qualified','quote_qualified','certified_NAV')),
        'EXPLICIT_ISSUER_BOUND_OWN_HELD_ACCOUNTING_SOURCE_REQUIRED')
    subject=value['subject']
    _causal_need(subject==dict(ticker='MKFG',issuer_CIK=1816613,old_CUSIP='57064N102',new_CUSIP='57064N201',
        share_class='Common Stock',raw_code='US.MKFG',original_issuer='Markforged Holding Corp',
        public_issuer='Markforged Holding Corporation'),'EXACT_MKFG_COMMON_ISSUER_ACCOUNTING_SUBJECT_REQUIRED')
    facts_ref=_held_ref(value['split_only_facts_ref']);facts=interface.read(_causal_pin(interface,facts_ref))
    _causal_need(facts.get('schema')=='B_MKFG_2024_SPLIT_ONLY_ORIGINAL_SOURCE_FACTS_V1'
        and facts.get('date_scope_stop_exclusive')=='2025-01-01'
        and facts.get('original_research_fractional_contract_unchanged') is True
        and facts.get('issuer_roundup_applied') is False,'EXACT_PRE_ACTION_SPLIT_ONLY_SOURCE_FACTS_REQUIRED')
    header=facts['header'];original_ref=_held_ref(header['original_ref']);original=Path(_causal_pin(interface,original_ref))
    _causal_need(original_ref['sha256']=='7c3ac5071b586b9e16983130fcd7fd987d3fa987c3130292e26ed923d0f6c0a1',
        'EXACT_ALREADY_CAPTURED_PRE2026_MKFG_SPLIT_ORIGINAL_REQUIRED')
    with original.open('rb') as stream:
        prefix=b''
        while b'<DOCUMENT>' not in prefix and len(prefix)<=65536:
            line=stream.readline()
            if not line:break
            prefix+=line
        _causal_need(b'20240909' in prefix and b'20240909161605' in prefix and b'<DOCUMENT>' in prefix
            and len(prefix)<=65536,'EXACT_PRE2026_SPLIT_HEADER_BEFORE_BODY_REQUIRED')
        payload=prefix+stream.read()
    raw=dict(sha256=original_ref['sha256'],local_path=str(original),source_reference=header['source_url'],retrieval_timestamp_utc=header['retrieved_at_utc'])
    row=dict(cik=1816613,accession='0000950170-24-104750',form='8-K',filed_date='20240909',role='EARNINGS',url=header['source_url'],primary_document='mkfg-20240909.htm')
    metadata,_=parse_original(payload,row,raw);known=pd.Timestamp(metadata['accepted_at_utc'])
    _causal_need(metadata['accepted_source_raw']=='20240909161605' and known==pd.Timestamp('2024-09-09T20:16:05Z')
        and known<pd.Timestamp('2024-09-19T04:01:00Z'),'EXACT_SOURCE_SPLIT_PUBLICATION_BEFORE_EFFECT_REQUIRED')
    texts={}
    for f in facts['fragments']:
        a,b=f['original_byte_range'];_causal_need(type(a) is int and type(b) is int and 0<=a<b<=len(payload) and b-a<=32768,'EXACT_BOUNDED_SPLIT_SOURCE_FRAGMENT_REQUIRED')
        saved=Path(_causal_pin(interface,_held_ref(f['raw_fragment_ref']))).read_bytes();parser=FilingText();parser.feed(saved.decode('utf-8',errors='replace'));text=' '.join(' '.join(parser.parts).split())
        _causal_need(_held_ref(f['original_ref'])==original_ref and payload[a:b]==saved and text==f['visible_text']
            and content_hash(text)==f['text_typed_content_sha256'],'UNCHANGED_ORIGINAL_SPLIT_FRAGMENT_REQUIRED')
        texts[f['role']]=text
    _causal_need(all(t in texts['SPLIT_SAME_COMMON_RATIO_EFFECTIVE'] for t in ('1-for-10','Common Stock','12:01','September 19, 2024'))
        and all(t in texts['SPLIT_COMMON_NEW_CUSIP_AND_TICKER'] for t in ('57064N201','MKFG','Common Stock'))
        and all(t in texts['SPLIT_FRACTIONAL_WHOLE_SHARE_TERM'] for t in ('No fractional shares','whole number of shares')),
        'EXACT_COMMON_SPLIT_CUSIP_AND_UNAPPLIED_ROUNDUP_TERMS_REQUIRED')
    entries=value['original_uid_rows'];rows=[]
    old=dict(security_id='57064N102',security_id_type='CUSIP',cusip='57064N102',share_class='Common Stock',raw_code='US.MKFG',raw_actual_share_coordinate='RAW_ACTUAL_SHARE')
    for entry in entries:
        row=deepcopy(entry['source_row']);row['effective_start']=pd.Timestamp(row['effective_start']);row['effective_end']=pd.Timestamp(row['effective_end'])
        _causal_need(set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS) and content_hash(row)==entry['source_row_content_sha256']
            and row['mapping_status']=='RESOLVED' and row['ticker']=='MKFG' and row['issuer_name']==subject['original_issuer']
            and row['effective_start']<=row['effective_end']<pd.Timestamp('2024-09-19') and _held_identity(entry['identity'])==old
            and _held_identity(dict(row,share_class=row['title_of_class'],raw_code=row['moomoo_transport_code'],raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))==old,
            'EXACT_UNCHANGED_OLD_LEGAL_HELD_SEED_SOURCE_ROWS_REQUIRED')
        rows.append(row)
    _causal_need(bool(rows) and len({content_hash(r) for r in rows})==len(rows),'UNIQUE_ORIGINAL_OLD_HELD_SOURCE_ROWS_REQUIRED')
    _causal_pin(interface,_held_ref(event_ref));obj_ref=_held_ref(value['original_source_event_object_ref'])
    obj=Path(_causal_pin(interface,obj_ref)).read_bytes();a,b=value['original_source_event_byte_range']
    _causal_need(type(a) is int and type(b) is int and 0<=a<b and b-a==len(obj)<=4096,'EXACT_SOURCE_EVENT_OBJECT_RANGE_REQUIRED')
    with Path(event_ref['path']).open('rb') as stream:stream.seek(a);parent=stream.read(b-a)
    _causal_need(parent==obj and b'"2024-09-19"' in obj,'EXACT_ORIGINAL_PRE2026_SHARE_OBJECT_REQUIRED')
    event=json.loads(obj)
    _causal_need(event['ticker']=='MKFG' and event['event_date']=='2024-09-19' and event['status']=='SHARE_ONLY_SUPPORTED'
        and _held_equal(event['quantity_multiplier'],.1)
        and event['source_fingerprint']=='aaed1d8d6f38463303413f22256579f9fe80814bf690be24a77b4e8883c158d0'
        and event['event_fingerprint']=='1629807d873a24c7f3c99806351ee6fcf35bf4fbc861783b6239beadd8da7fc0',
        'EXACT_ORIGINAL_MKFG_SHARE_SOURCE_NOT_NEW_QUANTITY_EVENT_REQUIRED')
    owner_ref=_held_ref(value['account_owner_ref']);_causal_pin(interface,owner_ref)
    return (dict(source_ref=_held_ref(reference),facts_ref=facts_ref,original_uid_intervals_ref=_held_ref(uid_ref),
        original_event_binding_ref=_held_ref(event_ref),account_owner_ref=owner_ref,original_source_event=event,
        source_available_at=known.isoformat(),post_split_trading_session='2024-09-19',old_identity=old,
        old_row=rows[0],old_row_hash=content_hash(rows[0]),original_seed_row_hashes=tuple(content_hash(r) for r in rows),
        public_current_CUSIP='57064N201',issuer_bound_held_accounting_coordinate_only=True,
        broker_nominee_actual_quantity_certified=False),)


def _load_delayed_identity_metadata_transport(interface, reference, uid_intervals_ref, event_binding_ref):
    """Declared current-position metadata evidence; no quantity or historical UID alias."""
    from copy import deepcopy
    reference = _held_ref(reference)
    value = interface.read(_causal_pin(interface, reference))
    if value.get('schema')=='B_MKFG_ISSUER_BOUND_OWN_HELD_ACCOUNTING_COORDINATE_SOURCE_V1':
        return _load_issuer_bound_held_accounting_source(interface,reference,value,uid_intervals_ref,event_binding_ref)
    if value.get('schema')=='B_SOURCE_BOUND_PRE_ACTION_CLASS_A_SEED_EXTENSION_V1':
        return _load_pre_action_class_a_seed_extension(interface,reference,value,uid_intervals_ref,event_binding_ref)
    if value.get('schema')=='B_SOURCE_BOUND_POST_ACTION_PUBLIC_CLASS_A_HELD_METADATA_INPUT_V1':
        return _load_post_action_public_class_a_metadata_transport(interface,reference,value,uid_intervals_ref)
    if value.get('schema')=='B_SOURCE_BOUND_PRE_ACTION_EXISTING_HELD_IDENTITY_METADATA_TRANSPORT_V1':
        return _load_pre_action_existing_held_identity_metadata_transport(interface,reference,value,uid_intervals_ref,event_binding_ref)
    _causal_need(value.get('schema') in ('B_SOURCE_BOUND_DELAYED_IDENTITY_METADATA_TRANSPORT_V1',
        'B_SOURCE_BOUND_DELAYED_COMMON_CLASS_IDENTITY_METADATA_TRANSPORT_V2')
        and value.get('status') == 'DECLARED_SOURCE_INPUT_NOT_RUNTIME_ADMISSION'
        and value.get('rule') == DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
        and value.get('relation_role') == 'SAME_ISSUED_AND_OUTSTANDING_COMMON_STOCK_OLD_13F_AND_NEW_ISSUER_SOURCE'
        and value.get('historical_original_archive_vintage') == 'UNKNOWN'
        and all(value.get(k) is False for k in
            ('strict_PIT', 'quantity_effect', 'typed_CA_event', 'historical_observations_relabelled')),
        'EXACT_DECLARED_ZERO_QUANTITY_IDENTITY_METADATA_INPUT_REQUIRED')
    uid_ref = _held_ref(uid_intervals_ref); event_ref = _held_ref(event_binding_ref)
    _causal_need(_held_ref(value['original_uid_intervals_ref']) == uid_ref
        and _held_ref(value['original_event_binding_ref']) == event_ref,
        'EXACT_UNCHANGED_IDENTITY_AND_EVENT_SOURCES_REQUIRED')
    facts_ref = _held_ref(value['historical_sources_candidate_ref'])
    facts = interface.read(_causal_pin(interface, facts_ref))
    class_a = facts.get('schema') == 'B_HISTORICAL_SOURCE_BACKED_COMMON_CLASS_CUSIP_TRANSITION_CANDIDATE_V2'
    share_fragment = facts.get('issuer_share_terms_fragment',{}) if class_a else facts.get('issuer_EX99_1_fragment',{})
    if class_a:
        _causal_need(value.get('schema') == 'B_SOURCE_BOUND_DELAYED_COMMON_CLASS_IDENTITY_METADATA_TRANSPORT_V2'
            and facts.get('common_share_class_binding') == dict(
            schema='B_EXPLICIT_ISSUER_COMMON_SHARE_CLASS_SOURCE_BINDING_V1',
            scope='SAME_ISSUED_AND_OUTSTANDING_CLASS_A_COMMON_STOCK_POST_SPLIT_ONLY',
            issuer_common_class_literal='Class A common stock',
            prior_manager_class_literal=facts.get('old_source_common_class_literal'),
            current_frozen_metadata_class_literal=facts.get('current_frozen_metadata_class_literal'),
            preferred_or_special_class=False)
            and facts.get('delayed_old_interval_role') == 'ORIGINAL_METADATA_INTERVAL_ALREADY_POST_SPLIT'
            and facts.get('new_source_common_class_literal') == 'Class A common stock'
            and share_fragment.get('document_role') == 'ORIGINAL_ISSUER_SEC_8K_ITEM8_01'
            and 'Class A common stock' in share_fragment.get('text','')
            and isinstance(facts.get('new_cusip'),str) and facts['new_cusip'] in share_fragment.get('text','')
            and all(facts.get(k) is False for k in
                ('strict_PIT','production_qualified','quote_qualified','certified_NAV')),
            'EXPLICIT_SAME_CLASS_A_COMMON_POST_SPLIT_SOURCE_BINDING_REQUIRED')
    _causal_need((class_a or (facts.get('schema') == 'B_HISTORICAL_SOURCE_BACKED_COMMON_CUSIP_TRANSITION_CANDIDATE_V1'
        and value.get('schema') == 'B_SOURCE_BOUND_DELAYED_IDENTITY_METADATA_TRANSPORT_V1'))
        and facts.get('status') == ('PRIMARY_CLASS_A_POST_SPLIT_CUSIP_AND_PRIOR_FROZEN_CLASS_A_IDENTITY_SOURCE_READY_FOR_OWNER_ADJUDICATION' if class_a
            else 'PRIMARY_SAME_COMMON_POST_SPLIT_CUSIP_AND_PRIOR_FROZEN_COMMON_IDENTITY_SOURCE_READY_FOR_OWNER_ADJUDICATION')
        and facts.get('old_CUSIP_source_role') == 'EXPLICIT_OLD_LITERAL_IN_ORIGINAL_PINNED_PRIOR_MANAGER_SEC_INFORMATION_TABLE'
        and facts.get('new_CUSIP_source_role') == ('EXPLICIT_NEW_LITERAL_IN_ISSUER_SEC_8K_ITEM8_01_FOR_SAME_ISSUED_AND_OUTSTANDING_CLASS_A_COMMON_STOCK' if class_a
            else 'EXPLICIT_NEW_LITERAL_IN_ISSUER_SEC_8K_AND_ORIGINAL_ISSUER_EX99_1_FOR_SAME_ISSUED_AND_OUTSTANDING_COMMON_STOCK')
        and facts['original_prior_manager_source_identity'].get('source_role') == ('ORIGINAL_FROZEN_MANAGER_13F_CLASS_A_SECURITY_IDENTITY' if class_a
            else 'ORIGINAL_PRIOR_FROZEN_MANAGER_13F_COMMON_SECURITY_IDENTITY')
        and facts.get('one_primary_document_prints_both_CUSIPs') is False
        and (facts['old_cusip'] not in share_fragment['text'] if class_a
             else facts.get('primary_8K_old_CUSIP_literal_match_count') == 0)
        and facts['availability_scope'].get('historical_original_archive_vintage') == 'UNKNOWN'
        and facts['availability_scope'].get('historical_PIT_not_granted') is True
        and facts['quantity_scope'].get('do_not_multiply_current_holding_or_buy_again' if class_a
            else 'do_not_multiply_current_holding_again') is True
        and facts['quantity_scope'].get('no_NEW_quantity_effect_or_CA_engine') is True
        and facts.get('strict_PIT') is False,
        'DISTINCT_ORIGINAL_OLD_AND_NEW_COMMON_SOURCE_ROLES_REQUIRED')
    # Pin original and projected sources; decode only the supplied identity facts.
    for artifact in facts['source_refs']:
        _causal_pin(interface, _held_ref(artifact))
    entries=value['original_rows']; normalized=[]; identities=[]
    _causal_need(len(entries)==2, 'EXACT_TWO_UNCHANGED_CUSIP_ROWS_REQUIRED')
    for entry in entries:
        row=deepcopy(entry['source_row'])
        _causal_need(set(row)==set(FrozenHeldSourceGuards.IDENTITY_COLUMNS),
            'EXACT_ORIGINAL_IDENTITY_METADATA_FIELDS_REQUIRED')
        row['effective_start']=pd.Timestamp(row['effective_start'])
        row['effective_end']=pd.Timestamp(row['effective_end'])
        _held_session(row['effective_start']); _held_session(row['effective_end'])
        identity=_held_identity(entry['identity'])
        observed=_held_identity(dict(row, share_class=row['title_of_class'],
            raw_code=row['moomoo_transport_code'], raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
        _causal_need(row['mapping_status']=='RESOLVED'
            and row['effective_start']<=row['effective_end']
            and content_hash(row)==entry['source_row_content_sha256']
            and identity==observed and identity['security_id_type']=='CUSIP',
            'EXACT_UNCHANGED_ORIGINAL_CUSIP_ROW_AND_IDENTITY_REQUIRED')
        normalized.append(row);identities.append(identity)
    old,new=identities; before,after=normalized
    prior=facts['original_prior_manager_source_identity']['identity_projection']
    if class_a:
        fact_rows=facts['original_rows']
        _causal_need(len(fact_rows)==2 and _held_ref(facts['existing_pinned_interval_ref'])==uid_ref
            and all(entry['source_row_content_sha256']==fact['source_row_content_sha256']
                and entry['identity']==fact['identity'] for entry,fact in zip(entries,fact_rows)),
            'EXACT_ORIGINAL_CLASS_A_METADATA_ROWS_AND_SOURCE_REF_REQUIRED')
        context=dict(old_row_hash=fact_rows[0]['source_row_content_sha256'],
            new_row_hash=fact_rows[1]['source_row_content_sha256'],
            old_source_filing=fact_rows[0]['source_row']['source_filing'],
            new_source_filing=fact_rows[1]['source_row']['source_filing'])
        current=facts['original_current_manager_source_identity']
        _causal_need(current.get('source_role')=='ORIGINAL_FROZEN_MANAGER_13F_CLASS_A_SECURITY_IDENTITY'
            and current['identity_projection']==dict(nameOfIssuer=after['issuer_name'],
                titleOfClass=after['title_of_class'],cusip=new['cusip']),
            'EXACT_CURRENT_MANAGER_CLASS_A_SOURCE_IDENTITY_REQUIRED')
        source_refs=[_held_ref(r) for r in facts['source_refs']]
        _causal_need(all(_held_ref(r['source_ref']) in source_refs for r in
            (facts['original_prior_manager_source_identity'],current)),
            'BOTH_ORIGINAL_MANAGER_CLASS_A_DOCUMENTS_MUST_BE_PINNED')
        for fragment in (share_fragment,facts['issuer_effective_date_fragment']):
            raw_ref=_held_ref(fragment['raw_fragment_ref'])
            _causal_need(_held_ref(fragment['original_source_ref']) in source_refs
                and raw_ref['sha256']==fragment['original_substring_sha256'],
                'EXACT_ORIGINAL_ISSUER_FRAGMENT_CUSTODY_REQUIRED')
            _causal_pin(interface,raw_ref);_causal_pin(interface,_held_ref(fragment['text_projection_ref']))
    else:
        context=facts['existing_owner_identity_metadata_context']
    _causal_need(before['ticker']==after['ticker']==facts['ticker']
        and before['issuer_name']==after['issuer_name']==prior['nameOfIssuer']
        and before['title_of_class']==prior['titleOfClass']==facts['old_source_common_class_literal']
        and (class_a or before['title_of_class']=='COM')
        and after['title_of_class']==facts['current_frozen_metadata_class_literal']
        and facts['new_source_common_class_literal']==('Class A common stock' if class_a else 'common stock')
        and old['cusip']==facts['old_cusip']==prior['cusip']
        and new['cusip']==facts['new_cusip'] and old['cusip']!=new['cusip']
        and old['raw_code']==new['raw_code']=='US.'+before['ticker']
        and before['effective_end']<after['effective_start']
        and content_hash(before)==context['old_row_hash']
        and content_hash(after)==context['new_row_hash']
        and before['source_filing']==context['old_source_filing']
        and after['source_filing']==context['new_source_filing'],
        'EXACT_SOURCE_BOUND_SAME_COMMON_OLD_AND_NEW_ROW_RELATION_REQUIRED')
    post=_held_session(value['post_split_trading_session'])
    filed=_held_session(value['source_filing_day'])
    if class_a:
        effective_day=_held_session(value['split_effective_date'])
        effective_fragment=facts.get('issuer_effective_date_fragment',{})
        _causal_need(value.get('source_effective_clock_authority') == 'DATE_ONLY_NO_TIME_STATED'
            and 'split_effective_at' not in value
            and effective_fragment.get('document_role') == 'ORIGINAL_ISSUER_SEC_8K_ITEM5_03'
            and value.get('source_effective_date_literal') == facts.get('effective_date_literal')
            and isinstance(facts.get('effective_date_literal'),str)
            and facts['effective_date_literal'] in effective_fragment.get('text','')
            and effective_day==facts.get('issuer_effective_date')
            and filed==facts['issuer_filed_as_of_date'] and post==facts['post_split_trading_session']
            and filed<=effective_day<post and pd.Timestamp(post)<=before['effective_start']
            and pd.Timestamp(post)<after['effective_start'],
            'EXACT_SOURCE_DATE_ONLY_PRE_ADMISSION_ACTION_AND_DELAYED_METADATA_REQUIRED')
        effective=None
    else:
        effective=pd.Timestamp(value['split_effective_at'])
        _causal_need(not pd.isna(effective) and effective.tzinfo is not None
            and filed==facts['issuer_filed_as_of_date']
            and post==facts['post_split_trading_session']
            and value['source_effective_time_literal']==facts['effective_time_literal']
            and filed<=str(effective.tz_convert('America/New_York').date())<post
            and before['effective_start']<=pd.Timestamp(filed)
            and pd.Timestamp(post)<after['effective_start'],
            'ORIGINAL_PRE_ADMISSION_ACTION_AND_DELAYED_METADATA_CLOCK_REQUIRED')
    import re
    ratio_literal=facts['quantity_scope']['source_ratio_literal']
    ratio_pattern=r'(?<![0-9])([0-9]+)-for-([0-9]+)(?![0-9])'
    if class_a and ':' in ratio_literal:
        ratio_pattern=r'(?<![0-9])([0-9]+):([0-9]+)(?![0-9])'
    ratio_terms=re.findall(ratio_pattern,ratio_literal)
    _causal_need(len(ratio_terms)==1 and all(int(v)>0 for v in ratio_terms[0])
        and (ratio_literal in share_fragment['text'] if class_a
             else '-for-'.join(ratio_terms[0]) in share_fragment['text']),
        'EXACT_ORIGINAL_COMMON_SHARE_RATIO_SOURCE_LITERAL_REQUIRED')
    source_ratio=int(ratio_terms[0][0])/int(ratio_terms[0][1])
    event=value['original_event']; fields=('ticker','event_date','status','quantity_multiplier','event_fingerprint','source_fingerprint')
    if class_a:
        # The parent may contain mixed-period fields. Pin opaque bytes only;
        # semantic reads use the separately pinned exact pre-2026 projection.
        _causal_pin(interface,event_ref)
        projection_ref=_held_ref(value['original_event_pre2026_projection_ref'])
        original=interface.read(_causal_pin(interface,projection_ref))
        _causal_need(original.get('schema')=='B_EXACT_ORIGINAL_PRE2026_EVENT_RECORD_PROJECTION_V1'
            and _held_ref(original['original_event_binding_ref'])==event_ref
            and original.get('date_scope')==dict(start='2023-01-01',stop_exclusive='2026-01-01')
            and original.get('new_event_authority') is False
            and all(original.get(k) is False for k in
                ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
            and len(original.get('event_records',()))==1
            and all(set(r)==set(fields) and '2023-01-01'<=_held_session(r['event_date'])<'2026-01-01'
                for r in original['event_records']),
            'EXACT_ORIGINAL_PARENT_BOUND_PRE2026_EVENT_PROJECTION_REQUIRED')
        object_ref=_held_ref(original['original_object_ref'])
        _causal_pin(interface,object_ref)
        byte_range=original.get('original_object_byte_range')
        _causal_need(isinstance(byte_range,list) and len(byte_range)==2
            and all(isinstance(n,int) and not isinstance(n,bool) for n in byte_range)
            and 0<=byte_range[0]<byte_range[1]
            and isinstance(original.get('original_object_bytes'),int)
            and not isinstance(original['original_object_bytes'],bool)
            and original['original_object_bytes']==byte_range[1]-byte_range[0]
            and original.get('original_event_fields')==list(fields),
            'EXACT_ORIGINAL_EVENT_OBJECT_BYTE_RANGE_REQUIRED')
        with Path(event_ref['path']).open('rb') as h:
            h.seek(byte_range[0]); parent_object=h.read(byte_range[1]-byte_range[0])
        object_bytes=Path(object_ref['path']).read_bytes()
        _causal_need(len(parent_object)==original['original_object_bytes']
            and parent_object==object_bytes
            and hashlib.sha256(object_bytes).hexdigest()==object_ref['sha256'],
            'EXACT_PINNED_PARENT_SLICE_MUST_EQUAL_ORIGINAL_EVENT_OBJECT_BYTES')
        try:
            original_object=json.loads(object_bytes)
        except (ValueError,UnicodeError):
            _causal_need(False,'EXACT_ORIGINAL_EVENT_OBJECT_JSON_REQUIRED')
        _causal_need(isinstance(original_object,dict)
            and {k:original_object.get(k) for k in fields}==original['event_records'][0],
            'EXACT_ORIGINAL_EVENT_OBJECT_FIELDS_MUST_EQUAL_PRE2026_PROJECTION')
    else:
        original=interface.read(_causal_pin(interface,event_ref))
    matches=[r for r in original['event_records']
        if {k:r.get(k) for k in fields}==event]
    _causal_need(set(event)==set(fields) and len(matches)==1
        and event['ticker']==before['ticker'] and _held_session(event['event_date'])==post
        and event['status'] in ('SHARE_ONLY_SUPPORTED','FROZEN_TIER1_SHARE_ONLY_SUPPORTED')
        and isinstance(event['quantity_multiplier'],(int,float))
        and not isinstance(event['quantity_multiplier'],bool)
        and np.isfinite(event['quantity_multiplier']) and event['quantity_multiplier']>0
        and _held_equal(event['quantity_multiplier'],source_ratio),
        'EXACT_EXISTING_PRE_ADMISSION_SHARE_ACTION_CORRELATION_REQUIRED')
    if class_a:
        typed_event=facts['original_share_event']
        _causal_need(all(typed_event.get(k)==event[k] for k in fields if k!='event_fingerprint')
            and isinstance(typed_event.get('event_fingerprint'),str) and len(typed_event['event_fingerprint'])==64,
            'ORIGINAL_TYPED_AND_SOURCE_ACTION_ROLES_MUST_RETAIN_SEPARATE_FINGERPRINTS')
    result=dict(source_ref=reference, facts_ref=facts_ref, original_uid_intervals_ref=uid_ref,
        original_event_binding_ref=event_ref, original_event=event,
        old_identity=old,new_identity=new,old_row=before,new_row=after,
        old_row_hash=content_hash(before),new_row_hash=content_hash(after),
        post_split_trading_session=post,source_filing_day=filed,
        historical_availability_qualified=False)
    if class_a:
        result.update(split_effective_date=effective_day,source_effective_clock_authority='DATE_ONLY_NO_TIME_STATED',
            original_event_pre2026_projection_ref=projection_ref)
    else:
        result['split_effective_at']=effective.isoformat()
    return (result,)



def _load_additional_identity_metadata_transports(interface, references, uid_intervals_ref,
                                                  event_binding_ref, existing_transports=()):
    """Append explicit pinned source declarations using the same zero-quantity owner."""
    transports=tuple(existing_transports)
    if references is None:
        return transports
    _causal_need(isinstance(references,list) and bool(references),
        'EXPLICIT_ADDITIONAL_IDENTITY_METADATA_REFERENCE_LIST_REQUIRED')
    seen={item['source_ref']['sha256'] for item in transports}
    relations={(item['old_identity']['raw_code'],item['old_row_hash']) for item in transports}
    for raw in references:
        reference=_held_ref(raw)
        _causal_need(set(raw)=={'path','sha256'} and reference['sha256'] not in seen,
            'UNIQUE_EXACT_ADDITIONAL_IDENTITY_METADATA_INPUT_REFS_REQUIRED')
        extra=_load_delayed_identity_metadata_transport(interface,reference,uid_intervals_ref,event_binding_ref)
        relation=(extra[0]['old_identity']['raw_code'],extra[0]['old_row_hash'])
        _causal_need(relation not in relations,'ONE_SOURCE_BOUND_TRANSITION_PER_ORIGINAL_IDENTITY_ROW_REQUIRED')
        transports+=extra;seen.add(reference['sha256']);relations.add(relation)
    return transports


def _held_pre_action_class_a_past_row(row, item):
    """A pre-action extension admits only its two immutable source rows."""
    return (item.get('pre_action_class_a_seed_extension') is True
        and any(content_hash(row)==content_hash(prior)
                for prior in item['exact_pre_action_historical_rows']))


def _held_identity_metadata_binding(seed, identity, day, transports, *, held_spell=None):
    """Resolve only a declared post-action seed's exact old -> current metadata."""
    from copy import deepcopy
    if not isinstance(seed,dict):
        return None
    for item in transports:
        if (not _held_security_identity_equal(_held_identity(seed),item['old_identity'])
                or seed.get('seed_source_row_identity')!=item['old_row_hash']
                or _held_ref(seed['seed_source_ref'])!=item['original_uid_intervals_ref']):
            continue
        if (not _held_security_identity_equal(identity,item['old_identity'])
                and not _held_security_identity_equal(identity,item['new_identity'])):
            continue
        if item.get('post_action_existing_public_class_a_metadata') is True:
            public_binding=_held_post_action_public_class_a_metadata_binding(item,seed,identity,day,held_spell)
            if public_binding is not None:return public_binding
            continue
        processed_transition=None
        if item.get('pre_action_existing_held') is True:
            if (not isinstance(held_spell,dict) or held_spell.get('role')!='ACCEPTED_POSITION'
                    or not isinstance(held_spell.get('position_id'),str)
                    or held_spell.get('seed')!=seed
                    or not _held_session(seed['signal_session'])<_held_session(held_spell['seed_admitted_at'])<=item['post_split_trading_session']
                    or pd.Timestamp(day)<item['new_row']['effective_start']):
                continue
            event=item['original_event']
            matches=[r for r in held_spell.get('processed_share_transitions',())
                if r.get('event_fingerprint')==event['event_fingerprint']]
            if len(matches)!=1:
                continue
            actual=matches[0]
            if (actual.get('position_id')!=held_spell['position_id'] or actual.get('kind')!='SPLIT'
                    or actual.get('session')!=item['post_split_trading_session']
                    or actual.get('old_identity')!=item['old_identity'] or actual.get('new_identity')!=item['old_identity']
                    or actual.get('source_ref')!=item['original_event_binding_ref']
                    or actual.get('owner_ref')!=item['account_owner_ref']
                    or not _held_quantity(actual['before_raw_quantity'])>0
                    or not _held_equal(actual['after_raw_quantity'],actual['before_raw_quantity']*event['quantity_multiplier'])):
                continue
            processed_transition=dict(actual)
        elif (_held_session(seed['signal_session'])<item['post_split_trading_session']
                or pd.Timestamp(day)<item['new_row']['effective_start']):
            continue
        result=dict(role='SOURCE_IDENTITY_METADATA_TRANSPORT_NO_QUANTITY_EFFECT',
            decision_session=_held_session(day),ticker=item['old_row']['ticker'],
            old_identity=deepcopy(item['old_identity']),current_identity=deepcopy(item['new_identity']),
            seed_source_ref=deepcopy(item['original_uid_intervals_ref']),
            seed_source_row_identity=item['old_row_hash'],
            seed_signal_session=_held_session(seed['signal_session']),
            seed_historical_source_epoch=seed['historical_source_epoch'],
            transport_source_ref=deepcopy(item['source_ref']),historical_sources_candidate_ref=deepcopy(item['facts_ref']),
            new_source_row_identity=item['new_row_hash'],
            metadata_effective_start=str(item['new_row']['effective_start'].date()),
            post_split_trading_session=item['post_split_trading_session'],
            original_action_ref=dict(source_ref=deepcopy(item['original_event_binding_ref']),
                original_event=deepcopy(item['original_event']),
                **({'pre2026_projection_ref':deepcopy(item['original_event_pre2026_projection_ref'])}
                   if 'original_event_pre2026_projection_ref' in item else {})),
            quantity_effect=False,typed_CA_event=False,historical_observations_relabelled=False,
            historical_availability_qualified=False,strict_PIT=False)
        if processed_transition is not None:
            result.update(binding_scope='PRE_ACTION_ACTUAL_EXISTING_HELD_ALREADY_PROCESSED_SHARE_CHAIN',
                actual_processed_share_transition=processed_transition,pre_action_held_position_id=held_spell['position_id'])
        return result
    return None


def _held_metadata_proof_matches_current(proof, identity, guard):
    """The real book's current metadata binding is distinct from its immutable seed."""
    try:
        value=proof['current_identity_metadata_binding']
        source=value['source_binding']
        return (value['account_id']==proof['actual_quantity_binding']['account_id']
            and value['position_id']==proof['position_id']
            and value['decision_session']==proof['decision_session']==source['decision_session']
            and value['raw_quantity_effect']==0
            and value['typed_CA_event'] is False
            and value['historical_observations_relabelled'] is False
            and source in guard['identity_metadata_bindings']
            and source['role']=='SOURCE_IDENTITY_METADATA_TRANSPORT_NO_QUANTITY_EFFECT'
            and source['old_identity']['security_id']==proof['seed_security_id']
            and source['old_identity']['security_id_type']==proof['seed_security_id_type']
            and source['old_identity']['share_class']==proof['seed_share_class']
            and source['seed_source_ref']==proof['seed_source_ref']
            and source['seed_source_row_identity']==proof['seed_source_row_identity']
            and source['current_identity']==_held_identity(identity)
            and ((source.get('binding_scope')=='PRE_ACTION_ACTUAL_EXISTING_HELD_ALREADY_PROCESSED_SHARE_CHAIN'
                and source.get('pre_action_held_position_id')==proof['position_id']
                and source['actual_processed_share_transition']['position_id']==proof['position_id']
                and _held_session(source['seed_signal_session'])<_held_session(proof['seed_admitted_at'])<=_held_session(source['post_split_trading_session'])
                and _held_session(source['post_split_trading_session'])<=_held_session(source['metadata_effective_start']))
                or (source.get('binding_scope') is None
                and _held_session(source['post_split_trading_session'])<=_held_session(proof['seed_admitted_at'])
                and _held_session(source['post_split_trading_session'])<=_held_session(source['seed_signal_session']))
                or (source.get('binding_scope')=='POST_ACTION_PUBLIC_CLASS_A_EXISTING_ACCEPTED_HELD'
                and source.get('pre_action_held_position_id')==proof['position_id']
                and source.get('source_filings_completed_before_current_day') is True
                and source['actual_prior_raw_unit_binding']==proof['prior_quantity_binding']
                and source['actual_prior_raw_unit_binding']['account_id']==proof['actual_quantity_binding']['account_id']
                and source['actual_prior_raw_unit_binding']['owner_ref']==proof['actual_quantity_binding']['owner_ref']
                and _held_quantity(source['actual_prior_raw_unit_binding']['raw_quantity'])>0
                and _held_session(source['actual_prior_raw_unit_binding']['session'])<=_held_session(proof['decision_session'])
                and _held_session(source['metadata_effective_start'])<=_held_session(proof['decision_session'])<=_held_session(source['metadata_effective_end'])))
            and _held_session(source['metadata_effective_start'])<=_held_session(proof['decision_session'])
            and all(source[k] is False for k in ('quantity_effect','typed_CA_event',
                'historical_observations_relabelled','historical_availability_qualified','strict_PIT'))
            and bool(_held_ref(source['transport_source_ref']))
            and bool(_held_ref(source['historical_sources_candidate_ref'])))
    except (KeyError,TypeError,ValueError,HeldLineageUnavailable):
        return False


class HeldPositionLineageBook:
    """Pure per-account admitted-position lineage, independent of entry features.

    No I/O, price/NAV arithmetic, source discovery, CA execution or identity master.
    Supplied guards must be made by the accepted source/typed lifecycle owner.
    A guard is scoped to the decision session and the interval since the previous
    successful check. Historical source epochs remain historical observations;
    this book does not turn a feature gap into an observed-UID epoch.
    """

    PROOF_FIELDS = (
        "decision_session", "position_id", "ticker", "seed_admitted_at",
        "seed_security_id", "seed_security_id_type", "seed_share_class",
        "seed_source_ref", "seed_source_row_identity", "raw_actual_share_coordinate",
        "current_accounting_mapping_ref", "current_mapping_row_identity",
        "actual_quantity_binding", "prior_quantity_binding", "quantity_transition_refs",
        "raw_exact_key_ref", "declared_catalogue_refs", "catalogue_checked_through_session",
        "processed_event_fingerprints", "unsupported_event_fingerprints",
        "identity_conflict_count", "lineage_status")
    FILL_FIELDS = ("path_id", "order_id", "signal_date", "execution_date", "ticker", "side",
                   "fractional_shares", "index_units_before", "index_units_after")

    def __init__(self, account_id, *, fill_owner_ref, lineage_rule_ref, descriptor_bridges=(), identity_transports=()):
        self.account_id = _held_text(account_id)
        self.fill_owner_ref = _held_ref(fill_owner_ref)
        self.lineage_rule_ref = _held_ref(lineage_rule_ref)
        self.descriptor_bridges = descriptor_bridges
        self.identity_transports = identity_transports
        self._candidates, self._positions, self._pending, self._orders = {}, {}, [], {}
        self._closed, self._last_session, self._last_decision = [], None, None
        self._processed_share_fps = set()

    @property
    def held_assets(self):
        return tuple(self._positions)

    @property
    def pending_fill_count(self):
        return len(self._pending)

    @property
    def closed_positions(self):
        from copy import deepcopy
        return deepcopy(tuple(self._closed))

    def note_qualified_decision(self, session, seeds_by_asset):
        """Register candidates, not holdings; an actual positive BUY admits one."""
        day = _held_session(session)
        if self._last_decision is not None and day < self._last_decision:
            raise ValueError("HELD_DECISION_CLOCK_CANNOT_REWIND")
        incoming = {}
        for asset, value in seeds_by_asset.items():
            asset = _held_text(asset)
            if (value.get("qualified") is not True
                    or value.get("historical_observations_relabelled") is not False):
                raise HeldLineageUnavailable("CAUSAL_QUALIFIED_ENTRY_SEED_REQUIRED", asset=asset)
            seed = _held_identity(value)
            asof = pd.Timestamp(value["identity_asof"])
            if (pd.isna(asof) or asof.tzinfo is None or asof > producer._clock(day)):
                raise HeldLineageUnavailable("FUTURE_ENTRY_IDENTITY_SEED", asset=asset)
            seed.update(identity_asof=asof.isoformat(),
                        seed_source_ref=_held_ref(value["seed_source_ref"]),
                        seed_source_row_identity=_held_text(value["seed_source_row_identity"]),
                        historical_source_epoch=_held_text(value["historical_source_epoch"]),
                        signal_session=day)
            key = (day, asset)
            if key in self._candidates and self._candidates[key] != seed:
                raise HeldLineageUnavailable("QUALIFIED_SEED_CHANGED", asset=asset)
            incoming[key] = seed
        self._candidates.update(incoming)
        self._last_decision = day

    def observe_fills(self, frame):
        """Queue actual raw-share owner rows without touching any economic column.

        Atomic ingestion: duplicates/malformed rows leave valid prior pending audit
        and candidates intact. Pre-open share transitions are reconciled later,
        before these fills, by qualified_proofs.
        """
        if not isinstance(frame, pd.DataFrame) or not set(self.FILL_FIELDS).issubset(frame.columns):
            raise ValueError("ACTUAL_FILL_OWNER_COLUMNS_REQUIRED")
        incoming, orders = [], {}
        for value in frame.loc[:, self.FILL_FIELDS].to_dict("records"):
            if value["path_id"] != self.account_id:
                raise HeldLineageUnavailable("CROSS_ACCOUNT_FILL_REJECTED")
            row = {k: _held_text(value[k]) for k in ("order_id", "ticker", "side")}
            row.update(signal_date=_held_session(value["signal_date"]),
                       execution_date=_held_session(value["execution_date"]), path_id=self.account_id,
                       fractional_shares=_held_quantity(value["fractional_shares"]),
                       index_units_before=_held_quantity(value["index_units_before"]),
                       index_units_after=_held_quantity(value["index_units_after"]))
            if (row["side"] not in ("BUY", "SELL")
                    or row["signal_date"] >= row["execution_date"]
                    or self._last_session is not None and row["execution_date"] <= self._last_session):
                raise ValueError("ACTUAL_CAUSAL_FILL_CLOCK_AND_SIDE_REQUIRED")
            quantity = row["fractional_shares"]
            expected = row["index_units_before"] + (quantity if row["side"] == "BUY" else -quantity)
            if (expected < 0 and not _held_equal(expected, 0)
                    or not _held_equal(expected, row["index_units_after"])):
                raise HeldLineageUnavailable("ACTUAL_FILL_QUANTITY_CONFLICT", asset=row["ticker"])
            previous = orders.get(row["order_id"], self._orders.get(row["order_id"]))
            if previous is not None:
                # Original owner target IDs bind a ticker/date, not a fill side.
                # Its one SELL then one BUY may share that ID across callbacks.
                if any(row[k] != previous[k] for k in
                       ("path_id", "ticker", "signal_date", "execution_date")):
                    raise HeldLineageUnavailable("ACTUAL_FILL_ORDER_IDENTITY_CONFLICT", order_id=row["order_id"])
                if row["side"] == previous["side"]:
                    raise HeldLineageUnavailable("DUPLICATE_ACTUAL_FILL_LEG", order_id=row["order_id"])
                if (previous["side"], row["side"]) != ("SELL", "BUY"):
                    raise HeldLineageUnavailable("ACTUAL_FILL_LEG_SEQUENCE_CONFLICT", order_id=row["order_id"])
                if not _held_equal(row["index_units_before"], previous["index_units_after"]):
                    raise HeldLineageUnavailable("ACTUAL_FILL_LEG_QUANTITY_CHAIN_CONFLICT", order_id=row["order_id"])
            if quantity > 0 and row["side"] == "BUY" and (row["signal_date"], row["ticker"]) not in self._candidates:
                raise HeldLineageUnavailable("ACTUAL_BUY_QUALIFIED_SEED_MISSING", asset=row["ticker"])
            orders[row["order_id"]] = row
            if quantity > 0:
                incoming.append(row)
        self._pending.extend(incoming)
        self._orders.update(orders)
        return len(incoming)

    def source_lineages(self):
        """Read-only asset -> ordered spell records for source-guard construction.

        Accepted identities retain their direct last committed raw quantity.
        Pending actual BUY candidates expose their prior-decision seed, explicitly
        without admitted status. Pending sells/clear/reentry retain fill order.
        This view neither reconciles quantities nor executes pre-open CA effects;
        qualified_proofs alone can commit a holding spell.
        """
        from copy import deepcopy
        result, active = {}, {}
        for asset, position in self._positions.items():
            item = dict(role="ACCEPTED_POSITION", position_id=position["position_id"],
                identity=deepcopy(position["identity"]), seed=deepcopy(position["seed"]),
                seed_admitted_at=position["admitted"],
                committed_prior_raw_quantity=position["quantity"],
                prior_quantity_binding=deepcopy(position["quantity_binding"]), pending_fill_refs=[],
                processed_share_transitions=deepcopy(position.get("processed_share_transitions",[])))
            result[asset], active[asset] = [item], item
        for row in self._pending:
            asset = row["ticker"]
            item = active.get(asset)
            candidate = None
            if row["side"] == "BUY":
                candidate = deepcopy(self._candidates[(row["signal_date"], asset)])
                identity = {k: candidate[k] for k in
                            ("security_id", "security_id_type", "cusip", "share_class",
                             "raw_code", "raw_actual_share_coordinate")}
                if item is None or not _held_security_identity_equal(item["identity"], identity, self.descriptor_bridges):
                    item = dict(role="PENDING_ACTUAL_BUY_CANDIDATE_NOT_ADMITTED",
                        position_id=None, identity=identity, seed=candidate,
                        seed_admitted_at=None, committed_prior_raw_quantity=None,
                        prior_quantity_binding=None, pending_fill_refs=[])
                    result.setdefault(asset, []).append(item)
                    active[asset] = item
            if item is None:
                # Preserve a real SELL lacking prior lineage as unresolved audit,
                # never convert it into an identity seed or discard its effect.
                item = dict(role="PENDING_ACTUAL_SELL_WITHOUT_LINEAGE", position_id=None,
                    identity=None, seed=None, seed_admitted_at=None,
                    committed_prior_raw_quantity=None, prior_quantity_binding=None, pending_fill_refs=[])
                result.setdefault(asset, []).append(item)
                active[asset] = item
            item["pending_fill_refs"].append(dict(actual_owner_fill=deepcopy(row),
                fill_owner_ref=deepcopy(self.fill_owner_ref), candidate_seed=candidate))
            if row["index_units_after"] == 0:
                active.pop(asset, None)
        return deepcopy({asset: tuple(records) for asset, records in result.items()})

    def required_guard_assets(self, ctx):
        """Read-only master-ordered union of current H, prior book and pending."""
        assets = tuple(map(str, ctx.tickers))
        if len(set(assets)) != len(assets):
            raise ValueError("UNIQUE_HELD_MASTER_REQUIRED")
        units = _vector(ctx, "current_units", len(assets))
        weights = _vector(ctx, "current_weights", len(assets))
        required = {a for a, q, w in zip(assets, units, weights) if q > 0 or w > 0}
        required |= set(self._positions) | {r["ticker"] for r in self._pending}
        if not required.issubset(assets):
            raise HeldLineageUnavailable("ACTUAL_LINEAGE_OUTSIDE_MASTER", assets=sorted(required-set(assets)))
        return tuple(a for a in assets if a in required)

    def _guard(self, asset, value, day, earliest, *, terminal_closing=False):
        if (value.get("qualified") is not True
                or value.get("historical_observations_relabelled") is not False
                or _held_session(value["decision_session"]) != day):
            raise HeldLineageUnavailable("CURRENT_HELD_SOURCE_GUARD_REQUIRED", asset=asset)
        identity = _held_identity(value)
        terminal_absent = (terminal_closing and value.get("terminal_raw_key_absence") is True
            and value.get("raw_key_count") == 0
            and len(value["quantity_transitions"]) == 1
            and value["quantity_transitions"][0].get("kind") == "TERMINAL")
        if (value.get("mapping_row_count") != 1 or isinstance(value.get("mapping_row_count"), bool)
                or isinstance(value.get("raw_key_count"), bool)
                or value.get("raw_key_count") != 1 and not terminal_absent):
            raise HeldLineageUnavailable("UNIQUE_DATED_RAW_MAPPING_AND_KEY_REQUIRED", asset=asset)
        start = _held_session(value["mapping_start"])
        end = pd.Timestamp(value["mapping_end_exclusive"])
        if (start > day or pd.isna(end) or end.tzinfo is not None or end != end.normalize()
                or pd.Timestamp(day) >= end):
            raise HeldLineageUnavailable("CURRENT_DATED_MAPPING_REQUIRED", asset=asset)
        if (value.get("mapping_raw_code") != identity["raw_code"]
                or not terminal_absent and (_held_session(value["raw_key_session"]) != day
                                             or value.get("raw_key_code") != identity["raw_code"])):
            raise HeldLineageUnavailable("CURRENT_RAW_CODE_CONFLICT", asset=asset)
        from_day = _held_session(value["catalogue_checked_from_session"])
        through = _held_session(value["catalogue_checked_through_session"])
        if from_day > earliest or through != day:
            raise HeldLineageUnavailable("COMPLETE_CURRENT_CATALOGUE_INTERVAL_REQUIRED", asset=asset)
        refs = [_held_ref(r) for r in value["declared_catalogue_refs"]]
        processed = [_held_text(v) for v in value["processed_event_fingerprints"]]
        unsupported = [_held_text(v) for v in value["unsupported_event_fingerprints"]]
        conflict = value["identity_conflict_count"]
        if (not refs or unsupported or conflict != 0 or isinstance(conflict, bool)
                or len(processed) != len(set(processed))):
            raise HeldLineageUnavailable("UNSUPPORTED_SHARE_OR_IDENTITY_EVENT", asset=asset)
        return dict(identity=identity, mapping_ref=_held_ref(value["current_accounting_mapping_ref"]),
                    mapping_row=_held_text(value["current_mapping_row_identity"]),
                    raw_ref=None if terminal_absent else _held_ref(value["raw_exact_key_ref"]),
                    raw_row=None if terminal_absent else _held_text(value["raw_key_row_identity"]), refs=refs,
                    processed=processed, transitions=value["quantity_transitions"],
                    metadata_bindings=value.get("identity_metadata_bindings", []))

    def _transition(self, asset, position, row, guard, day):
        """Verify the existing typed owner's effect; never execute that effect."""
        if (row.get("qualified") is not True or row.get("typed_event") is not True
                or row.get("stage") != "PRE_OPEN"
                or _held_session(row["session"]) != day
                or row.get("kind") not in ("SPLIT", "CONVERSION", "TERMINAL")):
            raise HeldLineageUnavailable("APPROVED_TYPED_SHARE_TRANSITION_REQUIRED", asset=asset)
        fp = _held_text(row["event_fingerprint"])
        if fp not in guard["processed"]:
            raise HeldLineageUnavailable("UNPROCESSED_TYPED_SHARE_TRANSITION", asset=asset)
        if position is None:
            raise HeldLineageUnavailable("SHARE_TRANSITION_WITHOUT_ACTUAL_POSITION", asset=asset)
        before, after = _held_quantity(row["before_raw_quantity"]), _held_quantity(row["after_raw_quantity"])
        old, new = _held_identity(row["old_identity"]), _held_identity(row["new_identity"])
        if not _held_security_identity_equal(old, position["identity"], self.descriptor_bridges) or not _held_equal(before, position["quantity"]):
            raise HeldLineageUnavailable("TYPED_SHARE_TRANSITION_PRIOR_CONFLICT", asset=asset)
        if row["kind"] == "TERMINAL":
            if after != 0:
                raise HeldLineageUnavailable("TERMINAL_OWNER_QUANTITY_CONFLICT", asset=asset)
        else:
            try:
                ratio = _held_quantity(row.get("share_ratio"))
            except (TypeError, ValueError) as exc:
                raise HeldLineageUnavailable("TYPED_SHARE_RATIO_REQUIRED", asset=asset) from exc
            if ratio <= 0 or not _held_equal(after, before*ratio):
                raise HeldLineageUnavailable("TYPED_SHARE_RATIO_REQUIRED", asset=asset)
            if row["kind"] == "SPLIT" and not _held_security_identity_equal(old, new, self.descriptor_bridges):
                raise HeldLineageUnavailable("SPLIT_CANNOT_RENAME_SECURITY", asset=asset)
        ref = dict(kind=row["kind"], session=day, event_fingerprint=fp,
                   before_raw_quantity=before, after_raw_quantity=after,
                   old_identity=old, new_identity=new,
                   source_ref=_held_ref(row["source_ref"]), owner_ref=_held_ref(row["owner_ref"]))
        if 'quantity_after_role' in row:
            role=_held_text(row['quantity_after_role'])
            if role not in ('FIRST_ACTUAL_FILL_BEFORE_AFTER_PRE_OPEN',
                            'DIRECT_CURRENT_RAW_QUANTITY_NO_ASSET_FILLS',
                            'DIRECT_ORIGINAL_TERMINAL_PRE_OPEN_AFTER'):
                raise HeldLineageUnavailable('DIRECT_ACTUAL_AFTER_EVIDENCE_ROLE_REQUIRED',asset=asset)
            evidence=row.get('actual_quantity_evidence_ref')
            if (not isinstance(evidence,dict) or _held_ref(evidence['owner_ref'])!=_held_ref(row['owner_ref'])
                    or not _held_equal(evidence['actual_raw_quantity'],after)):
                raise HeldLineageUnavailable('EXACT_ACTUAL_AFTER_QUANTITY_EVIDENCE_REQUIRED',asset=asset)
            ref.update(quantity_after_role=role,actual_quantity_evidence_ref=dict(evidence))
            if 'quantity_before_role' in row:
                before_evidence=row.get('actual_before_quantity_evidence_ref')
                if (row['quantity_before_role']!='DIRECT_ORIGINAL_PRE_OPEN_RAW_BEFORE'
                        or not isinstance(before_evidence,dict)
                        or _held_ref(before_evidence['owner_ref'])!=_held_ref(row['owner_ref'])
                        or not _held_equal(before_evidence['actual_raw_quantity'],before)):
                    raise HeldLineageUnavailable('EXACT_ACTUAL_BEFORE_QUANTITY_EVIDENCE_REQUIRED',asset=asset)
                ref.update(quantity_before_role=row['quantity_before_role'],
                           actual_before_quantity_evidence_ref=dict(before_evidence))
        position.setdefault("processed_share_transitions",[]).append(dict(ref,position_id=position["position_id"]))
        position.update(quantity=after, identity=new,
                        quantity_binding=dict(stage="ORIGINAL_TYPED_PRE_OPEN_AFTER", session=day,
                                              raw_quantity=after, source_transition=ref))
        return ref

    def qualified_proofs(self, ctx, current_guard_by_asset):
        """Validate every held/previous/pending asset and atomically commit 22 fields.

        Guard failure changes neither holdings nor pending fills/candidates. A
        cleared spell is closed; a later actual BUY uses that signal's fresh seed.
        No positive weight or quantity can disappear due to feature eligibility.
        """
        from copy import deepcopy
        day = _held_session(ctx.signal_date)
        if pd.Timestamp(ctx.signal_asof) != producer._clock(day):
            raise ValueError("EXACT_HELD_DECISION_CLOSE_REQUIRED")
        if self._last_session is not None and day <= self._last_session:
            raise ValueError("HELD_PROOF_SESSION_MUST_ADVANCE")
        assets = tuple(map(str, ctx.tickers))
        if len(set(assets)) != len(assets):
            raise ValueError("UNIQUE_HELD_MASTER_REQUIRED")
        units = _vector(ctx, "current_units", len(assets))
        weights = _vector(ctx, "current_weights", len(assets))
        quantities = dict(zip(assets, units))
        held = {a for a, q, w in zip(assets, units, weights) if q > 0 or w > 0}
        pending = deepcopy(self._pending)
        if any(r["execution_date"] != day for r in pending):
            raise HeldLineageUnavailable("PENDING_FILL_CURRENT_SESSION_REQUIRED")
        needed = set(self.required_guard_assets(ctx))
        if not needed.issubset(quantities) or not needed.issubset(current_guard_by_asset):
            raise HeldLineageUnavailable("COMPLETE_ACTUAL_HELD_GUARD_DOMAIN_REQUIRED",
                                         assets=sorted(needed-set(current_guard_by_asset)))
        positions, closed, proofs = deepcopy(self._positions), [], {}
        processed_share_fps = set(self._processed_share_fps)
        for asset in assets:
            if asset not in needed:
                continue
            rows = [r for r in pending if r["ticker"] == asset]
            position = positions.get(asset)
            earliest = self._last_session or min((r["signal_date"] for r in rows), default=day)
            guard = self._guard(asset, current_guard_by_asset[asset], day, earliest,
                                terminal_closing=asset not in held)
            def current_metadata(seed, identity, position=None):
                spell=None if position is None else dict(role="ACCEPTED_POSITION",position_id=position["position_id"],
                    seed=position["seed"],seed_admitted_at=position["admitted"],
                    committed_prior_raw_quantity=position["quantity"], prior_quantity_binding=deepcopy(position["quantity_binding"]),
                    processed_share_transitions=position.get("processed_share_transitions",[]))
                evidence=_held_identity_metadata_binding(seed,identity,day,self.identity_transports,held_spell=spell)
                if evidence is None:
                    return identity, None
                if (evidence not in guard["metadata_bindings"]
                        or evidence["current_identity"]!=guard["identity"]):
                    raise HeldLineageUnavailable("EXACT_CURRENT_METADATA_TRANSPORT_GUARD_REQUIRED",asset=asset)
                return deepcopy(evidence["current_identity"]), evidence
            if position is not None:
                position["identity"], _ = current_metadata(position["seed"],position["identity"],position)
            prior = None if position is None else deepcopy(position["quantity_binding"])
            refs, fingerprints = [], set()
            for transition in guard["transitions"]:
                fp = transition["event_fingerprint"]
                if fp in fingerprints or fp in processed_share_fps:
                    raise HeldLineageUnavailable("DUPLICATE_TYPED_SHARE_TRANSITION", asset=asset)
                fingerprints.add(fp)
                refs.append(self._transition(asset, position, transition, guard, day))
                processed_share_fps.add(fp)
            if position is not None and position["quantity"] == 0:
                closed.append(dict(position_id=position["position_id"], ticker=asset,
                                   closed_session=day, closing_quantity_binding=deepcopy(position["quantity_binding"])))
                position = None
            for row in rows:
                before, after = row["index_units_before"], row["index_units_after"]
                if not _held_equal(before, 0 if position is None else position["quantity"]):
                    raise HeldLineageUnavailable("ACTUAL_FILL_PRIOR_QUANTITY_CONFLICT", asset=asset)
                if row["side"] == "BUY":
                    seed = self._candidates[(row["signal_date"], asset)]
                    identity = {k: seed[k] for k in guard["identity"]}
                    identity, _ = current_metadata(seed,identity)
                    if position is None:
                        position = dict(position_id=content_hash(dict(account=self.account_id, order=row["order_id"],
                            admitted=day, seed=seed)), seed=deepcopy(seed), identity=identity,
                            admitted=day, quantity=0., quantity_binding=None)
                    elif not _held_security_identity_equal(position["identity"], identity, self.descriptor_bridges):
                        raise HeldLineageUnavailable("ACTUAL_BUY_EXISTING_IDENTITY_CONFLICT", asset=asset)
                elif position is None:
                    raise HeldLineageUnavailable("ACTUAL_SELL_LINEAGE_MISSING", asset=asset)
                ref = dict(stage="ACTUAL_RAW_SHARE_FILL", account_id=self.account_id,
                           order_id=row["order_id"], signal_session=row["signal_date"], session=day,
                           side=row["side"], raw_quantity=row["fractional_shares"],
                           before_raw_quantity=before, after_raw_quantity=after, owner_ref=self.fill_owner_ref)
                if prior is None:
                    prior = dict(stage="ACTUAL_RAW_SHARE_FILL_BEFORE", session=day,
                                 raw_quantity=before, source_fill=ref)
                refs.append(ref)
                position.update(quantity=after, quantity_binding=dict(stage="ACTUAL_RAW_SHARE_FILL_AFTER",
                                session=day, raw_quantity=after, source_fill=ref))
                if after == 0:
                    closed.append(dict(position_id=position["position_id"], ticker=asset, closed_session=day,
                                       closing_quantity_binding=deepcopy(position["quantity_binding"])))
                    position = None
            if position is None:
                if asset in held:
                    raise HeldLineageUnavailable("ACTUAL_HELD_ADMISSION_SEED_MISSING", asset=asset)
                positions.pop(asset, None)
                continue
            if not _held_security_identity_equal(position["identity"], guard["identity"], self.descriptor_bridges):
                raise HeldLineageUnavailable("CURRENT_HELD_IDENTITY_CONFLICT", asset=asset)
            actual = float(quantities[asset])
            if (actual <= 0 or not _held_equal(actual, position["quantity"])):
                raise HeldLineageUnavailable("DIRECT_ACTUAL_HELD_QUANTITY_CONFLICT", asset=asset)
            actual_binding = dict(account_id=self.account_id, session=day, stage="DECISION_CLOSE_RAW_ACTUAL_SHARE",
                                  raw_quantity=actual, owner_ref=self.fill_owner_ref)
            seed = position["seed"]
            proof = dict(decision_session=day, position_id=position["position_id"], ticker=asset,
                seed_admitted_at=position["admitted"], seed_security_id=seed["security_id"],
                seed_security_id_type=seed["security_id_type"], seed_share_class=seed["share_class"],
                seed_source_ref=seed["seed_source_ref"], seed_source_row_identity=seed["seed_source_row_identity"],
                raw_actual_share_coordinate="RAW_ACTUAL_SHARE",
                current_accounting_mapping_ref=guard["mapping_ref"], current_mapping_row_identity=guard["mapping_row"],
                actual_quantity_binding=actual_binding, prior_quantity_binding=prior or position["quantity_binding"],
                quantity_transition_refs=refs,
                raw_exact_key_ref=dict(source_ref=guard["raw_ref"], row_identity=guard["raw_row"]),
                declared_catalogue_refs=guard["refs"], catalogue_checked_through_session=day,
                processed_event_fingerprints=guard["processed"], unsupported_event_fingerprints=[],
                identity_conflict_count=0, lineage_status="QUALIFIED_RESEARCH_HELD_LINEAGE")
            assert tuple(proof) == self.PROOF_FIELDS
            _, metadata_binding = current_metadata(seed,position["identity"],position)
            if metadata_binding is not None:
                proof["current_identity_metadata_binding"]=dict(
                    account_id=self.account_id,position_id=position["position_id"],decision_session=day,
                    source_binding=metadata_binding,raw_quantity_effect=0,
                    typed_CA_event=False,historical_observations_relabelled=False)
            position.update(quantity=actual, quantity_binding=actual_binding)
            positions[asset], proofs[asset] = position, proof
        self._positions = positions
        self._processed_share_fps = processed_share_fps
        self._closed.extend(closed)
        self._pending = []
        self._candidates = {k: v for k, v in self._candidates.items() if k[0] >= day}
        self._last_session = day
        return deepcopy(proofs)


HELD_RUNTIME_BINDING_SCHEMA = 'B_HELD_IDENTITY_RUNTIME_SOURCE_BINDING_V1'
CAUSAL_LW_REUSE_RULE = dict(schema='B_CAUSAL_APPROVED_SINGLE_LW_REUSE_RULE_V1',
    primary_priority=True, fallback='APPROVED_SINGLE_WHOLE_LW',
    require_same_original_primary_epoch=True, require_complete_required_axis=True,
    expiry='FIRST_NEXT_ORIGINAL_PRIMARY_EVENT', matrix_mixing=False,
    additional_estimate_or_refresh_allowed=False,
    identity_role='IMMUTABLE_FIT_ASOF_PROOF_SEPARATE_CURRENT_ACTUAL_HELD_LINEAGE')


def _causal_need(ok, reason, **evidence):
    if not ok:
        raise ExistingRiskInputUnavailable(reason, **evidence)


def _causal_pin(interface, reference):
    reference = _held_ref(reference)
    # Never resolve or inspect a prohibited drive to decide whether it is legal.
    if Path(reference['path']).drive.upper() != 'D:':
        raise HeldLineageUnavailable('LITERAL_D_RUNTIME_SOURCE_REQUIRED_BEFORE_IO')
    return interface.pin(reference)


def _source_value(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _held_raw_key_row_identity(rows):
    """Original guard commitment of exact metadata rows, not price payloads.

    Keep the existing ordered list/string representation. A scalar typed-row
    digest is a different commitment and must never be accepted as its alias.
    """
    return content_hash(rows.astype(str).to_dict('records'))


CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE = dict(
    schema='B_CLOSED_SELL_SPELL_CURRENT_ENTRY_SOURCE_ROLE_RULE_V1',
    scope='EXACT_ACTUAL_ZERO_SELL_CLOSING_SPELL_SEPARATE_FROM_CURRENT_ENTRY',
    prior_admitted_spell_required=True, all_actual_fills_current_session_sell_only=True,
    current_units_and_weight_exact_zero=True, current_entry_same_nonclass_coordinates=True,
    same_original_uid_source_and_issuer_required=True, original_seed_and_rows_immutable=True,
    changed_descriptor_new_interval_starts_current_session=True,
    class_equivalence_granted=False, quantity_effect=False,
    historical_observations_relabelled=False, current_entry_identity_and_epoch_preserved=True,
    membership_extension=False, buy_permission_extension=False,
    strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)


class FrozenHeldSourceGuards:
    """Thin metadata projections, not an identity master or CA execution owner.

    Membership certifies new entry seeds only. Held continuity uses an admitted
    seed, a unique dated raw coordinate, and the complete declared catalogue.
    Actual quantity changes are supplied by the existing owner and verified.
    """
    IDENTITY_COLUMNS = ('ticker', 'effective_start', 'effective_end', 'security_id',
        'security_id_type', 'cusip', 'issuer_name', 'title_of_class',
        'moomoo_transport_code', 'mapping_status', 'mapping_source', 'source_filing')
    AUDIT_COLUMNS = ('ticker', 'event_date', 'source_event_date', 'code',
                     'audit_kind', 'share_event', 'manual_wolf', 'aligned_to_next_session')

    def __init__(self, base, binding, source_context, *, account_id, accounting_freeze_ref, descriptor_bridges=(), identity_transports=(), closed_sell_spell_entry_rule=None, investment_exclusion_tickers=()):
        from copy import deepcopy
        import ast
        self.base, self.binding, self.interface = base, deepcopy(binding), base.interface
        self.investment_exclusion_tickers = tuple(investment_exclusion_tickers)
        self.descriptor_bridges = descriptor_bridges
        self.held_accounting_sources = tuple(t for t in identity_transports if t.get('issuer_bound_held_accounting_coordinate_only') is True)
        self.identity_transports = tuple(t for t in identity_transports if t.get('issuer_bound_held_accounting_coordinate_only') is not True)
        self.held_accounting_account_id = account_id
        if closed_sell_spell_entry_rule is not None and closed_sell_spell_entry_rule != CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE:
            raise HeldLineageUnavailable('EXACT_DECLARED_CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE_REQUIRED')
        self.closed_sell_spell_entry_rule = deepcopy(closed_sell_spell_entry_rule)
        if (binding.get('schema') != HELD_RUNTIME_BINDING_SCHEMA
                or binding.get('date_start') != '2023-01-03'
                or binding.get('date_stop_exclusive') != '2026-01-01'
                or any(binding.get(k) is not False for k in
                       ('strict_PIT', 'production_qualified', 'quote_qualified', 'certified_NAV'))):
            raise HeldLineageUnavailable('COMPLETE_FROZEN_RESEARCH_SOURCE_BINDING_REQUIRED')
        names = ('source_manifest_ref', 'mapping_ref', 'original_event_binding_ref',
                 'static_event_source_ref', 'source_account_contract_ref',
                 'lineage_rule_ref', 'fill_owner_ref', 'account_owner_ref')
        pinned = {n: _causal_pin(self.interface, binding[n]) for n in names}
        context = source_context
        if (not isinstance(context, dict)
                or context.get('owner_ref') != binding['account_owner_ref']
                or binding['fill_owner_ref'] != binding['account_owner_ref']
                or context.get('input_refs') != binding['account_input_refs']
                or context.get('source_account_contract_ref') != binding['source_account_contract_ref']
                or tuple(context.get('market_dates', ())) != tuple(base.market_dates)
                or tuple(map(str, context.get('master_assets', ()))) != base.master_assets):
            raise HeldLineageUnavailable('EXACT_ACTUAL_OWNER_AND_SOURCE_CONTEXT_REQUIRED')
        # code:* refs are retained historical logical commitments, not today's
        # execution bytes. The actual owner/caller closure is pinned separately.
        if binding.get('legacy_input_code_ref_role') != 'INHERITED_LOGICAL_COMMITMENT_NOT_CURRENT_EXECUTION_SOURCE; preserve original loader/custody resolution':
            raise HeldLineageUnavailable('EXPLICIT_INHERITED_CODE_COMMITMENT_ROLE_REQUIRED')
        for name, reference in binding['account_input_refs'].items():
            if not name.startswith('code:'):
                _causal_pin(self.interface, reference)
        present = np.asarray(context.get('raw_row_present'))
        if present.dtype != bool or present.shape != (len(base.market_dates), len(base.master_assets)):
            raise HeldLineageUnavailable('EXACT_FROZEN_ACCOUNT_RAW_KEY_DOMAIN_REQUIRED')
        self.present = present.copy(); self.present.flags.writeable = False
        self.events = deepcopy(context['events'])
        self.mapping = self.interface.read(pinned['mapping_ref'])
        if self.mapping.get('coordinate') != 'RAW_ACTUAL_SHARE' or self.mapping.get('role') != 'ACCOUNTING_MAPPING_ONLY':
            raise HeldLineageUnavailable('RAW_ACCOUNTING_MAPPING_ONLY_REQUIRED')
        for row in self.mapping['records']:
            _held_session(row['start']); end = pd.Timestamp(row['end'])
            if end.tzinfo is not None or end > pd.Timestamp('2026-01-01') or end != end.normalize():
                raise HeldLineageUnavailable('PRE2026_DATED_MAPPING_DOMAIN_REQUIRED')
        original = self.interface.read(pinned['original_event_binding_ref'])
        self.original_events = tuple(original['event_records'])
        for row in self.original_events: _held_session(row['event_date'])
        node = next(n for n in ast.parse(Path(pinned['static_event_source_ref']).read_text(encoding='utf-8-sig')).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'frozen_evidence_records')
        literal = next(n.value for n in node.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'records' for t in n.targets))
        self.static_events = tuple(ast.literal_eval(literal))
        for row in self.static_events: _held_session(row['event_date'])
        self.share_events, self.cash_events, self.terminal_events = [], [], []
        for event in self.events.get('corporate_actions', ()):
            self.share_events.append(dict(event=event,day=_held_session(_source_value(event,'effective_date')),
                ticker=_source_value(event,'old_ticker'),fp=_source_value(event,'event_fingerprint')))
        classes=context.get('typed_entitlement_classes')
        if (not isinstance(classes,dict) or set(classes)!={'cash','terminal'}
                or context.get('typed_ca_owner_ref')!=binding.get('typed_ca_owner_ref')
                or not all(isinstance(c,type) for c in classes.values())):
            raise HeldLineageUnavailable('ACTUAL_FROZEN_TYPED_OWNER_CLASSES_REQUIRED')
        _causal_pin(self.interface,binding['typed_ca_owner_ref'])
        self.typed_classes=classes
        for event in self.events.get('entitlement_events', ()):
            if isinstance(event,classes['cash']) and not isinstance(event,classes['terminal']):
                self.cash_events.append(dict(event=event,day=_held_session(_source_value(event,'ex_date')),
                    ticker=_source_value(event,'ticker'),fp=_source_value(event,'event_fingerprint')))
            elif isinstance(event,classes['terminal']):
                effective = pd.Timestamp(_source_value(event,'effective_at'))
                if pd.isna(effective) or effective.tzinfo is None:
                    raise HeldLineageUnavailable('UNKNOWN_TYPED_TERMINAL_EFFECTIVE_CLOCK')
                self.terminal_events.append(dict(event=event,
                    day=_held_session(effective.tz_convert('America/New_York').tz_localize(None).normalize()),
                    ticker=_source_value(event,'ticker'),fp=_source_value(event,'event_fingerprint')))
            else:
                raise HeldLineageUnavailable('UNSUPPORTED_TYPED_ENTITLEMENT_CLASS')
        self.unsupported = tuple(self.events.get('unsupported_events', ()))
        for row in self.unsupported: _held_session(row['effective_date'])
        for transport in self.identity_transports:
            if transport.get('pre_action_existing_held') is True:
                expected=transport['original_event']
                matches=[r for r in self.share_events if r['fp']==expected['event_fingerprint']
                    and r['day']==transport['post_split_trading_session'] and r['ticker']==transport['old_row']['ticker']]
                if (len(matches)!=1 or transport['account_owner_ref']!=binding['account_owner_ref']
                        or not _held_equal(_source_value(matches[0]['event'],'quantity_multiplier'),expected['quantity_multiplier'])
                        or _source_value(matches[0]['event'],'source_fingerprint')!=expected['source_fingerprint']):
                    raise HeldLineageUnavailable('EXACT_ORIGINAL_TYPED_SHARE_METADATA_RELATION_REQUIRED')
        for source in self.held_accounting_sources:
            expected=source['original_source_event']
            matches=[r for r in self.share_events if r['day']==source['post_split_trading_session'] and r['ticker']=='MKFG'
                and _source_value(r['event'],'source_fingerprint')==expected['source_fingerprint']
                and _held_equal(_source_value(r['event'],'quantity_multiplier'),expected['quantity_multiplier'])]
            if len(matches)!=1 or source['account_owner_ref']!=binding['account_owner_ref']:
                raise HeldLineageUnavailable('EXACT_ORIGINAL_OWN_HELD_ACCOUNTING_SHARE_RELATION_REQUIRED')
            source['runtime_typed_share_event_fingerprint']=matches[0]['fp']
        self.unit_effects, self.lifecycle_effects = {}, {}
        self._bind_account_boundary_context(context.get('account_boundary_context'),
            account_id=account_id, accounting_freeze_ref=accounting_freeze_ref)

    def _bind_account_boundary_context(self, context, *, account_id, accounting_freeze_ref):
        """Keep the original owner's live list; never create another ledger."""
        if (not isinstance(context, dict) or set(context) != {'account_id','owner_ref','convention_ref','rows'}
                or context['account_id'] != account_id or not isinstance(context['rows'], list)
                or _held_ref(context['owner_ref']) != _held_ref(self.binding['account_owner_ref'])
                or _held_ref(context['convention_ref']) != _held_ref(accounting_freeze_ref)):
            raise HeldLineageUnavailable('EXACT_ORIGINAL_ACCOUNT_BOUNDARY_CONTEXT_REQUIRED')
        _causal_pin(self.interface, accounting_freeze_ref)
        self.account_boundary_context = dict(account_id=_held_text(account_id),
            owner_ref=_held_ref(context['owner_ref']), convention_ref=_held_ref(context['convention_ref']),
            rows=context['rows'])

    def _account_prefix_nonapplicability(self, event, ctx, account_id):
        """Accept only the original exact-key PRE_OPEN zero-position disposition.

        A later new BUY does not make a past zero-position event applicable.
        Missing or conflicting facts stay residual SOURCE blockers. No declared
        event, price mask or typed cash/share/terminal permission is changed.
        """
        fields=('ticker','effective_date','reason','source_reference','source_fingerprint')
        context=getattr(self,'account_boundary_context',None)
        if (not isinstance(context,dict) or context.get('account_id')!=account_id
                or not all(isinstance(event.get(k),str) and event[k].strip() for k in fields)):
            return None
        key=tuple(event[k] for k in fields)
        rows=[r for r in context['rows'] if isinstance(r,dict) and tuple(r.get(k) for k in fields)==key]
        if len(rows)!=1:
            return None
        row=rows[0]
        try:
            effective=_held_session(event['effective_date'])
            clock=pd.Timestamp(row['accounting_boundary_at'])
            asof=pd.Timestamp(ctx.signal_asof)
            opened=(pd.Timestamp(effective)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
            values=[row[k] for k in ('pre_open_engine_units','pre_open_raw_shares','prior_session_quantity_factor')]
            if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,float,np.number)) for v in values):
                return None
            engine,raw,factor=map(float,values)
            if (row.get('path_id')!=account_id or row.get('clock_role')!='RESEARCH_SESSION_BOUNDARY_ACCOUNTING_CONVENTION'
                    or row.get('disposition')!='NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX'
                    or pd.isna(clock) or clock.tzinfo is None or pd.isna(asof) or asof.tzinfo is None
                    or clock!=opened or clock>asof or effective>_held_session(ctx.signal_date)
                    or not np.isfinite([engine,raw,factor]).all() or engine!=0 or raw!=0 or factor<=0):
                return None
        except (KeyError,TypeError,ValueError,OverflowError):
            return None
        return dict(role='ORIGINAL_OWNER_ACCOUNT_PREFIX_NOT_APPLICABLE',
            account_id=account_id,original_event_key=dict(zip(fields,key)),
            accounting_boundary_at=clock.isoformat(),pre_open_engine_units=engine,
            pre_open_raw_shares=raw,prior_session_quantity_factor=factor,
            disposition=row['disposition'],clock_role=row['clock_role'],
            owner_ref=dict(context['owner_ref']),convention_ref=dict(context['convention_ref']),
            original_boundary_list_source=True,typed_cash_processed=False,
            cash_or_share_or_terminal_permission_granted=False,quote_qualification_granted=False,
            historical_availability_granted=False)

    def observe_owner_transitions(self, payload, account_id):
        """Store actual output; a unit-one commitment never admits a position."""
        from copy import deepcopy
        if payload.get('owner_ref') != self.binding['account_owner_ref']:
            raise HeldLineageUnavailable('ACTUAL_EXECUTION_OWNER_COMMITMENT_REQUIRED')
        role = payload.get('role')
        if role == 'UNIT_COORDINATE_APPLIED':
            day=_held_session(payload['effective_session']);fp=_held_text(payload['event_fingerprint'])
            if (len([r for r in self.share_events if r['fp']==fp and r['day']==day])!=1
                    or payload.get('quantity_coordinate')!='ORIGINAL_OWNER_UNIT_FACTOR_COMMITMENT'):
                raise HeldLineageUnavailable('EXACT_ORIGINAL_UNIT_COORDINATE_EVENT_REQUIRED')
            if fp in self.unit_effects:
                raise HeldLineageUnavailable('DUPLICATE_ACTUAL_OWNER_UNIT_EFFECT')
            self.unit_effects[fp]=deepcopy(payload)
        elif role == 'PRE_OPEN_LIFECYCLE_APPLIED':
            day=_held_session(payload['session'])
            expected_open=(pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
            if (payload.get('account_id')!=account_id or payload.get('quantity_coordinate')!='RAW_ACTUAL_SHARE'
                    or pd.Timestamp(payload['session_open_at'])!=expected_open):
                raise HeldLineageUnavailable('EXACT_ACCOUNT_RAW_PREOPEN_LIFECYCLE_REQUIRED')
            for field in ('positions_before','positions_after'):
                for value in payload[field].values(): _held_quantity(value)
            supplement=payload.get('original_preopen_raw_positions_by_ticker')
            if supplement is not None:
                if (payload.get('original_preopen_quantity_role')!='DIRECT_ORIGINAL_OWNER_PREOPEN_UNITS_TIMES_PRIOR_FACTOR'
                        or not isinstance(supplement,dict) or set(supplement)!=set(self.base.master_assets)):
                    raise HeldLineageUnavailable('EXACT_ORIGINAL_OWNER_PREOPEN_TICKER_AXIS_REQUIRED')
                for value in supplement.values(): _held_quantity(value)
                for sid,ticker in payload['security_tickers'].items():
                    if ticker in supplement and sid in payload['positions_before'] and not _held_equal(
                            supplement[ticker],payload['positions_before'][sid]):
                        raise HeldLineageUnavailable('ORIGINAL_PREOPEN_QUANTITY_SOURCES_CONFLICT',asset=ticker)
            if day in self.lifecycle_effects:
                raise HeldLineageUnavailable('DUPLICATE_ACTUAL_OWNER_PREOPEN_EFFECT')
            # Only the latest current-session facts are needed; per-use proofs
            # keep commitments. Do not create a second 752-day quantity store.
            self.lifecycle_effects={day:deepcopy(payload)}
        else:
            raise HeldLineageUnavailable('UNKNOWN_ACTUAL_OWNER_TRANSITION_ROLE')

    def _own_held_issuer_accounting_proof(self, asset, day, ctx, spells, eligible, book):
        """Source-check the old own seed and original split; never relabel H or E."""
        from copy import deepcopy
        sources=[s for s in getattr(self,'held_accounting_sources',()) if s['old_row']['ticker']==asset
            and pd.Timestamp(s['post_split_trading_session'])<=day]
        if not sources:return None
        if len(sources)!=1 or asset in eligible or len(spells)!=1 or book.account_id!=self.held_accounting_account_id:
            raise HeldLineageUnavailable('EXACT_OUTSIDE_ENTRY_OWN_HELD_ACCOUNTING_SCOPE_REQUIRED',asset=asset)
        source=sources[0];spell=spells[0];seed=spell.get('seed')
        known=pd.Timestamp(source['source_available_at'])
        if (pd.isna(known) or known.tzinfo is None or spell.get('role')!='ACCEPTED_POSITION' or not isinstance(spell.get('position_id'),str)
                or not isinstance(seed,dict)
                or _held_identity(seed)!=source['old_identity'] or spell.get('identity')!=source['old_identity']
                or seed.get('seed_source_row_identity') not in source['original_seed_row_hashes']
                or _held_ref(seed['seed_source_ref'])!=source['original_uid_intervals_ref']
                or not _held_quantity(spell.get('committed_prior_raw_quantity'))>0
                or not _held_session(seed['signal_session'])<_held_session(spell['seed_admitted_at'])<=source['post_split_trading_session']
                or known>(day+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')):
            raise HeldLineageUnavailable('EXACT_OWN_IMMUTABLE_HELD_SEED_AND_SOURCE_CLOCK_REQUIRED',asset=asset)
        fp=source['runtime_typed_share_event_fingerprint'];post=source['post_split_trading_session']
        if str(day.date())==post:
            matches=[r for r in self.share_events if r['fp']==fp and r['ticker']==asset and r['day']==post]
            if len(matches)!=1:raise HeldLineageUnavailable('EXACT_OWN_ACTION_DAY_SHARE_CATALOGUE_REQUIRED',asset=asset)
            actual=self._share_transition(asset,matches[0],ctx,spell,source['old_identity'])
            if (actual['actual_before_quantity_evidence_ref']['account_id']!=book.account_id
                    or not _held_equal(actual['share_ratio'],.1)
                    or not _held_equal(actual['after_raw_quantity'],actual['before_raw_quantity']*.1)):
                raise HeldLineageUnavailable('EXACT_OWN_ORIGINAL_SPLIT_POSITION_SOURCE_AND_RESEARCH_UNITS_REQUIRED',asset=asset)
            phase='CURRENT_ORIGINAL_OWNER_PREOPEN_RESEARCH_EFFECT_PENDING_ATOMIC_BOOK_COMMIT'
        else:
            matches=[r for r in spell.get('processed_share_transitions',()) if r.get('event_fingerprint')==fp]
            if len(matches)!=1:raise HeldLineageUnavailable('EXACT_OWN_COMMITTED_SHARE_CHAIN_REQUIRED',asset=asset)
            actual=matches[0];phase='OWN_BOOK_ALREADY_COMMITTED_ORIGINAL_SHARE_CHAIN'
            if (actual.get('position_id')!=spell['position_id'] or actual.get('kind')!='SPLIT' or actual.get('session')!=post
                    or actual.get('old_identity')!=source['old_identity'] or actual.get('new_identity')!=source['old_identity']
                    or actual.get('source_ref')!=source['original_event_binding_ref'] or actual.get('owner_ref')!=source['account_owner_ref']
                    or not _held_quantity(actual['before_raw_quantity'])>0
                    or not _held_equal(actual['after_raw_quantity'],actual['before_raw_quantity']*.1)):
                raise HeldLineageUnavailable('EXACT_OWN_ORIGINAL_SPLIT_POSITION_SOURCE_AND_RESEARCH_UNITS_REQUIRED',asset=asset)
        return dict(role='ORIGINAL_ISSUER_BOUND_OWN_HELD_ACCOUNTING_LABEL_ONLY',account_id=book.account_id,
            position_id=spell['position_id'],decision_session=_held_session(day),seed_source_ref=deepcopy(seed['seed_source_ref']),
            seed_source_row_identity=seed['seed_source_row_identity'],immutable_admission_identity=deepcopy(source['old_identity']),
            public_current_issuer_CUSIP=source['public_current_CUSIP'],mapping_sid='CUSIP:'+source['public_current_CUSIP'],
            source_ref=deepcopy(source['source_ref']),facts_ref=deepcopy(source['facts_ref']),source_available_at=source['source_available_at'],
            phase=phase,own_original_share_effect=deepcopy(actual),original_quantity_multiplier=.1,
            original_research_fractional_contract_unchanged=True,issuer_roundup_applied=False,
            broker_nominee_actual_quantity_certified=False,new_UID_pool_row=False,BUY_permission=False,risk_identity_alias=False,
            historical_observations_relabelled=False,quantity_effect=False,strict_PIT=False)

    def _mapping(self, asset, day, raw_code, legal_identity, *, held_accounting_proof=None):
        """Validate the frozen accounting label, never make it a security seed.

        Source issuer IDs and raw transport IDs are distinct namespaces. Their
        existing accounting-label bridge grants no historical availability,
        CUSIP identity, cash entitlement, quote or settlement qualification.
        Current legal entry/held identity comes from the separate source gate.
        """
        rows=[r for r in self.mapping['records'] if r['ticker']==asset
              and pd.Timestamp(r['start'])<=day<pd.Timestamp(r['end'])]
        if len(rows)!=1 or rows[0]['coordinate']!='RAW_ACTUAL_SHARE':
            raise HeldLineageUnavailable('EXACT_CURRENT_RAW_ACCOUNTING_MAPPING_REQUIRED',asset=asset)
        row=rows[0];basis=self.mapping.get('basis_by_ticker',{}).get(asset)
        if not isinstance(basis,dict):
            raise HeldLineageUnavailable('EXPLICIT_FROZEN_ACCOUNTING_MAPPING_BASIS_REQUIRED',asset=asset)
        kind=basis.get('kind')
        audit=dict(kind=kind,mapping_sid=row['sid'],raw_code=raw_code,
            basis_content_sha256=content_hash(basis),mapping_ref=self.binding['mapping_ref'],
            role='ACCOUNTING_LABEL_REPRESENTATION_ONLY_NOT_CURRENT_SECURITY_AUTHORITY',
            current_security_identity_granted=False,historical_availability_granted=False,
            cash_permission_granted=False,quote_qualification_granted=False,
            terminal_or_settlement_qualification_granted=False)
        if kind=='FROZEN_RAW_TRANSPORT_INSTRUMENT_COORDINATE':
            rawref=_held_ref(self.base._components['reader'].sources['raw_open_close'])
            if (row['sid']!='FROZEN_RAW_TRANSPORT_CODE:'+raw_code
                    or basis.get('source_sid')!=row['sid']
                    or _held_ref(basis.get('source_ref'))!=rawref
                    or basis.get('not_a_CUSIP_claim') is not True):
                raise HeldLineageUnavailable('EXACT_CURRENT_RAW_ACCOUNTING_MAPPING_REQUIRED',asset=asset)
            audit['basis_source_ref']=rawref
        elif kind=='EXACT_REUSED_SOURCE_CASH_ISSUER_CLASS':
            cashref=_held_ref(self.binding['account_input_refs']['cash_kwargs'])
            cover=self.events.get('entitlement_source_binding',{})
            tickers=self.events.get('entitlement_security_tickers',{})
            if (basis.get('source_sid')!=row['sid']
                    or _held_ref(basis.get('source_ref'))!=cashref
                    or cover.get('status')!='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND'
                    or cover.get('security_tickers')!=tickers
                    or tickers.get(row['sid'])!=asset
                    or sum(t==asset for t in tickers.values())!=1):
                raise HeldLineageUnavailable('EXACT_EXISTING_ISSUER_ACCOUNTING_LABEL_BINDING_REQUIRED',asset=asset)
            # Source descendants retain their parent's identity proofs. Inspect
            # identity fields only; never read cash rates or price predicates.
            proofs=[];node=cover;seen=set();depth=0
            while node:
                if not isinstance(node,dict) or id(node) in seen:
                    raise HeldLineageUnavailable('EXACT_EXISTING_IDENTITY_PROOF_CHAIN_REQUIRED',asset=asset)
                seen.add(id(node));manifest=node.get('manifest',{})
                proofs.extend((proof,depth) for proof in manifest.get('proofs',()))
                node=manifest.get('parent_source_binding');depth+=1
            events=[r for r in self.cash_events if r['ticker']==asset]
            role='EXACT_PARENT_CASH_CORROBORATION_NO_NEW_EVENT'
            event_fps={r['fp'] for r in events}
            # A corrupted top fingerprint cannot silently drop corroboration
            # still linked to this asset by its exact parent ref or subject.
            for proof,_ in proofs:
                if proof.get('event_binding_role')!=role: continue
                current=proof.get('identity',{})
                subject=current.get('identity',{}) if isinstance(current,dict) else {}
                original_ref=proof.get('original_typed_event_ref',{})
                parent_fp=original_ref.get('event_fingerprint') if isinstance(original_ref,dict) else None
                fp=proof.get('event_fingerprint')
                linked=(fp in event_fps or parent_fp in event_fps
                    or isinstance(subject,dict) and (subject.get('security_id')==row['sid'] or subject.get('ticker')==asset))
                if linked and (fp!=parent_fp or sum(r['fp']==fp for r in events)!=1):
                    raise HeldLineageUnavailable('EXACT_PARENT_CASH_ACCOUNTING_CORROBORATION_REQUIRED',asset=asset)
            identity_proofs=[]
            for item in events:
                event=item.get('event');fp=item['fp']
                matches=[(p,location) for p,location in proofs if p.get('event_fingerprint')==fp]
                exact=[(p.get('identity'),location) for p,location in matches if p.get('event_binding_role')!=role]
                corroborations=[(p,location) for p,location in matches if p.get('event_binding_role')==role]
                if len(corroborations)>1:
                    raise HeldLineageUnavailable('EXACT_PARENT_CASH_ACCOUNTING_CORROBORATION_REQUIRED',asset=asset)
                if (not isinstance(event,self.typed_classes['cash']) or isinstance(event,self.typed_classes['terminal'])
                        or _source_value(event,'old_security_id')!=row['sid'] or len(exact)!=1
                        or not isinstance(exact[0][0],dict)):
                    raise HeldLineageUnavailable('EXACT_TYPED_ISSUER_ACCOUNTING_IDENTITY_PROOF_REQUIRED',asset=asset)
                envelope,original_depth=exact[0];identity=envelope.get('identity',{})
                if not isinstance(identity,dict):
                    raise HeldLineageUnavailable('EXACT_EXISTING_ISSUER_CLASS_NAMESPACE_REQUIRED',asset=asset)
                cls=identity.get('security_type')
                prefix={'COMMON_STOCK':'SOURCE_ISSUER_COMMON_CLASS:',
                        'AMERICAN_DEPOSITARY_SHARE':'SOURCE_ISSUER_ADS_CLASS:'}.get(cls)
                if (not isinstance(identity,dict)
                        or set(identity)!={'security_id','identity_kind','issuer','ticker','listing_identity','security_type'}
                        or identity.get('security_id')!=row['sid'] or identity.get('ticker')!=asset
                        or identity.get('identity_kind')!='SOURCE_DERIVED_ISSUER_COMMON_CLASS'
                        or prefix is None or not row['sid'].startswith(prefix)
                        or not isinstance(identity.get('issuer'),str) or not identity['issuer'].strip()
                        or not isinstance(envelope.get('source_reference'),str) or not envelope['source_reference'].strip()
                        or not isinstance(envelope.get('source_fingerprint'),str)
                        or len(envelope['source_fingerprint'])!=64
                        or any(c not in '0123456789abcdef' for c in envelope['source_fingerprint'])
                        # Original cash proof uses 79cb canonical_bytes (ASCII
                        # escaped metadata), distinct from typed-state hashes.
                        or envelope.get('identity_payload_sha256')!=hashlib.sha256(json.dumps(
                            identity,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str).encode()).hexdigest()):
                    raise HeldLineageUnavailable('EXACT_EXISTING_ISSUER_CLASS_NAMESPACE_REQUIRED',asset=asset)
                # Reuse the source-label ontology only as syntax validation.
                # Its returned SID never replaces this frozen label or legal UID.
                from scripts.research.a2.data.joint_cash_bindings import source_derived_security_id
                try:
                    source_derived_security_id(identity['issuer'],asset,identity['listing_identity'],cls)
                except ValueError as exc:
                    raise HeldLineageUnavailable('EXACT_EXISTING_ISSUER_CLASS_NAMESPACE_REQUIRED',asset=asset) from exc
                representation=dict(event_fingerprint=fp,identity=identity,
                    identity_payload_sha256=envelope['identity_payload_sha256'],
                    identity_source_reference=envelope.get('source_reference'),
                    identity_source_fingerprint=envelope.get('source_fingerprint'),
                    identity_available_at_as_recorded=envelope.get('available_at'),
                    historical_availability_qualified=False,CUSIP_equivalence_granted=False)
                checked=[]
                for proof,proof_depth in corroborations:
                    current=proof.get('identity')
                    original_ref=dict(event_id=_source_value(event,'event_id'),event_fingerprint=fp)
                    if (original_depth<=proof_depth
                            or not isinstance(current,dict) or current.get('identity')!=identity
                            or current.get('identity_payload_sha256')!=envelope['identity_payload_sha256']
                            or proof.get('original_typed_event_ref')!=original_ref
                            or _source_value(event,'ticker')!=asset
                            or proof.get('original_source_reference')!=_source_value(event,'source_reference')
                            or proof.get('original_source_fingerprint')!=_source_value(event,'source_fingerprint')
                            or proof.get('original_available_at')!=_source_value(event,'available_at')
                            or proof.get('original_typed_fields_and_fingerprint_preserved') is not True
                            or proof.get('original_frozen_classification_unchanged') is not True
                            or proof.get('descendant_clock_is_new_source_account_identity') is not True
                            or current.get('CUSIP_claim') is not False
                            or not isinstance(current.get('source_reference'),str) or not current['source_reference'].strip()
                            or not isinstance(current.get('source_fingerprint'),str)
                            or len(current['source_fingerprint'])!=64
                            or any(c not in '0123456789abcdef' for c in current['source_fingerprint'])):
                        raise HeldLineageUnavailable('EXACT_PARENT_CASH_ACCOUNTING_CORROBORATION_REQUIRED',asset=asset)
                    checked.append(dict(event_binding_role=role,original_typed_event_ref=original_ref,
                        original_identity_proof_chain_depth=original_depth,corroboration_proof_chain_depth=proof_depth,
                        source_fact_ref=_held_ref(proof.get('source_fact_ref')),
                        identity=current['identity'],identity_payload_sha256=current['identity_payload_sha256'],
                        identity_source_reference=current['source_reference'],
                        identity_source_fingerprint=current['source_fingerprint'],
                        identity_available_at_as_recorded=current.get('available_at'),
                        original_source_reference=proof['original_source_reference'],
                        original_source_fingerprint=proof['original_source_fingerprint'],
                        original_available_at=proof['original_available_at'],
                        new_source_publication_bound=proof.get('new_source_publication_bound'),
                        descendant_ordinary_cash_clock=proof.get('descendant_ordinary_cash_clock'),
                        descendant_clock_is_new_source_account_identity=True,
                        original_typed_fields_and_fingerprint_preserved=True,
                        original_frozen_classification_unchanged=True,
                        historical_availability_qualified=False,CUSIP_equivalence_granted=False))
                if checked: representation['exact_parent_cash_corroborations']=checked
                identity_proofs.append(representation)
            if not identity_proofs:
                raise HeldLineageUnavailable('EXACT_TYPED_ISSUER_ACCOUNTING_IDENTITY_PROOF_REQUIRED',asset=asset)
            audit.update(basis_source_ref=cashref,identity_representation_proofs=identity_proofs)
        elif kind=='FROZEN_POST_VERIFIED_CUSIP_SPLIT_AND_TERMINAL_BINDING':
            # Use only the already qualified current UID or admitted held seed.
            # The post-verified reconstruction itself is not read or adopted.
            # The entitlement dictionary covers cash events, not all holdings;
            # it is not authority for this literal, directly verified label.
            direct=(legal_identity.get('security_id_type')=='CUSIP'
                and legal_identity.get('cusip')==legal_identity.get('security_id')
                and legal_identity.get('raw_code')==raw_code and row['sid']=='CUSIP:'+legal_identity['security_id'])
            if not direct:
                proof=held_accounting_proof
                sources=[s for s in getattr(self,'held_accounting_sources',()) if isinstance(proof,dict) and s['source_ref']==proof.get('source_ref')]
                if (len(sources)!=1 or proof.get('role')!='ORIGINAL_ISSUER_BOUND_OWN_HELD_ACCOUNTING_LABEL_ONLY'
                        or proof.get('account_id')!=self.held_accounting_account_id or proof.get('decision_session')!=_held_session(day)
                        or proof.get('immutable_admission_identity')!=legal_identity or legal_identity!=sources[0]['old_identity']
                        or proof.get('mapping_sid')!=row['sid'] or row['sid']!='CUSIP:'+sources[0]['public_current_CUSIP']
                        or raw_code!=legal_identity['raw_code'] or proof.get('broker_nominee_actual_quantity_certified') is not False
                        or any(proof.get(k) is not False for k in ('new_UID_pool_row','BUY_permission','risk_identity_alias','quantity_effect'))):
                    raise HeldLineageUnavailable('DIRECT_CURRENT_LEGAL_ID_ACCOUNTING_COORDINATE_REQUIRED',asset=asset)
                audit.update(bridge='EXPLICIT_ORIGINAL_ISSUER_OWN_HELD_ACCOUNTING_LABEL_RELATION',
                    immutable_admission_identity_preserved=True,public_current_issuer_CUSIP=sources[0]['public_current_CUSIP'],
                    own_held_accounting_source_proof=proof)
            else:
                audit.update(bridge='DIRECT_CURRENT_LEGAL_ID_ACCOUNTING_COORDINATE')
            audit.update(
                direct_legal_identity=legal_identity,
                direct_identity_authority_role='ORIGINAL_CURRENT_UID_OR_ACCEPTED_HELD_IDENTITY_ONLY',
                inherited_postverified_basis_proof_ref=_held_ref(basis.get('proof')),
                postverified_basis_proof_not_consumed=True)
        else:
            raise HeldLineageUnavailable('UNKNOWN_FROZEN_ACCOUNTING_MAPPING_BASIS',asset=asset)
        return row,audit
    def _quantity_after(self, asset, ctx, spell):
        rows=[x['actual_owner_fill'] for x in spell['pending_fill_refs']]
        day=_held_session(ctx.signal_date)
        if rows:
            row=rows[0]
            if row['execution_date']!=day:
                raise HeldLineageUnavailable('EXACT_CURRENT_ACTUAL_FILL_REQUIRED',asset=asset)
            return row['index_units_before'], 'FIRST_ACTUAL_FILL_BEFORE_AFTER_PRE_OPEN', dict(
                owner_ref=self.binding['fill_owner_ref'], account_id=row['path_id'],
                order_id=row['order_id'], execution_session=day, quantity_field='index_units_before',
                actual_raw_quantity=row['index_units_before'])
        column=self.base.master_assets.index(asset)
        q=float(_vector(ctx,'current_units',len(self.base.master_assets))[column])
        return q, 'DIRECT_CURRENT_RAW_QUANTITY_NO_ASSET_FILLS', dict(
            owner_ref=self.binding['fill_owner_ref'],session=day,
            quantity_field='current_units',actual_raw_quantity=q,asset_fill_count=0)

    def _share_transition(self, asset, row, ctx, spell, identity):
        day=_held_session(ctx.signal_date); payload=self.unit_effects.get(row['fp'])
        if payload is None:
            raise HeldLineageUnavailable('ACTUAL_OWNER_UNIT_EFFECT_REQUIRED',asset=asset)
        opened=(pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
        known=pd.Timestamp(payload['known_at'])
        if (pd.isna(known) or known.tzinfo is None or known>opened
                or payload['old_ticker']!=asset or payload['new_ticker']!=asset
                or payload['old_security_id']!=payload['new_security_id']):
            raise HeldLineageUnavailable('CAUSAL_SAME_SECURITY_SHARE_SOURCE_REQUIRED',asset=asset)
        kind=str(payload['typed_kind'])
        if kind not in ('FORWARD_SPLIT','REVERSE_SPLIT','OTHER_SHARE_COUNT_TRANSFORM'):
            raise HeldLineageUnavailable('UNPROVED_SHARE_CONVERSION_IDENTITY',asset=asset)
        ratio=_held_quantity(payload['quantity_multiplier'])
        if ratio<=0 or not _held_equal(payload['unit_before_quantity'],1) or not _held_equal(payload['unit_after_quantity'],ratio):
            raise HeldLineageUnavailable('ORIGINAL_UNIT_FACTOR_COMMITMENT_CONFLICT',asset=asset)
        actual=self.lifecycle_effects.get(day)
        sids=[] if actual is None else [sid for sid,ticker in actual['security_tickers'].items() if ticker==asset]
        supplement=None if actual is None else actual.get('original_preopen_raw_positions_by_ticker')
        if len(sids)==1 and sids[0] in actual['positions_before']:
            before=_held_quantity(actual['positions_before'][sids[0]])
            if supplement is not None and asset in supplement and not _held_equal(before,supplement[asset]):
                raise HeldLineageUnavailable('ORIGINAL_PREOPEN_QUANTITY_SOURCES_CONFLICT',asset=asset)
            before_evidence=dict(owner_ref=self.binding['account_owner_ref'],account_id=actual['account_id'],
                session=day,security_id=sids[0],quantity_field='positions_before',actual_raw_quantity=before)
        elif len(sids)==0 and isinstance(supplement,dict) and asset in supplement:
            if actual.get('original_preopen_quantity_role')!='DIRECT_ORIGINAL_OWNER_PREOPEN_UNITS_TIMES_PRIOR_FACTOR':
                raise HeldLineageUnavailable('EXACT_ORIGINAL_OWNER_PREOPEN_QUANTITY_ROLE_REQUIRED',asset=asset)
            before=_held_quantity(supplement[asset])
            before_evidence=dict(owner_ref=self.binding['account_owner_ref'],account_id=actual['account_id'],
                session=day,ticker=asset,quantity_field='original_preopen_raw_positions_by_ticker',
                quantity_role=actual['original_preopen_quantity_role'],actual_raw_quantity=before)
        else:
            raise HeldLineageUnavailable('DIRECT_ORIGINAL_PREOPEN_RAW_BEFORE_REQUIRED',asset=asset)
        if not _held_equal(before,spell['committed_prior_raw_quantity']):
            raise HeldLineageUnavailable('ACTUAL_PREOPEN_PRIOR_QUANTITY_CONFLICT',asset=asset)
        after,role,evidence=self._quantity_after(asset,ctx,spell)
        return dict(qualified=True,typed_event=True,stage='PRE_OPEN',kind='SPLIT',session=day,
            event_fingerprint=row['fp'],before_raw_quantity=before,
            quantity_before_role='DIRECT_ORIGINAL_PRE_OPEN_RAW_BEFORE',actual_before_quantity_evidence_ref=before_evidence,
            after_raw_quantity=after,old_identity=identity,new_identity=identity,share_ratio=ratio,
            quantity_after_role=role,actual_quantity_evidence_ref=evidence,
            source_ref=self.binding['original_event_binding_ref'],owner_ref=self.binding['account_owner_ref'])

    def _terminal_transition(self, asset, row, ctx, spell, identity):
        day=_held_session(ctx.signal_date); p=self.lifecycle_effects.get(day)
        if p is None:
            raise HeldLineageUnavailable('ACTUAL_TERMINAL_PREOPEN_QUANTITY_REQUIRED',asset=asset)
        sid=_source_value(row['event'],'old_security_id')
        known=pd.Timestamp(_source_value(row['event'],'available_at'))
        records=[r for r in p['terminal_effect_records'] if r.get('event_fingerprint')==row['fp']
                 and r.get('ticker')==asset and r.get('old_security_id')==sid
                 and r.get('phase')=='SECURITY_EXTINGUISHED' and _held_session(r['session'])==day]
        if (len(records)!=1 or p['security_tickers'].get(sid)!=asset
                or sid not in p['positions_before'] or sid not in p['positions_after']
                or p['positions_after'][sid]!=0 or pd.isna(known) or known.tzinfo is None
                or known>pd.Timestamp(p['session_open_at'])):
            raise HeldLineageUnavailable('EXACT_CAUSAL_TERMINAL_OWNER_EFFECT_REQUIRED',asset=asset)
        before=_held_quantity(p['positions_before'][sid])
        if not _held_equal(before,spell['committed_prior_raw_quantity']):
            raise HeldLineageUnavailable('TERMINAL_CURRENT_RAW_PRIOR_CONFLICT',asset=asset)
        return dict(qualified=True,typed_event=True,stage='PRE_OPEN',kind='TERMINAL',session=day,
            event_fingerprint=row['fp'],before_raw_quantity=before,after_raw_quantity=0.,
            old_identity=identity,new_identity=identity,quantity_after_role='DIRECT_ORIGINAL_TERMINAL_PRE_OPEN_AFTER',
            actual_quantity_evidence_ref=dict(owner_ref=self.binding['account_owner_ref'],session=day,
                security_id=sid,quantity_field='positions_after',actual_raw_quantity=0.,
                terminal_effect_record=records[0]),source_ref=self.binding['original_event_binding_ref'],
            owner_ref=self.binding['account_owner_ref'])

    def _closed_sell_spell_entry_binding(self, asset, day, ctx, domain, spells, entry, intervals, refs, book):
        """Separate a proved closed old spell from a new entry; never alias classes."""
        if getattr(self, 'closed_sell_spell_entry_rule', None) != CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE:
            return None
        ix=self.base.master_assets.index(asset); daystr=str(day.date())
        if (domain['held_mask'][ix] or len(spells)!=1 or spells[0]['role']!='ACCEPTED_POSITION'
                or entry is None or float(_vector(ctx,'current_units',len(self.base.master_assets))[ix])!=0
                or float(_vector(ctx,'current_weights',len(self.base.master_assets))[ix])!=0):
            return None
        spell=spells[0]; old=spell['identity']; seed=spell['seed']
        current=_held_identity(entry)
        if any(old[k]!=current[k] for k in current if k!='share_class'):
            return None
        j=self.base.market_dates.get_loc(day)
        if j<=0: return None
        previous=_held_session(self.base.market_dates[j-1])
        rows=intervals.loc[intervals.ticker.eq(asset)].to_dict('records')
        prior=[r for r in rows if content_hash(r)==seed.get('seed_source_row_identity')]
        now=[r for r in rows if content_hash(r)==entry['seed_source_row_identity']]
        if (len(prior)!=1 or len(now)!=1
                or _held_ref(seed.get('seed_source_ref'))!=refs['uid_intervals']
                or _held_ref(entry['seed_source_ref'])!=refs['uid_intervals']): return None
        prior,now=prior[0],now[0]
        if (prior['mapping_status']!='RESOLVED' or now['mapping_status']!='RESOLVED'
                or _held_text(prior['issuer_name'])!=_held_text(now['issuer_name'])
                or not _held_source_row_descriptor_bridge(prior,old,self.descriptor_bridges)
                or not pd.Timestamp(prior['effective_start'])<=pd.Timestamp(seed['signal_session'])<=pd.Timestamp(prior['effective_end'])
                or pd.Timestamp(prior['effective_end'])<pd.Timestamp(previous)
                or not _held_source_row_descriptor_bridge(now,current,self.descriptor_bridges)
                or not pd.Timestamp(now['effective_start'])<=day<=pd.Timestamp(now['effective_end'])
                or not _held_class_equal(old['share_class'],current['share_class'])
                    and pd.Timestamp(now['effective_start'])!=day): return None
        pending=spell['pending_fill_refs']; quantity=_held_quantity(spell['committed_prior_raw_quantity'])
        if quantity<=0 or not pending: return None
        fills=[]
        for item in pending:
            row=item['actual_owner_fill']
            if (item.get('candidate_seed') is not None or _held_ref(item['fill_owner_ref'])!=_held_ref(self.binding['fill_owner_ref'])
                    or row['path_id']!=book.account_id or row['ticker']!=asset or row['side']!='SELL'
                    or _held_session(row['execution_date'])!=daystr or _held_session(row['signal_date'])!=previous
                    or _held_quantity(row['fractional_shares'])<=0
                    or not _held_equal(row['index_units_before'],quantity)
                    or not _held_equal(quantity-row['fractional_shares'],row['index_units_after'])): return None
            quantity=_held_quantity(row['index_units_after']);fills.append(dict(row))
        if quantity!=0: return None
        return dict(role='CLOSED_ACTUAL_SELL_SPELL_AND_CURRENT_ENTRY_SOURCE_ROLES_DISTINCT',
            decision_session=daystr,prior_identity_session=previous,position_id=spell['position_id'],
            held_spell_identity=dict(old),current_entry_identity=current,
            original_seed_source_ref=seed['seed_source_ref'],original_seed_source_row_identity=seed['seed_source_row_identity'],
            original_seed_signal_session=_held_session(seed['signal_session']),original_seed_admitted_at=spell['seed_admitted_at'],
            current_entry_source_ref=entry['seed_source_ref'],current_entry_source_row_identity=entry['seed_source_row_identity'],
            held_spell_historical_source_epoch=seed['historical_source_epoch'],
            current_entry_historical_source_epoch=entry['historical_source_epoch'],issuer_name=prior['issuer_name'],
            exact_actual_closing_fills=fills,fill_owner_ref=self.binding['fill_owner_ref'],
            closed_raw_quantity=0,class_equivalence_granted=False,quantity_effect=False,
            historical_observations_relabelled=False,strict_PIT=False,production_qualified=False,
            quote_qualified=False,certified_NAV=False)

    def session(self, ctx, original, book):
        """Bounded source projections for original entries and actual held spells."""
        day=pd.Timestamp(_held_session(ctx.signal_date)); daystr=str(day.date())
        from copy import deepcopy
        domain=causal_held_domain(ctx,original['mask'],
            excluded_tickers=getattr(self,'investment_exclusion_tickers',()))
        needed=book.required_guard_assets(ctx)
        eligible=tuple(self.base.master_assets[i] for i in np.flatnonzero(domain['eligible_mask']))
        projected=tuple(a for a in self.base.master_assets if a in set(eligible)|set(needed))
        c=self.base._components; reader=c['reader']
        if _held_ref(c['refs']['source'])!=_held_ref(self.binding['source_manifest_ref']):
            raise HeldLineageUnavailable('EXACT_ORIGINAL_METADATA_SOURCE_REQUIRED')
        stop=day+pd.Timedelta(days=1) if day+pd.Timedelta(days=1)<pd.Timestamp('2026-01-01') else None
        intervals=reader.read('uid_intervals',self.IDENTITY_COLUMNS,date_field='effective_start',stop=stop,tickers=projected)
        raw=reader.read('raw_open_close',('ticker','trade_date','code'),date_field='trade_date',day=day,tickers=projected)
        # Reuse only already-projected metadata within this one session.
        interval_starts=pd.to_datetime(intervals.effective_start)
        interval_ends=pd.to_datetime(intervals.effective_end)
        raw_dates=pd.to_datetime(raw.trade_date)
        interval_indices=intervals.groupby('ticker',sort=False).indices
        raw_indices=raw.groupby('ticker',sort=False).indices
        refs={k:_held_ref(reader.sources[k]) for k in ('uid_intervals','raw_open_close','share_ca_audit')}
        lineages=book.source_lineages(); seeds={}; guards={}; identities={}; histories={}; closed_entry_bindings={}
        audit_batch=None
        def raw_row(a):
            ix=raw_indices.get(a,np.empty(0,dtype=int))
            return raw.iloc[ix].loc[raw_dates.iloc[ix].eq(day)]
        for asset in eligible:
            ix=interval_indices.get(asset,np.empty(0,dtype=int))
            active=intervals.iloc[ix].loc[interval_starts.iloc[ix].le(day)&interval_ends.iloc[ix].ge(day)]
            rows=raw_row(asset); ix=self.base.master_assets.index(asset)
            if len(active)!=1 or len(rows)!=1 or not self.present[self.base.market_dates.get_loc(day),ix]:
                raise HeldLineageUnavailable('UNIQUE_CURRENT_ENTRY_IDENTITY_AND_RAW_KEY_REQUIRED',asset=asset)
            row=active.iloc[0].to_dict(); code=str(rows.iloc[0]['code'])
            if row['mapping_status']!='RESOLVED' or row['security_id']!=original['record']['asset_uids'][asset] or row['moomoo_transport_code']!=code:
                raise HeldLineageUnavailable('CURRENT_ENTRY_IDENTITY_CONFLICT',asset=asset)
            identity=_held_identity(dict(row,share_class=row['title_of_class'],raw_code=code,raw_actual_share_coordinate='RAW_ACTUAL_SHARE'))
            _,mapping_basis=self._mapping(asset,day,code,identity)
            seeds[asset]=dict(identity,qualified=True,historical_observations_relabelled=False,
                identity_asof=pd.Timestamp(ctx.signal_asof).isoformat(),seed_source_ref=refs['uid_intervals'],
                seed_source_row_identity=content_hash(row),historical_source_epoch=original['record']['asset_epochs'][asset],
                accounting_mapping_basis_proof=mapping_basis)
            identities[asset]=identity; histories[asset]=seeds[asset]['historical_source_epoch']
        for asset in needed:
            spells=lineages.get(asset,())
            if not spells or any(s['identity'] is None or s['seed'] is None for s in spells):
                raise HeldLineageUnavailable('ACTUAL_HELD_CAUSAL_ADMISSION_SOURCE_REQUIRED',asset=asset)
            spells=deepcopy(spells); metadata_bindings=[]
            transports=getattr(self,'identity_transports',())
            for spell in spells:
                evidence=_held_identity_metadata_binding(spell['seed'],spell['identity'],day,transports,held_spell=spell)
                if evidence is not None:
                    if not any(content_hash(row)==evidence['new_source_row_identity']
                            for row in intervals.loc[intervals.ticker.eq(asset)].to_dict('records')):
                        raise HeldLineageUnavailable('EXACT_CURRENT_ORIGINAL_METADATA_TRANSPORT_ROW_REQUIRED',asset=asset)
                    spell['identity']=deepcopy(evidence['current_identity'])
                    if evidence not in metadata_bindings:metadata_bindings.append(evidence)
            identity=spells[-1]['identity']
            closed_entry=(self._closed_sell_spell_entry_binding(asset,day,ctx,domain,spells,
                seeds.get(asset),intervals,refs,book) if not metadata_bindings else None)
            if asset in identities and not _held_security_identity_equal(identities[asset],identity,self.descriptor_bridges) and closed_entry is None:
                raise HeldLineageUnavailable('CURRENT_ENTRY_AND_HELD_METADATA_IDENTITY_CONFLICT',asset=asset,
                    decision_session=daystr,current_entry_identity=deepcopy(identities[asset]),
                    current_entry_seed=deepcopy(seeds[asset]),held_spell_identity=deepcopy(identity),
                    held_spell_source_evidence=[{k:deepcopy(s.get(k)) for k in
                        ('role','position_id','identity','seed','seed_admitted_at','pending_fill_refs')} for s in spells])
            if closed_entry is not None:
                closed_entry_bindings[asset]=closed_entry
            else:
                identities[asset]=identity
            if closed_entry is not None:
                pass  # Entry identity/history keep the exact current original P roles.
            elif metadata_bindings and asset in original['record']['asset_uids']:
                if original['record']['asset_uids'][asset]!=identity['security_id']:
                    raise HeldLineageUnavailable('CURRENT_PRIMARY_AND_HELD_METADATA_UID_CONFLICT',asset=asset)
                histories[asset]=original['record']['asset_epochs'][asset]
            elif metadata_bindings:
                j=self.base.market_dates.get_loc(day)
                cutoff=producer._clock(self.base.market_dates[j-1]) if j>0 else None
                past=[e for e in c.get('support',{}).get('events',())
                    if cutoff is not None and pd.Timestamp(e['decision_asof'])<=cutoff
                    and e['asset_uids'].get(asset)==identity['security_id']]
                if not past:
                    raise HeldLineageUnavailable('EXACT_ORIGINAL_CURRENT_UID_HISTORICAL_EPOCH_WITNESS_REQUIRED',asset=asset)
                histories[asset]=max(past,key=lambda e:pd.Timestamp(e['decision_asof']))['asset_epochs'][asset]
            else:
                histories[asset]=spells[-1]['seed']['historical_source_epoch']
            if any(not _held_security_identity_equal(s['identity'],identity,self.descriptor_bridges) for s in spells):
                raise HeldLineageUnavailable('SAME_DAY_UNPROVED_IDENTITY_REENTRY',asset=asset)
            start=min(pd.Timestamp(s['seed']['signal_session']) for s in spells)
            own_accounting=self._own_held_issuer_accounting_proof(asset,day,ctx,spells,eligible,book)
            rows=raw_row(asset); mapping,mapping_basis=self._mapping(asset,day,identity['raw_code'],identity,
                held_accounting_proof=own_accounting)
            ix=interval_indices.get(asset,np.empty(0,dtype=int))
            current_interval=intervals.iloc[ix].loc[interval_ends.iloc[ix].ge(start)&interval_starts.iloc[ix].le(day)]
            for r in current_interval.to_dict('records'):
                observed=dict(security_id=r['security_id'],security_id_type=r['security_id_type'],
                    cusip=r['cusip'],share_class=r['title_of_class'],raw_code=r['moomoo_transport_code'],
                    raw_actual_share_coordinate=identity['raw_actual_share_coordinate'])
                bound_old=(bool(metadata_bindings) and any(
                    (content_hash(r)==t['old_row_hash'] or _held_pre_action_class_a_past_row(r,t)
                    or (t.get('pre_action_existing_held') is True and t.get('pre_action_class_a_seed_extension') is not True
                    and _held_source_row_descriptor_bridge(r,t['old_identity'],self.descriptor_bridges)
                    and r['issuer_name']==t['old_row']['issuer_name']
                    and r['effective_end']<t['new_row']['effective_start'])
                    or _held_post_action_public_class_a_past_row(r,t,metadata_bindings,identity,day))
                    and _held_security_identity_equal(identity,t['new_identity']) for t in transports))
                distinct_closed_entry=(closed_entry is not None
                    and content_hash(r)==closed_entry['current_entry_source_row_identity']
                    and _held_source_row_descriptor_bridge(r,closed_entry['current_entry_identity'],self.descriptor_bridges))
                if r['mapping_status']!='RESOLVED' or not (
                        _held_source_row_descriptor_bridge(r,identity,self.descriptor_bridges) or bound_old or distinct_closed_entry):
                    raise HeldLineageUnavailable('HELD_DATED_SECURITY_COORDINATE_CONFLICT',asset=asset)
            share=[r for r in self.share_events if r['ticker']==asset and start<=pd.Timestamp(r['day'])<=day]
            cash=[r for r in self.cash_events if r['ticker']==asset and start<=pd.Timestamp(r['day'])<=day]
            terminal=[r for r in self.terminal_events if r['ticker']==asset and start<=pd.Timestamp(r['day'])<=day]
            typedkeys={(r['ticker'],r['day']) for r in share+cash+terminal}
            typedsharekeys={(r['ticker'],r['day']) for r in share+terminal}
            declared_residual=[r for r in self.unsupported if r['ticker']==asset and start<=pd.Timestamp(r['effective_date'])<=day]
            residual,nonapplicable=[],[]
            for event in declared_residual:
                proof=self._account_prefix_nonapplicability(event,ctx,book.account_id)
                if proof is None:residual.append(event)
                else:nonapplicable.append(proof)
            if audit_batch is None:
                # Metadata only, bounded to current required-held prefixes.
                # Qualification remains in the original per-asset loop.
                audit_starts=[pd.Timestamp(s['seed']['signal_session'])
                    for a in needed for s in lineages.get(a,())
                    if s.get('seed') is not None]
                audit_assets=tuple(a for a in self.base.master_assets if a in set(needed))
                audit_batch=reader.read('share_ca_audit',self.AUDIT_COLUMNS,
                    date_field='event_date',start=min(audit_starts),stop=stop,tickers=audit_assets)
            audits=audit_batch.loc[audit_batch.ticker.eq(asset)
                &pd.to_datetime(audit_batch.event_date).ge(start)].copy()
            catalogue=[r for r in self.original_events+self.static_events if r['ticker']==asset
                       and start<=pd.Timestamp(r['event_date'])<=day]
            auditrows=audits.to_dict('records')
            auditkeys={(str(r['ticker']),_held_session(r['event_date'])) for r in auditrows
                       if bool(r['share_event']) or bool(r['manual_wolf'])}
            price_only=[r for r in catalogue if r.get('reason')=='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY']
            unknown=[]
            for r in catalogue:
                key=(str(r['ticker']),_held_session(r['event_date']))
                declared_share=(r.get('status') in ('SHARE_ONLY_SUPPORTED','FROZEN_TIER1_SHARE_ONLY_SUPPORTED')
                                or 'quantity_multiplier' in r)
                required=typedsharekeys if declared_share else typedkeys
                if r not in price_only and key not in required: unknown.append(key)
            unknown.extend(sorted(auditkeys-typedsharekeys))
            if residual or unknown:
                raise HeldLineageUnavailable('UNSUPPORTED_DECLARED_SHARE_OR_CASH_SOURCE',asset=asset,
                    unsupported_source_keys=unknown,residual_unsupported_count=len(residual))
            processed=list(dict.fromkeys(r['fp'] for r in share+cash+terminal)); transitions=[]
            current=[r for r in share+terminal if pd.Timestamp(r['day'])==day]
            prior=next((s for s in spells if s['role']=='ACCEPTED_POSITION'),None)
            if len(current)>1 and prior is not None:
                raise HeldLineageUnavailable('UNOBSERVED_INTERMEDIATE_SAME_DAY_SHARE_QUANTITY',asset=asset)
            if prior is not None and current:
                item=current[0]
                transitions.append(self._share_transition(asset,item,ctx,prior,identity) if item in share
                    else self._terminal_transition(asset,item,ctx,prior,identity))
            # A new BUY after PRE_OPEN has no pre-existing holding to transform,
            # but any source share effect must still have a causal unit proof.
            elif current:
                for item in current:
                    if item in share:
                        p=self.unit_effects.get(item['fp']); opened=(day+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
                        known=pd.Timestamp(None if p is None else p['known_at'])
                        if p is None or pd.isna(known) or known.tzinfo is None or known>opened:
                            raise HeldLineageUnavailable('CAUSAL_SHARE_SOURCE_BEFORE_NEW_BUY_REQUIRED',asset=asset)
                    else:
                        raise HeldLineageUnavailable('NEW_BUY_ON_TERMINAL_SECURITY_REJECTED',asset=asset)
            if own_accounting is not None and own_accounting['phase']=='CURRENT_ORIGINAL_OWNER_PREOPEN_RESEARCH_EFFECT_PENDING_ATOMIC_BOOK_COMMIT':
                if transitions!=[own_accounting['own_original_share_effect']]:
                    raise HeldLineageUnavailable('ATOMIC_OWN_SHARE_ACCOUNTING_LABEL_GUARD_REQUIRED',asset=asset)
            terminal_absent=len(rows)==0 and len(transitions)==1 and transitions[0]['kind']=='TERMINAL'
            if (len(rows)!=1 and not terminal_absent or len(rows)==1 and str(rows.iloc[0]['code'])!=identity['raw_code']):
                raise HeldLineageUnavailable('EXACT_CURRENT_HELD_RAW_KEY_REQUIRED',asset=asset)
            ix=self.base.master_assets.index(asset)
            if not terminal_absent and not self.present[self.base.market_dates.get_loc(day),ix]:
                raise HeldLineageUnavailable('ACTUAL_ACCOUNT_RAW_KEY_PRESENCE_REQUIRED',asset=asset)
            guards[asset]=dict(identity,qualified=True,historical_observations_relabelled=False,
                decision_session=daystr,mapping_row_count=1,mapping_start=mapping['start'],
                mapping_end_exclusive=mapping['end'],mapping_raw_code=identity['raw_code'],
                current_accounting_mapping_ref=self.binding['mapping_ref'],current_mapping_row_identity=content_hash(mapping),
                accounting_mapping_basis_proof=mapping_basis,
                raw_key_count=len(rows),raw_key_session=daystr,raw_key_code=identity['raw_code'],
                raw_exact_key_ref=refs['raw_open_close'],raw_key_row_identity=_held_raw_key_row_identity(rows),
                terminal_raw_key_absence=terminal_absent,catalogue_checked_from_session=str(start.date()),
                catalogue_checked_through_session=daystr,declared_catalogue_refs=list(refs.values())+
                    [self.binding[k] for k in ('original_event_binding_ref','static_event_source_ref','source_account_contract_ref')],
                processed_event_fingerprints=processed,unsupported_event_fingerprints=[],identity_conflict_count=0,
                quantity_transitions=transitions,identity_metadata_bindings=metadata_bindings,
                share_class_descriptor_bridge_refs=[r for b in self.descriptor_bridges
                    if identity['security_id']==b['coordinates']['security_id']
                    for r in ([b['source_ref']]+([b['extension_ref']] if 'extension_ref' in b else []))],
                original_residual_unsupported_events=[{k:r.get(k) for k in
                    ('ticker','effective_date','reason','source_reference','source_fingerprint')} for r in declared_residual],
                account_prefix_nonapplicability_proofs=nonapplicable,
                nonshare_quote_diagnostics=[{k:r.get(k) for k in ('ticker','event_date','status','reason','source_fingerprint')}
                    for r in price_only]+[{k:r.get(k) for k in ('ticker','event_date','audit_kind','code')}
                    for r in auditrows if not bool(r['share_event']) and not bool(r['manual_wolf'])],
                quote_qualification_granted=False,original_account_quote_and_unsupported_gates_unchanged=True)
            if closed_entry is not None:
                guards[asset]['closed_spell_current_entry_binding']=closed_entry
        result=dict(domain=domain,entry_seeds=seeds,held_guards=guards,current_identities=identities,
            historical_source_epochs=histories,source_receipt=dict(schema='B_CURRENT_HELD_SOURCE_GUARDS_V1',
                session=daystr,source_binding=self.binding,projected_assets=list(projected),
                entry_seed_count=len(seeds),held_guard_count=len(guards),quantity_guard_proofs=guards,
                source_metadata_only=True,historical_observations_relabelled=False,strict_PIT=False,
                production_qualified=False,quote_qualified=False,certified_NAV=False))
        if closed_entry_bindings:
            result['source_receipt']['closed_spell_current_entry_bindings']=closed_entry_bindings
        return result
class CausalHeldLWInputs:
    """New research descendant: one actual lineage book and whole-state reuse.

    The original provider retains its frozen behavior. Simple consumes only the
    qualified source domain; Joint requests numeric risk separately and lazily.
    """
    def __init__(self, *, base, account_id, sources, supplemental, source_contract,
                 references, reuse_rule, state_loader=None):
        from copy import deepcopy
        if reuse_rule!=CAUSAL_LW_REUSE_RULE:
            raise ExistingRiskInputUnavailable('EXACT_FROZEN_WHOLE_LW_REUSE_RULE_REQUIRED')
        self.base,self.account_id,self.sources=base,_held_text(account_id),sources
        self.investment_exclusion_tickers=tuple(getattr(sources,'investment_exclusion_tickers',()))
        self.supplemental,self.source_contract=deepcopy(supplemental),deepcopy(source_contract)
        self.references,self.reuse_rule=deepcopy(references),deepcopy(reuse_rule)
        self.book=HeldPositionLineageBook(self.account_id,fill_owner_ref=sources.binding['fill_owner_ref'],
            lineage_rule_ref=sources.binding['lineage_rule_ref'],
            descriptor_bridges=getattr(sources,'descriptor_bridges',()),
            identity_transports=getattr(sources,'identity_transports',()))
        self._last=None; self._supplement=None; self._state_loader=state_loader
        self.supplemental_loads_count=0

    @classmethod
    def from_freeze(cls, *, freeze, base_shared, account_id, market_dates, master_assets, source_context):
        return cls._from_freeze(freeze=freeze,base_shared=base_shared,account_id=account_id,
            market_dates=market_dates,master_assets=master_assets,source_context=source_context,
            inherited_runtime_evidence_only=False)

    @classmethod
    def _from_freeze(cls, *, freeze, base_shared, account_id, market_dates, master_assets,
                     source_context, inherited_runtime_evidence_only):
        investment_exclusions=frozen_investment_exclusion_tickers(freeze)
        if tuple(pd.DatetimeIndex(market_dates))!=tuple(base_shared.market_dates) or tuple(map(str,master_assets))!=base_shared.master_assets:
            raise ExistingRiskInputUnavailable('EXACT_SHARED_ORIGINAL_MARKET_DOMAIN_REQUIRED')
        names=('held_support_admission_ref','single_lw_approval_ref','single_lw_preflight_ref',
               'supplemental_lw_state_ref','held_identity_source_binding_ref','runtime_independent_acceptance_ref')
        refs={n:_held_ref(freeze[n]) for n in names}
        values={n:base_shared.interface.read(_causal_pin(base_shared.interface,refs[n])) for n in names}
        approval=values['single_lw_approval_ref']; preflight=values['single_lw_preflight_ref']
        state=values['supplemental_lw_state_ref']; accepted=values['runtime_independent_acceptance_ref']
        _causal_need(approval.get('schema')=='B_SPECIFIC_SINGLE_LW_HUMAN_APPROVAL_V1',
                     'EXACT_SINGLE_LW_HUMAN_APPROVAL_REQUIRED')
        _causal_need(preflight.get('status')=='PASS_SOURCE_NUMERIC_PREFLIGHT_NO_FIT'
                     and preflight.get('new_fits')==0 and preflight.get('budget_reservations')==0,
                     'ACTUAL_COMPLETED_SOURCE_NUMERIC_PREFLIGHT_REQUIRED')
        _causal_need(state.get('schema')=='B_APPROVED_SINGLE_LW_PUBLISHED_STATE_R1'
                     and state.get('status')=='PASS_APPROVED_SINGLE_LW_STATE' and state.get('family')=='LW',
                     'INDEPENDENTLY_ACCEPTED_SINGLE_LW_PUBLICATION_REQUIRED')
        _causal_need(state.get('independent') is True and state.get('actual_exit_code')==0
            and (state.get('learned_units'),state.get('physical_operations'),state.get('inherited_learned_units'))==(9,14,0)
            and state.get('old_budget_balance_used') is False and state.get('one_approved_outer_invocation') is True
            and state.get('retry_max')==0 and state.get('physical_events_started_remaining')==0
            and state.get('all_14_cached_result_commitments_verified') is True
            and state.get('cache_budget_matches_actual_ledger') is True,
            'ACTUAL_SINGLE_APPROVED_TERMINAL_STATE_AND_BUDGET_REQUIRED')
        _causal_need(accepted.get('schema')=='B_CAUSAL_HELD_RUNTIME_INDEPENDENT_ACCEPTANCE_V1'
                     and accepted.get('status')=='PASS_SOURCE_RUNTIME_READY_FOR_PAIRED_REPLAY'
                     and accepted.get('independent') is True,'INDEPENDENT_RUNTIME_SOURCE_ACCEPTANCE_REQUIRED')
        historical_identity_ref=(_held_ref(freeze['inherited_held_identity_source_binding_ref'])
            if inherited_runtime_evidence_only else refs['held_identity_source_binding_ref'])
        _causal_need(_held_ref(accepted['single_lw_state_ref'])==refs['supplemental_lw_state_ref']
            and _held_ref(accepted['held_identity_source_binding_ref'])==historical_identity_ref,
            'EXACT_REVIEWED_STATE_AND_RUNTIME_SOURCE_BINDING_REQUIRED')
        _causal_need((approval.get('output_count_max'),approval.get('learned_units_max'),approval.get('physical_operations_max'),approval.get('retry_max'))==(1,9,14,0)
            and approval.get('subsequent_estimate_or_refresh_authorized') is False
            and approval.get('old_R5_R6_balance_used') is False, 'EXACT_NO_FURTHER_ESTIMATE_AUTHORITY_REQUIRED')
        _causal_pin(base_shared.interface,approval['proposal_ref'])
        execution=base_shared.interface.read(_causal_pin(base_shared.interface,state['execution_freeze_ref']))
        _causal_need(_held_ref(execution['approval_ref'])==refs['single_lw_approval_ref']
            and _held_ref(execution['numeric_ref'])==refs['single_lw_preflight_ref']
            and _held_ref(execution['proposal_ref'])==_held_ref(approval['proposal_ref'])
            and _held_ref(execution['identity_contract_ref'])==_held_ref(state['source_identity_contract_ref']),
            'EXACT_APPROVED_STATE_SOURCE_AND_PROPOSAL_AUTHORITY_REQUIRED')
        own=Path(__file__).resolve()
        closure=accepted.get('producer_source_pins')
        _causal_need(isinstance(closure,list) and any(Path(r['path'])==own for r in closure),
                     'REVIEWED_ACTUAL_RUNTIME_PRODUCER_CLOSURE_REQUIRED')
        if inherited_runtime_evidence_only:
            from scripts.research.a2.risk.continuous_lw_support import CONTINUOUS_LW_RULE,TASK
            _causal_need(freeze.get('task_id')==TASK and freeze.get('continuous_lw_rule')==CONTINUOUS_LW_RULE,
                         'EXACT_NEW_CONTINUOUS_DESCENDANT_REQUIRED')
            config_ref=_held_ref(freeze['research_config_ref'])
            config=base_shared.interface.read(_causal_pin(base_shared.interface,config_ref))
            _causal_need(config.get('schema')=='B_FAST_TRACK_HUMAN_AUTHORIZED_RESEARCH_CONFIG_V1'
                and config.get('task_id')==TASK and config.get('status')=='FROZEN_RESEARCH_CONFIGURATION'
                and config.get('continuous_lw_rule')==CONTINUOUS_LW_RULE
                and freeze['continuous_lw_source_science']['scientific_contract_sha256']==config_ref['sha256'],
                'EXACT_NEW_FROZEN_SCIENCE_AUTHORITY_REQUIRED')
            from scripts.research.a2.risk import continuous_lw_support as backend
            required_paths={own,Path(backend.__file__).resolve()}
            _causal_need(required_paths.issubset({Path(_held_ref(r)['path']) for r in freeze['source_pins']}),
                         'NEW_CONTINUOUS_RUNTIME_AND_BACKEND_SOURCE_PINS_REQUIRED')
            for reference in freeze['source_pins']:_causal_pin(base_shared.interface,reference)
            inherited=base_shared.interface.read(_causal_pin(base_shared.interface,historical_identity_ref))
            derived=values['held_identity_source_binding_ref']
            _causal_need(_held_ref(derived['parent_binding_ref'])==historical_identity_ref
                and derived.get('source_binding_revision') in ('AUTHORIZED_FAST_TRACK_CA_SOURCE_DESCENDANT_ONLY',
                    'AUTHORIZED_FAST_TRACK_SOURCE_AND_EXACT_CASH_NAMESPACE_DESCENDANT')
                and derived.get('task_id')==TASK
                and derived.get('status')=='FROZEN_SOURCE_BOUND_RUNTIME_ACCEPTANCE_PENDING'
                and _held_ref(derived['source_account_contract_ref'])==_held_ref(freeze['source_account_contract_ref']),
                'EXACT_NEW_ACCOUNT_SOURCE_BINDING_DESCENDANT_REQUIRED')
            changes={'task_id','status','created_utc','source_account_contract_ref','parent_binding_ref','source_binding_revision'}
            if derived['source_binding_revision']=='AUTHORIZED_FAST_TRACK_SOURCE_AND_EXACT_CASH_NAMESPACE_DESCENDANT':
                actual_typed_ref=_held_ref(freeze['frozen_history_cash_owner_ref'])
                _causal_need(_held_ref(derived['typed_ca_owner_ref'])==actual_typed_ref
                    and _held_ref(source_context['typed_ca_owner_ref'])==actual_typed_ref
                    and _held_ref(derived['inherited_typed_ca_owner_ref'])==_held_ref(inherited['typed_ca_owner_ref'])
                    and actual_typed_ref in [_held_ref(r) for r in freeze['source_pins']],
                    'EXACT_ACTUAL_TYPED_CASH_OWNER_NAMESPACE_DESCENDANT_REQUIRED')
                changes.update(('typed_ca_owner_ref','inherited_typed_ca_owner_ref'))
            _causal_need({k:v for k,v in derived.items() if k not in changes}==
                {k:v for k,v in inherited.items() if k not in changes},
                'ONLY_CA_SOURCE_REF_MAY_CHANGE_IN_INHERITED_IDENTITY_BINDING')
        else:
            for reference in closure:_causal_pin(base_shared.interface,reference)
            _causal_need(all(_held_ref(r) in [_held_ref(x) for x in freeze['source_pins']] for r in closure),
                         'EXACT_REVIEWED_FREEZE_SOURCE_CLOSURE_REQUIRED')
        identity_ref=_held_ref(state['source_identity_contract_ref'])
        _causal_need(identity_ref==_held_ref(preflight['contract_ref']),
                     'EXACT_QUALIFIED_STATE_SOURCE_CONTRACT_REQUIRED')
        contract=base_shared.interface.read(_causal_pin(base_shared.interface,identity_ref))
        _causal_need(_held_ref(contract['approval_ref'])==refs['single_lw_approval_ref']
            and _held_ref(contract['proposal_ref'])==_held_ref(approval['proposal_ref']),
            'EXACT_SOURCE_IDENTITY_APPROVAL_AND_PROPOSAL_REQUIRED')
        refs['source_identity_contract_ref']=identity_ref
        _causal_pin(base_shared.interface,state['state_ref']); _causal_pin(base_shared.interface,state['producer_ref'])
        descriptor_bridges=()
        if inherited_runtime_evidence_only and freeze.get('share_class_descriptor_bridge_ref') is not None:
            source_manifest=base_shared.interface.read(_causal_pin(base_shared.interface,
                values['held_identity_source_binding_ref']['source_manifest_ref']))
            descriptor_bridges=_load_share_class_descriptor_bridge(base_shared.interface,
                freeze['share_class_descriptor_bridge_ref'],source_manifest['sources']['uid_intervals'])
            refs['share_class_descriptor_bridge_ref']=_held_ref(freeze['share_class_descriptor_bridge_ref'])
            if freeze.get('share_class_descriptor_bridge_extension_ref') is not None:
                descriptor_bridges=_extend_share_class_descriptor_bridge(base_shared.interface,descriptor_bridges,
                    freeze['share_class_descriptor_bridge_extension_ref'],source_manifest['sources']['uid_intervals'])
                refs['share_class_descriptor_bridge_extension_ref']=_held_ref(freeze['share_class_descriptor_bridge_extension_ref'])
        _causal_need(freeze.get('share_class_descriptor_bridge_extension_ref') is None or bool(descriptor_bridges),
            'DESCRIPTOR_EXTENSION_REQUIRES_EXACT_BASE_BRIDGE')
        additional_refs=freeze.get('additional_share_class_descriptor_bridge_refs')
        if inherited_runtime_evidence_only:
            _causal_need(additional_refs==config.get('additional_share_class_descriptor_bridge_refs'),
                'EXACT_FROZEN_ADDITIONAL_DESCRIPTOR_BRIDGE_INPUT_REFS_REQUIRED')
        else:
            _causal_need(additional_refs is None, 'NEW_DESCENDANT_REQUIRED_FOR_ADDITIONAL_DESCRIPTOR_BRIDGES')
        additional=_normalize_additional_descriptor_bridge_refs(additional_refs)
        if additional:
            source_manifest=base_shared.interface.read(_causal_pin(base_shared.interface,
                values['held_identity_source_binding_ref']['source_manifest_ref']))
            descriptor_bridges=_load_additional_share_class_descriptor_bridges(base_shared.interface,
                additional,source_manifest['sources']['uid_intervals'],descriptor_bridges)
            for i,item in enumerate(additional):
                for role,reference in item.items():refs['additional_descriptor_'+role+':'+str(i)]=reference
        identity_transports=()
        transport_ref=freeze.get('delayed_identity_metadata_transport_ref')
        if transport_ref is not None:
            _causal_need(inherited_runtime_evidence_only
                and freeze.get('delayed_identity_metadata_transport_rule')==DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
                and config.get('delayed_identity_metadata_transport_rule')==DELAYED_IDENTITY_METADATA_TRANSPORT_RULE
                and _held_ref(config['delayed_identity_metadata_transport_ref'])==_held_ref(transport_ref),
                'EXPLICIT_FROZEN_NEW_IDENTITY_METADATA_INPUT_RULE_REQUIRED')
            source_manifest=base_shared.interface.read(_causal_pin(base_shared.interface,
                values['held_identity_source_binding_ref']['source_manifest_ref']))
            identity_transports=_load_delayed_identity_metadata_transport(base_shared.interface,
                transport_ref,source_manifest['sources']['uid_intervals'],
                values['held_identity_source_binding_ref']['original_event_binding_ref'])
            refs['delayed_identity_metadata_transport_ref']=_held_ref(transport_ref)
        additional_transport_refs=freeze.get('additional_delayed_identity_metadata_transport_refs')
        _causal_need(additional_transport_refs==config.get('additional_delayed_identity_metadata_transport_refs')
            if inherited_runtime_evidence_only else additional_transport_refs is None,
            'EXACT_FROZEN_ADDITIONAL_IDENTITY_METADATA_INPUT_REFS_REQUIRED')
        if additional_transport_refs is not None:
            _causal_need(inherited_runtime_evidence_only and bool(identity_transports),
                'ADDITIONAL_IDENTITY_METADATA_REQUIRES_EXACT_EXISTING_FROZEN_RULE')
            identity_transports=_load_additional_identity_metadata_transports(base_shared.interface,
                additional_transport_refs,source_manifest['sources']['uid_intervals'],
                values['held_identity_source_binding_ref']['original_event_binding_ref'],identity_transports)
            for i,reference in enumerate(additional_transport_refs):
                refs['additional_delayed_identity_metadata_transport_ref:'+str(i)]=_held_ref(reference)
        _causal_need(freeze.get('delayed_identity_metadata_transport_rule') is None or bool(identity_transports),
            'IDENTITY_METADATA_RULE_REQUIRES_PINNED_SOURCE_INPUT')
        closed_rule=freeze.get('closed_sell_spell_entry_source_rule')
        if closed_rule is not None:
            _causal_need(inherited_runtime_evidence_only
                and closed_rule==CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE
                and config.get('closed_sell_spell_entry_source_rule')==CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE,
                'EXPLICIT_FROZEN_CLOSED_SELL_SPELL_ENTRY_SOURCE_RULE_REQUIRED')
        sources=FrozenHeldSourceGuards(base_shared,values['held_identity_source_binding_ref'],source_context,
            account_id=account_id,accounting_freeze_ref=_held_ref(freeze['accounting_freeze_ref']),
            descriptor_bridges=descriptor_bridges,identity_transports=identity_transports,
            closed_sell_spell_entry_rule=closed_rule,
            investment_exclusion_tickers=investment_exclusions)
        _causal_need(_held_ref(sources.binding['lineage_rule_ref'])==refs['held_support_admission_ref'],
                     'EXACT_CURRENT_HELD_ADMISSION_RULE_REQUIRED')
        return cls(base=base_shared,account_id=account_id,sources=sources,supplemental=state,
            source_contract=contract,references=refs,reuse_rule=freeze['causal_lw_reuse_rule'])

    @property
    def loads_count(self):
        return self.base.loads_count+self.supplemental_loads_count

    def observe_owner_transitions(self, payload):
        self.sources.observe_owner_transitions(payload,self.account_id)

    def observe_fills(self, frame):
        excluded=getattr(self,'investment_exclusion_tickers',())
        if excluded and not frame.empty:
            if 'ticker' not in frame or frame.ticker.astype(str).isin(excluded).any():
                raise HeldLineageUnavailable('EXCLUDED_INVESTMENT_ACTUAL_FILL_FORBIDDEN')
        return self.book.observe_fills(frame)

    def _context_identity(self, ctx):
        n=len(self.base.master_assets)
        return content_hash(dict(account=self.account_id,day=_held_session(ctx.signal_date),
            as_of=pd.Timestamp(ctx.signal_asof).isoformat(),assets=tuple(map(str,ctx.tickers)),
            units=_vector(ctx,'current_units',n),weights=_vector(ctx,'current_weights',n),
            decision=_vector(ctx,'decision_mask',n,boolean=True),buy=_vector(ctx,'buy_allowed',n,boolean=True)))

    def qualified_causal_domain(self, ctx):
        if tuple(map(str,ctx.tickers))!=self.base.master_assets:
            raise ExistingRiskInputUnavailable('EXACT_MASTER_ASSET_ORDER_REQUIRED')
        signature=self._context_identity(ctx)
        if self._last is not None and self._last['signature']==signature:
            return self._last['domain']
        original=self.base._domain(ctx.signal_date,ctx.signal_asof)
        source=self.sources.session(ctx,original,self.book)
        proofs=self.book.qualified_proofs(ctx,source['held_guards'])
        domain=source['domain']
        receipt=dict(schema='B_CAUSAL_CURRENT_REQUIRED_DOMAIN_V1',account_id=self.account_id,
            decision_session=_held_session(ctx.signal_date),current_use_asof=pd.Timestamp(ctx.signal_asof).isoformat(),
            original_source_receipt=original['receipt'],required_assets=list(domain['assets']),
            original_E_assets=[self.base.master_assets[i] for i in np.flatnonzero(domain['eligible_mask'])],
            actual_H_assets=[self.base.master_assets[i] for i in np.flatnonzero(domain['held_mask'])],
            held_lineage_proofs=proofs,held_source_receipt=source['source_receipt'],
            historical_observations_relabelled=False,old_current_pool_contract_unchanged=True,
            new_descendant_not_original_current_pool_equivalence=True,numeric_state_loaded=False,
            additional_fit_units=0,additional_inference_calls=0,strict_PIT=False,
            production_qualified=False,quote_qualified=False,certified_NAV=False)
        if self.investment_exclusion_tickers:
            receipt.update(investment_exclusion_tickers=list(self.investment_exclusion_tickers),
                original_E_assets=[self.base.master_assets[i] for i in np.flatnonzero(domain['original_eligible_mask'])],
                eligible_E_assets=[self.base.master_assets[i] for i in np.flatnonzero(domain['eligible_mask'])],
                investment_entry_domain_changed=True)
        pool=original['mask'].copy(); pool.flags.writeable=False
        domain['pool_mask']=pool
        domain['receipt']=receipt
        self._last=dict(signature=signature,domain=domain,original=original,source=source,proofs=proofs)
        return domain

    def _require_domain(self, ctx, domain):
        _causal_need(self._last is not None and domain is self._last['domain']
                     and self._context_identity(ctx)==self._last['signature'],
                     'EXACT_ALREADY_QUALIFIED_CURRENT_DOMAIN_REQUIRED')
        current=causal_held_domain(ctx,self._last['original']['mask'],
            excluded_tickers=getattr(self,'investment_exclusion_tickers',()))
        _causal_need(current['assets']==domain['assets'] and all(np.array_equal(current[k],domain[k])
            for k in ('columns','eligible_mask','held_mask','decision_mask','buy_allowed')),
            'QUALIFIED_REQUIRED_DOMAIN_CHANGED')
        return self._last

    def note_qualified_decision(self, ctx, domain):
        current=self._require_domain(ctx,domain)
        self.book.note_qualified_decision(ctx.signal_date,current['source']['entry_seeds'])

    def _guard_supplement(self, ctx, domain, current):
        state=self.supplemental; binding=self.source_contract['binding']; original=current['original']
        assets=tuple(state['assets'])
        _causal_need(len(set(assets))==len(assets) and assets==tuple(binding['ordered_assets']),
                     'ACCEPTED_WHOLE_LW_ORDERED_AXIS_REQUIRED')
        for field,target in (('asset_uids','asset_uids'),('asset_epochs','current_authority_epochs'),
                             ('historical_source_epochs','historical_source_epochs')):
            _causal_need(state[field]==binding[target] and set(state[field])==set(assets),
                         'IMMUTABLE_FIT_ASOF_AND_HISTORICAL_EPOCH_ROLES_REQUIRED')
        clocks={k:pd.Timestamp(state[k]) for k in ('as_of','cutoff','state_available_at')}
        _causal_need(all(not pd.isna(c) and c.tzinfo is not None for c in clocks.values())
            and clocks['cutoff']<clocks['as_of'] and max(clocks['as_of'],clocks['state_available_at'])<=pd.Timestamp(ctx.signal_asof)
            and clocks['as_of']==pd.Timestamp(binding['current_identity_asof'])
            and clocks['cutoff']==pd.Timestamp(binding['history_cutoff']), 'CAUSAL_APPROVED_STATE_CLOCK_REQUIRED')
        epoch=state['original_primary_dependency_epoch']; event=original['event']
        _causal_need(epoch['event_id']==event['dependency_local_event_ids']['PRIMARY']
            and epoch['signature_sha256']==event['dependency_local_signature_sha256']['PRIMARY'],
            'APPROVED_SINGLE_LW_EXPIRED_AT_NEXT_ORIGINAL_PRIMARY_EVENT')
        missing=[a for a in domain['assets'] if a not in assets]
        _causal_need(not missing,'APPROVED_WHOLE_LW_REQUIRED_AXIS_UNAVAILABLE',assets=missing)
        source=current['source']; record=original['record']
        bridges={}
        for asset in domain['assets']:
            identity=source['current_identities'][asset]
            _causal_need(identity['security_id']==state['asset_uids'][asset]
                and source['historical_source_epochs'][asset]==state['historical_source_epochs'][asset],
                'CURRENT_SECURITY_AND_HISTORICAL_SUPPORT_ROLE_CONFLICT',asset=asset)
            if asset in record['asset_uids']:
                _causal_need(record['asset_uids'][asset]==state['asset_uids'][asset]
                    and record['asset_epochs'][asset]==state['historical_source_epochs'][asset],
                    'ORIGINAL_PRIMARY_OBSERVATION_SUPPORT_CHANGED',asset=asset)
            else:
                proof=current['proofs'].get(asset); old=binding['held_lineages'].get(asset)
                _causal_need(proof is not None and old is not None
                    and identity['security_id']==old['uid'] and _held_class_equal(identity['share_class'],old['share_class'])
                    and identity['raw_code']==old['raw_code'], 'UNPROVED_FIT_ASOF_TO_CURRENT_HELD_IDENTITY_ROLE',asset=asset)
                bridges[asset]=dict(immutable_fit_asof_epoch=state['asset_epochs'][asset],
                    historical_source_epoch=state['historical_source_epochs'][asset],
                    runtime_actual_position_id=proof['position_id'],
                    relation='SAME_SECURITY_AND_HISTORICAL_SUPPORT_NOT_SAME_POSITION_ID',
                    current_held_proof_sha256=content_hash(proof))
        return bridges

    def _supplement_state(self):
        from scripts.research.a2.portfolio.shared_joint_adapter_r2 import risk_state_sha256
        state_ref=self.supplemental['state_ref']; _causal_pin(self.base.interface,state_ref)
        _causal_pin(self.base.interface,self.supplemental['producer_ref'])
        if self._supplement is None:
            if self._state_loader is None:
                import joblib
                state=joblib.load(state_ref['path'])
            else:
                state=self._state_loader(state_ref)
            self.supplemental_loads_count+=1
            self._supplement=state
        state=self._supplement; accepted=self.supplemental; assets=tuple(accepted['assets'])
        _causal_need(risk_state_sha256(state)==accepted['typed_state_content_sha256']
            and state.risk_state_id==accepted['risk_state_id'] and tuple(state.assets)==assets
            and state.method==accepted['method'] and state.status=='PASS_FROZEN_HISTORY_MECHANISM'
            and pd.Timestamp(state.as_of)==pd.Timestamp(accepted['as_of'])
            and pd.Timestamp(state.cutoff)==pd.Timestamp(accepted['cutoff']), 'EXACT_APPROVED_ORIGINAL_TYPED_STATE_REQUIRED')
        for a in assets:
            _causal_need(state.coverage[a]['uid']==accepted['asset_uids'][a]
                and state.coverage[a]['identity_epoch']==accepted['asset_epochs'][a],
                'APPROVED_STATE_COVERAGE_COORDINATE_CHANGED',asset=a)
        lineage=state.notes.get('estimator_lineage',{})
        _causal_need(lineage.get('family')=='LW' and lineage.get('recipe_sha256')==accepted['recipe_sha256'],
            'ORIGINAL_APPROVED_LW_RECIPE_REQUIRED')
        full=np.asarray(state.covariance,dtype=float)
        _causal_need(full.shape==(len(assets),len(assets)),'APPROVED_COMPLETE_CROSS_COVARIANCE_REQUIRED')
        _,psd=validate_covariance(full,regularize=False)
        return state,full,psd

    def for_required_domain(self, ctx, domain):
        current=self._require_domain(ctx,domain); original=current['original']
        if set(domain['assets']).issubset(original['record']['assets']):
            result=self.base.for_decision(ctx)
            _causal_need(result.assets==domain['assets'] and np.array_equal(result.columns,domain['columns']),
                         'PRIMARY_REQUIRED_DOMAIN_PROJECTION_CHANGED')
            receipt=dict(result.source_receipt,causal_held_source_receipt=domain['receipt'],
                         selected_state_role='COMPLETE_ORIGINAL_PRIMARY_FIRST',additional_fit_units=0)
            return ExistingRiskSlice(result.assets,result.columns,result.covariance,result.pool_mask,
                                     result.covariance_psd_qualified,receipt,self.loads_count)
        bridges=self._guard_supplement(ctx,domain,current)
        state,full,psd=self._supplement_state()
        axis=pd.Index(self.supplemental['assets']).get_indexer(domain['assets'])
        covariance=np.array(full[np.ix_(axis,axis)],copy=True); covariance.flags.writeable=False
        receipt=dict(schema='B_APPROVED_WHOLE_SINGLE_LW_CURRENT_USE_V1',account_id=self.account_id,
            selected_state_role='APPROVED_SINGLE_WHOLE_LW_NECESSARY_FALLBACK',
            current_use_asof=pd.Timestamp(ctx.signal_asof).isoformat(),required_assets=list(domain['assets']),
            accepted_publication_ref=self.references['supplemental_lw_state_ref'],
            original_artifact_ref=self.supplemental['state_ref'],
            publication_typed_state_content_sha256=self.supplemental['typed_state_content_sha256'],
            immutable_fit_asof_current_epochs=self.supplemental['asset_epochs'],
            historical_source_epochs=self.supplemental['historical_source_epochs'],
            original_primary_dependency_epoch=self.supplemental['original_primary_dependency_epoch'],
            current_held_role_bridges=bridges,causal_held_source_receipt=domain['receipt'],
            exact_principal_projection=True,consumer_psd_guard=psd,numeric_state_loaded=True,
            consumer_projection_sha256=content_hash(dict(assets=domain['assets'],covariance=covariance)),
            matrix_mixing=False,new_risk_estimates=0,additional_fit_units=0,historical_availability_authority='UNKNOWN',
            strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
        return ExistingRiskSlice(domain['assets'],domain['columns'],covariance,original['mask'],True,receipt,self.loads_count)

class ContinuousCausalLWInputs(CausalHeldLWInputs):
    """Authorized continuous support; unchanged Simple source/book API stays lazy."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.estimate_callback=None
        self.continuous_rule=None
        self.last_request=None
        self.generated=[]
        self.generated_loads_count=0
        self.new_outputs_count=0

    def budget_summary(self):
        callback=self.estimate_callback
        if callback is not None and hasattr(callback,'budget_summary'):
            return callback.budget_summary()
        return dict(new_complete_outputs=self.new_outputs_count,charged_new_learned_units=0,
            charged_new_physical_operations=0,physical_failed=0,physical_started=0,
            ledger_ref=None,inherited_paid_history=dict(learned_units=9,physical_operations=14),
            authoritative_ledger_available=False)

    @classmethod
    def from_freeze(cls, *, freeze, base_shared, account_id, market_dates, master_assets,
                    source_context, estimate_callback=None):
        from scripts.research.a2.risk.continuous_lw_support import (
            CONTINUOUS_LW_RULE, TASK, make_continuous_lw_estimator)
        _causal_need(freeze.get('task_id')==TASK and freeze.get('continuous_lw_rule')==CONTINUOUS_LW_RULE,
                     'AUTHORIZED_CONTINUOUS_WHOLE_LW_DESCENDANT_REQUIRED')
        result=cls._from_freeze(freeze=freeze,base_shared=base_shared,account_id=account_id,
            market_dates=market_dates,master_assets=master_assets,source_context=source_context,
            inherited_runtime_evidence_only=True)
        result.continuous_rule=dict(CONTINUOUS_LW_RULE)
        result.estimate_callback=estimate_callback or make_continuous_lw_estimator(
            freeze,base_shared=base_shared,account_id=account_id)
        return result

    @property
    def loads_count(self):
        return super().loads_count+self.generated_loads_count

    def describe_required_domains(self,ctx):
        """Pre-qualification request snapshot: P is full original structural pool."""
        from copy import deepcopy
        original=self.base._domain(ctx.signal_date,ctx.signal_asof)
        domain=causal_held_domain(ctx,original['mask'],
            excluded_tickers=getattr(self,'investment_exclusion_tickers',()))
        assets=self.base.master_assets
        p=list(original['record']['assets'])
        h=[assets[i] for i in np.flatnonzero(domain['held_mask'])]
        d=list(domain['assets']);e=[assets[i] for i in np.flatnonzero(domain['eligible_mask'])]
        calendar=self.base._components['calendar'];j=calendar.get_loc(pd.Timestamp(ctx.signal_date))
        _causal_need(j>0,'EXACT_PRIOR_CALENDAR_SESSION_REQUIRED')
        event=original['event']
        self.last_request=dict(schema='B_CONTINUOUS_LW_REQUIRED_DOMAIN_SNAPSHOT_V1',account_id=self.account_id,
            decision_session=_held_session(ctx.signal_date),as_of=pd.Timestamp(ctx.signal_asof).isoformat(),
            cutoff=producer._clock(calendar[j-1]).isoformat(),P=p,E=e,H=h,D=d,
            U=sorted(set(p)|set(h)),
            original_primary_dependency_epoch=dict(event_id=event['dependency_local_event_ids']['PRIMARY'],
                signature_sha256=event['dependency_local_signature_sha256']['PRIMARY']),
            original_source_receipt=original['receipt'],selection_checks=[],selected_state=None,
            source_qualification_status='PENDING_CURRENT_ACCOUNT_SOURCE_GUARDS',numeric_state_loaded=False,
            new_risk_estimates=0,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
        if self.investment_exclusion_tickers:
            self.last_request['investment_exclusion_tickers']=list(self.investment_exclusion_tickers)
        return deepcopy(self.last_request)

    def qualified_causal_domain(self,ctx):
        self.describe_required_domains(ctx)
        try:
            domain=super().qualified_causal_domain(ctx)
        except BaseException as exc:
            self.last_request.update(source_qualification_status='FAILED',source_failure=dict(
                type=type(exc).__name__,reason=str(exc),receipt=getattr(exc,'receipt',None)))
            raise
        self.last_request['source_qualification_status']='CURRENT_ACCOUNT_SOURCE_QUALIFIED'
        domain['receipt']['continuous_support_request']=dict(self.last_request)
        return domain

    def _generated_eligible(self,metadata,ctx,domain,current):
        assets=tuple(metadata['assets']);original=current['original'];source=current['source']
        event=original['event']
        epoch=dict(event_id=event['dependency_local_event_ids']['PRIMARY'],
            signature_sha256=event['dependency_local_signature_sha256']['PRIMARY'])
        _causal_need(metadata['original_primary_dependency_epoch']==epoch,'GENERATED_LW_PRIMARY_EPOCH_EXPIRED')
        _causal_need(pd.Timestamp(metadata['cutoff'])<pd.Timestamp(metadata['as_of'])
            and max(pd.Timestamp(metadata['as_of']),pd.Timestamp(metadata['state_available_at']))<=pd.Timestamp(ctx.signal_asof),
            'GENERATED_LW_FUTURE_CLOCK_UNAVAILABLE')
        missing=[a for a in domain['assets'] if a not in assets]
        _causal_need(not missing,'GENERATED_WHOLE_LW_REQUIRED_AXIS_UNAVAILABLE',assets=missing)
        for asset in domain['assets']:
            identity=source['current_identities'][asset]
            _causal_need(_held_security_identity_equal(identity,metadata['current_identities'][asset],self.book.descriptor_bridges),
                'GENERATED_LW_SOURCE_IDENTITY_OR_HISTORICAL_ROLE_EXPIRED',asset=asset)
            if asset in original['record']['asset_uids']:
                _causal_need(original['record']['asset_uids'][asset]==metadata['asset_uids'][asset]
                    and original['record']['asset_epochs'][asset]==metadata['historical_source_epochs'][asset],
                    'GENERATED_LW_ORIGINAL_POOL_SUPPORT_CHANGED',asset=asset)
            else:
                _causal_need(asset in current['proofs'] and source['historical_source_epochs'][asset]==metadata['historical_source_epochs'][asset],
                    'GENERATED_LW_SOURCE_IDENTITY_OR_HISTORICAL_ROLE_EXPIRED',asset=asset)
        return True

    def _generated_slice(self,state,metadata,ctx,domain,current):
        from scripts.research.a2.portfolio.shared_joint_adapter_r2 import risk_state_sha256
        from scripts.research.a2.risk.continuous_lw_support import RECIPE
        _causal_pin(self.base.interface,metadata['state_ref'])
        _causal_pin(self.base.interface,metadata['producer_ref'])
        _causal_need(metadata.get('status')=='COMPLETE_WHOLE_LW_OUTPUT'
            and tuple(state.assets)==tuple(metadata['assets']) and state.status=='PASS_FROZEN_HISTORY_MECHANISM'
            and state.risk_state_id==metadata['risk_state_id'] and state.method==metadata['method']
            and risk_state_sha256(state)==metadata['typed_state_content_sha256']
            and pd.Timestamp(state.as_of)==pd.Timestamp(metadata['as_of'])
            and pd.Timestamp(state.cutoff)==pd.Timestamp(metadata['cutoff'])
            and metadata['recipe_sha256']==RECIPE
            and state.notes.get('estimator_lineage',{}).get('recipe_sha256')==RECIPE,
            'EXACT_PERSISTED_ORIGINAL_OWNER_GENERATED_STATE_REQUIRED')
        _causal_need(0<=metadata['learned_units']<=9 and 0<=metadata['physical_operations']<=14,
                     'GENERATED_LW_INVOCATION_BUDGET_REQUIRED')
        for a in metadata['assets']:
            _causal_need(state.coverage[a]['uid']==metadata['asset_uids'][a]
                and state.coverage[a]['identity_epoch']==metadata['asset_epochs'][a],
                'GENERATED_STATE_COVERAGE_IDENTITY_CHANGED',asset=a)
        full=np.asarray(state.covariance,dtype=float)
        _causal_need(full.shape==(len(state.assets),len(state.assets))
            and content_hash(full)==metadata['covariance_sha256'],'GENERATED_COMPLETE_CROSS_COVARIANCE_REQUIRED')
        _,psd=validate_covariance(full,regularize=False)
        axis=pd.Index(state.assets).get_indexer(domain['assets'])
        covariance=np.array(full[np.ix_(axis,axis)],copy=True);covariance.flags.writeable=False
        receipt=dict(metadata,selected_state_role='COMPLETE_GENERATED_WHOLE_LW',
            current_use_asof=pd.Timestamp(ctx.signal_asof).isoformat(),required_assets=list(domain['assets']),
            causal_held_source_receipt=domain['receipt'],current_held_role_bridges={a:dict(
                immutable_fit_asof_current_epoch=metadata['asset_epochs'][a],
                current_actual_position_id=current['proofs'][a]['position_id'],
                relation='SAME_SECURITY_AND_HISTORICAL_SUPPORT_NOT_SAME_POSITION_ID')
                for a in domain['assets'] if a in current['proofs']},
            numeric_state_loaded=True,exact_principal_projection=True,matrix_mixing=False,
            consumer_psd_guard=psd,consumer_projection_sha256=content_hash(dict(assets=domain['assets'],covariance=covariance)))
        self.last_request.update(selected_state=metadata['state_ref'],numeric_state_loaded=True)
        return ExistingRiskSlice(domain['assets'],domain['columns'],covariance,current['original']['mask'],True,receipt,self.loads_count)

    def for_required_domain(self,ctx,domain):
        current=self._require_domain(ctx,domain);original=current['original']
        checks=self.last_request['selection_checks']
        if set(domain['assets']).issubset(original['record']['assets']):
            checks.append(dict(candidate='ORIGINAL_PRIMARY',status='COMPLETE_REQUIRED_AXIS'))
            result=super().for_required_domain(ctx,domain)
            self.last_request.update(selected_state=original['record']['artifact_ref'],numeric_state_loaded=bool(domain['assets']))
            return result
        checks.append(dict(candidate='ORIGINAL_PRIMARY',status='INCOMPLETE_REQUIRED_AXIS',
            missing=[a for a in domain['assets'] if a not in original['record']['assets']]))
        # The previously paid single output is inherited evidence, not new-fit authority.
        try:
            self._guard_supplement(ctx,domain,current)
        except ExistingRiskInputUnavailable as exc:
            checks.append(dict(candidate='INHERITED_APPROVED_SINGLE_LW',status='INELIGIBLE',receipt=exc.receipt))
        else:
            result=super().for_required_domain(ctx,domain)
            self.last_request.update(selected_state=self.supplemental['state_ref'],numeric_state_loaded=bool(domain['assets']))
            return result
        if hasattr(self.estimate_callback,'available_state_records'):
            from scripts.research.a2.risk.continuous_lw_support import ContinuousLWEstimator
            available = self.estimate_callback.available_state_records
            metadata_args = (ctx.signal_asof, self.last_request['original_primary_dependency_epoch'])
            if getattr(available, '__func__', None) is ContinuousLWEstimator.available_state_records:
                metadata_records = available(*metadata_args, known_state_refs=tuple(
                    x['metadata']['state_ref'] for x in self.generated))
            else:
                # Retain the existing two-argument duck-typed callback contract.
                metadata_records = available(*metadata_args)
            for metadata in metadata_records:
                if not any(x['metadata']['state_ref']==metadata['state_ref'] for x in self.generated):
                    self.generated.append(dict(state=None,metadata=metadata))
        for item in reversed(self.generated):
            try:self._generated_eligible(item['metadata'],ctx,domain,current)
            except ExistingRiskInputUnavailable as exc:
                checks.append(dict(candidate=item['metadata']['state_ref'],status='INELIGIBLE',receipt=exc.receipt))
                continue
            if item['state'] is None:
                _causal_pin(self.base.interface,item['metadata']['state_ref'])
                import joblib
                item['state']=joblib.load(item['metadata']['state_ref']['path'])
                self.generated_loads_count+=1
            return self._generated_slice(item['state'],item['metadata'],ctx,domain,current)
        from copy import deepcopy
        request=deepcopy(self.last_request)
        request.update(current_identities=deepcopy(current['source']['current_identities']),
            historical_source_epochs=dict(current['source']['historical_source_epochs']),
            held_lineage_proofs=deepcopy(current['proofs']),held_source_receipt=deepcopy(current['source']['source_receipt']))
        if self.estimate_callback is None:
            raise ExistingRiskInputUnavailable('AUTHORIZED_CONTINUOUS_ESTIMATOR_NOT_CONNECTED',request=request)
        try:
            output=self.estimate_callback(request)
            metadata=output['metadata']
            _causal_need(tuple(metadata['assets'])==tuple(request['U']),
                         'NEW_ESTIMATE_MUST_COVER_EXACT_FULL_P_UNION_H')
            self._generated_eligible(metadata,ctx,domain,current)
            result=self._generated_slice(output['state'],metadata,ctx,domain,current)
        except BaseException as exc:
            self.last_request.update(estimation_status='FAILED',estimation_failure=dict(
                type=type(exc).__name__,reason=str(exc),receipt=getattr(exc,'receipt',None)))
            raise
        self.generated.append(output)
        # PRIMARY expiry is monotone in the original structural chain. Keep only
        # current-epoch numeric matrices; durable original-owner records persist.
        epoch=metadata['original_primary_dependency_epoch']
        self.generated=[item for item in self.generated if item['metadata']['original_primary_dependency_epoch']==epoch]
        self.new_outputs_count+=1
        self.last_request.update(estimation_status='COMPLETE_WHOLE_LW_OUTPUT',new_risk_estimates=1)
        return result
