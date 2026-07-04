# Daily Chain Runbook

1. V21.198 Moomoo health check.
2. V21.199 Moomoo broad daily import and canonical merge.
3. Existing broad-date-aware ABCDE rerun chain.
4. Existing DRAM daily execution chain.
5. Existing forward tracking / switch governance chain.
6. Report/archive generation.

ABCDE reruns must use broad_honest_latest_date / broad-date completeness, never raw max(date). broker_action_allowed remains false throughout the chain.
