#!/bin/bash
# Patch the two injected/buggy code paths found during the reverse engineering:
#
#  [1] classes9.dex  -> MainActivity.mcFixDisplay()
#      The injected BYD fix-up hack forces the task back onto display 0
#      (or, when the ActivityTaskManager reflection is denied, relaunches
#      MainActivity with NEW_TASK|CLEAR_TASK).  BYD split screen runs the app on a
#      non-zero display, so this yanks the app out of split screen / restarts it ->
#      observed as 闪退.  Patch: make it a no-op (always return false).
#
#  [2] classes22.dex -> NaviView.Dd()
#      Dd() unconditionally does  this.j5.setOnClickListener(this.X6)  while j5 is
#      findViewById(R.id.lane_location).  fragment_auto_navi_half (the layout used
#      when the platform is NOT "platformized", e.g. while isInMultiWindowMode()) has
#      no lane_location view -> NPE in NaviPresenter.onViewCreated -> crash.
#      Patch: null-guard j5 exactly like the neighbouring i5 guard.
#
#  [3] classes25.dex -> DpiScaleManager.applyImmersive()
#      The injected helper unconditionally calls
#      window.getDecorView().setSystemUiVisibility(0x1706)  (immersive-sticky:
#      HIDE_NAVIGATION|FULLSCREEN|LAYOUT_*|IMMERSIVE_STICKY) and forces
#      layoutInDisplayCutoutMode=3.  That hides BOTH the status bar and the navigation
#      bar, i.e. the app is stuck fullscreen.  The stock BYD theme does not do this
#      (resources.arsc is untouched and contains no windowFullscreen attribute).
#      Patch: skip the window manipulation, keep the VoiceXtt init that follows.
#
#  [4] classes.dex, 5, 8, 9, 11, 13, 18, 21, 22, 25 -> package rename
#      The car head unit ships a system-signed com.autonavi.amapauto, so installing
#      this build over it fails with INSTALL_FAILED_UPDATE_INCOMPATIBLE (shown by the
#      head unit as "与现有软件冲突").  Renaming the package lets it coexist as a
#      separate app.  See scripts/fix_RenamePackage.py for the KEEP list.
#
# Outputs .work/patch/classes{9,22,25}_patched.dex and, for the renamed dexes,
# .work/patch/classes{0,5,8,9,11,13,18,21,22,25}_pkg.dex
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
APKTOOL=/opt/rea-tools/apktool.jar
BASE=/home/jcleng/work/mywork/revert_amap/.work
W=$BASE/patch
SRC9=$BASE/dex9/classes9.dex
SRC22=$BASE/dex22/classes22.dex
SRC25=$BASE/dex25/classes25.dex
RENAME_FIXER=/home/jcleng/work/mywork/revert_amap/scripts/fix_RenamePackage.py

rm -rf "$W"
mkdir -p "$W"

patch_one() {
  local src="$1" outname="$2" fixer="$3" label="$4"
  local d="$W/$outname"
  mkdir -p "$d"
  cd "$d"
  cp "$src" classes.dex
  python3 - <<'PY'
import zipfile
z = zipfile.ZipFile('in.apk', 'w', zipfile.ZIP_DEFLATED)
z.write('classes.dex', 'classes.dex')
z.close()
PY
  java -Xmx4g -jar "$APKTOOL" d -f -o smali_out in.apk >/dev/null
  echo "[$label] baksmali: $(find smali_out -name '*.smali' | wc -l) smali files"
  python3 "$fixer"
  java -Xmx4g -jar "$APKTOOL" b -o patched.apk smali_out >/dev/null
  python3 - "$outname" <<'PY'
import zipfile, hashlib, sys, os
d = zipfile.ZipFile('patched.apk').read('classes.dex')
out = os.path.join('..', sys.argv[1] + '_patched.dex')
open(out, 'wb').write(d)
print(f"    -> {out}: {len(d)} bytes  sha256 {hashlib.sha256(d).hexdigest()}")
PY
  cd "$W"
}

# rename-only pass: baksmali, run fix_RenamePackage.py, smali back
patch_pkg() {
  local src="$1" outname="$2"
  local d="$W/${outname}_pkg"
  mkdir -p "$d"
  cd "$d"
  cp "$src" classes.dex
  python3 - <<'PY'
import zipfile
z = zipfile.ZipFile('in.apk', 'w', zipfile.ZIP_DEFLATED)
z.write('classes.dex', 'classes.dex')
z.close()
PY
  java -Xmx4g -jar "$APKTOOL" d -f -o smali_out in.apk >/dev/null
  python3 "$RENAME_FIXER" smali_out
  java -Xmx4g -jar "$APKTOOL" b -o patched.apk smali_out >/dev/null
  python3 - "$outname" <<'PY'
import zipfile, hashlib, sys, os
d = zipfile.ZipFile('patched.apk').read('classes.dex')
out = os.path.join('..', sys.argv[1] + '_pkg.dex')
open(out, 'wb').write(d)
print(f"    -> {out}: {len(d)} bytes  sha256 {hashlib.sha256(d).hexdigest()}")
PY
  cd "$W"
}

patch_one "$SRC9"  classes9  /home/jcleng/work/mywork/revert_amap/scripts/fix_mcFixDisplay.py     1
patch_one "$SRC22" classes22 /home/jcleng/work/mywork/revert_amap/scripts/fix_NaviView.py         2
patch_one "$SRC25" classes25 /home/jcleng/work/mywork/revert_amap/scripts/fix_DpiScaleManager.py 3

# Package rename.  Applied to the *patched* output for the three dexes that carry a
# code fix, and straight from the original for the rest, so every dex is touched once.
SRCDEX=$BASE/target.apk
for spec in "0:classes" "5:classes5" "8:classes8" "9:classes9" "11:classes11" \
            "13:classes13" "18:classes18" "21:classes21" "22:classes22" "25:classes25"; do
  idx=${spec%%:*}; name=${spec##*:}
  case "$name" in
    classes9)  src="$W/classes9_patched.dex" ;;
    classes22) src="$W/classes22_patched.dex";;
    classes25) src="$W/classes25_patched.dex";;
    *)         src="$W/${name}_orig.dex"
               [ -f "$src" ] || unzip -p "$SRCDEX" "$name.dex" > "$src" ;;
  esac
  patch_pkg "$src" "$name"
done

echo "[done] patched dex files in $W"
