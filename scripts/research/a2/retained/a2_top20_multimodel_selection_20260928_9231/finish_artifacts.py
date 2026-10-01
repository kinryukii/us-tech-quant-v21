"""Finish all reviewable artifacts once the four frozen scenarios are complete."""
from pathlib import Path
import os,subprocess,sys,time

ROOT=Path(__file__).resolve().parent
def main():
    outputs=[ROOT/f'evaluation_{y}/cost_{c}/COMPLETE.json' for y,c in [(2025,10),(2026,10),(2026,5),(2026,25)]]
    start=time.monotonic()
    while not all(p.exists() for p in outputs):
        if time.monotonic()-start>2700:raise TimeoutError('Scenario outputs not all complete')
        time.sleep(3)
    env=os.environ.copy();env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',LOKY_MAX_CPU_COUNT='2')
    for script in ['summarize_training.py','verify_and_report.py','diagnostics.py','export_top20.py','seal_run.py']:
        print(f'Running {script}',flush=True)
        subprocess.run([sys.executable,'-u',str(ROOT/script)],cwd=ROOT,env=env,check=True)
    print('ALL_ARTIFACTS_COMPLETE',flush=True)

if __name__=='__main__':main()
