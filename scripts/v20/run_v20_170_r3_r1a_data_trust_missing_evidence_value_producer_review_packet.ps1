$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r3_r1a_data_trust_missing_evidence_value_producer_review_packet.py"

python $Runner
