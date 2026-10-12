#!/bin/bash
# Capture the split-screen crash from a wireless-debug car head unit.
# Usage:
#   bash capture.sh pair  <ip:port> <pairing-code>   # one-off pairing
#   bash capture.sh connect <ip:port>                # connect (port = debug port)
#   bash capture.sh run                              # clear log, wait, dump crash evidence
set -uo pipefail
ADB=/opt/rea-tools/platform-tools/adb
OUT=/home/jcleng/work/mywork/revert_amap/.work/logs
mkdir -p "$OUT"

case "${1:-}" in
pair)
  $ADB pair "$2" "$3" 2>&1
  ;;
connect)
  $ADB disconnect >/dev/null 2>&1
  $ADB connect "$2" 2>&1
  sleep 1; $ADB devices -l 2>&1
  ;;
run)
  echo "### 设备信息"
  $ADB shell getprop ro.product.model ro.build.version.release ro.build.version.sdk 2>&1
  $ADB shell dumpsys display 2>/dev/null | grep -E "mDisplayId|DisplayDeviceInfo|name=" | head -40 > "$OUT/displays.txt"
  echo "### 清空日志（现在去分屏复现闪退）"
  $ADB logcat -c 2>&1
  $ADB logcat -b crash -c 2>&1
  echo ">>> 请在车机上复现分屏闪退，然后按回车..."
  read -r _
  echo "### 抓取"
  $ADB logcat -d -v threadtime > "$OUT/full.log" 2>&1
  $ADB logcat -d -b crash -v threadtime > "$OUT/crash.log" 2>&1
  # crash buffer is not always reachable; fall back to grepping the main buffer
  grep -nE "FATAL EXCEPTION|AndroidRuntime|beginning of crash|McDebug|McGuard|mc_fix_display|moveTaskToDisplay" \
      "$OUT/full.log" > "$OUT/crash_markers.txt" 2>&1
  # native tombstones / dropbox
  $ADB shell ls -t /data/tombstones 2>/dev/null | head -5
  for t in $($ADB shell ls -t /data/tombstones 2>/dev/null | head -3); do
    $ADB shell "cat /data/tombstones/$t" > "$OUT/tombstone_$t.txt" 2>/dev/null
  done
  $ADB shell dumpsys dropbox --print 2>/dev/null | tail -400 > "$OUT/dropbox.txt"
  # app-specific
  $ADB shell pidof ${PKG:-com.autonavi.amapautolite} 2>&1
  echo "### 结果"
  echo "-- crash.log --";            tail -60 "$OUT/crash.log"
  echo "-- crash_markers.txt --";    cat "$OUT/crash_markers.txt"
  echo "-- displays.txt --";         cat "$OUT/displays.txt"
  echo "全部输出在 $OUT/"
  ;;
*)
  echo "usage: $0 {pair <ip:port> <code> | connect <ip:port> | run}"; exit 1;;
esac
