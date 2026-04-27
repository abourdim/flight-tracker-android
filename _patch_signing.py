#!/usr/bin/env python3
"""Idempotently patch android/app/build.gradle to wire signingConfigs.release
from android/keystore.properties.

Capacitor's `npx cap add android` produces a build.gradle with NO signing
configuration. Without this patch, `./gradlew bundleRelease` produces an
unsigned AAB that Play Console rejects.

This patch is idempotent — running it twice is a no-op.

Usage:
  ./_patch_signing.py             # patches ./android/app/build.gradle
  ./_patch_signing.py /path/to/repo/android/app/build.gradle
"""
import sys, pathlib, re

PRELUDE = '''def keystorePropertiesFile = rootProject.file("keystore.properties")
def keystoreProperties = new Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
}

'''

SIGNING_BLOCK = '''    signingConfigs {
        release {
            if (keystorePropertiesFile.exists()) {
                keyAlias keystoreProperties['keyAlias']
                keyPassword keystoreProperties['keyPassword']
                storeFile file(keystoreProperties['storeFile'])
                storePassword keystoreProperties['storePassword']
            }
        }
    }
'''

def patch(bg_path: pathlib.Path) -> bool:
    """Patches build.gradle in place. Returns True if changes were made."""
    if not bg_path.exists():
        print(f"  ✗ build.gradle not found: {bg_path}", file=sys.stderr)
        return False

    src = bg_path.read_text()
    changed = False

    # 1. Prelude
    if 'keystorePropertiesFile' not in src:
        src = PRELUDE + src
        changed = True

    # 2. signingConfigs block
    if 'signingConfigs {' not in src:
        new_src, n = re.subn(r'(    buildTypes \{)', SIGNING_BLOCK + r'\1', src, count=1)
        if n == 1:
            src = new_src
            changed = True

    # 3. Reference signing config from release buildType
    if 'signingConfig signingConfigs.release' not in src:
        new_src, n = re.subn(
            r'(release \{\s*\n)(            minifyEnabled false)',
            r'\1            signingConfig signingConfigs.release\n\2',
            src, count=1
        )
        if n == 1:
            src = new_src
            changed = True

    if changed:
        bg_path.write_text(src)
    return changed

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'android/app/build.gradle'
    bg = pathlib.Path(target)
    if patch(bg):
        print(f"  ✓ patched: {bg}")
    else:
        print(f"  · already patched (or no buildTypes block to inject into): {bg}")

if __name__ == "__main__":
    main()
