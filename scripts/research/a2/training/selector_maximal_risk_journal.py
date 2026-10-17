"""One append-only C14 conditional delta over the original fit/solve authority.

No bank/state reader, fitter, matcher, risk estimator or worker is introduced.
The caller must qualify all 752 numeric inputs before activating a role. Original
ledgers are opaque immutable pins, never parsed or rewritten by this transport.
"""
from __future__ import annotations
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_maximal_breadth as owner
from scripts.research.a2.risk import event_risk_contract_r5 as event

RUN = Path("D:/us-tech-quant-backtests/V24/20261004T070941+0000_13adcb4c")
B_RUN = Path("D:/us-tech-quant-backtests/V24/20261004T044305+0000_d21499cc")
ID = "V24_C_SELECTOR_MAXIMAL_BREADTH_PRE2026_C14"
REPO = Path(__file__).resolve().parents[4]
OWNER_SHA = "6b24280e16581563ebcae5f5ff8708d5a6537b586e2227552e2b2c29b7ce503c"
EVENT_SHA = "ef17df6d655cc25796613282a87c8f04fe9ade62cf815c3ce06d22dd245a0b90"
BASELINE_FITS, BASELINE_SOLVES = 656, 18006
FIT_CAP, SOLVE_CAP, NAMED_CEILING = 1800, 30000, 29542
BASELINE_HASHES = {
    "DESIGN_FREEZE.json": "8bdcabcc09817691741d8aaaf7baab8ba663e0360e13cc62b9d918208ff901b6",
    "PHYSICAL_DAG.json": "b26dbcb71e63ea56263567cfd1ed8b086e8d8a221a5544ff9ab37e014e1dce85",
    "SOURCE_CLOSURE_RECEIPT.json": "4c8c5427db4b5b2b1cf7510226687a52a82a8ad388d18e45ea84abeff57fe16d",
    "FIT_LEDGER.json": "fc24cdf60a368ce055fe19f87d31acc8212ca1b35f0b23ba8a67d07f5dbb6111",
    "SOLVE_LEDGER.json": "ad9face8ac53c35d88944844f07f077a9a76acf0e7dcf1ee575b590a18c67d10",
    "SOLVE_EVENTS.jsonl": "4b0e2917bf91d55968aae8f01ee34aad8d9841ede28da9905c68f2eceb24669d",
}
RX_COUNTS = {
    "C14_RX_RIDGE_DIAG": 14, "C14_RX_HGB_LW": 14,
    "C14_RX_XGB_QQQ_RESIDUAL": 14, "C14_RX_CAT_DOWNSIDE_SEMIVARIANCE": 34,
    "C14_RX_MLP_REGIME_COVARIANCE": 34, "C14_RX_QUANTILE_UNCERTAINTY_JACKKNIFE": 34,
}
ACTIVE_RX = {"C14_RX_HGB_LW": "LW", "C14_RX_XGB_QQQ_RESIDUAL": "QQQ_RESIDUAL"}
TERMINAL_FITS = {"COMPLETE", "FAILED", "BLOCKED_DEPENDENCY"}
SOURCE_GUARD_REVIEW_NAME = "C14_TERMINAL_SOURCE_GUARD_RECOVERY_REVIEW_R1.json"
SOURCE_GUARD_BACKUP_ROOT = "source_corrections/C14_TERMINAL_SOURCE_GUARD_RECOVERY_R1"
SOURCE_GUARD_SOURCES = {
    "scripts/research/a2/training/selector_maximal_risk_journal.py":
        "ab2ac39a22440892b1f99d8b9f2fbb70b28d260ec449e98349f9046ae48bd674",
    "scripts/research/a2/evaluation/selector_maximal_risk_execution.py":
        "95d57d78291058e32f6620f861da46a3f3a902021399bfa5ea99d53dcc07866e",
    "scripts/research/a2/training/selector_maximal_risk_hybrids.py":
        "aed6e06f59077a3dd8c665f17f44d382810bd125c766e2810e641d6c2b65e38d",
    "scripts/research/a2/training/selector_maximal_risk_membership.py":
        "a2fec18c01cd7de3fb1c4eaad0cac0159942762b918877a038882f60fb680fe7",
}
SOURCE_GUARD_REFS = {
    "original_source_review": ("RISK_INPUT_SOURCE_REVIEW_R3.json",
        "94494524c91fac4cac34eff9283c4b2e546d668c2478edebf693c3089d249b6e"),
    "qualification": ("risk_execution/source_metadata_recovery_r1/INPUT_QUALIFICATION_R1.json",
        "a4976c8990b9af5e5107bcaeeed70ff7d15680f8659d4680fdeb6e4d646f99d3"),
    "prior_terminal": ("risk_execution/source_metadata_recovery_r1/RISK_DECISIONS_TERMINAL_R1.json",
        "f4ac7ecb650787b9695470080b4284f54333c2062278cc3b55a4794d6a208bf2"),
    "prior_audit": ("risk_execution/source_metadata_recovery_r1/CHECKPOINT_CLASSICAL_RESUME_COMPLETE_R2.json",
        "52fe1ba01fc7273b7e6e482b3d689287da6939802e905dca822fef3de1c05f11"),
}
SOURCE_GUARD_PREFIX = dict(bytes=13094104, lines=5597,
    sha256="12c5f2a1866b6693d92985d73982db2e55bec1e0b166ee17cdf0261b6486d948")
SOURCE_GUARD_CHARGED = 2793
SOURCE_GUARD_ROLES = {*ACTIVE_RX, "C14_D01", "C14_D05", "C14_D06", "C14_D09", "C14_D10", "C14_D11"}
SOURCE_GUARD_BLOCK_REASON = "UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS"


POST_REBOOT_REVIEW_NAME = "C14_POST_REBOOT_CLASSICAL_CHECKPOINT_REVIEW_R1.json"
POST_REBOOT_BACKUP_ROOT = "source_corrections/C14_POST_REBOOT_CLASSICAL_CHECKPOINT_R1"
POST_REBOOT_SOURCES = {
    "scripts/research/a2/training/selector_maximal_risk_journal.py":
        "1525702202d93bd2b35bc4b98fb9d71fd3ec44d4d80439823aa42e7b6c0bea6c",
    "scripts/research/a2/evaluation/selector_maximal_risk_resume.py":
        "1a6cf59a48851058d85e0c35bca777db784ac3d71293ac19bc83716cf5d0798e",
    "tests/research/a2/training/test_selector_maximal_risk_journal.py":
        "8f6002693e885e837e5934ab099d4fd92d692351ed5c38297a4209def13cfa30",
    "tests/research/a2/evaluation/test_selector_maximal_risk_resume.py":
        "bd8ebfc4847809bee29dadddffa23005b317cad934792dd02c66638bb321b06c",
}
POST_REBOOT_PREFIX = dict(bytes=15563481, lines=7832,
    sha256="94829aa339c9128665fef95a0650d45cd029c38387e8f1a95e57260ce443734e")
POST_REBOOT_COUNTS = {"C14_D01": 752, "C14_D05": 752, "C14_D06": 752,
                      "C14_D09": 608, "C14_RX_HGB_LW": 502, "C14_RX_XGB_QQQ_RESIDUAL": 502}
