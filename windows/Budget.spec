# PyInstaller recipe for Budget on Windows (a Budget folder with Budget.exe).
# Built by GitHub Actions (.github/workflows/windows.yml) or windows\build.ps1, not directly.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "static"), "static")],
    hiddenimports=[
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr",
        "keyring.backends.Windows",
        "win32ctypes.core",
        *collect_submodules("app"),
        *collect_submodules("uvicorn"),
    ],
    excludes=["tkinter", "pytest", "PIL", "PyInstaller"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Budget",
    icon=str(ROOT / "windows" / "Budget.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Budget")
