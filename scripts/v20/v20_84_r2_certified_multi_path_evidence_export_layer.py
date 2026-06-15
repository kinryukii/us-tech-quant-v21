#!/usr/bin/env python
"""V20.84-R2 rerun entrypoint after V20.93 evidence schema repair."""

from __future__ import annotations

from v20_84_certified_multi_path_evidence_export_layer import main


if __name__ == "__main__":
    raise SystemExit(main())
