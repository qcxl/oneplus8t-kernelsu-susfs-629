#!/bin/bash
set -euo pipefail

ROOT="/build"
NPROC="${NPROC:-$(nproc --all)}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

cd "$ROOT"

# Verify clang
log_info "Using system clang-14:"
clang --version | head -1

# Step 1: Apply kernel patches
cd "$ROOT/kernel"
log_info "Applying patches..."
patch -p1 --forward --fuzz=3 < "$ROOT/kernel-patches/fix_strnstr_msm_drv.patch" || true
# fix_dup_techpack_only_dups partially applied already (msm_atomic/msm_fb lines already removed)
# Skip it - techpack display duplicates are handled
# Patch VDSO Makefile for clang compatibility (-g0 disables debug .loc, -no-integrated-as uses GNU as)
patch -p1 --forward < "$ROOT/kernel-patches/fix_vdso_clang.patch" || true

# Step 2: Configure kernel
log_info "Configuring kernel..."
export ARCH=arm64

# LLVM_IAS=1: Use clang integrated assembler (handles DWARF 5 .loc)
# VDSO uses -no-integrated-as (applied via fix_vdso_clang.patch)
MAKE_ARGS="O=out ARCH=arm64 LLVM_IAS=1 \
    CC=clang LD=ld.lld \
    CLANG_TRIPLE=aarch64-linux-gnu- CROSS_COMPILE=aarch64-linux-gnu- \
    CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
    CROSS_COMPILE_COMPAT=arm-linux-gnueabi-"

make $MAKE_ARGS vendor/kona-perf_defconfig

# Copy device config as base, merge debug overlay, then resolve
cp "$ROOT/kernel-patches/ksu.config.pure" out/.config

# Merge debug config (pstore/ramoops + verbose logging + missing options)
if [ -f "$ROOT/kernel-patches/debug.config" ]; then
    scripts/kconfig/merge_config.sh -m -O out \
        out/.config "$ROOT/kernel-patches/debug.config" 2>&1
fi

make $MAKE_ARGS olddefconfig

log_info "Config ready"

# Step 3: Build kernel
log_info "Building kernel with -j${NPROC}..."
make -j"$NPROC" $MAKE_ARGS 2>&1 | tee "$ROOT/build.log"

# Step 4: Verify
cd "$ROOT/kernel"
if [ -f out/arch/arm64/boot/Image ]; then
    log_info "Build successful!"
    ls -lh out/arch/arm64/boot/Image
    if [ ! -f out/arch/arm64/boot/Image.gz ]; then
        log_info "Creating Image.gz..."
        gzip -c out/arch/arm64/boot/Image > out/arch/arm64/boot/Image.gz
    fi
    ls -lh out/arch/arm64/boot/Image.gz
    log_info "Output: $ROOT/kernel/out/arch/arm64/boot/Image.gz"
else
    log_error "Build failed: Image not found"
    tail -200 "$ROOT/build.log"
    exit 1
fi
