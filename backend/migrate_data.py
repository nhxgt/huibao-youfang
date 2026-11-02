"""Explicitly copy an existing installation's data; never imported on startup."""
import argparse
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .paths import user_data_dir


def _empty_destination(target):
    if not target.exists():
        return True
    if not target.is_dir():
        return False
    allowed = {"reports.sqlite3", "reports.sqlite3-wal", "reports.sqlite3-shm", "files", "tmp"}
    for entry in target.iterdir():
        if entry.is_symlink() or entry.name not in allowed or (entry.is_dir() and any(entry.iterdir())):
            return False
        if (entry.name in {"files", "tmp"}) != entry.is_dir():
            return False
    database = target / "reports.sqlite3"
    if database.exists():
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != {"settings", "files", "reports", "report_files", "drafts"}:
                return False
            if any(con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in tables):
                return False
    elif any(entry.is_file() for entry in target.iterdir()):
        return False
    return True


def migrate_data(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("源目录和目标目录必须相互独立。")
    database = source / "reports.sqlite3"
    if not database.is_file():
        raise ValueError("源目录没有汇报数据库。")
    if not _empty_destination(target):
        raise ValueError("目标目录已有数据，迁移不会覆盖现有用户内容。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="report-migration-", dir=target.parent) as directory:
        stage = Path(directory)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as old:
            with closing(sqlite3.connect(stage / "reports.sqlite3")) as copied:
                old.backup(copied)
                file_ids = [row[0] for row in copied.execute("SELECT id FROM files")]
                reports = copied.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        (stage / "files").mkdir()
        for file_id in file_ids:
            if not re.fullmatch(r"[0-9a-f]{32}", file_id):
                raise ValueError("存在无效文件标识，未执行迁移。")
            shutil.copy2(source / "files" / file_id, stage / "files" / file_id)
        if target.exists():
            if not _empty_destination(target):
                raise ValueError("迁移期间目标目录已写入数据，未覆盖目标。")
            # Only the verified empty app database and empty directories are removed.
            for entry in target.iterdir():
                entry.rmdir() if entry.is_dir() else entry.unlink()
            target.rmdir()
        os.replace(stage, target)
    return {"reports": reports, "files": len(file_ids)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="保留原目录，将旧版数据复制到独立用户目录。请先停止旧服务。")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", default=str(user_data_dir()))
    args = parser.parse_args()
    print(migrate_data(args.source, args.target))
