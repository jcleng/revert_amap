#!/bin/bash
# Build a flashable/installable patched APK:
#   - replaces classes9.dex with the version where MainActivity.mcFixDisplay()
#     is a no-op (no more forced moveTaskToDisplay(0) / CLEAR_TASK relaunch)
#   - re-signs v1+v2+v3 with a fresh keystore
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
BASE=/home/jcleng/work/mywork/revert_amap/.work
OUT=$BASE/out
SRC=$BASE/target.apk
PATCHED_DEX=$BASE/patch/classes9_patched.dex
KS=$BASE/keystore/amapfix2.jks
KS_PASS=amapfix2

mkdir -p "$OUT" "$(dirname "$KS")"

if [ ! -f "$KS" ]; then
  keytool -genkeypair -v -keystore "$KS" -alias amapfix2 \
    -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -dname "CN=amap-fix, OU=dev, O=amap-fix, L=CN, ST=CN, C=CN" 2>&1 | tail -2
fi

UNSIGNED=$OUT/unsigned.apk
FINAL=$OUT/amap-splitfix-unsigned-tmp.apk
FINALAPK=$OUT/amap-splitfix.apk

python3 - "$SRC" "$UNSIGNED" "$PATCHED_DEX" <<'PY'
import sys, zipfile, shutil, os
src, dst, newdex = sys.argv[1], sys.argv[2], sys.argv[3]
nd = open(newdex, 'rb').read()
zin = zipfile.ZipFile(src)
zout = zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)
n = 0
for item in zin.infolist():
    name = item.filename
    if name.startswith('META-INF/') and name.upper().endswith(('.SF', '.RSA', '.DSA', '.EC', 'MANIFEST.MF')):
        continue                      # drop old signature files
    if name == 'classes9.dex':
        zout.writestr(item, nd)
        n += 1
        continue
    zout.writestr(item, zin.read(name))
zout.close(); zin.close()
print(f"[1] repacked {dst}: replaced classes9.dex ({len(nd)} bytes), dropped old META-INF sigs")
PY

# align then sign
zipalign -f -p 4 "$UNSIGNED" "$FINAL" 2>&1 | tail -2
apksigner sign --ks "$KS" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$FINALAPK" "$FINAL" 2>&1 | tail -3
rm -f "$UNSIGNED" "$FINAL"
echo "[2] signed -> $FINALAPK"
apksigner verify --print-certs -v "$FINALAPK" 2>&1 | head -10
ls -la "$FINALAPK"
sha256sum "$FINALAPK"
