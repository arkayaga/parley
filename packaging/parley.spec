# PyInstaller spec for Parley.
#   Windows: one-folder build in dist/Parley, wrapped into ParleySetup.exe by Inno Setup.
#   macOS:   dist/Parley.app, wrapped into Parley.dmg (first install) and Parley-macOS.zip (updates).
# Run from the repository root:  pyinstaller packaging/parley.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from parley.version import VERSION  # noqa: E402

mac = sys.platform == "darwin"
hidden = collect_submodules("edge_tts")
hidden += collect_submodules("winrt") if sys.platform == "win32" else []
hidden += ["Vision", "Quartz", "parley.ocr_mac"] if mac else ["parley.ocr_win"]

a = Analysis(
    [str(root / "parley" / "__main__.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "ui"), "ui"),
        (str(root / "THIRD_PARTY_NOTICES.txt"), "."),
        (str(root / "LICENSE"), "."),
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "numpy", "PIL", "pytest", "unittest", "pydoc_data", "lib2to3"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Parley",
    icon=str(root / "assets" / ("parley.icns" if mac else "parley.ico")),
    console=False,
    upx=False,
    version=None if mac else str(root / "build" / "version_info.txt"),
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Parley", upx=False)

if mac:
    app = BUNDLE(
        coll,
        name="Parley.app",
        icon=str(root / "assets" / "parley.icns"),
        bundle_identifier="io.github.arkayaga.parley",
        version=VERSION,
        info_plist={
            "CFBundleName": "Parley",
            "CFBundleDisplayName": "Parley",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "Parley - free software (MIT)",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Parley project",
                "CFBundleTypeExtensions": ["parley"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
