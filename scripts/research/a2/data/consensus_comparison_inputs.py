"""R12 input routing only; frozen R3 readers and existing numerical owners.

No read on import, no fitting, no source qualification, no forward-label maker.
Numeric access requires a separately pinned root input freeze. The caller owns
the exact current/held UID domain; label coverage never selects that domain.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import FunctionType

import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as r3
from scripts.research.a2.evaluation import joint_method_accounts as accounts
from scripts.research.a2.data import shared_risk_inputs_r3 as packaging
from scripts.research.a2.risk import shared_risk_engine_r2 as engine
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.training import stateful_mechanism_inputs as native_owner
from scripts.common.storage_paths import resolve, assert_safe_output_path

SCHEMA = "CONSENSUS_COMPARISON_INPUT_FREEZE_R12"
GATE = "AUTHORIZED_PRE2026_COMPARISON_INPUTS"
MODE = "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"
BOUNDARY = pd.Timestamp("2026-01-01", tz="UTC")
DAILY_QQQ = "QFQ_CLOSE_TO_CLOSE_DECIMAL_RETURN"
LABEL_ECONOMICS = "QTY_ADJUSTED_RAW_OPEN_PRICE_RETURN_EXCLUDING_CASH_DISTRIBUTIONS"
REFERENCE = "OWNER_TOP20_LEGAL_BY_FROZEN_CONSENSUS_RANK_EQUAL_WEIGHT"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def source_pins():
    return {name: dict(path=str(Path(module.__file__).resolve()), sha256=r3.sha(module.__file__))
            for name, module in (("reader", r3), ("packaging", packaging), ("engine", engine),
                                 ("accounts", accounts), ("native_owner", native_owner))} | {
        "adapter": dict(path=str(Path(__file__).resolve()), sha256=r3.sha(__file__))}


def metadata(reference):
    path = Path(reference["path"])
    require(path.is_absolute() and path.resolve(strict=True) == path and path.stat().st_size <= 262144,
            "BOUNDED_EXACT_COMPARISON_INPUT_METADATA_REQUIRED")
    require(r3.sha(path) == reference["sha256"], "COMPARISON_INPUT_METADATA_CHANGED")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "COMPARISON_INPUT_METADATA_OBJECT_REQUIRED")
    return value


def freeze_template(run, root_scope_ref, r3_source_ref, *, actual_snapshot_timestamp,
                    parent_binding_ref=None, native_horizon_ref=None, native_source_scope=None,
                    consensus_roster_ref=None, reference_definition=REFERENCE):
    """Reviewable metadata proposal only; never create directories or open bodies."""
    run = Path(run).resolve()
    assert_safe_output_path(run, kind="backtest", paths=resolve())
    root = metadata(root_scope_ref); source = metadata(r3_source_ref)
    require(root["research_id"] == "CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12"
            and root["source_policy"] == MODE and source.get("sources"), "EXACT_R12_SOURCE_METADATA_REQUIRED")
    engine._time(actual_snapshot_timestamp)
    return dict(schema=SCHEMA, status="PROPOSED", research_id=root["research_id"], run=str(run),
        root_scope_ref=root_scope_ref, source_manifest_ref=r3_source_ref, parent_binding_ref=parent_binding_ref,
        source_pins=source_pins(),
        source_policy=MODE, numeric_read_authorized=False, test2026_read_authorized=False,
        confirmation_read_authorized=False, actual_snapshot_timestamp=str(actual_snapshot_timestamp),
        bank_qqq_coordinate=DAILY_QQQ, bank_window_sessions=120, r2_window_sessions=252,
        r2_cutoff="PREVIOUS_LEGAL_SESSION_NY1600_STRICT_ALL_RETURN_CLOCKS_LT_CUTOFF",
        bank_cutoff="DAILY_DATE_EXCLUSIVE_120_MATURE_DAILY_ROWS; INDEPENDENT_QQQ_CLOSE_TO_CLOSE",
        domain_role="EXACT_CALLER_REQUESTED_CURRENT_OR_HELD_UNION_NO_LABEL_SELECTION",
        native_horizon_ref=native_horizon_ref, reference_definition=reference_definition,
        native_source_scope=native_source_scope, consensus_roster_ref=consensus_roster_ref,
        risk_label_economic_semantics=LABEL_ECONOMICS,
        account_cash_distributions="SEPARATE_REAL_CASH_ENTITLEMENTS_IN_NAV_AND_RL_REWARDS_NOT_IN_RISK_LABELS",
        scenario_counted_mean_required=True, fundamental_definition=None,
        scenario_mean_owner="CANONICAL_BOUNDED_BANK_DIAG_EXACT_ANNUAL_H5_TABLE",
        scenario_mean_fit_unit_upper=2,
        strict_PIT_promotion_eligible=False, account_qualification_granted=False, fit_authority=False,
        output_locations=dict(input_freeze=str(run/"CONSENSUS_COMPARISON_INPUT_FREEZE.json"),
                              runtime_evidence=str(run/"comparison")),
        numeric_read_roles=dict(extended_shareholder_y5=["y_open5"], qqq_qfq_years=["open", "close"],
            native_source_assembly="ONLY_EXPLICIT_FROZEN_RAW_OPEN_AND_EXISTING_EVENT_QUANTITY_CALLBACKS",
            native_horizons="ONLY_SEPARATELY_FROZEN_NATIVE_SHAREHOLDER_TYPED_OBSERVATIONS; ER_CLOSE_EXCESS_FORBIDDEN"),
        metadata_read_roles=dict(calendar=["trade_date"], prediction_features=list(r3.FEATURE_META),
            raw_open_close=["ticker", "trade_date"], shareholder_y5=["ticker", "signal_date", "security_id"],
            uid_intervals=["ticker", "security_id", "effective_start"],
            ff48_surface=["decision_date", "canonical_security_id", "ticker_at_date", "sic_available_at",
                "ff48_code", "identity_status", "taxonomy_status", "sic_source_sha256", "source_fingerprints"]),
        physical_source_pins={name: [{k:p[k] for k in ("path", "sha256")} for p in pins]
            if isinstance(pins,list) else {k:pins[k] for k in ("path", "sha256")}
            for name,pins in source["sources"].items()})


def decision_clocks(value, calendar):
    days, closes = packaging._calendar(calendar)
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        require(stamp == stamp.normalize(), "DATE_OR_EXPLICIT_SIGNAL_CLOSE_REQUIRED")
        as_of = packaging._clock(stamp)
    else:
        as_of = engine._time(stamp)
    require(as_of < BOUNDARY, "COMPARISON_PRE2026_DECISION_REQUIRED")
    matches = np.flatnonzero(closes == as_of)
    require(len(matches) == 1 and matches[0] > 0, "EXACT_SIGNAL_CLOSE_AND_PRIOR_LEGAL_SESSION_REQUIRED")
    return days, as_of, closes[int(matches[0])-1]


def native_horizon_metadata(reference):
    """Reject ER/Close schemas before any native numeric callback can run."""
    path = r3._safe_source(reference["path"])
    r3._pin(path, reference["sha256"], "comparison_native_horizons")
    columns = r3.pq.ParquetFile(path).schema_arrow.names
    require(set((*engine.META, "return_value")).issubset(columns),
            "BLOCK_MULTI_HORIZON_COORDINATE_SCHEMA_MISMATCH")
    clocks = ["origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"]
    _, proof = guard_parquet(path, reference["sha256"], clocks)
    for field in clocks:
        require(all(engine._time(bound["max"]) < BOUNDARY for bound in proof["date_bounds"][field]),
                "NATIVE_HORIZON_PHYSICAL_PRE2026_REQUIRED")
    return proof


def append_native_horizons(assembly, observations, receipt, *, cutoff):
    """Append original typed shareholder returns; never reinterpret ER/Close labels.

    The caller must supply the actual frozen native-horizon receipt and already
    isolated typed observations. The canonical panel owner validates all clocks,
    UID/epoch, endpoint sessions and units before inspecting eligible values.
    """
    require(isinstance(receipt, engine.SourceReceipt), "NATIVE_HORIZON_TYPED_RECEIPT_REQUIRED")
    inputs = assembly.risk_input
    receipt.validate(cutoff, primary=inputs.source_receipt)
    require(receipt.return_coordinate == engine.COORDINATE, "BLOCK_MULTI_HORIZON_COORDINATE_MISMATCH")
    require(isinstance(observations, pd.DataFrame) and set(engine.META).issubset(observations),
            "NATIVE_SHAREHOLDER_HORIZON_OBSERVATIONS_REQUIRED")
    require(set(observations.horizon).issubset({3, 10, 20}), "ORIGINAL_H5_MUST_NOT_BE_REPLACED")
    for clock in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        times = observations[clock].map(engine._time)
        require(times.lt(engine._time(cutoff)).all() and times.lt(BOUNDARY).all(),
                "NATIVE_HORIZON_MUST_BE_ISOLATED_BEFORE_NUMERIC_ACCESS")
    composite = replace(inputs.source_receipt, source_identity="R12_FROZEN_NATIVE_SHAREHOLDER_HORIZONS",
        source_sha256=r3.content_hash([inputs.source_receipt.cache_identity(), receipt.cache_identity()]))
    stock = inputs.observations.copy(); extra = observations.copy()
    require(extra.source_identity.eq(receipt.source_identity).all(), "NATIVE_HORIZON_SOURCE_SWAP")
    stock["source_identity"] = composite.source_identity; extra["source_identity"] = composite.source_identity
    combined = pd.concat([stock, extra], ignore_index=True)
    for horizon in (3, 10, 20):
        engine._panel(combined, inputs.assets, inputs.asset_uids, inputs.identity_epoch,
                      composite, pd.DatetimeIndex(inputs.sessions), engine._time(cutoff), horizon)
    inputs = replace(inputs, observations=combined, source_receipt=composite)
    declaration = dict(assembly.support_declarations)
    declaration["stock_horizons"] = [3, 5, 10, 20]; declaration["missing_stock_horizons"] = []
    declaration["method_block_reasons"] = {m: list(v) for m, v in declaration["method_block_reasons"].items()}
    declaration["method_block_reasons"]["RM"] = [v for v in declaration["method_block_reasons"]["RM"]
        if v != "BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20"]
    declaration["native_horizon_receipt"] = receipt.cache_identity()
    return packaging.RiskInputAssembly(inputs, declaration)


def assemble_native_shareholder_horizons(payload, domain, calendar, cutoff, receipt):
    """Adapt R10 pure owners only; never invoke its reader/strategy/research run."""
    cutoff = engine._time(cutoff)
    require(payload.get("risk_label_economic_semantics") == LABEL_ECONOMICS,
            "NATIVE_QUANTITY_PRICE_PROXY_NOT_FULL_CASH_TOTAL_RETURN")
    keys, quotes, sid = payload["keys"], payload["raw_quotes"], payload["sid_projection"]
    # These source callbacks must already isolate the current declared domain and
    # prior numeric endpoint window. Inspect metadata before native owner values.
    for frame, field in ((keys,"signal_date"),(quotes,"trade_date"),(sid,"signal_date")):
        times = pd.to_datetime(frame[field]).map(packaging._clock)
        require(times.lt(cutoff).all() and times.lt(BOUNDARY).all(), "NATIVE_CALLBACK_NOT_ASOF_ISOLATED")
        require(set(frame.ticker).issubset(domain["assets"]), "NATIVE_CALLBACK_DOMAIN_EXPANSION")
    require(callable(payload.get("event_window")), "FROZEN_EXISTING_EVENT_WINDOW_OWNER_REQUIRED")
    packets = []
    for horizon in (3,10,20):
        plan = native_owner.native_endpoint_plan(keys, calendar, horizon, sid,
            quotes[["trade_date","ticker"]], payload["event_records"], payload["event_window"], receipt.source_identity)
        legal = pd.Series(True,index=plan.index)
        for field in ("signal_date","execution_date","label_end_date","label_mature_date"):
            legal &= pd.to_datetime(plan[field]).notna() & pd.to_datetime(plan[field]).map(
                lambda d: packaging._clock(d) if not pd.isna(d) else BOUNDARY).lt(cutoff)
        # Enforce the already established R3 contiguous current UID segment in
        # addition to native owner's own entry/exit SID checks; retain its epoch.
        starts = plan.ticker.map(domain["segment_starts"]).map(pd.Timestamp)
        legal &= pd.to_datetime(plan.signal_date).ge(starts)
        legal &= plan.security_id.eq(plan.ticker.map(domain["asset_uids"]))
        packet = native_owner.native_labels(plan.loc[legal].copy(), quotes)
        obs = native_owner.native_risk_observations(packet)
        obs["identity_epoch"] = domain["identity_epoch"]
        obs["source_identity"] = receipt.source_identity
        obs["aggregate_domain_bound"] = True
        obs["risk_label_economic_semantics"] = LABEL_ECONOMICS
        packets.append(obs)
    return pd.concat(packets,ignore_index=True)


class ComparisonInputProvider:
    """Callbacks for TypedR2Fit and bank dependencies; no execution authority maker.

    Freeze fields: schema/status/source_policy, source_manifest_ref,
    actual_snapshot_timestamp, numeric_read_authorized=true and denied 2026 /
    Confirmation flags. bank_qqq_coordinate must explicitly freeze DAILY_QQQ.
    A domain callback(cutoff, ordered_assets) returns assets/current_assets/
    held_assets, asset_uids, asset_epochs, identity_epoch and identity_history.
    Native horizons require an additional caller callback returning actual typed
    observations and their frozen receipt. The old ER_* file is never used here.
    """
    def __init__(self, freeze_ref, domain_provider=None, *, reader=None, native_horizon_provider=None,
                 native_source_provider=None):
        self.freeze_ref = dict(freeze_ref); self.freeze = metadata(freeze_ref)
        f = self.freeze
        require(f.get("schema") == SCHEMA and f.get("status") == GATE and f.get("source_policy") == MODE
                and f.get("numeric_read_authorized") is True
                and f.get("test2026_read_authorized") is False
                and f.get("confirmation_read_authorized") is False, "ROOT_COMPARISON_INPUT_FREEZE_REQUIRED")
        require(f.get("strict_PIT_promotion_eligible") is False and f.get("account_qualification_granted") is False
                and f.get("fit_authority") is False, "INPUT_ROUTING_CANNOT_GRANT_QUALIFICATION_OR_FIT")
        require(f.get("risk_label_economic_semantics") == LABEL_ECONOMICS,
                "ACCEPTED_QUANTITY_PRICE_RISK_LABEL_PROXY_REQUIRED_NOT_FULL_CASH_RETURN")
        require(f.get("source_pins") == source_pins(), "COMPARISON_INPUT_OWNER_CODE_CHANGED")
        root = metadata(f["root_scope_ref"])
        require(root.get("research_id") == f["research_id"] and root.get("source_policy") == MODE
                and root.get("test2026_read_authorized") is False
                and root.get("confirmation_read_authorized") is False, "COMPARISON_ROOT_BOUNDARY_CHANGED")
        require(domain_provider is None or callable(domain_provider), "EXACT_CURRENT_AND_HELD_DOMAIN_PROVIDER_REQUIRED")
        self.source = metadata(f["source_manifest_ref"])
        self.science = dict(scientific_contract_identity=f["research_id"],
            scientific_contract_sha256=freeze_ref["sha256"], actual_snapshot_timestamp=f["actual_snapshot_timestamp"])
        self.reader = reader if reader is not None else r3.ProjectedReader(self.source, phase="numeric")
        self.calendar = self.reader.read("calendar", ("trade_date",), date_field="trade_date",
                                         stop="2026-01-01").trade_date
        self.native_horizon_provider = native_horizon_provider
        require(native_source_provider is None or native_horizon_provider is None, "ONE_NATIVE_SOURCE_OWNER_REQUIRED")
        self.native_source_provider = native_source_provider
        self.domain_provider = domain_provider or self.default_domain
        self.last_declaration = None

    def default_domain(self, cutoff, assets):
        """R3 contiguous-UID owner plus exact dated interval corroboration.

        The caller supplies the current/held union. This method does not infer
        which names are held, revive an expired universe or expand that union.
        Missing current metadata blocks the request; a label never removes it.
        """
        days, _ = packaging._calendar(self.calendar)
        prior = engine._time(cutoff).tz_convert(packaging.NY).tz_localize(None).normalize()
        stop = prior + pd.Timedelta(days=1)
        features = self.reader.read("prediction_features", r3.FEATURE_META, date_field="signal_date",
                                     stop=stop, tickers=assets)
        keys = self.reader.read("raw_open_close", ("ticker", "trade_date"), date_field="trade_date",
                                day=prior, tickers=assets)
        pool = r3.current_pool(features, keys, days, cutoff)
        require(set(pool["assets"]) == set(assets) and not pool["blocked_assets"],
                "BLOCK_REQUESTED_CURRENT_OR_HELD_DATED_UID_OR_RAW_KEY")
        intervals = self.reader.read("uid_intervals", ("ticker", "security_id", "effective_start"),
            date_field="effective_start", stop=stop, tickers=assets)
        for asset in assets:
            rows = intervals.loc[intervals.ticker.eq(asset)]
            require(not rows.empty, "BLOCK_NO_DATED_UID_INTERVAL:"+asset)
            latest = rows.loc[pd.to_datetime(rows.effective_start).eq(pd.to_datetime(rows.effective_start).max())]
            require(len(latest)==1 and latest.iloc[0].security_id == pool["asset_uids"][asset],
                    "BLOCK_DATED_UID_INTERVAL_MISMATCH:"+asset)
        pool["assets"] = tuple(assets)
        pool["identity_history"] = pool.pop("history")
        pool["identity_epoch"] = "CURRENT_POOL_OBSERVED_UIDS:"+r3.content_hash(pool["asset_epochs"])
        pool["domain_role"] = "EXACT_CURRENT_OR_HELD_UNION"
        pool["qualification_receipt"] = dict(status="DATED_UID_METADATA_BOUND_MECHANISM_ONLY",
            input_freeze_ref=self.freeze_ref, ordered_assets=list(assets), cutoff=str(cutoff),
            source_manifest_ref=self.freeze["source_manifest_ref"], owner="R3.current_pool",
            label_values_used_for_domain=False, future_interval_end_used=False,
            strict_PIT_promotion_eligible=False, account_qualification_granted=False)
        return pool

    def _domain(self, cutoff, assets):
        assets = tuple(assets); domain = self.domain_provider(cutoff, assets)
        declared_union = (domain.get("domain_role") == "EXACT_CURRENT_OR_HELD_UNION" or
            (set(domain.get("current_assets", ())) | set(domain.get("held_assets", ()))) == set(assets))
        require(assets and len(set(assets)) == len(assets) and tuple(domain["assets"]) == assets and declared_union
            and set(domain["asset_uids"]) == set(domain["asset_epochs"]) == set(assets),
            "EXACT_CURRENT_HELD_ASSET_ORDER_AND_UID_DOMAIN_REQUIRED")
        return domain

    def _labels(self, days, cutoff, assets, domain, *, lookback_sessions=306):
        prior = cutoff.tz_convert(packaging.NY).tz_localize(None).normalize()
        eligible = days[days < prior]
        require(len(eligible), "PRIOR_LABEL_CALENDAR_REQUIRED")
        start = eligible[0] if lookback_sessions is None else eligible[max(0,len(eligible)-lookback_sessions)]
        labels = self.reader.read("extended_shareholder_y5", (*r3.LABEL_META, "y_open5"),
            date_field="signal_date", start=start, stop=prior, tickers=assets, mature_before=prior)
        base = self.reader.read("shareholder_y5", ("ticker", "signal_date", "security_id"),
            date_field="signal_date", start=start, stop=prior, tickers=assets)
        require(not base.duplicated(["ticker", "signal_date"]).any(), "AMBIGUOUS_SOURCE_LABEL_UID")
        labels = labels.merge(base, on=["ticker", "signal_date"], how="left", validate="one_to_one")
        history = domain["identity_history"]
        require("identity_epoch" in history and not history.duplicated(["ticker", "signal_date"]).any(),
                "EXPLICIT_CONTIGUOUS_UID_HISTORY_REQUIRED")
        return labels.merge(history[["ticker", "signal_date", "identity_epoch"]],
                            on=["ticker", "signal_date"], how="left", validate="one_to_one")

    def typed_r2(self, method, date, assets):
        days, as_of, cutoff = decision_clocks(date, self.calendar)
        domain = self._domain(cutoff, assets); epoch = domain["identity_epoch"]
        labels = self._labels(days, cutoff, assets, domain)
        receipt = replace(r3._receipt(self.source, self.science, cutoff, epoch),
                          source_version="FROZEN_EXISTING_BYTES_R3|"+LABEL_ECONOMICS)
        prior = cutoff.tz_convert(packaging.NY).tz_localize(None).normalize()
        qstart = days[max(0, days.get_loc(prior)-360)]
        qq = self.reader.read("qqq_qfq_years", ("ticker", "trade_date", "open"), date_field="trade_date",
            start=qstart, stop=prior, tickers=("QQQ",))
        qreceipt = r3._receipt(self.source, self.science, cutoff, "EXISTING_QQQ_QFQ_OPEN_PROXY", benchmark=True)
        ff, ireceipt, reason = r3.asof_ff48(self.reader, self.source, self.science, domain, cutoff, epoch)
        assembly = packaging.assemble_risk_inputs(labels, days, assets=tuple(assets), asset_uids=domain["asset_uids"],
            asset_epochs=domain["asset_epochs"], identity_epoch=epoch, source_receipt=receipt, cutoff=cutoff,
            identity_history=domain["identity_history"], qqq_opens=qq, qqq_receipt=qreceipt,
            industry_mapping=ff, industry_receipt=ireceipt)
        if self.native_source_provider is not None:
            scope = self.freeze.get("native_source_scope")
            require(isinstance(scope,dict) and scope.get("source_refs")
                    and scope.get("risk_label_economic_semantics") == LABEL_ECONOMICS,
                    "SEPARATE_NATIVE_SOURCE_ASSEMBLY_FREEZE_REQUIRED")
            payload = self.native_source_provider(cutoff,tuple(assets),domain,scope)
            require(payload.get("source_refs") == scope["source_refs"], "NATIVE_ASSEMBLY_PHYSICAL_SOURCE_CHANGED")
            native_receipt = replace(receipt, source_identity="R12_NATIVE_R10_OWNER_QUANTITY_OPEN_PROXY",
                source_sha256=r3.content_hash(scope["source_refs"]))
            observations = assemble_native_shareholder_horizons(payload,domain,days,cutoff,native_receipt)
            assembly = append_native_horizons(assembly,observations,native_receipt,cutoff=cutoff)
        if self.native_horizon_provider is not None:
            require(self.freeze.get("native_horizon_ref") is not None, "SEPARATE_NATIVE_HORIZON_FREEZE_REQUIRED")
            native_horizon_metadata(self.freeze["native_horizon_ref"])
            obs, native_receipt = self.native_horizon_provider(cutoff, tuple(assets), domain,
                                                             self.freeze["native_horizon_ref"])
            require(native_receipt.source_sha256 == self.freeze["native_horizon_ref"]["sha256"],
                    "NATIVE_HORIZON_RECEIPT_NOT_THE_FROZEN_SOURCE")
            assembly = append_native_horizons(assembly, obs, native_receipt, cutoff=cutoff)
        self.last_declaration = dict(assembly.support_declarations)
        self.last_declaration["ff48_binding_reason"] = reason
        self.last_declaration["input_freeze_ref"] = self.freeze_ref
        self.last_declaration["signal_as_of"] = as_of.isoformat()
        self.last_declaration["shared_engine_previous_close_cutoff"] = cutoff.isoformat()
        self.last_declaration["risk_label_economic_semantics"] = LABEL_ECONOMICS
        self.last_declaration["risk_labels_include_cash_distributions"] = False
        return assembly.risk_input, as_of

    def scenario_training_frame(self, date, assets):
        """Full prior-year mature H5 table in the current requested UID segment."""
        days, _, current_cutoff = decision_clocks(date,self.calendar)
        domain = self._domain(current_cutoff,assets)
        year = pd.Timestamp(date).year; cutoff_date = pd.Timestamp(f"{year}-01-01")
        cutoff = packaging._clock(cutoff_date)
        labels = self._labels(days,cutoff,assets,domain,lookback_sessions=None)
        receipt = replace(r3._receipt(self.source,self.science,cutoff,domain["identity_epoch"]),
                          source_version="FROZEN_EXISTING_BYTES_R3|"+LABEL_ECONOMICS)
        packed = packaging.assemble_risk_inputs(labels,days,assets=tuple(assets),asset_uids=domain["asset_uids"],
            asset_epochs=domain["asset_epochs"],identity_epoch=domain["identity_epoch"],source_receipt=receipt,
            cutoff=cutoff,identity_history=domain["identity_history"])
        obs = packed.risk_input.observations
        local_date = lambda values: values.map(lambda t: engine._time(t).tz_convert(packaging.NY).tz_localize(None).normalize())
        frame = pd.DataFrame(dict(ticker=obs.asset,signal_date=local_date(obs.origin_at),
            execution_date=local_date(obs.entry_at),label_end_date=local_date(obs.endpoint_at),
            label_mature_date=local_date(obs.matured_at),y_open5=obs.return_value,
            fit_eligible=True,label_coordinate=packaging.STORED_LABEL_COORDINATE))
        refs = dict(input_freeze=self.freeze_ref,sources=self.freeze["source_manifest_ref"])
        details = dict(cutoff=cutoff_date,assets=tuple(assets),source_refs=refs,
            identity=dict(year=year,ordered_assets=tuple(assets),uids=domain["asset_uids"],
                epochs=domain["asset_epochs"],frame_sha256=r3.content_hash(frame),
                risk_label_economic_semantics=LABEL_ECONOMICS),provider_new_mean_fits=0)
        return frame,details

    def scenario(self,date,assets,*,mean_state_provider,account_assets=None,inactive_zero_padding_assets=()):
        require(callable(mean_state_provider),"CANONICAL_COUNTED_SCENARIO_DIAG_CALLBACK_REQUIRED")
        frame,details = self.scenario_training_frame(date,assets)
        cutoff = details["cutoff"]
        table = frame.loc[accounts.mature_training_mask(frame,cutoff)].pivot(
            index="signal_date",columns="ticker",values="y_open5").reindex(columns=assets)
        require(len(table)>=30 and table.count().ge(30).all(),"BLOCK_ACTIVE_SCENARIO_DOMAIN_BELOW30")
        params=dict(fit_cutoff=cutoff,return_unit=LABEL_ECONOMICS,return_horizon_sessions=5,
            source_id=r3.content_hash(details["source_refs"]),information_set_id=r3.content_hash(details["identity"]))
        # Callback owns canonical DIAG fit, durable two-state reservation and
        # exact year/UID/domain/frame identity reuse. This adapter never fits.
        state,dependency = mean_state_provider(table,cutoff=cutoff,assets=tuple(assets),
            source_refs=details["source_refs"],identity=details["identity"],params=params)
        require(dependency and state.status=="FITTED","COUNTED_SCENARIO_DIAG_FIT_OR_REUSE_RECEIPT_REQUIRED")
        require(state.specification.get("return_unit")==LABEL_ECONOMICS
            and state.specification.get("return_horizon_sessions")==5,"SCENARIO_MEAN_H5_PROXY_STATE_UNIT_REQUIRED")
        refs = dict(details["source_refs"],mean_preprocessor=dependency)
        return scenario_record(frame,assets,date,mean_state=(state,dependency),source_refs=refs,
            account_assets=account_assets,inactive_zero_padding_assets=inactive_zero_padding_assets)

    def reference(self,market,day):
        ref = self.freeze.get("consensus_roster_ref")
        require(ref and self.freeze.get("reference_definition")==REFERENCE,"FROZEN_CONSENSUS_RANK_REFERENCE_REQUIRED")
        path = r3._safe_source(ref["path"])
        r3._pin(path,ref["sha256"],"consensus_reference_roster")
        guard_parquet(path,ref["sha256"],["signal_date","decision_at","available_at","effective_at"])
        as_of = engine._time(market.signal_asof[day]); date = pd.Timestamp(market.dates[day])
        require(as_of<BOUNDARY and date<pd.Timestamp("2026-01-01"),"PRE2026_REFERENCE_REQUIRED")
        dataset = r3.ds.dataset(path,format="parquet")
        expr = r3.ds.field("signal_date")==r3.ProjectedReader._scalar(dataset,"signal_date",date)
        legal=accounts.legal_new_buy_domain(market)[day]
        expr &= r3.ds.field("ticker").isin(list(np.asarray(market.tickers)[legal]))
        clocks=("decision_at","available_at","effective_at")
        cols=["ticker","security_id","identity_present",*clocks]
        rows=dataset.to_table(columns=cols,filter=expr).to_pandas()
        eligible=pd.Series(True,index=rows.index)
        for field in clocks:
            eligible &= rows[field].map(engine._time).le(as_of)
        rows=rows.loc[eligible].copy()
        require(len(rows)>0,"BLOCK_EMPTY_LEGAL_FROZEN_CONSENSUS_REFERENCE")
        require(not rows.ticker.duplicated().any() and rows.identity_present.eq(True).all()
            and rows.security_id.map(lambda v:isinstance(v,str) and bool(v)).all(),"REFERENCE_DATED_UID_REQUIRED")
        # Clock columns in the actual roster are ISO strings. Bind their exact
        # already-qualified values before projecting numeric ranks; date-only
        # lexicographic comparison or implicit timezone casting is not valid.
        allowed=None
        for row in rows.itertuples(index=False):
            branch=(r3.ds.field("ticker")==row.ticker)&(r3.ds.field("security_id")==row.security_id)
            for field in clocks:branch &= r3.ds.field(field)==getattr(row,field)
            allowed=branch if allowed is None else allowed|branch
        ranks_frame=dataset.to_table(columns=["ticker","consensus_rank"],filter=expr&allowed).to_pandas()
        require(len(ranks_frame)==len(rows) and not ranks_frame.ticker.duplicated().any(),"REFERENCE_RANK_KEYS_CHANGED")
        ranks = pd.to_numeric(ranks_frame.set_index("ticker").consensus_rank,errors="raise")
        require(np.isfinite(ranks).all() and ranks.gt(0).all(),"FROZEN_CONSENSUS_RANK_REQUIRED")
        scores = -ranks.reindex(market.tickers).to_numpy(float)
        available = max(engine._time(v) for field in ("decision_at","available_at","effective_at") for v in rows[field])
        return reference_record(market,scores,day,source_refs=dict(roster=ref,input_freeze=self.freeze_ref),
            available_at=available,frozen_definition=REFERENCE,decision_as_of=as_of)

    def bank_dependencies(self, method, cutoff, assets):
        stamp = pd.Timestamp(cutoff)
        day = stamp.tz_convert("UTC").tz_localize(None).normalize() if stamp.tzinfo else stamp
        require(day == day.normalize() and day < pd.Timestamp("2026-01-01"), "PRE2026_BANK_DATE_CUTOFF_REQUIRED")
        days, _, previous = decision_clocks(day, self.calendar)
        refs = dict(input_freeze=self.freeze_ref, sources=self.freeze["source_manifest_ref"])
        if method == "FUNDAMENTAL":
            return dict(blocked_reason="BLOCK_NO_FROZEN_REAL_FUNDAMENTAL_FACTOR_SEMANTICS", source_refs=refs)
        if method == "SINGLE_INDEX":
            require(self.freeze.get("bank_qqq_coordinate") == DAILY_QQQ, "FROZEN_INDEPENDENT_QQQ_DAILY_COORDINATE_REQUIRED")
            prior = previous.tz_convert(packaging.NY).tz_localize(None).normalize()
            start = days[max(0, days.get_loc(prior)-120)]
            q = self.reader.read("qqq_qfq_years", ("ticker", "trade_date", "close"), date_field="trade_date",
                start=start, stop=day, tickers=("QQQ",))
            require(not q.trade_date.duplicated().any(), "AMBIGUOUS_QQQ_DAILY_SESSION")
            close = q.set_index("trade_date").close.reindex(days[(days >= start) & (days < day)])
            require(np.isfinite(close).all() and close.gt(0).all(), "BLOCK_MISSING_QUALIFIED_QQQ_DAILY_CLOSE")
            series = close.pct_change(fill_method=None).iloc[1:]
            series.attrs.update(source_id="FROZEN_INDEPENDENT_QQQ_QFQ_CLOSE", source_refs=refs,
                                return_coordinate=DAILY_QQQ, no_price_fill=True)
            available = packaging._clock(series.index[-1])
            if stamp.tzinfo is None: available = available.tz_localize(None)
            return dict(market_returns=series, available_at=available, source_refs=refs)
        require(method == "INDUSTRY", "UNREGISTERED_BANK_DEPENDENCY")
        domain = self._domain(previous, assets)
        frame, receipt, reason = r3.asof_ff48(self.reader, self.source, self.science, domain,
                                             previous, domain["identity_epoch"])
        if reason:
            return dict(blocked_reason=reason, source_refs=refs)
        groups = frame.set_index("asset").group.reindex(assets)
        exposures = pd.get_dummies(groups, prefix="FF48", dtype=float).reindex(index=assets)
        available = max(frame.available_at.max(), frame.effective_at.max())
        if stamp.tzinfo is None: available = available.tz_convert("UTC").tz_localize(None)
        exposures.attrs.update(pit_qualified=True, available_at=available,
            source_id=receipt.source_identity, source_sha256=receipt.source_sha256,
            historical_authority_status="UNKNOWN", strict_PIT_promotion_eligible=False,
            qualification_scope="FROZEN_HISTORY_MECHANISM_ONLY", source_refs=refs)
        return dict(exposure_frame=exposures, available_at=available, source_refs=refs)


def scenario_record(labels, assets, date, *, mean_state, source_refs,account_assets=None,inactive_zero_padding_assets=()):
    """Reuse one original annual scenario calculation and counted mean state."""
    cutoff = pd.Timestamp(f"{pd.Timestamp(date).year}-01-01")
    require(cutoff < pd.Timestamp("2026-01-01") and source_refs and mean_state is not None,
            "FROZEN_SCENARIO_LABELS_AND_COUNTED_MEAN_STATE_REQUIRED")
    clocks = ("signal_date", "execution_date", "label_end_date", "label_mature_date")
    meta = labels.loc[:, ["ticker", *clocks]].copy()
    mask = meta.ticker.isin(assets)
    for c in clocks:
        mask &= pd.to_datetime(meta[c]).lt(cutoff)
    require("label_coordinate" in labels and labels.loc[mask, "label_coordinate"].eq(
        packaging.STORED_LABEL_COORDINATE).all(), "SCENARIOS_REQUIRE_ORIGINAL_SHAREHOLDER_H5_UNIT")
    isolated = labels.loc[mask].copy()
    isolated["y_open5"] = pd.to_numeric(isolated["y_open5"], errors="raise")
    namespace = dict(accounts.scenario_inputs.__globals__, YEARS=(cutoff.year,))
    owner = FunctionType(accounts.scenario_inputs.__code__, namespace, accounts.scenario_inputs.__name__,
                         accounts.scenario_inputs.__defaults__)
    tables, known, receipts = owner(isolated, tuple(assets), {cutoff.year: mean_state})
    require(known[cutoff.year].all(), "BLOCK_SCENARIO_ASSET_SUPPORT_BELOW30")
    record = dict(assets=tuple(assets), values=tables[cutoff.year], source_refs=source_refs,
        available_at=isolated.label_mature_date.max(), label_mature_max=isolated.label_mature_date.max(),
        unit="FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN", owner_receipt=receipts[str(cutoff.year)])
    if account_assets is not None:
        inactive=tuple(inactive_zero_padding_assets)
        require(set(assets).isdisjoint(inactive) and set(assets)|set(inactive)==set(account_assets),
                "EXPLICIT_ACCOUNT_DOMAIN_AND_INACTIVE_PADDING_REQUIRED")
        record.update(account_assets=tuple(account_assets),inactive_zero_padding_assets=inactive)
    return record


def reference_record(market, scores, day, *, source_refs, available_at, frozen_definition=None,decision_as_of=None):
    require(frozen_definition == REFERENCE and source_refs,
            "BLOCK_NO_FROZEN_REFERENCE_BENCHMARK_DEFINITION")
    date = market.dates[day]
    as_of=engine._time(market.signal_asof[day] if decision_as_of is None else decision_as_of)
    require(engine._time(available_at)<=as_of<BOUNDARY and pd.Timestamp(date)<pd.Timestamp("2026-01-01"),
            "REFERENCE_SOURCE_MUST_BE_AVAILABLE_BY_SIGNAL_DECISION")
    # Restrict the existing owner to the requested row before it inspects scores.
    names = ("open", "close", "quality", "adv", "input_present", "new_buy_eligible", "signal_mask",
             "buy_restricted", "sell_restricted", "row_present")
    kwargs = {name: getattr(market, name)[day:day+1] for name in names}
    one = replace(market, dates=market.dates[day:day+1], signal_asof=market.signal_asof[day:day+1],
                  operational_exits={d: a for d, a in market.operational_exits.items() if d == date}, **kwargs)
    score_values=np.asarray(scores)
    current_scores=score_values[None,:] if score_values.ndim==1 else score_values[day:day+1]
    values = accounts.reference_portfolios(one,current_scores)[0]
    require(values.sum() > 0, "BLOCK_EMPTY_FROZEN_REFERENCE_DOMAIN")
    return dict(assets=tuple(market.tickers), values=values, available_at=available_at,
                decision_as_of=as_of,source_refs=source_refs)
