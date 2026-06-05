# PyInstaller spec for Home Fileshare Admin.
#
# Build from the repo root:
#     pyinstaller admin_app/build_exe.spec
#
# Produces dist/HomeFileshareAdmin.exe (one-file, windowed).
# Distribute the .exe alongside the existing server/, web/, scripts/,
# config.example.yaml so it can manage the local install.

import os

import customtkinter

block_cipher = None

# Bundle the customtkinter assets (themes, fonts) that it loads at runtime.
ctk_path = os.path.dirname(customtkinter.__file__)

a = Analysis(
    ["__main__.py"],
    pathex=[os.path.abspath(os.path.join(os.getcwd()))],
    binaries=[],
    datas=[
        (ctk_path, "customtkinter"),
    ],
    hiddenimports=[
        "passlib.handlers.bcrypt",
        "server.config",
        "server.database",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HomeFileshareAdmin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
