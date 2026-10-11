#!/bin/bash
# Patch classes9.dex: neutralize the injected MainActivity.mcFixDisplay() hack.
# Rationale: mcFixDisplay() forcibly moves the task back to display 0 (or relaunches
# MainActivity with NEW_TASK|CLEAR_TASK when that reflection call fails). BYD split
# screen runs the app on a non-zero display, so this injected code yanks the app out
# of split screen / restarts it -> observed as a crash (闪退).
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
APKTOOL=/opt/rea-tools/apktool.jar
BASE=/home/jcleng/work/mywork/revert_amap/.work
W=$BASE/patch
SRC=$BASE/dex9/classes9.dex

rm -rf "$W"
mkdir -p "$W"
cd "$W"
cp "$SRC" classes.dex
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile('in.apk', 'w', zipfile.ZIP_DEFLATED)
z.write('classes.dex', 'classes.dex')
z.close()
PY
java -Xmx4g -jar "$APKTOOL" d -f -o smali_out in.apk >/dev/null
echo "[1] baksmali: $(find smali_out -name '*.smali' | wc -l) smali files"

python3 - <<'PY'
p = 'smali_out/smali/com/byd/automap/activity/MainActivity.smali'
s = open(p, encoding='utf-8').read()
old = """.method private mcFixDisplay()Z
    .locals 7

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;"""
new = """.method private mcFixDisplay()Z
    .locals 7

    const/4 v0, 0x0

    return v0

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;"""
n = s.count(old)
assert n == 1, f"anchor count = {n}"
open(p, 'w', encoding='utf-8').write(s.replace(old, new, 1))
print("[2] patched mcFixDisplay -> always return false")
PY

java -Xmx4g -jar "$APKTOOL" b -o patched.apk smali_out >/dev/null
python3 - <<'PY'
import zipfile, hashlib
d = zipfile.ZipFile('patched.apk').read('classes.dex')
open('classes9_patched.dex', 'wb').write(d)
print("[3] classes9_patched.dex:", len(d), "bytes")
print("    sha256", hashlib.sha256(d).hexdigest())
PY
