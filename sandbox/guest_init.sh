#!/bin/busybox sh
# Guest init for the Living Replay sandbox microVM.
/bin/busybox --install -s /bin
export PATH=/bin:/usr/local/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts 2>/dev/null
[ -e /dev/vdb ] || mknod /dev/vdb b 254 16
mkdir -p /data /opt
mount -t ext4 /dev/vdb /data || echo "LR-ERROR data drive mount failed"
# The model shim serves on guest loopback :8642 and Hermes calls it at
# 127.0.0.1. A fresh kernel boots with lo DOWN and nothing else in this
# init configures networking, so every guest-local HTTP call failed
# with a connection error while vsock (which needs no interface) kept
# working. Bring lo up before any agent starts.
/bin/ip link set lo up 2>/dev/null || /bin/ifconfig lo up
export PYTHONDONTWRITEBYTECODE=1
export HOME=/root
if [ -f /data/RUN_LIVE ]; then
  exec /usr/local/bin/python3 /opt/live_agent.py
fi
if [ -f /data/RUN_HERMES ]; then
  exec /usr/local/bin/python3 /opt/hermes_agent.py
fi
if [ -f /data/RUN_FLAGSHIP ]; then
  exec /usr/local/bin/python3 /opt/flagship_agent.py
fi
exec /usr/local/bin/python3 /opt/guest_agent.py
