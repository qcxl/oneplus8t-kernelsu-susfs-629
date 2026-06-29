#!/usr/bin/env python3
"""
Create custom boot.img by replacing kernel in original boot.img.
Original boot.img structure:
- Header: 0x1000 (4096) bytes
- Kernel: starts at 0x1000, 51998736 bytes (original)
- Ramdisk: starts after kernel, aligned to page_size
"""

import struct
import sys
import os

def make_boot_img(original_boot, new_kernel, output_boot):
    PAGE_SIZE = 4096

    with open(original_boot, 'rb') as f:
        original_data = f.read()

    with open(new_kernel, 'rb') as f:
        new_kernel_data = f.read()

    # Read original boot.img
    PAGE_SIZE = 4096

    with open(original_boot, 'rb') as f:
        original_data = f.read()

    with open(new_kernel, 'rb') as f:
        new_kernel_data = f.read()

    # Copy entire first page (header + cmdline), not just 64 bytes
    header_data = bytearray(original_data[:PAGE_SIZE])
    magic = header_data[0:4]
    assert magic == b'ANDR', f"Invalid boot image magic: {magic}"

    # Parse header
    kernel_size_orig = struct.unpack('<I', header_data[8:12])[0]
    ramdisk_size = struct.unpack('<I', header_data[16:20])[0]
    second_size = struct.unpack('<I', header_data[24:28])[0]
    page_size = struct.unpack('<I', header_data[36:40])[0]

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

    # Calculate offsets
    # Header: 1 page
    # Kernel: starts at page 1 (offset 0x1000)
    kernel_start = page_size
    kernel_pages = (kernel_size_orig + page_size - 1) // page_size
    kernel_end = kernel_start + kernel_size_orig

    # Ramdisk starts after kernel, aligned to page boundary
    ramdisk_start = kernel_start + kernel_size_orig
    # Round up to page boundary
    ramdisk_start = ((ramdisk_start + page_size - 1) // page_size) * page_size

    # Second starts after ramdisk
    second_start = ramdisk_start + ramdisk_size
    second_start = ((second_start + page_size - 1) // page_size) * page_size

    print(f"\nLayout:")
    print(f"  Header: 0x0 - 0x{kernel_start:x}")
    print(f"  Kernel: 0x{kernel_start:x} - 0x{kernel_end:x}")
    print(f"  Ramdisk: 0x{ramdisk_start:x} - 0x{ramdisk_start + ramdisk_size:x}")
    print(f"  Second: 0x{second_start:x}")

    # Build new boot image
    new_data = bytearray()

    # Copy full first page (header + cmdline), not just 64 bytes
    new_data.extend(header_data)

    # Kernel starts after first page
    kernel_start = page_size

    # Write new kernel (padded to original size)
    new_data.extend(new_kernel_padded)

    # Pad to ramdisk start (page boundary)
    new_data.extend(b'\x00' * (ramdisk_start - len(new_data)))

    # Copy ramdisk from original
    ramdisk_from_original = original_data[ramdisk_start:ramdisk_start + ramdisk_size]
    new_data.extend(ramdisk_from_original)

    # Pad to second start
    new_data.extend(b'\x00' * (second_start - len(new_data)))

    # Copy second from original (if any)
    if second_size > 0:
        second_from_original = original_data[second_start:second_start + second_size]
        new_data.extend(second_from_original)

    # Copy DTB section: search for DTB magic in original data
    DTB_MAGIC = b'\xd0\x0d\xfe\xed'
    dtb_start = original_data.find(DTB_MAGIC)
    dtb_size = 0
    dtb_data = b''
    if dtb_start > 0 and dtb_start + 8 <= len(original_data):
        dtb_size = struct.unpack('>I', original_data[dtb_start + 4:dtb_start + 8])[0]
        if dtb_start + dtb_size <= len(original_data):
            dtb_data = original_data[dtb_start:dtb_start + dtb_size]
            print(f"DTB: {dtb_size} bytes at 0x{dtb_start:x}")

    # Place DTB in new boot.img after ramdisk
    if len(dtb_data) > 0:
        new_dtb_start = (ramdisk_start + ramdisk_size + page_size - 1) // page_size * page_size
        new_data.extend(b'\x00' * (new_dtb_start - len(new_data)))
        new_data.extend(dtb_data)
        print(f"DTB: placed at 0x{new_dtb_start:x} ({dtb_size} bytes)")
    else:
        print("No DTB found")

    # Copy any remaining data after DTB from original (bootloader sig, padding, etc.)
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
        print(f"  Cmdline: {verify_cmdline[:120]}...")
        # Check if DTB is findable at expected offset
        with open(output_boot, 'rb') as f2:
            dtb_check = f2.read().find(b'\xd0\x0d\xfe\xed')
        if dtb_check >= 0:
            print(f"  DTB magic found at: 0x{dtb_check:x}")
        else:
            print("  WARNING: DTB magic not found in output!")

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <original_boot.img> <new_kernel> <output_boot.img>")
        sys.exit(1)

    make_boot_img(sys.argv[1], sys.argv[2], sys.argv[3])
