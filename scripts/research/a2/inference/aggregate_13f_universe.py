"""Aggregate a qualified, full-holdings 13F snapshot before taking its Top100.

This pure adapter owns no filing acquisition, snapshot selection, source
qualification, instrument policy, security mapping, or strategy implementation.
The caller binds an already-qualified snapshot and the existing frozen
``eligibility_v17b.classify_equity`` callable. Evidence fields are consistency
checks, not proof that the source was actually qualified: the caller must verify
the referenced source, qualification and USD-unit evidence before calling.

The original per-manager Top100/union implementation remains unchanged. All
input rows for the selected snapshot are reconciled before instrument filtering;
identity/price coverage must be assessed after this function, without backfill.
Other snapshot IDs are ignored, so appending a future snapshot cannot revise the
chosen vintage. This is not authorization to load restricted future input data.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import re
from typing import Callable

import pandas as pd

from scripts.storage.refresh_13f_quarter import active_managers, manager_roster_identity


class Aggregate13FContractError(ValueError):
    """The supplied full-holdings snapshot cannot support the requested ranking."""


def _fail(reason: str) -> None:
    raise Aggregate13FContractError(reason)


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail("INVALID_TEXT:" + field)
    return value


def _timestamp(value, field: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        _fail("INVALID_TIMESTAMP:" + field)
    if pd.isna(stamp) or stamp.tzinfo is None:
        _fail("TIMEZONE_REQUIRED:" + field)
    return stamp.tz_convert("UTC")


def _money(value, field: str) -> Decimal:
    if isinstance(value, bool):
        _fail("INVALID_USD_AMOUNT:" + field)
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail("INVALID_USD_AMOUNT:" + field)
    if not amount.is_finite() or amount < 0:
        _fail("INVALID_USD_AMOUNT:" + field)
    return amount


def aggregate_snapshot_top100(
    holdings: pd.DataFrame,
    manager_evidence: pd.DataFrame,
    registry: pd.DataFrame,
    *,
    quarter: str,
    snapshot_id: str,
    decision_at,
    classify_equity: Callable[[object, object, object, object], tuple[bool, str]],
    selection_rule: str = "AGGREGATE_USD",
    filing_policy: str = "RESOLVED_FULL_AS_FILED",
) -> dict:
    """Return a declared Top100 and its pre-coverage ranking/audit.

    ``manager_evidence`` has exactly one row per applicable manager in the chosen
    snapshot, including a declared zero-holdings manager. ``source_sha256`` binds
    the consolidated full snapshot for that manager; its recorded row count and
    USD total include rejected instruments too. ``accepted_at`` is the latest
    contributing initial/amendment disclosure. Amendment interpretation and the
    five-session activation rule belong to the existing snapshot owner.

    INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL accepts only the caller-bound
    first public original 13F-HR, with full_public_filing_complete and explicit
    amendments_handled=False. It uses disclosure_available_by as a conservative
    filing-date upper bound, never an invented acceptance timestamp. Completeness
    means public filing rows, never institution total assets. The source owner
    binds the five-session activation; original resolved-snapshot gates remain.

    Holdings require a unique ``source_row_id`` per manager and the same source
    SHA. Repeated CUSIPs with different source row IDs are legitimate and summed.
    The default AGGREGATE_USD rule preserves the original amount-ranked output.
    MANAGER_COUNT_WEIGHT_SUM orders by distinct disclosed manager count, then
    the sum of each manager's holding value / ALL its eligible-equity value,
    then historical CUSIP. Same-manager CUSIP lines are summed before weighting
    and count as one vote. Zero-value disclosed eligible lines retain a vote;
    there is no new minimum-position filter. A manager with eligible rows but
    zero total eligible value cannot support the ratio and is rejected. A
    manager without any eligible rows has no votes and remains in the cohort.
    Fraction comparison determines consensus order exactly; its Decimal display
    is rounded to 24 places and is never used for selection. Neither rule uses
    configured manager weights, ticker, identity or market coverage.
    """
    if filing_policy not in {"RESOLVED_FULL_AS_FILED", "INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL"}:
        _fail("UNKNOWN_FILING_POLICY")
    initial_public = filing_policy == "INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL"
    if selection_rule not in {"AGGREGATE_USD", "MANAGER_COUNT_WEIGHT_SUM"}:
        _fail("UNKNOWN_SELECTION_RULE")
    _text(snapshot_id, "snapshot_id")
    if not isinstance(quarter, str) or not re.fullmatch(r"20\d{2}Q[1-4]", quarter):
        _fail("INVALID_QUARTER")
    decision = _timestamp(decision_at, "decision_at")
    if pd.Period(quarter, freq="Q") >= decision.tz_convert("America/New_York").tz_localize(None).to_period("Q"):
        _fail("SAME_OR_FUTURE_REPORT_QUARTER")
    if not callable(classify_equity):
        _fail("BOUND_INSTRUMENT_CLASSIFIER_REQUIRED")
    required_holdings = {"snapshot_id", "quarter", "manager_id", "source_row_id",
        "source_sha256", "cusip", "issuer_name", "title_of_class", "ssh_prnamt_type",
        "put_call", "value_usd"}
    required_evidence = {"snapshot_id", "quarter", "manager_id", "holdings_scope",
        "full_report_complete", "amendment_resolved", "full_row_count", "full_value_usd",
        "source_sha256", "qualification_sha256", "unit_evidence_sha256", "accepted_at",
        "qualification_available_at", "effective_at"}
    if initial_public:
        required_evidence -= {"full_report_complete", "amendment_resolved", "accepted_at"}
        required_evidence |= {"full_public_filing_complete", "amendments_handled",
            "filing_form", "initial_public_filing", "filing_date", "disclosure_available_by"}
    for frame, required, label in ((holdings, required_holdings, "holdings"),
                                  (manager_evidence, required_evidence, "evidence")):
        if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
            _fail("REQUIRED_COLUMNS_MISSING:" + label)
    rows = holdings.loc[holdings.snapshot_id.eq(snapshot_id)].copy(deep=True)
    evidence = manager_evidence.loc[manager_evidence.snapshot_id.eq(snapshot_id)].copy(deep=True)
    if evidence.empty:
        _fail("SELECTED_SNAPSHOT_MISSING")
    for frame in (rows, evidence):
        if not frame.quarter.eq(quarter).all():
            _fail("SNAPSHOT_QUARTER_CONFLICT")
        for name in frame.manager_id:
            _text(name, "manager_id")
    if evidence.manager_id.duplicated().any():
        _fail("DUPLICATE_MANAGER_SNAPSHOT")
    active = active_managers(registry, quarter)
    expected = set(active.manager_id)
    if set(evidence.manager_id) != expected or not set(rows.manager_id).issubset(expected):
        _fail("APPLICABLE_MANAGER_COHORT_INCOMPLETE_OR_UNREGISTERED")
    for identifier in rows.source_row_id:
        _text(identifier, "source_row_id")
    if rows.duplicated(["manager_id", "source_row_id"]).any():
        _fail("DUPLICATE_SOURCE_ROW")
    rows["_usd"] = [_money(value, "value_usd") for value in rows.value_usd]
    activations = []
    for item in evidence.to_dict("records"):
        expected_scope = "FULL_INITIAL_PUBLIC_AS_FILED_HOLDINGS" if initial_public else "FULL_AS_FILED_HOLDINGS"
        if item["holdings_scope"] != expected_scope:
            _fail("TRUNCATED_OR_UNKNOWN_HOLDINGS_SCOPE")
        if initial_public:
            if (item["full_public_filing_complete"] is not True or item["amendments_handled"] is not False
                or item["filing_form"] != "13F-HR" or item["initial_public_filing"] is not True
                or item.get("amendment_resolved") is True):
                _fail("INITIAL_PUBLIC_FILING_POLICY_UNQUALIFIED")
        elif item["full_report_complete"] is not True or item["amendment_resolved"] is not True:
            _fail("FULL_REPORT_OR_AMENDMENT_UNQUALIFIED")
        for field in ("source_sha256", "qualification_sha256", "unit_evidence_sha256"):
            if not isinstance(item[field], str) or not re.fullmatch(r"[0-9a-f]{64}", item[field]):
                _fail("SOURCE_OR_QUALIFICATION_OR_UNIT_EVIDENCE_MISSING:" + field)
        accepted = _timestamp(item["disclosure_available_by"], "disclosure_available_by") if initial_public else _timestamp(item["accepted_at"], "accepted_at")
        if initial_public:
            filing_date = item["filing_date"]
            if not isinstance(filing_date, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", filing_date):
                _fail("INITIAL_PUBLIC_FILING_DATE_REQUIRED")
            next_day = (pd.Timestamp(filing_date) + pd.Timedelta(days=1)).tz_localize("America/New_York").tz_convert("UTC")
            if accepted < next_day:
                _fail("FILING_DATE_CONSERVATIVE_DISCLOSURE_BOUND_REQUIRED")
        qualified = _timestamp(item["qualification_available_at"], "qualification_available_at")
        effective = _timestamp(item["effective_at"], "effective_at")
        if accepted > decision or qualified > decision or effective > decision:
            _fail("FUTURE_DISCLOSURE_QUALIFICATION_OR_REVISION")
        if effective <= accepted or qualified < accepted:
            _fail("SNAPSHOT_AVAILABILITY_PRECEDES_DISCLOSURE")
        activations.append(effective)
        count = item["full_row_count"]
        if type(count) is not int or count < 0:
            _fail("INVALID_FULL_ROW_COUNT")
        group = rows.loc[rows.manager_id.eq(item["manager_id"])]
        if len(group) != count or not group.source_sha256.eq(item["source_sha256"]).all():
            _fail("FULL_SOURCE_ROW_COUNT_OR_HASH_MISMATCH")
        if sum(group._usd, Decimal(0)) != _money(item["full_value_usd"], "full_value_usd"):
            _fail("FULL_SOURCE_USD_TOTAL_MISMATCH")
    if len(set(activations)) != 1:
        _fail("MIXED_SNAPSHOT_ACTIVATION")
    eligible = []
    for item in rows.to_dict("records"):
        result = classify_equity(item["issuer_name"], item["title_of_class"],
                                 item["ssh_prnamt_type"], item["put_call"])
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not bool:
            _fail("INSTRUMENT_CLASSIFIER_RESULT_INVALID")
        if result[0]:
            cusip = str(item["cusip"]).strip().upper()
            if not re.fullmatch(r"[0-9A-Z*@#]{9}", cusip):
                _fail("HISTORICAL_CUSIP_IDENTITY_REQUIRED")
            eligible.append({"cusip": cusip, "manager_id": item["manager_id"], "_usd": item["_usd"]})
    if not eligible:
        _fail("NO_ELIGIBLE_EQUITIES")
    totals = {}
    for item in eligible:
        state = totals.setdefault(item["cusip"], {"amount": Decimal(0), "managers": set()})
        state["amount"] += item["_usd"]
        state["managers"].add(item["manager_id"])
    consensus = selection_rule == "MANAGER_COUNT_WEIGHT_SUM"
    weight_sums = {}
    if consensus:
        manager_totals, manager_positions = {}, {}
        for item in eligible:
            manager, cusip = item["manager_id"], item["cusip"]
            amount = Fraction(item["_usd"])
            manager_totals[manager] = manager_totals.get(manager, Fraction(0)) + amount
            key = (manager, cusip)
            manager_positions[key] = manager_positions.get(key, Fraction(0)) + amount
        if any(total <= 0 for total in manager_totals.values()):
            _fail("ZERO_ELIGIBLE_EQUITY_WEIGHT_DENOMINATOR")
        for (manager, cusip), amount in manager_positions.items():
            weight_sums[cusip] = weight_sums.get(cusip, Fraction(0)) + amount / manager_totals[manager]
        ordered = sorted(totals.items(), key=lambda item:
                         (-len(item[1]["managers"]), -weight_sums[item[0]], item[0]))
    else:
        ordered = sorted(totals.items(), key=lambda item: (-item[1]["amount"], item[0]))
    rank_column = "consensus_rank" if consensus else "amount_rank"
    ranking = pd.DataFrame([{"snapshot_id": snapshot_id, "quarter": quarter,
        "cusip": cusip, "aggregate_value_usd": state["amount"],
        "manager_count": len(state["managers"]), "manager_ids": ";".join(sorted(state["managers"])),
        rank_column: rank} for rank, (cusip, state) in enumerate(ordered, 1)])
    if consensus:
        exact, displayed = [], []
        # Audit display only. Fraction keys above, not rounded Decimal values,
        # resolve near ties deterministically and independently of input order.
        with localcontext() as context:
            context.prec = 50
            for cusip in ranking.cusip:
                weight = weight_sums[cusip]
                exact.append(f"{weight.numerator}/{weight.denominator}")
                displayed.append((Decimal(weight.numerator) / Decimal(weight.denominator))
                                 .quantize(Decimal("1e-24"), rounding=ROUND_HALF_EVEN))
        ranking["holding_weight_sum"] = displayed
        ranking["holding_weight_sum_exact"] = exact
    audit = {"snapshot_id": snapshot_id, "quarter": quarter,
        "decision_at": decision.isoformat(), "effective_at": activations[0].isoformat(),
        "roster": manager_roster_identity(registry, quarter),
        "full_source_rows": len(rows), "eligible_source_rows": len(eligible),
        "eligible_security_count": len(ranking), "selected_count": min(100, len(ranking)),
        "selection": "FULL_ELIGIBLE_DISCLOSED_USD_DESC_CUSIP_ASC_TOP100_BEFORE_COVERAGE",
        "qualification_scope": "INPUT_CONSISTENCY_ONLY_CALLER_VERIFIES_SOURCE_EVIDENCE"}
    if initial_public:
        audit.update(filing_policy=filing_policy, holdings_completeness="PUBLIC_INITIAL_FILING_ROWS_ONLY",
            amendments_handled=False, institution_total_assets_complete=False,
            exact_acceptance_timestamp="NOT_ASSERTED", historical_vendor_arrival="UNKNOWN",
            activation_rule="LATEST_INITIAL_FILING_DATE_PLUS_5_NYSE_SESSIONS_CALLER_BINDS",
            availability_basis="CONSERVATIVE_PUBLIC_FILING_DATE_UPPER_BOUND_NOT_VENDOR_ARRIVAL")
    if consensus:
        audit.update(selection_rule=selection_rule,
            selection="DISTINCT_MANAGER_COUNT_DESC_ELIGIBLE_EQUITY_WEIGHT_SUM_DESC_CUSIP_ASC_TOP100_BEFORE_COVERAGE",
            weight_denominator="EACH_MANAGER_FULL_ELIGIBLE_EQUITY_VALUE_SAME_SNAPSHOT",
            manager_vote_rule="ONE_PER_MANAGER_CUSIP_WITH_ELIGIBLE_DISCLOSED_ROW_NO_MINIMUM_POSITION",
            zero_eligible_total_rule="REJECT_IF_ELIGIBLE_ROWS_EXIST_OTHERWISE_NO_VOTE",
            weight_rank_arithmetic="EXACT_FRACTION",
            weight_display="DECIMAL_24_PLACES_HALF_EVEN_NOT_USED_FOR_RANKING")
    return {"members": ranking.head(100).copy(), "ranking": ranking, "audit": audit}
