"""
test_rotate_snapshots.py — 測試 90 天快照歸檔

"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.rotate_snapshots import find_snapshot_dirs, rotate


def test_find_snapshot_dirs_skips_special_dirs():
    """find_snapshot_dirs 應該排除 latest / _archive / local。"""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # 建立一些目錄
        (data_dir / "2026-09-22").mkdir()
        (data_dir / "2025-01-01").mkdir()
        (data_dir / "latest").mkdir()
        (data_dir / "_archive").mkdir()
        (data_dir / "local").mkdir()
        (data_dir / "not-a-date").mkdir()
        (data_dir / "2026-09-22" / "prices.json").write_text("{}")

        result = find_snapshot_dirs(data_dir)
        names = sorted(p.name for p in result)
        assert "2026-09-22" in names
        assert "2025-01-01" in names
        assert "latest" not in names
        assert "_archive" not in names
        assert "local" not in names
        assert "not-a-date" not in names


def test_rotate_dry_run_moves_old_snapshots():
    """rotate --dry-run 應該列出會被移的目錄但實際不動。"""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # 建立一個 100 天前的快照
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        (data_dir / old_date).mkdir()
        (data_dir / old_date / "data.json").write_text("{}")
        # 建立一個 30 天前的快照
        new_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        (data_dir / new_date).mkdir()
        (data_dir / new_date / "data.json").write_text("{}")

        result = rotate(data_dir, retention_days=90, dry_run=True)

        assert result["dry_run"] is True
        assert old_date in result["moved_to_archive"]
        assert new_date in result["kept"]
        # 驗證 dry-run 沒有實際移動
        assert (data_dir / old_date).exists()
        assert not (data_dir / "_archive").exists()


def test_rotate_actually_moves_old_snapshots():
    """rotate（live）應該把過期快照真的移到 _archive。"""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        old_dir = data_dir / old_date
        old_dir.mkdir()
        (old_dir / "prices.json").write_text('{"test": 1}')

        result = rotate(data_dir, retention_days=90, dry_run=False)

        assert old_date in result["moved_to_archive"]
        # 原始位置不應再存在
        assert not old_dir.exists()
        # 已移到 _archive
        assert (data_dir / "_archive" / old_date / "prices.json").exists()
        # 內容應一致
        with open(data_dir / "_archive" / old_date / "prices.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data["test"] == 1


def test_rotate_keeps_recent_snapshots():
    """rotate 應該保留 retention 內的快照。"""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        recent_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        (data_dir / recent_date).mkdir()

        result = rotate(data_dir, retention_days=90, dry_run=False)

        assert recent_date in result["kept"]
        assert recent_date not in result["moved_to_archive"]
        assert (data_dir / recent_date).exists()
        assert not (data_dir / "_archive").exists()


def test_rotate_custom_retention():
    """rotate 應該尊重 --retention-days 參數。"""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # 50 天前的快照
        date_50 = (datetime.now() - timedelta(days=50)).strftime("%Y-%m-%d")
        (data_dir / date_50).mkdir()

        # retention=30：50 天前的應該被歸檔
        result_30 = rotate(data_dir, retention_days=30, dry_run=False)
        assert date_50 in result_30["moved_to_archive"]

        # 重新建立
        (data_dir / date_50).mkdir()

        # retention=60：50 天前的應該保留
        result_60 = rotate(data_dir, retention_days=60, dry_run=False)
        assert date_50 in result_60["kept"]


if __name__ == "__main__":
    test_find_snapshot_dirs_skips_special_dirs()
    print("PASS: test_find_snapshot_dirs_skips_special_dirs")
    test_rotate_dry_run_moves_old_snapshots()
    print("PASS: test_rotate_dry_run_moves_old_snapshots")
    test_rotate_actually_moves_old_snapshots()
    print("PASS: test_rotate_actually_moves_old_snapshots")
    test_rotate_keeps_recent_snapshots()
    print("PASS: test_rotate_keeps_recent_snapshots")
    test_rotate_custom_retention()
    print("PASS: test_rotate_custom_retention")
    print("\nAll 5 rotation tests passed.")