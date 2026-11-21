# -*- mode: python ; coding: utf-8 -*-
# Bauplan der EXE. BUILD.bat ruft:  py -3 -m PyInstaller --noconfirm --clean Essens-Plan.spec
from PyInstaller.utils.hooks import collect_submodules

# Eine onefile-EXE packt sich bei jedem Start komplett nach %TEMP% aus – alles, was nicht
# mitkommt, macht also nicht nur die Datei kleiner, sondern auch den Start schneller.
# Das hier zieht PyInstaller von selbst mit, das Programm braucht es aber nie:
WEG = [
    'PIL._avif', 'PIL.AvifImagePlugin',                     # AVIF-Bilder (8 MB)
    'cryptography', 'OpenSSL', 'cffi', '_cffi_backend',     # pyOpenSSL – requests nimmt das eingebaute ssl (10 MB)
    'setuptools', 'pkg_resources', '_distutils_hack', 'distutils',
]

hiddenimports = ['tkinter.ttk', 'PIL.ImageTk']
hiddenimports += collect_submodules('PIL')
hiddenimports += collect_submodules('reportlab')
hiddenimports = [m for m in hiddenimports if m not in WEG]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('res/rezepte.json', 'res'), ('res/icon.ico', 'res')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=WEG,
    noarchive=False,
    optimize=0,
)


def _unnoetig(ziel):
    """Zeitzonen-Tabellen von Tcl: 600 kleine Dateien, die nur der Tcl-Befehl „clock“ mit
    benannten Zeitzonen liest – den benutzt weder Tk noch das Programm."""
    return ziel.replace('\\', '/').startswith('_tcl_data/tzdata/')


a.datas = [d for d in a.datas if not _unnoetig(d[0])]
a.binaries = [b for b in a.binaries if not _unnoetig(b[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Essens-Plan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX-gepackte EXEn schlagen bei Virenscannern öfter falsch an
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['res/icon.ico'],
)
