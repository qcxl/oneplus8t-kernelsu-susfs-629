#!/usr/bin/env python3
"""Inject ksud binary into boot.img ramdisk.
Usage: python3 inject-ksud-ramdisk.py <ksud_binary> <stock_boot.img> <output_ramdisk.lz4>
"""
import struct, os, subprocess, shutil, sys

def main():
    if len(sys.argv) < 4:
        print("Usage: inject-ksud-ramdisk.py <ksud_binary> <stock_boot.img> <output_ramdisk.lz4>")
        sys.exit(1)

    ksud_bin = sys.argv[1]
    boot_img = sys.argv[2]
    output = sys.argv[3]

    if not os.path.exists(ksud_bin):
        print(f"ERROR: ksud binary not found at {ksud_bin}")
        sys.exit(1)

    # Parse boot.img header
    with open(boot_img, 'rb') as f:
        hdr = f.read(4096)
    kernel_size = struct.unpack('<I', hdr[8:12])[0]
    ramdisk_size = struct.unpack('<I', hdr[16:20])[0]
    page_size = struct.unpack('<I', hdr[36:40])[0]
    kernel_end = page_size + kernel_size
    ramdisk_start = ((kernel_end + page_size - 1) // page_size) * page_size

    print(f"Kernel size: {kernel_size}")
    print(f"Ramdisk size: {ramdisk_size} at offset {ramdisk_start}")

    # Read ramdisk
    f = open(boot_img, 'rb')
    f.seek(ramdisk_start)
    rd = f.read(ramdisk_size)
    f.close()

    # Save compressed ramdisk
    ramdisk_lz4 = '/tmp/ramdisk-orig.lz4'
    with open(ramdisk_lz4, 'wb') as rf:
        rf.write(rd)

    # Decompress
    ramdisk_raw = '/tmp/ramdisk-orig.raw'
    subprocess.run(['lz4', '-d', ramdisk_lz4, ramdisk_raw], check=True)
    print(f"Decompressed: {os.path.getsize(ramdisk_raw)} bytes")

    # Extract cpio
    extract_dir = '/tmp/ramdisk-extract'
    if os.path.exists(extract_dir):
        subprocess.run(['rm', '-rf', extract_dir])
    os.makedirs(extract_dir)
    os.chdir(extract_dir)
    subprocess.run(['cpio', '-idm', '-F', ramdisk_raw], check=True)
    orig_count = len(os.listdir(extract_dir))
    print(f"Extracted {orig_count} entries")

    # Create /sbin/ and add ksud
    os.makedirs('sbin', exist_ok=True)
    shutil.copy2(ksud_bin, 'sbin/ksud')
    os.chmod('sbin/ksud', 0o755)
    print(f"Added sbin/ksud ({os.path.getsize('sbin/ksud')} bytes)")

    # Create su symlink -> /sbin/ksud
    if os.path.exists('sbin/su'):
        os.unlink('sbin/su')
    os.symlink('/sbin/ksud', 'sbin/su')
    print("Added sbin/su -> /sbin/ksud symlink")

    # Repack cpio
    ramdisk_new_cpio = '/tmp/ramdisk-new.cpio'
    subprocess.run(['sh', '-c', f'find . | cpio -o -H newc > {ramdisk_new_cpio}'], check=True)
    print(f"Repacked cpio: {os.path.getsize(ramdisk_new_cpio)} bytes")

    # Re-compress with lz4
    subprocess.run(['lz4', '-f', ramdisk_new_cpio, output], check=True)
    new_size = os.path.getsize(output)
    print(f"Output ramdisk: {new_size} bytes ({new_size/1024/1024:.1f} MB)")

if __name__ == '__main__':
    main()
