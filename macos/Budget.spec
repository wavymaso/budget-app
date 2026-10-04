# PyInstaller recipe for Budget.app. Run via ./build.sh, not directly.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = (ROOT / "VERSION").read_text().strip()

a = Analysis(
    [str(ROOT / "macos" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "static"), "static")],
    hiddenimports=[
        "app._build_info",
        "webview.platforms.cocoa",
        "keyring.backends.macOS",
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
    console=False,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Budget")
app = BUNDLE(
    coll,
    name="Budget.app",
    icon=str(ROOT / "macos" / "Budget.icns"),
    bundle_identifier="local.budget.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "Budget",
        "CFBundleDisplayName": "Budget",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSApplicationCategoryType": "public.app-category.finance",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Personal budget tracker",
        # The window talks to the app's own server on 127.0.0.1.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
