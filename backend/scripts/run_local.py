"""
scripts/run_local.py — 本地手動跑（包裝 pipeline.py）

用法：
    python -m backend.scripts.run_local
    python -m backend.scripts.run_local --source twse
"""

import argparse
import sys
from pathlib import Path

# 確保 backend/ 路徑可被 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import main


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run chip-resonance pipeline locally")
    p.add_argument("--source", default="all", choices=["all", "twse"])
    p.add_argument("--out-dir", default="data/latest")
    p.add_argument("--repo", default=None,
                   help="Repo root path (default: parent of backend/)")
    args = p.parse_args()

    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    rc = main(repo=repo, source=args.source, out_dir_name=args.out_dir)
    sys.exit(rc)