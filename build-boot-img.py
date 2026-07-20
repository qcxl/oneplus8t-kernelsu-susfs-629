#!/usr/bin/env python3
"""
Create custom boot.img by replacing kernel in original boot.img.
Usage:
  python3 build-boot-img.py <original_boot.img> <new_kernel> <output_boot.img>
    [--append-cmdline "extra kernel cmdline flags"]
    [--ramdisk-file <prebuilt_ramdisk>]
"""

import struct
import sys
import argparse

def make_boot_img(original_boot, new_kernel, output_boot, extra_cmdline="", ramdisk_file=""):
    with open(original_boot, 'rb') as f:
        original_data = f.read()

    with open(new_kernel, 'rb') as f:
        new_kernel_data = f.read()

    PAGE_SIZE = 4096

    # Copy entire first page (header + cmdline), not just 64 bytes
    header_data = bytearray(original_data[:PAGE_SIZE])
    magic = header_data[0:4]
    assert magic == b'ANDR', f"Invalid boot image magic: {magic}"

    # Parse header
    kernel_size_orig = struct.unpack('<I', header_data[8:12])[0]
    ramdisk_size = struct.unpack('<I', header_data[16:20])[0]
    second_size = struct.unpack('<I', header_data[24:28])[0]
    page_size = struct.unpack('<I', header_data[36:40])[0]

    # Save original ramdisk position BEFORE kernel_size_orig may change
    orig_kernel_size = kernel_size_orig

    print(f"Original kernel size: {kernel_size_orig} (0x{kernel_size_orig:x})")
    print(f"New kernel size: {len(new_kernel_data)} (0x{len(new_kernel_data):x})")
    print(f"Ramdisk size: {ramdisk_size} (0x{ramdisk_size:x})")
    print(f"Second size: {second_size}")
    print(f"Page size: {page_size}")

    # If new kernel is larger than original, update kernel size in header
    if len(new_kernel_data) > kernel_size_orig:
        print(f"\nWARNING: New kernel ({len(new_kernel_data)}) is larger than original ({kernel_size_orig})")
        kernel_size_orig = len(new_kernel_data)
        struct.pack_into('<I', header_data, 8, kernel_size_orig)

    # Pad new kernel to "original" size (now updated if larger)
    new_kernel_padded = new_kernel_data + b'\x00' * (kernel_size_orig - len(new_kernel_data))

    # Calculate offsets (for NEW boot.img layout, using updated kernel_size_orig)
    kernel_start = page_size
    kernel_end = kernel_start + kernel_size_orig

    # Ramdisk starts after kernel, aligned to page boundary
    ramdisk_start = ((kernel_start + kernel_size_orig + page_size - 1) // page_size) * page_size

    # Second starts after ramdisk
    second_start = ((ramdisk_start + ramdisk_size + page_size - 1) // page_size) * page_size

    print(f"\nLayout:")
    print(f"  Header: 0x0 - 0x{kernel_start:x}")
    print(f"  Kernel: 0x{kernel_start:x} - 0x{kernel_end:x}")
    print(f"  Ramdisk: 0x{ramdisk_start:x} - 0x{ramdisk_start + ramdisk_size:x}")
    print(f"  Second: 0x{second_start:x}")

    # ---- Read ramdisk from ORIGINAL boot.img (using orig_kernel_size) ----
    if ramdisk_file:
        with open(ramdisk_file, 'rb') as rf:
            ramdisk_from_original = rf.read()
        ramdisk_size = len(ramdisk_from_original)
        print(f"Ramdisk from custom file: {ramdisk_file} ({ramdisk_size} bytes)")
        struct.pack_into('<I', header_data, 16, ramdisk_size)
    else:
        orig_ramdisk_start = ((page_size + orig_kernel_size + page_size - 1) // page_size) * page_size
        ramdisk_from_original = original_data[orig_ramdisk_start:orig_ramdisk_start + ramdisk_size]
        print(f"  Ramdisk read from original at: 0x{orig_ramdisk_start:x}")

    # ---- Read DTB from ORIGINAL boot.img ----
    DTB_MAGIC = b'\xd0\x0d\xfe\xed'
    dtb_start = original_data.find(DTB_MAGIC)
    dtb_size = 0
    dtb_data = b''
    if dtb_start > 0 and dtb_start + 8 <= len(original_data):
        dtb_size = struct.unpack('>I', original_data[dtb_start + 4:dtb_start + 8])[0]
        if dtb_start + dtb_size <= len(original_data):
            dtb_data = original_data[dtb_start:dtb_start + dtb_size]
            print(f"DTB: {dtb_size} bytes at 0x{dtb_start:x}")

    # ---- Append extra cmdline if specified ----
    if extra_cmdline:
        cmdline_start = 0x40
        cmdline_max = 0x200  # 512 bytes for v0/v1 header, might be larger for v2/v3
        old_cmdline = bytes(header_data[cmdline_start:cmdline_start + cmdline_max])
        old_cmdline_str = old_cmdline.split(b'\x00')[0].decode('ascii', errors='replace').strip()
        new_cmdline_str = old_cmdline_str + ' ' + extra_cmdline
        new_cmdline_bytes = new_cmdline_str.encode('ascii')
        if len(new_cmdline_bytes) >= cmdline_max:
            print(f"WARNING: Cmdline too long ({len(new_cmdline_bytes)} >= {cmdline_max}), truncating")
            new_cmdline_bytes = new_cmdline_bytes[:cmdline_max - 1]
        new_cmdline_bytes = new_cmdline_bytes + b'\x00' * (cmdline_max - len(new_cmdline_bytes))
        header_data[cmdline_start:cmdline_start + cmdline_max] = new_cmdline_bytes
        print(f"Cmdline: appended '{extra_cmdline}'")
        print(f"  Full: {old_cmdline_str} {extra_cmdline}")

    # ---- Build new boot.img ----
    new_data = bytearray()

    # 1. Header + cmdline (full first page)
    new_data.extend(header_data)

    # 2. Kernel
    new_data.extend(new_kernel_padded)

    # 3. Pad to ramdisk position
    new_data.extend(b'\x00' * (ramdisk_start - len(new_data)))

    # 4. Ramdisk (from original, correctly positioned)
    new_data.extend(ramdisk_from_original)

    # 5. Pad to second position
    new_data.extend(b'\x00' * (second_start - len(new_data)))

    # 6. Second stage (from original)
    if second_size > 0:
        second_from_original = original_data[second_start:second_start + second_size]
        new_data.extend(second_from_original)

    # 7. DTB (placed after ramdisk/second area)
    if len(dtb_data) > 0:
        new_dtb_start = ((ramdisk_start + ramdisk_size + page_size - 1) // page_size) * page_size
        if second_size > 0:
            new_dtb_start = ((second_start + second_size + page_size - 1) // page_size) * page_size
        new_data.extend(b'\x00' * (new_dtb_start - len(new_data)))
        new_data.extend(dtb_data)
        print(f"DTB: placed at 0x{new_dtb_start:x} ({dtb_size} bytes)")
    else:
        print("No DTB found")

    # 8. Pad to original file size
    if len(new_data) < len(original_data):
        print(f"Padding to original size: {len(original_data) - len(new_data)} bytes")
        new_data.extend(b'\x00' * (len(original_data) - len(new_data)))

    # Write output
    with open(output_boot, 'wb') as f:
        f.write(new_data)

    print(f"\nOutput: {output_boot}")
    print(f"Size: {len(new_data)} bytes (0x{len(new_data):x})")

    # Verify
    with open(output_boot, 'rb') as f:
        verify_page = f.read(PAGE_SIZE)
        verify_kernel_size = struct.unpack('<I', verify_page[8:12])[0]
        verify_ramdisk_size = struct.unpack('<I', verify_page[16:20])[0]
        verify_cmdline = verify_page[0x40:0x240].decode('ascii', errors='replace').rstrip('\x00').strip()
        print(f"\nVerification:")
        print(f"  Kernel size in header: {verify_kernel_size}")
        print(f"  Ramdisk size in header: {verify_ramdisk_size}")
        print(f"  Cmdline ({len(verify_cmdline)} chars): {verify_cmdline[:150]}...")
        with open(output_boot, 'rb') as f2:
            dtb_check = f2.read().find(b'\xd0\x0d\xfe\xed')
        print(f"  DTB magic found at: 0x{dtb_check:x}" if dtb_check >= 0 else "  WARNING: DTB magic NOT found!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create custom boot.img by replacing kernel')
    parser.add_argument('original_boot', help='Original boot.img file')
    parser.add_argument('new_kernel', help='New kernel Image file')
    parser.add_argument('output_boot', help='Output boot.img file')
    parser.add_argument('--append-cmdline', help='Extra kernel cmdline flags to append (e.g. "initcall_debug log_buf_len=16M")')
    parser.add_argument('--ramdisk-file', help='Pre-built LZ4-compressed ramdisk file (overrides original)')
    args = parser.parse_args()

    make_boot_img(args.original_boot, args.new_kernel, args.output_boot, args.append_cmdline or "", args.ramdisk_file or "")