POST_REBOOT_EVENT_SEQUENCE = 5597
POST_REBOOT_REFS = {
    "original_source_guard_review": ("run", "C14_TERMINAL_SOURCE_GUARD_RECOVERY_REVIEW_R1.json",
        "0f3d8ed74282ec026a7238e8d7afdfe0cde8f53c034c99694a8c18f5449b697b"),
    "prior_runtime_source_review": ("run", "RISK_INPUT_SOURCE_REVIEW_R4.json",
        "b5372ea2703639b1c3e44d90d6f0cc9f9780175d8164506b081f85b8fae1891f"),
    "old_marker": ("run", "risk_execution/source_guard_recovery_r1/SOURCE_GUARD_RECOVERY_STARTED_R1.json",
        "57b7a0860bb53c61f459eb05d298957fc57e78e5938d11eb4f76fc0396156b91"),
    "reboot_receipt": ("maintenance", "POST_REBOOT_CHECKPOINT_OBSERVATION_R1.json",
        "31df277876e354db95203bc35fffdf71c292a89376b34ffe0769059ec97516a3"),
    "independent_RX_completion": ("maintenance", "TERMINAL_SOURCE_GUARD_RX_COMPLETE_OBSERVATION_R1.json",
        "69df4659a7c5506e29001a44ab3728616186e2011f274c011bc3419e20788e91"),
}
POST_REBOOT_MAINTENANCE = Path("D:/us-tech-quant-results/V24/C_SELECTOR/C14_MAXIMAL_BREADTH/_maintenance/C14_RISK_EXECUTION_ENGINEERING_R1")
POST_REBOOT_FIELDS = {
    "schema", "status", "research_id", "classification", "independent_review",
    "scientific_contract_changed", "scientific_retry", "test2026_rows_read",
    "source_pins", "source_backups", "original_source_guard_review", "prior_runtime_source_review",
    "runtime_source_review", "checkpoint_delta", "old_recovery_event", "old_marker",
    "reboot_receipt", "input_qualification", "completed_fit_artifacts", "completed_role_artifacts",
    "remaining_classical_roles", "snapshot_transport", "execution_configuration", "B_freeze",
    "original_publication_admission", "independent_RX_completion",
}


class RiskJournalBlocked(ValueError):
    """A conditional operation is blocked without refund or implicit retry."""


