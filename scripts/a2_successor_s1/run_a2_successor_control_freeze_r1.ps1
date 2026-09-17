param(
    [string]$Config = "D:\us-tech-quant\config\a2_successor_s1\control_contract.json",
    [string]$Artifact = "D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\final_full_pre2026_hgb.joblib"
)
$ErrorActionPreference = "Stop"
$python = "D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe"
& $python "D:\us-tech-quant\scripts\a2_successor_s1\successor_control.py" validate --config $Config --artifact $Artifact
exit $LASTEXITCODE
