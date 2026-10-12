#!/bin/bash
# Deterministic A/B for the 收藏夹 sync-callback crash (fix #5).
#
# Trigger (verified):  设置 (bottom bar) -> 我的 tab -> 收藏夹
#   That opens UserFavoritesFragment (k.e.v.j.f.f) / UserFavoritesPresenter,
#   whose initData() starts a sync; the native GBL sync-end callback then runs
#   v0() -> TextView.setText() on "bl_thd_pool_worker" -> crash.
#
# Usage: scripts/ab_favorites_crash.sh <apk> <label>
set -uo pipefail
ADB=${ADB:-/opt/rea-tools/platform-tools/adb}
export ANDROID_SERIAL=${ANDROID_SERIAL:-'adb-c8f97a5-MDclle (2)._adb-tls-connect._tcp'}
APK=$1; LABEL=$2
LOG=/tmp/ab-fav-$LABEL.log
HERE=$(dirname "$0")

echo "### [$LABEL] installing $APK"
$ADB install -r -d "$APK" 2>&1 | tail -1
$ADB logcat -c 2>/dev/null
$ADB logcat -v time > "$LOG" 2>&1 &
LOGPID=$!
sleep 2

bash "$HERE/goto_favorites.sh" >/tmp/ab-fav-$LABEL-nav.log 2>&1
sleep 8
kill $LOGPID 2>/dev/null; wait $LOGPID 2>/dev/null

PID=$($ADB shell pidof com.autonavi.amapautolite | tr -d '\r')
WRONG=$(grep -ac 'CalledFromWrongThread' "$LOG")
HMI=$(grep -ac 'HMI callback exception' "$LOG")
FATAL=$(grep -ac 'FATAL EXCEPTION' "$LOG")
echo "=================================================="
echo "[$LABEL] apk   : $(basename "$APK")"
echo "[$LABEL] alive : ${PID:-<dead>}"
echo "[$LABEL] CalledFromWrongThread : $WRONG"
echo "[$LABEL] HMI callback exception: $HMI"
echo "[$LABEL] FATAL EXCEPTION       : $FATAL"
if [ "$WRONG" -gt 0 ]; then echo "[$LABEL] => CRASHED"; else echo "[$LABEL] => NO CRASH"; fi
grep -a 'WZWFAV' "$LOG" | head -5
