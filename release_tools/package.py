"""Package only the frozen application; reject common personal-data artifacts."""
import argparse
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

APP_NAME = "汇报有方"
DISTRIBUTION_NAME = "《汇报有方——智能日报周报》平台"
FORBIDDEN_NAMES = {".env", "reports.sqlite3-wal", "reports.sqlite3-shm"}
FORBIDDEN_DIRS = {"data", "files", ".venv", "tests", "__pycache__"}


def create_release(dist):
    dist = Path(dist).resolve()
    root = dist / APP_NAME
    if not (root / (APP_NAME + ".exe")).is_file():
        raise ValueError("未找到已构建的应用程序。")
    members = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if (path.is_symlink() or any(part in FORBIDDEN_DIRS for part in rel.parts) or
                path.name in FORBIDDEN_NAMES or path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}):
            raise ValueError("分发目录包含不应打包的用户数据或配置，请检查构建内容。")
        if path.is_file():
            members.append(path)
    readme = root / "README.txt"
    shutil.copyfile(Path(__file__).with_name("README-zh-CN.txt"), readme)
    members = [p for p in members if p != readme] + [readme]
    archive = dist / (DISTRIBUTION_NAME + ".zip")
    handle, temporary = tempfile.mkstemp(prefix="release-", suffix=".zip", dir=dist)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for path in members:
                output.write(path, Path(DISTRIBUTION_NAME) / path.relative_to(root))
        os.replace(temporary, archive)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    print(create_release(parser.parse_args().dist))