def need(condition, reason):
    if not condition:
        raise RiskJournalBlocked(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def cloned(value):
    return json.loads(canonical(value))


def stamp(path):
    s = Path(path).stat()
    return s.st_size, s.st_mtime_ns, s.st_ctime_ns


def hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def date_token(value):
    text = str(value)
    need(len(text) == 19 and text.endswith("T00:00:00"), "EXACT_NAMED_DECISION_DATE_REQUIRED")
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise RiskJournalBlocked("EXACT_NAMED_DECISION_DATE_REQUIRED") from error
    need(parsed.isoformat() == text and parsed.year < 2026, "PRE2026_DECISION_REQUIRED")
    return text


@contextmanager
def exclusive(stream):
    """OS lock plus revision check prevents concurrent stale writers."""
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class _RequestView(Mapping):
    """Copy just the requested cache row, never the complete numeric cache."""
    def __init__(self, requests):
        self._requests = requests

    def __getitem__(self, token):
        return copy.deepcopy(self._requests[token])

    def __iter__(self):
        return iter(self._requests)

    def __len__(self):
        return len(self._requests)


class ConditionalFitLedger:
    """Restricted Ledger protocol used by the byte-identical stored_fit owner."""
    def __init__(self, journal):
        self.journal = journal
        self.run = journal.run

    @property
    def value(self):
        return dict(research_id=ID, design_sha256=BASELINE_HASHES["DESIGN_FREEZE.json"],
                    hard_cap=FIT_CAP, scientific_retries=0, slots=copy.deepcopy(self.journal.slots))

    def begin(self, node, identity):
        j = self.journal
        j.verify()
        need(node in j.slots, "UNNAMED_CONDITIONAL_FIT")
        slot = j.slots[node]
        if slot["status"] == "COMPLETE":
            need(slot["identity"] == cloned(identity), "EXACT_MODEL_REUSE_IDENTITY_CHANGED")
            j.model_artifact(slot["artifact"], node)
            return False
        need(slot["status"] == "RESERVED", "ZERO_RETRY_RESERVED_ONLY:" + node)
        need(str(identity.get("cutoff")) == str(slot["cutoff"]), "EXACT_FROZEN_FIT_CUTOFF_REQUIRED")
        j.emit("FIT_BEGIN", dict(node=node, identity=identity))
        return True

    def entered(self, node, event=None):
        self.journal.emit("FIT_ENTER", dict(node=node, event=event))

    def finish(self, node, status, **details):
        j = self.journal
        need(status in TERMINAL_FITS, "TERMINAL_STATUS_REQUIRED")
        need(node in j.slots and j.slots[node]["status"] == "STARTED", "FIT_STARTED_TRANSITION_REQUIRED")
        if status == "COMPLETE":
            need(j.slots[node]["entered"] == 1, "COMPLETE_REQUIRES_ONE_BACKEND_ENTER")
            j.model_artifact(details.get("artifact"), node)
        need(not (set(details) & {"status", "entered", "identity", "node_id"}), "FIT_CONTROL_FIELDS_IMMUTABLE")
        j.emit("FIT_FINISH", dict(node=node, status=status, details=details))


class RiskJournal:
    """Transport only; FULL752 gate construction belongs to the reviewed caller."""
    def __init__(self, run, *, source_guard_recovery_ref=None, post_reboot_checkpoint_ref=None):
        self.run = Path(run).resolve()
        need(self.run == RUN.resolve(), "EXACT_ORIGINAL_C14_RUN_REQUIRED")
        self.path = self.run / "RISK_EXECUTION_DELTA.jsonl"
        assert_safe_output_path(self.path, kind="backtest", paths=resolve(REPO))
        owner.safe_d(self.path)
        self.pins = {}
        for name, expected in BASELINE_HASHES.items():
            self.pin(self.run / name, expected)
        self.pin(Path(owner.__file__), OWNER_SHA)
        self.pin(Path(event.__file__), EVENT_SHA)
        self.pin(Path(__file__), sha(__file__))
        # Only frozen design/DAG metadata is materialized. Old ledgers stay opaque.
        design = json.loads((self.run / "DESIGN_FREEZE.json").read_text(encoding="utf-8"))
        dag = json.loads((self.run / "PHYSICAL_DAG.json").read_text(encoding="utf-8"))
        need(design.get("research_id") == dag.get("research_id") == ID, "RESEARCH_ID_CHANGED")
        checks = dict(active_ml_fit_state_nodes=656, conditional_risk_fit_state_nodes=144,
                      maximum_named_fit_state_nodes=800, physical_fit_hard_cap=1800,
                      optimizer_solve_hard_cap=30000, admissible_solve_request_ceiling=29542,
                      conditional_hybrid_solves=3012, conditional_classical_solves=7520,
                      scientific_retry=0, failed_reservation_refund=False,
                      shared_risk_new_estimation_by_C=0, shared_risk_learned_cap=3000,
                      conditional_ml_not_reserved_until_qualified=True)
        need(all(type(dag.get(k)) is type(v) and dag[k] == v for k, v in checks.items()),
             "ORIGINAL_COMBINED_BUDGET_AUTHORITY_CHANGED")
        nodes = dag["conditional_risk_fit_nodes"]
        names = [n["node_id"] for n in nodes]
        need(len(names) == len(set(names)) == 144, "EXACT144_UNIQUE_CONDITIONAL_NODES_REQUIRED")
        need({r: sum(n["candidate_id"] == r for n in nodes) for r in RX_COUNTS} == RX_COUNTS
             and all(n["candidate_id"] in RX_COUNTS for n in nodes), "ORIGINAL_RX_NODE_ROSTER_CHANGED")
        need(all(n["node_id"].startswith(("RX_SCALER|", "RX_MODEL|"))
                 and str(n["cutoff"]) < "2026-01-01" for n in nodes), "ORIGINAL_RX_NODE_KIND_OR_CUTOFF_CHANGED")
        requests = dag["solve_request_ids"]
        need(len(requests) == len(set(requests)) == NAMED_CEILING, "DUPLICATE_OR_CHANGED_NAMED_SOLVES")
        self.allowed_solves = {s for s in requests if s.startswith(("HYBRID|", "CLASSICAL|"))}
        need(sum(s.startswith("HYBRID|") for s in self.allowed_solves) == 3012
             and sum(s.startswith("CLASSICAL|") for s in self.allowed_solves) == 7520,
             "EXACT_CONDITIONAL_SOLVE_ROSTER_REQUIRED")
        self.dates = tuple(sorted(s.rsplit("|", 1)[1] for s in requests if s.startswith("CLASSICAL|C14_D01|")))
        need(len(self.dates) == len(set(self.dates)) == 752, "ORIGINAL752_DATE_MASK_REQUIRED")
        for value in self.dates:
            date_token(value)
        risk = design["risk"]
        self.families = {v["candidate_id"]: v["family"] for v in risk["hybrid_bindings"]}
        self.families.update({v["candidate_id"]: v["family"] for v in risk["classical_bindings"]
                              if v["existing_rule"] != "RAW_IDENTITY" and v["candidate_id"] != "C14_D12"})
        need(all(self.families.get(r) == f for r, f in ACTIVE_RX.items()), "CURRENT_RX_FAMILY_CHANGED")
        self.slots = {n["node_id"]: dict(cloned(n), status="UNRESERVED", entered=0) for n in nodes}
        self.requests, self.roles = {}, {}
        self.source_guard_recovery_ref = None
        self._source_guard_review = None
        self._source_guard_recovered = False
        self._fit_seen = False
        self._block_history = {}
        self._post_reboot_review = None
        self._post_reboot_checked = False
        self._post_reboot_transport = {}
        self.sequence, self.previous = 0, "0" * 64
        self.last_stamp = stamp(self.path) if self.path.exists() else None
        self.header = dict(schema="C14_CONDITIONAL_EXECUTION_DELTA_V1", research_id=ID,
                           original_pins=BASELINE_HASHES, baseline_fit_slots=BASELINE_FITS,
                           baseline_charged_solves=BASELINE_SOLVES, fit_hard_cap=FIT_CAP,
                           solve_hard_cap=SOLVE_CAP, all_named_solve_ceiling=NAMED_CEILING,
                           original_conditional_fit_nodes=144, currently_activatable_fit_nodes=28,
                           scientific_retry=0, failed_reservation_refund=False,
                           strict_PIT_promotion_eligible=False)
        need(source_guard_recovery_ref is None or post_reboot_checkpoint_ref is None,
             "POST_REBOOT_DISTINCT_EXPLICIT_ADMISSION_REQUIRED")
        if post_reboot_checkpoint_ref is not None:
            self._post_reboot_custody(post_reboot_checkpoint_ref)
        if source_guard_recovery_ref is not None:
            self._source_guard_custody(source_guard_recovery_ref)
        if self.path.exists():
            with self.path.open(encoding="utf-8") as stream:
                for line in stream:
                    need(line.endswith("\n"), "INCOMPLETE_DELTA_ROW_NO_AUTOMATIC_REPAIR")
                    row = json.loads(line)
                    self.accept(row)
                    if self._post_reboot_review is not None and self.sequence == POST_REBOOT_PREFIX["lines"]:
                        self._post_reboot_boundary()
            need(self.sequence > 0, "EMPTY_EXISTING_DELTA_FORBIDDEN")
            need(self._post_reboot_review is None or self._post_reboot_checked,
                 "POST_REBOOT_COMPLETE_CHECKPOINT_NOT_REPLAYED")
        else:
            self.emit("HEADER", self.header)
        self.fit_ledger = ConditionalFitLedger(self)
        # Resume revalidates independent gate/source pins; no state payload loads.
        for role, stored in self.roles.items():
            need(self.qualify_role(role, stored["qualification_ref"]) == stored,
                 "ROLE_QUALIFICATION_CHANGED")

    def pin(self, path, expected):
        path = owner.safe_d(path).resolve()
        need(hex64(expected), "EXACT_SHA256_PIN_REQUIRED")
        before = stamp(path)
        need(sha(path) == expected and before == stamp(path), "PHYSICAL_AUTHORITY_PIN_CHANGED:" + path.name)
        self.pins[str(path)] = (expected, before)
        return path

    def verify(self):
        for path, (_, expected_stamp) in self.pins.items():
            need(stamp(path) == expected_stamp, "PHYSICAL_AUTHORITY_CHANGED:" + Path(path).name)
        need((stamp(self.path) if self.path.exists() else None) == self.last_stamp,
             "DELTA_CHANGED_OR_CONCURRENT_WRITER")

    def read_ref(self, reference, root):
        need(isinstance(reference, dict) and set(reference) == {"path", "sha256"}, "EXACT_PINNED_REFERENCE_REQUIRED")
        path = owner.safe_d(reference["path"]).resolve()
        need(path.is_relative_to(Path(root).resolve()), "REFERENCE_CUSTODY_CHANGED")
        self.pin(path, reference["sha256"])
        return json.loads(path.read_text(encoding="utf-8"))

    def qualify_role(self, role, qualification_ref):
        """Read the independent gate only; native state payloads remain unopened."""
        self.verify()
        need(role in self.families, "UNNAMED_CONDITIONAL_ROLE")
        need(role not in RX_COUNTS or role in ACTIVE_RX, "RX_FAMILY_NOT_CURRENTLY_QUALIFIED")
        gate = self.read_ref(qualification_ref, self.run)
        need(gate.get("phase") == "FULL752_NUMERIC_INPUT_QUALIFIED"
             and gate.get("research_id") == ID and gate.get("role") == role
             and gate.get("family") == self.families[role]
             and gate.get("design_sha256") == BASELINE_HASHES["DESIGN_FREEZE.json"]
             and gate.get("dag_sha256") == BASELINE_HASHES["PHYSICAL_DAG.json"]
             and gate.get("full_required_dates_qualified") is True
             and type(gate.get("test2026_rows_read")) is int and gate["test2026_rows_read"] == 0,
             "INDEPENDENT_FULL752_NUMERIC_GATE_REQUIRED")
        review = self.read_ref(gate["source_review"], self.run)
        source_pins = review.get("source_pins", {})
        own_path = str(Path(__file__).resolve())
        approved = self._source_guard_review
        prior_sources = ({str((REPO / p).resolve()): h for p, h in SOURCE_GUARD_SOURCES.items()}
                         if approved is not None else {})
        required = {str(Path(owner.__file__).resolve()): OWNER_SHA,
                    str(Path(event.__file__).resolve()): EVENT_SHA,
                    own_path: prior_sources.get(own_path, sha(__file__))}
        if approved is not None:
            need(gate["source_review"] == approved["original_source_review"],
                 "SOURCE_GUARD_ORIGINAL_QUALIFICATION_REVIEW_REQUIRED")
        need(review.get("status") == "PASS" and review.get("research_id") == ID
             and all(source_pins.get(p) == h for p, h in required.items()), "EXACT_REVIEWED_TRANSPORT_SOURCE_CLOSURE_REQUIRED")
        for p, h in source_pins.items():
            need(Path(p).resolve().is_relative_to(REPO.resolve()) and Path(p).suffix == ".py",
                 "SOURCE_REVIEW_SOURCE_ONLY")
            if p in prior_sources:
                need(h == prior_sources[p], "SOURCE_GUARD_PRIOR_SOURCE_PIN_CHANGED")
                self._fixed_transport_pin(p, approved["source_pins"][p])
            else:
                self.pin(p, h)
        states = gate.get("states", [])
        need(len(states) == 752 and [s.get("decision_date") for s in states] == list(self.dates),
             "FULL752_NUMERIC_GATE_NO_SHORTENING")
        for state in states:
            ref = state.get("state_ref")
            need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and Path(ref["path"]).is_absolute() and Path(ref["path"]).resolve().is_relative_to(B_RUN.resolve())
                 and hex64(ref["sha256"]), "EXACT_ORIGINAL_R5_STATE_REFERENCE_REQUIRED")
            need(all(state.get(k) is True for k in ("header_qualified", "current_UID_qualified", "numeric_qualified"))
                 and hex64(state.get("full_U_keys_sha256")), "ALL_STATE_HEADER_UID_NUMERIC_GATES_REQUIRED")
        value = dict(qualification_ref=cloned(qualification_ref), family=self.families[role],
                     states_sha256=digest(states), dates=states)
        return value

    def activate_role(self, role, qualification_ref):
        """Require independent full752 numeric gate, never source-only readiness."""
        value = self.qualify_role(role, qualification_ref)
        if role in self.roles:
            need(self.roles[role] == value, "ROLE_QUALIFICATION_CHANGED")
            return
        self.emit("ACTIVATE_ROLE", dict(role=role, qualification=value))

    def model_artifact(self, reference, node):
        need(isinstance(reference, dict) and set(reference) == {"path", "sha256"}, "EXACT_MODEL_ARTIFACT_REQUIRED")
        path = self.model_destination(reference["path"], node)
        self.pin(path, reference["sha256"])
        return path

    def model_destination(self, path, node):
        path = owner.safe_d(path).resolve()
        need(path.is_relative_to(self.run / "risk_execution" / "models"), "CONDITIONAL_MODEL_DESTINATION_REQUIRED")
        need(path.name == owner.content_hash(node) + ".joblib", "EXACT_NODE_MODEL_ARTIFACT_REQUIRED")
        assert_safe_output_path(path, kind="backtest", paths=resolve(REPO))
        return path

    def stored_fit(self, node, identity, model_path, fit):
        self.verify()
        need(node in self.slots and self.slots[node]["status"] != "UNRESERVED", "QUALIFIED_RX_RESERVATION_REQUIRED")
        model_path = self.model_destination(model_path, node)
        need(self.slots[node]["status"] == "COMPLETE" or not model_path.exists(),
             "EXISTING_NONCOMPLETE_MODEL_ARTIFACT_PRESERVED")
        # Existing fitter, serializer, thread cap and failed-fit handling are reused.
        return owner.stored_fit(self.fit_ledger, node, identity, model_path, fit)

    def block_remaining(self, role, reason):
        """Terminalize only unused reservations; never enter a backend or refund."""
        self.verify()
        need(role in ACTIVE_RX and role in self.roles, "ACTIVATED_CURRENT_RX_ROLE_REQUIRED")
        need(isinstance(reason, str) and bool(reason.strip()), "DEPENDENCY_BLOCK_REASON_REQUIRED")
        role_slots = {node: slot for node, slot in self.slots.items() if slot["candidate_id"] == role}
        need(not any(slot["status"] == "STARTED" for slot in role_slots.values()),
             "UNRESOLVED_STARTED_FIT_REQUIRES_FAILURE_RECEIPT")
        nodes = sorted(node for node, slot in role_slots.items() if slot["status"] == "RESERVED")
        need(all(role_slots[node]["entered"] == 0 for node in nodes), "UNTOUCHED_RESERVATION_REQUIRED")
        if nodes:
            self.emit("BLOCK_REMAINING", dict(role=role, nodes=nodes, reason=reason))
        return nodes

    def _fixed_transport_pin(self, path, expected):
        """Keep public pin/sha physical; only a fully admitted old R1 pin moves."""
        key = str(Path(path).resolve())
        if key in self._post_reboot_transport:
            old_sha, new_sha = self._post_reboot_transport[key]
            need(expected == old_sha, "POST_REBOOT_EXACT_OLD_DECLARED_SOURCE_PIN_REQUIRED")
            return self.pin(path, new_sha)
        return self.pin(path, expected)

    def _post_reboot_custody(self, reference):
        need(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
             and Path(reference["path"]).resolve() == self.run / POST_REBOOT_REVIEW_NAME,
             "POST_REBOOT_FIXED_FORMAL_REQUIRED")
        review = self.read_ref(reference, self.run)
        need(set(review) == POST_REBOOT_FIELDS
             and review["schema"] == "C14_POST_REBOOT_CLASSICAL_CHECKPOINT_V1"
             and review["status"] == "PASS" and review["research_id"] == ID
             and review["classification"] == "POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_ENGINEERING"
             and review["independent_review"] is True
             and review["scientific_contract_changed"] is False
             and type(review["scientific_retry"]) is int and review["scientific_retry"] == 0
             and type(review["test2026_rows_read"]) is int and review["test2026_rows_read"] == 0,
             "POST_REBOOT_CLOSED_REVIEWED_ENGINEERING_ONLY_REQUIRED")
        fixed = {}
        for key, (kind, relative, expected) in POST_REBOOT_REFS.items():
            root = self.run if kind == "run" else POST_REBOOT_MAINTENANCE.resolve()
            ref = review[key]
            need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and Path(ref["path"]).resolve() == root / relative and ref["sha256"] == expected,
                 "POST_REBOOT_EXACT_PRIOR_AUTHORITY_REQUIRED:" + key)
            fixed[key] = self.read_ref(ref, root)
        old, r4 = fixed["original_source_guard_review"], fixed["prior_runtime_source_review"]
        prior = {str((REPO / p).resolve()): h for p, h in POST_REBOOT_SOURCES.items()}
        need(isinstance(review["source_pins"], dict) and isinstance(review["source_backups"], dict)
             and set(review["source_pins"]) == set(review["source_backups"]) == set(prior)
             and all(old["source_pins"].get(p) == h for p, h in prior.items()),
             "POST_REBOOT_EXACT_FOUR_PRIOR_DECLARED_SOURCES_REQUIRED")
        bridge = {}
        for relative, old_sha in POST_REBOOT_SOURCES.items():
            path = (REPO / relative).resolve()
            suffix = Path("tests") / "training" if relative.startswith("tests/") and path.name.endswith("journal.py") else (
                     Path("tests") / "evaluation" if relative.startswith("tests/") else Path(relative).parent.name)
            backup = self.run / POST_REBOOT_BACKUP_ROOT / suffix / path.name
            ref = review["source_backups"][str(path)]
            need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and Path(ref["path"]).resolve() == backup and ref["sha256"] == old_sha,
                 "POST_REBOOT_EXACT_PHYSICAL_SOURCE_BACKUP_REQUIRED")
            self.pin(backup, old_sha)
            self.pin(path, review["source_pins"][str(path)])
            bridge[str(path)] = (old_sha, review["source_pins"][str(path)])
        need(review["checkpoint_delta"] == dict(path=str(self.path), **POST_REBOOT_PREFIX),
             "POST_REBOOT_EXACT_CHECKPOINT_PREFIX_REQUIRED")
        with self.path.open("rb") as stream:
            raw = stream.read(POST_REBOOT_PREFIX["bytes"])
        need(len(raw) == POST_REBOOT_PREFIX["bytes"] and raw.endswith(b"\n") and b"\r" not in raw
             and raw.count(b"\n") == POST_REBOOT_PREFIX["lines"]
             and hashlib.sha256(raw).hexdigest() == POST_REBOOT_PREFIX["sha256"],
             "POST_REBOOT_PRESERVED_CHECKPOINT_BYTES_REQUIRED")
        need(review["old_recovery_event"] == dict(sequence=POST_REBOOT_EVENT_SEQUENCE,
             review_ref=review["original_source_guard_review"], nodes=old["recover_rx_nodes"]),
             "POST_REBOOT_EXACT_OLD_ONCE_EVENT_REQUIRED")
        need(review["remaining_classical_roles"] == ["C14_D09", "C14_D10", "C14_D11"]
             and review["input_qualification"] == old["qualification"]
             and review["execution_configuration"] == old["original_config"]
             and review["B_freeze"] == old["B_freeze"]
             and review["original_publication_admission"] == old["original_publication_admission"]
             and review["snapshot_transport"] == old["snapshot_transport"],
             "POST_REBOOT_ORIGINAL_INPUT_CONTRACT_UNCHANGED_REQUIRED")
        for key in ("input_qualification", "execution_configuration", "original_publication_admission"):
            self.read_ref(review[key], self.run)
        self.read_ref(review["B_freeze"], B_RUN)
        r5ref = review["runtime_source_review"]
        need(isinstance(r5ref, dict) and set(r5ref) == {"path", "sha256"}
             and Path(r5ref["path"]).resolve() == self.run / "RISK_INPUT_SOURCE_REVIEW_R5.json"
             and old["runtime_source_review"] == review["prior_runtime_source_review"],
             "POST_REBOOT_FIXED_RUNTIME_SOURCE_CHAIN_REQUIRED")
        r5 = self.read_ref(r5ref, self.run)
        expected = cloned(r4)
        own = str(Path(__file__).resolve())
        need(r4["source_pins"].get(own) == prior[own] and len(r4["source_pins"]) == 30,
             "POST_REBOOT_EXACT_PRIOR_JOURNAL_RUNTIME_PIN_REQUIRED")
        expected["source_pins"][own] = review["source_pins"][own]
        expected["prior_runtime_source_review"] = cloned(review["prior_runtime_source_review"])
        need(r5 == expected, "POST_REBOOT_ONLY_JOURNAL_RUNTIME_SOURCE_INCREMENT_ALLOWED")
        for path, value in r5["source_pins"].items():
            need(Path(path).resolve().is_relative_to(REPO.resolve()) and Path(path).suffix == ".py",
                 "SOURCE_REVIEW_SOURCE_ONLY")
            self.pin(path, value)
        marker = fixed["old_marker"]
        need(marker.get("review") == review["original_source_guard_review"]
             and marker.get("runtime_source_review") == review["prior_runtime_source_review"]
             and marker.get("status") == "STARTED_TERMINAL_SOURCE_GUARD_ENGINEERING_RECOVERY"
             and type(marker.get("scientific_retry")) is int and marker["scientific_retry"] == 0
             and type(marker.get("test2026_rows_read")) is int and marker["test2026_rows_read"] == 0,
             "POST_REBOOT_ORIGINAL_MARKER_UNCHANGED_REQUIRED")
        self._post_reboot_role_artifacts(review, old, fixed["independent_RX_completion"])
        # No old hash is accepted as a current physical hash. This bridge is
        # installed only after every new formal/current/old backup gate passed.
        self._post_reboot_transport = bridge
        self._post_reboot_review = review

    def _post_reboot_role_artifacts(self, review, old, completion):
        """Pin opaque leaves through the fixed independent completion receipts."""
        complete = review["completed_role_artifacts"]
        prior = old.get("completed_artifacts")
        classical = {"C14_D01", "C14_D02", "C14_D05", "C14_D06", "C14_G1", "C14_G4"}
        need(isinstance(prior, dict) and set(prior) == classical
             and isinstance(complete, dict) and set(complete) == classical | set(ACTIVE_RX),
             "POST_REBOOT_EXACT_EIGHT_COMPLETED_ROLE_ARTIFACTS_REQUIRED")
        for role in classical:
            need(complete[role] == prior[role] and isinstance(prior[role], dict)
                 and set(prior[role]) == {"panels", "predicted_risk", "variance_diagnostics"},
                 "POST_REBOOT_ORIGINAL_SIX_ROLE_ARTIFACTS_UNCHANGED_REQUIRED")
            for leaf in prior[role].values():
                need(isinstance(leaf, dict) and {"path", "sha256"} <= set(leaf)
                     and Path(leaf["path"]).resolve().is_relative_to(self.run),
                     "POST_REBOOT_ORIGINAL_ROLE_ARTIFACT_CUSTODY_REQUIRED")
                self.pin(leaf["path"], leaf["sha256"])
        hgbref = completion.get("hgb_completion_observation")
        need(isinstance(hgbref, dict) and set(hgbref) == {"path", "sha256"}
             and Path(hgbref["path"]).resolve() == POST_REBOOT_MAINTENANCE.resolve()
                 / "TERMINAL_SOURCE_GUARD_HGB_COMPLETE_OBSERVATION_R1.json",
             "POST_REBOOT_FIXED_HGB_COMPLETION_RECEIPT_REQUIRED")
        hgb = self.read_ref(hgbref, POST_REBOOT_MAINTENANCE)
        receipts = {"C14_RX_HGB_LW": hgb.get("hgb_completion"),
                    "C14_RX_XGB_QQQ_RESIDUAL": completion.get("xgb_completion")}
        names = {"assembly": "HYBRID_ASSEMBLY.json", "panel": "scores_pre2026.parquet",
                 "native_pairs": "native_pairs_pre2026.parquet", "matching": "matching_pre2026.parquet"}
        for role, receipt in receipts.items():
            need(isinstance(receipt, dict) and receipt.get("role") == role
                 and receipt.get("status") == "HYBRID_COMPLETE"
                 and receipt.get("strict_PIT_promotion_eligible") is False
                 and all(type(receipt.get(k)) is int and receipt[k] == v for k, v in
                         dict(fit_begin=14, fit_enter=14, fit_finish=14, fit_complete=14, fit_failed=0,
                              solve_enter=POST_REBOOT_COUNTS[role], solve_complete=POST_REBOOT_COUNTS[role],
                              scientific_retry=0, forecast2026_rows=0).items()),
                 "POST_REBOOT_INDEPENDENT_RX_COMPLETE_STATUS_REQUIRED")
            references = receipt.get("artifact_refs")
            need(isinstance(references, list) and len(references) == 4
                 and {Path(r.get("path", "")).name for r in references if isinstance(r, dict)} == set(names.values()),
                 "POST_REBOOT_INDEPENDENT_RX_FOUR_ARTIFACT_REFS_REQUIRED")
            expected = {}
            for key, name in names.items():
                leaf = next(r for r in references if Path(r.get("path", "")).name == name)
                destination = self.run / "risk_execution" / "source_guard_recovery_r1" / role / name
                need({"path", "sha256"} <= set(leaf) and Path(leaf["path"]).resolve() == destination,
                     "POST_REBOOT_EXACT_ORIGINAL_RX_ARTIFACT_DESTINATION_REQUIRED")
                expected[key] = dict(path=str(destination), sha256=leaf["sha256"])
                self.pin(destination, leaf["sha256"])
            need(complete[role] == expected, "POST_REBOOT_RX_ARTIFACTS_EXACT_INDEPENDENT_RECEIPT_REQUIRED")

    def _post_reboot_boundary(self):
        review = self._post_reboot_review
        need(not self._post_reboot_checked and self._source_guard_recovered
             and self.source_guard_recovery_ref == review["original_source_guard_review"]
             and set(self.roles) == SOURCE_GUARD_ROLES, "POST_REBOOT_EXACT_OLD_EVENT_AND_ROLES_REQUIRED")
        nodes = sorted(n for n, s in self.slots.items() if s["candidate_id"] in ACTIVE_RX)
        artifacts = review["completed_fit_artifacts"]
        need(len(nodes) == 28 and isinstance(artifacts, dict) and set(artifacts) == set(nodes),
             "POST_REBOOT_EXACT28_COMPLETE_FIT_ARTIFACTS_REQUIRED")
        for node in nodes:
            slot = self.slots[node]
            need(slot["status"] == "COMPLETE" and type(slot.get("entered")) is int and slot["entered"] == 1
                 and slot.get("artifact") == artifacts[node]
                 and slot.get("source_guard_recovery_ref") == review["original_source_guard_review"],
                 "POST_REBOOT_COMPLETE_FITS_EXACT_REUSE_ONLY")
            self.model_artifact(artifacts[node], node)
        need(all(s["status"] == "UNRESERVED" for n, s in self.slots.items() if n not in nodes),
             "POST_REBOOT_NO_NEW_OR_ADDITIONAL_RESERVATIONS")
        expected = set()
        for role, count in POST_REBOOT_COUNTS.items():
            dates = self.dates[-count:] if role in ACTIVE_RX else self.dates[:count]
            prefix = "HYBRID" if role in ACTIVE_RX else "CLASSICAL"
            expected.update(prefix + "|" + role + "|" + d for d in dates)
        need(set(self.requests) == expected
             and all(s.get("status") == "COMPLETE" and type(s.get("charged")) is int and s["charged"] == 1
                     for s in self.requests.values()), "POST_REBOOT_COMPLETE_PAIRED_CHECKPOINT_ONLY")
        need(self._block_history.keys() == ACTIVE_RX.keys()
             and all(len(v) == 1 for v in self._block_history.values()), "POST_REBOOT_SINGLE_OLD_RECOVERY_ONLY")
        self._post_reboot_checked = True

    def _source_guard_custody(self, review_ref):
        """Fixed reviewed source bridge; no native inputs or old ledgers read."""
        need(isinstance(review_ref, dict) and set(review_ref) == {"path", "sha256"}
             and Path(review_ref["path"]).resolve() == self.run / SOURCE_GUARD_REVIEW_NAME,
             "SOURCE_GUARD_FIXED_REVIEW_REQUIRED")
        review = self.read_ref(review_ref, self.run)
        need(review.get("schema") == "C14_TERMINAL_SOURCE_GUARD_RECOVERY_V1"
             and review.get("status") == "PASS" and review.get("research_id") == ID
             and review.get("classification") == "TERMINAL_BOUND_SOURCE_GUARD_ENGINEERING_ONLY"
             and review.get("independent_review") is True
             and review.get("scientific_contract_changed") is False
             and type(review.get("scientific_retry")) is int and review["scientific_retry"] == 0
             and type(review.get("test2026_rows_read")) is int and review["test2026_rows_read"] == 0,
             "SOURCE_GUARD_REVIEWED_ENGINEERING_ONLY_REQUIRED")
        if self.source_guard_recovery_ref is not None:
            need(review_ref == self.source_guard_recovery_ref, "SOURCE_GUARD_REVIEW_CHANGED")
        fixed = {}
        for key, (relative, expected) in SOURCE_GUARD_REFS.items():
            ref = review.get(key)
            need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and Path(ref["path"]).resolve() == self.run / relative
                 and ref["sha256"] == expected, "SOURCE_GUARD_FIXED_PRIOR_REFERENCE_REQUIRED:" + key)
            fixed[key] = self.read_ref(ref, self.run)
        need(review.get("prior_delta") == dict(path=str(self.path), **SOURCE_GUARD_PREFIX),
             "SOURCE_GUARD_EXACT_PRIOR_PREFIX_REQUIRED")
        source_pins, backups = review.get("source_pins"), review.get("source_backups")
        prior = {str((REPO / p).resolve()): h for p, h in SOURCE_GUARD_SOURCES.items()}
        need(isinstance(source_pins, dict) and isinstance(backups, dict) and set(backups) == set(prior),
             "SOURCE_GUARD_EXACT_FOUR_SOURCE_BACKUPS_REQUIRED")
        original_pins = fixed["original_source_review"].get("source_pins", {})
        need(fixed["original_source_review"].get("status") == "PASS"
             and fixed["original_source_review"].get("research_id") == ID
             and all(original_pins.get(p) == h for p, h in prior.items()),
             "SOURCE_GUARD_PRIOR_REVIEW_CLOSURE_CHANGED")
        for relative, old_sha in SOURCE_GUARD_SOURCES.items():
            path = (REPO / relative).resolve()
            ref = backups[str(path)]
            destination = self.run / SOURCE_GUARD_BACKUP_ROOT / Path(relative).parent.name / path.name
            need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and Path(ref["path"]).resolve() == destination and ref["sha256"] == old_sha,
                 "SOURCE_GUARD_EXACT_ORIGINAL_SOURCE_BACKUP_REQUIRED")
            self.pin(destination, old_sha)
            need(str(path) in source_pins, "SOURCE_GUARD_CURRENT_SOURCE_PIN_REQUIRED")
        for path, expected in source_pins.items():
            need(Path(path).resolve().is_relative_to(REPO.resolve()) and Path(path).suffix == ".py",
                 "SOURCE_GUARD_SOURCE_ONLY_CURRENT_PINS_REQUIRED")
            self._fixed_transport_pin(path, expected)
        terminal, audit, qualification = (fixed[k] for k in ("prior_terminal", "prior_audit", "qualification"))
        need(terminal.get("status") == "RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING"
             and terminal.get("research_id") == ID
             and terminal.get("delta") == dict(path=str(self.path), sha256=SOURCE_GUARD_PREFIX["sha256"])
             and terminal.get("input_qualification") == review["qualification"]
             and terminal.get("review_ref") == review["original_source_review"]
             and all(type(terminal.get(k)) is int and terminal[k] == v for k, v in
                     dict(reserved_fit_slots=28, backend_entered=0, complete_fit_slots=0,
                          failed_fit_slots=0, blocked_fit_slots=28, charged_solves=SOURCE_GUARD_CHARGED,
                          combined_charged_solves=BASELINE_SOLVES + SOURCE_GUARD_CHARGED,
                          scientific_retry=0, test2026_rows_read=0).items()),
             "SOURCE_GUARD_EXACT_ZERO_ENTRY_TERMINAL_REQUIRED")
        need(audit.get("research_id") == ID and audit.get("terminal") == review["prior_terminal"]
             and audit.get("RX_reopened") is False
             and audit.get("preserved_engineering_blocked_fit_slots") == 28,
             "SOURCE_GUARD_PRIOR_AUDIT_REQUIRED")
        need(qualification.get("research_id") == ID and isinstance(qualification.get("roles"), dict),
             "SOURCE_GUARD_PRIOR_NUMERIC_QUALIFICATION_REQUIRED")
        expected_nodes = sorted(n for n, slot in self.slots.items() if slot["candidate_id"] in ACTIVE_RX)
        need(len(expected_nodes) == 28 and review.get("recover_rx_nodes") == expected_nodes,
             "SOURCE_GUARD_EXACT28_ORIGINAL_NODES_REQUIRED")
        for path, expected in original_pins.items():
            need(Path(path).resolve().is_relative_to(REPO.resolve()) and Path(path).suffix == ".py",
                 "SOURCE_REVIEW_SOURCE_ONLY")
            self._fixed_transport_pin(path, source_pins[path] if path in prior else expected)
        with self.path.open("rb") as prefix:
            raw = prefix.read(SOURCE_GUARD_PREFIX["bytes"])
        need(len(raw) == SOURCE_GUARD_PREFIX["bytes"] and raw.endswith(b"\n")
             and raw.count(b"\n") == SOURCE_GUARD_PREFIX["lines"]
             and hashlib.sha256(raw).hexdigest() == SOURCE_GUARD_PREFIX["sha256"],
             "SOURCE_GUARD_PRIOR_PREFIX_CHANGED")
        self.source_guard_recovery_ref = cloned(review_ref)
        self._source_guard_review = review
        return qualification

    def _source_guard_zero_entry_state(self, data):
        need(set(data) == {"review_ref", "nodes"} and not self._source_guard_recovered,
             "SOURCE_GUARD_ONCE_ONLY_TRANSITION_REQUIRED")
        qualification = self._source_guard_custody(data["review_ref"])
        expected = self._source_guard_review["recover_rx_nodes"]
        need(data["nodes"] == expected and self.sequence == SOURCE_GUARD_PREFIX["lines"]
             and not self._fit_seen and set(self.roles) == SOURCE_GUARD_ROLES,
             "SOURCE_GUARD_EXACT_TERMINAL_ZERO_ENTRY_STATE_REQUIRED")
        need(len(self.requests) == SOURCE_GUARD_CHARGED
             and all(token.startswith("CLASSICAL|") and state.get("status") == "COMPLETE"
                     and state.get("charged") == 1 for token, state in self.requests.items()),
             "SOURCE_GUARD_COMPLETE_CLASSICAL_ONLY_CACHE_REQUIRED")
        need(set(self._block_history) == set(ACTIVE_RX), "SOURCE_GUARD_TWO_ENGINEERING_BLOCKS_REQUIRED")
        for role in ACTIVE_RX:
            nodes = sorted(n for n in expected if self.slots[n]["candidate_id"] == role)
            history = self._block_history[role]
            need(len(history) == 1 and history[0] == dict(role=role, nodes=nodes,
                 reason=SOURCE_GUARD_BLOCK_REASON), "SOURCE_GUARD_EXACT_ENGINEERING_BLOCK_HISTORY_REQUIRED")
        need(all(self.slots[n]["status"] == "BLOCKED_DEPENDENCY"
                 and type(self.slots[n].get("entered")) is int and self.slots[n]["entered"] == 0
                 and self.slots[n].get("dependency_only") is True
                 and self.slots[n].get("error") == SOURCE_GUARD_BLOCK_REASON
                 and not (set(self.slots[n]) & {"identity", "artifact", "event", "source_guard_recovery_ref"})
                 for n in expected), "SOURCE_GUARD_UNTOUCHED_ENGINEERING_BLOCKS_ONLY")
        need(all(slot["status"] == "UNRESERVED" for n, slot in self.slots.items() if n not in expected),
             "SOURCE_GUARD_NO_ADDITIONAL_RESERVATIONS")
        for role, stored in self.roles.items():
            need(qualification["roles"].get(role) == self.read_ref(stored["qualification_ref"], self.run)
                 and self.qualify_role(role, stored["qualification_ref"]) == stored,
                 "SOURCE_GUARD_ORIGINAL_ACTIVATION_QUALIFICATION_CHANGED")

    def _source_guard_artifact_absent(self, nodes):
        """Existence only before append; replay preserves later legitimate fits."""
        for node in nodes:
            model = self.run / "risk_execution" / "models" / (owner.content_hash(node) + ".joblib")
            need(not model.exists() and not any(model.parent.glob(model.name + ".*")),
                 "SOURCE_GUARD_EXISTING_MODEL_ARTIFACT_FORBIDDEN")
        for role in ACTIVE_RX:
            directories = (self.run / "risk_execution" / "source_metadata_recovery_r1" / role,
                           self.run / "risk_execution" / "source_guard_recovery_r1" / role,
                           self.run / "models" / role, self.run / "models" / "risk_hybrids" / role)
            need(not any(p.is_file() and p.name != "ENGINEERING_FAILURE_R1.json"
                         for directory in directories if directory.exists() for p in directory.rglob("*"))
                 and not any((self.run / "predictions").glob("*" + role + "*")),
                 "SOURCE_GUARD_EXISTING_ROLE_PREDICTION_ARTIFACT_FORBIDDEN")

    def recover_source_guard_zero_entry(self, review_ref):
        """Append one reviewed engineering reopening of the exact original28."""
        self.verify()
        data = dict(review_ref=cloned(review_ref), nodes=sorted(
                    n for n, slot in self.slots.items() if slot["candidate_id"] in ACTIVE_RX))
        self._source_guard_zero_entry_state(data)
        need(stamp(self.path)[0] == SOURCE_GUARD_PREFIX["bytes"],
             "SOURCE_GUARD_NO_POST_TERMINAL_APPEND")
        self._source_guard_artifact_absent(data["nodes"])
        self.emit("SOURCE_GUARD_ZERO_ENTRY", data)
        return data["nodes"]

    def role_token(self, token):
        need(token in self.allowed_solves, "UNNAMED_CONDITIONAL_SOLVE")
        prefix, role, date = token.split("|")
        need(role in self.roles, "FULL752_NUMERIC_ROLE_ACTIVATION_REQUIRED")
        need((prefix == "HYBRID" and role in ACTIVE_RX)
             or (prefix == "CLASSICAL" and role in self.families and role not in RX_COUNTS),
             "EXACT_CONDITIONAL_ROUTE_REQUIRED")
        date_token(date)
        need(date in self.dates, "EXACT_FROZEN_DATE_MASK_REQUIRED")
        return prefix, role, date

    def solve_state(self, run):
        need(Path(run).resolve() == self.run, "EXACT_ORIGINAL_C14_RUN_REQUIRED")
        self.verify()
        return dict(research_id=ID, hard_cap=SOLVE_CAP, requests=_RequestView(self.requests))

    def solve_callback(self, run, token):
        need(Path(run).resolve() == self.run, "EXACT_ORIGINAL_C14_RUN_REQUIRED")
        self.role_token(token)
        self.emit("SOLVE_ENTER", dict(token=token))

    def complete_solve(self, run, token, **receipt):
        need(Path(run).resolve() == self.run, "EXACT_ORIGINAL_C14_RUN_REQUIRED")
        need("identity" in receipt, "EXACT_SOLVE_CACHE_IDENTITY_REQUIRED")
        self.emit("SOLVE_COMPLETE", dict(token=token, receipt=receipt))

    def fail_solve(self, token, error):
        if token in self.requests and self.requests[token]["status"] == "ENTERED":
            self.emit("SOLVE_FAILED", dict(token=token, error=str(error),
                                          error_type=type(error).__name__))

    def checkpoint_decode(self, token, raw, geometry, score, candidate_id, eligible):
        self.verify()
        prefix, role, _ = self.role_token(token)
        need(prefix == "HYBRID" and role == candidate_id, "EXACT_HYBRID_TOKEN_ROLE_REQUIRED")
        kernel = event.bind_pinned_kernel(owner.checkpoint_decode, physical_path=owner.__file__,
                    expected_sha256=OWNER_SHA, dependencies=dict(solve_state=self.solve_state,
                    solve_callback=self.solve_callback, complete_solve=self.complete_solve))
        try:
            return kernel(self.run, token, raw, geometry, score, candidate_id, eligible)
        except Exception as error:
            self.fail_solve(token, error)
            raise

    def classical_request(self, token, identity, operation):
        """Persist charge before invoking the caller's original membership owner."""
        self.verify()
        prefix, _, _ = self.role_token(token)
        need(prefix == "CLASSICAL", "EXACT_CLASSICAL_ROUTE_REQUIRED")
        identity = cloned(identity)
        need(isinstance(identity, dict) and identity, "EXACT_CLASSICAL_INPUT_IDENTITY_REQUIRED")
        old = self.requests.get(token)
        if old is not None:
            need(old["status"] == "COMPLETE" and "result" in old, "BLOCKED_CHARGED_CLASSICAL_NO_COMPLETE_CACHE")
            need(old["identity"] == identity and digest(old["result"]) == old["result_sha256"],
                 "EXACT_CLASSICAL_CHECKPOINT_CHANGED")
            return cloned(old["result"])
        self.solve_callback(self.run, token)
        try:
            result = cloned(operation())
            self.complete_solve(self.run, token, identity=identity, result=result,
                                result_sha256=digest(result))
            return cloned(result)
        except Exception as error:
            self.fail_solve(token, error)
            raise

    def flush(self):
        """All events are already flushed and fsynced; original ledgers untouched."""
        self.verify()

    def counts(self):
        self.verify()
        reserved = sum(s["status"] != "UNRESERVED" for s in self.slots.values())
        entered = sum(s["entered"] for s in self.slots.values())
        return dict(original_fit_slots=BASELINE_FITS, conditional_reserved=reserved,
                    combined_fit_slots=BASELINE_FITS + reserved,
                    conservative_combined_backend_entered=BASELINE_FITS + entered,
                    original_charged_solves=BASELINE_SOLVES, conditional_charged=len(self.requests),
                    combined_charged_solves=BASELINE_SOLVES + len(self.requests),
                    original_conditional_nodes=144, conditional_unreserved=144 - reserved,
                    failed_reservation_refund=False, scientific_retry=0)

    def emit(self, action, data):
        self.verify()
        self._post_reboot_tail(action, data)
        if action == "SOURCE_GUARD_ZERO_ENTRY":
            self._source_guard_artifact_absent(data.get("nodes", []))
        # Validate on a detached copy before durable append or in-memory mutation.
        previous_state = (self.slots, self.requests, self.roles, self._source_guard_recovered,
                          self._fit_seen, self._block_history)
        self._block_history = copy.deepcopy(self._block_history)
        self.slots, self.requests, self.roles = self.slots.copy(), self.requests.copy(), self.roles.copy()
        if data.get("node") in self.slots:
            self.slots[data["node"]] = copy.deepcopy(self.slots[data["node"]])
        if data.get("token") in self.requests:
            self.requests[data["token"]] = copy.deepcopy(self.requests[data["token"]])
        if action in {"ACTIVATE_ROLE", "BLOCK_REMAINING"}:
            for node, slot in list(self.slots.items()):
                if slot["candidate_id"] == data["role"]:
                    self.slots[node] = copy.deepcopy(slot)
        if action == "SOURCE_GUARD_ZERO_ENTRY":
            for node in data.get("nodes", []):
                if node in self.slots:
                    self.slots[node] = copy.deepcopy(self.slots[node])
        try:
            self.apply(action, cloned(data))
        finally:
            (self.slots, self.requests, self.roles, self._source_guard_recovered,
             self._fit_seen, self._block_history) = previous_state
        payload = dict(sequence=self.sequence, previous=self.previous, action=action, data=cloned(data))
        row = dict(payload, sha256=digest(payload))
        mode = "r+b" if self.path.exists() else "x+b"
        with self.path.open(mode) as stream:
            with exclusive(stream):
                for pinned, (_, expected_stamp) in self.pins.items():
                    need(stamp(pinned) == expected_stamp, "PHYSICAL_AUTHORITY_CHANGED:" + Path(pinned).name)
                need(stamp(self.path) == self.last_stamp if self.last_stamp is not None
                     else stream.seek(0, os.SEEK_END) == 0, "DELTA_CHANGED_OR_CONCURRENT_WRITER")
                if action == "SOURCE_GUARD_ZERO_ENTRY":
                    self._source_guard_artifact_absent(data["nodes"])
                stream.seek(0, os.SEEK_END)
                stream.write((canonical(row) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        self.last_stamp = stamp(self.path)
        self.accept(row)

    def accept(self, row):
        payload = {k: row[k] for k in ("sequence", "previous", "action", "data")}
        need(set(row) == {*payload, "sha256"} and row["sequence"] == self.sequence
             and row["previous"] == self.previous and digest(payload) == row["sha256"],
             "DELTA_HASH_CHAIN_OR_REVISION_CHANGED")
        self.apply(row["action"], row["data"])
        self.sequence += 1
        self.previous = row["sha256"]

    def _post_reboot_tail(self, action, data):
        """One original remaining classical charge; no new fit or recovery."""
        if self._post_reboot_checked:
            need(action in {"SOLVE_ENTER", "SOLVE_COMPLETE", "SOLVE_FAILED"},
                 "POST_REBOOT_CLASSICAL_EVENTS_ONLY")
            token = data.get("token")
            remaining = {"CLASSICAL|C14_D09|" + d for d in self.dates[POST_REBOOT_COUNTS["C14_D09"]:]}
            remaining.update("CLASSICAL|" + role + "|" + d
                             for role in ("C14_D10", "C14_D11") for d in self.dates)
            need(token in remaining, "POST_REBOOT_ORIGINAL_REMAINING_CLASSICAL_TOKEN_ONLY")

    def apply(self, action, data):
        self._post_reboot_tail(action, data)
        if action == "HEADER":
            need(self.sequence == 0 and data == self.header, "ORIGINAL_DELTA_AUTHORITY_CHANGED")
        elif action == "ACTIVATE_ROLE":
            role = data["role"]
            need(role not in self.roles and role in self.families, "DUPLICATE_OR_UNNAMED_ROLE")
            need(role not in RX_COUNTS or role in ACTIVE_RX, "RX_FAMILY_NOT_CURRENTLY_QUALIFIED")
            self.roles[role] = data["qualification"]
            for slot in self.slots.values():
                if slot["candidate_id"] == role:
                    need(slot["status"] == "UNRESERVED", "CONDITIONAL_RESERVATION_ALREADY_USED")
                    slot["status"] = "RESERVED"
            need(sum(s["status"] != "UNRESERVED" for s in self.slots.values()) <= 28
                 and BASELINE_FITS + len(self.slots) == 800 <= FIT_CAP,
                 "COMBINED_PHYSICAL_FIT_CAP_EXHAUSTED")
        elif action == "BLOCK_REMAINING":
            role = data["role"]
            need(role in ACTIVE_RX and role in self.roles, "ACTIVATED_CURRENT_RX_ROLE_REQUIRED")
            need(isinstance(data.get("reason"), str) and bool(data["reason"].strip()),
                 "DEPENDENCY_BLOCK_REASON_REQUIRED")
            role_slots = {node: slot for node, slot in self.slots.items() if slot["candidate_id"] == role}
            need(not any(slot["status"] == "STARTED" for slot in role_slots.values()),
                 "UNRESOLVED_STARTED_FIT_REQUIRES_FAILURE_RECEIPT")
            expected = sorted(node for node, slot in role_slots.items() if slot["status"] == "RESERVED")
            need(data.get("nodes") == expected and bool(expected)
                 and all(role_slots[node]["entered"] == 0 for node in expected),
                 "ALL_AND_ONLY_UNTOUCHED_RESERVATIONS_REQUIRED")
            for node in expected:
                role_slots[node].update(status="BLOCKED_DEPENDENCY", error=data["reason"],
                                        dependency_only=True)
            self._block_history.setdefault(role, []).append(cloned(data))
        elif action == "SOURCE_GUARD_ZERO_ENTRY":
            self._source_guard_zero_entry_state(data)
            for node in data["nodes"]:
                self.slots[node].update(status="RESERVED", source_guard_recovery_ref=cloned(data["review_ref"]))
            self._source_guard_recovered = True
        elif action in {"FIT_BEGIN", "FIT_ENTER", "FIT_FINISH"}:
            node = data["node"]
            need(node in self.slots, "UNNAMED_CONDITIONAL_FIT")
            slot = self.slots[node]
            self._fit_seen = True
            if action == "FIT_BEGIN":
                need(slot["status"] == "RESERVED", "ZERO_RETRY_RESERVED_ONLY:" + node)
                need(str(data["identity"].get("cutoff")) == str(slot["cutoff"]), "EXACT_FROZEN_FIT_CUTOFF_REQUIRED")
                slot.update(status="STARTED", identity=data["identity"])
            elif action == "FIT_ENTER":
                need(slot["status"] == "STARTED" and slot["entered"] == 0, "DUPLICATE_BACKEND_ENTER")
                need(BASELINE_FITS + sum(s["entered"] for s in self.slots.values()) < FIT_CAP,
                     "COMBINED_BACKEND_CAP_EXHAUSTED")
                slot.update(entered=1, event=data["event"])
            else:
                need(slot["status"] == "STARTED" and data["status"] in TERMINAL_FITS,
                     "FIT_STARTED_TRANSITION_REQUIRED")
                need(not (set(data["details"]) & {"status", "entered", "identity", "node_id"}),
                     "FIT_CONTROL_FIELDS_IMMUTABLE")
                if data["status"] == "COMPLETE":
                    need(slot["entered"] == 1 and "artifact" in data["details"],
                         "COMPLETE_REQUIRES_BACKEND_AND_EXACT_ARTIFACT")
                slot.update(status=data["status"], **data["details"])
        elif action in {"SOLVE_ENTER", "SOLVE_COMPLETE", "SOLVE_FAILED"}:
            token = data["token"]
            self.role_token(token)
            if action == "SOLVE_ENTER":
                need(token not in self.requests, "DUPLICATE_SOLVE_REQUEST_NO_RETRY")
                need(BASELINE_SOLVES + len(self.requests) < min(SOLVE_CAP, NAMED_CEILING),
                     "COMBINED_SOLVE_CAP_EXHAUSTED")
                self.requests[token] = dict(status="ENTERED", charged=1)
            else:
                need(token in self.requests and self.requests[token]["status"] == "ENTERED",
                     "CHARGED_ENTERED_TRANSITION_REQUIRED")
                if action == "SOLVE_FAILED":
                    self.requests[token].update(status="FAILED", error=data["error"], error_type=data["error_type"])
                else:
                    receipt = data["receipt"]
                    need("identity" in receipt and not (set(receipt) & {"status", "charged"}),
                         "EXACT_SOLVE_CACHE_RECEIPT_REQUIRED")
                    matching = "matching_records" in receipt
                    need(matching != ("result" in receipt), "ONE_EXACT_CACHE_KIND_REQUIRED")
                    need(matching == token.startswith("HYBRID|"), "EXACT_SOLVE_ROUTE_CACHE_KIND_REQUIRED")
                    if matching:
                        need(owner.content_hash(receipt["matching_records"]) == receipt.get("matching_sha256"),
                             "EXACT_MATCHING_CACHE_DIGEST_REQUIRED")
                    else:
                        need(digest(receipt["result"]) == receipt.get("result_sha256"),
                             "EXACT_CLASSICAL_CACHE_DIGEST_REQUIRED")
                    self.requests[token].update(status="COMPLETE", **receipt)
        else:
            raise RiskJournalBlocked("UNKNOWN_DELTA_TRANSITION")

