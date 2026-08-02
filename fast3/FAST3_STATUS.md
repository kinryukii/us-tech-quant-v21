# FAST3 status

Machine source: `state/FAST3_STATE.json`.

| Field | Value |
|---|---|
| CURRENT_STAGE | FAST3-003 |
| CURRENT_STATUS | PASS_ARCHITECTURE_CONSOLIDATION |
| LAST_COMPLETED_STAGE | FAST3-003 |
| CONFIRMATION_READ_COUNT | 0 |
| LIVE_TRADING_ALLOWED | false |
| FROZEN_FAST3_002_HASH | 72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead |
| DATA_ROOT | D:\us-tech-quant-data\fast3 |
| RESULT_ROOT | D:\us-tech-quant-results\fast3 |
| LATEST_FORMAL_RESULT | D:\us-tech-quant-results\fast3\FAST3_002_EXECUTABLE_CONTRACT |

FAST3-002 remains contract-only and no model is trained. FAST3-004 is not
eligible to start automatically.

The current audit does not reopen Validation or Confirmation and does not alter
any historical result.

FAST3-003 maintenance moved all 115 identified repository-local legacy FAST3
result files to the external legacy archive after SHA256 verification, and
promoted the two FAST3-002 smoke outputs to the formal external result path.
Eleven pre-existing external autoresearch directories remain registered as an
unresolved archival boundary because this maintenance turn may not read their
potentially frozen Confirmation artifacts to perform required SHA256 checks.
