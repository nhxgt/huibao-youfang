# PyInstaller resource allowlist: never collect a project or user-data directory.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
resources = [
    (str(project / "work-report-prototype.html"), "."),
    (str(project / "frontend" / "app.js"), "frontend"),
    *[(str(path), "backend/prompts") for path in (project / "backend" / "prompts").glob("*.txt")],
]
analysis = Analysis(
    [str(project / "run.py")], pathex=[str(project)], binaries=[], datas=resources,
    hiddenimports=collect_submodules("uvicorn"), hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tests", "pytest"], noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="汇报有方",
    debug=False, strip=False, upx=False, console=True,
)
release = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name="汇报有方")
