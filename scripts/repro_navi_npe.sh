#!/bin/bash
# Reproduce the NaviView split-screen NPE deterministically on a phone (no car needed).
#
# Chain that triggers it:
#   launch app -> enter split screen (isInMultiWindowMode==true, displayId stays 0)
#   -> tap 查找目的地 -> type "wanda" -> tap the first POI -> tap 导航
#   -> NaviFragment is created while in multi-window
#   -> NaviViewManager picks res/layout/fragment_auto_navi_half (isPlatformUI()==false)
#   -> that layout has no R.id.lane_location
#   -> NaviView.Dd() does this.j5.setOnClickListener(...) on null -> NPE -> 闪退
#
# Usage: ./repro_navi_npe.sh <apk|->   # "-" = keep whatever is installed
set -uo pipefail
ADB=${ADB:-/opt/rea-tools/platform-tools/adb}
PKG=${PKG:-com.autonavi.amapautolite}
ACT=$PKG/com.byd.automap.activity.MainActivity
OUT=${OUT:-.work/logs}
LOGF=$OUT/$(basename "${2:-$1}" .apk)-navinpe.log

apk=${1:--}
mkdir -p "$OUT"
adb() { "$ADB" "$@"; }
tap() { adb shell input tap "$1" "$2"; sleep "${3:-2}"; }

if [ "$apk" != "-" ]; then
  echo "[*] installing $apk"
  adb uninstall $PKG >/dev/null 2>&1
  adb install -r "$apk" 2>&1 | tail -1
fi

adb shell "wm shell splitscreen exitSplitScreen 0" >/dev/null 2>&1
adb shell "settings put global overlay_display_devices 'null'" >/dev/null 2>&1
adb shell "am force-stop $PKG" >/dev/null 2>&1
adb logcat -c
sleep 1

echo "[*] 1/6 launch fullscreen"
adb shell "am start -n $ACT" >/dev/null 2>&1
sleep 8

echo "[*] 2/6 enter split screen"
TID=$(adb shell "dumpsys activity activities" 2>/dev/null \
      | grep -oE "#[0-9]+ type=standard A=[0-9]+:$PKG" | head -1 | grep -oE '[0-9]+' | head -1)
echo "    taskId=$TID"
adb shell "wm shell splitscreen moveToSideStage $TID 0" >/dev/null 2>&1
sleep 6

echo "[*] 3/6 open search"
tap 456 266 4

echo "[*] 4/6 type query (ASCII; the car app falls back to fuzzy POI search)"
tap 800 266 2
adb shell input text "wanda"
sleep 4

echo "[*] 5/6 tap first POI result"
tap 618 494 8

echo "[*] 6/6 tap 导航 (start navigation)"
tap 625 1106 12

adb logcat -d -v threadtime > "$LOGF" 2>/dev/null
echo "[*] wrote $LOGF ($(wc -l < "$LOGF") lines)"
echo "[*] pid=$(adb shell pidof $PKG | tr -d '\r')  (empty == process died == 闪退)"
echo "[*] stats:"
for pat in "NaviView.Dd" "FATAL EXCEPTION" "lane_location" \
           "mInSplitScreen=true" "isInMultiWindowMode:true" "loaded multiView"; do
  printf "    %-28s %s\n" "$pat" "$(grep -c "$pat" "$LOGF")"
done
echo "[*] crash frame:"
grep -A3 "FATAL EXCEPTION" "$LOGF" | grep -E "^\s+at |Exception" | head -5 | sed 's/^/    /'
