#!/bin/bash
# Build the Firecracker sandbox assets on the sandbox host (onyx-Linux).
# Assets expected in ~/lr-sandbox/assets: firecracker.tgz, vmlinux,
# cpython.tgz (standalone CPython), busybox (static). Produces in
# ~/lr-sandbox: bin/firecracker, rootfs.ext4, and the repo copy used by
# the host driver.
set -euo pipefail
SB="$HOME/lr-sandbox"
ASSETS="$SB/assets"
REPO_SRC="${1:?usage: build_sandbox.sh <path-to-living-replay-repo>}"

mkdir -p "$SB/bin" "$SB/rootfs"
if [ ! -x "$SB/bin/firecracker" ]; then
  tar xzf "$ASSETS/firecracker.tgz" -C "$SB/bin" --strip-components=1
  fc_file=$(ls "$SB/bin"/firecracker-v*-x86_64 | grep -v debug | head -1)
  mv "$fc_file" "$SB/bin/firecracker"
  chmod +x "$SB/bin/firecracker"
fi
"$SB/bin/firecracker" --version

rm -rf "$SB/rootfs"; mkdir -p "$SB/rootfs/usr/local/bin" "$SB/pybuild"
tar xzf "$ASSETS/cpython.tgz" -C "$SB/pybuild"
mv "$SB/pybuild/python" "$SB/rootfs/usr/local/python"
rmdir "$SB/pybuild"
# CPython resolves its prefix through symlinks, so a link keeps the
# install_only layout (bin + ../lib) intact.
ln -sf /usr/local/python/bin/python3.12 "$SB/rootfs/usr/local/bin/python3"

# glibc closure for the standalone interpreter (from the host's loader set)
PYBIN="$SB/rootfs/usr/local/python/bin/python3.12"
[ -f "$PYBIN" ] || PYBIN="$SB/rootfs/usr/local/python/bin/python3"
for lib in $(ldd "$PYBIN" | grep -oE '/[^ ]+\.so[^ ]*' | sort -u); do
  mkdir -p "$SB/rootfs$(dirname "$lib")"
  cp -L "$lib" "$SB/rootfs$lib"
done
for lib in $(ldd "$SB/rootfs/usr/local/python/lib/libpython3.12.so.1.0" 2>/dev/null | grep -oE '/[^ ]+\.so[^ ]*' | sort -u); do
  mkdir -p "$SB/rootfs$(dirname "$lib")"
  cp -L "$lib" "$SB/rootfs$lib" 2>/dev/null || true
done

# busybox + init + agent + the living_replay package
mkdir -p "$SB/rootfs/bin" "$SB/rootfs/opt"
cp "$ASSETS/busybox" "$SB/rootfs/bin/busybox"; chmod +x "$SB/rootfs/bin/busybox"
cp "$REPO_SRC/sandbox/guest_init.sh" "$SB/rootfs/init"; chmod +x "$SB/rootfs/init"
cp "$REPO_SRC/sandbox/guest_agent.py" "$SB/rootfs/opt/guest_agent.py"
cp "$REPO_SRC/sandbox/flagship_agent.py" "$SB/rootfs/opt/flagship_agent.py"
mkdir -p "$SB/rootfs/opt/living_replay"
cp "$REPO_SRC"/src/living_replay/*.py "$SB/rootfs/opt/living_replay/"
mkdir -p "$SB/rootfs"/{proc,sys,dev,data,root,tmp,etc}

rm -f "$SB/rootfs.ext4"
truncate -s 320M "$SB/rootfs.ext4"
mkfs.ext4 -q -d "$SB/rootfs" -F "$SB/rootfs.ext4"
echo "rootfs built: $SB/rootfs.ext4"
ls -la "$SB"
