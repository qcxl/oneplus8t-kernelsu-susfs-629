#!/usr/bin/env python3
"""
inject-susfs-sus-map.py - Port sus_map feature from SUSFS v2.2.0 to v1.5.5.

Adds:
1. INODE_STATE_SUS_MAP flag + CMD to include/linux/susfs_def.h
2. struct st_susfs_sus_map + declaration to include/linux/susfs.h
3. susfs_add_sus_map() implementation to fs/susfs.c
4. SUS_MAP early-return hook to fs/proc/task_mmu.c show_map_vma()

Usage: python3 inject-susfs-sus-map.py <kernel-root>
"""

import sys, os, re


def add_after_last_endif(lines, text_block):
    """Append text_block before the last #endif in lines list (which closes the include guard)."""
    last_endif = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('#endif'):
            last_endif = i
    if last_endif < 0:
        return False
    lines.insert(last_endif, text_block)
    return True


def inject_susfs_def_h(root):
    """Add INODE_STATE_SUS_MAP and CMD_SUSFS_ADD_SUS_MAP to susfs_def.h"""
    path = os.path.join(root, "include/linux/susfs_def.h")
    if not os.path.exists(path):
        print("  ERROR: susfs_def.h not found")
        return False

    with open(path) as f:
        content = f.read()
    if 'INODE_STATE_SUS_MAP' in content:
        print("  susfs_def.h: already has SUS_MAP, skipping")
        return True

    lines = content.split('\n')
    # Add INODE_STATE_SUS_MAP after INODE_STATE_OPEN_REDIRECT
    for i, line in enumerate(lines):
        if 'INODE_STATE_OPEN_REDIRECT' in line:
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i + 1, f'{indent}#define INODE_STATE_SUS_MAP BIT(28)')
            break

    # Add CMD_SUSFS_ADD_SUS_MAP before the last CMD (CMD_SUSFS_SUS_SU)
    for i, line in enumerate(lines):
        if 'CMD_SUSFS_SUS_SU' in line and 'define' in line:
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i, f'{indent}#define CMD_SUSFS_ADD_SUS_MAP 0x60020')
            break

    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print("  susfs_def.h: added INODE_STATE_SUS_MAP + CMD_SUSFS_ADD_SUS_MAP")
    return True


def inject_susfs_h(root):
    """Add struct st_susfs_sus_map and function declaration to susfs.h"""
    path = os.path.join(root, "include/linux/susfs.h")
    if not os.path.exists(path):
        print("  ERROR: susfs.h not found")
        return False

    with open(path) as f:
        content = f.read()
    if 'SUS_MAP' in content:
        print("  susfs.h: already has SUS_MAP, skipping")
        return True

    # Add struct after the last existing feature struct (open_redirect)
    struct_block = (
        '\n'
        '/* sus_map */\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        'struct st_susfs_sus_map {\n'
        '\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n'
        '\tint                              err;\n'
        '};\n'
        '#endif\n'
    )
    lines = content.split('\n')
    # Find the comment "/* open_redirect */" and insert after its #endif
    marker = '#endif // #ifdef CONFIG_KSU_SUSFS_SUS_SU'
    inserted = False
    for i, line in enumerate(lines):
        if marker in line:
            lines.insert(i + 1, struct_block)
            inserted = True
            break
    if not inserted:
        # Fallback: insert before last #endif
        for i, line in enumerate(lines):
            if line.strip() == '#endif' and i > len(lines) * 0.8:
                lines.insert(i, struct_block)
                inserted = True
                break

    # Add function declaration after the struct block
    decl = (
        '\n'
        '/* sus_map */\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        'void susfs_add_sus_map(void __user **user_info);\n'
        '#endif\n'
    )
    for i, line in enumerate(lines):
        if '/* susfs_init */' in line:
            lines.insert(i, decl)
            break

    content = '\n'.join(lines)
    with open(path, 'w') as f:
        f.write(content)
    print("  susfs.h: added struct + declaration")
    return True


def inject_susfs_c(root):
    """Add susfs_add_sus_map() implementation to fs/susfs.c before susfs_init()"""
    path = os.path.join(root, "fs/susfs.c")
    if not os.path.exists(path):
        print("  ERROR: susfs.c not found")
        return False

    with open(path) as f:
        content = f.read()
    if 'SUS_MAP' in content:
        print("  susfs.c: already has SUS_MAP, skipping")
        return True

    func_code = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        'void susfs_add_sus_map(void __user **user_info) {\n'
        '\tstruct st_susfs_sus_map info = {0};\n'
        '\tstruct path path;\n'
        '\tstruct inode *inode = NULL;\n'
        '\n'
        '\tif (copy_from_user(&info, (struct st_susfs_sus_map __user*)*user_info, sizeof(info))) {\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tinfo.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);\n'
        '\tif (info.err) {\n'
        '\t\tSUSFS_LOGE("Failed opening file \'%s\'\\n", info.target_pathname);\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tinode = d_backing_inode(path.dentry);\n'
        '\tif (!inode) {\n'
        '\t\tSUSFS_LOGE("inode is NULL\\n");\n'
        '\t\tinfo.err = -ENOENT;\n'
        '\t\tgoto out_path_put;\n'
        '\t}\n'
        '\tinode->i_state |= INODE_STATE_SUS_MAP;\n'
        '\tSUSFS_LOGI("pathname: \'%s\', flagged as SUS_MAP\\n", info.target_pathname);\n'
        '\tinfo.err = 0;\n'
        '\nout_path_put:\n'
        '\tpath_put(&path);\n'
        'out:\n'
        '\tif (copy_to_user(&((struct st_susfs_sus_map __user*)*user_info)->err, &info.err, sizeof(info.err)))\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\tSUSFS_LOGI("CMD_SUSFS_ADD_SUS_MAP -> ret: %d\\n", info.err);\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS_SUS_MAP */\n'
    )

    # Insert before "/* susfs_init */"
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if '/* susfs_init */' in line.strip():
            lines.insert(i, func_code)
            break

    content = '\n'.join(lines)
    with open(path, 'w') as f:
        f.write(content)
    print("  susfs.c: added susfs_add_sus_map()")
    return True


