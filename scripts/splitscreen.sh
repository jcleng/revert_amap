#!/bin/bash
# Phone-side split-screen (分屏) test harness.
#
# Why: the BYD head unit has no adb access, so we reproduce the split-screen
# condition on a phone. There are two ways to get the app onto a "not the main
# display / not full screen" state:
#
#   real  -> AOSP `wm shell splitscreen moveToSideStage` (MIUI/AOSP split screen).
#            The app keeps displayId=0 but gets windowingMode=multi-window,
#            mInSplitScreen=true and isInMultiWindowMode()==true.
#   virt  -> `settings put global overlay_display_devices` creates a virtual
#            display; `am start --display N` puts the app on displayId=N.
#            This is the closest analogue of BYD split screen, where split
#            windows really are separate displays (displayId 1 / 2,
#            "fission_*", "叠加视图 #1").
#
# Usage:
#   ./splitscreen.sh real  <apk|->   # install apk if given, then split-screen it
#   ./splitscreen.sh virt  <apk|->   # virtual-display route, displayId=2
#   ./splitscreen.sh exit            # leave split screen / remove virtual display
#   ./splitscreen.sh log   <file>    # dump logcat + stats
#
set -uo pipefail
ADB=${ADB:-/opt/rea-tools/platform-tools/adb}
PKG=com.autonavi.amapauto
ACT=$PKG/com.byd.automap.activity.MainActivity
OUT=${OUT:-.work/logs}

adb() { "$ADB" "$@"; }

kill_app() { adb shell "am force-stop $PKG" >/dev/null 2>&1; }

wait_pid() {
  for _ in $(seq 1 15); do
    p=$(adb shell "pidof $PKG" | tr -d '\r')
    [ -n "$p" ] && { echo "$p"; return 0; }
    sleep 1
  done
  echo ""
}

task_id() {
  # NOTE: the uid part (A=100xx) changes on reinstall, so do not hardcode it.
  adb shell "dumpsys activity activities" 2>/dev/null \
    | grep -oE "#[0-9]+ type=standard A=[0-9]+:$PKG" | head -1 | grep -oE '[0-9]+' | head -1
}

install_apk() {
  local apk=$1
  [ "$apk" = "-" ] && return 0
  echo "[*] installing $apk"
  adb uninstall $PKG >/dev/null 2>&1
  adb install -r "$apk" 2>&1 | tail -2
}

case "${1:-}" in
  real)
    install_apk "${2:--}"
    kill_app
    adb shell "wm shell splitscreen exitSplitScreen 0" >/dev/null 2>&1
    sleep 1
    adb shell "am start -n $ACT" >/dev/null 2>&1
    sleep 6
    TID=$(task_id)
    echo "[*] taskId=$TID"
    adb shell "wm shell splitscreen moveToSideStage $TID 0" 2>&1 | head -3
    sleep 6
    echo "[*] windowingMode:"
    adb shell "dumpsys activity activities" 2>/dev/null \
      | grep -E "amapauto.*Task\{" | head -2 | sed 's/^/    /'
    echo "[*] pid=$(wait_pid)"
    ;;

  virt)
    install_apk "${2:--}"
    kill_app
    adb shell "settings put global overlay_display_devices '1280x720/213'" >/dev/null 2>&1
    sleep 3
    echo "[*] displays:"; adb shell "dumpsys display | grep -oE 'DisplayDeviceInfo\{\"[^\"]+\", uniqueId=\"[^\"]+\", [0-9]+ x [0-9]+' | head -4" 2>/dev/null | sed 's/^/    /'
    adb shell "am start --display 2 -n $ACT" >/dev/null 2>&1
    sleep 6
    echo "[*] pid=$(wait_pid)"
    ;;

  exit)
    adb shell "settings put global overlay_display_devices 'null'" >/dev/null 2>&1
    adb shell "wm shell splitscreen exitSplitScreen 0" >/dev/null 2>&1
    kill_app
    echo "[*] restored"
    ;;

  log)
    F=${2:-$OUT/ss.log}
    mkdir -p "$(dirname "$F")"
    adb logcat -d -v threadtime > "$F" 2>/dev/null
    echo "[*] wrote $F ($(wc -l < "$F") lines)"
    echo "[*] stats:"
    for pat in "mc_fix_display_relaunched" "ActivityTaskManager;->getService" \
               "moveTaskToDisplay" "FATAL EXCEPTION" "am_crash" "am_proc_died" \
               "mInSplitScreen=true" "isInMultiWindowMode :true"; do
      printf "    %-42s %s\n" "$pat" "$(grep -c "$pat" "$F")"
    done
    echo "[*] crash frames:"
    grep -A6 "FATAL EXCEPTION" "$F" | grep -E "^\s+at |Exception" | head -12 | sed 's/^/    /'
    ;;

  *)
    sed -n '2,25p' "$0"
    ;;
esac
