#!/bin/bash
# Build the installable patched APK.
#
#   * repair the systematically mistranslated charging (充电) string family in
#     resources.arsc -- see scripts/fix_ChargeStationStrings.py (fix #6)
#   * rename the application package  com.autonavi.amapauto -> com.autonavi.amapautolite
#     in AndroidManifest.xml + resources.arsc (binary, in place, see
#     scripts/rename_pkg_binary.py) and in the dex files (scripts/fix_RenamePackage.py)
#   * swap in the code-fixed dexes for
#       classes9.dex  - MainActivity.mcFixDisplay() no-op
#       classes22.dex - NaviView.Dd() null-guard
#       classes25.dex - DpiScaleManager.applyImmersive() no longer forces fullscreen
#   * drop the old signature, zipalign, re-sign v1+v2+v3
#
# Inputs : .work/target.apk (original repack) and .work/patch/*_pkg.dex
# Outputs: .work/out/amap-splitfix-lite.apk
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
BASE=/home/jcleng/work/mywork/revert_amap/.work
OUT=$BASE/out
SRC=$BASE/target.apk
PATCH=$BASE/patch
KS=$BASE/keystore/amapfix2.jks
KS_PASS=amapfix2
OLD_PKG=com.autonavi.amapauto
NEW_PKG=com.autonavi.amapautolite
# ContentProvider authorities that are NOT derived from the package name and that
# collide with the pre-installed app (INSTALL_FAILED_CONFLICTING_PROVIDER).
EXTRA_RENAMES="com.byd.naviauto.mapprovider=com.autonavi.amapautolite.mapprovider \
com.byd.automap.fenceprovider=com.autonavi.amapautolite.fenceprovider"
# dexes whose contents get replaced (the three code fixes + the rename-only ones)
DEXES="classes.dex classes5.dex classes8.dex classes9.dex classes11.dex classes13.dex \
       classes18.dex classes21.dex classes22.dex classes25.dex"

mkdir -p "$OUT" "$(dirname "$KS")"

if [ ! -f "$KS" ]; then
  keytool -genkeypair -v -keystore "$KS" -alias amapfix2 \
    -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -dname "CN=amap-fix, OU=dev, O=amap-fix, L=CN, ST=CN, C=CN" 2>&1 | tail -2
fi

for d in $DEXES; do
  b=${d%.dex}
  [ -f "$PATCH/${b}_pkg.dex" ] || { echo "missing $PATCH/${b}_pkg.dex -- run scripts/build_patch.sh first"; exit 1; }
done

UNSIGNED=$OUT/unsigned.apk
ALIGNED=$OUT/aligned.apk
FINALAPK=$OUT/amap-splitfix-lite.apk

# shellcheck disable=SC2086
python3 - "$SRC" "$UNSIGNED" "$PATCH" "$OLD_PKG" "$NEW_PKG" $EXTRA_RENAMES $DEXES <<'PY'
import sys, zipfile, os
src, dst, patchdir, old, new = sys.argv[1:6]
rest = sys.argv[6:]
# leading "a=b" arguments are extra old=new rename pairs; the rest are dex names
pairs = [(old, new)]
while rest and '=' in rest[0]:
    pairs.append(tuple(rest.pop(0).split('=', 1)))
dexes = rest

# --- 1. binary rename of AndroidManifest.xml + resources.arsc -----------------
sys.path.insert(0, '/home/jcleng/work/mywork/revert_amap/scripts')
from rename_pkg_binary import replace_manifest, replace_arsc
from fix_ChargeStationStrings import patch_arsc

zin = zipfile.ZipFile(src)
mf = zin.read('AndroidManifest.xml')
ar = zin.read('resources.arsc')

# --- 0. fix #6: repair the mistranslated 充电 (charging) string family ----------
ar, cs_n = patch_arsc(ar, verbose=False)
print('[0] arsc string fix: %d charge-family entries repointed, %d -> %d bytes'
      % (cs_n, len(zin.read('resources.arsc')), len(ar)))

# --- 1. binary rename of AndroidManifest.xml + resources.arsc -----------------
mf2, mf_n, mf_total = replace_manifest(mf, pairs)
ar2, pkg_n, pool_n = replace_arsc(ar, pairs)
assert mf_n > 0 and pkg_n > 0, 'package rename did not apply'
print('[1] renames: %s' % ', '.join('%s->%s' % p for p in pairs))
print('    manifest: %d/%d strings renamed, %d -> %d bytes'
      % (mf_n, mf_total, len(mf), len(mf2)))
print('    arsc    : %d package-name field, %d pool strings, %d -> %d bytes'
      % (pkg_n, pool_n, len(ar), len(ar2)))

# --- 2. repack: renamed manifest/arsc + patched dexes, old signature dropped ---
zout = zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)
replaced = []
for item in zin.infolist():
    name = item.filename
    if name.startswith('META-INF/') and name.upper().endswith(
            ('.SF', '.RSA', '.DSA', '.EC', 'MANIFEST.MF')):
        continue
    if name == 'AndroidManifest.xml':
        zout.writestr(item, mf2); continue
    if name == 'resources.arsc':
        zout.writestr(item, ar2); continue
    if name in dexes:
        data = open(os.path.join(patchdir, name.replace('.dex', '_pkg.dex')), 'rb').read()
        zout.writestr(item, data)
        replaced.append('%s(%d)' % (name, len(data)))
        continue
    zout.writestr(item, zin.read(name))
zout.close(); zin.close()
print('[2] repacked %s' % dst)
print('    replaced: %s' % ', '.join(replaced))
print('    dropped old META-INF signature')
PY

zipalign -f -p 4 "$UNSIGNED" "$ALIGNED"
apksigner sign --ks "$KS" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$FINALAPK" "$ALIGNED" 2>&1 | tail -3
rm -f "$UNSIGNED" "$ALIGNED"
echo "[3] signed -> $FINALAPK"
apksigner verify --print-certs -v "$FINALAPK" 2>&1 | head -8
zipalign -c -p 4 "$FINALAPK" && echo "[4] zipalign OK"

AAPT=/home/jcleng/work/mywork/zhongjian-liquor-web/node_modules/aaptjs/bin/linux/aapt
echo "[5] badging:"
"$AAPT" d badging "$FINALAPK" 2>/dev/null | grep -E "^package|^launchable-activity" | head -3
echo "[6] fix #6 spot-check (charge_station must be 充电站, gas_station 加油站):"
"$AAPT" dump --values resources "$FINALAPK" 2>/dev/null \
  | awk '/string\/(charge_station|gas_station): t=/{n=$2; next} n!=""&&/string8/{gsub(/^ +/,""); print "    "n" = "$0; n=""}' \
  | sort -u
ls -la "$FINALAPK"
sha256sum "$FINALAPK"