def inject_task_mmu(root):
    """Add SUS_MAP early-return hook to show_map_vma() in task_mmu.c"""
    path = os.path.join(root, "fs/proc/task_mmu.c")
    if not os.path.exists(path):
        print("  ERROR: task_mmu.c not found")
        return False

    with open(path) as f:
        content = f.read()
    if 'SUS_MAP' in content:
        print("  task_mmu.c: already has SUS_MAP, skipping")
        return True

    # 1. Add include <linux/susfs_def.h> after existing includes (for SUS_MAP macros)
    include_line = '#include <linux/mm_inline.h>'
    susfs_include = '#include <linux/susfs_def.h>'
    if susfs_include not in content:
        content = content.replace(include_line, include_line + '\n' + susfs_include)

    # 2. Add static inline for SUS_MAP check before show_map_vma
    #    (mimics SUSFS_IS_INODE_SUS_MAP but without v2.2.0 dependencies)
    check_func = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        'static inline bool susfs_is_sus_map_inode(struct inode *inode)\n'
        '{\n'
        '\treturn inode && unlikely(inode->i_state & INODE_STATE_SUS_MAP);\n'
        '}\n'
        '#endif\n'
        '\n'
    )
    lines = content.split('\n')
    marker = 'static void\nshow_map_vma(struct seq_file *m, struct vm_area_struct *vma)'
    for i, line in enumerate(lines):
        if marker in line:
            lines.insert(i, check_func)
            break

    # 3. Add early return inside show_map_vma, after 'file = vma->vm_file'
    #    but before 'if (file) {'
    hook = (
        '\tif (file) {\n'
        '\t\tstruct inode *inode = file_inode(vma->vm_file);\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        '\t\tif (susfs_is_sus_map_inode(inode))\n'
        '\t\t\treturn;\n'
        '#endif\n'
    )
    content = '\n'.join(lines)
    # Find 'if (file) {' and replace it with our hook version
    # But be careful: there are TWO 'if (file) {' blocks in show_map_vma
    # The first one (with dev/ino computation) is what we want
    old_block = (
        '\tif (file) {\n'
        '\t\tstruct inode *inode = file_inode(vma->vm_file);\n'
        '\t\tdev = inode->i_sb->s_dev;\n'
    )
    if old_block in content:
        content = content.replace(old_block, hook, 1)

    with open(path, 'w') as f:
        f.write(content)
    print("  task_mmu.c: added SUS_MAP hook to show_map_vma()")
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"ERROR: {root} not a directory")
        sys.exit(1)

    print(f"[SUSFS sus_map] target={root}")
    ok = True
    ok &= inject_susfs_def_h(root)
    ok &= inject_susfs_h(root)
    ok &= inject_susfs_c(root)
    ok &= inject_task_mmu(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
