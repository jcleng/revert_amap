#!/bin/bash
# Start the persistent JADX query server backed by a FIFO.
set -u
cd /home/jcleng/work/mywork/revert_amap
source .work/env.sh
mkdir -p .work/jx
rm -f .work/jx/in .work/jx/out .work/jx/err
mkfifo .work/jx/in
touch .work/jx/out

# Keep the FIFO write end open so the server does not see EOF between requests.
nohup bash -c 'exec 3>.work/jx/in; sleep 100000' >/dev/null 2>&1 &
echo $! > .work/jx/fifo.pid

nohup java -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 -Xmx5120m \
  -cp /opt/rea-tools/jadx-headless-mcp-0.7.1-all.jar:/opt/rea-tools/apiprobe \
  JadxServer "$APK" 4 < .work/jx/in > .work/jx/out 2> .work/jx/err &
echo $! > .work/jx/server.pid
echo "fifo=$(cat .work/jx/fifo.pid) server=$(cat .work/jx/server.pid)"
