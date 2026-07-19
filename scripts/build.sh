#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
KERNEL_REPO="https://github.com/LineageOS/android_kernel_oneplus_sm8250.git"
KERNEL_BRANCH="lineage-20"
KERNELSU_VERSION="builtin"
SUSFS_BRANCH="kernel-4.19"
CLANG_VERSION="r416183b"
DEVICE="kebab"
OUTPUT_DIR="$PROJECT_ROOT/output"
ARTIFACT_NAME="kebab-kernelsu-susfs-a13-4.19"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Step 1: Clone kernel source
log_info "Cloning kernel source..."
if [ ! -d "kernel" ]; then
    git clone "$KERNEL_REPO" kernel
fi
cd kernel
git checkout "$KERNEL_BRANCH"
git pull origin "$KERNEL_BRANCH"

# Step 2: Apply KernelSU-Next patch
log_info "Applying KernelSU-Next patch..."
curl -LSs "https://raw.githubusercontent.com/rifsxd/KernelSU-Next/legacy/kernel/setup.sh" \
  | bash -s "$KERNELSU_VERSION"

# Step 3: Apply SUSFS patch
log_info "Applying SUSFS patch..."
git clone -b "$SUSFS_BRANCH" https://gitlab.com/simonpunk/susfs4ksu.git susfs
cp susfs/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch KernelSU/
cp susfs/kernel_patches/50_add_susfs_in_kernel-4.19.patch .
cp susfs/kernel_patches/fs/susfs.c fs/
cp susfs/kernel_patches/include/linux/susfs.h include/linux/
cp susfs/kernel_patches/include/linux/sus_su.h include/linux/
cp susfs/kernel_patches/kernelsu/sus_su.c kernelsu/
patch -p1 < KernelSU/10_enable_susfs_for_ksu.patch
patch -p1 < 50_add_susfs_in_kernel-4.19.patch

# Step 4: Configure kernel
log_info "Configuring kernel..."
make ARCH=arm64 LLVM=1 LLVM_IAS=1 \
    CLANG_PREBUILT_BIN="prebuilts-master/clang/host/linux-x86/clang-${CLANG_VERSION}/bin" \
    CROSS_COMPILE=aarch64-linux-gnu- \
    vendor/kona-perf_defconfig

# Merge SUSFS config
./scripts/kconfig/merge_config.sh -m -O .config .config "$PROJECT_ROOT/kernel-patches/ksu.config"
make ARCH=arm64 LLVM=1 LLVM_IAS=1 \
    CLANG_PREBUILT_BIN="prebuilts-master/clang/host/linux-x86/clang-${CLANG_VERSION}/bin" \
    CROSS_COMPILE=aarch64-linux-gnu- \
    olddefconfig

# Step 5: Fix compilation (preserve all drivers)
log_info "Fixing compilation flags..."
# Remove -Werror to allow warnings (DO NOT delete any source files)
find . -name "Makefile" -exec sed -i 's/-Werror//g' {} +

# Add susfs_stubs if needed
if [ -f "$PROJECT_ROOT/kernel-patches/susfs_stubs.c" ]; then
    cp "$PROJECT_ROOT/kernel-patches/susfs_stubs.c" fs/
    echo 'obj-m += susfs_stubs.o' >> fs/Makefile || true
fi

# Step 6: Compile kernel
log_info "Compiling kernel..."
make ARCH=arm64 LLVM=1 LLVM_IAS=1 \
    CLANG_PREBUILT_BIN="prebuilts-master/clang/host/linux-x86/clang-${CLANG_VERSION}/bin" \
    CROSS_COMPILE=aarch64-linux-gnu- \
    -j$(nproc) 2>&1 | tee build.log

# Step 7: Check compilation result
if [ ! -f arch/arm64/boot/Image.gz ]; then
    log_error "Compilation failed: Image.gz not found"
    cat build.log | tail -100
    exit 1
fi
log_info "Compilation successful"
ls -lh arch/arm64/boot/Image.gz

# Step 8: Package boot.img
log_info "Packaging boot.img..."
ORIGINAL_BOOT="/Users/weifeng/Downloads/OnePlus8T/lineage-20.0-20240209-nightly-kebab-signed/boot.img"

if [ ! -f "$ORIGINAL_BOOT" ]; then
    log_error "Original boot.img not found at $ORIGINAL_BOOT"
    exit 1
fi

cd "$PROJECT_ROOT"
cp kernel/arch/arm64/boot/Image.gz Image.gz

# Use magiskboot to repack
if [ ! -f tools/magiskboot ]; then
    log_error "magiskboot not found in tools/"
    exit 1
fi

tools/magiskboot unpack boot_unpack
cp Image.gz boot_unpack/kernel
cd boot_unpack
../tools/magiskboot repack ../kernel/arch/arm64/boot/Image.gz ../"${ARTIFACT_NAME}.zip"
cd ..

# Verify output
if [ ! -f "${ARTIFACT_NAME}.zip" ]; then
    log_error "Packaging failed: ${ARTIFACT_NAME}.zip not found"
    exit 1
fi

mv "${ARTIFACT_NAME}.zip" "$OUTPUT_DIR/"
log_info "Output: $OUTPUT_DIR/${ARTIFACT_NAME}.zip"
ls -lh "$OUTPUT_DIR/${ARTIFACT_NAME}.zip"

log_info "Build complete!"
