#!/bin/bash
# Persistent JADX TCP query server manager (start/stop/status).
set -u
cd /home/jcleng/work/mywork/revert_amap
source .work/env.sh
JX=.work/jx
PORT=47811
mkdir -p $JX

stop() {
  for f in $JX/server.pid; do
    [ -f "$f" ] && kill "$(cat $f)" 2>/dev/null
  done
  sleep 1
  rm -f $JX/server.pid
}

start() {
  setsid nohup java -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 -Xmx5120m \
    -cp /opt/rea-tools/jadx-headless-mcp-0.7.1-all.jar:/opt/rea-tools/apiprobe \
    JadxServer "$APK" $PORT 4 > $JX/out 2> $JX/err &
  echo $! > $JX/server.pid
  echo "started server=$(cat $JX/server.pid) port=$PORT"
  for i in $(seq 1 180); do
    grep -q "^LISTENING" $JX/err 2>/dev/null && { echo "READY ($(grep '^LOADED' $JX/err))"; return 0; }
    sleep 1
  done
  echo "NOT READY after 180s"; tail -3 $JX/err
}

status() {
  if [ -f "$JX/server.pid" ] && kill -0 "$(cat $JX/server.pid)" 2>/dev/null; then
    echo "server alive pid=$(cat $JX/server.pid)"
  else
    echo "server DEAD"
  fi
  python3 .work/jxq.py PING 2>&1 | head -3
}

case "${1:-start}" in
  start) stop; start ;;
  stop) stop ;;
  status) status ;;
esac
