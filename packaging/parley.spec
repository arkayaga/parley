# PyInstaller spec for Parley (one-folder build; the installer wraps it into one setup .exe).
# Run from the repository root:  pyinstaller packaging/parley.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent

hidden = collect_submodules("edge_tts") + collect_submodules("winrt")

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
    icon=str(root / "assets" / "parley.ico"),
    console=False,
    upx=False,
    version=str(root / "build" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Parley", upx=False)
