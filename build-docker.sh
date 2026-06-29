#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
IMG_NAME="kebab-kernel-builder"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Build image
docker build -t "$IMG_NAME" -f "$ROOT/Dockerfile.builder" "$ROOT" > /dev/null

# Volumes
CCACHE_VOL="${IMG_NAME}-ccache"
OUTPUT_VOL="${IMG_NAME}-output"
docker volume create "$CCACHE_VOL" 2>/dev/null || true
docker volume create "$OUTPUT_VOL" 2>/dev/null || true

# Ensure correct commit
cd "$ROOT/kernel"
git checkout 5dea892fe7e4 2>/dev/null || true
cd "$ROOT"

NPROC=$(sysctl -n hw.logicalcpu 2>/dev/null || echo 2)
[ "$NPROC" -gt 3 ] && NPROC=3

log_info "Building kernel (git archive -> container ext4, bypassing macOS FS corruption)..."
log_info "CPU cores: $NPROC"

# git archive reads from git objects directly, bypassing case-insensitive FS corruption
# Patch files are small and don't have case issues, so volume mount is safe
docker run --rm -i \
    -v "$ROOT/kernel-patches:/build/patches:ro" \
    -v "$CCACHE_VOL:/ccache" \
    -v "$OUTPUT_VOL:/build/kernel/out" \
    -e NPROC="$NPROC" \
    "$IMG_NAME" \
    bash -c '
set -euo pipefail
cd /build

# Receive kernel source from git archive on stdin
echo "=== Extracting kernel source ==="
tar -xf - 2>&1

cd /build/kernel

echo "=== Applying patches ==="
patch -p1 --forward --fuzz=3 < /build/patches/fix_strnstr_msm_drv.patch 2>/dev/null || true
patch -p1 --forward < /build/patches/fix_vdso_clang.patch 2>/dev/null || true

echo "=== Configuring ==="
export ARCH=arm64
MAKE_ARGS="O=out ARCH=arm64 LLVM_IAS=1 \
    CC=clang LD=ld.lld \
    CLANG_TRIPLE=aarch64-linux-gnu- CROSS_COMPILE=aarch64-linux-gnu- \
    CROSS_COMPILE_ARM32=arm-linux-gnueabi-"

make $MAKE_ARGS vendor/kona-perf_defconfig 2>&1
cp /build/patches/ksu.config.pure out/.config
make $MAKE_ARGS olddefconfig 2>&1

echo "=== Building kernel ==="
make -j${NPROC} $MAKE_ARGS 2>&1 | tee /build/build.log

echo "=== Result ==="
ls -lh out/arch/arm64/boot/Image 2>/dev/null && echo "SUCCESS" || echo "FAILED"
' < <(cd "$ROOT/kernel" && git archive --format=tar 5dea892fe7e4) 2>&1 | \
    tee >(grep -q "SUCCESS" && echo "BUILD OK" || true)

echo "=== Copying build.log ==="
docker run --rm -v "$OUTPUT_VOL:/out" alpine cp /out/../build.log /tmp/ 2>/dev/null || true
