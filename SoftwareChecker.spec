# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app/server.py'],
    pathex=[],
    binaries=[],
    datas=[('app/files', 'files')],
    hiddenimports=[
        'win32com.client',
        'pywintypes',
        'win32file',
        'win32event',
        'win32process',
        'windows_toasts',
        'lxml',
        'lxml.etree',
        'flask',
        'flask_cors',
        'openpyxl',
        'openpyxl.cell',
        'openpyxl.cell.cell',
        'tkinter',
        'webview',
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
    name='SoftwareChecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon='icon.ico',
)
