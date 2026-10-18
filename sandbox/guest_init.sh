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
# Entropy: these guests have no working hardware RNG path (Firecracker's
# entropy device does not surface in this kernel, verified 2026-10-16),
# and a fresh boot can stall indefinitely at the agent's first blocking
# getrandom while the kernel CRNG waits on interrupt jitter (three
# stalled boots, serial ending at the python urandom read, vs healthy
# boots initializing CRNG at ~170s). The host writes fresh random bytes
# to /data/seed.bin; credit them to the pool here so CRNG initializes
# before any agent starts.
if [ -f /data/seed.bin ]; then
  /usr/local/bin/python3 -c "import fcntl,struct; s=open('/data/seed.bin','rb').read(); f=open('/dev/urandom','wb',buffering=0); fcntl.ioctl(f,0x40085203,struct.pack('ii',len(s)*8,len(s))+s); f.close()" 2>/dev/null || echo "LR-WARN entropy seed failed"
fi
export PYTHONDONTWRITEBYTECODE=1
export HOME=/root
if [ -f /data/RUN_RESUME ]; then
  exec /usr/local/bin/python3 /opt/live_resume_agent.py
fi
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
