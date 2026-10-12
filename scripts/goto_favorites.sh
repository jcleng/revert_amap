#!/bin/bash
# Navigate: home -> 设置 (bottom bar) -> 我的 tab -> 收藏夹
# Leaves the UserFavoritesFragment (k.e.v.j.f.f) on screen.
set -uo pipefail
ADB=${ADB:-/opt/rea-tools/platform-tools/adb}
export ANDROID_SERIAL=${ANDROID_SERIAL:-'adb-c8f97a5-MDclle (2)._adb-tls-connect._tcp'}
PKG=${PKG:-com.autonavi.amapautolite}
ACT=$PKG/com.byd.automap.activity.MainActivity

dump() { $ADB shell uiautomator dump /sdcard/nav.xml >/dev/null 2>&1; $ADB shell cat /sdcard/nav.xml 2>/dev/null; }

# find the centre of a node whose text matches $1
centre_of() {
  dump | python3 -c "
import sys,re
want=sys.argv[1]
s=sys.stdin.read()
for m in re.finditer(r'<node[^>]*?/?>', s):
    tag=m.group(0)
    t=re.search(r'text=\"([^\"]*)\"',tag)
    b=re.search(r'bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"',tag)
    if t and b and t.group(1)==want:
        x=(int(b.group(1))+int(b.group(3)))//2
        y=(int(b.group(2))+int(b.group(4)))//2
        print(x,y); break
" "$1"
}

$ADB shell am force-stop "$PKG"; sleep 2
$ADB shell am start -n "$ACT" >/dev/null
for i in $(seq 1 12); do
  sleep 3
  dump | grep -q 'map_main_head_container' && break
done
echo "[nav] home ready"

# bottom bar 设 置  -> use the known home layout coordinates
$ADB shell input tap 540 2598; sleep 4
dump | grep -q 'setting_tab_ll_person' || { echo "[nav] FAIL: settings page not open"; exit 1; }
echo "[nav] settings page open"

c=$(centre_of '我 的'); [ -n "$c" ] && $ADB shell input tap $c; sleep 3
c=$(centre_of '收藏夹'); [ -n "$c" ] || { echo "[nav] FAIL: 收藏夹 not found"; dump | grep -o 'text="[^"]*"' | head -30; exit 1; }
echo "[nav] tapping 收藏夹 at $c"
$ADB shell input tap $c; sleep 6

dump > /tmp/nav-final.xml
if grep -q 'slv_favorite_list' /tmp/nav-final.xml; then
  echo "[nav] OK: UserFavoritesFragment (slv_favorite_list) is open"
else
  echo "[nav] WARNING: slv_favorite_list not found; page ids:"
  grep -o 'resource-id="[^"]*"' /tmp/nav-final.xml | sort -u | head -30
fi
