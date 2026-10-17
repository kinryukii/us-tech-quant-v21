"""Streamlit entrypoint without the legacy adjacent pages-directory discovery."""
import os

# Presentation uses small tables; avoid preallocating a BLAS thread pool per DEMO.
# Respect explicit caller settings and leave the research-worker environment alone.
for _thread_variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_thread_variable, "1")

from apps.demo_console.app import main

if __name__ == "__main__":
    main()
