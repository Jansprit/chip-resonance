"""
scripts/rotate_snapshots.py — Prune old dated snapshots beyond retention

Usage:
    python -m backend.scripts.rotate_snapshots --retention-days 90

預設：保留最近 90 天的 data/YYYY-MM-DD/ 快照，超過的移到 data/_archive/YYYY-MM-DD/。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def find_snapshot_dirs(data_dir: Path) -> list[Path]:
    """找出所有 data/YYYY-MM-DD/ 目錄（不含 data/_archive、data/latest）。"""
    if not data_dir.exists():
        return []
    out = []
    for p in data_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if name in ("latest", "_archive", "local"):
            continue
        # 確認是 YYYY-MM-DD 格式
        try:
            datetime.fromisoformat(name)
            out.append(p)
        except ValueError:
            pass
    return out


def rotate(data_dir: Path, retention_days: int = 90, dry_run: bool = False) -> dict:
    """把超過 retention_days 的快照移到 data/_archive/。"""
    cutoff = datetime.now() - timedelta(days=retention_days)
    archive_dir = data_dir / "_archive"

    snapshots = find_snapshot_dirs(data_dir)
    moved = []
    kept = []
    for snap in snapshots:
        snap_date = datetime.fromisoformat(snap.name)
        if snap_date < cutoff:
            target = archive_dir / snap.name
            if not dry_run:
                archive_dir.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(snap), str(target))
            moved.append(snap.name)
        else:
            kept.append(snap.name)

    return {
        "cutoff_date": cutoff.date().isoformat(),
        "retention_days": retention_days,
        "moved_to_archive": sorted(moved),
        "kept": sorted(kept),
        "dry_run": dry_run,
    }


def main():
    repo = Path(__file__).resolve().parents[2]
    data_dir = repo / "data"

    p = argparse.ArgumentParser(description="Rotate old data snapshots")
    p.add_argument("--retention-days", type=int, default=90,
                   help="保留最近 N 天的快照（預設 90）")
    p.add_argument("--dry-run", action="store_true",
                   help="只列印會被移的資料夾，不實際移動")
    p.add_argument("--data-dir", default=str(data_dir))
    args = p.parse_args()

    result = rotate(Path(args.data_dir), args.retention_days, args.dry_run)
    print(f"Cutoff date: {result['cutoff_date']}")
    print(f"Retention:   {result['retention_days']} days")
    print(f"Mode:        {'DRY-RUN' if result['dry_run'] else 'LIVE'}")
    print()
    print(f"Moved to archive ({len(result['moved_to_archive'])}):")
    for d in result["moved_to_archive"]:
        print(f"  - {d}")
    print(f"Kept ({len(result['kept'])}):")
    for d in result["kept"]:
        print(f"  - {d}")


if __name__ == "__main__":
    main()