#!/bin/bash
# Build 4 rootfs: the Build 2/3 rootfs PLUS a real hermes-agent install
# and its sandboxed home. Produces ~/lr-sandbox/rootfs-hermes.ext4.
# Run AFTER build_sandbox.sh (needs the same assets + extracted python).
set -euo pipefail
SB="$HOME/lr-sandbox"
REPO_SRC="${1:?usage: build_rootfs_hermes.sh <path-to-living-replay-repo>}"

bash "$REPO_SRC/sandbox/build_sandbox.sh" "$REPO_SRC"

# Install hermes-agent into the guest python (host runs the same
# interpreter build; wheels land in the rootfs tree).
PY="$SB/rootfs/usr/local/python/bin/python3"
"$PY" -m pip install -q --no-cache-dir hermes-agent
ln -sf /usr/local/python/bin/hermes "$SB/rootfs/usr/local/bin/hermes"
# pip wrote entry-point shebangs with the BUILD host's python path;
# rewrite them to the guest's interpreter path or exec fails ENOENT.
sed -i "1s|^#!.*|#!/usr/local/bin/python3|" "$SB"/rootfs/usr/local/python/bin/hermes*

# Library closure for the WHEELS, not just the interpreter: Rust-backed
# wheels (cryptography & friends) need libgcc_s/libstdc++ in the guest.
# Scan every .so in the tree, ldd it, copy what the host resolves.
find "$SB/rootfs/usr/local/python" -name "*.so*" -type f | while read -r so; do
  ldd "$so" 2>/dev/null | grep -oE '/[^ ]+\.so[^ ]*' || true
done | sort -u | while read -r lib; do
  mkdir -p "$SB/rootfs$(dirname "$lib")"
  cp -L "$lib" "$SB/rootfs$lib" 2>/dev/null || true
done

# Sandboxed Hermes home: a fresh instance pointing at the in-guest
# shim. The api_key here is a placeholder the bridge discards — the
# real key never enters the guest.
mkdir -p "$SB/rootfs/root/hermes-home"
cat > "$SB/rootfs/root/hermes-home/config.yaml" <<'YAML'
providers:
  strata:
    base_url: http://127.0.0.1:8642/v1
    api_key: lr-guest-placeholder
    model: qwen3.8-flash-next
model:
  provider: strata
  name: qwen3.8-flash-next
YAML

# Hermes's environment layer wraps shell commands with `builtin cd`,
# which busybox sh cannot run ("builtin: not found") - every guest file
# and terminal operation failed on it. Ship real bash + library closure.
cp -L /bin/bash "$SB/rootfs/bin/bash"
ldd /bin/bash | grep -oE '/[^ ]+\.so[^ ]*' | sort -u | while read -r lib; do
  mkdir -p "$SB/rootfs$(dirname "$lib")"
  cp -L "$lib" "$SB/rootfs$lib"
done

cp "$REPO_SRC/sandbox/model_shim.py" "$SB/rootfs/opt/model_shim.py"
cp "$REPO_SRC/sandbox/guest_init.sh" "$SB/rootfs/init" 2>/dev/null || true
cp "$REPO_SRC/sandbox/hermes_agent.py" "$SB/rootfs/opt/hermes_agent.py"
cp "$REPO_SRC/sandbox/live_agent.py" "$SB/rootfs/opt/live_agent.py"
cp "$REPO_SRC/sandbox/live_resume_agent.py" "$SB/rootfs/opt/live_resume_agent.py"

rm -f "$SB/rootfs-hermes.ext4"
truncate -s 1200M "$SB/rootfs-hermes.ext4"
mkfs.ext4 -q -d "$SB/rootfs" -F "$SB/rootfs-hermes.ext4"
echo "hermes rootfs built: $SB/rootfs-hermes.ext4"
du -sh "$SB/rootfs/usr/local/python/lib/python3.12/site-packages" | tail -1
