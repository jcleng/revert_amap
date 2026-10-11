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
# Outputs .work/patch/classes{9,22,25}_patched.dex
set -euo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
APKTOOL=/opt/rea-tools/apktool.jar
BASE=/home/jcleng/work/mywork/revert_amap/.work
W=$BASE/patch
SRC9=$BASE/dex9/classes9.dex
SRC22=$BASE/dex22/classes22.dex
SRC25=$BASE/dex25/classes25.dex

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

patch_one "$SRC9"  classes9  /home/jcleng/work/mywork/revert_amap/scripts/fix_mcFixDisplay.py     1
patch_one "$SRC22" classes22 /home/jcleng/work/mywork/revert_amap/scripts/fix_NaviView.py         2
patch_one "$SRC25" classes25 /home/jcleng/work/mywork/revert_amap/scripts/fix_DpiScaleManager.py 3

echo "[done] patched dex files in $W"
