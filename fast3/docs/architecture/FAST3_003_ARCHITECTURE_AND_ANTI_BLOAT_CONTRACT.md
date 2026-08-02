# FAST3-003 architecture and anti-bloat contract

Frozen root layout is the FAST3-003 user-approved whitelist: root documents;
`configs/{contracts,models,runtime}`; `src/fast3`; classified tests;
`scripts/{run,audit,maintenance}`; `docs/{architecture,governance,reports,legacy}`;
`manifests/{stages,registries,legacy}`; `state/FAST3_STATE.json`; and top-level
`compatibility` for only startup/path wrappers. Historical V22 remains outside
this package and is reachable only through `src/fast3/compatibility/legacy_v22.py`.

`FAST3_STATE.json` is the machine state source. Stage/config/file registries
are machine sources; `FAST3_STATUS.md` and `FAST3_REGISTRY.md` are checked human
views. Data and formal run results are fixed to `D:\us-tech-quant-data\fast3`
and `D:\us-tech-quant-results\fast3`, respectively. Repository `outputs` and
`stages` are prohibited as formal result roots.

Anti-bloat limits are in `configs/runtime/FAST3_ANTI_BLOAT_LIMITS.json`; the
policy is in `docs/governance/FAST3_ANTI_BLOAT_POLICY.md`. FAST3-003 has one
explicit Architecture Exception because its mandated independent Guard files,
registries, governance documents, pre-inventory, report, and evidence exceed a
normal 12-file research-stage budget. It authorizes only governance/guard work,
not new model/business modules.
