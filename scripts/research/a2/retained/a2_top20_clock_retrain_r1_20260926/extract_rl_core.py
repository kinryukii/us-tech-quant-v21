"""Preparation-only source whitelist for the unchanged original policy mapping."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parent
source = (root.parent / "a2_top20_all_methods_20260925" / "rl_policy.py").read_text(encoding="utf-8")
tree = ast.parse(source)
names = ("Policy", "build_days", "policy_target")
found = {node.name: ast.get_source_segment(source, node) for node in tree.body
         if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names}
if set(found) != set(names):
    raise RuntimeError("POLICY_SOURCE_WHITELIST_CHANGED")
header = '''"""Original REINFORCE policy and target mapping, whitelisted source extract."""
from __future__ import annotations
import numpy as np
import pandas as pd
import torch
from torch import nn
FEATURES = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d", "ret_20d",
            "realized_vol_20d", "downside_vol_20d", "max_drawdown_20d",
            "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d"]
MAX_WEIGHT = .10
MAX_EXPOSURE = .95
MAX_NAMES = 30
ZERO_GATE = .30
NOISE_STD = .45
'''
path = root / "trainer_bundle" / "rl_core.py"
if path.exists():
    raise RuntimeError("RL_CORE_ALREADY_EXISTS")
path.write_text(header + "\n\n".join(found[name] for name in names) + "\n", encoding="utf-8")
print(path)
