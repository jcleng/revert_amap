#!/bin/bash
# Reproduce / verify the 收藏 (favorites) sync-callback crash.
#
# Crash (pre-fix):
#   FATAL EXCEPTION: main
#   java.lang.RuntimeException: HMI callback exception:ThreadId(...):
#     ViewRootImpl$CalledFromWrongThreadException  (Expected: main, Calling: bl_thd_pool_wor)
#       TextView.setText <- k.e.j.d.j0.updateViewText <- k.e.v.j.f.f.h2
#       <- UserFavoritesPresenter.v0 <- UserFavoritesPresenter$3.notify
#       <- SyncSdkModel.notify <- SyncSDKServiceObserverRouter.notify <- ...JNI...
#
# Trigger: the favorites page (UserFavoritesPresenter.initData) calls
# SyncSdkModel.startSync() when it is not already syncing.  The native GBL
# sync then reports SyncSdkEventSyncEnd(4) from its own thread pool, which
# walks into v0() -> TextView.setText() off the main thread.
#
# Usage: scripts/repro_favorites_crash.sh <label> [seconds]
set -uo pipefail
ADB=${ADB:-/opt/rea-tools/platform-tools/adb}
export ANDROID_SERIAL=${ANDROID_SERIAL:-'adb-c8f97a5-MDclle (2)._adb-tls-connect._tcp'}
PKG=${PKG:-com.autonavi.amapautolite}
ACT=$PKG/com.byd.automap.activity.MainActivity
LABEL=${1:-run}
WAIT=${2:-75}
LOG=/tmp/fav-crash-$LABEL.log

$ADB logcat -c 2>/dev/null
$ADB shell am force-stop "$PKG"
sleep 2
$ADB shell am start -n "$ACT" >/dev/null
echo "[$LABEL] launched, waiting 12s for the home page ..."
sleep 12

echo "[$LABEL] tapping 收藏 entry (924,266) ..."
$ADB shell input tap 924 266
sleep 3
$ADB shell uiautomator dump /sdcard/repro_ui.xml >/dev/null 2>&1
if $ADB shell cat /sdcard/repro_ui.xml 2>/dev/null | grep -q 'slv_search_favorite'; then
  echo "[$LABEL] favorites page is open"
else
  echo "[$LABEL] WARNING: favorites page not detected"
fi

echo "[$LABEL] capturing logcat for ${WAIT}s ..."
timeout "$WAIT" $ADB logcat -v time > "$LOG" 2>&1

PID=$($ADB shell "pidof $PKG" | tr -d '\r')
FATAL=$(grep -ac 'CalledFromWrongThread' "$LOG")
HMI=$(grep -ac 'HMI callback exception' "$LOG")
ANYF=$(grep -ac 'FATAL EXCEPTION' "$LOG")
echo "=========================================================="
echo "[$LABEL] pid after wait : ${PID:-<none>}"
echo "[$LABEL] CalledFromWrongThread : $FATAL"
echo "[$LABEL] HMI callback exception: $HMI"
echo "[$LABEL] FATAL EXCEPTION       : $ANYF"
echo "[$LABEL] log -> $LOG"
if [ "$FATAL" = "0" ] && [ -n "$PID" ]; then
  echo "[$LABEL] RESULT: PASS (no wrong-thread crash, process alive)"
else
  echo "[$LABEL] RESULT: FAIL"
  grep -a -A6 'CalledFromWrongThread' "$LOG" | head -40
fi
