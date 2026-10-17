"""Cache-only fixed CORE_ACCOUNT_SOURCE_RECOVERY_R1 proposal; no CLI.
Import performs no account, cold probe, marker write or real-owner import.
Future root installation/review/cold must precede recover_once. Existing source
context, ledger, metadata reader, quote owner and run_accounts own all behavior.
"""
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import traceback
from contextlib import contextmanager
ID="V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"
RUN=Path("D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248")
REPO=Path("D:/us-tech-quant")
CACHE=Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals")
NAME="CORE_ACCOUNT_SOURCE_RECOVERY_R1"
PHASE="core-account-source-recovery"
RUNTIME_PATH=REPO/"scripts/research/a2/training/full_selector_core_account_source_recovery.py"
CORE_IDS=("RAW","RIDGE","HGB","LAMBDAMART","FUSION_equal")
ORIGINAL_PINS={
"DESIGN_FREEZE.json":"20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359",
"FREEZE_ACCEPTANCE.json":"7f9a4bf1fd0128a8ab7b0f1628432e23e6722a20ea7279cd7f595b3ce6162636",
"input_manifest.json":"788eb12fd3448dd83779536dbda2cee4cbb70e201edaf12f7890266041a91d5d",
"run_config.json":"721a3b14d337caa8e5046fee3c76a7774b33017403369555d3f809f59d490c4a",
"risk_inputs.json":"0873f9248858fd0e0ab08cdc590968b939e1bc6535af488579eca2a7c0be041f"}
HISTORY={
"original_start_ref":("PRIMARY_CORE_EXECUTION_STARTED.json","319cc51defc2a6273b9cf60744b1036ac3ed21f3b46d9032bab71c63908a57bd"),
"original_failure_ref":("EXECUTION_FAILURE.json","02af4f117bf872e21123b07bfb6b4a235377502f5e1753b8e0cec1d044b58fe1"),
"old_core_start_ref":("continuation/CORE_ACCOUNT_CONTINUATION_R1_STARTED.json","44757250835788a1b3b62a46d0265e7ead723f950a618fe62670d2d79210280c"),
"old_core_failure_ref":("continuation/CORE_ACCOUNT_CONTINUATION_R1_FAILURE.json","4b82752e4736b7d43387ecde610aae67e87178ff10eeb189a2fd311d5a9f6d69"),
"core_policy_terminal_ref":("CORE_BASE_POLICY_TERMINAL.json","fdd4350e8440850fe904785f4d73d74bf450c0e03b985f53cbca95f05947771d"),
"equal_policy_ref":("predictions/policy_FUSION_equal.parquet","a0504bc593f5b43b1ba8e954d69bccc95a1cf901a66272489a8c25c1e575f282"),
"equal_receipt_ref":("predictions/policy_FUSION_equal.parquet.json","d61f043c115f22f75553e89f2477e7deeeb7fd5de0dfb9f1933b4482c0468b88")}
BASE_MANIFEST_SHA="66217f50d66236d35b8009c0dc7837ce6d99d2ff5c7beda120ce7cfc3466ba40"
OLD_SOURCE_SHA="29b37530c058f178855ec55494e92ed752aeb57b3b327fabd145fb8abaccb6b5"
MODULE_REFS={
"continuation":dict(path=str(REPO/"scripts/research/a2/training/full_selector_engineering_continuation.py"),sha256="c6a8f9ac13ba1570661c7496b661007d211d17b01a70dcebca37126df6a6dcc0"),
"controller":dict(path=str(REPO/"scripts/research/a2/training/selector_full_fixed_policy.py"),sha256="ec6d7caf68a511f6084e85aad6ec2ceb6c9e3496ef7620ff5e64d9154cd06a4d"),
"workflow":dict(path=str(REPO/"scripts/research/a2/training/full_selector_workflow.py"),sha256="4e989ebb783ce4b7c0f231417afee1e1357a6b38c94f78ddd60801c7ad72160d"),
"account":dict(path=str(REPO/"scripts/research/a2/data/full_selector_account_inputs.py"),sha256="f6b084e5ffead9fca2897dd1ba1605de2d54eb5290112fddb1ad860a6d1b9d6d"),
"r7":dict(path=str(CACHE/"account_final_owner_projection_R1.py"),sha256="f9a020cfff567b2e9ff17d6a0a80c933e36f291ce3491abeba6ee50e2bb838fb"),
"seam":dict(path=str(CACHE/"core_account_quote_seam_context_proposal_R1.py"),sha256="4fe345e4f5be0b36bea2c76919e9acdbea23d62f53d5357e0dd759ba3a8cc500"),
"transport":dict(path=str(CACHE/"quote_domain_transport_proposal_R1.py"),sha256="73874f5ed6be53c7a3765493b21b194ac01721ad99fde7a7a3f29de37449fda5"),
"quote":dict(path=str(REPO/"scripts/research/a2/evaluation/frozen_history_research_quote_domain.py"),sha256="eda136406c8de2c9053441943e751c6b16d5a56307ae118b904ac8fb773b55f4")}
FINITE_REFS={
"r7_candidate":dict(path=str(CACHE/"account_inputs_final_owner_transport_R1.py"),sha256="e060865495e1e4b746e728b80fd430cfe662c7636b68da01e62595c09ee2452e"),
"v17_source_equivalence":dict(path=str(CACHE/"CASH_DRIFT_V17_REACHABLE_SOURCE_EQUIVALENCE_R2.json"),sha256="ed0f09b1f9da89693df0ffe7864cbd758be7db46fc93ca253e0b89ea821bbef5")}
CLASSIFICATION_REF=dict(path="D:/us-tech-quant-results/_maintenance/V24_SHARED_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_R1/source_metadata_final/QUOTE_DOMAIN_CLASSIFICATION.json",
sha256="0509ad75a4bc549833b7109e2763addf369994631d9600e782043483dc97ceba")
MARKET_REFS={
"raw_prices":dict(path="D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/full848raw_pre2026.parquet",sha256="20057f59e6188ac4a2d35923ec8c1689e43380aefbbc87a1a7c78312616693f8"),
"market_adapter":dict(path="D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/selector_replay.py",sha256="b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb"),
"quote_composer":dict(path="D:/us-tech-quant-cache/V24/V24_SHARED_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_R1/source_audit/run_shared_quote_B_descendant.py",sha256="ad6d9b90652fff35804c0d18723fed5bff3a8bad64bb05bc8c82e078d942d07c")}
SOURCE_FORMAL_R2=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R2.json"),
sha256="8009d9bdc0f9e23760ea877bdee0f1e72f1af8affdb454e8c10e0f4824bb303f")
CONFIG_FIELDS={"schema","research_id","phase","run","runtime_entry_ref","module_refs","finite_source_refs",
"base_manifest_ref","engineering_source_configuration_ref","prior_source_configuration_ref","original_refs","preserved_refs"}
COMPLETE_FIELDS={"schema","research_id","phase","status","phase_configuration_ref","review_ref","marker_ref",
"runtime_entry_ref","engineering_source_configuration_ref","base_manifest_ref","preserved_refs","ledger_prestate",
"ledger_poststate","account_terminal_ref","applicable_core_account_ids","core_account_states","preserved_failed_core_ref",
"existing_equal_exact_reuse","only_saved_core_account_dispatch","all66_accounts_complete","scientific_retries",
"all_task_complete","risk_dispatch_entered","outer_feedback"}
REVIEW_FIELDS={"phase_configuration_ref","schema","research_id","run","phase","status","runtime_entry_ref","module_refs","finite_source_refs",
"base_manifest_ref","prior_source_configuration_ref","engineering_source_configuration_ref","original_refs","preserved_refs",
"remaining_terminal_ref","remaining_terminal_audit_ref","actual_source_metadata_cold_ref","actual_quote_input_qualification_ref",
"ledger_prestate","all_prior_workers_terminal","independent_from_entry_writer","scientific_retry_authorized",
"first_account_dispatch_only","fixed_core_account_ids","account_backend_entered_before_review"}

