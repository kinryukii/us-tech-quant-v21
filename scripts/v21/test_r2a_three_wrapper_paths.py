from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FILES=[ROOT/'scripts/v21/run_v21_232_moomoo_only_dram_daily_and_intraday_plan.ps1',ROOT/'scripts/v21/run_v21_234_minimal_moomoo_only_daily_research_chain.ps1',ROOT/'scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1']
def text(i): return FILES[i].read_text(encoding='utf-8')
def test_232_external_python(): assert 'Get-UstqPythonExecutable' in text(0)
def test_232_external_daily(): assert 'Get-UstqDailyRoot' in text(0)
def test_232_no_repo_venv(): assert '.venv\\Scripts\\python.exe' not in text(0)
def test_234_external_python(): assert 'Get-UstqPythonExecutable' in text(1)
def test_234_external_daily(): assert 'Get-UstqDailyRoot' in text(1)
def test_234_no_repo_outputs(): assert 'Join-Path $RepoRoot "outputs' not in text(1)
def test_256_external_python(): assert 'Get-UstqPythonExecutable' in text(2)
def test_256_external_daily_context_log(): assert 'Get-UstqDailyRoot' in text(2) and 'v21_256_wrapper_stdout.log' in text(2)
def test_256_inherits_ustq_paths(): assert '$env:USTQ_DAILY_ROOT' in text(2) and '$env:USTQ_PYTHON_EXE' in text(2)
