$ErrorActionPreference = "Stop"

python scripts/v21/v21_154_e_r1_invalid_trial_repair_and_replay_reaudit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.154 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_154_e_r1_invalid_trial_repair_and_replay_reaudit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.154 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/V21.154_readable_report.txt
Get-Content outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/V21.154_machine_summary.json
