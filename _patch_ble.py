#!/usr/bin/env python3
"""Idempotent BLE wiring for Capacitor Android wrapper:

  1. Inject Bluetooth permissions into android/app/src/main/AndroidManifest.xml
     (BLUETOOTH_SCAN, BLUETOOTH_CONNECT, ACCESS_FINE_LOCATION fallback for ≤A11)
  2. Inject <script src="cordova.js"> + cordova_plugins.js + web-bluetooth-shim.js
     tags into www/index.html (after <head>)

Run from a spawned wrapper repo.  Also called from manage-*.sh after `npx cap add android`.
"""
import sys, pathlib, re

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
MANIFEST = ROOT / 'android/app/src/main/AndroidManifest.xml'
INDEX    = ROOT / 'www/index.html'
SHIM_DST = ROOT / 'www/web-bluetooth-shim.js'
SHIM_SRC = pathlib.Path(__file__).parent / 'www-overlay/web-bluetooth-shim.js'

PERMS_BLOCK = '''    <!-- Bluetooth Low Energy (Capacitor BLE plugin) -->
    <uses-permission android:name="android.permission.BLUETOOTH_SCAN"   android:usesPermissionFlags="neverForLocation" tools:targetApi="s" />
    <uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
    <uses-permission android:name="android.permission.BLUETOOTH_ADVERTISE" />
    <!-- Pre-Android 12 fallback -->
    <uses-permission android:name="android.permission.BLUETOOTH" android:maxSdkVersion="30" />
    <uses-permission android:name="android.permission.BLUETOOTH_ADMIN" android:maxSdkVersion="30" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" android:maxSdkVersion="30" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30" />

    <uses-feature android:name="android.hardware.bluetooth_le" android:required="true" />

'''

SCRIPT_TAGS = '''<script src="cordova.js"></script>
<script src="cordova_plugins.js"></script>
<script src="web-bluetooth-shim.js"></script>
'''

def patch_manifest():
    if not MANIFEST.exists():
        print(f'  · manifest not found at {MANIFEST} (run npx cap add android first)')
        return False
    s = MANIFEST.read_text()
    if 'BLUETOOTH_SCAN' in s:
        print('  · manifest already patched')
        return True
    if 'xmlns:tools' not in s:
        s = s.replace(
            'xmlns:android="http://schemas.android.com/apk/res/android"',
            'xmlns:android="http://schemas.android.com/apk/res/android"\n    xmlns:tools="http://schemas.android.com/tools"',
            1)
    s = s.replace('    <application', PERMS_BLOCK + '    <application', 1)
    MANIFEST.write_text(s)
    print('  ✓ manifest: BLE permissions added')
    return True

def patch_index_html():
    if not INDEX.exists():
        print(f'  · {INDEX} not found')
        return False
    s = INDEX.read_text()
    if 'web-bluetooth-shim.js' in s:
        print('  · index.html already injects shim')
        return True
    if '<head>' in s:
        s = s.replace('<head>', '<head>\n' + SCRIPT_TAGS, 1)
    else:
        s = SCRIPT_TAGS + s
    INDEX.write_text(s)
    print('  ✓ index.html: cordova.js + shim script tags injected')
    return True

def copy_shim():
    if SHIM_DST.exists():
        print('  · shim already at www/')
        return True
    if not SHIM_SRC.exists():
        # Look for it next to the spawned repo (template might be elsewhere)
        for p in [pathlib.Path.cwd() / 'web-bluetooth-shim.js',
                  ROOT / 'web-bluetooth-shim.js']:
            if p.exists():
                SHIM_DST.write_text(p.read_text())
                print(f'  ✓ shim: copied from {p}')
                return True
        print(f'  ✗ shim source not found at {SHIM_SRC}')
        return False
    SHIM_DST.write_text(SHIM_SRC.read_text())
    print('  ✓ shim: copied to www/')
    return True

if __name__ == '__main__':
    print(f'BLE wiring for {ROOT}:')
    copy_shim()
    patch_index_html()
    patch_manifest()
