# FAST3 anti-bloat policy

FAST3 stages use one integer stage ID, one formal config, one runner, one final
report, one stage manifest, and one test-evidence record. Git commits—not file
suffixes—record fixes. New `A`, `B`, `R1`, `final`, `patched`, retry prompts,
authorization files, and patch-applied files are prohibited.

The hard budgets in `configs/runtime/FAST3_ANTI_BLOAT_LIMITS.json` govern each
ordinary stage. Exceeding them fails the guard unless that stage manifest holds
one explicit Architecture Exception stating the required files and reason.
Tests extend shared unit/integration/regression files when possible. Results are
external under `D:\us-tech-quant-results\fast3`; repository artifacts are code,
small manifests, summaries, and evidence only.

The sole current directive is `FAST3_CURRENT_STAGE_DIRECTIVE.md`; one final
directive may be archived per completed stage. Authorization scope belongs in a
stage manifest and governance belongs in `FAST3_GOVERNANCE.md`.