# One additional finite provenance branch. Original R2 tables remain immutable.
POST_PRIMARY_MODE="POST_PRIMARY_FUSION_R4"
POST_PRIMARY_SCHEMAS={
    "configuration":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_SOURCE_RECOVERY_CONFIGURATION_R1",
    "acceptance":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_SOURCE_RECOVERY_ACCEPTANCE_R1",
    "cold":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_SOURCE_RECOVERY_METADATA_COLD_R1",
    "quote":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_QUOTE_INPUT_QUALIFICATION_R1"}
SOURCE_FORMAL_R4=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R4.json"),
    sha256="c3025e79f43c6503b97aecfb686399592385e788c0a12bdba3bf38a0a95658b9")
CURRENT_CONTROLLER_REF=dict(path=MODULE_REFS["controller"]["path"],
    sha256="8ec650d05d97129a9e8dba6d29e41883273f4a5a48d9729f21acc577c9afc414")
REBOOT_OWNER_REF=dict(path=str(REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py"),
    sha256="0e81a6dab455ad23b80d1014f6cc14b87ef830d34b04b3086855c153eafdd64c")
POST_PRIMARY_REFS={
    "entry_ref":dict(path=str(REPO/"scripts/research/a2/training/full_selector_post_primary_fusion_continuation_R1.py"),sha256="0d3d76a0210017d7d5d3e2fee3e6ea12e177811dbc1e935ee54966947aedc02a"),
    "configuration_ref":dict(path=str(RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_CONFIGURATION.json"),sha256="ec86cb92777bad2c3b560c620d37f15eba3092d7ca872ee3f716aa7c396cb18e"),
    "acceptance_ref":dict(path=str(RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_ACCEPTANCE.json"),sha256="7c18ad738126cfc2059913aeacb07ceb6ddaae0809fbfa6144e0a051eaa349ca"),
    "launch_ref":dict(path=str(RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_LAUNCH_RECEIPT_R1.json"),sha256="5e6c7bea9a678a16f5cebab93e7469805bc934830e55c03078f781716ca4a75f"),
    "complete_ref":dict(path=str(RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_COMPLETE.json"),sha256="c21ab4b07b7cb8216e12616973659789ebb68052fc7679875120a25ebc0bc6bc"),
    "os_exit_ref":dict(path=str(RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_OS_EXIT_RECEIPT_R1.json"),sha256="b0a682ef7a90fa44aa38eeffbd85f8b11c7fd440bcde0350cb6313f3940d6372"),
    "audit_ref":dict(path=str(CACHE/"POST_PRIMARY_FUSION_ALPHA_TERMINAL_METADATA_ACCEPTANCE_R1.json"),sha256="19ff902cad76db560d7f35545777671d5a71c8b9538378731f6ae0d33af8f51e"),
    "audit_caller_ref":dict(path=str(CACHE/"audit_post_primary_fusion_alpha_natural_terminal_R1.py"),sha256="a9e375f34621a4efa2b9443fc425fc14b165e4446acf9bf470b8f2f23b550408"),
    "transport_ref":dict(path=str(RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_SOURCE_TRANSPORT_R4.json"),sha256="ced8eb8fff68686b0bc2c654e3a80ac70e90959a124f0612faddc2781557da95"),
    "original_ec6_custody_ref":dict(path=str(RUN/"source_corrections/ALPHA_REBOOT_RECOVERY_R1/controller.ec6d7caf68a511f6084e85aad6ec2ceb6c9e3496ef7620ff5e64d9154cd06a4d.before.py"),sha256=MODULE_REFS["controller"]["sha256"]),
    "upgrade_f28_custody_ref":dict(path=str(RUN/"source_corrections/ALPHA_POST_PRIMARY_SOURCE_R1/controller.f28adfcbe664aa1720879dffee998398fea47a9435a63596b94c7eaab3a77e26.before.py"),sha256="f28adfcbe664aa1720879dffee998398fea47a9435a63596b94c7eaab3a77e26"),
    "upgrade_formal_custody_ref":dict(path=str(RUN/"source_corrections/ALPHA_POST_PRIMARY_SOURCE_R1/formal.da33915da67a6f58e06872eaac98bdcb408458cdf2fea930bd6e2bc5d6e1a4ad.before.json"),sha256="da33915da67a6f58e06872eaac98bdcb408458cdf2fea930bd6e2bc5d6e1a4ad"),
    "upgrade_transport_custody_ref":dict(path=str(RUN/"source_corrections/ALPHA_POST_PRIMARY_SOURCE_R1/transport.d0e91fdf21dbdeb80e188ce8b6ba289715ef2e852033ad5fd703fe574722efd2.before.json"),sha256="d0e91fdf21dbdeb80e188ce8b6ba289715ef2e852033ad5fd703fe574722efd2")}
POST_PRIMARY_HISTORY={
    "boundary_ref":dict(path=str(RUN/"continuation/ALPHA_REBOOT_FAILURE_FUSION_SOURCE_DRIFT_R1_BOUNDARY.json"),sha256="3dc4f969640b65a82acf6fe69b9bdfe61b9e7c1fd92a1b75b892271775262595"),
    "prior_failure_ref":dict(path=str(RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_FAILURE.json"),sha256="a75a237323b19fa06ada0f5bcdd0f48cfcc8efb998528760d3f2559b69cef03e"),
    "prior_started_ref":dict(path=str(RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_STARTED.json"),sha256="802ae235823af588a004638595c6592551a1137c1bafae4ce10a381f0da6ed5d"),
    "prior_configuration_ref":dict(path=str(RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_CONFIGURATION.json"),sha256="6676582c67bf0966349bd1476f07d9af56399b3d72df4700df6640a033ac54e6"),
    "prior_acceptance_ref":dict(path=str(RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_ACCEPTANCE.json"),sha256="b530db332b2c112766047a7e709e11069c839391e987089b189b4304b09c91ec"),
    "design_ref":dict(path=str(RUN/"DESIGN_FREEZE.json"),sha256=ORIGINAL_PINS["DESIGN_FREEZE.json"]),
    "authority_ref":dict(path=str(RUN/"continuation/CURRENT_ROUND_BACKGROUND_PYTHON_PERMISSION_R1.json"),sha256="7c5648dc99dea580d7ec32491d838eae182c40ffa4bd28e40eacfbcc0cd83235")}
POST_PRIMARY_TERMINAL_FIELDS={"schema","status","research_id","utc","marker_ref","acceptance_ref",
    "before","after","first_fusion_entry_only","new_backend_replay_events","original_replay_events_preserved",
    "scientific_failed_retries","application_fusion_owner_calls","os_exit_code_not_inferred",
    "actual_source_transport","nonexecuting_source_observation","config_ref","entry_ref","test_ref",
    "boundary_ref","source_review_ref","source_configuration_ref","controller_ref","history_refs"}

# Finite current R5 sources are separate from the historical R4 alpha terminal.
POST_PRIMARY_R5_MODE="POST_PRIMARY_FUSION_R5"
POST_PRIMARY_R5_SCHEMAS={
    "configuration":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_CONFIGURATION_R1",
    "acceptance":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_ACCEPTANCE_R1",
    "cold":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_METADATA_COLD_R4",
    "quote":"FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_QUOTE_INPUT_QUALIFICATION_R4"}
SOURCE_FORMAL_R5=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json"),sha256="c3bff6e808e73155f34f74928f28e041e1ee6107fb9b561984d02642e7766a8d")
R5_R7_PROJECTION_REF={'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\account_final_owner_projection_post_primary_R5_proposal_R2.py', 'sha256': '85e9cba0f7e7672784c3518e7f6c43a835f9631562c372689d8cdf7eb923cc88'}
R5_FINITE_REFS={**FINITE_REFS,"r7_candidate":{'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\account_inputs_final_owner_transport_post_primary_R5_proposal_R2.py', 'sha256': 'eac3a8ac0551bf3b12ebcfc5e5788a75bbd27228a35c8cd233f950cf6f34cd28'}}
CURRENT_R5_CONTROLLER_REF=dict(path=MODULE_REFS["controller"]["path"],
    sha256="c06c16288e939b58e1a78cfbe196996c196c6c7d1f2c65716833f95e0d48442e")
R5_RECOVERY_OWNER_REF=dict(path=REBOOT_OWNER_REF["path"],
    sha256="343a867113d361ebf3956ebcc5b66f6b4c4fb4e5a88e083e99b44e059de2aca9")
R5_TRANSPORT_REF=dict(path=str(RUN/"continuation/SAVED5_POST_PRIMARY_SOURCE_TRANSPORT_R5.json"),
    sha256="fc647b1b8d24a3753f61a176fa8feba70eb2a2ed9b569ad05854b40a44330dc0")
R5_CAPTURE_REF=dict(path=str(RUN/"maintenance/SAVED5_POST_PRIMARY_R5_NONEXECUTED_LIVE_CUSTODY_OBSERVATION_R1.json"),
    sha256="8ac4183796b0c87636276914bf1dcd907df00c1bb9da73f99a67bf30b72b6de0")
R5_RUNTIME_CUSTODY_REFS={
    "controller":dict(path=str(RUN/"source_corrections/SAVED5_POST_PRIMARY_SOURCE_R5"/("controller."+CURRENT_CONTROLLER_REF["sha256"]+".before.py")),
        sha256=CURRENT_CONTROLLER_REF["sha256"]),
    "transport_owner":dict(path=str(RUN/"source_corrections/SAVED5_POST_PRIMARY_SOURCE_R5"/("transport_owner."+REBOOT_OWNER_REF["sha256"]+".before.py")),
        sha256=REBOOT_OWNER_REF["sha256"])}
R5_COLD_PATH=CACHE/"CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_METADATA_COLD_R4.json"
R5_QUOTE_PATH=CACHE/"CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_QUOTE_INPUT_QUALIFICATION_R4.json"

R5_QUOTE_TRANSPORT_REF={'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\quote_domain_transport_fixed_absence_cohort_proposal_R1.py', 'sha256': '3c1d9ecc6032fd0ca1d140846195c14b2154675cbef3fc59d102cd9f4aacb4de'}
R5_QUOTE_SEAM_REF={'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\core_account_quote_seam_fixed_absence_cohort_proposal_R1.py', 'sha256': '598fb68bd9d927308d5fae9a4d7bc009b8e161b3eef74f93e590f1a1bb6e188b'}
R5_QUOTE_COHORT_REFS={'actual_census': {'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\SAVED5_CURRENT_QUOTE_COVERAGE_METADATA_CENSUS_R2.json', 'sha256': '33f946a18aec83f34b2589760baa3d384c3c38121de96600fbd3b3ed43fcf715'}, 'actual_terminal': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\maintenance\\SAVED5_QUOTE_CENSUS_ACTUAL_COMPLETE_ZERO_ENTRY_R2.json', 'sha256': 'fbede22773e4d2d10da77a8946b57be670d78b84dc7479846107a29d161115c3'}, 'natural_os_exit': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\maintenance\\SAVED5_QUOTE_COVERAGE_METADATA_CENSUS_OS_EXIT_R2.json', 'sha256': 'e3ca5103c72536f0508a2e9b6cb0a956c454ca68cb0f91a32e66c6348f8fc6f1'}, 'independent_metadata': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\maintenance\\SAVED5_QUOTE_CENSUS_ACTUAL_METADATA_INDEPENDENT_ACCEPTANCE_R2.json', 'sha256': 'bfefa8dbfde3d322326fc63757845689f7b81fe339861147e056e998c33b7ebd'}}
R5_FINITE_REFS={**R5_FINITE_REFS,**{"quote_cohort_"+name:ref for name,ref in R5_QUOTE_COHORT_REFS.items()}}

def _binding(mode):
    if mode==POST_PRIMARY_R5_MODE:
        return dict(mode=mode,module_refs={**MODULE_REFS,"controller":dict(CURRENT_R5_CONTROLLER_REF),"r7":dict(R5_R7_PROJECTION_REF),"transport":dict(R5_QUOTE_TRANSPORT_REF),"seam":dict(R5_QUOTE_SEAM_REF)},
            source_ref=SOURCE_FORMAL_R5,schemas=POST_PRIMARY_R5_SCHEMAS)
    if mode==POST_PRIMARY_MODE:
        return dict(mode=mode,module_refs={**MODULE_REFS,"controller":dict(CURRENT_CONTROLLER_REF)},
            source_ref=SOURCE_FORMAL_R4,schemas=POST_PRIMARY_SCHEMAS)
    return dict(mode="R2",module_refs=MODULE_REFS,source_ref=SOURCE_FORMAL_R2,schemas={
        "configuration":"FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1",
        "acceptance":"FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_ACCEPTANCE_R1",
        "cold":"FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_METADATA_COLD_R1",
        "quote":"FULL_SELECTOR_CORE_ACCOUNT_QUOTE_INPUT_QUALIFICATION_R1"})

def finite_source_refs_for(binding):
    return R5_FINITE_REFS if binding["mode"]==POST_PRIMARY_R5_MODE else FINITE_REFS

def configuration_binding(e,cfg):
    e.require(set(cfg)==CONFIG_FIELDS and cfg.get("schema") in (
        _binding("R2")["schemas"]["configuration"],POST_PRIMARY_SCHEMAS["configuration"],POST_PRIMARY_R5_SCHEMAS["configuration"]),
        "CLOSED_FINITE_SAVED5_CONFIGURATION_MODE_REQUIRED")
    mode=next(mode for mode in ("R2",POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE)
        if cfg["schema"]==_binding(mode)["schemas"]["configuration"])
    binding=_binding(mode)
    e.require(cfg["module_refs"]==binding["module_refs"] and cfg["finite_source_refs"]==finite_source_refs_for(binding)
        and cfg["engineering_source_configuration_ref"]==binding["source_ref"],
        "NO_MIXED_SAVED5_SOURCE_OR_CONTROLLER_PROVENANCE")
    return binding

def runtime_binding(e,c):
    actual=e.ref(c.__file__)
    e.require(actual in (MODULE_REFS["controller"],CURRENT_CONTROLLER_REF,CURRENT_R5_CONTROLLER_REF),"EXACT_OLD_OR_CURRENT_SAVED5_CONTROLLER_REQUIRED")
    return _binding(POST_PRIMARY_R5_MODE if actual==CURRENT_R5_CONTROLLER_REF else
        POST_PRIMARY_MODE if actual==CURRENT_CONTROLLER_REF else "R2")

@contextmanager
def registry_metadata_scope(e,c,run):
    e.require(Path(run).resolve()==RUN.resolve(),"EXACT_FIXED_ACCOUNT_RECOVERY_RUN_REQUIRED")
    binding=runtime_binding(e,c)
    if binding["mode"] in (POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE):
        with c.nonexecuting_registry_metadata_scope(run) as observation:
            yield observation
    else:
        yield None

def validate_source_history(e,cfg,binding):
    if binding["mode"] not in (POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE):
        return
    e.pin(SOURCE_FORMAL_R4,RUN/"ENGINEERING_SOURCE_CORRECTION_R4.json")
    correction=e.read(SOURCE_FORMAL_R4["path"])
    fields={"schema","status","research_id","design_ref","original_sources","replacements",
        "independent_review_ref","prior_source_configuration_ref","prior_controller_custody_ref","source_transport_ref"}
    e.require(set(correction)==fields and correction["schema"]=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R4"
        and correction["status"]=="PASS" and correction["research_id"]==ID
        and correction["prior_source_configuration_ref"]==SOURCE_FORMAL_R2
        and correction["prior_controller_custody_ref"]==POST_PRIMARY_REFS["original_ec6_custody_ref"]
        and correction["source_transport_ref"]==POST_PRIMARY_REFS["transport_ref"]
        and correction["design_ref"]==cfg["original_refs"]["DESIGN_FREEZE.json"],
        "EXACT_R4_R2_R1_EC6_HISTORY_REQUIRED")
    for value in (SOURCE_FORMAL_R2,cfg["prior_source_configuration_ref"],
        R5_RECOVERY_OWNER_REF if binding["mode"]==POST_PRIMARY_R5_MODE else REBOOT_OWNER_REF,
        *POST_PRIMARY_REFS.values(),*POST_PRIMARY_HISTORY.values()):
        e.pin(value)
    if binding["mode"]==POST_PRIMARY_R5_MODE:
        e.pin(SOURCE_FORMAL_R5,RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json")
        current=e.read(SOURCE_FORMAL_R5["path"])
        extra={"prior_r4_configuration_ref","prior_r4_transport_ref","prior_runtime_custody_refs",
            "human_authorization_ref","nonexecuted_live_custody_observation_ref","transport_owner_ref"}
        e.require(set(current)==fields|extra and current["schema"]=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R5"
            and current["status"]=="PASS" and current["research_id"]==ID
            and current["design_ref"]==correction["design_ref"] and current["original_sources"]==correction["original_sources"]
            and current["prior_source_configuration_ref"]==SOURCE_FORMAL_R2
            and current["prior_controller_custody_ref"]==POST_PRIMARY_REFS["original_ec6_custody_ref"]
            and current["source_transport_ref"]==R5_TRANSPORT_REF
            and current["prior_r4_configuration_ref"]==SOURCE_FORMAL_R4
            and current["prior_r4_transport_ref"]==POST_PRIMARY_REFS["transport_ref"]
            and current["prior_runtime_custody_refs"]==R5_RUNTIME_CUSTODY_REFS
            and current["human_authorization_ref"]==POST_PRIMARY_HISTORY["authority_ref"]
            and current["nonexecuted_live_custody_observation_ref"]==R5_CAPTURE_REF
            and current["transport_owner_ref"]==R5_RECOVERY_OWNER_REF,
            "EXACT_CURRENT_R5_SEPARATE_FROM_HISTORICAL_ALPHA_R4_REQUIRED")
        for value in (R5_TRANSPORT_REF,R5_CAPTURE_REF,CURRENT_R5_CONTROLLER_REF,*R5_RUNTIME_CUSTODY_REFS.values()):
            e.pin(value)
        e.pin(current["independent_review_ref"],RUN/"maintenance/SAVED5_POST_PRIMARY_SOURCE_GUARD_R5_INDEPENDENT_REVIEW_R1.json")
    # These three are upgrade byte custody, never formal R4's ec6 prior.
    # Unknown old registry/stateful bytes carry no AST equivalence claim.
    prior=e.read(SOURCE_FORMAL_R2["path"])
    e.require(prior.get("schema")=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2" and prior.get("status")=="PASS"
        and prior.get("research_id")==ID and prior["prior_source_configuration_ref"]==cfg["prior_source_configuration_ref"],
        "ORIGINAL_R2_TO_R1_HISTORY_REQUIRED")

def validate_post_primary_terminal(e,run,cfg,terminal_ref,audit_ref,ledger_prestate=None):
    e.require(Path(run).resolve()==RUN.resolve() and terminal_ref==POST_PRIMARY_REFS["complete_ref"]
        and audit_ref==POST_PRIMARY_REFS["audit_ref"],"EXACT_TRUE_POST_PRIMARY_COMPLETE_AND_AUDIT_REFS_REQUIRED")
    e.pin(terminal_ref,RUN/"continuation/POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_COMPLETE.json")
    e.pin(audit_ref,CACHE/"POST_PRIMARY_FUSION_ALPHA_TERMINAL_METADATA_ACCEPTANCE_R1.json")
    complete=e.read(terminal_ref["path"]);audit=e.read(audit_ref["path"])
    e.require(not (RUN/"continuation/REMAINING_ALPHA_REBOOT_RECOVERY_R1_COMPLETE.json").exists(),
        "OLD_REBOOT_FAILURE_CANNOT_BE_FAKE_COMPLETE")
    e.require(set(complete)==POST_PRIMARY_TERMINAL_FIELDS and complete["schema"]=="FULL_SELECTOR_POST_PRIMARY_FUSION_COMPLETE_R1"
        and complete["research_id"]==ID and complete["status"]=="NATURAL_APPLICATION_RETURN"
        and complete["entry_ref"]==POST_PRIMARY_REFS["entry_ref"] and complete["config_ref"]==POST_PRIMARY_REFS["configuration_ref"]
        and complete["acceptance_ref"]==POST_PRIMARY_REFS["acceptance_ref"] and complete["controller_ref"]==CURRENT_CONTROLLER_REF
        and complete["source_configuration_ref"]==SOURCE_FORMAL_R4 and complete["history_refs"]==POST_PRIMARY_HISTORY
        and complete["boundary_ref"]==POST_PRIMARY_HISTORY["boundary_ref"]
        and complete["first_fusion_entry_only"] is True and type(complete["new_backend_replay_events"]) is int
        and complete["new_backend_replay_events"]==0 and complete["original_replay_events_preserved"] is True
        and type(complete["scientific_failed_retries"]) is int and complete["scientific_failed_retries"]==0
        and type(complete["application_fusion_owner_calls"]) is int and complete["application_fusion_owner_calls"]==1
        and complete["os_exit_code_not_inferred"] is True,"TRUE_NEW_FUSION_COMPLETE_NOT_OLD_REBOOT_OR_COLD_REQUIRED")
    post=e.public_snapshot(complete["after"]["ledger"])
    e.require(set(post)=={"nodes_sha256","events_sha256","event_count"} and type(post["event_count"]) is int
        and (ledger_prestate is None or ledger_prestate==post),"EXACT_THREE_FIELD_TRUE_POST_PRIMARY_LEDGER_REQUIRED")
    e.require(audit.get("schema")=="FULL_SELECTOR_POST_PRIMARY_FUSION_ALPHA_TERMINAL_METADATA_ACCEPTANCE_R1"
        and audit.get("research_id")==ID and audit.get("status")=="PASS"
        and all(audit.get(k) is True for k in ("independent_from_entry_writer","actual_read_only_audit","workers_naturally_exited",
            "original432_event_prefix_exact","original1059_event_prefix_exact","original1554_failure_prefix_exact",
            "other_branches_zero_entry","HYBRID144_still_NAMED0","all99_actual_source_guard_passed","before_after_unchanged",
            "no_business_or_economic_body_reads","source_contexts_restored","readonly_connection_closed"))
        and audit.get("remaining_terminal_ref")==terminal_ref and audit.get("ledger_poststate")==post
        and cfg["engineering_source_configuration_ref"] in (SOURCE_FORMAL_R4,SOURCE_FORMAL_R5)
        and audit.get("engineering_source_configuration_ref")==SOURCE_FORMAL_R4
        and audit.get("base_manifest_ref")==cfg["base_manifest_ref"] and audit.get("runtime_entry_ref")==POST_PRIMARY_REFS["entry_ref"]
        and audit.get("phase_configuration_ref")==POST_PRIMARY_REFS["configuration_ref"]
        and audit.get("phase_acceptance_ref")==POST_PRIMARY_REFS["acceptance_ref"]
        and audit.get("natural_exit_receipt_ref")==POST_PRIMARY_REFS["os_exit_ref"]
        and audit.get("launch_receipt_ref")==POST_PRIMARY_REFS["launch_ref"]
        and audit.get("actual_controller_ref")==CURRENT_CONTROLLER_REF
        and audit.get("source_transport_ref")==POST_PRIMARY_REFS["transport_ref"]
        and audit.get("original_controller_custody_ref")==POST_PRIMARY_REFS["original_ec6_custody_ref"]
        and audit.get("old_reboot_failure_ref")==POST_PRIMARY_HISTORY["prior_failure_ref"]
        and audit.get("actual_failure_boundary_ref")==POST_PRIMARY_HISTORY["boundary_ref"]
        and type(audit.get("new_fusion_backend_replays")) is int and audit["new_fusion_backend_replays"]==0
        and type(audit.get("scientific_failure_retries")) is int and audit["scientific_failure_retries"]==0
        and type(audit.get("authorized_interruption_replays")) is int and audit["authorized_interruption_replays"]==1
        and audit.get("material_limits",{}).get("caller_ref")==POST_PRIMARY_REFS["audit_caller_ref"],
        "INDEPENDENT_EXACT_NEW_FUSION_NATURAL_TERMINAL_AUDIT_REQUIRED")
    for value in (POST_PRIMARY_REFS["os_exit_ref"],POST_PRIMARY_REFS["audit_caller_ref"]):e.pin(value)
    return complete,audit

def history_refs(run):
    return {key:dict(path=str(Path(run)/relative),sha256=value) for key,(relative,value) in HISTORY.items()}

def quote_binding():
    return dict(classification_ref=CLASSIFICATION_REF,current_market_refs=MARKET_REFS,
        transport_ref=MODULE_REFS["transport"],quote_owner_ref=MODULE_REFS["quote"])

def no_prior_attempt(e,run):
    folder=Path(run)/"continuation"
    forbidden=[folder/(NAME+"_"+x+".json") for x in ("STARTED","COMPLETE","FAILURE")]
    forbidden += [folder/"CORE_ACCOUNT_CONTINUATION_R1_COMPLETE.json",Path(run)/"PRIMARY_CORE_EXECUTION_COMPLETE.json",
        Path(run)/"CORE_BASE_ACCOUNT_TERMINAL.json",Path(run)/"CORE_ACCOUNT_TERMINAL.json",Path(run)/"ACCOUNT_TERMINAL.json"]
    e.require(not any(path.exists() for path in forbidden),"FIRST_NEW_ACCOUNT_PHASE_ONLY_OLD_FAILURE_PRESERVED")
    # Empty/partial paths are evidence of an attempt too; no prefix is removed.
    e.require(not (Path(run)/"accounts").exists(),"PRIOR_ACCOUNT_PUBLICATION_PREFIX_NO_RETRY")

def check_owners(e,modules):
    refs=runtime_binding(e,modules["controller"])["module_refs"]
    e.require(set(modules)==set(MODULE_REFS),"EXACT_FINITE_RUNTIME_MODULE_SET_REQUIRED")
    for name,value in refs.items():
        owner=modules[name];e.pin(value,value["path"])
        e.require(Path(owner.__file__).resolve()==Path(value["path"]).resolve(),
            "ACTUAL_ACCOUNT_RECOVERY_MODULE_ORIGIN_CHANGED:"+name)
    functions=((modules["continuation"].ledger_snapshot,"continuation"),
        (modules["controller"].worker_runtime,"controller"),
        (modules["controller"].engineering_source_configuration.__wrapped__,"controller"),(modules["controller"]._TaskLedger.__init__,"controller"),
        (modules["workflow"].run_accounts,"workflow"),(modules["workflow"]._worker_lock.__wrapped__,"workflow"),
        (modules["account"].load_account_inputs,"account"),(modules["transport"].bind_existing_quote_domain,"transport"),
        (modules["r7"].fixed_r7_account_overlay.__wrapped__,"r7"),(modules["seam"].account_quote_transport.__wrapped__,"seam"),
        (modules["quote"].build_usable_a_mask,"quote"))
    for function,name in functions:
        e.require(Path(function.__code__.co_filename).resolve()==Path(refs[name]["path"]).resolve(),
            "ACTUAL_ACCOUNT_RECOVERY_FUNCTION_ORIGIN_CHANGED:"+name)
    if refs["controller"] in (CURRENT_CONTROLLER_REF,CURRENT_R5_CONTROLLER_REF):
        for function in (modules["controller"].nonexecuting_registry_metadata_scope.__wrapped__,
            modules["controller"]._correction_ref):
            e.require(Path(function.__code__.co_filename).resolve()==Path(CURRENT_CONTROLLER_REF["path"]).resolve(),
                "ORIGINAL_CURRENT_REGISTRY_SCOPE_AND_RESOLVER_REQUIRED")


def load_acceptance(e,run,review_ref):
    run=Path(run).resolve();e.require(run==RUN.resolve(),"EXACT_FIXED_ACCOUNT_RECOVERY_RUN_REQUIRED")
    e.pin(review_ref,run/"continuation"/(NAME+"_ACCEPTANCE.json"));review=e.read(review_ref["path"])
    e.require(set(review)==REVIEW_FIELDS and review["schema"] in (_binding("R2")["schemas"]["acceptance"],POST_PRIMARY_SCHEMAS["acceptance"],POST_PRIMARY_R5_SCHEMAS["acceptance"])
        and review["research_id"]==ID and review["phase"]==PHASE and review["status"]=="PASS"
        and Path(review["run"]).resolve()==run,"CLOSED_FIXED_ACCOUNT_RECOVERY_ACCEPTANCE_REQUIRED")
    e.pin(review["phase_configuration_ref"],run/"continuation/CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1.json")
    cfg=e.read(review["phase_configuration_ref"]["path"])
    binding=configuration_binding(e,cfg)
    e.require(review["schema"]==binding["schemas"]["acceptance"],"NO_MIXED_SAVED5_ACCEPTANCE_SCHEMA")
    e.require(set(cfg)==CONFIG_FIELDS and cfg["schema"]==binding["schemas"]["configuration"]
        and all(cfg[k]==review[k] for k in CONFIG_FIELDS-{"schema"}),"CLOSED_FIXED_ACCOUNT_SOURCE_CONFIGURATION_REQUIRED")
    e.require(review["engineering_source_configuration_ref"]==binding["source_ref"],
        "EXACT_ACTUAL_FOUR_SOURCE_FORMAL_R2_REQUIRED")
    e.require(Path(__file__).resolve()==RUNTIME_PATH.resolve() and review["runtime_entry_ref"]==e.ref(__file__),
        "EXACT_INSTALLED_ACCOUNT_RECOVERY_ENTRY_REQUIRED")
    e.require(review["module_refs"]==binding["module_refs"] and review["finite_source_refs"]==finite_source_refs_for(binding),
        "FIXED_REVIEWED_ACCOUNT_RECOVERY_SOURCES_REQUIRED")
    e.require(review["all_prior_workers_terminal"] is True and review["independent_from_entry_writer"] is True
        and review["scientific_retry_authorized"] is False and review["first_account_dispatch_only"] is True
        and review["fixed_core_account_ids"]==list(CORE_IDS) and review["account_backend_entered_before_review"]==0,
        "NATURAL_TERMINAL_INDEPENDENT_FIRST_ACCOUNT_REVIEW_REQUIRED")
    e.pin(review["base_manifest_ref"],run/"continuation/ENGINEERING_CONTINUATION_MANIFEST_R1.json")
    e.require(review["base_manifest_ref"]["sha256"]==BASE_MANIFEST_SHA,"IMMUTABLE_SINGLE_BASE_MANIFEST_REQUIRED")
    manifest=e.read(review["base_manifest_ref"]["path"])
    e.pin(review["prior_source_configuration_ref"],run/"ENGINEERING_SOURCE_CORRECTION_R1.json")
    e.require(review["prior_source_configuration_ref"]["sha256"]==OLD_SOURCE_SHA
        and manifest["engineering_source_configuration_ref"]==review["prior_source_configuration_ref"],
        "OLD_SOURCE_R1_IS_IMMUTABLE_CUSTODY_REQUIRED")
    if binding["mode"] in (POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE):
        validate_source_history(e,cfg,binding)
    else:
        e.pin(review["engineering_source_configuration_ref"],run/"ENGINEERING_SOURCE_CORRECTION_R2.json")
        correction=e.read(review["engineering_source_configuration_ref"]["path"])
        e.require(correction.get("schema")=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2" and correction.get("status")=="PASS"
            and correction.get("research_id")==ID and correction["prior_source_configuration_ref"]==review["prior_source_configuration_ref"],
            "ACTUAL_CLOSED_FOUR_SOURCE_CORRECTION_REQUIRED")
    expected={n:dict(path=str(run/n),sha256=h) for n,h in ORIGINAL_PINS.items()}
    e.require(review["original_refs"]==expected and review["preserved_refs"]==history_refs(run),
        "ORIGINAL_FREEZE_FAILED_CORE_AND_EQUAL_REFS_REQUIRED")
    for value in (*expected.values(),*review["preserved_refs"].values(),*finite_source_refs_for(binding).values(),
        CLASSIFICATION_REF,*MARKET_REFS.values()):e.pin(value)
    old_failure=e.read(review["preserved_refs"]["old_core_failure_ref"]["path"])
    e.require("QUOTE_DECISION_KEY_NOT_IN_OLD_MASK:2023-01-26|PFE" in old_failure.get("error","")
        and old_failure.get("scientific_retries")==0,"EXACT_PRESERVED_PRE_ACCOUNT_QUOTE_FAILURE_REQUIRED")
    if binding["mode"] in (POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE):
        validate_post_primary_terminal(e,run,cfg,review["remaining_terminal_ref"],review["remaining_terminal_audit_ref"],review["ledger_prestate"])
    else:
        e.pin(review["remaining_terminal_ref"],run/"continuation/REMAINING_ALPHA_SOURCE_RECOVERY_R1_COMPLETE.json")
        remaining=e.read(review["remaining_terminal_ref"]["path"])
        e.require(remaining.get("research_id")==ID and remaining.get("phase")=="remaining-alpha-source-recovery"
            and remaining.get("status")=="INDEPENDENT_ALPHA_STAGE_TERMINAL"
            and remaining.get("ledger_poststate")==review["ledger_prestate"]
            and remaining.get("account_entry") is False and remaining.get("risk_dispatch_entered") is False
            and remaining.get("scientific_retries")==0,"NATURAL_REMAINING_ALPHA_TERMINAL_REQUIRED")
        e.pin(review["remaining_terminal_audit_ref"]);audit=e.read(review["remaining_terminal_audit_ref"]["path"])
        e.require(audit.get("schema")=="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_RECOVERY_TERMINAL_METADATA_ACCEPTANCE_R1"
            and audit.get("research_id")==ID and audit.get("status")=="PASS" and audit.get("actual_read_only_audit") is True
            and audit.get("remaining_terminal_ref")==review["remaining_terminal_ref"] and audit.get("workers_naturally_exited") is True
            and audit.get("ledger_poststate")==review["ledger_prestate"]
            and audit.get("engineering_source_configuration_ref")==review["engineering_source_configuration_ref"]
            and audit.get("base_manifest_ref")==review["base_manifest_ref"]
            and audit.get("runtime_entry_ref")==MODULE_REFS["continuation"],"INDEPENDENT_ACTUAL_REMAINING_TERMINAL_AUDIT_REQUIRED")
    e.pin(review["actual_source_metadata_cold_ref"]);cold=e.read(review["actual_source_metadata_cold_ref"]["path"])
    e.require(cold.get("schema")==binding["schemas"]["cold"]
        and cold.get("research_id")==ID and cold.get("status")=="PASS" and cold.get("actual_cold") is True
        and cold.get("synthetic") is False and cold.get("runtime_entry_ref")==review["runtime_entry_ref"]
        and cold.get("engineering_source_configuration_ref")==review["engineering_source_configuration_ref"]
        and cold.get("base_manifest_ref")==review["base_manifest_ref"] and cold.get("module_refs")==binding["module_refs"]
        and cold.get("finite_source_refs")==finite_source_refs_for(binding)
        and cold.get("phase_configuration_ref")==review["phase_configuration_ref"] and cold.get("ledger_prestate")==review["ledger_prestate"]
        and cold.get("ledger_poststate")==review["ledger_prestate"] and cold.get("scientific_entry_calls")==0,
        "ACTUAL_R7_SOURCE_METADATA_COLD_REQUIRED_NOT_SYNTHETIC")
    e.pin(review["actual_quote_input_qualification_ref"]);q=e.read(review["actual_quote_input_qualification_ref"]["path"])
    e.require(q.get("schema")==binding["schemas"]["quote"] and q.get("status")=="PASS"
        and q.get("research_id")==ID and q.get("actual_input_binding") is True and q.get("synthetic") is False
        and q.get("quote_binding")==quote_binding() and q.get("module_refs")==binding["module_refs"]
        and q.get("finite_source_refs")==finite_source_refs_for(binding)
        and q.get("phase_configuration_ref")==review["phase_configuration_ref"]
        and q.get("base_manifest_ref")==review["base_manifest_ref"]
        and q.get("engineering_source_configuration_ref")==review["engineering_source_configuration_ref"]
        and q.get("source_axis")=="ALL_CURRENT_FULL_U_SOURCE_AXES_PRE2026"
        and q.get("current_true_owner_coverage_exact") is True and q.get("current_quality_unchanged") is True
        and q.get("current_false_still_false") is True and q.get("historical_all_decisions_original_owner_verified") is True
        and q.get("historical_projected_keys_all_named") is True and q.get("original_raw_equality_verified") is True
        and q.get("held_or_selected_filter") is False and q.get("new_class_A_records")==0
        and q.get("classifier_rule_changed") is False and q.get("account_backend_entered")==0
        and q.get("ledger_prestate")==review["ledger_prestate"] and q.get("ledger_poststate")==review["ledger_prestate"],
        "ACTUAL_ALL_SOURCE_QUOTE_QUALIFICATION_REQUIRED_NO_WINNER_FILTER")
    if binding["mode"]==POST_PRIMARY_R5_MODE:
        extension=q.get("quote_coverage",{}).get("source_domain_transport",{}).get("fixed_raw_absence_non_a_extension",{})
        e.require(extension.get("schema")=="FULL_SELECTOR_FIXED_RAW_ABSENCE_NON_A_SOURCE_EXTENSION_R1"
            and extension.get("cohort_refs")==R5_QUOTE_COHORT_REFS
            and extension.get("runtime_metadata",{}).get("missing_count")==18500
            and extension.get("runtime_metadata",{}).get("missing_keys_sha256")=="b26b3dad6931ebd2676ae1af4714c1035c7875257b6de260db5c6ca81eee6575"
            and extension.get("runtime_metadata",{}).get("current_axis_sha256")=="acfe73dfb7bc8e878edfb8c87e31bec7c0565a570e13c3e5dee5c203aac193bc"
            and extension.get("classification_counts")=={"B":18500}
            and extension.get("new_class_A_records")==0 and extension.get("permission_added") is False
            and extension.get("persisted_new_decisions") is False and extension.get("U_t_used_as_filter") is False
            and all(extension.get(name)=="UNKNOWN" for name in ("identity_authority","raw_coordinate_authority","terminal_authority","real_defect_scope_completeness")),
            "EXACT_ACTUAL_NON_A_ABSENCE_COHORT_QUOTE_QUALIFICATION_REQUIRED")
    if binding["mode"] in (POST_PRIMARY_MODE,POST_PRIMARY_R5_MODE):
        e.require(cold.get("remaining_terminal_audit_ref")==review["remaining_terminal_audit_ref"]
            and q.get("remaining_terminal_audit_ref")==review["remaining_terminal_audit_ref"],
            "ACTUAL_NEW_TERMINAL_BOUND_COLD_AND_QUOTE_REQUIRED")
        e.pin(review["actual_source_metadata_cold_ref"],R5_COLD_PATH if binding["mode"]==POST_PRIMARY_R5_MODE else
            CACHE/"CORE_ACCOUNT_POST_PRIMARY_FUSION_SOURCE_RECOVERY_METADATA_COLD_R1.json")
        e.pin(review["actual_quote_input_qualification_ref"],R5_QUOTE_PATH if binding["mode"]==POST_PRIMARY_R5_MODE else
            CACHE/"CORE_ACCOUNT_POST_PRIMARY_FUSION_QUOTE_INPUT_QUALIFICATION_R1.json")
    no_prior_attempt(e,run)
    return review,manifest,e.read(run/"DESIGN_FREEZE.json")

def account_zero(e,snapshot,design,events):
    expected={"ACCOUNT|"+x for x in design["account_path_ids"]}
    rows=[r for r in snapshot["rows"] if r[1]=="CONTINUOUS_ACCOUNT"]
    e.require(len(expected)==len(rows)==66 and {r[0] for r in rows}==expected,
        "EXACT_ALL66_ACCOUNT_NODE_SET_REQUIRED")
    e.require(all(r[2]=="NAMED" and r[3]==0 and r[4] is None and r[5] is None and r[6] is None for r in rows),
        "ALL66_ACCOUNT_MUST_BE_UNATTEMPTED_NAMED")
    e.require(not any(row[1].startswith("ACCOUNT|") for row in events),"ACCOUNT_EVENT_HISTORY_EXISTS_NO_FIRST_DISPATCH")

def readonly_prestate(e,run,design,review):
    e.validate_existing_sqlite(run,design)
    db=sqlite3.connect((Path(run)/"TASK_LEDGER.sqlite").resolve().as_uri()+"?mode=ro",uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        snapshot=e.ledger_snapshot(SimpleNamespace(db=db),run)
        events=list(db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
        account_zero(e,snapshot,design,events)
        e.require(e.public_snapshot(snapshot)==review["ledger_prestate"],"TERMINAL_BOUND_LEDGER_CHANGED_BEFORE_ACCOUNT_CONSTRUCTOR")
        return snapshot
    finally:db.close()

def saved_core_terminal(e,run,review):
    terminal=e.read(e.pin(review["preserved_refs"]["core_policy_terminal_ref"],Path(run)/"CORE_BASE_POLICY_TERMINAL.json"))
    e.require(terminal.get("research_id")==ID and terminal.get("status")=="CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT"
        and terminal.get("design_sha256")==ORIGINAL_PINS["DESIGN_FREEZE.json"]
        and terminal.get("outer_result_feedback") is False and set(terminal.get("policy_refs",{}))==set(CORE_IDS),
        "EXACT_SAVED_FIVE_CORE_POLICIES_REQUIRED_NO_EQUAL_RETRANSFORM")
    for role,value in terminal["policy_refs"].items():
        e.frame_receipt(value,review["preserved_refs"]["equal_receipt_ref"] if role=="FUSION_equal" else None)
    equal=terminal["policy_refs"]["FUSION_equal"]
    e.require({k:equal[k] for k in ("path","sha256")}==review["preserved_refs"]["equal_policy_ref"],
        "EXACT_ALREADY_COMPLETE_EQUAL_POLICY_REQUIRED")
    return terminal

def postcondition(e,journal,run,before,events_before,authority_before,terminal):
    after=e.ledger_snapshot(journal,run);allowed={"ACCOUNT|"+x for x in terminal["policy_refs"]}
    e.require({r[0]:r for r in before["rows"] if r[0] not in allowed}==
        {r[0]:r for r in after["rows"] if r[0] not in allowed},"NON_CORE_ACCOUNT_SCIENTIFIC_STATE_CHANGED")
    events=list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
    e.require(events[:len(events_before)]==events_before and all(row[1] in allowed for row in events[len(events_before):]),
        "ORIGINAL_EVENTS_OR_NON_CORE_ACCOUNT_EVENTS_CHANGED")
    e.require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==authority_before,
        "SOLE_ACCOUNT_LEDGER_AUTHORITY_CHANGED")
    states={r[0]:r[2] for r in after["rows"]}
    e.require(all(states[n] in e.TERMINAL for n in allowed),"APPLICABLE_CORE_ACCOUNT_MUST_BE_TERMINAL")
    return after,states

def recover_once(run,review_ref,modules):
    """Future actual first account dispatch; never called in author validation."""
    e=modules["continuation"];c=modules["controller"];w=modules["workflow"];account=modules["account"]
    run=Path(run).resolve();e.require(run==RUN.resolve(),"EXACT_FIXED_ACCOUNT_RECOVERY_RUN_REQUIRED")
    check_owners(e,modules)
    with w._worker_lock(run):
        with registry_metadata_scope(e,c,run):
            review,manifest,design=load_acceptance(e,run,review_ref)
            # Original actual closed4 controller context, before readonly SQLite and
            # original constructor. No cached guard or old closed2 context is used.
            with c.engineering_source_configuration(review["engineering_source_configuration_ref"]):
                before=readonly_prestate(e,run,design,review)
                journal=c._TaskLedger(run)
                try:
                    current=e.ledger_snapshot(journal,run)
                    e.require(e.public_snapshot(current)==e.public_snapshot(before),"ACCOUNT_CONSTRUCTOR_CHANGED_TERMINAL_PRESTATE")
                    events_before=list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
                    authority_before=journal.db.execute("SELECT design_sha256 FROM authority").fetchall()
                    account_zero(e,current,design,events_before)
                    c.worker_runtime(run)
                    with modules["r7"].fixed_r7_account_overlay(e,account,manifest) as overlay:
                        account.metadata_preflight(run)
                        terminal=saved_core_terminal(e,run,review) # metadata + exact 8field/sidecar only
                        with modules["seam"].account_quote_transport(account,modules["quote"],modules["transport"],quote_binding()) as seam:
                            marker=e.append_json(run/"continuation"/(NAME+"_STARTED.json"),dict(
                                schema="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_STARTED_R1",
                                research_id=ID,phase=PHASE,phase_configuration_ref=review["phase_configuration_ref"],
                                review_ref=review_ref,runtime_entry_ref=review["runtime_entry_ref"],
                                base_manifest_ref=review["base_manifest_ref"],engineering_source_configuration_ref=review["engineering_source_configuration_ref"],
                                preserved_refs=review["preserved_refs"],ledger_prestate=e.public_snapshot(before),
                                account_source_overlay=overlay,quote_source_transport=seam,scientific_retries=0))
                            try:
                                # Sole business call: existing saved five-policy core,
                                # same66 ACCOUNT ledger, original account/friction rules.
                                w.run_accounts(run,policy_terminal=terminal)
                                after,states=postcondition(e,journal,run,before,events_before,authority_before,terminal)
                                e.validate_existing_sqlite(run,design)
                                for value in review["preserved_refs"].values():e.pin(value)
                                e.pin(review["base_manifest_ref"]);e.pin(review["prior_source_configuration_ref"])
                                account_terminal=e.ref(run/"CORE_BASE_ACCOUNT_TERMINAL.json")
                                completion=dict(schema="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_COMPLETE_R1",
                                    research_id=ID,phase=PHASE,status="CORE_NON_RISK_ACCOUNT_STAGE_TERMINAL",
                                    phase_configuration_ref=review["phase_configuration_ref"],review_ref=review_ref,marker_ref=marker,
                                    runtime_entry_ref=review["runtime_entry_ref"],
                                    engineering_source_configuration_ref=review["engineering_source_configuration_ref"],
                                    base_manifest_ref=review["base_manifest_ref"],preserved_refs=review["preserved_refs"],
                                    ledger_prestate=e.public_snapshot(before),ledger_poststate=e.public_snapshot(after),
                                    account_terminal_ref=account_terminal,applicable_core_account_ids=list(CORE_IDS),
                                    core_account_states={x:states["ACCOUNT|"+x] for x in CORE_IDS},
                                    preserved_failed_core_ref=review["preserved_refs"]["old_core_failure_ref"],
                                    existing_equal_exact_reuse=True,only_saved_core_account_dispatch=True,
                                    all66_accounts_complete=False,scientific_retries=0,all_task_complete=False,
                                    risk_dispatch_entered=False,outer_feedback=False)
                                e.require(set(completion)==COMPLETE_FIELDS,"CLOSED_FIVE_CORE_ACCOUNT_COMPLETION_REQUIRED")
                                completed=e.append_json(run/"continuation"/(NAME+"_COMPLETE.json"),completion)
                            except BaseException:
                                e.append_json(run/"continuation"/(NAME+"_FAILURE.json"),dict(
                                    schema="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_FAILURE_R1",
                                    research_id=ID,phase=PHASE,phase_configuration_ref=review["phase_configuration_ref"],
                                    review_ref=review_ref,marker_ref=marker,error=traceback.format_exc(),
                                    scientific_retries=0,preserved_failed_core_ref=review["preserved_refs"]["old_core_failure_ref"]))
                                raise
                            # First compatible publication only AFTER the new phase's
                            # natural terminal record. A publication failure retains
                            # COMPLETE and cannot cause another account dispatch.
                            e.require(not (run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").exists(),"PRESERVE_EXISTING_COMPATIBLE_COMPLETION")
                            w._immutable_account_json(run/"PRIMARY_CORE_EXECUTION_COMPLETE.json",dict(
                                research_id=ID,status="CORE_NON_RISK_STAGE_COMPLETE",design_ref=review["original_refs"]["DESIGN_FREEZE.json"],
                                all_task_complete=False,risk_estimates_started=False,account_terminal_ref=account_terminal,
                                engineering_continuation_ref=completed,original_core_failure_ref=review["preserved_refs"]["old_core_failure_ref"],
                                first_account_dispatch_only=True))
                            return completion
                finally:journal.db.close()
