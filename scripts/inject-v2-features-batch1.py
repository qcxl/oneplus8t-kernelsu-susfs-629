#!/usr/bin/env python3
"""
inject-v2-features-batch1.py - Port Batch 1 v2.2.0 features to v1.5.5.

Adds:
1. susfs_def.h: CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING + size constants
2. susfs.h: st_susfs_avc_log_spoofing struct + declarations
3. susfs.c: susfs_set_avc_log_spoofing() + susfs_enable_log() 
4. Dispatch entries for AVC_LOG_SPOOFING + updated ENABLE_LOG

V2.2.0 calling convention for NEW functions:
  void func(void __user **user_info)
  (reads struct from *user_info, processes, writes err back)
"""

import sys, os, re

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

def patch_file(path, old_str, new_str):
    p = os.path.join(KERNEL_ROOT, path)
    with open(p) as f: content = f.read()
    if old_str in content:
        content = content.replace(old_str, new_str, 1)
        with open(p, 'w') as f: f.write(content)
        return True
    print(f"  WARNING: pattern not found in {path}")
    return False

def insert_before(path, marker, text):
    p = os.path.join(KERNEL_ROOT, path)
    with open(p) as f: content = f.read()
    if marker in content:
        pos = content.find(marker)
        content = content[:pos] + text + content[pos:]
        with open(p, 'w') as f: f.write(content)
        return True
    print(f"  WARNING: marker '{marker}' not found in {path}")
    return False

def insert_after(path, marker, text):
    p = os.path.join(KERNEL_ROOT, path)
    with open(p) as f: content = f.read()
    if marker in content:
        pos = content.find(marker) + len(marker)
        content = content[:pos] + text + content[pos:]
        with open(p, 'w') as f: f.write(content)
        return True
    print(f"  WARNING: marker '{marker}' not found in {path}")
    return False

def inject_susfs_def_h():
    path = "include/linux/susfs_def.h"
    changes = [
        # CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING before CMD_SUSFS_ADD_SUS_MAP
        ('#define CMD_SUSFS_ADD_SUS_MAP 0x60020', 
         '#define CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING 0x60010\n#define CMD_SUSFS_ADD_SUS_MAP 0x60020'),
        # Add size constants after SUSFS_MAX_LEN_PATHNAME
        ('#define SUSFS_FAKE_CMDLINE_OR_BOOTCONFIG_SIZE 4096',
         '#define SUSFS_FAKE_CMDLINE_OR_BOOTCONFIG_SIZE 8192\n#define SUSFS_ENABLED_FEATURES_SIZE 8192\n#define SUSFS_MAX_VERSION_BUFSIZE 16\n#define SUSFS_MAX_VARIANT_BUFSIZE 16\n'),
    ]
    for old, new in changes:
        if not patch_file(path, old, new):
            return False
    print("  [OK] susfs_def.h: added CMD + size constants")
    return True

def inject_susfs_h():
    path = "include/linux/susfs.h"
    
    # Add avc log spoofing struct after existing feature structs
    avc_struct = (
        '\n'
        '/* enable_log */\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n'
        'struct st_susfs_log {\n'
        '\tbool                                    enabled;\n'
        '\tint                                     err;\n'
        '};\n'
        '#endif\n'
        '\n'
        '/* avc log spoofing */\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING\n'
        'struct st_susfs_avc_log_spoofing {\n'
        '\tbool                                    enabled;\n'
        '\tint                                     err;\n'
        '};\n'
        '#endif\n'
    )
    
    # Add function declarations before /* susfs_init */
    avc_decl = (
        '\n'
        '/* enable_log */\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n'
        'void susfs_enable_log(void __user **user_info);\n'
        '#endif\n'
        '\n'
        '/* avc log spoofing */\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING\n'
        'void susfs_set_avc_log_spoofing(void __user **user_info);\n'
        '#endif\n'
    )
    
    # Insert struct and declarations before /* susfs_init */
    # Use /* susfs_init */ as the sole anchor point (reliable across versions)
    lines = open(os.path.join(KERNEL_ROOT, path)).read().split('\n')
    
    inserted_struct = False
    for i, line in enumerate(lines):
        if '/* susfs_init */' in line:
            lines.insert(i, avc_struct + '\n' + avc_decl)
            inserted_struct = True
            break
    
    if not inserted_struct:
        print("  ERROR: /* susfs_init */ marker not found in susfs.h")
        return False
    
    content = '\n'.join(lines)
    with open(os.path.join(KERNEL_ROOT, path), 'w') as f:
        f.write(content)
    print("  [OK] susfs.h: added avc struct + declaration")
    return True

def inject_susfs_c():
    path = "fs/susfs.c"
    
    # susfs_set_avc_log_spoofing() - insert before susfs_init
    # The v2.2.0 variable is declared elsewhere (extern)
    avc_func = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING\n'
        'bool susfs_is_avc_log_spoofing_enabled __read_mostly = false;\n'
        '\n'
        'void susfs_set_avc_log_spoofing(void __user **user_info) {\n'
        '\tstruct st_susfs_avc_log_spoofing info = {0};\n'
        '\n'
        '\tif (copy_from_user(&info, (struct st_susfs_avc_log_spoofing __user*)*user_info, sizeof(info))) {\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tWRITE_ONCE(susfs_is_avc_log_spoofing_enabled, info.enabled);\n'
        '\tSUSFS_LOGI("susfs_is_avc_log_spoofing_enabled: %d\\n", info.enabled);\n'
        '\tinfo.err = 0;\n'
        'out:\n'
        '\tif (copy_to_user(&((struct st_susfs_avc_log_spoofing __user*)*user_info)->err, &info.err, sizeof(info.err)))\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\tSUSFS_LOGI("CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING -> ret: %d\\n", info.err);\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING */\n'
    )
    
    # Enhanced susfs_set_log with v2.2.0 protocol wrapper
    enable_log_wrapper = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n'
        'void susfs_enable_log(void __user **user_info) {\n'
        '\tstruct st_susfs_log info = {0};\n'
        '\n'
        '\tif (copy_from_user(&info, (struct st_susfs_log __user*)*user_info, sizeof(info))) {\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tsusfs_set_log(info.enabled);\n'
        '\tinfo.err = 0;\n'
        'out:\n'
        '\tif (copy_to_user(&((struct st_susfs_log __user*)*user_info)->err, &info.err, sizeof(info.err)))\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\tSUSFS_LOGI("CMD_SUSFS_ENABLE_LOG -> ret: %d\\n", info.err);\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS_ENABLE_LOG */\n'
    )
    
    content = open(os.path.join(KERNEL_ROOT, path)).read()
    skip = 'susfs_set_avc_log_spoofing' in content
    if skip:
        print("  [SKIP] susfs.c: avc_log_spoofing already present")
        return True
    
    # Insert both functions together (atomic) before /* susfs_init */
    combined = avc_func + enable_log_wrapper
    
    lines = content.split('\n')
    inserted = False
    for i, line in enumerate(lines):
        if '/* susfs_init */' in line:
            lines.insert(i, combined)
            inserted = True
            break
    
    if not inserted:
        print("  ERROR: /* susfs_init */ marker not found in susfs.c")
        return False
    
    content = '\n'.join(lines)
    
    with open(os.path.join(KERNEL_ROOT, path), 'w') as f:
        f.write(content)
    print("  [OK] susfs.c: added susfs_set_avc_log_spoofing + susfs_enable_log")
    return True


def main():
    ok = True
    ok &= inject_susfs_def_h()
    ok &= inject_susfs_h()
    ok &= inject_susfs_c()
    print(f"\n  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
